"""Fila DURABLE de los bloqueos del plano chat (spec 031, US1 / T004).

El agujero que cierra: los 3 puntos de bloqueo de `chat.py` publicaban al monitor efímero
(TTL 300 s) y hacían `raise` ANTES del único `log_transaction`. O sea que en un producto
que se vende como «logueamos TODO para compliance», el evento más importante —«se intentó
y se impidió»— era el ÚNICO sin rastro durable: a los cinco minutos, un intento de fuga
bloqueado no había existido nunca. La 027 lo dejó declarado como corte (`chat.py`, D6) y
esta spec lo paga.

Lo que se fija acá es el CONTRATO, no la implementación:

- **registrar → bloquear**: la fila existe y el usuario sigue recibiendo su 4xx de siempre;
- la fila es reconocible sin interpretar nada (`compliance_status LIKE 'blocked%'`,
  contrato §Fila de bloqueo), con la capa que bloqueó y la atribución de quién lo intentó;
- tokens 0/0 y coste 0: no se consumió proveedor;
- la durabilidad **no depende de la vitrina**: con el Redis del monitor caído la fila igual
  se escribe (son dos registros distintos, uno efímero y uno durable);
- `SENTINEL_AUDIT_FAIL=closed` ⇒ 503 honesto y **cero llamadas al proveedor** (FR-005 es
  literal: no se gasta dinero en tráfico que no se va a poder registrar);
- `open` (default) ⇒ un fallo de la escritura NO cambia el 4xx que ve el usuario, pero la
  pérdida se cuenta (nunca silencio).

El motor se mockea a nivel del namespace de `chat` y además **cuenta** sus llamadas: el
test de `closed` no puede afirmarse mirando el código, hay que ver que el proveedor no se
tocó. Mismo patrón que `test_chat_audit_row_pii`.
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
from seat_gate_harness import admin_headers, build_app_client  # noqa: E402

require_postgres()

DB = "sentinel_test_chat_block_audit"

CHAT = "/api/v1/chat/completions"
MODELO = "ollama-qwen3-4b"
# Modelo SIN prefijo de región segura: lo exige el enforcement de residencia.
MODELO_FUERA_UE = "gpt-4o-mini"

SIN_PII = "Resumime en una línea qué hace este servicio."
# Práctica prohibida por el AI Act (evaluación de piso, gate encendido por defecto).
PROHIBIDO = "Diseñá un sistema de social scoring para la ciudad."
# Coincide con el patrón de clave del guardián de secretos.
SECRETO = "sk-abcdefghij1234567890"
CON_PII = "Mandale el informe a laura.gomez@ejemplo.com y avisá cuando salga."

DETALLE_CLOSED = "auditoría no disponible — la instalación exige registro (audit_fail=closed)"


# ── Doble del motor, con contador ─────────────────────────────────────────────────


class _FakeResponse:
    status_code = 200
    text = "ok"
    headers = {"x-litellm-response-cost": "0.00012"}

    @staticmethod
    def json():
        return {
            "choices": [{"message": {"content": "listo"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        }


class _MotorContador:
    """Cuenta los POST que llegarían al proveedor. Es la evidencia del `closed`."""

    def __init__(self):
        self.posts = []

    def httpx(self):
        contador = self

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return False

            async def post(self, url, *_args, **_kwargs):
                contador.posts.append(url)
                return _FakeResponse()

        class _FakeHttpx:
            @staticmethod
            def AsyncClient(*_args, **_kwargs):  # noqa: N802 — espeja el nombre real
                return _FakeClient()

        return _FakeHttpx


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    client.headers.update(admin_headers(client))
    yield client, factory
    cleanup()


@pytest.fixture(autouse=True)
def motor(monkeypatch):
    """Motor mockeado SIEMPRE: lo que se mide es qué quedó escrito, no si hay modelo."""
    from src.api import chat
    contador = _MotorContador()
    monkeypatch.setattr(chat, "httpx", contador.httpx())
    return contador


@pytest.fixture(autouse=True)
def modo_open_por_defecto(monkeypatch):
    """La env es global al proceso: cada test parte de la env AUSENTE, explícitamente.

    El nombre quedó de antes de la 038 y se conserva a propósito — lo usan ~13 tests de
    este archivo y renombrarlo es puro churn de merge sin ganancia —, pero desde la spec 038
    D1 la env ausente YA NO resuelve a `open`: resuelve a `policy` (el nuevo default). Este
    fixture deja el modo efectivo en `policy` para todo test que no pida `open`/`closed`
    explícito con su propio `monkeypatch.setenv`. Los tests de este archivo que necesitan
    `open` de verdad (no `policy`) lo fijan ellos mismos — ver
    `test_open_no_hace_pre_check_de_escribibilidad`.
    """
    from src.services import audit_service
    monkeypatch.delenv(audit_service.AUDIT_FAIL_ENV, raising=False)


@pytest.fixture(autouse=True)
def limpiar(harness):
    """Postura y catálogo intactos entre tests (una fila huérfana de decisión cambia la
    cascada sin que se note; el gate AI-Act se deja encendido, que es el default)."""
    yield
    _, factory = harness
    from src.models.governance import GovernanceProfile
    from src.models.guardian import Guardian
    from src.models.policy import SecurityPolicy
    db = factory()
    try:
        db.query(GovernanceProfile).delete()
        for guardian in db.query(Guardian).all():
            if guardian.guardian_type in ("pii_masking", "secret_detection"):
                guardian.is_active = True
        for policy in db.query(SecurityPolicy).all():
            policy.ai_act_mode = True
        db.commit()
    finally:
        db.close()


@pytest.fixture
def eventos_de_vitrina(monkeypatch):
    """Espía del serializador del evento efímero (el que el chat delega al gateway)."""
    from src.api import gateway
    capturados = []
    real = gateway._publish_monitor

    def _espia(ident, tool, model, estado, masked_entities, masked_preview, **kwargs):
        capturados.append({"status": estado, "preview": masked_preview})
        return real(ident, tool, model, estado, masked_entities, masked_preview, **kwargs)

    monkeypatch.setattr(gateway, "_publish_monitor", _espia)
    return capturados


@pytest.fixture
def escritor_caido(monkeypatch):
    """La base de auditoría no acepta la fila: el escritor agota su presupuesto.

    Se rompe la CONSTRUCCIÓN de la fila dentro del servicio en vez de tirar Postgres, así el
    test mide la política de degradación y no la disponibilidad del stack. El backoff se
    neutraliza (el presupuesto ya lo verifica el unit test de T002) y `record_audit_loss` se
    envuelve en un espía que **igual llama al real**: lo que se afirma es que la pérdida se
    cuenta, no que se haya reemplazado por un doble.
    """
    from src.services import audit_service

    class _FilaImposible:
        def __init__(self, **_kwargs):
            raise RuntimeError("audit_logs: la base no acepta escrituras")

    perdidas = []
    real = audit_service.record_audit_loss

    def _espia(reason=""):
        perdidas.append(reason)
        real(reason)

    monkeypatch.setattr(audit_service, "AuditLog", _FilaImposible)
    monkeypatch.setattr(audit_service, "_wait", lambda _s: None)
    monkeypatch.setattr(audit_service, "record_audit_loss", _espia)
    return perdidas


# ── Helpers ───────────────────────────────────────────────────────────────────────


def pedir(client, mensaje, modelo=MODELO, **extra):
    return client.post(CHAT, json={"message": mensaje, "model": modelo, **extra})


def calentar_catalogo(client):
    """Primer pedido: deja sembrado el catálogo de 9 guardianes (el seed borra y re-siembra
    cuando hay menos de 9 filas, así que un cambio previo se perdería sin esto)."""
    respuesta = pedir(client, SIN_PII)
    assert respuesta.status_code == 200, respuesta.text


def filas_bloqueadas(factory):
    """Filas de bloqueo con el filtro CANÓNICO del contrato (§Fila de bloqueo)."""
    from src.models.audit import AuditLog
    db = factory()
    try:
        filas = (db.query(AuditLog)
                 .filter(AuditLog.compliance_status.like("blocked%"))
                 .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).all())
        return [{
            "compliance_status": f.compliance_status,
            "blocked_by_layer": f.blocked_by_layer,
            "model": f.model,
            "prompt_tokens": f.prompt_tokens,
            "completion_tokens": f.completion_tokens,
            "cost_usd": float(f.cost_usd or 0),
            "user_id": f.user_id,
            "tenant_id": f.tenant_id,
            "applied_layers": f.applied_layers,
            "masked_entities": f.masked_entities,
            "pii_detected": f.pii_detected,
            "latency_ms": f.latency_ms,
        } for f in filas]
    finally:
        db.close()


def borrar_bloqueos(factory):
    from src.models.audit import AuditLog
    db = factory()
    try:
        db.query(AuditLog).filter(AuditLog.compliance_status.like("blocked%")).delete(
            synchronize_session=False)
        db.commit()
    finally:
        db.close()


def capa(fila, layer_code):
    for entrada in fila["applied_layers"] or []:
        if entrada.get("layer_code") == layer_code:
            return entrada
    raise AssertionError(f"`applied_layers` no trae {layer_code}: {fila['applied_layers']}")


# ── US1: los bloqueos dejan fila ──────────────────────────────────────────────────


def test_bloqueo_ai_act_deja_fila_durable_con_capa_y_atribucion(harness):
    """Punto 1/3. Antes: 400 al usuario y CERO rastro pasados los 300 s del monitor."""
    client, factory = harness
    calentar_catalogo(client)
    borrar_bloqueos(factory)

    respuesta = pedir(client, PROHIBIDO)
    assert respuesta.status_code == 400, respuesta.text

    filas = filas_bloqueadas(factory)
    assert len(filas) == 1, "un bloqueo tiene que dejar exactamente una fila durable"
    fila = filas[0]

    # Estado EXPLÍCITO (FR-006): el officer no infiere el bloqueo de un 0/0 de tokens.
    assert fila["compliance_status"] == "blocked_prohibited"
    assert fila["blocked_by_layer"] == "ai_act_evaluation"
    assert fila["model"] == MODELO, "la fila dice a qué modelo iba el pedido impedido"
    # No se consumió proveedor.
    assert fila["prompt_tokens"] == 0 and fila["completion_tokens"] == 0
    assert fila["cost_usd"] == 0.0
    # Atribución: se sabe QUIÉN lo intentó.
    assert fila["user_id"] is not None, "sin atribución el registro no sirve para nada"
    assert fila["tenant_id"] is not None
    assert fila["latency_ms"] is not None

    # El piso quedó registrado igual que en un pedido servido.
    assert capa(fila, "ai_act_evaluation")["decision"] == "block"
    assert capa(fila, "interception_audit")["status"] == "applied"
    # C1: sólo códigos y contadores, jamás texto del prompt.
    for entrada in fila["applied_layers"]:
        assert set(entrada) <= {"layer_code", "status", "decision", "count"}


def test_bloqueo_de_guardian_deja_fila_durable_con_su_capa(harness):
    """Punto 2/3: secreto detectado ⇒ `blocked_by_policy` + `secret_detection`.

    La capa sale del veredicto, JAMÁS del nombre del guardián (editable y white-label): un
    rename del cliente no puede reescribir la historia de sus bloqueos.
    """
    client, factory = harness
    calentar_catalogo(client)
    borrar_bloqueos(factory)

    respuesta = pedir(client, f"{CON_PII} La clave es {SECRETO}")
    assert respuesta.status_code == 400, respuesta.text

    filas = filas_bloqueadas(factory)
    assert len(filas) == 1
    fila = filas[0]

    assert fila["compliance_status"] == "blocked_by_policy"
    assert fila["blocked_by_layer"] == "secret_detection"
    assert fila["prompt_tokens"] == 0 and fila["cost_usd"] == 0.0
    assert fila["user_id"] is not None

    # El intento impedido conserva el hallazgo del piso: cuántos datos personales llevaba.
    assert fila["pii_detected"] is True
    assert fila["masked_entities"], "el officer necesita saber QUÉ se intentó filtrar"
    assert sum(e["count"] for e in fila["masked_entities"]) == capa(fila, "pii_detection")["count"]
    # C1: metadata-only. Ni el secreto ni el dato personal tocan la fila.
    texto = str(fila["masked_entities"]) + str(fila["applied_layers"])
    assert SECRETO not in texto and "laura" not in texto.lower()


def test_bloqueo_por_residencia_deja_fila_sin_capa_inventada(harness):
    """Punto 3/3: la residencia NO es una capa del registry, así que `blocked_by_layer`
    queda NULL a propósito — el motivo lo nombra `compliance_status`. Inventar una capa
    "porque suena a cumplimiento" sería falsear el registro."""
    client, factory = harness
    calentar_catalogo(client)
    borrar_bloqueos(factory)

    from src.models.compliance import ComplianceProject
    from src.models.user import User
    db = factory()
    try:
        proyecto = ComplianceProject(id=uuid.uuid4(), name="Residencia UE",
                                     legal_basis="contract", is_active=True,
                                     eu_region_required=True, ai_disclosure_enabled=False)
        db.add(proyecto)
        db.flush()
        usuario = db.query(User).filter(User.username == "admin").first()
        usuario.compliance_project_id = proyecto.id
        db.commit()
        proyecto_id = proyecto.id
    finally:
        db.close()

    try:
        respuesta = pedir(client, SIN_PII, modelo=MODELO_FUERA_UE)
        assert respuesta.status_code == 503, respuesta.text

        filas = filas_bloqueadas(factory)
        assert len(filas) == 1
        assert filas[0]["compliance_status"] == "blocked_residency"
        assert filas[0]["blocked_by_layer"] is None
        assert filas[0]["model"] == MODELO_FUERA_UE
        assert filas[0]["cost_usd"] == 0.0
    finally:
        db = factory()
        try:
            usuario = db.query(User).filter(User.username == "admin").first()
            usuario.compliance_project_id = None
            db.query(ComplianceProject).filter(ComplianceProject.id == proyecto_id).delete()
            db.commit()
        finally:
            db.close()


def test_con_el_enmascarado_apagado_la_fila_del_bloqueo_igual_cuenta_la_pii(harness):
    """El intento impedido conserva el hallazgo del PISO, no el del enmascarado.

    Es el mismo invariante que `test_chat_audit_row_pii` fija para el camino feliz, y en un
    bloqueo importa más: con `pii_masking=off` derivar el desglose de lo enmascarado haría
    que la fila dijera "no hubo datos personales" justo en el pedido que se rechazó por
    intentar sacarlos. La detección es piso y corre igual.
    """
    client, factory = harness
    calentar_catalogo(client)
    borrar_bloqueos(factory)

    from src.models.governance import GovernanceProfile
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    try:
        db.add(GovernanceProfile(tenant_id=DEFAULT_TENANT_ID, scope_type="tenant_default",
                                 scope_value="*", layer_key="pii_masking",
                                 decision="off", updated_by="suite-031"))
        db.commit()
    finally:
        db.close()

    assert pedir(client, f"{CON_PII} La clave es {SECRETO}").status_code == 400

    fila = filas_bloqueadas(factory)[0]
    assert fila["compliance_status"] == "blocked_by_policy"
    assert fila["pii_detected"] is True, (
        "el enmascarado apagado no puede borrar del registro la PII que el pedido llevaba")
    assert sum(e["count"] for e in fila["masked_entities"]) >= 1
    assert capa(fila, "pii_masking")["status"] == "skipped"


def test_el_bloqueo_de_un_pedido_auto_registra_la_decision_de_ruteo(harness, monkeypatch):
    """030 ↔ 031: la fila del bloqueo dice a qué modelo IBA y qué pidió el usuario.

    `request.model` se reasigna al destino efectivo (la fila jamás dice «auto», que no es
    un modelo y no se puede auditar), y lo que el usuario escribió viaja textual en
    `routing_decision.requested`. En un bloqueo esto es lo que permite responder «¿a qué
    proveedor habría ido este intento?» sin dar a entender que el texto viajó.
    """
    client, factory = harness
    calentar_catalogo(client)
    borrar_bloqueos(factory)

    from src.services import auto_router_service
    decision = {"requested": "auto", "route": "codigo", "score": 0.91,
                "model_selected": MODELO, "degraded": False, "reason": None}

    async def _ruta_fija(_mensaje, available_models=None):
        return dict(decision)

    monkeypatch.setattr(auto_router_service, "route", _ruta_fija)

    assert pedir(client, PROHIBIDO, modelo=auto_router_service.AUTO_MODEL).status_code == 400

    from src.models.audit import AuditLog
    db = factory()
    try:
        fila = (db.query(AuditLog)
                .filter(AuditLog.compliance_status.like("blocked%"))
                .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).first())
        assert fila.model == MODELO, "la fila registra el destino efectivo, nunca «auto»"
        assert fila.routing_decision is not None, (
            "sin la decisión, la fila no puede decir qué pidió el usuario ni por qué ruta")
        assert fila.routing_decision["requested"] == "auto"
        assert fila.routing_decision["route"] == "codigo"
    finally:
        db.close()


def test_la_fila_existe_aunque_el_redis_del_monitor_este_caido(harness, monkeypatch):
    """La durabilidad NO puede depender de la vitrina.

    Son dos registros distintos: el efímero (300 s, best-effort) y el durable. Con Redis
    caído el feed no muestra nada — y ese es justo el escenario donde el registro durable
    tiene que estar, porque es el único que queda.
    """
    client, factory = harness
    calentar_catalogo(client)
    borrar_bloqueos(factory)

    from src.api import gateway
    monkeypatch.setattr(gateway, "get_redis", lambda: None)

    respuesta = pedir(client, PROHIBIDO)
    assert respuesta.status_code == 400, respuesta.text

    filas = filas_bloqueadas(factory)
    assert len(filas) == 1
    assert filas[0]["compliance_status"] == "blocked_prohibited"


def test_el_evento_efimero_se_conserva_junto_a_la_fila(harness, eventos_de_vitrina):
    """La vitrina no se sacrifica por la durabilidad: los dos registros conviven y cuentan
    la MISMA historia (mismo estado)."""
    client, factory = harness
    calentar_catalogo(client)
    borrar_bloqueos(factory)

    assert pedir(client, PROHIBIDO).status_code == 400

    assert eventos_de_vitrina, "un bloqueo sin evento de monitor es un bloqueo invisible"
    assert eventos_de_vitrina[-1]["status"] == "blocked_prohibited"
    assert filas_bloqueadas(factory)[0]["compliance_status"] == eventos_de_vitrina[-1]["status"]


# ── US2 en el plano chat: `open` no cambia la respuesta, `closed` no gasta proveedor ──


def test_open_con_el_escritor_caido_mantiene_el_4xx_y_cuenta_la_perdida(
        harness, monkeypatch, escritor_caido):
    """`open` EXPLÍCITO: que la auditoría esté caída NO puede convertir un bloqueo en un
    error distinto para el usuario. Pero la pérdida deja de ser silenciosa.

    El `setenv` es de la spec 038 (SC-002) y va ANTES del calentamiento: la env ausente ya
    no resuelve a `open` sino a `policy`, y con `escritor_caido` activo el pedido de
    calentamiento —que es tráfico normal— corta con 503 porque el admin del harness no
    resuelve riesgo (`None` ⇒ corta, matriz D2). Sin el override explícito este test medía
    el default, no `open`; los asserts de abajo no se tocaron.
    """
    client, _ = harness
    from src.services import audit_service
    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, "open")
    calentar_catalogo(client)

    respuesta = pedir(client, PROHIBIDO)

    assert respuesta.status_code == 400, "el bloqueo se sigue comunicando igual"
    assert "social scoring" in respuesta.json()["detail"].lower() or respuesta.json()["detail"]
    assert escritor_caido, "una fila perdida sin contador es exactamente el agujero de la spec"


def test_open_no_hace_pre_check_de_escribibilidad(harness, monkeypatch):
    """En `open` la instalación no paga NI un `SELECT 1` extra por request (D4)."""
    client, _ = harness
    calentar_catalogo(client)

    # `open` EXPLÍCITO (spec 038 SC-002), no el default del fixture del módulo: desde D1 la
    # env ausente resuelve a `policy`, y `policy` SÍ paga el pre-check cuando el pedido no
    # resuelve un riesgo bajo (el admin de este harness no tiene `risk_level` ni grupo con
    # `default_risk_level`, así que la matriz D2 lo trata como `None` ⇒ corta). Sin este
    # `setenv` el `llamadas == []` de abajo mediría el corte por `None`, no la exención de
    # `open` que el nombre del test declara.
    from src.services import audit_service
    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, "open")

    from src.api import chat
    llamadas = []
    monkeypatch.setattr(chat, "audit_writable", lambda db: llamadas.append(db) or True)

    assert pedir(client, SIN_PII).status_code == 200
    assert llamadas == [], "el pre-check es exclusivo del modo closed"


def test_closed_con_auditoria_caida_responde_503_sin_llamar_al_proveedor(
        harness, monkeypatch, motor):
    """SC-002 `closed`: 503 honesto ANTES del proveedor (FR-005 es literal — no se gasta
    dinero en tráfico que no se va a poder registrar)."""
    client, _ = harness
    calentar_catalogo(client)
    motor.posts.clear()

    from src.api import chat
    from src.services import audit_service
    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, "closed")
    monkeypatch.setattr(chat, "audit_writable", lambda _db: False)

    respuesta = pedir(client, SIN_PII)

    assert respuesta.status_code == 503, respuesta.text
    assert respuesta.json()["detail"] == DETALLE_CLOSED
    assert motor.posts == [], "en closed no puede salir UNA sola llamada al proveedor"


def test_closed_con_la_base_sana_no_estorba_el_camino_feliz(harness, monkeypatch, motor):
    """El fail-closed sólo actúa cuando de verdad no se puede escribir."""
    client, _ = harness
    calentar_catalogo(client)
    motor.posts.clear()

    from src.services import audit_service
    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, "closed")

    assert pedir(client, SIN_PII).status_code == 200
    assert len(motor.posts) == 1


def test_closed_con_la_fila_del_bloqueo_perdida_responde_503(
        harness, monkeypatch, escritor_caido, eventos_de_vitrina):
    """Bloqueo + `closed` + escritura imposible ⇒ 503 honesto (no el 400 del bloqueo).

    La instalación pidió «sin auditoría no hay servicio», y un 400 sin fila diría "te
    bloqueamos y quedó registrado" cuando no quedó nada. La vitrina se publica igual: el
    bloqueo ocurrió, y el operador lo necesita ver mientras diagnostica la caída.
    """
    client, _ = harness
    from src.services import audit_service
    # El CALENTAMIENTO no es lo que este test mide, y con `escritor_caido` activo tiene que
    # poder pasar: en la env ausente (=`policy` desde D1) un pedido normal del admin —que no
    # resuelve riesgo— corta con 503, así que se calienta en `open` explícito y recién
    # después se pone el `closed` que el test SÍ mide. Los asserts no cambiaron.
    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, "open")
    calentar_catalogo(client)

    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, "closed")

    respuesta = pedir(client, PROHIBIDO)

    assert respuesta.status_code == 503, respuesta.text
    assert respuesta.json()["detail"] == DETALLE_CLOSED
    assert escritor_caido, "la pérdida se cuenta también en closed (el health la muestra)"
    assert eventos_de_vitrina[-1]["status"] == "blocked_prohibited"


# ── FR-010: nada de esto toca la hash-chain de licencias ──────────────────────────


def test_las_filas_de_bloqueo_no_contaminan_la_cadena_de_licencias(harness):
    """Los eslabones de la 021 son `model='license'`; una fila de bloqueo nunca lo es, así
    que la verificación de la cadena no ve ninguna fila nueva (SC-003)."""
    client, factory = harness
    calentar_catalogo(client)
    borrar_bloqueos(factory)

    assert pedir(client, PROHIBIDO).status_code == 400

    for fila in filas_bloqueadas(factory):
        assert fila["model"] != "license"
