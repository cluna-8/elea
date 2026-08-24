"""Rutas del flujo SSO (spec 017 US2, T015, FR-006/007/009/010/011).

Cubre las tres cosas que hacen que esta superficie sea segura o no:

- **El gate de licencia como dependency del router** (FR-010): con el flag apagado la
  superficie contesta 403 ANTES de correr nada del handler. Se afirma con un pedido
  que, con el flag prendido, daría 400 — si la respuesta es 403 igual, el gate
  preempta al handler y no al revés.
- **CSRF del flujo** (state): un callback cuyo ``state`` no es el que emitimos se
  rechaza. Sin esto, un atacante inyecta su propio callback y engancha SU sesión en el
  navegador de la víctima.
- **Fallback permanente** (FR-009): todo fallo del camino SSO deja intacto el login
  local con usuario y contraseña.

El IdP se dobla **en la frontera del proveedor** (se registra un ``SsoProvider`` falso
en el registry), no simulando HTTP: lo que este módulo debe probar son las rutas, el
gate y la emisión de sesión. El OIDC de verdad —firma, iss, aud, nonce— es de T014 y
se prueba allá; el tenant Entra real es T018.
"""
import sys
import uuid
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import (  # noqa: E402
    admin_headers, build_app_client, restore_suite_license, set_license,
)

require_postgres()

DB = "basa_test_sso_api"

LOGIN = "/api/v1/auth/sso/login"
CALLBACK = "/api/v1/auth/sso/callback"
AVAILABLE = "/api/v1/auth/sso/available"

# La URI que el IdP tiene registrada: es una ruta del FRONTEND, no de la API.
FRONTEND_REDIRECT = "https://consola.cliente.test/sso/callback"

EMAIL_IDP = "persona@cliente.test"


class ProveedorFalso:
    """Doble del IdP en la frontera del contrato (T014). Registra lo que recibe para
    poder afirmar que la ruta le pasa el ``nonce`` y el ``redirect_uri`` correctos."""

    provider_type = "falso"

    def __init__(self):
        self.identidad = {"email": EMAIL_IDP, "subject": "sub-123", "display_name": "Persona Cliente"}
        self.explota = None
        self.visto = {}

    def authorize_url(self, config, state, *, nonce, redirect_uri):
        if self.explota:
            raise self.explota
        self.visto = {"config": config, "state": state, "nonce": nonce, "redirect_uri": redirect_uri}
        return f"https://idp.test/authorize?state={state}&nonce={nonce}"

    def exchange_code(self, config, code, *, nonce, redirect_uri):
        if self.explota:
            raise self.explota
        self.visto = {"config": config, "code": code, "nonce": nonce, "redirect_uri": redirect_uri}
        return dict(self.identidad)


@pytest.fixture(scope="module")
def entorno():
    client, factory, cleanup = build_app_client(DB)
    # La cookie de state nace ``Secure`` (ver ``test_la_cookie_de_state_es_secure``), así
    # que el cliente HTTP NO la reenvía sobre http:// — igual que un navegador real. Se
    # habla https con la app para ejercitar el flujo tal como se despliega, en vez de
    # apagar el flag ``Secure`` para que el test sea fácil.
    client.base_url = "https://testserver"
    yield client, factory
    cleanup()


@pytest.fixture
def proveedor():
    """Registra el doble y lo saca al terminar, para no contaminar otros módulos.

    Toca ``_REGISTRY`` directo porque el contrato (T014) no expone un `unregister`:
    dar de baja un proveedor no es una operación de producto, sólo de test.
    """
    from src.sso import registry
    falso = ProveedorFalso()
    registry.register(falso)
    yield falso
    registry._REGISTRY.pop(falso.provider_type, None)


@pytest.fixture
def config_sso(entorno):
    """Fila ``sso_providers`` habilitada para el tenant del deployment."""
    _, factory = entorno
    from src.models.sso_provider import SSOProvider
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    try:
        db.query(SSOProvider).delete()
        db.add(SSOProvider(
            tenant_id=DEFAULT_TENANT_ID,
            provider_type="falso",
            config={"client_id": "cid-123", "directory_id": "dir-456"},
            client_secret_encrypted=None,
            enabled=True,
        ))
        db.commit()
    finally:
        db.close()
    yield
    db = factory()
    try:
        db.query(SSOProvider).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture
def sso_licenciado(monkeypatch, tmp_path):
    """Licencia con el flag ``sso`` — el default de la suite NO lo trae."""
    set_license(monkeypatch, tmp_path, feature_flags=["sso", "monitor"])
    yield
    restore_suite_license()


@pytest.fixture(autouse=True)
def _licencia_base():
    restore_suite_license()
    yield
    restore_suite_license()


@pytest.fixture(autouse=True)
def _redirect_uri_configurada(monkeypatch):
    """La URI de retorno es obligatoria y apunta al FRONTEND (ver ``_redirect_uri``).
    Se configura como en un deployment real en vez de dejar que el código la derive."""
    monkeypatch.setenv("BASA_SSO_REDIRECT_URI", FRONTEND_REDIRECT)


# ── El gate de licencia (FR-010) ───────────────────────────────────────────────────

def test_flag_apagado_403_en_login(entorno):
    """La licencia dev de la suite trae ``["monitor"]``: sin ``sso`` la ruta no opera."""
    client, _ = entorno
    resp = client.get(LOGIN, follow_redirects=False)
    assert resp.status_code == 403, resp.text
    assert "sso_no_licenciado" in resp.text


def test_el_gate_preempta_al_handler(entorno):
    """Con el flag apagado, un callback SIN state —que con el flag prendido daría
    400— contesta 403 igual: el gate corre ANTES del cuerpo del handler.

    Es la versión medible de «dependency, no inline»: inline correría después y la
    respuesta sería 400, filtrando que la superficie existe y qué le falta.
    """
    client, _ = entorno
    resp = client.get(CALLBACK, follow_redirects=False)
    assert resp.status_code == 403, f"inline daría 400; dependency da 403 — dio {resp.status_code}"
    assert "sso_no_licenciado" in resp.text


def test_flag_apagado_no_borra_la_config_del_tenant(entorno, config_sso):
    """FR-010: la config del tenant PERSISTE con el flag apagado (el perfil configura,
    la licencia autoriza)."""
    client, factory = entorno
    from src.models.sso_provider import SSOProvider
    assert client.get(LOGIN, follow_redirects=False).status_code == 403
    db = factory()
    try:
        assert db.query(SSOProvider).count() == 1
    finally:
        db.close()


def test_con_flag_prendido_y_sin_config_da_404(entorno, sso_licenciado):
    """Licencia OK pero el tenant no configuró proveedor: 404 claro, no 500."""
    client, _ = entorno
    resp = client.get(LOGIN, follow_redirects=False)
    assert resp.status_code == 404, resp.text
    assert "sso_no_configurado" in resp.text


# ── /available: discovery pre-auth para la pantalla de login ───────────────────────

def test_available_con_flag_apagado_403(entorno, config_sso):
    """El discovery vive DENTRO del gate: con el flag apagado no contesta 200, así
    que no hay una superficie nueva sin gatear."""
    client, _ = entorno
    resp = client.get(AVAILABLE)
    assert resp.status_code == 403, resp.text


def test_available_licenciado_y_configurado(entorno, sso_licenciado, config_sso):
    client, _ = entorno
    resp = client.get(AVAILABLE)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"enabled": True, "provider_type": "falso"}


def test_available_licenciado_sin_config(entorno, sso_licenciado):
    """Sin proveedor habilitado la respuesta es «no hay botón», no un error."""
    client, _ = entorno
    resp = client.get(AVAILABLE)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"enabled": False, "provider_type": None}


def test_available_no_filtra_la_config_del_tenant(entorno, sso_licenciado, config_sso):
    """Es una respuesta PRE-AUTH: el client_id y el directory ID del IdP no salen."""
    client, _ = entorno
    cuerpo = client.get(AVAILABLE).text
    assert "cid-123" not in cuerpo
    assert "dir-456" not in cuerpo
    assert "client_secret" not in cuerpo


# ── /login ─────────────────────────────────────────────────────────────────────────

def test_login_redirige_al_idp_con_state_y_nonce(entorno, sso_licenciado, config_sso, proveedor):
    client, _ = entorno
    resp = client.get(LOGIN, follow_redirects=False)

    assert resp.status_code == 302, resp.text
    assert resp.headers["location"].startswith("https://idp.test/authorize")
    assert proveedor.visto["state"] and proveedor.visto["nonce"]
    assert proveedor.visto["state"] != proveedor.visto["nonce"], "state y nonce son valores distintos"
    assert proveedor.visto["config"]["client_id"] == "cid-123", "le llega la config del tenant"


def test_login_deja_la_cookie_de_state_httponly(entorno, sso_licenciado, config_sso, proveedor):
    """La cookie es HttpOnly: si JS la puede leer, un XSS roba el flujo."""
    client, _ = entorno
    resp = client.get(LOGIN, follow_redirects=False)

    cookie = resp.headers.get("set-cookie", "")
    assert "basa_sso_state=" in cookie
    assert "HttpOnly" in cookie
    assert "Path=/api/v1/auth/sso" in cookie


def test_la_cookie_de_state_es_secure(entorno, sso_licenciado, config_sso, proveedor):
    """Sin ``Secure`` la cookie de state viaja en claro y un MITM secuestra el flujo.
    Es el default: sólo un deployment que declare HTTP plano (dev) lo apaga."""
    client, _ = entorno
    resp = client.get(LOGIN, follow_redirects=False)
    assert "Secure" in resp.headers.get("set-cookie", "")


def test_dos_logins_emiten_states_distintos(entorno, sso_licenciado, config_sso, proveedor):
    """Un state fijo sería reusable entre víctimas."""
    client, _ = entorno
    client.get(LOGIN, follow_redirects=False)
    primero = proveedor.visto["state"]
    client.cookies.clear()
    client.get(LOGIN, follow_redirects=False)
    assert proveedor.visto["state"] != primero


def test_la_redirect_uri_va_al_frontend_no_a_la_api(entorno, sso_licenciado, config_sso, proveedor):
    """El IdP redirige un NAVEGADOR: si la URI apuntara a ``/callback``, el usuario
    aterrizaría mirando el JSON de la sesión. Va a la ruta del frontend, que después
    cambia el code por la sesión con un fetch."""
    client, _ = entorno
    client.get(LOGIN, follow_redirects=False)

    assert proveedor.visto["redirect_uri"] == FRONTEND_REDIRECT
    assert "/api/v1/auth/sso/callback" not in proveedor.visto["redirect_uri"]


def test_sin_redirect_uri_configurada_el_flujo_corta_claro(entorno, sso_licenciado,
                                                           config_sso, proveedor, monkeypatch):
    """Sin configurar NO se cae a la URL de la API en silencio: eso daría un flujo que
    pasa los tests y aterriza en una página de JSON en producción."""
    client, _ = entorno
    monkeypatch.delenv("BASA_SSO_REDIRECT_URI", raising=False)

    resp = client.get(LOGIN, follow_redirects=False)

    assert resp.status_code == 500, resp.text
    assert "sso_redirect_uri_no_configurado" in resp.text


def test_la_redirect_uri_del_intercambio_es_la_misma_del_authorize(
        entorno, sso_licenciado, config_sso, proveedor):
    """OIDC exige que coincidan; si divergen, el IdP rechaza el intercambio."""
    client, _ = entorno
    client.cookies.clear()
    client.get(LOGIN, follow_redirects=False)
    uri_authorize = proveedor.visto["redirect_uri"]
    state = proveedor.visto["state"]

    client.get(f"{CALLBACK}?state={state}&code=abc", follow_redirects=False)

    assert proveedor.visto["redirect_uri"] == uri_authorize


def test_idp_caido_en_login_degrada_solo_sso(entorno, sso_licenciado, config_sso, proveedor):
    """FR-009: discovery caído → 502 claro del camino SSO, login local intacto."""
    client, _ = entorno
    proveedor.explota = RuntimeError("discovery inaccesible")

    resp = client.get(LOGIN, follow_redirects=False)
    assert resp.status_code == 502, resp.text
    assert "sso_idp_inaccesible" in resp.text

    assert admin_headers(client), "el login con usuario y contraseña sigue funcionando"


# ── /callback: CSRF del flujo ──────────────────────────────────────────────────────

def test_callback_sin_cookie_400(entorno, sso_licenciado, config_sso, proveedor):
    client, _ = entorno
    client.cookies.clear()
    resp = client.get(f"{CALLBACK}?state=loquesea&code=abc", follow_redirects=False)
    assert resp.status_code == 400
    assert "sso_state_ausente" in resp.text


def test_callback_con_state_ajeno_400(entorno, sso_licenciado, config_sso, proveedor):
    """El state que vuelve del IdP debe ser EL que emitimos (anti-CSRF de login)."""
    client, _ = entorno
    client.cookies.clear()
    client.get(LOGIN, follow_redirects=False)  # deja la cookie legítima

    resp = client.get(f"{CALLBACK}?state=state-del-atacante&code=abc", follow_redirects=False)

    assert resp.status_code == 400, resp.text
    assert "sso_state_invalido" in resp.text


def test_callback_con_cookie_falsificada_400(entorno, sso_licenciado, config_sso, proveedor):
    """Una cookie de state no firmada por nosotros no habilita el paso."""
    client, _ = entorno
    client.cookies.clear()
    client.cookies.set("basa_sso_state", "no.es.un.jwt.valido")
    resp = client.get(f"{CALLBACK}?state=x&code=abc", follow_redirects=False)
    assert resp.status_code == 400
    assert "sso_state_invalido" in resp.text


def test_un_token_de_sesion_no_sirve_como_state(entorno, sso_licenciado, config_sso, proveedor):
    """Un JWT de sesión presentado como cookie de state no habilita el callback.

    (Hoy lo frena el propio chequeo de ``state`` —un token de sesión no lleva ese
    claim—, no el de ``purpose``: ver ``test_el_claim_purpose_es_lo_que_separa...``
    para el que aísla esa defensa.)
    """
    client, _ = entorno
    from src.auth.session import create_session_token
    from src.models.tenant import DEFAULT_TENANT_ID
    sesion = create_session_token(str(uuid.uuid4()), "tenant_admin", "admin", str(DEFAULT_TENANT_ID))

    client.cookies.clear()
    client.cookies.set("basa_sso_state", sesion)
    resp = client.get(f"{CALLBACK}?state=x&code=abc", follow_redirects=False)

    assert resp.status_code == 400
    assert "sso_state_invalido" in resp.text


def test_el_claim_purpose_es_lo_que_separa_los_dos_tipos_de_token(
        entorno, sso_licenciado, config_sso, proveedor):
    """Un token firmado con NUESTRO secreto y con un ``state`` válido, pero emitido con
    otro propósito, se rechaza igual.

    El chequeo de ``state`` no alcanza para probar esto: un token que YA trae el state
    correcto lo pasa. Lo único que lo frena es ``purpose``. Es la defensa que hace que
    agregar mañana otro token firmado con el mismo secreto (reset de contraseña,
    invitación) no abra por accidente una vía de entrada al callback.
    """
    client, _ = entorno
    from datetime import datetime, timedelta
    from jose import jwt
    from src.auth.session import ALGORITHM, _ensure_secret

    state = "state-valido-pero-de-otro-token"
    forjado = jwt.encode(
        {
            "purpose": "reset_password",   # ← lo ÚNICO fuera de lugar
            "state": state,
            "nonce": "nonce-cualquiera",
            "provider_type": "falso",
            "exp": datetime.utcnow() + timedelta(minutes=10),
        },
        _ensure_secret(), algorithm=ALGORITHM,
    )

    client.cookies.clear()
    client.cookies.set("basa_sso_state", forjado)
    resp = client.get(f"{CALLBACK}?state={state}&code=abc", follow_redirects=False)

    assert resp.status_code == 400, (
        f"un token de otro propósito completó el callback (dio {resp.status_code}): "
        "el claim purpose no está separando los tipos de token"
    )
    assert "sso_state_invalido" in resp.text


def test_callback_sin_code_400(entorno, sso_licenciado, config_sso, proveedor):
    client, _ = entorno
    client.cookies.clear()
    client.get(LOGIN, follow_redirects=False)
    state = proveedor.visto["state"]

    resp = client.get(f"{CALLBACK}?state={state}", follow_redirects=False)
    assert resp.status_code == 400
    assert "sso_code_ausente" in resp.text


# ── /callback: camino feliz — el MISMO JWT del login local ─────────────────────────

def _flujo_completo(client, proveedor):
    client.cookies.clear()
    client.get(LOGIN, follow_redirects=False)
    state = proveedor.visto["state"]
    return client.get(f"{CALLBACK}?state={state}&code=code-del-idp", follow_redirects=False)


def test_callback_feliz_emite_sesion_con_tenant_claim(entorno, sso_licenciado, config_sso, proveedor):
    """FR-007/FR-011: la sesión de SSO es el MISMO JWT del login local, con tenant."""
    client, _ = entorno
    from src.auth.session import decode_session_token
    from src.models.tenant import DEFAULT_TENANT_ID

    resp = _flujo_completo(client, proveedor)

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["token_type"] == "bearer"
    payload = decode_session_token(cuerpo["access_token"])
    assert payload is not None, "el token de SSO decodifica con el MISMO secreto de sesión"
    assert payload["tenant"] == str(DEFAULT_TENANT_ID), "lleva el tenant claim de T005"
    assert payload["role"] == "client"
    assert cuerpo["user"]["email"] == EMAIL_IDP


def test_la_sesion_de_sso_sirve_aguas_abajo(entorno, sso_licenciado, config_sso, proveedor):
    """Cero bifurcación (FR-007): el JWT nacido de Entra autentica igual que el local.

    Se mide por contraste sobre ``POST /users/me/password``, que corta por identidad
    para CUALQUIER rol: sin token contesta 401 «Autenticación requerida»; con el token
    de SSO tiene que pasar esa puerta. Lo que se afirma es el reconocimiento de la
    sesión, no el resultado del cambio de contraseña.
    """
    client, _ = entorno
    token = _flujo_completo(client, proveedor).json()["access_token"]
    cuerpo = {"current_password": "loquesea-12345", "new_password": "otracosa-12345"}

    sin_token = client.post("/api/v1/users/me/password", json=cuerpo)
    assert sin_token.status_code == 401 and "Autenticación requerida" in sin_token.text

    con_sso = client.post("/api/v1/users/me/password", json=cuerpo,
                          headers={"Authorization": f"Bearer {token}"})
    assert "Autenticación requerida" not in con_sso.text, "el JWT de SSO no autenticó aguas abajo"


def test_el_callback_le_pasa_al_proveedor_el_nonce_que_emitio(entorno, sso_licenciado, config_sso, proveedor):
    """El nonce del intercambio debe ser el del /login, no uno nuevo: es lo que ata el
    id_token a ESTA sesión de navegador (la validación es de T014)."""
    client, _ = entorno
    client.cookies.clear()
    client.get(LOGIN, follow_redirects=False)
    nonce_login = proveedor.visto["nonce"]
    state = proveedor.visto["state"]

    client.get(f"{CALLBACK}?state={state}&code=abc", follow_redirects=False)

    assert proveedor.visto["nonce"] == nonce_login


def test_el_state_no_se_puede_reusar(entorno, sso_licenciado, config_sso, proveedor):
    """Tras un callback exitoso la cookie se borra: el mismo state no vuelve a entrar."""
    client, _ = entorno
    client.cookies.clear()
    client.get(LOGIN, follow_redirects=False)
    state = proveedor.visto["state"]

    primero = client.get(f"{CALLBACK}?state={state}&code=abc", follow_redirects=False)
    assert primero.status_code == 200, primero.text

    segundo = client.get(f"{CALLBACK}?state={state}&code=abc", follow_redirects=False)
    assert segundo.status_code == 400, "el state consumido no se reusa"


# ── /callback: fallos del IdP (FR-009) ─────────────────────────────────────────────

def test_identidad_no_verificada_401_y_login_local_intacto(entorno, sso_licenciado, config_sso, proveedor):
    """id_token con firma/iss/aud/nonce inválidos → 401 del camino SSO. El login con
    usuario y contraseña NO se entera (fallback permanente)."""
    client, _ = entorno
    client.cookies.clear()
    client.get(LOGIN, follow_redirects=False)
    state = proveedor.visto["state"]
    proveedor.explota = ValueError("firma del id_token inválida")

    resp = client.get(f"{CALLBACK}?state={state}&code=abc", follow_redirects=False)

    assert resp.status_code == 401, resp.text
    assert "sso_identidad_no_verificada" in resp.text
    assert admin_headers(client), "el login local sigue operando"


def test_el_error_del_idp_no_se_filtra_al_cliente(entorno, sso_licenciado, config_sso, proveedor):
    """El texto de la excepción puede citar config del IdP: al cliente va el veredicto,
    el detalle técnico queda en logs server-side."""
    client, _ = entorno
    client.cookies.clear()
    client.get(LOGIN, follow_redirects=False)
    state = proveedor.visto["state"]
    proveedor.explota = ValueError("client_secret=SUPERSECRETO rechazado por https://idp/tenant/abc")

    resp = client.get(f"{CALLBACK}?state={state}&code=abc", follow_redirects=False)

    assert resp.status_code == 401
    assert "SUPERSECRETO" not in resp.text
    assert "idp/tenant/abc" not in resp.text


def test_identidad_sin_email_401(entorno, sso_licenciado, config_sso, proveedor):
    """Sin email no hay clave de matching (FR-008): no se inventa una."""
    client, _ = entorno
    proveedor.identidad = {"email": "", "subject": "sub-x", "display_name": "Sin Email"}

    resp = _flujo_completo(client, proveedor)

    assert resp.status_code == 401, resp.text
    assert "sso_identidad_sin_email" in resp.text
