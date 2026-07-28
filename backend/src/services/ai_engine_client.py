import logging
import os
import secrets
import time
from dataclasses import dataclass
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

    # F1: forzamos el prefijo sk-basa- en la virtual key. LiteLLM honra un `key`
    # provisto y lo devuelve verbatim; sin esto emite sk-<token>, que el router del
    # gateway (_BASA_KEY_RE = sk-basa-…) NO matchea → byok con key online caería a
    # passthrough (doble-masking + engine key fugada a Anthropic).
    payload["key"] = f"sk-basa-{secrets.token_urlsafe(24)}"

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


# --- Sonda de capas cargadas en el motor (spec 027, T012 — fuente B de data-model §4) ---
#
# Responde UNA sola pregunta: ¿qué guardrails tiene REALMENTE cargados el proceso del motor?
# Existe porque el motor **ignora en silencio** los nombres de guardrail que no conoce (D4):
# no valida, no rompe y no deja rastro, así que una capa "activada" contra un nombre
# inexistente es un no-op invisible. Sin esta sonda, el producto no tiene forma de distinguir
# "corre" de "no hace nada", y la vista de gobernanza vuelve a mentir.
#
# Tres reglas de diseño, las tres load-bearing:
#
# 1. **Cacheada** (~30 s): la consulta el endpoint de estado, que se abre por pageview. Una
#    llamada autenticada con la master key por cada carga de la vista sería tráfico
#    innecesario contra el motor y una amplificación trivial desde el navegador del admin.
# 2. **Tres estados, no dos**: "no se pudo confirmar" (motor caído, timeout, respuesta
#    ilegible) NO es lo mismo que "confirmado que no hay ninguna capa cargada". Un set vacío
#    que signifique las dos cosas colapsa `no_disponible porque el motor no responde` con
#    `no_disponible porque esa capa no está cargada`, que son justo los dos motivos que
#    FR-013 obliga a distinguir. Por eso el resultado lleva `confirmed` aparte de `names`.
# 3. **Se consume SOLO en el backend** (Constitución VII): el payload crudo lleva nombres de
#    guardrail y de proveedor externo; jamás se reenvía a la API pública, a la UI ni a un
#    error. Ni siquiera al log: acá NO se usa `_get`, que loguea `e.response.text` del motor
#    —esa línea existe para los endpoints de administración y arrastra texto del proveedor—;
#    esta función escribe log metadata-only (código de estado / "inalcanzable") y nada más.
#
# NO se usa `test_guardrail` como sonda: hace una llamada LLM real (facturable, con latencia
# de inferencia) y su heurística "400 ⇒ bloqueado" no distingue un bloqueo del guardrail de
# un 400 por payload inválido o modelo inexistente (research D4). Una sonda que cuesta plata
# y miente no es una sonda.

_GUARDRAIL_PROBE_PATH = "/guardrails/list"
# Timeout corto: esto cuelga de una vista de admin. Preferimos "no se pudo confirmar" en 3 s
# —que es un estado honesto y fail-closed— antes que una vista que tarda 10 s en cargar.
_PROBE_TIMEOUT = 3.0
# TTL del resultado confirmado. ~30 s (contrato #2 de contracts/api-gobernanza.md).
_PROBE_TTL_OK = 30.0
# TTL del fallo, más corto a propósito: un motor que vuelve tiene que reflejarse rápido en la
# vista ("los estados se recuperan solos al volver la sonda", quickstart), pero sin dejar que
# cada pageview reintente contra un motor caído.
_PROBE_TTL_FAIL = 5.0


@dataclass(frozen=True)
class EngineGuardrailProbe:
    """Resultado de la sonda. ``confirmed=False`` significa **no sabemos**, no "no hay".

    ``names`` solo tiene sentido con ``confirmed=True``; con ``confirmed=False`` es vacío y
    el consumidor debe tratar toda capa del plano motor como ``no_disponible`` (fail-closed,
    data-model §4.1 regla 5) — jamás como ``aplicandose``.
    """

    confirmed: bool
    names: frozenset
    checked_at: float

    def has(self, name: Optional[str]) -> bool:
        """¿El motor tiene cargada esta capa? Sin confirmación, **siempre False**: no se
        afirma que algo corre cuando no se pudo mirar."""
        return bool(self.confirmed and name and name in self.names)


_UNCONFIRMED = EngineGuardrailProbe(confirmed=False, names=frozenset(), checked_at=0.0)
_probe_cache: EngineGuardrailProbe = _UNCONFIRMED


def _parse_guardrail_names(data) -> frozenset:
    """Nombres cargados desde la respuesta de la sonda, tolerante al shape.

    El motor devuelve hoy ``{"guardrails": [{"guardrail_name": "...", ...}, ...]}``, pero
    versiones distintas devolvieron la lista de strings pelada. Se aceptan ambos y se
    descarta todo lo demás **sin levantar**: un shape inesperado es "no se pudo confirmar"
    (el caller lo convierte en fail-closed), nunca un 500 en la vista de gobernanza.
    """
    items = data.get("guardrails") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("shape inesperado")
    names = set()
    for item in items:
        if isinstance(item, str):
            names.add(item)
        elif isinstance(item, dict):
            name = item.get("guardrail_name") or item.get("name")
            if isinstance(name, str) and name:
                names.add(name)
    return frozenset(names)


async def probe_loaded_guardrails(*, force_refresh: bool = False) -> EngineGuardrailProbe:
    """Las capas realmente cargadas en el motor, cacheadas ~30 s. **Nunca levanta.**

    No levanta porque el consumidor es el cálculo de estado: una excepción ahí volvería
    500 la vista de gobernanza justo cuando el motor está caído, que es exactamente el
    momento en que el admin más necesita ver el estado honesto.
    """
    global _probe_cache
    now = time.monotonic()
    if not force_refresh:
        cached = _probe_cache
        ttl = _PROBE_TTL_OK if cached.confirmed else _PROBE_TTL_FAIL
        if cached.checked_at and (now - cached.checked_at) < ttl:
            return cached

    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            r = await client.get(f"{_BASE_URL}{_GUARDRAIL_PROBE_PATH}", headers=_headers())
            r.raise_for_status()
            names = _parse_guardrail_names(r.json())
        probe = EngineGuardrailProbe(confirmed=True, names=names, checked_at=time.monotonic())
    except httpx.HTTPStatusError as e:
        # Metadata-only: código de estado, jamás el cuerpo de la respuesta del motor.
        logger.warning("Sonda de capas: el motor respondió %s", e.response.status_code)
        probe = EngineGuardrailProbe(confirmed=False, names=frozenset(),
                                     checked_at=time.monotonic())
    except Exception:
        # Inalcanzable, timeout, JSON ilegible, shape inesperado: todo es "no sabemos".
        # Sin `exc_info` y sin str(e): el mensaje de httpx lleva el host interno del motor.
        logger.warning("Sonda de capas: no se pudo confirmar el estado del motor")
        probe = EngineGuardrailProbe(confirmed=False, names=frozenset(),
                                     checked_at=time.monotonic())

    _probe_cache = probe
    return probe


def reset_guardrail_probe_cache() -> None:
    """Invalida el cache de la sonda. Para los tests y para el caller que acaba de cambiar
    el cableado del motor y necesita releer sin esperar el TTL."""
    global _probe_cache
    _probe_cache = _UNCONFIRMED


# --- Embeddings (spec 030 — auto-router semántico) ---

async def embeddings(model: str, inputs: list[str], timeout: float = 10.0) -> list[list[float]]:
    """Vectores de `inputs`, en el MISMO orden, vía `POST {motor}/v1/embeddings`.

    `model` es la entrada del catálogo que apunta al modelo LOCAL de embeddings
    (`router-embeddings` → `ollama/qwen3-embedding:0.6b`): el texto que se embebe
    para decidir el ruteo no sale del host (FR-003 de la 030 + Principio I).

    Dos desvíos deliberados del resto del cliente, los dos load-bearing:

    1. **Las excepciones se propagan crudas** en vez de envolverse en
       `AIEngineClientError`: el auto-router necesita distinguir un timeout
       (`embed_timeout`) de cualquier otro fallo (`embed_error`) para registrar la
       degradación con motivo concreto (FR-004), y el wrapper aplasta esa diferencia
       en un string. Quien llama es responsable de capturar.
    2. **El timeout es parámetro**, no la constante `_TIMEOUT` del cliente: lo fija
       el admin desde el panel del router (`timeout_seconds`), y el presupuesto de
       latencia del ruteo (SC-002) no tiene nada que ver con el de las llamadas de
       administración.

    `inputs` es texto del usuario: no se loguea nunca (Principio VII).
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            f"{_BASE_URL}/v1/embeddings",
            json={"model": model, "input": inputs},
            headers=_headers(),
        )
        r.raise_for_status()
        data = r.json().get("data") or []
    # El contrato OpenAI numera cada vector con `index`; se ordena por él para no
    # depender de que el proveedor conserve el orden del input.
    ordenados = sorted(data, key=lambda item: item.get("index", 0))
    return [item["embedding"] for item in ordenados]


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
