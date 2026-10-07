"""057 (llaves de Kits): los límites rpm/tpm de una llave EXISTENTE se editan desde la consola y quedan
aplicados en los DOS lugares donde se hacen cumplir.

1. `api_keys` de la pasarela — `check_rpm`/`check_tpm` leen `APIKey.rpm_limit/tpm_limit` (chat.py).
2. La llave del motor — `POST /key/update` con la master key; además invalida la caché de la llave en el motor.

El motor va primero: si no responde no se toca la fila local (mismo criterio que el alta: sin motor, sin cambio),
así los dos lugares nunca divergen en silencio. Sin `engine_key_token` (instalación sin provisionador) solo cambia
la pasarela. Valores < 1 se rechazan: `check_rpm/tpm` leen `<= 0` como «sin límite» y la consola no debe poder
apagar el tope por un cero tipeado.
"""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.api import keys as keys_api
from src.services import ai_engine_client
from src.services.ai_engine_client import AIEngineClientError


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_a, **_k):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)

    def order_by(self, *_a, **_k):
        return self


class _Db:
    """Sesión mínima: `query(APIKey)` devuelve la llave; el resto de consultas, vacías."""

    def __init__(self, key):
        self.key = key
        self.commits = 0
        self.rollbacks = 0
        self.commit_error = None

    def query(self, *entities):
        if entities and entities[0] is keys_api.APIKey:
            return _Query([self.key] if self.key is not None else [])
        return _Query([])

    def commit(self):
        if self.commit_error:
            raise self.commit_error
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, _obj):
        pass


def _key(**over):
    base = dict(id=uuid.uuid4(), name="Kit claude_desktop", key_preview="sk-sentinel-…abcd", user_id=None,
                group_id=None, tool_type="claude-desktop", can_act_on_behalf=False, is_active=True,
                compliance_project_id=None, rpm_limit=60, tpm_limit=100000,
                created_at="2026-10-07T10:00:00Z", engine_key_token="sk-sentinel-engine")
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture
def engine_calls(monkeypatch):
    calls = []

    async def _update(token, rpm_limit=None, tpm_limit=None):
        calls.append({"token": token, "rpm_limit": rpm_limit, "tpm_limit": tpm_limit})

    monkeypatch.setattr(ai_engine_client, "update_key", _update)
    return calls


# ── cliente del motor ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_key_manda_key_y_limites_a_key_update(monkeypatch):
    captured = {}

    async def _post(path, payload):
        captured.update(path=path, payload=payload)
        return {}

    monkeypatch.setattr(ai_engine_client, "_post", _post)
    await ai_engine_client.update_key("sk-sentinel-x", rpm_limit=120, tpm_limit=1_000_000)
    assert captured["path"] == "/key/update"
    assert captured["payload"] == {"key": "sk-sentinel-x", "rpm_limit": 120, "tpm_limit": 1_000_000}


@pytest.mark.asyncio
async def test_update_key_solo_manda_lo_que_cambia(monkeypatch):
    captured = {}

    async def _post(path, payload):
        captured["payload"] = payload
        return {}

    monkeypatch.setattr(ai_engine_client, "_post", _post)
    await ai_engine_client.update_key("sk-sentinel-x", tpm_limit=500_000)
    assert captured["payload"] == {"key": "sk-sentinel-x", "tpm_limit": 500_000}


# ── esquema ───────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("campo", ["rpm_limit", "tpm_limit"])
@pytest.mark.parametrize("valor", [0, -1])
def test_el_esquema_rechaza_limites_menores_a_uno(campo, valor):
    with pytest.raises(ValidationError):
        keys_api.KeyLimitsUpdateSchema(**{campo: valor})


# ── PATCH /keys/{id} ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_edita_los_dos_lugares_motor_y_pasarela(engine_calls):
    k = _key()
    db = _Db(k)
    out = await keys_api.update_key_limits(k.id, keys_api.KeyLimitsUpdateSchema(rpm_limit=120, tpm_limit=1_000_000), db)
    assert (k.rpm_limit, k.tpm_limit) == (120, 1_000_000)             # pasarela (api_keys)
    assert engine_calls == [{"token": "sk-sentinel-engine", "rpm_limit": 120, "tpm_limit": 1_000_000}]   # motor
    assert db.commits == 1
    assert (out.rpm_limit, out.tpm_limit) == (120, 1_000_000)


@pytest.mark.asyncio
async def test_un_solo_campo_deja_el_otro_intacto(engine_calls):
    k = _key()
    await keys_api.update_key_limits(k.id, keys_api.KeyLimitsUpdateSchema(tpm_limit=1_000_000), _Db(k))
    assert (k.rpm_limit, k.tpm_limit) == (60, 1_000_000)
    assert engine_calls == [{"token": "sk-sentinel-engine", "rpm_limit": None, "tpm_limit": 1_000_000}]


@pytest.mark.asyncio
async def test_sin_ningun_campo_es_422(engine_calls):
    k = _key()
    with pytest.raises(HTTPException) as e:
        await keys_api.update_key_limits(k.id, keys_api.KeyLimitsUpdateSchema(), _Db(k))
    assert e.value.status_code == 422 and engine_calls == []


@pytest.mark.asyncio
async def test_llave_inexistente_es_404(engine_calls):
    with pytest.raises(HTTPException) as e:
        await keys_api.update_key_limits(uuid.uuid4(), keys_api.KeyLimitsUpdateSchema(rpm_limit=5), _Db(None))
    assert e.value.status_code == 404 and engine_calls == []


@pytest.mark.asyncio
async def test_motor_caido_es_503_y_no_toca_la_fila(monkeypatch):
    async def _boom(*_a, **_k):
        raise AIEngineClientError("down")

    monkeypatch.setattr(ai_engine_client, "update_key", _boom)
    k = _key()
    db = _Db(k)
    with pytest.raises(HTTPException) as e:
        await keys_api.update_key_limits(k.id, keys_api.KeyLimitsUpdateSchema(rpm_limit=120, tpm_limit=1_000_000), db)
    assert e.value.status_code == 503
    assert (k.rpm_limit, k.tpm_limit) == (60, 100000) and db.commits == 0


@pytest.mark.asyncio
async def test_sin_token_del_motor_solo_cambia_la_pasarela(engine_calls):
    k = _key(engine_key_token=None)
    await keys_api.update_key_limits(k.id, keys_api.KeyLimitsUpdateSchema(rpm_limit=120), _Db(k))
    assert k.rpm_limit == 120 and engine_calls == []


@pytest.mark.asyncio
async def test_si_falla_el_commit_se_devuelve_el_motor_a_los_valores_viejos(engine_calls):
    k = _key()
    db = _Db(k)
    db.commit_error = RuntimeError("db")
    with pytest.raises(HTTPException) as e:
        await keys_api.update_key_limits(k.id, keys_api.KeyLimitsUpdateSchema(rpm_limit=120, tpm_limit=1_000_000), db)
    assert e.value.status_code == 500
    assert db.rollbacks == 1
    assert engine_calls[-1] == {"token": "sk-sentinel-engine", "rpm_limit": 60, "tpm_limit": 100000}


def test_el_endpoint_es_solo_admin():
    rutas = [r for r in keys_api.router.routes if r.path.endswith("/{key_id}") and "PATCH" in r.methods]
    assert len(rutas) == 1
    assert rutas[0].dependencies, "PATCH /keys/{id} debe cerrar a admin por-endpoint (como POST y DELETE)"
