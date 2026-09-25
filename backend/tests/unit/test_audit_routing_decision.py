"""`routing_decision` confiable en las filas de auditoría del plano MOTOR.

La columna `audit_logs.routing_decision` existe (spec 030) pero solo la escribía el plano
chat. Este seam la lleva de punta a punta en el camino motor:

    código del motor (guardrail…) → metadata interna → sentinel_audit_logger → POST
    /internal/audit → INSERT

Contrato de procedencia (hallazgo A3 de la 027, el mismo agujero que dejó
`applied_layers` en NULL): el metadata-home es la FUSIÓN de `litellm_metadata` y
`metadata`, y `metadata` lo escribe el CLIENTE en el body. Por eso la decisión solo se
acepta si la escribió código del motor con `mark_routing_decision` — un valor que el
cliente mande bajo la MISMA clave es JSON plano y se ignora. JSON no puede fabricar una
instancia de una clase de Python: esa es la marca no falsificable.

Ausente ⇒ la fila es idéntica a la de antes (sin la clave en el payload, NULL en SQL).
"""
import json
import sys
import types
from datetime import datetime

import httpx
import pytest


def _instalar_doble_litellm():
    if "litellm.integrations.custom_logger" in sys.modules:
        return

    class CustomLogger:
        def __init__(self, *args, **kwargs):
            pass

    litellm_mod = sys.modules.setdefault("litellm", types.ModuleType("litellm"))
    integrations = sys.modules.setdefault(
        "litellm.integrations", types.ModuleType("litellm.integrations"))
    modulo = types.ModuleType("litellm.integrations.custom_logger")
    modulo.CustomLogger = CustomLogger
    sys.modules["litellm.integrations.custom_logger"] = modulo
    litellm_mod.integrations = integrations
    integrations.custom_logger = modulo


_instalar_doble_litellm()

from extensions import sentinel_audit_logger as logger_mod  # noqa: E402

# El MISMO módulo de política que usa el logger (el motor lo importa por nombre plano).
policy = logger_mod.policy

AUDIT_URL = "http://backend:8000/api/v1/internal/audit"
DECISION = {"requested": "auto", "route": "codigo", "score": 0.912,
            "model_selected": "modelo-a", "degraded": False, "reason": None}
FALSA = {"requested": "auto", "route": "inventada", "score": 1.0,
         "model_selected": "modelo-caro", "degraded": False, "reason": "cliente"}
IDENTIDAD = {"user_api_key_metadata": {"sentinel": {
    "tenant_id": "33333333-3333-3333-3333-333333333333",
    "client_id": "22222222-2222-2222-2222-222222222222",
    "key_id": "11111111-1111-1111-1111-111111111111",
}}}


class _Respuesta:
    status_code = 200


@pytest.fixture
def posts(monkeypatch):
    monkeypatch.setenv("SENTINEL_AUDIT_URL", AUDIT_URL)
    registro: list = []

    class _Cliente:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            registro.append(json)
            return _Respuesta()

    monkeypatch.setattr(httpx, "AsyncClient", _Cliente)

    async def _sin_monitor(*a, **k):
        return None
    monkeypatch.setattr(logger_mod.SentinelAuditLogger, "_publish_monitor_event", _sin_monitor)
    return registro


async def _loguear(metadata=None, litellm_metadata=None):
    kwargs = {"model": "m", "litellm_params": {}, "response_cost": 0.0,
              "metadata": {**IDENTIDAD, **(metadata or {})}}
    if litellm_metadata is not None:
        kwargs["litellm_metadata"] = litellm_metadata
    await logger_mod.sentinel_audit_logger_instance.async_log_success_event(
        kwargs, None, datetime(2026, 9, 1), datetime(2026, 9, 1))


# ── Plano motor: procedencia ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sin_decision_la_fila_es_identica(posts):
    await _loguear()
    assert "routing_decision" not in posts[0]


@pytest.mark.asyncio
async def test_decision_escrita_por_el_motor_se_persiste(posts):
    home: dict = {}
    policy.mark_routing_decision(home, DECISION)
    await _loguear(litellm_metadata=home)
    assert posts[0]["routing_decision"] == DECISION


@pytest.mark.asyncio
async def test_decision_mandada_por_el_cliente_se_ignora(posts):
    await _loguear(metadata={policy.ROUTING_DECISION_KEY: FALSA})
    assert "routing_decision" not in posts[0]


@pytest.mark.asyncio
async def test_cliente_no_pisa_la_del_motor_aunque_gane_el_merge(posts):
    """`metadata` (cliente) gana el merge del home sobre `litellm_metadata`: la lectura no
    puede depender del merge."""
    home: dict = {}
    policy.mark_routing_decision(home, DECISION)
    await _loguear(metadata={policy.ROUTING_DECISION_KEY: FALSA}, litellm_metadata=home)
    assert posts[0]["routing_decision"] == DECISION


def test_el_escritor_sobrescribe_el_valor_del_cliente():
    home = {policy.ROUTING_DECISION_KEY: FALSA}
    policy.mark_routing_decision(home, DECISION)
    assert policy.trusted_routing_decision(home) == DECISION


def test_json_no_puede_fabricar_la_marca():
    home = json.loads(json.dumps({policy.ROUTING_DECISION_KEY: DECISION}))
    assert policy.trusted_routing_decision(home) is None


def test_la_marca_sobrevive_la_copia_profunda_y_serializa_como_json():
    import copy
    home: dict = {}
    policy.mark_routing_decision(home, DECISION)
    assert policy.trusted_routing_decision(copy.deepcopy(home)) == DECISION
    assert json.loads(json.dumps(home))[policy.ROUTING_DECISION_KEY] == DECISION


@pytest.mark.asyncio
async def test_camino_de_desarrollo_por_prisma_lleva_la_columna(monkeypatch):
    llamadas: list = []

    class _Db:
        async def query_raw(self, sql, *params):
            llamadas.append((sql, params))

    fake = types.ModuleType("litellm.proxy.proxy_server")
    fake.prisma_client = types.SimpleNamespace(db=_Db())
    monkeypatch.setitem(sys.modules, "litellm.proxy.proxy_server", fake)
    entry = {"tenant_id": "t", "user_id": None, "api_key_id": None, "model": "m",
             "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0,
             "pii_detected": False, "compliance_status": "passed", "latency_ms": 0,
             "user_group_id": None}
    inst = logger_mod.sentinel_audit_logger_instance
    await inst._insertar_por_prisma(dict(entry), [], None, None)
    await inst._insertar_por_prisma({**entry, "routing_decision": DECISION}, [], None, None)
    sql, sin = llamadas[0]
    assert "routing_decision" in sql and sin[-1] is None
    assert json.loads(llamadas[1][1][-1]) == DECISION


# ── Plano interno del backend ────────────────────────────────────────────────────────

class _DbFalsa:
    def __init__(self):
        self.params = None

    def execute(self, _sql, params=None):
        self.params = params

    def commit(self):
        pass

    def rollback(self):
        pass


def _registrar(**campos):
    from src.api import internal
    db = _DbFalsa()
    internal.record_audit(internal.AuditEntry(tenant_id=None, **campos), db=db)
    return db.params


def test_backend_sin_decision_inserta_null():
    assert _registrar()["routing_decision"] is None


def test_backend_persiste_la_decision():
    assert json.loads(_registrar(routing_decision=DECISION)["routing_decision"]) == DECISION


def test_backend_sanea_por_vocabulario_cerrado():
    sucia = {**DECISION, "prompt": "texto del usuario", "route": "x" * 500,
             "score": True, "degraded": "si"}
    guardada = json.loads(_registrar(routing_decision=sucia)["routing_decision"])
    assert "prompt" not in guardada
    assert len(guardada["route"]) == 128
    assert "score" not in guardada and "degraded" not in guardada
    assert guardada["model_selected"] == "modelo-a"
