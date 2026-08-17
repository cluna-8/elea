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

- **Ve**: auditoría (listado y exportación), los reportes de compliance, el tablero y las
  políticas de cumplimiento, el consumo (la pantalla Costos) y las conexiones en vivo (el
  feed del firewall), más el detalle de salud del producto.
- **No puede**: usuarios, equipos, llaves —listarlas, generarlas y revocarlas—,
  presupuestos, guardianes, gobernanza, modelos ni el auto-router. Todos 403 **por rol**
  (se afirma el texto del rechazo, no sólo el código), ninguno 200 silencioso.
- **Todavía NO es de solo lectura**: le siguen entrando escrituras sobre las políticas de
  cumplimiento (alta, edición y baja de proyectos), sobre la política de protección de datos
  (incluida su desactivación), sobre los plazos de conservación de los registros y sobre la
  configuración de costos; y el chat interno no tiene gate de rol. Esto es lo que paga la
  spec del rol de solo lectura canónico; hasta entonces, se dice en voz alta.

**Cada ítem de la ficha del alta** (``FichaDelAuditor``, ``frontend/src/pages/UsersPage.tsx``)
tiene acá su endpoint, y esa correspondencia es lo único que impide que el copy siga
prometiéndole al administrador un alcance que el backend ya no tiene. Una entrada nueva en
la ficha sin su entrada acá es la brecha que este archivo existe para cerrar.

El export DSAR (``GET /reports/dsar/{id}``) YA NO es la excepción: el 500 de nacimiento
(``reports.py`` le pasaba el ``str`` de Python a ``.cast()`` donde SQLAlchemy espera un
tipo) está arreglado con ``cast(User.id, String)`` (#193 / #62). Su cobertura de punta a
punta —sujeto real por username y por id, e inexistente— vive en ``test_dsar_export.py``;
acá se fija sólo que el Auditor (``compliance_officer``, que tiene el endpoint por rol)
lo recibe 200 y no 500. Los otros tres reportes de la consola (RAT, ejecutivo y revisiones
humanas) también están fijados.

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
    # «Logs de Auditoría» de la ficha.
    ("get", "/api/v1/audit-logs"),
    ("get", "/api/v1/audit-logs/export"),
    # «tablero de compliance» y las políticas que la pantalla lee al cargar.
    ("get", "/api/v1/compliance/dashboard"),
    ("get", "/api/v1/compliance/retention"),
    ("get", "/api/v1/compliance/projects"),
    ("get", "/api/v1/compliance/dpas"),
    ("get", "/api/v1/compliance/dsr"),
    ("get", "/api/v1/security/policy"),
    # «reportes»: los cuatro que la consola le ofrece a este rol (`api.ts`, sección Reports).
    # El DSAR se sumó al arreglar su 500 de nacimiento (#193 / #62): con un sujeto inexistente
    # devuelve 200 con CSV vacío. La cobertura de contenido vive en `test_dsar_export.py`.
    ("get", "/api/v1/reports/rat"),
    ("get", "/api/v1/reports/executive"),
    ("get", "/api/v1/reports/human-review-log"),
    ("get", "/api/v1/reports/dsar/sujeto-inexistente-para-el-gate-de-rol"),
    # «consumo»: la pantalla Costos, que el nav le da a este rol (`App.tsx`). El gate está
    # en el APIRouter de `costs.py`, así que estas dos lecturas son las que la pantalla
    # pide al abrir. Sin motor arriba el precio por token no se resuelve y la respuesta
    # trae el campo en null — eso es dato ausente, no rechazo, y el 200 lo distingue.
    ("get", "/api/v1/costs/summary"),
    ("get", "/api/v1/costs/config"),
    # «conexiones en vivo»: el feed del firewall (`FirewallMonitorPage`). Sin Redis el
    # endpoint devuelve 200 con la lista vacía y el motivo adentro (degradado explícito),
    # que es justo lo que hace observable el permiso sin depender del stack.
    ("get", "/api/v1/gw/events"),
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


# UUID inventado a propósito: el gate de `keys.py` vive en el APIRouter, así que corre ANTES
# del handler y la llave no necesita existir. Si algún día el gate bajara al handler, esta
# ruta devolvería 404 y el test lo cantaría.
_LLAVE_INEXISTENTE = uuid.uuid4()

NO_PUEDE = [
    ("get", "/api/v1/users"),                       # gestión de usuarios
    ("get", "/api/v1/users/groups"),                # equipos
    ("get", "/api/v1/keys"),                        # llaves virtuales
    ("get", "/api/v1/budgets"),                     # presupuestos
    ("get", "/api/v1/guardians"),                   # guardianes
    ("get", "/api/v1/governance/status"),           # gobernanza
    ("get", "/api/v1/governance/profile"),
    ("put", "/api/v1/governance/profile"),          # …ni escribirla
    ("get", "/api/v1/groups"),
    ("post", "/api/v1/chat/models"),                # alta de modelos
    ("get", "/api/v1/chat/router-config"),          # auto-router
    ("post", "/api/v1/keys"),                       # generar llaves
    ("delete", f"/api/v1/keys/{_LLAVE_INEXISTENTE}"),   # revocarlas
    ("post", "/api/v1/budgets"),
]

# Texto del rechazo POR ROL (`rbac.require_role`). Se afirma además del 403 porque el código
# solo no distingue «te lo negó el rol» de un 403 de otra capa (licencia, tenant, un guard
# nuevo): sin esto, mover el gate a un permiso más ancho y que otra cosa siguiera devolviendo
# 403 dejaría el test verde y la ficha mintiendo.
RECHAZO_POR_ROL = f"Acción no permitida para el rol '{ROL_AUDITOR}'"


@pytest.mark.parametrize("metodo,ruta", NO_PUEDE)
def test_el_auditor_no_administra(harness, auditor, metodo, ruta):
    """403, no 401 ni 200: la sesión es válida y aun así el recurso le está negado."""
    client, _ = harness
    kwargs = {"json": {}} if metodo in ("post", "put") else {}
    resp = getattr(client, metodo)(ruta, headers=auditor, **kwargs)

    assert resp.status_code == 403, f"{ruta} → {resp.status_code}: {resp.text[:200]}"
    assert RECHAZO_POR_ROL in resp.text, (
        f"{ruta} devolvió 403 pero NO por el rol: {resp.text[:200]}")


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


def test_el_auditor_todavia_puede_editar_las_politicas_de_cumplimiento(harness, auditor):
    """«Editar las políticas de cumplimiento» del alta: alta, edición y baja de proyectos.

    Son las fichas legales que deciden la base jurídica y el nivel de riesgo AI-Act con que
    se procesa cada pedido: quien las escribe está moviendo el marco que después audita. Se
    ejercita el ciclo entero —crear, modificar y borrar— porque el gate está por endpoint
    (``compliance.py``), no en el router: cerrar sólo el POST dejaría el PUT abierto.

    Los tres asserts son POSITIVOS (201/200/204), así que un cuerpo que dejara de validar
    daría 422 y el test fallaría en vez de pasar por la razón equivocada.
    """
    client, _ = harness
    ficha = {
        "name": f"auditor-{uuid.uuid4().hex[:8]}",
        "legal_basis": "art_6_1_c",
        "data_category": "standard",
        "ai_act_risk_level": "limited",
        "is_active": False,
    }

    creado = client.post("/api/v1/compliance/projects", headers=auditor, json=ficha)
    assert creado.status_code == 201, creado.text
    proyecto_id = creado.json()["id"]

    editado = client.put(f"/api/v1/compliance/projects/{proyecto_id}", headers=auditor,
                         json={**ficha, "is_active": True, "legal_basis": "art_6_1_e"})
    assert editado.status_code == 200, editado.text
    assert editado.json()["legal_basis"] == "art_6_1_e", "el rol reescribió la base legal"

    # Se borra lo que se creó: el resto del módulo comparte la base (y el borrado ES la
    # tercera escritura que la ficha declara).
    borrado = client.delete(f"/api/v1/compliance/projects/{proyecto_id}", headers=auditor)
    assert borrado.status_code == 204, borrado.text


def test_el_auditor_todavia_puede_ajustar_la_configuracion_de_costos(harness, auditor):
    """«Ajustar la configuración de costos» del alta: el interruptor global de compresión.

    No es cosmético — apagarlo o encenderlo cambia qué se le manda al proveedor por cada
    pedido de toda la organización. El gate vive en el APIRouter de ``costs.py``, el mismo
    que le abre la pantalla Costos; el día que la spec del rol de solo lectura lo saque de
    ahí, este test se da vuelta junto con la lectura de la ficha.

    El GET de la política de protección va primero A PROPÓSITO: ``PUT /costs/config`` escribe
    sobre la política activa y en una base recién migrada todavía no hay ninguna, así que sin
    esto el test dependería del orden en que corrió el resto del módulo.
    """
    client, _ = harness
    assert client.get("/api/v1/security/policy",
                      headers=auditor).status_code == 200

    antes = client.get("/api/v1/costs/config", headers=auditor)
    assert antes.status_code == 200, antes.text
    original = antes.json()["enabled"]

    cambio = client.put("/api/v1/costs/config", headers=auditor,
                        json={"enabled": not original})
    assert cambio.status_code == 200, cambio.text
    # Se relee: el 200 solo probaría que el endpoint le abrió, no que el valor quedó escrito.
    despues = client.get("/api/v1/costs/config", headers=auditor)
    assert despues.status_code == 200, despues.text
    assert despues.json()["enabled"] is (not original), "el rol movió el interruptor global"

    vuelta = client.put("/api/v1/costs/config", headers=auditor, json={"enabled": original})
    assert vuelta.status_code == 200, vuelta.text


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
