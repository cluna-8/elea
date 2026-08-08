"""BasaGuardrail — la política Basa como CustomGuardrail nativo (spec 014 US1).

Tres hooks sobre el pipeline del motor (firmas confirmadas contra litellm 1.92.0,
research T005 — corren también sobre ``/v1/messages`` con ``call_type=
"anthropic_messages"``):

1. ``async_pre_call_hook``: AI-Act Art.5 → 400; secretos → block; PII → mask
   reversible (el upstream solo ve placeholders).
2. ``async_post_call_success_hook``: unmask de la respuesta no-streaming.
3. ``async_post_call_streaming_iterator_hook``: **Estrategia A′** (decisión T005) —
   el punto de extensión es nativo, y como en ``/v1/messages`` los chunks son frames
   SSE Anthropic crudos (bytes), DENTRO del hook se aplica el rewrite SSE de la
   librería compartida (carry-split). No se reimplementa transporte: el motor sigue
   siendo dueño del HTTP/SSE framing hacia el cliente, auth, usage y retries.

Rutas bridged (modelos no-Claude): el round-trip completo lo cierra la spec 024 —
respuesta dict en el hook 2 (``unmask_response_payload``) y carry de ``[`` pelado en
la lib compartida (deltas de 1-3 chars del bridge partían el placeholder tras el
``[``; research 024 T002).
LÍMITE VIGENTE: ``/v1/responses`` NO está en ``_TEXT_CALL_TYPES`` → esa ruta corre SIN
política (solo identidad de custom_auth) — no ofrecer superficies sobre ella (issue #28).

El mapa reversible viaja en ``litellm_metadata`` (ruta anthropic — el motor filtra
``metadata`` a los campos válidos de la API de Anthropic ANTES del upstream, así que
el mapa no puede fugar; verificado en ``validate_anthropic_api_metadata``) o en
``metadata`` (rutas openai, que el motor no reenvía). JAMÁS se persiste (C1): el
audit logger lo scrubbea explícitamente.

GOTCHAS aplicados (research T005): NO definir ``apply_guardrail`` (redirigiría todo
al unified_guardrail); el override del streaming hook debe estar en ESTA clase hoja.

**Auditoría durable de los bloqueos (spec 031 D3, T005)**: hasta la 031, los cuatro
puntos de bloqueo de este hook devolvían el rechazo y NO dejaban fila en ``audit_logs``
— el logger de auditoría solo implementa el hook de ÉXITO, así que el evento más
importante para un producto de compliance ("se intentó y se impidió") era el único sin
rastro durable en TODO el tráfico byok de herramientas. Ahora cada punto **registra y
después bloquea**: arma la fila (identidad de la Connection, capa, motivo, conteos) y la
POSTea al plano interno del backend antes de devolver el rechazo.
"""
import asyncio
import codecs
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional

from litellm.integrations.custom_guardrail import CustomGuardrail

sys.path.insert(0, os.path.dirname(__file__))
import basa_guardian_policy as policy  # noqa: E402

logger = logging.getLogger("basa-guardrail")

# call_types con body de mensajes que esta política inspecciona/enmascara
_TEXT_CALL_TYPES = {"completion", "acompletion", "atext_completion", "anthropic_messages"}

# spec 016: motor de detección NLP real. Sin esta env var, el guardrail degrada a
# `default_analyze` (regex) — modo dev/demo EXPLÍCITO, nunca el default de prod
# (Constraint SC-2). Se lee una vez al importar el módulo (mismo proceso que la
# imagen pinneada del motor).
_PRESIDIO_URL = os.environ.get("NLP_ANALYZER_URL")


def _metadata_home(data: dict, call_type: Optional[str] = None) -> dict:
    """Dónde viven los campos litellm-specific según la ruta (research T005):
    ``litellm_metadata`` en la ruta anthropic (``metadata`` ahí es un campo del body
    de la API de Anthropic), ``metadata`` en el resto."""
    key = "litellm_metadata" if call_type == "anthropic_messages" or "litellm_metadata" in data else "metadata"
    home = data.get(key)
    if not isinstance(home, dict):
        home = {}
        data[key] = home
    return home


def _pii_tokens_from(data: dict) -> dict:
    for key in ("litellm_metadata", "metadata"):
        home = data.get(key)
        if isinstance(home, dict) and isinstance(home.get("pii_tokens"), dict):
            return home["pii_tokens"]
    return {}


def _basa_identity(user_api_key_dict) -> dict:
    md = getattr(user_api_key_dict, "metadata", None) or {}
    return md.get("basa") or {}


# ── Auditoría durable de los bloqueos (spec 031 D3/D4/D5) ────────────────────────────
#
# Por qué vía HTTP y no un INSERT: la imagen del motor no trae driver de Postgres (ni pip
# ni uv para agregarlo) y `audit_logs` vive en la base del BACKEND — es la misma razón por
# la que existe el plano interno para la identidad. Se reusa el endpoint y el secreto que
# ya usa `basa_audit_logger` para el camino de éxito; acá se estrena el emisor de BLOQUEO.

# Sufijo del probe sobre la misma URL base (contrato §probe): `…/internal/audit/probe`.
_AUDIT_PROBE_SUFFIX = "/probe"

# Presupuesto de red del registro. El plano agentic paga esta latencia ANTES de devolver
# el rechazo, así que el techo es corto y el reintento es UNO (D3): ante una avalancha de
# bloqueos el contador de pérdidas es la válvula, jamás una cola ni un backoff creciente.
_AUDIT_TIMEOUT_S = 5.0
_AUDIT_REINTENTOS = 1
_AUDIT_RETRY_BACKOFF_S = 0.2

# Probe del modo `closed`: barato y con cache, porque se paga por pedido durante una caída.
_AUDIT_PROBE_TIMEOUT_S = 2.0
# Ventana de cache del probe (riesgo R2 del research): 5 s. Se cachean los DOS resultados
# —escribible y no escribible—: sin cachear el "no", una caída convierte cada pedido en un
# probe extra justo cuando la base ya no da abasto. La contrapartida es la ventana de
# riesgo declarada: hasta 5 s de pedidos pueden pasar con la auditoría recién caída.
_AUDIT_PROBE_CACHE_TTL_S = 5.0
_probe_cache: Optional[tuple] = None  # (monotonic, escribible)

# Contador de pérdidas (contrato §Contador de pérdidas) — MISMAS claves que el backend:
# el health las lee de un solo lugar, vengan del plano que vengan.
_REDIS_KEY_AUDIT_LOST = "basa:audit:lost"
_REDIS_KEY_AUDIT_LAST_FAIL = "basa:audit:last_fail"

# Default del host de Redis ALINEADO con el del backend (`services/redis_client.py`:
# `eu-redis`). Antes acá decía `redis` —el nombre del servicio del compose de DEV— y el
# backend decía otra cosa: en un despliegue que no cablee `REDIS_HOST` (el perfil de nube no
# se lo pasaba al servicio `litellm`), el motor ESCRIBÍA las marcas en un host y el health
# las LEÍA de otro, así que la degradación se reportaba como cero. Las claves son
# compartidas entre planos; el destino también tiene que serlo.
_REDIS_HOST_DEFAULT = "eu-redis"


def _redis_endpoint() -> tuple:
    """`(host, port)` de Redis para este proceso. Único lugar donde se resuelve, para que
    los dos escritores de este módulo no puedan apuntar a sitios distintos."""
    return os.getenv("REDIS_HOST", _REDIS_HOST_DEFAULT), int(os.getenv("REDIS_PORT", "6379"))


# Timeouts ACOTADOS para TODO cliente Redis de este módulo (hallazgo #8 de #105). El default
# de `redis.asyncio` es SIN timeout: si Redis está lento o colgado, el `await` del connect o
# del `pipe.execute()` no vuelve nunca y la request degradada —que abre un cliente NUEVO por
# evento— queda pegada. Con timeouts, la marca de estado o el contador fallan RÁPIDO y caen al
# piso de log, sin colgar el request. Nunca infinito. Sub-segundo es holgado para un Redis
# sano (ops < 1 ms). Env-tuneables y con el MISMO nombre que en el backend (`redis_client`).
_REDIS_CONNECT_TIMEOUT_SECONDS = float(os.getenv("REDIS_CONNECT_TIMEOUT_SECONDS", "1.0"))
_REDIS_SOCKET_TIMEOUT_SECONDS = float(os.getenv("REDIS_SOCKET_TIMEOUT_SECONDS", "1.0"))


_AUDIT_FAIL_CLOSED = "closed"
_AUDIT_FAIL_OPEN = "open"

# Capas del registry 027 (`basa_governance.LAYER_KEYS`) por punto de bloqueo. Se escriben
# como literales y no se importa el registry: este módulo corre DENTRO de la imagen del
# motor y no puede pagar un import más en el camino caliente por cuatro constantes. Son
# `layer_key`s estables (identidad, no nombre de display) — ese es el contrato de la 027.
_LAYER_AI_ACT = "ai_act_evaluation"
_LAYER_SECRET = "secret_detection"
_LAYER_PII = "pii_detection"

# Tenant por defecto: mismo fallback que ya aplica el emisor de éxito
# (basa_audit_logger.py) cuando la identidad no resuelve. Un bloqueo sin tenant NO puede
# perderse — el intento existe aunque no sepamos de quién es (edge case de la spec).
_DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

# Rechazo honesto del modo `closed` (contrato §Semántica closed). Mismo mecanismo que el
# fail-closed de NLP: se devuelve un str y el contrato del hook lo convierte en 4xx ANTES
# de que el pedido salga al proveedor — que es lo que exige FR-005 (no gastar dinero en
# tráfico inauditable).
_AUDIT_UNAVAILABLE_MSG = (
    "Petición bloqueada: auditoría no disponible — la instalación exige registro "
    "(audit_fail=closed). El pedido NO se envió al proveedor."
)


def _audit_fail_mode() -> str:
    """`open` | `closed` desde `BASA_AUDIT_FAIL` (contrato §Config).

    Default `open` ante env ausente, vacía o con cualquier otro valor: un typo en la
    configuración NUNCA puede convertirse en un corte de servicio silencioso — el
    fail-closed es una decisión explícita de la instalación. Espejo exacto de
    `audit_service.audit_fail_mode()` del backend; se lee por llamada (no se congela al
    importar) para que un `compose up -d` con el valor cambiado surta efecto sin rebuild.
    """
    return (_AUDIT_FAIL_CLOSED
            if os.environ.get("BASA_AUDIT_FAIL", "").strip().lower() == _AUDIT_FAIL_CLOSED
            else _AUDIT_FAIL_OPEN)


def _audit_url() -> str:
    """URL del plano interno de auditoría (`BASA_AUDIT_URL`), o cadena vacía.

    Sin esta env el plano motor NO tiene por dónde emitir la fila: se trata como fallo de
    escritura (contado y logueado en `open`, rechazo honesto en `closed`) en vez de como
    "no hace falta auditar". Es exactamente el silencio que la 031 viene a terminar."""
    return os.environ.get("BASA_AUDIT_URL", "").strip()


def _internal_secret() -> str:
    return os.environ.get("LITELLM_MASTER_KEY", "")


async def _contar_perdida(motivo: str) -> None:
    """Deja constancia de UN evento de bloqueo sin registrar (contrato §Contador):
    `INCR basa:audit:lost` + `SET basa:audit:last_fail <iso>`.

    Tolerante a Redis caído — el piso innegociable es el `logger.error` que ya emitió el
    caller. Jamás propaga: es el camino de degradación y no puede él mismo romper nada.
    Redis se abre acá y no se reusa un cliente de módulo porque este proceso ya lo hace
    así en el emisor de la vitrina (una conexión por evento, sin estado compartido)."""
    ahora = datetime.now(timezone.utc).isoformat()
    try:
        import redis.asyncio as redis_lib
    except ImportError:
        logger.error("audit: evento PERDIDO sin contador — redis no está en la imagen "
                     "(motivo=%s ts=%s)", motivo, ahora)
        return
    try:
        host, port = _redis_endpoint()
        client = redis_lib.Redis(host=host, port=port,
                                 socket_timeout=_REDIS_SOCKET_TIMEOUT_SECONDS,
                                 socket_connect_timeout=_REDIS_CONNECT_TIMEOUT_SECONDS)
        pipe = client.pipeline()
        pipe.incr(_REDIS_KEY_AUDIT_LOST)
        pipe.set(_REDIS_KEY_AUDIT_LAST_FAIL, ahora)
        await pipe.execute()
        await client.aclose()
    except Exception as exc:  # noqa: BLE001
        logger.error("audit: evento PERDIDO y el contador (%s) también falló: %s "
                     "(motivo=%s ts=%s)", _REDIS_KEY_AUDIT_LOST, exc, motivo, ahora)


async def _emitir_fila(entry: dict) -> bool:
    """POST de la fila al plano interno con UN reintento. True si quedó registrada.

    Qué se reintenta y qué no: los fallos de transporte y los 5xx sí (son justo el fallo
    transitorio que el reintento existe para absorber); un 4xx **no** — un payload que el
    plano interno rechaza no se arregla repitiéndolo, y repetirlo solo suma latencia al
    rechazo que el cliente está esperando.

    Riesgo asumido (aceptado a cambio de no perder el evento): un timeout de LECTURA tras
    un INSERT que sí llegó duplicaría la fila, porque el endpoint no es idempotente. Está
    acotado a un reintento y a filas de bloqueo, que llevan 0 tokens y 0 coste — así que
    el reintento NO puede mover el contador de presupuesto (`_acumular_gasto` corta en
    seco con 0/0/0). Para un producto de auditoría, un duplicado acotado es un mal menor
    frente a un bloqueo sin rastro.
    """
    url = _audit_url()
    if not url:
        logger.error(
            "audit: BASA_AUDIT_URL no configurada — el plano motor no puede registrar el "
            "bloqueo (compliance=%s). Cablearla en el compose del perfil.",
            entry.get("compliance_status"))
        return False

    import httpx  # ya viene en la imagen del motor (mismo import que el resto del plano)
    intentos = _AUDIT_REINTENTOS + 1
    ultimo = ""
    for intento in range(intentos):
        try:
            async with httpx.AsyncClient(timeout=_AUDIT_TIMEOUT_S) as client:
                r = await client.post(url, json=entry,
                                      headers={"X-Basa-Internal": _internal_secret()})
            if r.status_code == 200:
                if intento:
                    logger.info("audit: fila de bloqueo registrada tras %d reintento(s) "
                                "— fallo transitorio absorbido", intento)
                return True
            if r.status_code < 500:
                logger.error("audit: el plano interno RECHAZÓ la fila de bloqueo "
                             "(HTTP %s) — no se reintenta: %s", r.status_code, r.text[:200])
                return False
            ultimo = f"HTTP {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            ultimo = str(exc)
        if intento < intentos - 1:
            logger.warning("audit: POST de la fila de bloqueo falló (%s) — reintento en %.1fs",
                           ultimo, _AUDIT_RETRY_BACKOFF_S)
            await asyncio.sleep(_AUDIT_RETRY_BACKOFF_S)
    logger.error("audit: POST de la fila de bloqueo agotó los %d intentos: %s",
                 intentos, ultimo)
    return False


async def _auditoria_escribible() -> bool:
    """Pre-check del modo `closed` contra `GET /internal/audit/probe`, cacheado 5 s.

    Se pregunta ANTES de correr la política y ANTES de que el pedido salga al proveedor:
    en una instalación que exige registro, tráfico inauditable no se sirve ni se paga.
    """
    global _probe_cache
    ahora = time.monotonic()
    if _probe_cache is not None and ahora - _probe_cache[0] < _AUDIT_PROBE_CACHE_TTL_S:
        return _probe_cache[1]

    escribible = False
    url = _audit_url()
    if not url:
        logger.error("audit: BASA_AUDIT_FAIL=closed sin BASA_AUDIT_URL — el plano motor "
                     "no tiene cómo registrar: se rechaza el tráfico (fail-closed).")
    else:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=_AUDIT_PROBE_TIMEOUT_S) as client:
                r = await client.get(url.rstrip("/") + _AUDIT_PROBE_SUFFIX,
                                     headers={"X-Basa-Internal": _internal_secret()})
            escribible = r.status_code == 200
            if not escribible:
                logger.error("audit: probe de escribibilidad respondió %s — modo closed: "
                             "se rechaza el tráfico", r.status_code)
        except Exception as exc:  # noqa: BLE001
            logger.error("audit: probe de escribibilidad no respondió (%s) — modo closed: "
                         "se rechaza el tráfico", exc)
    _probe_cache = (ahora, escribible)
    return escribible


async def _auditar_bloqueo(user_api_key_dict, data: dict, *, compliance_status: str,
                           layer: str, entidades: Optional[list] = None,
                           pii_detected: bool = False, inicio: float = 0.0) -> None:
    """Registra la fila durable del bloqueo (contrato §Fila de bloqueo) y NUNCA levanta.

    Se llama ANTES de devolver el rechazo (regla de oro de la US1: registrar → bloquear).
    Si la escritura falla, el rechazo al cliente sale igual —el bloqueo no depende de que
    la auditoría ande— pero el fallo deja `logger.error` + contador: nunca "se bloqueó y no
    quedó nada" en silencio.

    `applied_layers` va AUSENTE a propósito (SQL NULL = "pedido sin atribución"). El motor
    todavía no produce la atribución exhaustiva de la 027 por un canal no falsificable
    (ver `_attribution_del_motor` en basa_audit_logger.py); `blocked_by_layer` sí es
    afirmable —lo decidió ESTE código, en este proceso— y es lo que el contrato exige
    obligatorio en un bloqueo.
    """
    try:
        identidad = _basa_identity(user_api_key_dict)
        entry = {
            "tenant_id": identidad.get("tenant_id") or _DEFAULT_TENANT_ID,
            "user_id": identidad.get("client_id"),
            "api_key_id": identidad.get("key_id"),
            "model": (data.get("model") if isinstance(data, dict) else None) or "desconocido",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": 0.0,
            "pii_detected": bool(pii_detected),
            "masked_entities": entidades or [],
            "compliance_status": compliance_status,
            "latency_ms": max(0, int((time.monotonic() - inicio) * 1000)) if inicio else 0,
            "user_group_id": identidad.get("group_id"),
            "blocked_by_layer": layer,
        }
        # Las claves con valor None se ELIMINAN antes de mandar (misma convención que el
        # plano interno aplica al emitir identidad). Acá además evita un 422: los campos
        # escalares del modelo (`model`, tokens…) tienen default pero NO admiten null, así
        # que una identidad anónima mandando `user_id: null` está bien y un `model: null`
        # haría DESAPARECER la fila del intento por validación.
        entry = {k: v for k, v in entry.items() if v is not None}

        if await _emitir_fila(entry):
            return
        logger.error(
            "audit: BLOQUEO NO REGISTRADO (compliance=%s capa=%s modelo=%s key=%s) — el "
            "rechazo al cliente se emite igual, pero el registro durable se perdió",
            compliance_status, layer, entry.get("model"), identidad.get("key_id"))
        await _contar_perdida(f"guardrail/{compliance_status}")
    except Exception as exc:  # noqa: BLE001
        # El registro jamás puede voltear el BLOQUEO: un error acá (identidad rara, redis
        # explotando) deja el evento perdido y ruidoso, nunca una request servida.
        logger.error("audit: fallo inesperado registrando el bloqueo (%s): %s",
                     compliance_status, exc, exc_info=True)


def _conteo(tipo: str, cantidad: int) -> list:
    """Conteo por tipo en el formato del contrato (`[{"type", "count"}]`) — vocabulario
    cerrado y enteros, JAMÁS el valor detectado (C1)."""
    return [{"type": tipo, "count": int(cantidad)}]


def _conteos_de_entidades(entidades: list) -> list:
    """Conteos por `entity_type` de las entidades detectadas (formato del contrato).

    Se cuentan TODAS las detectadas, no solo las de tipos que bloquean: la fila responde
    "qué había en el intento", que es lo que el officer necesita para dimensionar la fuga
    impedida. Solo tipos del vocabulario del detector y enteros — nunca el valor."""
    conteos: dict = {}
    for e in entidades or []:
        tipo = e.get("entity_type") if isinstance(e, dict) else None
        if isinstance(tipo, str) and tipo:
            conteos[tipo] = conteos.get(tipo, 0) + 1
    return [{"type": t, "count": c} for t, c in sorted(conteos.items())]


def _nlp_unavailable_block(home: dict) -> str:
    """Motivo de bloqueo fail-closed (FR-004) cuando el motor NLP no responde —
    reusado tanto en el preview de BLOCK como en el masking real."""
    home["basa_compliance"] = {
        "status": policy.STATUS_NLP_BLOCKED, "risk_level": "unknown",
        "reason": "nlp_unavailable",
    }
    return policy.NLP_BLOCK_MESSAGE


# ── Degradación NLP RUIDOSA (issue #63) ──────────────────────────────────────────────
#
# `nlp_fail_mode = "degrade"` permite seguir sirviendo con el regex de dev cuando el sidecar
# NLP no responde. Es una postura legítima —hay instalaciones que prefieren continuidad—,
# pero el issue #63 es exactamente sobre lo contrario: que esa degradación fuese INVISIBLE.
# Por eso cada request degradada deja TRES rastros y ninguno es opcional:
#   1. `basa_compliance.status = degraded_nlp_regex` → lo copia el emisor de éxito
#      (`basa_audit_logger`, `compliance = request_md["basa_compliance"]["status"]`), así que
#      la fila DURABLE de esa transacción lo lleva sin tocar el logger;
#   2. marca de estado en Redis (`basa:nlp:degraded_*`) → la lee `GET /api/v1/health` y la
#      pinta el panel — mismas claves que escribe el backend, un solo lugar donde mirar;
#   3. `logger.error` (no warning): el nivel efectivo del contenedor es WARNING, y una
#      degradación de la capa de PII no es ruido de fondo.
_REDIS_KEY_NLP_DEGRADED_SINCE = "basa:nlp:degraded_since"
_REDIS_KEY_NLP_DEGRADED_COUNT = "basa:nlp:degraded_requests"


async def _marcar_nlp_degradado() -> None:
    """Deja constancia en Redis de UNA request servida con regex por NLP caído.

    Mismo contrato que `_contar_perdida`: tolerante a Redis ausente y JAMÁS propaga — el
    piso innegociable es el `logger.error` del caller. `SET NX` en `degraded_since` para que
    sobreviva el instante de la PRIMERA degradación (el operador necesita "desde cuándo",
    no "la última vez"); el contador sí acumula. Lo limpia el health cuando confirma que el
    analyzer volvió (un solo punto de reseteo, ver `backend/src/api/health.py`).
    """
    ahora = datetime.now(timezone.utc).isoformat()
    try:
        import redis.asyncio as redis_lib
    except ImportError:
        logger.error("nlp: DEGRADADO a regex sin poder marcarlo — redis no está en la imagen "
                     "(ts=%s)", ahora)
        return
    try:
        host, port = _redis_endpoint()
        client = redis_lib.Redis(host=host, port=port,
                                 socket_timeout=_REDIS_SOCKET_TIMEOUT_SECONDS,
                                 socket_connect_timeout=_REDIS_CONNECT_TIMEOUT_SECONDS)
        pipe = client.pipeline()
        pipe.set(_REDIS_KEY_NLP_DEGRADED_SINCE, ahora, nx=True)
        pipe.incr(_REDIS_KEY_NLP_DEGRADED_COUNT)
        await pipe.execute()
        await client.aclose()
    except Exception as exc:  # noqa: BLE001
        logger.error("nlp: DEGRADADO a regex y la marca de estado (%s) también falló: %s "
                     "(ts=%s)", _REDIS_KEY_NLP_DEGRADED_SINCE, exc, ahora)
        # #8 (#105): con timeout, la marca que no responde falla RÁPIDO en vez de colgar el
        # request. La pérdida de la marca se cuenta REUTILIZANDO el contador ya existente
        # (`_contar_perdida` → `basa:audit:lost` + /health), no un mecanismo nuevo.
        # `_contar_perdida` es best-effort y jamás propaga.
        await _contar_perdida("nlp_degrade_mark")


class BasaGuardrail(CustomGuardrail):
    """La política de compliance de Basa Guardian, montada en el motor."""

    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        if call_type not in _TEXT_CALL_TYPES:
            return None

        inicio = time.monotonic()

        async def _bloquear(mensaje: str, *, status: str, capa: str,
                            entidades: Optional[list] = None,
                            pii_detected: bool = False) -> str:
            """Registrar → bloquear (US1, regla de oro): la fila durable se escribe ANTES
            de devolver el rechazo, en TODOS los puntos de bloqueo de este hook."""
            await _auditar_bloqueo(user_api_key_dict, data, compliance_status=status,
                                   layer=capa, entidades=entidades,
                                   pii_detected=pii_detected, inicio=inicio)
            return mensaje

        # 0) Modo `closed`: sin auditoría escribible NO hay servicio (FR-005). El corte va
        # acá arriba —antes de la política y, sobre todo, antes de que el pedido salga al
        # proveedor— porque el punto entero es no gastar dinero en tráfico que no se va a
        # poder registrar. En `open` (default) este camino no cuesta ni una llamada.
        if _audit_fail_mode() == _AUDIT_FAIL_CLOSED and not await _auditoria_escribible():
            return _AUDIT_UNAVAILABLE_MSG

        identity = _basa_identity(user_api_key_dict)
        inspect_text = policy.extract_inspect_text(data)

        # 1) Enforcement duro: AI-Act Art.5 (400) — real hoy, nivel 1 de [D3]
        verdict = policy.evaluate_ai_act(inspect_text)
        home = _metadata_home(data, call_type)
        home["basa_compliance"] = verdict
        if verdict["status"] == "blocked_prohibited":
            # str → HTTPException 400 (contrato del hook), con fila durable ya escrita.
            return await _bloquear(verdict["reason"], status="blocked_prohibited",
                                   capa=_LAYER_AI_ACT)

        # 2) Secretos/keys: jamás salen hacia un LLM
        secrets = policy.detect_secrets(inspect_text)
        if secrets:
            # El estado del pedido pasa a ser el del bloqueo real: sin esto, la vitrina y
            # la fila contarían historias distintas (acá quedaba el veredicto AI-Act
            # "passed" mientras el pedido se rechazaba por secreto).
            home["basa_compliance"] = {
                "status": "blocked_secret", "risk_level": "high", "reason": "secret_detected",
            }
            return await _bloquear(
                (f"Petición bloqueada: material secreto detectado ({', '.join(secrets)}). "
                 "Las credenciales nunca deben enviarse a un modelo."),
                status="blocked_secret", capa=_LAYER_SECRET,
                # Tipo GENÉRICO a propósito: los nombres del catálogo de secretos llevan
                # marca de proveedor ("OpenAI API Key") y la fila se muestra en la UI
                # white-label (Constitución VII). El conteo es la información auditable;
                # el detalle vive en el mensaje al cliente, que no se persiste.
                entidades=_conteo("SECRET", len(secrets)))

        # 3) Mask PII reversible — toggle por Connection (NULL=heredar → True hoy)
        if identity.get("redact_enabled", True):
            custom_names = identity.get("custom_names") or []
            custom_entities = identity.get("custom_entities") or []

            # Región de patrones estructurados (spec 016, corrección post-review: el
            # despliegue objetivo es Europa, con LATAM como roadmap posterior — ver
            # STRUCTURED_ID_PATTERNS_BY_REGION). Hardcodeado por ahora; llevarlo a un
            # campo por tenant es extensión natural cuando haya despliegues multi-región
            # reales (no antes — YAGNI mientras solo exista Europa).
            region = os.environ.get("BASA_ENTITY_REGION", policy.DEFAULT_REGION)

            if _PRESIDIO_URL:
                async def _analyze(text: str) -> list:
                    return await policy.presidio_analyze(
                        text, _PRESIDIO_URL, custom_names, region, custom_entities=custom_entities)
            else:
                logger.warning(
                    "NLP_ANALYZER_URL no configurada — usando detección regex de "
                    "dev/demo (Constraint SC-2: NO usar en producción con PHI)."
                )
                _analyze = policy.default_analyze

            # Postura ante el analyzer CAÍDO (issue #63). Viaja con la identidad de la
            # Connection (`custom_auth` la trae del `Guardian.config` del guardián
            # `pii_masking`, igual que `custom_names`), así los DOS planos obedecen la misma
            # decisión del admin. Ausente ⇒ `block`: el comportamiento de la 016 no cambia
            # para ninguna instalación existente.
            nlp_fail_mode = policy.resolve_nlp_fail_mode(identity)

            async def _degradar_a_regex(texto_o_body, *, es_body: bool, pmap=None):
                """Rehace la detección con el regex de dev y deja los tres rastros del #63.

                `pmap` se REUSA a propósito cuando se degrada en medio de `mask_body`: si se
                creara un mapa nuevo, los placeholders que el NLP ya alcanzó a insertar antes
                de caerse quedarían huérfanos (otro nonce) y saldrían crudos al cliente en el
                unmask. Reusarlo mantiene UN solo mapa reversible por request.
                """
                logger.error(
                    "nlp: motor de detección NLP no disponible y la política de la "
                    "instalación es `degrade` — este pedido se sirve con detección REGEX de "
                    "dev (cobertura menor; Constraint SC-2). Queda marcado como %s.",
                    policy.STATUS_NLP_DEGRADED)
                await _marcar_nlp_degradado()
                home["basa_compliance"] = {
                    "status": policy.STATUS_NLP_DEGRADED, "risk_level": "unknown",
                    "reason": "nlp_unavailable_degraded_regex",
                }
                if es_body:
                    return await policy.mask_body(texto_o_body, policy.default_analyze, pmap)
                return await policy.default_analyze(texto_o_body)

            # 3a) Preview de entidades sobre el texto completo (misma fuente que ya
            # usan AI-Act/secretos): decide MASK vs BLOCK por tipo ANTES de tocar el
            # body — evita enmascarar parcialmente una request que después se
            # bloquea, y evita una segunda ronda de red si hay que bloquear (spec
            # 016 US2, FR-005/FR-006).
            entity_configs = identity.get("entity_configs") or {}
            try:
                preview_entities = await _analyze(inspect_text)
            except policy.NlpUnavailableError:
                if nlp_fail_mode == policy.NLP_FAIL_BLOCK:
                    return await _bloquear(_nlp_unavailable_block(home),
                                           status=policy.STATUS_NLP_BLOCKED, capa=_LAYER_PII)
                # `degrade`: se sigue, pero con el detector de dev y marcado en los tres
                # canales. El resto del hook (BLOCK por tipo, mask) corre igual sobre estas
                # entidades — degradar no puede además saltearse la política por tipo.
                preview_entities = await _degradar_a_regex(inspect_text, es_body=False)
                _analyze = policy.default_analyze

            blocked_types = sorted({
                e["entity_type"] for e in preview_entities
                if policy.resolve_entity_action(e["entity_type"], entity_configs) == "BLOCK"
            })
            if blocked_types:
                home["basa_compliance"] = {
                    "status": "blocked_entity_type", "risk_level": "high",
                    "reason": f"tipos bloqueados por política: {', '.join(blocked_types)}",
                }
                return await _bloquear(
                    (f"Petición bloqueada: se detectaron datos personales cuya política "
                     f"exige bloquear, no enmascarar ({', '.join(blocked_types)})."),
                    status="blocked_entity_type", capa=_LAYER_PII,
                    entidades=_conteos_de_entidades(preview_entities),
                    # Detección confirmada: la fila dice "había datos personales" aunque no
                    # se enmascarara nada (el pedido se rechazó antes) — D8/FR-002.
                    pii_detected=True)

            # 3b) Sin bloqueos → enmascarar reversible las entidades restantes (MASK).
            # El `PlaceholderMap` se crea ACÁ y no dentro de `mask_body` porque el camino de
            # degradación (#63) necesita continuar con el MISMO mapa: `mask_body` recorre
            # los turnos de a uno, así que una caída a mitad de camino deja parte del body ya
            # enmascarada. Con un mapa nuevo esos placeholders no tendrían original al que
            # volver y saldrían crudos al cliente.
            pmap = policy.PlaceholderMap()
            try:
                data, ph_to_orig = await policy.mask_body(data, _analyze, pmap)
            except policy.NlpUnavailableError:
                if nlp_fail_mode == policy.NLP_FAIL_BLOCK:
                    # Fail-closed (FR-004, default): sin detección NLP confiable no hay
                    # garantía de protección — se rechaza en vez de degradar en silencio.
                    return await _bloquear(_nlp_unavailable_block(home),
                                           status=policy.STATUS_NLP_BLOCKED, capa=_LAYER_PII)
                data, ph_to_orig = await _degradar_a_regex(data, es_body=True, pmap=pmap)

            if ph_to_orig:
                home["pii_tokens"] = ph_to_orig
                home["basa_masked_entities"] = _entity_counts(ph_to_orig)

        return data

    async def async_post_call_success_hook(self, data: dict, user_api_key_dict, response):
        ph_to_orig = _pii_tokens_from(data)
        if not ph_to_orig:
            return response
        _unmask_response_inplace(response, ph_to_orig)
        return response

    async def async_post_call_streaming_iterator_hook(
        self, user_api_key_dict, response: Any, request_data: dict
    ) -> AsyncGenerator[Any, None]:
        ph_to_orig = _pii_tokens_from(request_data)
        if not ph_to_orig:
            async for item in response:
                yield item
            return

        # Estrategia A′: los chunks de /v1/messages son frames SSE crudos (bytes/str).
        # Decoder UTF-8 incremental (un multibyte puede venir partido entre chunks) +
        # buffer de frames (un evento SSE puede venir partido) + carry-split compartido.
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        buffer = ""      # texto acumulado hasta el próximo límite de evento (\n\n)
        carry = ""       # fragmento de placeholder retenido entre deltas
        carry_field: Optional[str] = None

        async for item in response:
            if isinstance(item, bytes):
                buffer += decoder.decode(item)
            elif isinstance(item, str):
                buffer += item
            else:
                # Objeto ya parseado (otra ruta/versión): se entrega tal cual
                yield item
                continue

            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                if not block.strip():
                    continue
                out_blocks, carry, carry_field, _, _ = policy.rewrite_sse_block(
                    block, carry, carry_field, ph_to_orig
                )
                for ob in out_blocks:
                    yield (ob + "\n\n").encode("utf-8")

        # Fin del stream: procesar resto + flush del carry (stream truncado — 0 texto perdido)
        buffer += decoder.decode(b"", final=True)
        if buffer.strip():
            out_blocks, carry, carry_field, _, _ = policy.rewrite_sse_block(
                buffer, carry, carry_field, ph_to_orig
            )
            for ob in out_blocks:
                yield (ob + "\n\n").encode("utf-8")
        if carry:
            # Framed (review 024): un flush crudo lo descarta el parser SSE del cliente.
            yield policy.flush_carry_sse_block(carry, carry_field, ph_to_orig).encode("utf-8")


def _entity_counts(ph_to_orig: dict) -> list:
    counts: dict = {}
    for ph in ph_to_orig:
        m = policy.PH_TYPE_RE.match(ph)
        etype = m.group(1) if m else "PII"
        counts[etype] = counts.get(etype, 0) + 1
    return [{"type": t, "count": c} for t, c in counts.items()]


def _unmask_response_inplace(response, ph_to_orig: dict) -> None:
    """Des-enmascara una respuesta no-streaming (dict bridged u objeto), mutándola.
    La lógica vive en la lib compartida (testeable desde la suite del backend) — 024."""
    policy.unmask_response_payload(response, ph_to_orig)
