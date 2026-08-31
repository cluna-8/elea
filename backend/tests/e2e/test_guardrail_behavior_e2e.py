"""e2e de comportamiento REAL del `SentinelGuardrail` (spec 016 US1/US2/US3 — T014, T018,
T019, T025). A diferencia de `test_gateway_routing_e2e.py` (HTTP contra la puerta
única), estos tests ejercitan `SentinelGuardrail.async_pre_call_hook` y
`custom_auth.user_api_key_auth` **dentro del container litellm real** — es el único
lugar donde esas clases existen (el motor pinneado no se puede `pip install` en
backend, y no vamos a mockear lo que ya podemos correr de verdad).

Mecanismo: seedeamos una Connection + SecurityPolicy + Guardian reales en la MISMA
Postgres (`SessionLocal`, igual que `seeded_byok_key` de `conftest.py`), y despachamos
un script Python inline vía `docker exec sentinel-litellm python3 -c ...` que llama a
`custom_auth.user_api_key_auth` (T018: confirma que la identidad trae `entity_configs`
reales de la DB) y a `SentinelGuardrail().async_pre_call_hook` (T014 detección real de
PERSON sin prefijo; T019 enforcement BLOCK; T025 fail-closed). El script imprime un
JSON de una sola línea a stdout — el test lo parsea y assertea.

Se auto-skipea si `docker` no está disponible o el container no está corriendo (mismo
espíritu que `live_stack` en conftest.py — e2e opcional sin el stack).
"""
import json
import shutil
import subprocess
import uuid

import pytest

from src.database import SessionLocal
from src.models.budget import APIKey
from src.models.guardian import Guardian
from src.models.policy import SecurityPolicy
from src.models.tenant import DEFAULT_TENANT_ID
from src.services.key_material import hash_key, key_preview

_CONTAINER = "sentinel-litellm"


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        out = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", _CONTAINER],
            capture_output=True, text=True, timeout=5,
        )
        return out.returncode == 0 and out.stdout.strip() == "true"
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _docker_available(),
    reason=f"docker/{_CONTAINER} no disponible — `docker compose up -d litellm` para correr este e2e",
)


def _run_in_litellm(script: str, timeout: int = 30) -> dict:
    """Corre `script` con `python3 -c` DENTRO del container litellm y parsea la
    última línea de stdout como JSON (el script debe imprimir exactamente un
    `print(json.dumps(...))` al final, después de cualquier log de warning)."""
    result = subprocess.run(
        ["docker", "exec", "-i", _CONTAINER, "python3", "-c", script],
        capture_output=True, text=True, timeout=timeout,
    )
    lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
    assert lines, f"sin stdout — stderr:\n{result.stderr}"
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        raise AssertionError(f"última línea no es JSON: {lines[-1]!r}\nstderr:\n{result.stderr}")


@pytest.fixture
def seeded_connection_with_policy():
    """Seedea: SecurityPolicy activa con PERSON=MASK y CREDIT_CARD=BLOCK (para T019),
    Guardian pii_masking con un custom_name distintivo, y una Connection byok que
    referencia ese tenant. Devuelve la key en claro. Cleanup completo en `finally`."""
    db = SessionLocal()
    rand = uuid.uuid4().hex[:8]
    plain = f"sk-sentinel-guardbeh-{rand}"

    policy = db.query(SecurityPolicy).filter(
        SecurityPolicy.tenant_id == DEFAULT_TENANT_ID, SecurityPolicy.is_active == True
    ).first()
    created_policy = False
    if policy is None:
        policy = SecurityPolicy(
            tenant_id=DEFAULT_TENANT_ID, name="e2e-guardrail-behavior", is_active=True,
            entity_configs={"PERSON": "MASK", "CREDIT_CARD": "BLOCK"},
        )
        db.add(policy)
        created_policy = True
    original_entity_configs = dict(policy.entity_configs or {})
    policy.entity_configs = {**original_entity_configs, "PERSON": "MASK", "CREDIT_CARD": "BLOCK"}
    db.commit()

    key_row = APIKey(
        key_hash=hash_key(plain), tenant_id=DEFAULT_TENANT_ID, key_preview=key_preview(plain),
        name=f"e2e-guardbeh-{rand}", tool_type="chat-ui", upstream_mode="byok",
        is_active=True, user_id=None,
    )
    db.add(key_row)
    db.commit()
    db.refresh(key_row)
    key_id = key_row.id

    try:
        yield plain
    finally:
        obj = db.get(APIKey, key_id)
        if obj is not None:
            db.delete(obj)
            db.commit()
        if created_policy:
            db.delete(policy)
        else:
            policy.entity_configs = original_entity_configs
        db.commit()
        db.close()


# ── T018: custom_auth resuelve entity_configs reales desde la DB ───────────────────
#
# NOTA de corrección: la primera versión de este test llamaba a
# `custom_auth.user_api_key_auth` desde un `python3 -c` nuevo dentro del container —
# rompe siempre, porque `prisma_client` (litellm.proxy.proxy_server) es un global que
# solo existe en el PROCESO del servidor litellm ya arrancado, no en un proceso corto
# aparte. La forma real de ejercitar `custom_auth` es a través del servidor vivo — acá,
# vía HTTP contra la puerta única (igual que T019, pero probando la resolución real de
# identidad+entity_configs desde la DB, no una identidad fabricada a mano).

UNKNOWN_KEY_MARK = "clave de acceso desconocida"


def test_t018_custom_auth_resolves_entity_configs_from_real_db(gw, seeded_connection_with_policy):
    plain = seeded_connection_with_policy
    resp = gw.post(
        "/v1/messages",
        headers={"x-api-key": plain},
        json={
            "model": "claude-3-5-sonnet", "max_tokens": 16,
            "messages": [{"role": "user", "content": "guardame esta tarjeta 4111111111111111"}],
        },
    )
    body = resp.text
    # La key existe (custom_auth la resolvió) — si no, veríamos el fail-closed de auth,
    # no el bloqueo de la política.
    assert UNKNOWN_KEY_MARK not in body, (resp.status_code, body)
    # Y el bloqueo vino de entity_configs=BLOCK resuelto DESDE LA DB (no un default
    # hardcodeado — la SecurityPolicy seedeada por el fixture es la única fuente).
    assert resp.status_code == 400, (resp.status_code, body)
    assert "CREDIT_CARD" in body, body


# ── T014: SentinelGuardrail detecta PERSON sin prefijo (US1) ───────────────────────────

def test_t014_guardrail_masks_person_without_title_prefix():
    script = """
import asyncio, json, sys
sys.path.insert(0, "/app")
sys.path.insert(0, "/app/extensions")
from extensions.sentinel_guardrail import SentinelGuardrail

class _FakeIdentity:
    metadata = {"sentinel": {"redact_enabled": True, "entity_configs": {}, "custom_names": [],
                          "custom_entities": []}}

async def main():
    gr = SentinelGuardrail()
    data = {"messages": [{"role": "user", "content": "Juan Perez tiene turno el jueves"}]}
    result = await gr.async_pre_call_hook(_FakeIdentity(), None, data, "anthropic_messages")
    is_blocked = isinstance(result, str)
    masked_text = "" if is_blocked else result["messages"][0]["content"]
    print(json.dumps({
        "blocked": is_blocked,
        "person_in_masked": "Juan Perez" in masked_text or "Juan Pérez" in masked_text,
        "has_placeholder": "[PERSON_" in masked_text,
        "masked_text": masked_text,
    }))

asyncio.run(main())
"""
    result = _run_in_litellm(script)
    assert result["blocked"] is False, result
    assert result["person_in_masked"] is False, result
    assert result["has_placeholder"] is True, result


# ── T019: SentinelGuardrail bloquea por entity_configs=BLOCK (US2) ─────────────────────

def test_t019_guardrail_blocks_entity_configured_as_block():
    script = """
import asyncio, json, sys
sys.path.insert(0, "/app")
sys.path.insert(0, "/app/extensions")
from extensions.sentinel_guardrail import SentinelGuardrail

class _FakeIdentityBlock:
    metadata = {"sentinel": {"redact_enabled": True,
                          "entity_configs": {"CREDIT_CARD": "BLOCK"},
                          "custom_names": [], "custom_entities": []}}

class _FakeIdentityMask:
    metadata = {"sentinel": {"redact_enabled": True,
                          "entity_configs": {"PERSON": "MASK"},
                          "custom_names": [], "custom_entities": []}}

async def main():
    gr = SentinelGuardrail()

    data_block = {"messages": [{"role": "user", "content": "guardame esta tarjeta 4111111111111111"}]}
    r_block = await gr.async_pre_call_hook(_FakeIdentityBlock(), None, data_block, "anthropic_messages")

    data_mask = {"messages": [{"role": "user", "content": "Juan Perez llamo hoy"}]}
    r_mask = await gr.async_pre_call_hook(_FakeIdentityMask(), None, data_mask, "anthropic_messages")

    print(json.dumps({
        "block_case_is_blocked": isinstance(r_block, str),
        "block_reason_mentions_type": isinstance(r_block, str) and "CREDIT_CARD" in r_block,
        "mask_case_is_blocked": isinstance(r_mask, str),
        "mask_case_has_placeholder": (not isinstance(r_mask, str))
            and "[PERSON_" in r_mask["messages"][0]["content"],
    }))

asyncio.run(main())
"""
    result = _run_in_litellm(script)
    assert result["block_case_is_blocked"] is True, result
    assert result["block_reason_mentions_type"] is True, result
    assert result["mask_case_is_blocked"] is False, result
    assert result["mask_case_has_placeholder"] is True, result


# ── T025: SentinelGuardrail falla cerrado si Presidio no responde (US3) ────────────────

def test_t025_guardrail_fails_closed_when_presidio_unavailable():
    script = """
import asyncio, json, sys
sys.path.insert(0, "/app")
sys.path.insert(0, "/app/extensions")
from extensions import sentinel_guardrail

# Simula indisponibilidad SIN tocar el container real: apunta a un puerto cerrado.
sentinel_guardrail._PRESIDIO_URL = "http://nlp-analyzer:9"

class _FakeIdentity:
    metadata = {"sentinel": {"redact_enabled": True, "entity_configs": {}, "custom_names": [],
                          "custom_entities": []}}

async def main():
    gr = sentinel_guardrail.SentinelGuardrail()
    data = {"messages": [{"role": "user", "content": "hola, como estas"}]}
    result = await gr.async_pre_call_hook(_FakeIdentity(), None, data, "anthropic_messages")
    print(json.dumps({
        "blocked": isinstance(result, str),
        "reason_mentions_nlp": isinstance(result, str) and "detección de datos personales" in result,
    }))

asyncio.run(main())
"""
    result = _run_in_litellm(script)
    assert result["blocked"] is True, result
    assert result["reason_mentions_nlp"] is True, result
