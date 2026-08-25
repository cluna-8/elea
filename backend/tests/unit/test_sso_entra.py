"""`EntraProvider` — OIDC authorization code + discovery contra un IdP Entra simulado.

Spec 017 US2, T014. Cada test de la sección (b) prueba UNO de los 5 invariantes de seguridad
del brief y está escrito para romper si se saca el check correspondiente (verificado a mano
sacando cada guardia un momento — ver el cuerpo del PR).

Mocking: sin respx/pytest-httpx (no están en el repo, y el brief pide no agregarlos).
`httpx.MockTransport` (ya en httpx 0.28.1) sirve el discovery doc + JWKS + token endpoint;
`python-jose` (ya pineado) firma los id_token de prueba con un par RSA generado con
`cryptography` (ya pineada). Todo el mocking vive ACÁ — nada en `conftest.py`.
"""
import base64
import hashlib
import hmac
import json
import logging
import time

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt as jose_jwt

from src.sso.entra import EntraProvider, SsoDiscoveryError, SsoTokenExchangeError

TENANT_ID = "test-tenant-id-4242"
CLIENT_ID = "test-client-id-9999"
CLIENT_SECRET = "s3cr3t-do-not-leak-4b7f9c2e"  # noqa: S105 — literal de test, buscado en asserts
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"
AUTH_ENDPOINT = "https://mock-idp.test/oauth2/v2.0/authorize"
TOKEN_ENDPOINT = "https://mock-idp.test/oauth2/v2.0/token"
JWKS_URI = "https://mock-idp.test/discovery/v2.0/keys"
KID = "test-kid-1"
REDIRECT_URI = "https://cliente.example/api/v1/auth/sso/callback"


def _config(**overrides) -> dict:
    base = {"tenant_id": TENANT_ID, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════════════════
# Par RSA de test + JWKS + firma de id_tokens (python-jose, sobre cryptography)
# ═══════════════════════════════════════════════════════════════════════════════════


def _b64url_uint(n: int) -> str:
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _generar_par_rsa_y_jwks(kid: str = KID):
    clave_privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem_privado = clave_privada.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    numeros_publicos = clave_privada.public_key().public_numbers()
    jwks = {
        "keys": [{
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": kid,
            "n": _b64url_uint(numeros_publicos.n),
            "e": _b64url_uint(numeros_publicos.e),
        }]
    }
    return pem_privado, jwks


def _firmar_id_token(pem_privado: str, kid: str, claims: dict) -> str:
    return jose_jwt.encode(claims, pem_privado, algorithm="RS256", headers={"kid": kid})


def _b64u_json(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


def _jwt_alg_none(claims: dict) -> str:
    """Arma un id_token `{"alg":"none"}` a mano: header.payload. con firma VACÍA — el ataque
    clásico contra librerías JWT sin allowlist de algoritmos (CVE-2015-2951 y descendientes).
    No pasa por python-jose/authlib al firmarlo — no hay nada que firmar."""
    header = {"alg": "none", "typ": "JWT"}
    return f"{_b64u_json(header)}.{_b64u_json(claims)}."


def _clave_publica_pem(pem_privado: str) -> bytes:
    clave = serialization.load_pem_private_key(pem_privado.encode(), password=None)
    return clave.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _jwt_confusion_hs256_con_clave_publica(claims: dict, clave_publica_pem: bytes) -> str:
    """Ataque de confusión de algoritmo: el IdP firma con RSA (RS256, asimétrico — la clave
    PÚBLICA sólo sirve para VERIFICAR, jamás para firmar). Un atacante que consigue esa clave
    pública (es pública, está en el JWKS) arma un token `alg=HS256` y lo "firma" usando esos
    mismos bytes PEM como si fueran un secreto HMAC compartido. Contra una librería que resuelva
    el algoritmo de verificación por lo que el TOKEN declara (en vez de por una allowlist fija
    del lado del verificador), el HMAC "valida" porque el verificador usa la MISMA clave — sin
    que el atacante haya necesitado jamás la clave privada. Construido crudo con `hmac`/`hashlib`
    a propósito: no depende de que authlib/python-jose "dejen" firmar así (no van a dejar) — un
    atacante real arma los bytes del JWT él mismo, sin pedirle permiso a ninguna librería."""
    header = {"alg": "HS256", "typ": "JWT"}
    firmante = f"{_b64u_json(header)}.{_b64u_json(claims)}"
    firma = hmac.new(clave_publica_pem, firmante.encode(), hashlib.sha256).digest()
    firma_b64 = base64.urlsafe_b64encode(firma).rstrip(b"=").decode()
    return f"{firmante}.{firma_b64}"


def _tocar_bytes_de_la_firma(token: str) -> str:
    """Cambia UN BIT real de los bytes de la firma (no sólo el símbolo base64 de superficie).

    Tocar directamente el último carácter base64url del segmento de firma es engañoso: ese
    carácter final codifica, junto al padding implícito de base64, algunos bits que varios
    decoders (incluido el que usa authlib) descartan sin más — cambiar `'A'` por `'B'` puede
    no mover ni un bit del valor decodificado (falso negativo intermitente, lo until medí en
    vivo armando este test: ~1 corrida cada 16 no tocaba nada real). Decodificar a bytes,
    invertir el primer byte y re-codificar es la única forma de garantizar una firma
    CRIPTOGRÁFICAMENTE distinta en el 100% de las corridas.
    """
    encabezado, payload, firma = token.split(".")
    firma_bytes = bytearray(base64.urlsafe_b64decode(firma + "=" * (-len(firma) % 4)))
    firma_bytes[0] ^= 0xFF
    firma_tocada = base64.urlsafe_b64encode(bytes(firma_bytes)).rstrip(b"=").decode()
    return f"{encabezado}.{payload}.{firma_tocada}"


def _claims_validos(**overrides) -> dict:
    ahora = int(time.time())
    base = {
        "iss": AUTHORITY,
        "aud": CLIENT_ID,
        "sub": "entra-subject-abc123",
        "email": "usuaria@cliente.example",
        "name": "Usuaria de Prueba",
        "nonce": "nonce-del-pedido",
        "iat": ahora,
        "exp": ahora + 3600,
        # Claims que un IdP real manda y el contrato exige DESCARTAR (Identity es lo mínimo).
        "roles": ["Directory.Read.All"],
        "groups": ["grupo-admin-idp"],
        "tid": TENANT_ID,
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════════════════
# MockTransport: sirve discovery + JWKS + token endpoint por path
# ═══════════════════════════════════════════════════════════════════════════════════


def _proveedor_mockeado(
    *,
    jwks: dict,
    id_token: str | None,
    discovery_status: int = 200,
    jwks_status: int = 200,
    token_status: int = 200,
    discovery_overrides: dict | None = None,
    token_error_json: dict | None = None,
    token_error_text: str | None = None,
) -> EntraProvider:
    discovery_doc = {
        "issuer": AUTHORITY,
        "authorization_endpoint": AUTH_ENDPOINT,
        "token_endpoint": TOKEN_ENDPOINT,
        "jwks_uri": JWKS_URI,
    }
    if discovery_overrides is not None:
        discovery_doc = discovery_overrides

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            if discovery_status != 200:
                return httpx.Response(discovery_status, json={"error": "discovery_down"})
            return httpx.Response(200, json=discovery_doc)
        if path.endswith("/keys"):
            if jwks_status != 200:
                return httpx.Response(jwks_status, json={"error": "jwks_down"})
            return httpx.Response(200, json=jwks)
        if path.endswith("/token"):
            if token_status != 200:
                # #294: los tests de esta sección necesitan el documento de error TAL CUAL lo
                # manda Entra (o algo que no sea JSON); el default de siempre se mantiene para
                # no tocar los tests que ya existían.
                if token_error_text is not None:
                    return httpx.Response(
                        token_status, text=token_error_text,
                        headers={"content-type": "text/html; charset=utf-8"},
                    )
                return httpx.Response(
                    token_status, json=token_error_json or {"error": "token_endpoint_down"}
                )
            return httpx.Response(200, json={
                "token_type": "Bearer",
                "access_token": "access-token-no-usado-por-el-contrato",
                "id_token": id_token,
            })
        return httpx.Response(404, json={"error": f"mock transport: path sin ruta {path!r}"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return EntraProvider(http_client=client)


def _exchange(proveedor: EntraProvider, *, nonce: str = "nonce-del-pedido", config: dict | None = None):
    return proveedor.exchange_code(
        config or _config(), "auth-code-de-prueba", nonce=nonce, redirect_uri=REDIRECT_URI
    )


# ═══════════════════════════════════════════════════════════════════════════════════
# (a) Contrato: authorize_url y discovery
# ═══════════════════════════════════════════════════════════════════════════════════


def test_authorize_url_incluye_state_nonce_response_type_y_redirect_uri_tal_cual():
    """Regla dura 6 del contrato."""
    from urllib.parse import parse_qs, urlparse

    _, jwks = _generar_par_rsa_y_jwks()
    proveedor = _proveedor_mockeado(jwks=jwks, id_token=None)

    url = proveedor.authorize_url(
        _config(), "state-opaco-xyz", nonce="nonce-opaco-abc", redirect_uri=REDIRECT_URI
    )

    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == AUTH_ENDPOINT
    qs = parse_qs(parsed.query)
    assert qs["state"] == ["state-opaco-xyz"]
    assert qs["nonce"] == ["nonce-opaco-abc"]
    assert qs["response_type"] == ["code"]
    assert qs["redirect_uri"] == [REDIRECT_URI]
    assert qs["client_id"] == [CLIENT_ID]


def test_discovery_caida_levanta_excepcion_clara_no_degrada_en_silencio():
    """Regla dura 7 del contrato: un fallo de discovery es una excepción, no un login que
    sigue de largo sin verificar nada."""
    _, jwks = _generar_par_rsa_y_jwks()
    proveedor = _proveedor_mockeado(jwks=jwks, id_token=None, discovery_status=503)

    with pytest.raises(SsoDiscoveryError):
        proveedor.authorize_url(_config(), "s", nonce="n", redirect_uri=REDIRECT_URI)


def test_discovery_sin_campos_obligatorios_levanta_excepcion_clara():
    _, jwks = _generar_par_rsa_y_jwks()
    proveedor = _proveedor_mockeado(
        jwks=jwks, id_token=None,
        discovery_overrides={"issuer": AUTHORITY},  # faltan authorization/token/jwks
    )

    with pytest.raises(SsoDiscoveryError):
        proveedor.authorize_url(_config(), "s", nonce="n", redirect_uri=REDIRECT_URI)


def test_jwks_caido_levanta_excepcion_clara():
    pem_privado, jwks = _generar_par_rsa_y_jwks()
    id_token = _firmar_id_token(pem_privado, KID, _claims_validos())
    proveedor = _proveedor_mockeado(jwks=jwks, id_token=id_token, jwks_status=500)

    with pytest.raises(SsoDiscoveryError):
        _exchange(proveedor)


def test_intercambio_code_token_feliz_devuelve_identity_minima_y_descarta_claims_extra():
    """`Identity` es lo MÍNIMO — `roles`/`groups`/`tid` del id_token (claims reales que Entra
    manda) NO tienen que sobrevivir al contrato."""
    pem_privado, jwks = _generar_par_rsa_y_jwks()
    id_token = _firmar_id_token(pem_privado, KID, _claims_validos())
    proveedor = _proveedor_mockeado(jwks=jwks, id_token=id_token)

    identidad = _exchange(proveedor)

    assert identidad == {
        "email": "usuaria@cliente.example",
        "subject": "entra-subject-abc123",
        "display_name": "Usuaria de Prueba",
    }
    assert set(identidad.keys()) == {"email", "subject", "display_name"}


# ═══════════════════════════════════════════════════════════════════════════════════
# (b) Los 5 invariantes de seguridad — cada uno rompe si se saca su guardia
# ═══════════════════════════════════════════════════════════════════════════════════


def test_invariante_1_firma_manipulada_se_rechaza():
    """La firma se verifica contra el JWKS del IdP. Un id_token con la firma tocada en
    tránsito (bit-flip real sobre los bytes decodificados) tiene que ser RECHAZADO, nunca
    decodificado sin verificar."""
    pem_privado, jwks = _generar_par_rsa_y_jwks()
    id_token = _firmar_id_token(pem_privado, KID, _claims_validos())
    token_manipulado = _tocar_bytes_de_la_firma(id_token)
    assert token_manipulado != id_token

    proveedor = _proveedor_mockeado(jwks=jwks, id_token=token_manipulado)

    with pytest.raises(SsoTokenExchangeError):
        _exchange(proveedor)


def test_invariante_1b_firmado_con_una_clave_que_no_es_la_del_jwks_se_rechaza():
    """Variante del ataque: el atacante firma con SU PROPIA clave privada pero reusa el `kid`
    legítimo. Sin verificación real de firma (o con `verify=False`) esto pasaría."""
    pem_privado_legitimo, jwks = _generar_par_rsa_y_jwks()
    pem_privado_atacante, _ = _generar_par_rsa_y_jwks(kid=KID)
    assert pem_privado_atacante != pem_privado_legitimo

    id_token_forjado = _firmar_id_token(pem_privado_atacante, KID, _claims_validos())
    proveedor = _proveedor_mockeado(jwks=jwks, id_token=id_token_forjado)

    with pytest.raises(SsoTokenExchangeError):
        _exchange(proveedor)


def test_invariante_2a_issuer_que_no_corresponde_se_rechaza():
    pem_privado, jwks = _generar_par_rsa_y_jwks()
    id_token = _firmar_id_token(
        pem_privado, KID, _claims_validos(iss="https://login.microsoftonline.com/OTRO-TENANT/v2.0")
    )
    proveedor = _proveedor_mockeado(jwks=jwks, id_token=id_token)

    with pytest.raises(SsoTokenExchangeError):
        _exchange(proveedor)


def test_invariante_2b_audience_distinto_del_client_id_se_rechaza():
    pem_privado, jwks = _generar_par_rsa_y_jwks()
    id_token = _firmar_id_token(pem_privado, KID, _claims_validos(aud="client-id-de-otro-tenant"))
    proveedor = _proveedor_mockeado(jwks=jwks, id_token=id_token)

    with pytest.raises(SsoTokenExchangeError):
        _exchange(proveedor)


def test_invariante_3_nonce_distinto_del_pedido_se_rechaza():
    """El nonce del id_token tiene que coincidir con el que `exchange_code` recibió — no es
    un claim JWT registrado, así que si se saca el chequeo manual nada más lo protege."""
    pem_privado, jwks = _generar_par_rsa_y_jwks()
    id_token = _firmar_id_token(pem_privado, KID, _claims_validos(nonce="nonce-que-el-idp-devolvio"))
    proveedor = _proveedor_mockeado(jwks=jwks, id_token=id_token)

    with pytest.raises(SsoTokenExchangeError):
        _exchange(proveedor, nonce="nonce-que-esperaba-el-callback")


def test_invariante_4_id_token_vencido_se_rechaza():
    pem_privado, jwks = _generar_par_rsa_y_jwks()
    ahora = int(time.time())
    id_token = _firmar_id_token(
        pem_privado, KID, _claims_validos(iat=ahora - 7200, exp=ahora - 3600)
    )
    proveedor = _proveedor_mockeado(jwks=jwks, id_token=id_token)

    with pytest.raises(SsoTokenExchangeError):
        _exchange(proveedor)


def test_invariante_5_el_secreto_no_aparece_en_la_excepcion_ni_en_los_logs(caplog):
    """Se provoca un error de exchange (token endpoint caído) CON un client_secret conocido en
    la config, y se busca ese literal tanto en el texto de la excepción como en todo lo que
    `caplog` haya capturado (root logger, incluida la propia bitácora interna de httpx)."""
    pem_privado, jwks = _generar_par_rsa_y_jwks()
    id_token = _firmar_id_token(pem_privado, KID, _claims_validos())
    proveedor = _proveedor_mockeado(jwks=jwks, id_token=id_token, token_status=500)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(SsoTokenExchangeError) as excinfo:
            _exchange(proveedor)

    texto_excepcion = "".join(
        str(x) for x in (excinfo.value, excinfo.value.__cause__, excinfo.traceback)
    )
    assert CLIENT_SECRET not in texto_excepcion
    assert CLIENT_SECRET not in caplog.text


def test_invariante_5b_el_secreto_no_aparece_ni_en_el_camino_feliz_seguido_de_un_id_token_invalido(caplog):
    """Contracara: el POST al token endpoint SÍ sale bien (el secreto viajó, como debe), pero
    el id_token resultante es inválido (firma manipulada). El secreto sigue sin poder aparecer
    en la excepción de validación ni en los logs."""
    pem_privado, jwks = _generar_par_rsa_y_jwks()
    id_token = _firmar_id_token(pem_privado, KID, _claims_validos())
    token_manipulado = _tocar_bytes_de_la_firma(id_token)
    assert token_manipulado != id_token
    proveedor = _proveedor_mockeado(jwks=jwks, id_token=token_manipulado)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(SsoTokenExchangeError) as excinfo:
            _exchange(proveedor)

    assert CLIENT_SECRET not in str(excinfo.value)
    assert CLIENT_SECRET not in caplog.text


# ═══════════════════════════════════════════════════════════════════════════════════
# (c) P1 post-#260 (Jeff, sonda de ataque en vivo): allowlist de algoritmo
#
# `authlib.jose.jwt` (el objeto de módulo, ya sacado de este archivo) no tiene allowlist de
# `alg` — decodifica con lo que el TOKEN declara, `none` incluido. Los 5 invariantes de la
# sección (b) validan CONTENIDO (firma correcta para el `alg` dado, iss/aud/exp/nonce) pero
# ninguno fija el ALGORITMO — un atacante que elige su propio `alg` se salta la sección (b)
# entera. El fix es `JsonWebToken(["RS256"])`; estos tres tests rompen sin él.
# ═══════════════════════════════════════════════════════════════════════════════════


def test_invariante_6_alg_none_se_rechaza():
    """El bypass que reportó Jeff: id_token SIN FIRMA (`alg=none`), con claims elegidos por el
    atacante — email, subject, todo. Sin allowlist, `claims.validate()` los aprueba contento
    porque el contenido es "válido" a propósito."""
    _, jwks = _generar_par_rsa_y_jwks()
    id_token_hostil = _jwt_alg_none(_claims_validos())
    proveedor = _proveedor_mockeado(jwks=jwks, id_token=id_token_hostil)

    with pytest.raises(SsoTokenExchangeError):
        _exchange(proveedor)


def test_invariante_6b_confusion_hs256_con_clave_publica_rsa_se_rechaza():
    """El IdP firma RS256 (asimétrico). Un atacante que tiene la clave PÚBLICA (está en el
    JWKS, es pública por diseño) arma un token `alg=HS256` "firmado" usando esos bytes como
    secreto HMAC compartido — sin haber tocado jamás la clave privada. Construido crudo con
    `hmac`/`hashlib`, no con authlib/python-jose: no se depende de que la librería "permita"
    firmar así, un atacante real no le pide permiso a ninguna librería."""
    pem_privado, jwks = _generar_par_rsa_y_jwks()
    clave_publica = _clave_publica_pem(pem_privado)
    id_token_confundido = _jwt_confusion_hs256_con_clave_publica(_claims_validos(), clave_publica)
    proveedor = _proveedor_mockeado(jwks=jwks, id_token=id_token_confundido)

    with pytest.raises(SsoTokenExchangeError):
        _exchange(proveedor)


def test_invariante_6c_alg_rs512_fuera_de_la_allowlist_se_rechaza():
    """Pin de que la allowlist manda y no "cualquier RS* con firma válida": el token está
    firmado de verdad, con la clave privada LEGÍTIMA, criptográficamente correcto para RS512 —
    y aun así se rechaza porque el IdP (Entra) firma RS256 y sólo eso está permitido."""
    pem_privado, jwks = _generar_par_rsa_y_jwks()
    id_token_rs512 = jose_jwt.encode(
        _claims_validos(), pem_privado, algorithm="RS512", headers={"kid": KID}
    )
    proveedor = _proveedor_mockeado(jwks=jwks, id_token=id_token_rs512)

    with pytest.raises(SsoTokenExchangeError):
        _exchange(proveedor)


# ═══════════════════════════════════════════════════════════════════════════════════
# (d) #294: la causa del fallo tiene que sobrevivir hasta el log de la sede
#
# Los dos cuerpos de error de esta sección NO son inventados: son los que devolvió el tenant
# Entra real (`d37d0dde-…`) el 25-ago-2026, sondeado con un `client_secret` deliberadamente
# inválido — el secreto real nunca entró en la sonda. Sólo se les cambiaron los identificadores
# (trace/correlation) por literales que los tests puedan buscar:
#
#   grant_type=client_credentials  → 401 {"error":"invalid_client","error_codes":[7000215],
#                                         "error_description":"AADSTS7000215: Invalid client
#                                         secret provided…"}
#   grant_type=authorization_code  → 400 {"error":"invalid_grant","error_codes":[9002313],
#                                         "error_description":"AADSTS9002313: Invalid request.
#                                         Request is malformed or invalid…"}
#
# De paso quedó medido algo que importa para diagnosticar: Entra valida la FORMA del `code`
# ANTES que el secreto — con un code inventado contesta `invalid_grant` sea cual sea el secreto,
# incluido uno inválido. O sea que **el canje real es el único camino que ejercita el secreto**,
# justo el que este bloque hace legible. (Un `code` bien formado pero ya canjeado da otro AADSTS
# de la misma familia `invalid_grant`; ése no se pudo medir sin un login real y no se afirma.)
# ═══════════════════════════════════════════════════════════════════════════════════


def _error_entra(codigo: str, aadsts: int, descripcion: str) -> dict:
    """Documento de error con TODOS los campos que manda Entra, no sólo los dos que se usan —
    los que NO se transcriben tienen que estar presentes para que los tests puedan buscarlos."""
    return {
        "error": codigo,
        "error_codes": [aadsts],
        "error_description": descripcion,
        "error_uri": "https://login.microsoftonline.com/error?code=" + str(aadsts),
        "correlation_id": "c0rr3l4t-1d-del-tenant-0001",
        "trace_id": "tr4c3-1d-del-tenant-0001",
        "timestamp": "2026-08-25 11:20:33Z",
    }


_SECRETO_VENCIDO = _error_entra(
    "invalid_client", 7000215,
    "AADSTS7000215: Invalid client secret provided. Ensure the secret being sent in the "
    "request is the client secret value. Trace ID: tr4c3-1d-del-tenant-0001 "
    "Correlation ID: c0rr3l4t-1d-del-tenant-0001",
)
_CODE_INVALIDO = _error_entra(
    "invalid_grant", 9002313,
    "AADSTS9002313: Invalid request. Request is malformed or invalid. Trace ID: "
    "tr4c3-1d-del-tenant-0001 Correlation ID: c0rr3l4t-1d-del-tenant-0001",
)


def _mensaje_del_canje(cuerpo: dict | None, status: int, *, texto: str | None = None) -> str:
    pem_privado, jwks = _generar_par_rsa_y_jwks()
    id_token = _firmar_id_token(pem_privado, KID, _claims_validos())
    proveedor = _proveedor_mockeado(
        jwks=jwks, id_token=id_token, token_status=status,
        token_error_json=cuerpo, token_error_text=texto,
    )
    with pytest.raises(SsoTokenExchangeError) as excinfo:
        _exchange(proveedor)
    return str(excinfo.value)


def test_294_el_secreto_vencido_deja_su_codigo_y_su_AADSTS_en_el_mensaje():
    """El caso que le cuesta un día a la sede: el `client_secret` venció (los de Entra vencen a
    los 6/12/24 meses) y el SSO se cae para todo el mundo a la vez. `AADSTS7000215` es lo que
    convierte el log en una instrucción: rotar el secreto."""
    mensaje = _mensaje_del_canje(_SECRETO_VENCIDO, 401)

    assert "401" in mensaje
    assert "invalid_client" in mensaje
    assert "7000215" in mensaje


def test_294_el_code_rechazado_deja_el_suyo():
    mensaje = _mensaje_del_canje(_CODE_INVALIDO, 400)

    assert "400" in mensaje
    assert "invalid_grant" in mensaje
    assert "9002313" in mensaje


def test_294_los_dos_fallos_dejan_mensajes_DISTINTOS():
    """EL test de este issue. Los dos casos de arriba tienen dueños distintos —uno se arregla
    rotando el secreto, el otro no se arregla porque no está roto— y hasta este fix dejaban la
    MISMA línea en el log (`…falló con el IdP (HTTPStatusError)`), porque lo único que se
    conservaba era el tipo de la excepción y los dos llegan como `HTTPStatusError`."""
    por_secreto = _mensaje_del_canje(_SECRETO_VENCIDO, 401)
    por_code = _mensaje_del_canje(_CODE_INVALIDO, 400)

    assert por_secreto != por_code


def test_294_la_descripcion_y_los_identificadores_del_tenant_NO_se_transcriben():
    """`error_description` la redacta el IdP en texto libre y viene con Trace ID y Correlation
    ID adentro (medido contra el tenant real). Al log va el código, no el párrafo."""
    mensaje = _mensaje_del_canje(_SECRETO_VENCIDO, 401)

    assert "Trace ID" not in mensaje
    assert "tr4c3-1d-del-tenant-0001" not in mensaje
    assert "c0rr3l4t-1d-del-tenant-0001" not in mensaje
    assert "Ensure the secret being sent" not in mensaje


def test_294_un_error_con_salto_de_linea_no_puede_partir_la_linea_del_log():
    """El valor lo redacta quien contesta del otro lado de la red. Si `error` entrara crudo, un
    `\\n` adentro escribe una segunda línea en el log de la sede con contenido de un tercero."""
    cuerpo = dict(_SECRETO_VENCIDO)
    cuerpo["error"] = "invalid_client\nERROR [auth] sesion administrativa concedida a atacante"

    mensaje = _mensaje_del_canje(cuerpo, 401)

    assert "\n" not in mensaje
    assert "sesion administrativa" not in mensaje
    assert "401" in mensaje  # el status es nuestro y se conserva igual


def test_294_ni_siquiera_un_salto_de_linea_AL_FINAL_del_codigo_pasa():
    """El borde exacto que se me coló al escribir el guard: en Python `$` matchea también JUSTO
    ANTES de un `\\n` final, así que `^[a-z_]{1,40}$` deja pasar `"invalid_client\\n"` y el salto
    termina igual en el log. Este test rompe con `match`+`$` y pasa con `fullmatch` — es la
    única diferencia observable entre los dos, y el test de arriba (payload DESPUÉS del salto)
    no la ve porque ahí `$` tampoco matchea."""
    cuerpo = dict(_SECRETO_VENCIDO)
    cuerpo["error"] = "invalid_client\n"

    mensaje = _mensaje_del_canje(cuerpo, 401)

    assert "\n" not in mensaje


def test_294_los_AADSTS_que_no_son_numeros_no_entran():
    """La otra puerta por la que entra texto de un tercero: `error_codes` es una lista de
    enteros para Entra, pero quien contesta puede poner adentro lo que quiera."""
    cuerpo = dict(_SECRETO_VENCIDO)
    cuerpo["error_codes"] = ["7000215\nERROR [auth] linea falsa", 7000215]

    mensaje = _mensaje_del_canje(cuerpo, 401)

    assert "\n" not in mensaje
    assert "linea falsa" not in mensaje
    assert "7000215" in mensaje  # el entero legítimo de la misma lista sí sobrevive


def test_294_un_AADSTS_gigante_no_puede_elegir_el_largo_de_la_linea_de_log():
    """Acotar la CANTIDAD de códigos no acota el LARGO: un entero JSON de miles de dígitos es
    válido y `str()` lo escribe entero. Medido sobre el primer commit de este PR: un solo código
    de 4200 dígitos daba una línea de log de 4255 caracteres, y con cinco serían ~21 KB. Lo
    único que lo frenaba era `sys.get_int_max_str_digits()`, que es un tope del intérprete y no
    del producto. (Hallado por revisión independiente.)"""
    cuerpo = dict(_SECRETO_VENCIDO)
    cuerpo["error_codes"] = [int("9" * 4200), 7000215]

    mensaje = _mensaje_del_canje(cuerpo, 401)

    assert len(mensaje) < 200
    assert "999999999" not in mensaje
    assert "7000215" in mensaje  # el código legítimo de la misma lista sí sobrevive


def test_294_los_booleanos_no_se_cuelan_como_codigos():
    """`bool` es subclase de `int`: `isinstance(True, int)` es `True`, así que un filtro escrito
    con `isinstance` pintaría `AADSTS=True`. Por eso el filtro es `type(c) is int`."""
    cuerpo = dict(_SECRETO_VENCIDO)
    cuerpo["error_codes"] = [True, False, 7000215]

    mensaje = _mensaje_del_canje(cuerpo, 401)

    assert "True" not in mensaje and "False" not in mensaje
    assert "AADSTS=7000215" in mensaje


def test_294_un_cuerpo_JSON_que_no_es_un_objeto_no_rompe_el_manejo_del_error():
    """JSON válido pero lista, no objeto: sin el guard de forma, el `.get` de abajo revienta
    DENTRO del `except` y el fallo del IdP se convierte en un `AttributeError` que ya no es
    `SsoTokenExchangeError` — el callback pasaría de 401 a 500."""
    mensaje = _mensaje_del_canje(None, 500, texto='["no", "soy", "un", "objeto"]')

    assert "500" in mensaje


def test_294_un_idp_que_devolviera_el_secreto_en_el_cuerpo_no_lo_filtra_al_log(caplog):
    """Invariante 5 sostenido en el camino nuevo: el `client_secret` viaja en el FORM del pedido
    y Entra no lo echoea, pero el cuerpo de la respuesta lo redacta un tercero. Ninguno de los
    campos que se transcriben puede cargarlo."""
    cuerpo = dict(_SECRETO_VENCIDO)
    cuerpo["error_description"] = f"AADSTS7000215: el secreto {CLIENT_SECRET} no es válido"
    cuerpo["client_secret"] = CLIENT_SECRET

    with caplog.at_level(logging.DEBUG):
        mensaje = _mensaje_del_canje(cuerpo, 401)

    assert CLIENT_SECRET not in mensaje
    assert CLIENT_SECRET not in caplog.text


def test_294_un_cuerpo_que_no_es_JSON_conserva_el_status_y_no_transcribe_la_pagina():
    """Un proxy en el medio contesta HTML. El status —que es nuestro, no lo redacta nadie— tiene
    que sobrevivir igual, y la página no entra al log."""
    mensaje = _mensaje_del_canje(
        None, 502, texto="<html><body>502 Bad Gateway — corporate proxy</body></html>"
    )

    assert "502" in mensaje
    assert "Bad Gateway" not in mensaje
    assert "<html>" not in mensaje


def test_294_discovery_y_jwks_tambien_conservan_el_status():
    """Los otros dos sitios que colapsaban la causa en `type(exc).__name__`. Acá no hay secreto
    en juego, pero sí la diferencia entre «el IdP está caído» y «la authority está mal armada»."""
    pem_privado, jwks = _generar_par_rsa_y_jwks()

    proveedor = _proveedor_mockeado(jwks=jwks, id_token=None, discovery_status=503)
    with pytest.raises(SsoDiscoveryError) as discovery:
        proveedor.authorize_url(_config(), "s", nonce="n", redirect_uri=REDIRECT_URI)
    assert "503" in str(discovery.value)

    id_token = _firmar_id_token(pem_privado, KID, _claims_validos())
    proveedor = _proveedor_mockeado(jwks=jwks, id_token=id_token, jwks_status=500)
    with pytest.raises(SsoDiscoveryError) as jwks_error:
        _exchange(proveedor)
    assert "500" in str(jwks_error.value)
