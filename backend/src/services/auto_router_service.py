"""Auto-router semántico (spec 030) — decide a qué modelo del catálogo va una
consulta enviada con el pseudo-modelo «auto».

Port adaptado del servicio de llm-guardian. Tres diferencias que NO son cosméticas
(research R2/R4/R5):

1. **Embeddings locales**: el vector lo produce el motor con la entrada
   `router-embeddings` (→ `ollama/qwen3-embedding:0.6b`), así que el texto de la
   consulta JAMÁS sale del host para decidir el ruteo (FR-003 + Principio I).
   Por eso desaparece el `_ascii_fold` del original, que era workaround de un bug
   del proxy Azure: con el modelo local los acentos y la ñ son señal útil, no ruido.
   `_CACHE_VERSION = "v3-local-qwen"` impide que vectores del pipeline viejo
   (Azure + ascii-fold) se mezclen en silencio con los nuevos.
2. **`target_model` desacoplado del `name`** (R4): en llm-guardian el nombre de la
   ruta ERA el nombre del modelo. Acá la ruta declara a qué modelo del catálogo va,
   de modo que renombrar una ruta no re-rutea tráfico y el panel puede marcar
   «ruta rota» cuando el destino desaparece del catálogo.
3. **Degradación explícita, nunca silenciosa** (FR-004): toda caída al
   `default_model` viaja con `degraded` + `reason` concretos hacia el Debugger
   Técnico, la vitrina y la auditoría durable. Este servicio **jamás levanta** hacia
   el caller: devolver una decisión (degradada si hizo falta) ES el contrato.

La config (`auto_router.json`) se relee en CADA decisión: editar rutas o apagar el
switch aplica en la consulta siguiente, sin reiniciar el motor ni el backend. Los
vectores se cachean por hash de CONTENIDO, así que una utterance nueva es un miss
(se embebe) y una intacta no cuesta nada.
"""

import asyncio
import hashlib
import json
import logging
import math
import os

import httpx

from . import ai_engine_client
from .atomic_file import escribir_atomico
from .redis_client import get_redis

logger = logging.getLogger("basa-secure-gateway.auto-router")

# Pseudo-modelo que el usuario pide en el chat; no existe en el catálogo del motor.
AUTO_MODEL = "auto"

# Se sube esta versión cada vez que cambia el pipeline de embeddings (modelo o
# preprocesado del texto): vectores de pipelines distintos no son comparables y
# seguirían sirviéndose del cache para siempre. "v3" = local qwen, sin ascii-fold.
_CACHE_VERSION = "v3-local-qwen"
_CACHE_TTL_SECONDS = 7 * 24 * 3600
_CACHE_PREFIX = "autoroute:emb:"

# Solo el prefijo de la consulta se embebe: el ruteo es best-effort declarado y el
# tema de un prompt largo ya está en sus primeros caracteres (spec, Edge Cases).
_MAX_EMBED_CHARS = 500
# Umbral de respaldo cuando la ruta no declara uno válido (el schema lo exige, esto
# es defensa para un JSON editado a mano).
_FALLBACK_THRESHOLD = 0.45
_FALLBACK_TIMEOUT = 5.0
_MAX_TIMEOUT_SECONDS = 60

DEFAULT_CONFIG: dict = {
    "enabled": False,
    "default_model": "",
    "timeout_seconds": 5,
    "embedding_model": "router-embeddings",
    "routes": [],
}


class AutoRouterConfigError(Exception):
    """El fichero de config existe pero no se puede leer o parsear.

    NO se usa para «no existe»: un despliegue sin `auto_router.json` es un router
    apagado, no un error de lectura (ver `load_config`).
    """


# --------------------------------------------------------------------------- #
# Config: path, carga, validación y escritura atómica
# --------------------------------------------------------------------------- #

def get_config_path() -> str:
    """Ruta del `auto_router.json`: el volumen `litellm_config` en despliegue, el
    repo en dev. Mismo patrón que `_get_config_path()` de chat.py (config del motor)
    — el JSON del router viaja por el mismo camino que el config.yaml y se edita en
    caliente desde el panel, no desde la imagen."""
    path = "/app/litellm_config/auto_router.json"
    if not os.path.exists(path):
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../litellm/auto_router.json"))
    return path


def _default_config() -> dict:
    """Copia profunda de los defaults: el caller puede mutar lo que reciba sin
    contaminar el diccionario del módulo (`routes` es una lista compartida)."""
    return json.loads(json.dumps(DEFAULT_CONFIG))


def load_config() -> dict:
    """Config del router mergeada sobre `DEFAULT_CONFIG`.

    - Fichero ausente → `DEFAULT_CONFIG` (router apagado, sin rutas).
    - Fichero presente pero ilegible/corrupto → `AutoRouterConfigError`. Es un caso
      distinto y el runtime lo registra como degradación (`config_error`): un JSON
      roto por una edición a mano no puede parecer «apagado a propósito».

    Las claves con valor `null` se ignoran en el merge: una clave presente-en-None
    rompería a todos los consumidores que hacen `.get(campo, default)` río abajo.
    """
    path = get_config_path()
    if not os.path.exists(path):
        return _default_config()

    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        raise AutoRouterConfigError(f"auto_router.json ilegible ({type(e).__name__})") from e

    if not isinstance(raw, dict):
        raise AutoRouterConfigError("auto_router.json no contiene un objeto JSON")

    cfg = _default_config()
    cfg.update({k: v for k, v in raw.items() if v is not None})
    return cfg


def _es_texto(valor) -> bool:
    return isinstance(valor, str) and valor.strip() != ""


def _es_numero(valor) -> bool:
    # `bool` es subclase de `int`: `True` no es un umbral ni un timeout.
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def validate_config(cfg: dict) -> list[str]:
    """Errores legibles del config (lista vacía = válido). Reglas: data-model §1.

    Deliberadamente NO valida que `default_model`/`target_model` existan en el
    catálogo: el catálogo cambia después de guardar igualmente. La ruta rota se
    SEÑALA en el GET (`target_ok: false`) y el runtime degrada al default.
    """
    if not isinstance(cfg, dict):
        return ["El config debe ser un objeto JSON."]

    errores: list[str] = []

    if not isinstance(cfg.get("enabled"), bool):
        errores.append("enabled debe ser booleano (true/false).")

    if not _es_texto(cfg.get("default_model")):
        errores.append("default_model debe ser el nombre no vacío de un modelo del catálogo.")

    timeout = cfg.get("timeout_seconds")
    if not _es_numero(timeout) or not 0 < timeout <= _MAX_TIMEOUT_SECONDS:
        errores.append(
            f"timeout_seconds debe ser un número mayor que 0 y como mucho {_MAX_TIMEOUT_SECONDS}."
        )

    if "embedding_model" in cfg and not _es_texto(cfg.get("embedding_model")):
        errores.append("embedding_model debe ser un texto no vacío.")

    routes = cfg.get("routes")
    if not isinstance(routes, list):
        errores.append("routes debe ser una lista (puede estar vacía).")
        return errores

    for i, ruta in enumerate(routes):
        etiqueta = f"routes[{i}]"
        if not isinstance(ruta, dict):
            errores.append(f"{etiqueta} debe ser un objeto.")
            continue
        if not _es_texto(ruta.get("name")):
            errores.append(f"{etiqueta}: name debe ser un texto no vacío.")
        if not _es_texto(ruta.get("target_model")):
            errores.append(
                f"{etiqueta}: target_model debe ser el nombre no vacío de un modelo del catálogo."
            )
        umbral = ruta.get("score_threshold")
        if not _es_numero(umbral) or not 0 < umbral <= 1:
            errores.append(f"{etiqueta}: score_threshold debe ser un número en el rango (0, 1].")
        utterances = ruta.get("utterances")
        if not isinstance(utterances, list) or not utterances:
            errores.append(f"{etiqueta}: utterances debe ser una lista con al menos un ejemplo.")
        elif not all(_es_texto(u) for u in utterances):
            errores.append(f"{etiqueta}: utterances solo admite textos no vacíos.")

    return errores


def save_config(cfg: dict) -> None:
    """Persiste el config de forma ATÓMICA (`escribir_atomico`: temporal + `os.replace`).

    Sin atomicidad, una consulta que llegue durante el guardado podría leer un JSON a
    medio escribir — que es justo el `config_error` que el panel existe para evitar.
    El mecanismo es compartido con el `config.yaml` del motor: ver `atomic_file`.
    """
    escribir_atomico(
        get_config_path(),
        lambda f: json.dump(cfg, f, ensure_ascii=False, indent=2),
    )


# --------------------------------------------------------------------------- #
# Embeddings + cache por hash de contenido
# --------------------------------------------------------------------------- #

def _cache_key(model: str, texto: str) -> str:
    # El hash incluye el modelo y la versión del pipeline: vectores de modelos o
    # dimensiones distintas no son comparables entre sí.
    huella = hashlib.sha256(f"{model}:{_CACHE_VERSION}:{texto}".encode()).hexdigest()
    return f"{_CACHE_PREFIX}{huella}"


def _abrir_cache():
    """Cliente Redis o `None`. Redis caído NO rompe el ruteo: se embebe sin cache."""
    try:
        return get_redis()
    except Exception:
        logger.warning("Auto-router: Redis no disponible — se embebe sin cache")
        return None


def _cache_get(cache, model: str, texto: str):
    if cache is None:
        return None
    try:
        crudo = cache.get(_cache_key(model, texto))
        return json.loads(crudo) if crudo else None
    except Exception:
        return None


def _cache_set(cache, model: str, texto: str, vector) -> None:
    if cache is None:
        return
    try:
        cache.set(_cache_key(model, texto), json.dumps(vector), ex=_CACHE_TTL_SECONDS)
    except Exception:
        pass


async def _embed(texts: list, *, model: str, timeout: float) -> list:
    """Vectores de `texts` en el MISMO orden, resolviendo por cache lo que se pueda.

    Solo los textos que faltan viajan al motor, deduplicados: con el cache caliente
    una consulta cuesta UN vector (el de la consulta), no la batería entera de
    utterances (SC-002).
    """
    cache = _abrir_cache()
    vectores: dict = {}
    faltantes: list = []

    for texto in texts:
        if texto in vectores or texto in faltantes:
            continue
        cacheado = _cache_get(cache, model, texto)
        if cacheado is not None:
            vectores[texto] = cacheado
        else:
            faltantes.append(texto)

    if faltantes:
        nuevos = await ai_engine_client.embeddings(model, faltantes, timeout=timeout)
        if len(nuevos) != len(faltantes):
            raise ValueError(
                f"el motor devolvió {len(nuevos)} vectores para {len(faltantes)} textos"
            )
        for texto, vector in zip(faltantes, nuevos):
            vectores[texto] = vector
            _cache_set(cache, model, texto, vector)

    return [vectores[t] for t in texts]


def _cos(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# --------------------------------------------------------------------------- #
# Decisión de ruteo
# --------------------------------------------------------------------------- #

def _decision(model_selected: str, *, route=None, score: float = 0.0,
              degraded: bool = False, reason=None) -> dict:
    """Objeto decisión de data-model §2. Metadata-only: acá no entra jamás texto
    del prompt — viaja al Debugger, a la vitrina y a la auditoría durable."""
    return {
        "requested": AUTO_MODEL,
        "route": route,
        "score": round(float(score), 3),
        "model_selected": model_selected,
        "degraded": degraded,
        "reason": reason,
    }


def _umbral_de(ruta: dict) -> float:
    umbral = ruta.get("score_threshold")
    return float(umbral) if _es_numero(umbral) and 0 < umbral <= 1 else _FALLBACK_THRESHOLD


def _timeout_de(cfg: dict) -> float:
    timeout = cfg.get("timeout_seconds")
    if _es_numero(timeout) and 0 < timeout <= _MAX_TIMEOUT_SECONDS:
        return float(timeout)
    return _FALLBACK_TIMEOUT


def _rutas_utilizables(cfg: dict) -> list:
    """Rutas que pueden competir, normalizadas a `(ruta, utterances)`.

    Una ruta sin `target_model` o sin utterances no puede ganar nada; se descarta acá
    para que el recorrido de índices sobre el vector plano quede alineado sí o sí
    (un desfase silencioso ahí asignaría a una ruta el score de otra).
    """
    utilizables = []
    for ruta in cfg.get("routes") or []:
        if not isinstance(ruta, dict) or not _es_texto(ruta.get("target_model")):
            continue
        utterances = [u for u in (ruta.get("utterances") or []) if _es_texto(u)]
        if utterances:
            utilizables.append((ruta, utterances))
    return utilizables


async def route(message: str, available_models: set | None = None) -> dict:
    """Decide el modelo para una consulta «auto». **Nunca levanta.**

    `available_models` (opcional) es el catálogo real del motor: si se pasa y la ruta
    ganadora apunta a un modelo que ya no existe, se degrada al default en vez de
    mandar al motor un modelo inexistente (nunca un 500 por una ruta rota).

    Devuelve el objeto decisión de data-model §2. Motivos posibles:
      - `switch_off`       — el admin apagó el router: default directo, CERO embeddings.
      - `below_threshold`  — nada superó su umbral. NO es degradación: es el diseño
                             (lo que no matchea va al default, que es el local a coste 0).
      - `embed_timeout` / `embed_error` — el motor de embeddings no respondió a tiempo
                             o falló: default con `degraded=true`.
      - `config_error`     — el JSON falta o está roto: default con `degraded=true`.
                             Con el fichero ausente no hay `default_model` que leer, así
                             que `model_selected` viene vacío y el caller debe fallar
                             honestamente en vez de inventarse un modelo.
      - `target_missing`   — la ruta ganó pero su destino no está en el catálogo. Se
                             conservan `route` y `score` a propósito: el registro tiene
                             que decir QUÉ ruta quedó rota, no solo que se degradó.
    """
    path = get_config_path()
    if not os.path.exists(path):
        logger.warning("Auto-router: no hay config en %s — decisión degradada al default", path)
        return _decision(DEFAULT_CONFIG["default_model"], degraded=True, reason="config_error")

    try:
        cfg = load_config()
    except AutoRouterConfigError as e:
        logger.warning("Auto-router: %s — decisión degradada al default", e)
        return _decision(DEFAULT_CONFIG["default_model"], degraded=True, reason="config_error")

    default_model = cfg.get("default_model") or ""

    # Switch global: se responde ANTES de tocar nada más. Cero llamadas de embeddings
    # con el router apagado es un criterio de aceptación verificable en los logs del
    # motor (SC-003), no una optimización.
    if not cfg.get("enabled"):
        return _decision(default_model, reason="switch_off")

    rutas = _rutas_utilizables(cfg)
    if not rutas:
        # Router encendido pero sin rutas: nada puede matchear. Mismo resultado que
        # una consulta bajo umbral, y por el mismo motivo — no es un fallo.
        return _decision(default_model, reason="below_threshold")

    modelo_embeddings = cfg.get("embedding_model") or DEFAULT_CONFIG["embedding_model"]
    timeout = _timeout_de(cfg)
    plana = [u for _, utterances in rutas for u in utterances]
    consulta = (message or "")[:_MAX_EMBED_CHARS]

    try:
        vectores = await _embed(plana + [consulta], model=modelo_embeddings, timeout=timeout)
    except (asyncio.TimeoutError, httpx.TimeoutException):
        logger.warning(
            "Auto-router: timeout de embeddings (%.1fs) — decisión degradada al default", timeout
        )
        return _decision(default_model, degraded=True, reason="embed_timeout")
    except Exception as e:
        # Sin `str(e)`: los mensajes de httpx arrastran el host interno del motor.
        logger.warning(
            "Auto-router: fallo al embeber (%s) — decisión degradada al default", type(e).__name__
        )
        return _decision(default_model, degraded=True, reason="embed_error")

    vector_consulta = vectores[-1]
    mejor_ruta = None
    mejor_score = 0.0
    idx = 0
    for ruta, utterances in rutas:
        umbral = _umbral_de(ruta)
        for _ in utterances:
            score = _cos(vector_consulta, vectores[idx])
            idx += 1
            # `>` estricto sobre el mejor score: en un empate EXACTO gana la primera
            # ruta declarada. Determinista y documentado en el panel.
            if score >= umbral and score > mejor_score:
                mejor_ruta, mejor_score = ruta, score

    if mejor_ruta is None:
        return _decision(default_model, reason="below_threshold")

    destino = mejor_ruta.get("target_model") or ""
    nombre = mejor_ruta.get("name")

    if available_models is not None and destino not in available_models:
        logger.warning(
            "Auto-router: la ruta «%s» apunta a un modelo ausente del catálogo — "
            "decisión degradada al default", nombre
        )
        return _decision(default_model, route=nombre, score=mejor_score,
                         degraded=True, reason="target_missing")

    return _decision(destino, route=nombre, score=mejor_score)
