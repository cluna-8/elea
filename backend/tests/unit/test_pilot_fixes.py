"""Regresión de los 3 fixes del piloto Cámara (rama fix/pilot-bugs).

Bug 1 — timeout del motor de IA configurable por env (no hardcode 15s), para que
        un modelo local/self-hosted lento no se corte.
Bug 2 — un modelo local (Ollama del cliente) cuesta 0, no el default $5/$15.
Bug 3 — el detector de secretos captura las keys nuevas `sk-proj-...` además de
        las clásicas `sk-<alfanum>`, sin falsos positivos con strings cortos.

Todos PUROS: sin Postgres. Bug 3 corre `process_prompt` contra una sesión fake
(mismo patrón que test_guardian_seed_migration) con 9 guardianes ya presentes, así
que nunca entra al camino de re-seed ni toca la DB.
"""
from decimal import Decimal

import pytest

from src.models.guardian import Guardian
from src.services.budget_service import BudgetService, _is_local_model


# --------------------------------------------------------------------------- #
# Bug 1 — timeout del motor como setting (env), default holgado
#
# El parser se MUDÓ de `chat._resolve_engine_timeout` al helper compartido de
# `engine_gate` (nodo C1: el mismo timeout lo usan el chat y el byok de /gw, que
# tenía su propio 120 s hardcodeado). El env y el default no cambian, así que la
# regresión del piloto se sigue afirmando igual — sólo cambia dónde vive. El
# CABLEADO de la constante y la guardia de rango nueva viven en
# tests/unit/test_engine_gate.py.
# --------------------------------------------------------------------------- #
_ENGINE_TIMEOUT_ENV = "BASA_ENGINE_TIMEOUT_SECONDS"


def _engine_timeout(monkeypatch, valor=None):
    from src.services.engine_gate import _env_float
    if valor is None:
        monkeypatch.delenv(_ENGINE_TIMEOUT_ENV, raising=False)
    else:
        monkeypatch.setenv(_ENGINE_TIMEOUT_ENV, valor)
    return _env_float(_ENGINE_TIMEOUT_ENV, 60.0, maximo=600.0)


def test_engine_timeout_default_without_env(monkeypatch):
    assert _engine_timeout(monkeypatch) == 60.0


def test_engine_timeout_reads_env_value(monkeypatch):
    assert _engine_timeout(monkeypatch, "120") == 120.0


def test_engine_timeout_invalid_value_falls_back_to_default(monkeypatch):
    assert _engine_timeout(monkeypatch, "not-a-number") == 60.0


# --------------------------------------------------------------------------- #
# Bug 2 — modelo local cuesta 0; remoto conocido conserva precio; remoto
#         desconocido sigue cayendo al default conservador $5/$15.
# --------------------------------------------------------------------------- #
_1M = 1_000_000


def test_local_model_costs_zero():
    assert _is_local_model("ollama-qwen3-4b") is True
    # 1M input + 1M output → sigue siendo 0 (input y output).
    assert BudgetService.calculate_cost("ollama-qwen3-4b", _1M, _1M) == Decimal("0")
    # Otras formas del provider Ollama también son locales.
    assert _is_local_model("ollama_chat/qwen3:4b") is True
    assert _is_local_model("ollama/llama3") is True


def test_known_remote_model_keeps_its_price():
    # gpt-4o = 5/15 por 1M → 20.00; y un conocido de precio distinto para probar
    # que NO es simplemente el default: gpt-4o-mini = 0.15 + 0.60 = 0.75.
    assert BudgetService.calculate_cost("gpt-4o", _1M, _1M) == Decimal("20.00")
    assert BudgetService.calculate_cost("gpt-4o-mini", _1M, _1M) == Decimal("0.75")
    assert _is_local_model("gpt-4o") is False


def test_unknown_remote_model_still_uses_default_5_15():
    # Un modelo remoto DESCONOCIDO no es local → default conservador 5/15 = 20.00.
    assert _is_local_model("mystery-cloud-model") is False
    assert BudgetService.calculate_cost("mystery-cloud-model", _1M, _1M) == Decimal("20.00")


# --------------------------------------------------------------------------- #
# Bug 3 — regex de secreto captura sk-proj-… y clásicas; sin falso positivo corto
# --------------------------------------------------------------------------- #
class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def filter(self, *_a, **_k):
        # El único filtro relevante es guardian_type == "pii_masking".
        return _FakeQuery([g for g in self._rows if g.guardian_type == "pii_masking"])

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows
        self.commits = 0

    def query(self, *_a, **_k):
        return _FakeQuery(self._rows)

    def commit(self):
        self.commits += 1


def _guardians_with_active_secret_block():
    """9 guardianes (para saltar el re-seed): secret_detection ACTIVO en BLOCK y
    un pii_masking INACTIVO con config ya migrada (para no disparar la migración
    ni la ruta Presidio)."""
    secret = Guardian(
        name="Filtro de Secretos",
        guardian_type="secret_detection",
        is_active=True,
        config={"action": "BLOCK"},
    )
    pii = Guardian(
        name="PII",
        guardian_type="pii_masking",
        is_active=False,  # inactivo → no se ejecuta la ruta PII/Presidio
        config={
            "custom_names": [],  # clave presente → sin migración de nombres
            "entities": ["PERSON", "ES_NIF"],  # no es el set legacy AR → sin migración
            "action": "MASK",
        },
    )
    fillers = [
        Guardian(name=f"f{i}", guardian_type=f"filler_{i}", is_active=False, config={})
        for i in range(7)
    ]
    return [secret, pii, *fillers]


@pytest.mark.asyncio
async def test_secret_detection_matches_sk_proj_key():
    db = _FakeSession(_guardians_with_active_secret_block())
    key = "sk-proj-" + "aBcD1234_-XyZwVuT" * 6  # llave nueva, con guiones/underscores
    result = await GuardianServiceProcess(db, f"mi api key es {key} ojo")
    assert result["blocked"] is True


@pytest.mark.asyncio
async def test_secret_detection_still_matches_classic_key():
    db = _FakeSession(_guardians_with_active_secret_block())
    classic = "sk-" + "A1b2C3d4E5" * 4  # sk- + 40 alfanuméricos (clásica)
    result = await GuardianServiceProcess(db, f"clave: {classic}")
    assert result["blocked"] is True


@pytest.mark.asyncio
async def test_secret_detection_no_false_positive_on_short_string():
    db = _FakeSession(_guardians_with_active_secret_block())
    result = await GuardianServiceProcess(db, "el prefijo sk-abc no es una clave")
    assert result["blocked"] is False


# Import diferido para que la config del import de src.api.chat no interfiera con
# los tests de env de Bug 1 (monkeypatch).
async def GuardianServiceProcess(db, prompt):
    from src.services.guardian_service import GuardianService
    return await GuardianService.process_prompt(db, prompt, selected_model="gpt-4o")
