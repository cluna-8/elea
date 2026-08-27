import logging
import os
import secrets
import time
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger("basa-secure-gateway")

_BASE_URL = os.getenv("BASA_ENGINE_API_BASE", "http://engine:4000")
_MASTER_KEY = os.getenv("BASA_ENGINE_MASTER_KEY", "")
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


async def _delete_by_id(path: str) -> dict:
    """DELETE HTTP real, sin body — para `/guardrails/{id}`."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            r = await client.delete(f"{_BASE_URL}{path}", headers=_headers())
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


# --- Políticas de contenido (spec 036 US1/US2, sesión 11-ago-2026) ---
#
# El motor (LiteLLM) ya trae un guardrail nativo para esto (`litellm_content_filter`,
# decisión de adoptarlo — ver specs/036-plantillas-politicas-cliente/spec.md). Acá
# NO se reimplementa el motor de reglas: se envuelve su API de guardrails (creada
# con `general_settings.store_model_in_db: true` en litellm/config.yaml) para que el
# resto de Basa hable en un contrato simple — nombre, descripción, palabras a
# bloquear, activo/inactivo — sin conocer el shape completo de `litellm_params`.
#
# `blocked_words` (no `categories`/`category_file`) a propósito: es el camino que NO
# necesita un archivo en disco ni un restart del contenedor — probado en vivo el
# 11-ago-2026 (crear → aplica en el siguiente pedido). El camino de archivo
# (`litellm/policy_categories/`, PR #143) sigue existiendo para categorías más
# elaboradas (excepciones, severidad por keyword) que este contrato simple no cubre
# todavía; las dos formas conviven en el mismo guardrail nativo.
_CONTENT_POLICY_PROVIDER = "litellm_content_filter"
# Prefijo para distinguir, al listar, las políticas que creó Basa de cualquier otro
# guardrail (el propio `basa-guardian`, o el `basa-content-filter` de ejemplo del
# config.yaml) sin depender de un campo aparte que LiteLLM no tiene.
_CONTENT_POLICY_NAME_PREFIX = "basa-policy-"


class ContentPolicyError(AIEngineClientError):
    """Error específico de las políticas de contenido — mismo contrato que
    `AIEngineClientError`, nombre propio para que el caller lo distinga si hace falta."""


class ContentPolicyLostError(ContentPolicyError):
    """El borrado del `update` YA se aplicó y la recreación falló: en el motor NO queda
    ninguna política con este nombre.

    Existe para que el caller pueda **compensar**, y existe SEPARADA de
    `ContentPolicyError` porque las dos fases del borra+crea dejan el sistema en estados
    OPUESTOS y el caller no las puede distinguir de otra forma:

    - falla el `_delete_by_id` → la política sigue **INTACTA** ⇒ no hay nada que reponer.
    - falla el `_post` posterior → la política está **BORRADA** ⇒ hay que reponerla.

    Antes las dos levantaban `ContentPolicyError` y llegaban al endpoint indistinguibles, así
    que una compensación no podía saber cuál de los dos estados tenía delante.

    **Qué pasa si igual se compensa a ciegas (medido contra LiteLLM real el 26-ago-2026, no
    razonado):** el motor tiene UNIQUE sobre `guardrail_name` — un segundo `POST /guardrails`
    con el mismo nombre devuelve HTTP 500 `Unique constraint failed on the fields:
    (guardrail_name)` y el listado sigue con UNA sola. O sea el motor NO queda con un
    duplicado: la reposición ciega es un round-trip condenado cuyo fallo se traga el `except`,
    y el admin recibe el mismo 502 genérico en las dos ramas sin enterarse nunca de si su
    política sobrevivió. El daño es de INFORMACIÓN, no de integridad — que es exactamente lo
    que este tipo arregla.

    Quien atrape esto tiene que ordenar los `except` de más específico a más general:
    `ContentPolicyLostError` ANTES que `ContentPolicyError`/`AIEngineClientError`, o
    nunca entra."""


def _content_policy_guardrail_name(policy_id: str) -> str:
    return f"{_CONTENT_POLICY_NAME_PREFIX}{policy_id}"


def _content_policy_payload(name: str, description: str, blocked_words: list[dict],
                            categories: list[dict], active: bool) -> dict:
    """Arma el body que espera `POST/PUT /guardrails` de LiteLLM a partir del
    contrato simple de Basa. `blocked_words`: `[{"keyword": ..., "action": "BLOCK"|"MASK"}]`
    para palabras propias; `categories`: `[{"category": ..., "action": "BLOCK"|"MASK"}]` para
    activar una plantilla YA ARMADA de `litellm_content_filter` (EU AI Act, Singapur, EAU,
    etc. — PR #143, docs-referencia.md) por nombre, sin archivo propio. Las dos listas
    conviven en el mismo guardrail — un cliente puede tener palabras propias Y una plantilla
    regulatoria activas a la vez. Validado por el schema Pydantic del endpoint
    (backend/src/api/content_policies.py), acá se asume ya válido."""
    litellm_params: dict = {
        "guardrail": _CONTENT_POLICY_PROVIDER,
        "mode": "pre_call",
        "default_on": active,
    }
    if blocked_words:
        litellm_params["blocked_words"] = blocked_words
    if categories:
        litellm_params["categories"] = categories
    return {
        "guardrail": {
            "guardrail_name": name,
            "litellm_params": litellm_params,
            "guardrail_info": {"description": description},
        }
    }


async def create_content_policy(policy_id: str, description: str, blocked_words: list[dict],
                                 categories: list[dict], active: bool) -> dict:
    """Crea una política de contenido nueva en el motor. `policy_id` es un slug corto
    y estable (el admin lo elige) — se usa como parte del `guardrail_name`, así que
    debe ser único; el motor no lo valida por nosotros."""
    name = _content_policy_guardrail_name(policy_id)
    payload = _content_policy_payload(name, description, blocked_words, categories, active)
    data = await _post("/guardrails", payload)
    return {
        "policy_id": policy_id,
        "guardrail_id": data.get("guardrail_id"),
        "name": name,
        "description": description,
        "blocked_words": blocked_words,
        "categories": categories,
        "active": active,
    }


async def update_content_policy(guardrail_id: str, policy_id: str, description: str,
                                 blocked_words: list[dict], categories: list[dict],
                                 active: bool) -> dict:
    """Actualiza una política existente. LiteLLM exige el objeto COMPLETO en el PUT
    (no hay PATCH parcial) — por eso el caller tiene que mandar `blocked_words`/
    `categories` enteros, no solo lo que cambió.

    BORRAR + CREAR, no `PUT /guardrails/{id}` — hallazgo real en vivo (11-ago-2026, con
    Cristian): el PUT de LiteLLM guarda bien en su base, pero cuando la política tiene
    `categories` con `category_file`, la sincronización en memoria del proceso falla
    (`vars() argument must have __dict__ attribute`, log de LiteLLM) — la política queda
    guardada pero la versión que de verdad corre sobre el tráfico se queda vieja, sin
    error visible para el usuario. `POST /guardrails` (crear) no tiene ese problema,
    confirmado con curl directo. El `guardrail_id` cambia — no se persiste en ningún
    lado del lado de Basa (se resuelve siempre por nombre vía `list_content_policies`),
    así que no rompe nada."""
    name = _content_policy_guardrail_name(policy_id)
    try:
        await _delete_by_id(f"/guardrails/{guardrail_id}")
    except AIEngineClientError as e:
        raise ContentPolicyError(str(e)) from e
    payload = _content_policy_payload(name, description, blocked_words, categories, active)
    try:
        data = await _post("/guardrails", payload)
    except AIEngineClientError as e:
        # El delete de arriba YA se aplicó: en el motor no queda ninguna política con este
        # nombre. Tipo propio para que el endpoint pueda reponerla — con
        # `ContentPolicyError` a secas era indistinguible del fallo del delete, donde
        # reponer DUPLICA. Ver `ContentPolicyLostError`.
        raise ContentPolicyLostError(str(e)) from e
    guardrail_id = data.get("guardrail_id")
    return {
        "policy_id": policy_id,
        "guardrail_id": guardrail_id,
        "name": name,
        "description": description,
        "blocked_words": blocked_words,
        "categories": categories,
        "active": active,
    }


async def list_content_policies() -> list[dict]:
    """Políticas de contenido creadas por Basa — filtra del listado completo de
    LiteLLM (que también trae `basa-guardian` y el `basa-content-filter` de
    config.yaml) por el prefijo de nombre y el proveedor, y devuelve el contrato
    simple, no el `litellm_params` completo del motor."""
    data = await _get("/v2/guardrails/list", {})
    resultado = []
    for g in data.get("guardrails", []):
        name = g.get("guardrail_name") or ""
        if not name.startswith(_CONTENT_POLICY_NAME_PREFIX):
            continue
        params = g.get("litellm_params") or {}
        if params.get("guardrail") != _CONTENT_POLICY_PROVIDER:
            continue
        info = g.get("guardrail_info") or {}
        resultado.append({
            "policy_id": name[len(_CONTENT_POLICY_NAME_PREFIX):],
            "guardrail_id": g.get("guardrail_id"),
            "name": name,
            "description": info.get("description", ""),
            "blocked_words": params.get("blocked_words") or [],
            "categories": params.get("categories") or [],
            "active": bool(params.get("default_on")),
        })
    return resultado


async def delete_content_policy(guardrail_id: str) -> None:
    """Borra una política de contenido."""
    try:
        await _delete_by_id(f"/guardrails/{guardrail_id}")
    except AIEngineClientError as e:
        raise ContentPolicyError(str(e)) from e


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
