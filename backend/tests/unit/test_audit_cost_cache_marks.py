"""Gasto en cero: «sin costo informado» (None) ≠ «costo 0», y el acierto de caché se MARCA.

Origen: `specs/ANALISIS-GASTO-CERO-2026-10.md` §9. El motor fija `spend=0` en un acierto de
caché de respuestas y `response_cost=None` en un modelo que no conoce; el logger convertía
las dos cosas en `0` (`kwargs.get("response_cost") or 0`) y el backend aceptaba ese `0`
como costo real: sin marca en la auditoría y, para el modelo sin precio, presupuesto en USD
que nunca se descuenta. Contrato que fijan estos tests (genérico, sin nada de un cliente):

* logger: `None` con tokens → `cost_usd=None` + `cost_missing=True`; `0.0` real → `0.0`;
  el acierto de caché viaja como `cache_hit=True` (metadata-only: un booleano);
* backend: sin costo informado, el tarifario se resuelve UNA vez y vale para la fila y para
  el presupuesto (cierran) con la fila marcada `cost_estimated`; el `0.0` explícito no cae
  al tarifario; un acierto de caché no mueve el presupuesto (decisión de producto).

Sin Docker ni Postgres: el logger se importa como lo importa el motor (doble de litellm) y
el backend se prueba sobre sus funciones puras.
"""
import sys
import types
from datetime import datetime, timedelta
from decimal import Decimal

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
from src.api import internal  # noqa: E402
from src.services.budget_service import BudgetService  # noqa: E402

IDENTIDAD = {"key_id": "k-1", "client_id": "u-1",
             "tenant_id": "33333333-3333-3333-3333-333333333333"}


class _Uso:
    def __init__(self, prompt, completion):
        self.prompt_tokens = prompt
        self.completion_tokens = completion


class _Respuesta:
    def __init__(self, prompt=11, completion=4):
        self.usage = _Uso(prompt, completion)


def _kwargs(**extra):
    base = {"model": "modelo-x",
            "litellm_params": {"metadata": {"user_api_key_metadata": {"sentinel": IDENTIDAD}}}}
    base.update(extra)
    return base


@pytest.fixture
def emitidas(monkeypatch):
    """Captura la fila que el logger entrega al punto único de emisión."""
    filas = []

    async def _emitir(entry, masked, applied_layers=None, blocked_by_layer=None):
        filas.append(entry)

    async def _monitor(*args, **kwargs):
        return None

    monkeypatch.setattr(logger_mod, "emitir_fila_durable", _emitir)
    monkeypatch.setattr(logger_mod.sentinel_audit_logger_instance,
                        "_publish_monitor_event", _monitor)
    return filas


async def _auditar(kwargs, respuesta=None):
    ahora = datetime.utcnow()
    await logger_mod.sentinel_audit_logger_instance._log(
        kwargs, respuesta or _Respuesta(), ahora, ahora + timedelta(milliseconds=5))


# ── Logger del motor ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sin_costo_informado_con_tokens_no_se_convierte_en_cero(emitidas):
    """Reproduce el cero latente (§9.5): `response_cost=None` salía como `0.0`."""
    await _auditar(_kwargs(response_cost=None))

    fila = emitidas[0]
    assert fila["cost_usd"] is None, "None ≠ 0: el backend decide el respaldo"
    assert fila["cost_missing"] is True
    assert fila["cache_hit"] is False


@pytest.mark.asyncio
async def test_costo_ausente_del_kwargs_tambien_es_sin_costo_informado(emitidas):
    await _auditar(_kwargs())

    assert emitidas[0]["cost_usd"] is None and emitidas[0]["cost_missing"] is True


@pytest.mark.asyncio
async def test_acierto_de_cache_viaja_marcado_y_con_costo_cero(emitidas):
    """Reproduce §9.1 (R2): `spend=0`, tokens>0 y NINGUNA marca en la fila."""
    await _auditar(_kwargs(response_cost=0.0, cache_hit=True))

    fila = emitidas[0]
    assert fila["cost_usd"] == 0.0 and fila["cost_missing"] is False
    assert fila["cache_hit"] is True


@pytest.mark.asyncio
async def test_cache_hit_tambien_se_lee_del_standard_logging_object(emitidas):
    """§9.7: no está verificado qué kwargs trae el hook; se lee defensivo de los dos sitios."""
    await _auditar(_kwargs(response_cost=0.0,
                           standard_logging_object={"cache_hit": True}))

    assert emitidas[0]["cache_hit"] is True


@pytest.mark.asyncio
async def test_acierto_de_cache_sin_costo_informado_no_se_marca_faltante(emitidas):
    """Un acierto es un cero REAL aunque el motor no mande el número: no es «faltante»."""
    await _auditar(_kwargs(response_cost=None, cache_hit=True))

    assert emitidas[0]["cost_usd"] == 0.0 and emitidas[0]["cost_missing"] is False


@pytest.mark.asyncio
async def test_costo_normal_sigue_igual(emitidas):
    await _auditar(_kwargs(response_cost=2.625e-05))

    fila = emitidas[0]
    assert fila["cost_usd"] == pytest.approx(2.625e-05)
    assert fila["cost_missing"] is False and fila["cache_hit"] is False


@pytest.mark.asyncio
async def test_sin_tokens_el_costo_ausente_es_cero_no_faltante(emitidas):
    """Sin consumo (0 tokens) no hay nada que tarifar: no se pide respaldo."""
    await _auditar(_kwargs(response_cost=None), _Respuesta(0, 0))

    assert emitidas[0]["cost_usd"] == 0.0 and emitidas[0]["cost_missing"] is False


@pytest.mark.asyncio
async def test_camino_prisma_no_viola_el_not_null_con_costo_faltante(monkeypatch):
    """Sin `SENTINEL_AUDIT_URL` (desarrollo) el INSERT directo no puede recibir None."""
    llamadas = []

    class _Db:
        async def query_raw(self, sql, *args):
            llamadas.append((sql, args))

    proxy_server = types.ModuleType("litellm.proxy.proxy_server")
    proxy_server.prisma_client = types.SimpleNamespace(db=_Db())
    monkeypatch.setitem(sys.modules, "litellm.proxy", types.ModuleType("litellm.proxy"))
    monkeypatch.setitem(sys.modules, "litellm.proxy.proxy_server", proxy_server)
    entry = {"tenant_id": None, "user_id": None, "api_key_id": None, "model": "m",
             "prompt_tokens": 1, "completion_tokens": 1, "cost_usd": None,
             "cost_missing": True, "cache_hit": False, "pii_detected": False,
             "compliance_status": "passed", "latency_ms": 1, "user_group_id": None}

    await logger_mod.sentinel_audit_logger_instance._insertar_por_prisma(entry, [], None, None)

    sql, args = llamadas[0]
    assert None not in (args[6],), "cost_usd no puede ir None a una columna NOT NULL"
    assert "cache_hit" in sql


# ── Backend: costo del evento ──────────────────────────────────────────────────────────

def _evento(**kw):
    base = dict(model="azure-gpt-5.4-mini", prompt_tokens=11, completion_tokens=4)
    base.update(kw)
    return internal.AuditEntry(**base)


def test_el_contrato_viejo_sigue_valiendo_costo_explicito_manda():
    """Retrocompatible: un motor viejo manda `cost_usd` y nada más."""
    costo, estimado = internal._costo_del_evento(_evento(cost_usd=0.0100))

    assert costo == Decimal("0.0100") and estimado is False


def test_cero_explicito_no_cae_al_tarifario():
    """Modelo local o gratuito: el 0 informado es verdad y no se «corrige»."""
    costo, estimado = internal._costo_del_evento(_evento(cost_usd=0.0))

    assert costo == Decimal("0") and estimado is False


def test_sin_costo_informado_cae_al_tarifario_una_sola_vez(monkeypatch):
    llamadas = []
    real = BudgetService.calculate_cost

    def espia(model, p, c):
        llamadas.append(model)
        return real(model, p, c)

    monkeypatch.setattr(BudgetService, "calculate_cost", staticmethod(espia))

    costo, estimado = internal._costo_del_evento(
        _evento(model="gpt-4o-mini", prompt_tokens=100, completion_tokens=50,
                cost_usd=None, cost_missing=True))

    assert costo == Decimal("0.00004500") and estimado is True
    assert llamadas == ["gpt-4o-mini"]


def test_el_acierto_de_cache_es_cero_real_y_no_usa_tarifario():
    costo, estimado = internal._costo_del_evento(
        _evento(cost_usd=None, cost_missing=True, cache_hit=True))

    assert costo == Decimal("0") and estimado is False


def test_sin_tokens_ni_costo_no_hay_estimacion():
    costo, estimado = internal._costo_del_evento(
        _evento(prompt_tokens=0, completion_tokens=0, cost_usd=None, cost_missing=True))

    assert costo == Decimal("0") and estimado is False


# ── Backend: presupuesto ───────────────────────────────────────────────────────────────

@pytest.fixture
def cargas(monkeypatch):
    registro = []
    monkeypatch.setattr(BudgetService, "update_budget",
                        staticmethod(lambda **kw: registro.append(kw)))
    return registro


def test_modelo_sin_precio_descuenta_el_tarifario_y_no_cero(cargas):
    """Reproduce §9.5: tokens +30 y dólares sin cambio (`Decimal(0)` ganaba en
    `budget_service.py:216`). Ahora el presupuesto recibe el costo resuelto."""
    evento = _evento(model="gpt-4o-mini", prompt_tokens=100, completion_tokens=50,
                     cost_usd=None, cost_missing=True)
    costo, _ = internal._costo_del_evento(evento)

    internal._acumular_gasto(None, evento, costo)

    assert cargas[0]["override_cost"] == Decimal("0.00004500")
    assert cargas[0]["override_cost"] != 0


def test_acierto_de_cache_no_mueve_el_presupuesto(cargas):
    """Decisión de producto (owner, 6-oct-2026): costo 0 real, ni USD ni tokens."""
    evento = _evento(cost_usd=0.0, cache_hit=True)

    internal._acumular_gasto(None, evento, Decimal("0"))

    assert cargas == []


def test_costo_informado_sigue_descontando_el_del_evento(cargas):
    evento = _evento(model="modelo-desconocido", prompt_tokens=100000, completion_tokens=0,
                     cost_usd=0.0100)

    internal._acumular_gasto(None, evento, Decimal("0.0100"))

    assert cargas[0]["override_cost"] == Decimal("0.0100")


def test_fila_de_bloqueo_sigue_sin_cargar(cargas):
    internal._acumular_gasto(None, _evento(prompt_tokens=0, completion_tokens=0,
                                           cost_usd=0.0), Decimal("0"))

    assert cargas == []
