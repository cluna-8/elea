"""`BASA_AUDIT_FAIL=policy` en el plano chat (spec 038, Phase 2, T006-T008).

`test_chat_block_audit.py` fija el contrato de `open`/`closed` (spec 031). Esta spec agrega
un TERCER modo — y lo vuelve el DEFAULT (D1: env ausente/ilegible ⇒ `policy`, ya no `open`) —
que no es un override global sino una matriz por riesgo (D2, `audit_fail_decision()`): el
pedido se sirve sin fila si su `applied_risk_level` es `minimal`/`limited`, y corta (503) si
es `high_risk_annex1`/`high_risk_annex3` o si no se resolvió ningún riesgo (`None`).

Lo que se fija acá:

- FR-002 + el punto de costo (D4): tráfico de bajo riesgo NO paga el pre-check de
  escribibilidad — el mismo invariante que `test_open_no_hace_pre_check_de_escribibilidad`
  fija para `open`, pero ahora bajo el modo que es DEFAULT;
- el corte de `policy` es honesto y distinto del de `closed`: el `detail` nombra
  `(audit_fail=policy)`, no `(audit_fail=closed)` — confundirlos manda al operador a buscar
  una env que nunca seteó;
- fail-closed hacia lo reversible (D2): sin riesgo resuelto, `policy` corta igual que ante
  riesgo alto;
- SC-002: `open`/`closed` puestos EXPLÍCITOS en la env siguen siendo overrides globales que
  ignoran la matriz por completo, en los dos sentidos (el permisivo y el restrictivo).

Mismo harness, mismo doble de motor con contador y misma convención de nombres que
`test_chat_block_audit.py` — se lee ese archivo primero si hace falta más contexto de las
fixtures compartidas.
"""
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import admin_headers, build_app_client  # noqa: E402

require_postgres()

DB = "basa_test_chat_audit_policy"

CHAT = "/api/v1/chat/completions"
MODELO = "ollama-qwen3-4b"

SIN_PII = "Resumime en una línea qué hace este servicio."

DETALLE_POLICY = (
    "auditoría no disponible — este pedido no se sirve sin registro por su nivel de riesgo "
    "(audit_fail=policy)"
)
DETALLE_CLOSED = "auditoría no disponible — la instalación exige registro (audit_fail=closed)"


# ── Doble del motor, con contador (idéntico a test_chat_block_audit.py) ───────────


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
    """Cuenta los POST que llegarían al proveedor. Es la evidencia de que `policy` cortó
    ANTES de gastar el motor, igual que `closed` en el otro archivo."""

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
    """Motor mockeado SIEMPRE: lo que se mide es si se lo llamó, no si hay modelo."""
    from src.api import chat
    contador = _MotorContador()
    monkeypatch.setattr(chat, "httpx", contador.httpx())
    return contador


@pytest.fixture(autouse=True)
def modo_policy_por_defecto(monkeypatch):
    """Cada test parte de la env AUSENTE — el modo efectivo desde D1 es `policy`, el
    default de la spec 038. Los tests de override (`closed`/`open` explícitos) la pisan
    ellos mismos con su propio `monkeypatch.setenv`."""
    from src.services import audit_service
    monkeypatch.delenv(audit_service.AUDIT_FAIL_ENV, raising=False)


@pytest.fixture(autouse=True)
def limpiar(harness):
    """Postura y catálogo intactos entre tests, y el `risk_level` del admin vuelve a
    `None` — sin esto un test de riesgo bajo dejaría el siguiente (que espera `None`
    sin resolver) leyendo el riesgo que fijó el anterior."""
    yield
    _, factory = harness
    from src.models.governance import GovernanceProfile
    from src.models.guardian import Guardian
    from src.models.policy import SecurityPolicy
    from src.models.user import User
    db = factory()
    try:
        db.query(GovernanceProfile).delete()
        for guardian in db.query(Guardian).all():
            if guardian.guardian_type in ("pii_masking", "secret_detection"):
                guardian.is_active = True
        for policy in db.query(SecurityPolicy).all():
            policy.ai_act_mode = True
        usuario = db.query(User).filter(User.username == "admin").first()
        if usuario is not None:
            usuario.risk_level = None
        db.commit()
    finally:
        db.close()


# ── Helpers ───────────────────────────────────────────────────────────────────────


def pedir(client, mensaje, modelo=MODELO, **extra):
    return client.post(CHAT, json={"message": mensaje, "model": modelo, **extra})


def calentar_catalogo(client):
    """Primer pedido: deja sembrado el catálogo de 9 guardianes (el seed borra y re-siembra
    cuando hay menos de 9 filas, así que un cambio previo se perdería sin esto).

    Corre ANTES de `fijar_riesgo_admin` y de cualquier mock de `audit_writable`, con
    `risk_level=None` (el `limpiar` del test anterior lo deja así). En `policy` eso paga el
    pre-check, pero contra el `audit_writable` REAL — la sesión de auditoría de este harness
    es Postgres genuino y escribible —, así que sigue devolviendo 200 igual que en
    `test_chat_block_audit.py`."""
    respuesta = pedir(client, SIN_PII)
    assert respuesta.status_code == 200, respuesta.text


def fijar_riesgo_admin(factory, risk_level):
    """Puebla `user.risk_level` del admin (el usuario con el que `harness` hace los
    pedidos, vía JWT de sesión — no lleva `api_key_obj` ni `group`) escribiendo el objeto
    ORM directo en la sesión de test.

    Por qué esta vía y no el alta: `POST /users` DESCARTA `risk_level` — el `User(...)` de
    `backend/src/api/users.py` construye con una lista explícita de columnas que no lo
    incluye, así que mandarlo en el body del alta no lo persiste (dato medido leyendo ese
    endpoint, no supuesto). `PUT /users/{id}` sí lo persiste (usa `setattr` genérico) y
    `PUT /groups/{id}/compliance` serviría para `group.default_risk_level`, pero el admin
    de este harness no tiene `group_id` (el bootstrap lo crea sin grupo — ver
    `_bootstrap_admin_si_sin_dueno` en `users.py`), así que la vía por grupo no aplicaría a
    este usuario. La escritura ORM directa es además el patrón que ya usa
    `test_chat_block_audit.py` para mutar `compliance_project_id` del mismo admin
    (`test_bloqueo_por_residencia_deja_fila_sin_capa_inventada`): mismo mecanismo, mismo
    usuario, sin sumar una vía nueva al harness.
    """
    from src.models.user import User
    db = factory()
    try:
        usuario = db.query(User).filter(User.username == "admin").first()
        assert usuario is not None, "el bootstrap del admin corre en `admin_headers`"
        usuario.risk_level = risk_level
        db.commit()
    finally:
        db.close()


# ── FR-002 + D4: el riesgo bajo no paga el pre-check ───────────────────────────────


def test_policy_con_riesgo_bajo_sirve_sin_pagar_pre_check(harness, monkeypatch):
    """`policy` (default, env ausente) + `risk_level=minimal` ⇒ 200 y CERO llamadas a
    `audit_writable`. Es el mismo invariante de costo que `open` fija en el otro archivo,
    pero acá bajo el modo que HOY es el default de instalación: el tráfico normal no puede
    empezar a pagar un SELECT por el sólo hecho de que `open` dejó de ser el default."""
    client, factory = harness
    calentar_catalogo(client)
    fijar_riesgo_admin(factory, "minimal")

    from src.api import chat
    llamadas = []
    monkeypatch.setattr(chat, "audit_writable", lambda db: llamadas.append(db) or True)

    respuesta = pedir(client, SIN_PII)

    assert respuesta.status_code == 200, respuesta.text
    assert llamadas == [], "riesgo bajo: el pre-check de policy no debe correr (D4)"


# ── El corte de policy es 503 honesto y distinto del de closed ────────────────────


def test_policy_con_riesgo_alto_y_auditoria_caida_corta_con_503(harness, monkeypatch, motor):
    """`policy` + `risk_level=high_risk_annex3` + auditoría caída ⇒ 503 ANTES del proveedor,
    con el texto de `policy` (no el de `closed`) en el `detail` (FR-005 + D2)."""
    client, factory = harness
    calentar_catalogo(client)
    fijar_riesgo_admin(factory, "high_risk_annex3")
    motor.posts.clear()

    from src.api import chat
    monkeypatch.setattr(chat, "audit_writable", lambda _db: False)

    respuesta = pedir(client, SIN_PII)

    assert respuesta.status_code == 503, respuesta.text
    assert respuesta.json()["detail"] == DETALLE_POLICY
    assert motor.posts == [], "riesgo alto + auditoría caída: cero POST al proveedor"


def test_policy_sin_riesgo_resuelto_corta(harness, monkeypatch, motor):
    """`policy` + sin `risk_level` propio ni grupo con `default_risk_level` ⇒ `None` ⇒
    corta (D2: fail-closed hacia lo reversible — un pedido que no demostró ser de bajo
    riesgo se trata como si no lo fuera, igual que annex1/annex3)."""
    client, factory = harness
    calentar_catalogo(client)
    fijar_riesgo_admin(factory, None)  # explícito: el admin no arrastra riesgo de otro test
    motor.posts.clear()

    from src.api import chat
    llamadas = []
    monkeypatch.setattr(chat, "audit_writable", lambda db: llamadas.append(db) or False)

    respuesta = pedir(client, SIN_PII)

    assert respuesta.status_code == 503, respuesta.text
    assert respuesta.json()["detail"] == DETALLE_POLICY
    assert llamadas, "riesgo sin resolver: SÍ tiene que pagar el pre-check (a diferencia del bajo)"
    assert motor.posts == [], "corta antes de gastar proveedor, igual que con riesgo alto"


# ── SC-002: `open`/`closed` explícitos siguen siendo overrides globales ───────────


def test_closed_explicito_no_cambia_con_riesgo_bajo(harness, monkeypatch, motor):
    """`BASA_AUDIT_FAIL=closed` EXPLÍCITO + `risk_level=minimal` ⇒ igual corta (503) con el
    texto de `closed`, no el de `policy` — el override global ignora la matriz D2 por
    completo, incluso para el riesgo que `policy` serviría sin pestañear (SC-002)."""
    client, factory = harness
    calentar_catalogo(client)
    fijar_riesgo_admin(factory, "minimal")
    motor.posts.clear()

    from src.services import audit_service
    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, "closed")
    from src.api import chat
    monkeypatch.setattr(chat, "audit_writable", lambda _db: False)

    respuesta = pedir(client, SIN_PII)

    assert respuesta.status_code == 503, respuesta.text
    assert respuesta.json()["detail"] == DETALLE_CLOSED, (
        "closed explícito conserva SU texto, no el de policy")
    assert motor.posts == []


def test_open_explicito_sirve_con_riesgo_alto(harness, monkeypatch, motor):
    """`BASA_AUDIT_FAIL=open` EXPLÍCITO + `risk_level=high_risk_annex3` + auditoría caída ⇒
    se SIRVE (200) y `audit_writable` ni se consulta — el override permisivo también ignora
    la matriz D2 por completo, del otro lado (SC-002)."""
    client, factory = harness
    calentar_catalogo(client)
    fijar_riesgo_admin(factory, "high_risk_annex3")
    motor.posts.clear()

    from src.services import audit_service
    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, "open")
    from src.api import chat
    llamadas = []
    monkeypatch.setattr(chat, "audit_writable", lambda db: llamadas.append(db) or False)

    respuesta = pedir(client, SIN_PII)

    assert respuesta.status_code == 200, respuesta.text
    assert llamadas == [], "open explícito: ni el riesgo alto paga el pre-check"
    assert len(motor.posts) == 1, "se sirvió de verdad: el proveedor se llamó una vez"


# ── El P1 que este PR paga: la fila FINAL perdida es 503, no 500 ──────────────────
#
# Los cinco testigos de arriba cortan todos en el PRE-check (`audit_writable` mockeado en
# `False`): miden la matriz D2, no el `try/except` que la 038 agrega alrededor del
# `log_transaction` del camino feliz. Ese except es OTRO hecho y necesita su propio
# testigo, porque el escenario que cubre es el opuesto: el pre-check contestó que la base
# estaba SANA, el pedido se sirvió —el proveedor ya cobró— y es el INSERT final el que se
# agota después. Sin estos tests el except nace vacuo, y es lo primero que una
# refactorización futura borra en silencio.
#
# Qué pasaba sin él, MEDIDO en control (mutación del handler, no razonamiento sobre el
# fuente): `AuditUnavailableError` sube hasta el `@app.exception_handler(Exception)` de
# `main.py` —la app no tiene handler dedicado para ese tipo— y el cliente recibe
# **500 `InternalServerError`** con la respuesta del proveedor pagada y tirada. Ojo si se
# rehace ese control desde acá: bajo `TestClient` con `raise_server_exceptions=True` (el
# default, y el de este harness) la excepción se PROPAGA en vez de verse como respuesta —
# el 500 es lo que ve un cliente real contra uvicorn, no lo que devuelve `client.post`.


def romper_escritor(monkeypatch):
    """Rompe la CONSTRUCCIÓN de la fila dentro del escritor. Devuelve la lista de pérdidas.

    Función y no fixture a propósito: el `calentar_catalogo` de cada test es tráfico normal
    y en `closed` —o en `policy` con el admin sin riesgo resuelto— cortaría con 503 si el
    escritor ya estuviera roto antes del cuerpo del test. Una fixture se activa antes de la
    primera línea y no deja ventana sana para calentar. El `escritor_caido` de
    `test_chat_block_audit.py` sí puede ser fixture porque allá el calentamiento corre bajo
    `open` EXPLÍCITO, que sirve pase lo que pase.

    Se rompe el escritor y no Postgres para medir la POLÍTICA de degradación y no la
    disponibilidad del stack (mismo criterio que el otro archivo). El backoff se neutraliza
    —el presupuesto de reintentos ya lo pinea el unit test de T002— y `record_audit_loss` se
    envuelve en un espía que IGUAL llama al real: lo que se afirma es que la pérdida se
    cuenta, no que se la haya reemplazado por un doble.
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


def espiar_pre_check(monkeypatch):
    """Espía `chat.audit_writable` SIN reemplazarlo: junta lo que contestó el real contra el
    Postgres del harness.

    `[True]` es la prueba de que el corte ocurrió DESPUÉS del pre-check —la base estaba sana
    cuando se la sondeó—, que es exactamente lo que distingue estos testigos de los cinco de
    arriba; `[]` prueba que la matriz ni lo consultó (D4). Un mock que devuelve `True` fijo
    no serviría: el punto es que la sonda REAL diga que sí.
    """
    from src.api import chat
    real = chat.audit_writable
    sondas = []

    def _espia(db):
        resultado = real(db)
        sondas.append(resultado)
        return resultado

    monkeypatch.setattr(chat, "audit_writable", _espia)
    return sondas


def perdidas_del_escritor(perdidas):
    """Filtra las que contó `log_transaction`.

    `record_audit_loss` es un contador COMPARTIDO —lo reutiliza la marca de degradación NLP
    cuando Redis no acepta la escritura (`record_nlp_degradation`)—, así que un
    `len(perdidas) == 1` a secas mediría de más el día que el analyzer no responda en el
    runner, y el fallo sería un falso rojo ajeno a esta política.
    """
    return [p for p in perdidas if p.startswith("log_transaction/")]


def test_closed_con_la_fila_final_perdida_devuelve_503_y_no_500(harness, monkeypatch, motor):
    """Brazo `closed` del P1: pre-check SANO + INSERT final agotado ⇒ 503 con el copy de
    `closed` y el proveedor ya llamado. Preexistente de la 031 —sólo alcanzable en `closed`
    explícito— y por eso se paga acá: la 038 lo vuelve alcanzable para cualquier
    instalación, porque `policy` es el default y también corta."""
    client, _ = harness
    calentar_catalogo(client)  # con el escritor todavía sano

    from src.services import audit_service
    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, "closed")
    sondas = espiar_pre_check(monkeypatch)
    perdidas = romper_escritor(monkeypatch)
    motor.posts.clear()

    respuesta = pedir(client, SIN_PII)

    assert respuesta.status_code == 503, respuesta.text
    assert respuesta.json()["detail"] == DETALLE_CLOSED
    assert sondas == [True], (
        "el corte tiene que ser POST-pre-check: la sonda real contestó que la base estaba sana")
    assert len(motor.posts) == 1, "el proveedor YA se llamó — lo que falla es el INSERT final"
    assert len(perdidas_del_escritor(perdidas)) == 1, (
        "la pérdida se cuenta UNA sola vez: el except del plano no la vuelve a contar — "
        "`basa:audit:lost` es constancia de eventos perdidos, no de reintentos")


def test_policy_con_riesgo_alto_y_fila_final_perdida_devuelve_503_y_no_500(
        harness, monkeypatch, motor):
    """Brazo `policy` del P1, y además el ÚNICO testigo de que la decisión viaja hasta el
    escritor: si el `exige_registro=` del `log_transaction` del camino feliz se cayera, el
    default `None` haría decidir por modo (`policy != closed` ⇒ no corta) y este pedido se
    serviría con 200 sin fila — el agujero exacto que la matriz existe para tapar."""
    client, factory = harness
    calentar_catalogo(client)
    fijar_riesgo_admin(factory, "high_risk_annex3")

    sondas = espiar_pre_check(monkeypatch)
    perdidas = romper_escritor(monkeypatch)
    motor.posts.clear()

    respuesta = pedir(client, SIN_PII)

    assert respuesta.status_code == 503, respuesta.text
    assert respuesta.json()["detail"] == DETALLE_POLICY, (
        "el 503 del INSERT final usa el copy del modo VIGENTE, igual que el del pre-check")
    assert sondas == [True], "post-pre-check: la sonda real dijo que la base estaba sana"
    assert len(motor.posts) == 1, "el proveedor YA se llamó — lo que falla es el INSERT final"
    assert len(perdidas_del_escritor(perdidas)) == 1


def test_policy_con_riesgo_bajo_y_fila_final_perdida_sirve_igual(harness, monkeypatch, motor):
    """Testigo NEGATIVO del mismo except: con riesgo `minimal` la matriz dice servir, así que
    el escritor no propaga y el 200 llega con la pérdida contada (FR-004: «servido sin fila»
    no es silencioso). Sin este testigo, un except que devolviera 503 ante CUALQUIER fallo de
    escritura pasaría los dos de arriba y rompería el tráfico normal de toda instalación."""
    client, factory = harness
    calentar_catalogo(client)
    fijar_riesgo_admin(factory, "minimal")

    sondas = espiar_pre_check(monkeypatch)
    perdidas = romper_escritor(monkeypatch)
    motor.posts.clear()

    respuesta = pedir(client, SIN_PII)

    assert respuesta.status_code == 200, respuesta.text
    assert sondas == [], "riesgo bajo: no paga ni el pre-check (D4), tampoco en este camino"
    assert len(motor.posts) == 1, "se sirvió de verdad"
    assert len(perdidas_del_escritor(perdidas)) == 1, (
        "servido sin fila SÍ se cuenta: es el contador de FR-004, no un fallo silencioso")


def test_open_explicito_con_la_fila_final_perdida_sirve_igual(harness, monkeypatch, motor):
    """SC-002 en el camino feliz: el `try/except` nuevo no puede convertir en 503 un pedido
    que `open` explícito venía sirviendo, ni siquiera con riesgo alto. El testigo de `open`
    del otro archivo mide el camino de BLOQUEO (4xx), que ya estaba protegido antes de la
    038 — este mide el camino que la 038 tocó."""
    client, factory = harness
    calentar_catalogo(client)
    fijar_riesgo_admin(factory, "high_risk_annex3")

    from src.services import audit_service
    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, "open")
    sondas = espiar_pre_check(monkeypatch)
    perdidas = romper_escritor(monkeypatch)
    motor.posts.clear()

    respuesta = pedir(client, SIN_PII)

    assert respuesta.status_code == 200, respuesta.text
    assert sondas == [], "open explícito: ni el riesgo alto paga el pre-check"
    assert len(motor.posts) == 1, "se sirvió de verdad"
    assert len(perdidas_del_escritor(perdidas)) == 1
