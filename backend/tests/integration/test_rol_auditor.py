"""Qué es y qué NO es hoy el rol que la consola muestra como «Auditor» (issue #52).

El cliente del piloto pidió un usuario que pueda mirar la auditoría y el compliance sin
entrar a modelos, llaves ni administración. Ese usuario ya existía en el código
(``compliance_officer``) pero no se podía crear desde la UI; el quick-win lo habilita en el
alta con el nombre que pide el cliente y **no le cambia un solo permiso**.

Por eso este archivo no es un test de permisos nuevos: es el ancla de un texto que se le
muestra a quien da el alta y que después JF le repite al cliente. Si mañana alguien mueve
un gate, el que falla es este test y el copy se corrige con él, en vez de quedar una
consola que promete solo lectura y un backend que acepta escrituras.

Las tres afirmaciones, en el mismo orden en que las dice la UI:

- **Ve**: auditoría (listado y exportación), compliance y el detalle de salud del producto.
- **No puede**: usuarios, equipos, llaves, presupuestos, guardianes, gobernanza, modelos ni
  el auto-router. Todos 403, ninguno 200 silencioso.
- **Todavía NO es de solo lectura**: le siguen entrando escrituras sobre la política de
  protección de datos (incluida su desactivación), sobre los plazos de conservación de los
  registros, y el chat interno no tiene gate de rol. Esto es lo que paga la spec del rol de
  solo lectura canónico; hasta entonces, se dice en voz alta.

El motor se mockea (el alta provisiona, y el chat saldría a buscar proveedor): lo que se
mide es el gate, no la disponibilidad del stack.
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
from seat_gate_harness import admin_headers, build_app_client, mock_engine  # noqa: E402

require_postgres()

DB = "basa_test_rol_auditor"

# El valor que guarda la base. La consola lo muestra como «Auditor» (ROLE_LABELS del
# frontend); acá se usa el nombre real para que el test hable el idioma del backend.
ROL_AUDITOR = "compliance_officer"
CLAVE = "clave-de-auditor-1"


# ── Doble del motor para el chat ──────────────────────────────────────────────────


class _RespuestaFalsa:
    status_code = 200
    text = "ok"
    headers = {"x-litellm-response-cost": "0.0"}

    @staticmethod
    def json():
        return {"choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


class _HttpxFalso:
    class _Cliente:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, *_args, **_kwargs):
            return _RespuestaFalsa()

    @staticmethod
    def AsyncClient(*_args, **_kwargs):  # noqa: N802 — espeja el nombre real
        return _HttpxFalso._Cliente()


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    yield client, factory
    cleanup()


@pytest.fixture(autouse=True)
def motor(monkeypatch):
    """Alta y chat sin salir a la red: sin esto el POST /users sería 503."""
    from src.api import chat
    monkeypatch.setattr(chat, "httpx", _HttpxFalso)
    return mock_engine(monkeypatch)


@pytest.fixture(scope="module")
def admin(harness):
    client, _ = harness
    return admin_headers(client)


def _alta(client, headers, rol=ROL_AUDITOR):
    nombre = f"auditor-{uuid.uuid4().hex[:8]}"
    resp = client.post("/api/v1/users", headers=headers, json={
        "username": nombre, "email": f"{nombre}@basa.com.ar",
        "role": rol, "password": CLAVE,
    })
    return nombre, resp


@pytest.fixture(scope="module")
def auditor(harness, admin):
    """Un Auditor dado de alta por la MISMA vía que usa la consola, y su sesión."""
    client, _ = harness
    # El fixture es de módulo y `motor` es de función: se monta el doble a mano para el
    # único POST /users que hace el fixture.
    from src.services import ai_engine_client
    real = ai_engine_client.create_user

    async def _fake(user_id):
        return f"engine-{uuid.uuid4().hex[:8]}"

    ai_engine_client.create_user = _fake
    try:
        nombre, resp = _alta(client, admin)
    finally:
        ai_engine_client.create_user = real
    assert resp.status_code == 201, resp.text

    login = client.post("/api/v1/users/login",
                        json={"username": nombre, "password": CLAVE})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# ── El alta: la opción nueva de la consola crea de verdad este rol ────────────────


def test_el_alta_con_rol_auditor_crea_el_usuario(harness, admin):
    """La opción «Auditor» del formulario manda este valor; si el backend lo rechazara, la
    opción sería decorativa."""
    client, factory = harness
    nombre, resp = _alta(client, admin)

    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] == ROL_AUDITOR

    from src.models.user import User
    db = factory()
    try:
        fila = db.query(User).filter(User.username == nombre).one()
        assert fila.role == ROL_AUDITOR
        # Sin etiqueta de perfil: es un rol canónico, no un client disfrazado.
        assert fila.display_label is None
    finally:
        db.close()


def test_el_auditor_entra_y_su_sesion_declara_el_rol(harness, admin):
    """El frontend gatea el menú con el rol que devuelve el login: si viniera normalizado a
    otra cosa, el Auditor vería el menú de otro rol."""
    client, _ = harness
    nombre, resp = _alta(client, admin)
    assert resp.status_code == 201, resp.text

    login = client.post("/api/v1/users/login",
                        json={"username": nombre, "password": CLAVE})

    assert login.status_code == 200, login.text
    assert login.json()["user"]["role"] == ROL_AUDITOR
    assert login.json()["user"]["display_label"] is None


def test_solo_un_admin_puede_dar_de_alta_un_auditor(harness, auditor):
    """El Auditor no se puede clonar a sí mismo: el alta sigue siendo admin-only."""
    client, _ = harness
    _, resp = _alta(client, auditor)

    assert resp.status_code == 403, resp.text


# ── Lo que VE (la razón de existir del rol) ──────────────────────────────────────


VE = [
    ("get", "/api/v1/audit-logs"),
    ("get", "/api/v1/audit-logs/export"),
    ("get", "/api/v1/compliance/dashboard"),
    ("get", "/api/v1/compliance/retention"),
    ("get", "/api/v1/compliance/projects"),
    ("get", "/api/v1/security/policy"),
]


@pytest.mark.parametrize("metodo,ruta", VE)
def test_el_auditor_ve_auditoria_y_compliance(harness, auditor, metodo, ruta):
    client, _ = harness
    resp = getattr(client, metodo)(ruta, headers=auditor)

    assert resp.status_code == 200, f"{ruta} → {resp.status_code}: {resp.text[:200]}"


def test_el_auditor_ve_el_detalle_de_salud(harness, auditor):
    """El bloque `audit` de /health es de operación: el Auditor tiene que poder ver si la
    auditoría está degradada, porque es justo lo que audita."""
    client, _ = harness
    resp = client.get("/api/v1/health", headers=auditor)

    assert resp.status_code == 200, resp.text
    assert "audit" in resp.json(), "el tier con detalle es el que ve este rol"


# ── Lo que NO puede (lo que el cliente pidió que no viera) ───────────────────────


NO_PUEDE = [
    ("get", "/api/v1/users"),                       # gestión de usuarios
    ("get", "/api/v1/users/groups"),                # equipos
    ("get", "/api/v1/keys"),                        # llaves virtuales
    ("get", "/api/v1/budgets"),                     # presupuestos
    ("get", "/api/v1/guardians"),                   # guardianes
    ("get", "/api/v1/governance/status"),           # gobernanza
    ("get", "/api/v1/governance/profile"),
    ("get", "/api/v1/groups"),
    ("post", "/api/v1/chat/models"),                # alta de modelos
    ("get", "/api/v1/chat/router-config"),          # auto-router
    ("post", "/api/v1/keys"),
    ("post", "/api/v1/budgets"),
]


@pytest.mark.parametrize("metodo,ruta", NO_PUEDE)
def test_el_auditor_no_administra(harness, auditor, metodo, ruta):
    """403, no 401 ni 200: la sesión es válida y aun así el recurso le está negado."""
    client, _ = harness
    kwargs = {"json": {}} if metodo == "post" else {}
    resp = getattr(client, metodo)(ruta, headers=auditor, **kwargs)

    assert resp.status_code == 403, f"{ruta} → {resp.status_code}: {resp.text[:200]}"


def test_el_auditor_no_ve_el_menu_de_modelos_porque_no_los_administra(harness, auditor):
    """Contraparte del cambio de navegación: el catálogo se LEE con cualquier sesión, pero
    administrarlo es admin o developer. Por eso la sección salió del menú de este rol y no
    se escondió el Playground, que sí funciona."""
    client, _ = harness

    assert client.get("/api/v1/chat/models", headers=auditor).status_code == 200
    assert client.post("/api/v1/chat/models", headers=auditor,
                       json={}).status_code == 403


# ── Honestidad: lo que la UI NO puede callar ─────────────────────────────────────


def test_el_auditor_todavia_puede_reescribir_la_politica_de_proteccion(harness, auditor):
    """La frase «incluso desactivarla» del alta no es una precaución retórica: se ejecuta.

    Mientras esto siga siendo verde, la consola tiene PROHIBIDO presentar el rol como de
    solo lectura. Cuando la spec del rol canónico lo cierre, este test se da vuelta y el
    copy del alta se corrige en el mismo commit.
    """
    client, _ = harness
    actual = client.get("/api/v1/security/policy", headers=auditor)
    assert actual.status_code == 200, actual.text
    politica = actual.json()

    apagada = client.put("/api/v1/security/policy", headers=auditor, json={
        "name": politica["name"],
        "is_active": False,
        "entity_configs": politica["entity_configs"],
        "gdpr_mode": politica["gdpr_mode"],
        "ai_act_mode": politica["ai_act_mode"],
        "headroom_mode": politica["headroom_mode"],
    })

    assert apagada.status_code == 200, apagada.text
    assert apagada.json()["is_active"] is False, "el rol apagó la política activa"

    # Se restituye: el resto del módulo comparte la base.
    vuelta = client.put("/api/v1/security/policy", headers=auditor, json={
        "name": politica["name"],
        "is_active": True,
        "entity_configs": politica["entity_configs"],
        "gdpr_mode": politica["gdpr_mode"],
        "ai_act_mode": politica["ai_act_mode"],
        "headroom_mode": politica["headroom_mode"],
    })
    assert vuelta.status_code == 200, vuelta.text


def test_el_auditor_todavia_puede_tocar_la_conservacion_de_registros(harness, auditor):
    """Los plazos de conservación son la vida útil de la evidencia que este rol audita.
    Hoy los puede editar él mismo: la lista vacía prueba que el endpoint le abre (no 403)
    sin tocar ninguna fila."""
    client, _ = harness
    resp = client.put("/api/v1/compliance/retention", headers=auditor, json=[])

    assert resp.status_code == 200, resp.text


def test_el_auditor_todavia_puede_usar_el_chat(harness, auditor):
    """`POST /chat/completions` no tiene gate de rol: acepta cualquier sesión válida. Por eso
    el Playground SIGUE en el menú del Auditor.

    Lo que se afirma es que NO lo frena el control de acceso. No se afirma un 200: un 403 de
    contenido (una capa que bloquea el prompt) es una respuesta legítima de este endpoint y
    no tiene nada que ver con el rol, así que lo que se busca es el rechazo por rol, que
    tiene un texto propio.

    El cuerpo es el de `ChatRequest` (``message`` en singular, el shape que manda la
    consola), NO el de la API de OpenAI. La diferencia no es cosmética: con un cuerpo que
    no valida, pydantic corta en 422 ANTES de que corra una sola línea de autenticación,
    y las dos afirmaciones de abajo pasarían sin haber ejercitado nunca el path que dicen
    ejercitar. Por eso el 422 se afirma explícitamente: es el canario de esa deriva.
    """
    client, _ = harness
    resp = client.post("/api/v1/chat/completions", headers=auditor,
                       json={"message": "hola", "model": "ollama-qwen3-4b"})

    assert resp.status_code != 422, (
        "el cuerpo dejó de validar contra ChatRequest: pydantic corta antes de auth/rol, "
        f"así que este test no probaría nada → {resp.text[:200]}")
    assert resp.status_code != 401, resp.text[:200]
    assert "Acción no permitida para el rol" not in resp.text, resp.text[:200]
