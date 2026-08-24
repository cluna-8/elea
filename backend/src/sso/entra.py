"""Proveedor SSO Microsoft Entra ID — OIDC authorization code + discovery (spec 017 US2).

Implementa el contrato `registry.SsoProvider` sobre **authlib** (research D2: cliente OIDC
framework-agnóstico — Entra es config sobre este cliente, no código especial; Google, C3, se
suma igual). Se auto-registra al importarse (`registry.register(EntraProvider())` al final del
módulo); el import lo dispara `registry._cargar_builtins()` la primera vez que alguien pide un
proveedor — este módulo NO necesita que nadie lo importe a mano.

## `config` (JSONB de la fila `sso_providers`, T013)

- ``tenant_id``: directory/tenant ID de Entra (arma la authority
  ``https://login.microsoftonline.com/{tenant_id}/v2.0``).
- ``client_id``: client ID de la app registrada en Entra.
- ``client_secret``: el secreto **YA DESCIFRADO por el consumidor** — este módulo no lee
  ``client_secret_encrypted`` ni descifra nada (eso es `services/encryption_service`, fuera de
  esta pieza). Sólo lo usa como valor de formulario en el POST al token endpoint; jamás lo
  loguea ni lo mete en un mensaje de excepción (invariante 5 del brief).

## Discovery y JWKS

Se leen del documento OIDC del IdP (regla dura 7 del contrato): la authority arriba +
``/.well-known/openid-configuration``. Se cachea EN MEMORIA por instancia de
``EntraProvider`` y por authority (no hay TTL de invalidación activa — alcanza para la vida de
un worker; un cambio de config de tenant se recoge en el próximo restart). Un fallo de
discovery o de JWKS levanta ``SsoDiscoveryError`` — nunca degrada en silencio a "sin
verificar".

## Verificación del id_token

Algoritmo fijado por ALLOWLIST (`JsonWebToken(["RS256"])`, no el objeto de módulo
`authlib.jose.jwt` — ese no tiene allowlist y honra el `alg` que el TOKEN declara, `none`
incluido: bypass de autenticación completo, hallado por Jeff sobre #260). Firma verificada
contra el JWKS del IdP (nunca `verify=False`). `iss` debe ser EXACTAMENTE el `issuer` que el
propio discovery reportó; `aud` debe ser EXACTAMENTE el `client_id` de la config; expiración
estándar (`exp`); `nonce` se compara a mano contra el que `exchange_code` recibió (no es un
claim JWT registrado — authlib no lo valida por sí solo). Cualquier fallo de estas cinco cosas
levanta ``SsoTokenExchangeError``, nunca acepta el token.
"""
from __future__ import annotations

import time
from urllib.parse import urlencode

import httpx
from authlib.jose import JsonWebKey, JsonWebToken
from authlib.jose.errors import JoseError

from . import registry

DISCOVERY_CACHE_TTL_SECONDS = 3600.0
_CAMPOS_DISCOVERY_REQUERIDOS = ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri")

# Allowlist EXPLÍCITA de algoritmos — Entra firma RS256. El objeto de módulo `authlib.jose.jwt`
# NO tiene allowlist (su `_algorithms` es `None` = "todos los registrados", `none` incluido) y
# decodifica con el `alg` que el TOKEN declara, no con el que el IdP realmente usa: un atacante
# que llegue al callback con un id_token `{"alg":"none"}` (sin firma) o `{"alg":"HS256"}`
# (confusión de algoritmo, firmando con la clave PÚBLICA RSA del IdP como si fuera un secreto
# HMAC compartido) pasa `claims.validate()` con total normalidad porque el contenido lo elige
# él mismo. Hallazgo de Jeff sobre #260 (P1): bypass de autenticación completo, encadenado con
# T015/T016 es sesión con el email que el atacante quiera, sin secretos ni clave del IdP. Fijar
# la allowlist es el fix — `JsonWebToken(["RS256"]).decode()` levanta `UnsupportedAlgorithmError`
# (subclase de `JoseError`) ante cualquier `alg` que no sea RS256, cae en el mismo `except`.
_JWT = JsonWebToken(["RS256"])


class SsoDiscoveryError(Exception):
    """Discovery del documento OIDC (o del JWKS) falló: red, HTTP no-2xx, JSON inválido, o
    faltan campos obligatorios. Fail-closed explícito — regla dura FR-009: sólo el camino SSO
    se degrada, el password login jamás se entera de esto."""


class SsoTokenExchangeError(Exception):
    """El intercambio code→token, o la validación del id_token resultante (firma / iss / aud /
    nonce / expiración), falló. El mensaje NUNCA lleva el client_secret ni el id_token crudo —
    sólo el tipo de fallo (invariante 5)."""


class EntraProvider:
    provider_type = "entra"

    def __init__(self, *, http_client: httpx.Client | None = None) -> None:
        # Inyectable para tests (httpx.MockTransport); en producción, un Client real con
        # timeout acotado — un IdP colgado no puede colgar el callback SSO indefinidamente.
        self._client = http_client or httpx.Client(timeout=10.0)
        self._discovery_cache: dict[str, tuple[float, dict]] = {}

    # -- discovery ---------------------------------------------------------------------

    @staticmethod
    def _authority(config: dict) -> str:
        tenant_id = config.get("tenant_id")
        if not tenant_id:
            raise SsoDiscoveryError("config de Entra sin 'tenant_id' (directory ID del IdP)")
        return f"https://login.microsoftonline.com/{tenant_id}/v2.0"

    def _discover(self, config: dict) -> dict:
        authority = self._authority(config)
        cached = self._discovery_cache.get(authority)
        now = time.monotonic()
        if cached is not None and (now - cached[0]) < DISCOVERY_CACHE_TTL_SECONDS:
            return cached[1]

        url = f"{authority}/.well-known/openid-configuration"
        try:
            response = self._client.get(url)
            response.raise_for_status()
            doc = response.json()
        except SsoDiscoveryError:
            raise
        except Exception as exc:  # httpx.HTTPError, json.JSONDecodeError, lo que sea
            raise SsoDiscoveryError(
                f"discovery OIDC falló contra el IdP ({type(exc).__name__})"
            ) from exc

        faltantes = [campo for campo in _CAMPOS_DISCOVERY_REQUERIDOS if campo not in doc]
        if faltantes:
            raise SsoDiscoveryError(
                f"documento de discovery del IdP incompleto (faltan: {', '.join(faltantes)})"
            )

        self._discovery_cache[authority] = (now, doc)
        return doc

    def _jwks(self, discovery_doc: dict):
        try:
            response = self._client.get(discovery_doc["jwks_uri"])
            response.raise_for_status()
            raw = response.json()
            return JsonWebKey.import_key_set(raw)
        except Exception as exc:
            raise SsoDiscoveryError(
                f"no se pudo obtener/parsear el JWKS del IdP ({type(exc).__name__})"
            ) from exc

    # -- contrato SsoProvider ------------------------------------------------------------

    def authorize_url(
        self, config: dict, state: str, *, nonce: str, redirect_uri: str
    ) -> str:
        doc = self._discover(config)
        client_id = config.get("client_id")
        if not client_id:
            raise SsoDiscoveryError("config de Entra sin 'client_id'")

        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
        }
        return f"{doc['authorization_endpoint']}?{urlencode(params)}"

    def exchange_code(
        self, config: dict, code: str, *, nonce: str, redirect_uri: str
    ) -> registry.Identity:
        doc = self._discover(config)
        client_id = config.get("client_id")
        client_secret = config.get("client_secret")
        if not client_id or not client_secret:
            # Nunca se menciona el VALOR del secreto, sólo que falta.
            raise SsoTokenExchangeError(
                "config de Entra incompleta para el intercambio (client_id/client_secret)"
            )

        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        }
        try:
            response = self._client.post(doc["token_endpoint"], data=form)
            response.raise_for_status()
            token_response = response.json()
        except Exception as exc:
            # httpx encadena la excepción original en __cause__/__context__, pero su __str__
            # (método + URL + status) no lleva el body del POST — el secreto no viaja acá.
            raise SsoTokenExchangeError(
                f"intercambio code→token falló con el IdP ({type(exc).__name__})"
            ) from exc

        id_token = token_response.get("id_token")
        if not id_token:
            raise SsoTokenExchangeError("la respuesta de token del IdP no trae 'id_token'")

        key_set = self._jwks(doc)
        claims_options = {
            "iss": {"essential": True, "value": doc["issuer"]},
            "aud": {"essential": True, "value": client_id},
            "exp": {"essential": True},
        }
        try:
            claims = _JWT.decode(id_token, key_set, claims_options=claims_options)
            claims.validate()
        except JoseError as exc:
            # Firma manipulada (BadSignatureError), iss/aud que no matchean
            # (InvalidClaimError), vencido (ExpiredTokenError), o un `alg` fuera de la
            # allowlist —`none`, `HS256`, `RS512`— (UnsupportedAlgorithmError): todas caen
            # acá, todas rechazadas — jamás se decodifica sin verificar la firma con el
            # algoritmo que el IdP realmente usa.
            raise SsoTokenExchangeError(f"id_token inválido ({type(exc).__name__})") from exc

        if claims.get("nonce") != nonce:
            raise SsoTokenExchangeError(
                "nonce del id_token no coincide con el nonce del pedido"
            )

        email = claims.get("email") or claims.get("preferred_username")
        subject = claims.get("sub")
        display_name = claims.get("name") or email or subject
        if not email or not subject:
            raise SsoTokenExchangeError("id_token sin 'email'/'sub' — identidad incompleta")

        return registry.Identity(email=email, subject=subject, display_name=display_name)


registry.register(EntraProvider())
