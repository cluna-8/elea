"""Bug real encontrado en revisión (09-sep, contrato 2 de la 043): `_auditar_bloqueo`
(la fila de auditoría cuando un guardrail del motor bloquea un pedido) nunca leía
`acted_for_user_id`, aunque `custom_auth.py` ya lo calcula y lo deja en la identidad —
una llave de servicio actuando "en nombre de" alguien que se bloqueaba quedaba atribuida
solo a la cuenta de servicio, nunca a la persona real. `litellm` es una dependencia real
instalada en este venv (a diferencia de `test_custom_auth_acting_user_043.py`, que sí
necesita un doble porque su import es más liviano) — se usa el `UserAPIKeyAuth` real.
`_emitir_fila` (el único punto de I/O) se monkeypatchea para capturar el payload, sin red
ni base real."""
import pytest

from extensions import sentinel_guardrail as guardrail  # noqa: E402
from litellm.proxy._types import UserAPIKeyAuth as _FakeUser  # noqa: E402


@pytest.mark.asyncio
async def test_bloqueo_con_llave_de_servicio_atribuye_a_la_persona_real(monkeypatch):
    capturado = {}

    async def fake_emitir_fila(entry):
        capturado.update(entry)
        return True

    monkeypatch.setattr(guardrail, "_emitir_fila", fake_emitir_fila)

    user = _FakeUser(metadata={"sentinel": {
        "tenant_id": "t-1", "client_id": "svc.rag-masking-id", "key_id": "key-1",
        "group_id": None, "acted_for_user_id": "ana-la-persona-real",
    }})

    await guardrail._auditar_bloqueo(
        user, {"model": "gpt-4o"}, compliance_status="blocked_by_policy",
        layer="secret_detection", entidades=[], pii_detected=False, inicio=0.0,
    )

    assert capturado.get("acted_for_user_id") == "ana-la-persona-real", (
        "la fila de bloqueo debe atribuirse a la persona en cuyo nombre actuaba la llave "
        f"de servicio, no solo a la cuenta de servicio — capturado: {capturado}"
    )
    assert capturado.get("user_id") == "svc.rag-masking-id"  # sigue viajando también


@pytest.mark.asyncio
async def test_bloqueo_sin_acted_for_user_id_no_manda_el_campo(monkeypatch):
    """Una llave normal (sin actuar en nombre de nadie) no debe mandar el campo en
    absoluto — `entry` ya filtra los `None` antes de emitir (mismo criterio que el resto
    de los campos opcionales)."""
    capturado = {}

    async def fake_emitir_fila(entry):
        capturado.update(entry)
        return True

    monkeypatch.setattr(guardrail, "_emitir_fila", fake_emitir_fila)

    user = _FakeUser(metadata={"sentinel": {
        "tenant_id": "t-1", "client_id": "cliente-normal", "key_id": "key-2", "group_id": None,
    }})

    await guardrail._auditar_bloqueo(
        user, {"model": "gpt-4o"}, compliance_status="blocked_by_policy",
        layer="secret_detection", entidades=[], pii_detected=False, inicio=0.0,
    )

    assert "acted_for_user_id" not in capturado
