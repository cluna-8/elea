"""057: la llave que emite un Kit de Claude Desktop o Claude Code nace con el tope que esas herramientas necesitan.

Cada pedido de Claude Desktop/Cowork pesa 35 000–67 000 tokens: con el default de la llave (60 rpm / 100 000 tpm)
el segundo pedido del minuto ya excede el tope. Estas dos herramientas nacen con 120 rpm / 1 000 000 tpm; las
demás conservan el default de la base. El alta pasa los límites a `keys.generate_key`, que los aplica en los
DOS lugares (fila `api_keys` y llave del motor por `/key/generate`).
"""
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
pytest.importorskip("src.auth.rbac", reason="requiere el venv del backend")

from sentinel.redirect import kits  # noqa: E402
from sentinel.redirect.api import us5  # noqa: E402

USER = uuid.uuid4()


@pytest.fixture
def emitida(monkeypatch):
    from src.api import keys as keys_api
    visto = []

    async def fake(key_in, db):
        visto.append(key_in)
        return SimpleNamespace(id="k-1", plain_key="sk-sentinel-test")

    monkeypatch.setattr(keys_api, "generate_key", fake)
    monkeypatch.setattr(us5, "KEY_ISSUER", None)
    return visto


@pytest.mark.parametrize("tool", ["claude_desktop", "claude_code"])
@pytest.mark.asyncio
async def test_claude_desktop_y_code_nacen_con_120_rpm_y_1m_tpm(emitida, tool):
    await us5._issue_key(None, None, tool=tool, scope=("user", USER), models=["claude-sonnet-4-5"])
    assert (emitida[0].rpm_limit, emitida[0].tpm_limit) == (120, 1_000_000)


@pytest.mark.parametrize("tool", ["codex", "openai_generic"])
@pytest.mark.asyncio
async def test_las_otras_herramientas_conservan_el_default_de_la_base(emitida, tool):
    await us5._issue_key(None, None, tool=tool, scope=("group", USER), models=[])
    assert (emitida[0].rpm_limit, emitida[0].tpm_limit) == (60, 100000)


def test_los_limites_del_kit_son_datos_en_kits_py():
    assert kits.KEY_LIMITS["claude_desktop"] == (120, 1_000_000)
    assert kits.KEY_LIMITS["claude_code"] == (120, 1_000_000)
    assert set(kits.KEY_LIMITS) <= set(kits.TOOLS)


@pytest.mark.asyncio
async def test_el_limite_llega_al_motor_y_a_la_fila(monkeypatch):
    """De punta a punta del alta (sin base ni motor reales): el POST `/key/generate` lleva rpm/tpm y la fila
    `APIKey` que se guarda los lleva igual."""
    from src.api import keys as keys_api
    from src.services import ai_engine_client

    payloads, filas = [], []

    async def post(path, payload):
        payloads.append((path, payload))
        return {"key": payload["key"]}

    class Db:
        def query(self, entity, *_a, **_k):
            fila = None if entity is keys_api.APIKey else SimpleNamespace(engine_user_id="eu-1", engine_team_id="et-1")
            return SimpleNamespace(filter=lambda *a, **k: SimpleNamespace(first=lambda: fila))

        def add(self, row):
            filas.append(row)

        def commit(self):
            pass

        def refresh(self, _):
            filas[0].id = "00000000-0000-0000-0000-000000000001"
            filas[0].created_at = "2026-10-07T00:00:00Z"

    monkeypatch.setattr(ai_engine_client, "_post", post)
    monkeypatch.setattr(keys_api, "enforce_seat_gate", lambda *a, **k: None)
    monkeypatch.setattr(us5, "KEY_ISSUER", None)

    await us5._issue_key(Db(), None, tool="claude_desktop", scope=("user", USER), models=["claude-sonnet-4-5"])
    assert payloads[0][0] == "/key/generate"
    assert (payloads[0][1]["rpm_limit"], payloads[0][1]["tpm_limit"]) == (120, 1_000_000)
    assert (filas[0].rpm_limit, filas[0].tpm_limit) == (120, 1_000_000)
