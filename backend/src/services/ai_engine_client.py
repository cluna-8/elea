import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("basa-secure-gateway")

_BASE_URL = os.getenv("LITELLM_API_BASE", "http://litellm:4000")
_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY", "")
_TIMEOUT = 10.0


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_MASTER_KEY}",
        "Content-Type": "application/json",
    }


class AIEngineClientError(Exception):
    """Raised when the AI engine is unreachable or returns an unexpected error."""


async def _post(path: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            r = await client.post(f"{_BASE_URL}{path}", json=payload, headers=_headers())
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            logger.error("AI engine %s returned %s: %s", path, e.response.status_code, e.response.text)
            raise AIEngineClientError(f"AI engine error on {path}: {e.response.status_code}") from e
        except httpx.RequestError as e:
            logger.error("AI engine unreachable at %s: %s", path, e)
            raise AIEngineClientError("AI engine is unavailable") from e


async def _get(path: str, params: dict) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            r = await client.get(f"{_BASE_URL}{path}", params=params, headers=_headers())
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            logger.error("AI engine %s returned %s: %s", path, e.response.status_code, e.response.text)
            raise AIEngineClientError(f"AI engine error on {path}: {e.response.status_code}") from e
        except httpx.RequestError as e:
            logger.error("AI engine unreachable at %s: %s", path, e)
            raise AIEngineClientError("AI engine is unavailable") from e


async def _delete(path: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            r = await client.post(f"{_BASE_URL}{path}", json=payload, headers=_headers())
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            logger.error("AI engine %s returned %s: %s", path, e.response.status_code, e.response.text)
            raise AIEngineClientError(f"AI engine error on {path}: {e.response.status_code}") from e
        except httpx.RequestError as e:
            logger.error("AI engine unreachable at %s: %s", path, e)
            raise AIEngineClientError("AI engine is unavailable") from e


# --- Teams ---

async def create_team(name: str, max_budget: Optional[float] = None, budget_duration: str = "30d") -> str:
    """Creates a team in the AI engine. Returns the engine_team_id."""
    payload: dict = {"team_alias": name}
    if max_budget is not None:
        payload["max_budget"] = max_budget
        payload["budget_duration"] = budget_duration
    data = await _post("/team/new", payload)
    return data["team_id"]


async def get_team_spend(engine_team_id: str) -> dict:
    """Returns spend info for a team: {spend_usd, max_budget, remaining}."""
    data = await _get("/team/info", {"team_id": engine_team_id})
    spend = data.get("spend") or 0.0
    max_budget = data.get("max_budget")
    return {
        "spend_usd": float(spend),
        "max_budget": float(max_budget) if max_budget is not None else None,
        "remaining": float(max_budget - spend) if max_budget is not None else None,
    }


# --- Users ---

async def create_user(user_id: str, max_budget: Optional[float] = None) -> str:
    """Creates a user in the AI engine. Returns the engine_user_id."""
    payload: dict = {"user_id": user_id}
    if max_budget is not None:
        payload["max_budget"] = max_budget
    data = await _post("/user/new", payload)
    return data["user_id"]


async def get_user_spend(engine_user_id: str) -> dict:
    """Returns spend info for a user: {spend_usd, max_budget, remaining}."""
    data = await _get("/user/info", {"user_id": engine_user_id})
    spend = data.get("spend") or 0.0
    max_budget = data.get("max_budget")
    return {
        "spend_usd": float(spend),
        "max_budget": float(max_budget) if max_budget is not None else None,
        "remaining": float(max_budget - spend) if max_budget is not None else None,
    }


# --- Virtual Keys ---

async def generate_key(
    name: str,
    max_budget: Optional[float] = None,
    budget_duration: str = "30d",
    models: Optional[list] = None,
    team_id: Optional[str] = None,
    user_id: Optional[str] = None,
    rpm_limit: Optional[int] = None,
    tpm_limit: Optional[int] = None,
) -> dict:
    """
    Generates a virtual key in the AI engine.
    Returns {plain_key, engine_key_token} where engine_key_token is the
    first 10 chars used to reference the key in future engine calls.

    rpm/tpm/max_budget are forwarded to LiteLLM so the proxy enforces them at the
    edge as a hard backstop (USE-LITE). Our Redis rate-limiter remains the soft
    layer that also covers JWT sessions and powers the X-RateLimit-* response
    headers + audit (KEEP-WITH-REASON).
    """
    payload: dict = {"key_alias": name}
    if max_budget is not None:
        payload["max_budget"] = max_budget
        payload["budget_duration"] = budget_duration
    if models:
        payload["models"] = models
    if team_id:
        payload["team_id"] = team_id
    if user_id:
        payload["user_id"] = user_id
    if rpm_limit is not None:
        payload["rpm_limit"] = rpm_limit
    if tpm_limit is not None:
        payload["tpm_limit"] = tpm_limit

    data = await _post("/key/generate", payload)
    plain_key: str = data["key"]
    return {
        "plain_key": plain_key,
        "engine_key_token": plain_key,
    }


async def get_key_spend(engine_key_token: str) -> dict:
    """Returns spend info for a key: {spend_usd, max_budget, remaining}."""
    data = await _get("/key/info", {"key": engine_key_token})
    info = data.get("info", data)
    spend = info.get("spend") or 0.0
    max_budget = info.get("max_budget")
    return {
        "spend_usd": float(spend),
        "max_budget": float(max_budget) if max_budget is not None else None,
        "remaining": float(max_budget - spend) if max_budget is not None else None,
    }


async def delete_key(engine_key_token: str) -> None:
    """Revokes a key in the AI engine."""
    await _delete("/key/delete", {"keys": [engine_key_token]})


# --- Guardrails ---

async def get_active_guardrail_names(db) -> list[str]:
    """Returns the engine_guardrail_name of all active guardians that have one."""
    from ..models.guardian import Guardian
    guardians = db.query(Guardian).filter(
        Guardian.is_active == True,
        Guardian.engine_guardrail_name.isnot(None)
    ).all()
    return [g.engine_guardrail_name for g in guardians]


async def test_guardrail(guardrail_name: str, test_text: str) -> dict:
    """Sends a minimal request to the engine with a single guardrail to test it."""
    payload = {
        "model": "gemini-2.5-flash-lite",
        "messages": [{"role": "user", "content": test_text}],
        "guardrails": [guardrail_name],
        "stream": False,
        "max_tokens": 10,
    }
    try:
        await _post("/v1/chat/completions", payload)
        return {"blocked": False, "reason": None}
    except AIEngineClientError as e:
        err = str(e)
        if "400" in err:
            return {"blocked": True, "reason": "La petición fue bloqueada por las políticas de seguridad."}
        raise
