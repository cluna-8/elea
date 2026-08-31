"""Negar servicio por PRESUPUESTO también deja fila durable (issue #157).

Hallazgo de La ITV en el gate 125 (18 casos reales en 30 minutos): el 402 de presupuesto de
`/api/v1/chat/completions` corta antes de cualquier escritura de auditoría. El único rastro
es el dict `verdicts` en memoria, que muere con el request. El officer no puede reconstruir
«a quién le negamos servicio por presupuesto y cuándo».

El patrón que ya resuelve esto en este mismo endpoint es **registrar → bloquear**: el 503 de
admisión por capacidad (#135) escribe su fila ANTES de responder. Lo que se fija acá es lo
mismo para el 402, y con la misma semántica de balde:

* el rechazo por presupuesto **NO es un bloqueo de política** (ninguna capa impidió nada:
  es un tope económico nuestro), así que no puede contarse en `LIKE 'blocked%'`;
* tampoco es un pedido **permitido** (nunca se sirvió), así que tampoco puede caer en el
  `else` del filtro binario del listado — la exclusión que hereda del prefijo `rejected%`
  (`services/retention/classifier.py`, `es_rechazo()`; hasta la 018 vivía en `api/audit.py`),
  la misma que se le dio a `rejected_saturated`;
* pero sí es auditoría durable: **visible sin filtro** de estado.

El último bloque cubre el PRECIO de registrar primero: la respuesta del gate deja de ser
sólo función del presupuesto y pasa a depender también de la salud de la auditoría (402 en
`audit_fail=open`, 503 en `closed`). Es observable por el cliente, así que se fija con tests
y no con un comentario.

Cada test afirma PRIMERO que el escenario se dio de verdad (402 con el copy de presupuesto)
y recién después el invariante: un test que muere en plomería no prueba nada.

El escenario NO se monkeypatchea: se carga un `Budget` real del usuario con el gasto por
encima del techo, que es exactamente el estado que tenía la sede en el gate 125.
"""
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient  # noqa: F401 — el harness devuelve uno

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import admin_headers, build_app_client  # noqa: E402

require_postgres()

DB = "sentinel_test_chat_budget_audit"
CHAT = "/api/v1/chat/completions"
LOGS = "/api/v1/audit-logs"
MODELO = "ollama-qwen3-4b"
SIN_PII = "Resumime en una línea qué hace este servicio."

# El `compliance_status` del rechazo por presupuesto. Literal y no import del código de
# producto a propósito (mismo criterio que `test_audit_filtro_estado.py`): lo que se prueba
# es el CONTRATO contra el valor persistido, y un import haría pasar el test aunque la
# constante se renombrara de las dos puntas a la vez.
PRESUPUESTO = "rejected_budget"

# Copy ÚNICO del 503 de `audit_fail=closed` (`audit_service.AUDIT_CLOSED_DETAIL`; vivía en
# `chat.py` hasta que T007 lo subió al módulo que ya era dueño de la decisión). Literal por
# el mismo motivo que arriba, y además porque es lo que distingue este 503 de cualquier otro:
# si el test se conformara con «status_code == 503» pasaría con un 503 de otra causa.
DETALLE_CLOSED = "auditoría no disponible — la instalación exige registro (audit_fail=closed)"


# ── Doble del motor ───────────────────────────────────────────────────────────────


class _MotorProhibido:
    """El motor NO se puede tocar en este camino: el 402 corta mucho antes.

    Si alguna vez se llamara, el test rompe con un mensaje que dice qué se rompió, en vez
    de pasar de casualidad porque había un modelo levantado.
    """

    @staticmethod
    def AsyncClient(*_args, **_kwargs):  # noqa: N802 — espeja el nombre real
        raise AssertionError(
            "el pedido llegó al motor: el gate de presupuesto no cortó y el test ya no "
            "está midiendo lo que dice medir")


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    client.headers.update(admin_headers(client))
    yield client, factory
    cleanup()


@pytest.fixture(autouse=True)
def motor_prohibido(monkeypatch):
    from src.api import chat
    monkeypatch.setattr(chat, "httpx", _MotorProhibido)


@pytest.fixture
def presupuesto_agotado(harness):
    """Techo real, gastado real: el estado de la sede en el gate 125.

    Se limpian las filas de auditoría en el mismo paso para que contar filas sea una
    afirmación sobre ESTE pedido y no sobre la historia del módulo.
    """
    _, factory = harness
    from src.models.audit import AuditLog
    from src.models.budget import Budget
    from src.models.user import User

    db = factory()
    try:
        usuario = db.query(User).filter(User.username == "admin").first()
        assert usuario is not None, "el bootstrap del admin no dejó usuario: escenario no armado"
        db.query(AuditLog).delete()
        db.query(Budget).delete()
        db.add(Budget(
            id=uuid.uuid4(), tenant_id=usuario.tenant_id, user_id=usuario.id,
            max_spend_usd=10, current_spend_usd=10, max_tokens=1000, current_tokens=1000,
            reset_period="monthly",
        ))
        db.commit()
        datos = {"user_id": str(usuario.id), "tenant_id": str(usuario.tenant_id)}
    finally:
        db.close()
    return datos


@pytest.fixture
def modo_open_por_defecto(monkeypatch):
    """`SENTINEL_AUDIT_FAIL=open` EXPLÍCITO — la env es global al proceso y sin esto un test que
    corriera después de uno que setea `closed` heredaría el modo y afirmaría sobre un
    escenario que no es el que dice su nombre.

    Hasta la spec 038 esto era un `delenv`: el default era `open`, así que borrar la env y
    pedir `open` eran lo mismo. Desde D1 **ya no**: la env ausente resuelve a `policy`, y
    `policy` con un usuario que no resuelve riesgo corta el pedido (matriz D2). El único
    test que pide esta fixture se llama `test_open_…` y mide la semántica de `open`, así que
    lo que tiene que fijar es el override explícito, no el default de turno. El nombre se
    conserva porque sigue describiendo lo que hace.
    """
    from src.services import audit_service
    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, "open")


@pytest.fixture
def escritor_caido(monkeypatch):
    """La base de auditoría no acepta la fila: el escritor agota su presupuesto.

    Copiado del patrón de `test_chat_block_audit.py`: se rompe la CONSTRUCCIÓN de la fila
    dentro del servicio en vez de tirar Postgres, así el test mide la política de
    degradación y no la disponibilidad del stack. El backoff se neutraliza (el presupuesto
    de reintentos ya lo verifica el unit test de T002) y `record_audit_loss` se envuelve en
    un espía que **igual llama al real**: lo que se afirma es que la pérdida se cuenta, no
    que se haya reemplazado por un doble.
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


def filas(factory, estado):
    """Proyección de la fila del rechazo. Sólo campos que algún test AFIRMA.

    `latency_ms` quedó FUERA a propósito: no hay nada real que afirmar sobre él acá. La
    columna es `nullable=False` (`models/audit.py:28`), así que un `is not None` lo garantiza
    el esquema y no el código de este PR; y `0` es un valor legítimo —el rechazo corta antes
    del proveedor y suele tardar menos de 1 ms—, así que tampoco hay cota inferior que
    afirmar. Un campo proyectado que nadie mira se lee como cobertura y no lo es.
    """
    from src.models.audit import AuditLog
    db = factory()
    try:
        return [{"compliance_status": f.compliance_status, "model": f.model,
                 "prompt_tokens": f.prompt_tokens, "completion_tokens": f.completion_tokens,
                 "cost_usd": float(f.cost_usd or 0), "user_id": str(f.user_id) if f.user_id else None,
                 "tenant_id": str(f.tenant_id) if f.tenant_id else None,
                 "api_key_id": f.api_key_id, "pii_detected": f.pii_detected,
                 "routing_decision": f.routing_decision}
                for f in db.query(AuditLog)
                .filter(AuditLog.compliance_status == estado).all()]
    finally:
        db.close()


def filas_estilo_bloqueo(factory):
    """El filtro CANÓNICO de compliance. Un rechazo por presupuesto no puede aparecer acá."""
    from src.models.audit import AuditLog
    db = factory()
    try:
        return [f.compliance_status for f in db.query(AuditLog)
                .filter(AuditLog.compliance_status.like("blocked%")).all()]
    finally:
        db.close()


def estados(payload):
    return sorted(fila["compliance_status"] for fila in payload["logs"])


def pedir(client, modelo=MODELO):
    return client.post(CHAT, json={"message": SIN_PII, "model": modelo})


# ── Tests ─────────────────────────────────────────────────────────────────────────


def test_el_402_por_presupuesto_deja_una_fila_durable(harness, presupuesto_agotado):
    """El invariante del #157. Negar servicio sin fila durable es tan grave como bloquear
    sin ella: no hay forma de responderle al officer «a quién le negamos y cuándo»."""
    client, factory = harness

    respuesta = pedir(client)

    # Primero: el escenario se dio de verdad, y es el de presupuesto (no otro 402).
    assert respuesta.status_code == 402, respuesta.text
    assert "Presupuesto" in respuesta.json()["detail"], respuesta.text

    # Recién ahora, el invariante.
    registradas = filas(factory, PRESUPUESTO)
    assert len(registradas) == 1, (
        f"el 402 de presupuesto no dejó fila durable (filas halladas: {registradas})")

    fila = registradas[0]
    # Tokens y coste por contrato del rechazo: no se consumió nada, y decir otra cosa
    # ensuciaría el gasto del cliente con pedidos que nunca salieron.
    assert fila["prompt_tokens"] == 0 and fila["completion_tokens"] == 0, fila
    assert fila["cost_usd"] == 0.0, fila
    # Ningún detector corrió (el pipeline arranca después del gate): la fila no puede
    # afirmar que se miró y no había.
    assert fila["pii_detected"] is False, fila
    # Atribución: sin esto la fila existe pero no sirve para la pregunta que motivó el issue.
    assert fila["user_id"] == presupuesto_agotado["user_id"], fila
    assert fila["tenant_id"] == presupuesto_agotado["tenant_id"], fila
    # Camino JWT: no hay Connection. `None` es el valor honesto, no un placeholder.
    assert fila["api_key_id"] is None, fila
    # El auto-router corre DESPUÉS de este gate: no hubo decisión de ruteo que registrar.
    assert fila["routing_decision"] is None, fila


def test_la_fila_del_402_audita_el_modelo_que_el_usuario_pidio(harness, presupuesto_agotado):
    """El gate corta ANTES del auto-router, así que con `model="auto"` no hay modelo
    efectivo todavía. Lo honesto es auditar lo que el usuario pidió —«auto»— y no elegir
    un destino por nuestra cuenta que nadie eligió y que además se podría pricear."""
    client, factory = harness

    respuesta = pedir(client, modelo="auto")

    assert respuesta.status_code == 402, respuesta.text
    registradas = filas(factory, PRESUPUESTO)
    assert len(registradas) == 1, registradas
    assert registradas[0]["model"] == "auto", registradas[0]


def test_el_rechazo_por_presupuesto_no_es_un_bloqueo_de_politica(harness, presupuesto_agotado):
    """Ninguna capa impidió nada: no hubo dato personal, ni secreto, ni práctica prohibida.
    Contarlo entre los bloqueos le mentiría al officer sobre cuántos intentos se bloquearon."""
    client, factory = harness

    assert pedir(client).status_code == 402
    assert filas(factory, PRESUPUESTO), "el escenario no llegó a escribir la fila del rechazo"

    assert filas_estilo_bloqueo(factory) == [], (
        "el rechazo por presupuesto entró al filtro canónico de bloqueos de política")
    payload = client.get(LOGS, params={"estado": "bloqueados"}).json()
    assert PRESUPUESTO not in estados(payload), payload


def test_el_rechazo_por_presupuesto_tampoco_se_cuenta_como_permitido(harness, presupuesto_agotado):
    """La otra mitad: el pedido nunca se sirvió. Si el literal no heredara la exclusión de
    `rejected%`, caería en el `else` del filtro binario y se informaría como PERMITIDO —
    justo la mentira que H4 del #135 vino a cerrar."""
    client, factory = harness

    assert pedir(client).status_code == 402
    # Se afirma sobre la fila REAL del rechazo, no sobre el literal esperado: preguntar sólo
    # `PRESUPUESTO not in estados(...)` pasaría vacío si alguien renombra el estado a algo
    # sin prefijo `rejected` y lo manda al balde de permitidos, que es el mutante a matar.
    todas = client.get(LOGS).json()
    assert todas["total"] == 1, todas
    (estado_real,) = estados(todas)

    payload = client.get(LOGS, params={"estado": "permitidos"}).json()
    assert payload["total"] == 0, payload
    assert estado_real not in estados(payload), (estado_real, payload)


def test_sin_filtro_el_rechazo_por_presupuesto_es_visible(harness, presupuesto_agotado):
    """Dejarlo fuera del filtro binario no es esconderlo: es la fila que contesta la
    pregunta del officer, y tiene que poder verla."""
    client, _ = harness

    assert pedir(client).status_code == 402

    payload = client.get(LOGS).json()
    assert PRESUPUESTO in estados(payload), payload


# ── El cruce con `audit_fail`: registrar PRIMERO cambia lo que el cliente ve ───────
#
# Meter la fila antes de responder no es gratis: el registro puede fallar, y en
# `audit_fail=closed` ese fallo tiene su propia respuesta. O sea que el CÓDIGO HTTP del
# rechazo por presupuesto pasa a depender de la salud de la auditoría — 402 en `open`, 503
# en `closed`. Es una consecuencia observable desde afuera y por eso se fija con tests, no
# con un comentario: el gemelo de saturación (#135) tuvo que aprender lo mismo en su gate.


def test_open_con_la_auditoria_caida_el_cliente_igual_recibe_su_402(
        harness, presupuesto_agotado, modo_open_por_defecto, escritor_caido):
    """`open` (default): que la base de auditoría esté caída NO puede cambiarle la respuesta
    al usuario. Su presupuesto sigue agotado y el 402 es la verdad del pedido; devolverle un
    503 sería culparlo de un problema nuestro. La fila se pierde, pero NO en silencio."""
    client, factory = harness

    respuesta = pedir(client)

    assert respuesta.status_code == 402, respuesta.text
    assert "Presupuesto" in respuesta.json()["detail"], respuesta.text
    assert filas(factory, PRESUPUESTO) == [], (
        "el escritor estaba caído: si hay fila, el escenario no se dio y el test no prueba nada")
    assert escritor_caido, (
        "una fila perdida sin contador es exactamente el agujero que cerró la US2 de la 031")


def test_closed_con_la_auditoria_caida_el_402_se_convierte_en_503(
        harness, presupuesto_agotado, escritor_caido, monkeypatch):
    """`closed` + auditoría caída ⇒ **503 honesto en vez del 402**, y sin fila.

    La instalación pidió «sin registro no hay servicio». Un 402 sin fila le diría al cliente
    «te negamos servicio por presupuesto y quedó registrado» cuando no quedó nada, y sería
    justo la afirmación que el #157 vino a poder respaldar. El precio de registrar primero
    es este: el código que ve el cliente cambia cuando la auditoría no está.
    """
    client, factory = harness

    from src.services import audit_service
    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, "closed")

    respuesta = pedir(client)

    assert respuesta.status_code == 503, respuesta.text
    # Es el 503 de la AUDITORÍA, no otro 503 cualquiera: el copy es lo que prueba que se
    # ejercitó este cruce y no un fallo de plomería que pasaría igual de "verde".
    assert respuesta.json()["detail"] == DETALLE_CLOSED, respuesta.text
    assert filas(factory, PRESUPUESTO) == [], (
        "en closed no puede quedar fila: si la escritura hubiera funcionado, el cliente "
        "habría recibido su 402 y este test estaría midiendo otra cosa")
    assert escritor_caido, "la pérdida se cuenta también en closed (el health la muestra)"
