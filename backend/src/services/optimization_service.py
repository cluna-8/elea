"""Ahorro de Costes IA — compresión de contexto segura.

Reemplaza al compresor naïve anterior (que borraba ``#.*$`` y ``//.*$`` y
corrompía URLs, headings markdown y código). Esta versión:

* Preserva URLs, headings markdown (``#``) y comentarios (``//``) — nunca los
  borra. Solo normaliza espacios en blanco.
* Trata los placeholders PII ``[PII_N]`` / ``[PHI_N]`` como tokens atómicos.
* Cuenta tokens reales con ``tiktoken`` (vía ``token_counter``).
* Respeta un umbral mínimo: no comprime prompts cortos (overhead > ahorro).
* Fail-open: cualquier error devuelve el prompt original.

La capa LLM asistida (US5) se añadirá después; aquí se entrega la base
determinista (US1) y el helper ``analyze`` para la calculadora (US2).
"""
import logging
import os
import re
from typing import Tuple

from .token_counter import count_tokens

logger = logging.getLogger("sentinel-secure-gateway.optimization")

# Umbral mínimo de tokens para activar la compresión (evita overhead en prompts cortos).
DEFAULT_THRESHOLD = int(os.getenv("COMPRESSION_THRESHOLD_TOKENS", "256"))

# --- Módulo de compresión local headroom (US5) — sin tokens, sin torch ---
# headroom-ai (base, sin extras ML) aporta SmartCrusher: compresión LOCAL en Rust de
# contenido estructurado (JSON, logs, tool outputs, RAG, arrays de items repetidos).
# No gasta tokens (no llama a ningún LLM) y no requiere PyTorch. Para prosa libre
# cae al compresor determinista propio (headroom base no comprime prosa sin el modelo).
# Sobreescribible con COMPRESSION_HEADROOM_ENABLED=false para desactivar el módulo.
_HEADROOM_ENABLED = os.getenv("COMPRESSION_HEADROOM_ENABLED", "true").lower() == "true"
_headroom_crusher: "object | None" = None


def _get_headroom_crusher():
    """Lazy-init the headroom SmartCrusher (local, no tokens). Returns None if unavailable."""
    global _headroom_crusher
    if not _HEADROOM_ENABLED:
        return None
    if _headroom_crusher is not None:
        return _headroom_crusher
    try:
        from headroom import SmartCrusher  # type: ignore
        _headroom_crusher = SmartCrusher()
        logger.info("headroom SmartCrusher loaded (local compression module)")
    except Exception as e:  # módulo opcional — fail-open
        logger.info(f"headroom module unavailable ({e}) — using deterministic compressor only")
        _headroom_crusher = None
    return _headroom_crusher

# Placeholders PII/PHI generados por el enmascaramiento — tokens atómicos intocables.
_PLACEHOLDER_RE = re.compile(r"\[(?:PII|PHI)_\d+\]")
# URLs http/https/www — se blindan para que la normalización no las altere.
_URL_RE = re.compile(r"https?://[^\s]+|www\.[^\s]+")


# --- Caché de compresión por hash (spec 012 US5) — sin tokens ---
# Cachea el resultado de comprimir un prompt para no recomprimir duplicados.
# No gasta tokens: solo evita recomputar (y, si la estrategia LLM llegara a
# activarse, evitaría re-llamar al modelo). Fail-open: si Redis no está, comprime.
_CACHE_ENABLED = os.getenv("COMPRESSION_CACHE_ENABLED", "true").lower() == "true"
_CACHE_TTL = int(os.getenv("COMPRESSION_CACHE_TTL", "86400"))  # 24h por defecto


def _cache_key(text: str, strategy: str, aggressiveness: str) -> str:
    import hashlib
    h = hashlib.sha256(f"{strategy}|{aggressiveness}|{text}".encode()).hexdigest()
    return f"sentinel:compress:{h}"


def _cache_get(key: str):
    """Return cached (compressed, saved) tuple or None. Fail-open (None on any error)."""
    try:
        from .redis_client import get_redis
        r = get_redis()
        if r is None:
            return None
        raw = r.get(key)
        if not raw:
            return None
        import json
        data = json.loads(raw)
        return data.get("compressed"), int(data.get("saved", 0))
    except Exception as e:  # fail-open
        logger.warning(f"compression cache get failed ({e}) — recomputing")
        return None


def _cache_set(key: str, compressed: str, saved: int) -> None:
    """Store a compressed result. Fail-open (silent on error)."""
    try:
        from .redis_client import get_redis
        r = get_redis()
        if r is None:
            return
        import json
        r.setex(key, _CACHE_TTL, json.dumps({"compressed": compressed, "saved": saved}))
    except Exception as e:  # fail-open
        logger.warning(f"compression cache set failed ({e}) — skipping cache")


# --- Guardia de calidad (spec 012 US6): detección de respuesta anómala ---
# Una respuesta drásticamente corta/vacía tras compresión sugiere que la compresión
# degradó el prompt; la guardia reintenta con el prompt original (chat.py).
_REVERSAL_MIN_CHARS = int(os.getenv("COMPRESSION_REVERSAL_MIN_CHARS", "5"))


class OptimizationService:
    DEFAULT_THRESHOLD = DEFAULT_THRESHOLD

    # ------------------------------------------------------------------ #
    # Compresión usada por el pipeline de chat (capa 1.5)
    # ------------------------------------------------------------------ #
    @staticmethod
    def compress_context(
        text: str,
        enabled: bool = True,
        threshold: int = DEFAULT_THRESHOLD,
        aggressiveness: str = "medium",
        strategy: str = "deterministic",
        cache_enabled: bool = True,
    ) -> Tuple[str, int]:
        """Compress ``text`` and return (compressed, tokens_saved).

        ``enabled`` is kept as the 2nd positional arg for backward compatibility
        with the existing ``chat.py`` call ``compress_context(prompt, flag)``.

        ``strategy``:
          * ``deterministic`` (default) — compresor local seguro (prosa), sin coste.
          * ``headroom`` — módulo local headroom (SmartCrusher, Rust) para contenido
            estructurado (JSON/logs/RAG/arrays); cae al determinista para prosa o si falla.
            No gasta tokens ni requiere torch.
          * ``llm`` — **descartado** por la restricción verbatim "no gastar tokens para
            ahorrar tokens" (compresión LLM-asistida = circular). Cae a ``headroom`` si el
            contenido es estructurado, si no a ``deterministic``. Nunca gasta tokens.

        ``cache_enabled`` (spec 012 US5): si Redis está disponible, cachea el resultado
        por hash(prompt+strategy+aggressiveness) para no recomprimir duplicados. No gasta
        tokens. Fail-open: si Redis falta, comprime sin caché.
        """
        if not enabled or not text:
            return text, 0

        # US5 — estrategia 'llm' descartada (gasta tokens → circular). Fall-open a
        # headroom/deterministic sin llamar a ningún modelo.
        if strategy == "llm":
            logger.info(
                "compression strategy 'llm' is disabled (token-spending constraint) — "
                "falling back to headroom/deterministic, no tokens spent"
            )
            stripped = text.lstrip()
            strategy = "headroom" if (stripped.startswith("{") or stripped.startswith("[")) else "deterministic"

        original_tokens = count_tokens(text)
        if original_tokens < threshold:
            return text, 0

        # US5 — caché por hash (fail-open)
        if cache_enabled and _CACHE_ENABLED:
            key = _cache_key(text, strategy, aggressiveness)
            cached = _cache_get(key)
            if cached is not None:
                compressed, saved = cached
                logger.info(f"compression cache HIT (saved {saved}) — skipping recompute")
                return compressed, saved

        if strategy == "headroom":
            compressed, saved, applied = OptimizationService._headroom_compress(text)
            if saved > 0:
                logger.info(
                    f"headroom compression: {original_tokens} -> {original_tokens - saved} tokens "
                    f"(saved {saved}, applied={applied})"
                )
                if cache_enabled and _CACHE_ENABLED:
                    _cache_set(_cache_key(text, strategy, aggressiveness), compressed, saved)
                return compressed, saved
            # sin ahorro (prosa o no-JSON) -> cae al determinista abajo

        # Determinista (base segura, sin dependencias)
        try:
            compressed = OptimizationService._deterministic_compress(text, aggressiveness)
        except Exception as e:  # fail-open
            logger.error(f"Compression failed ({e}) — returning original prompt")
            return text, 0

        compressed_tokens = count_tokens(compressed)
        saved = max(0, original_tokens - compressed_tokens)
        logger.info(
            f"Context compressed: {original_tokens} -> {compressed_tokens} tokens "
            f"(saved {saved}, aggressiveness={aggressiveness})"
        )
        if cache_enabled and _CACHE_ENABLED and saved > 0:
            _cache_set(_cache_key(text, "deterministic", aggressiveness), compressed, saved)
        return compressed, saved

    # ------------------------------------------------------------------ #
    # Guardia de calidad (spec 012 US6) — detección de respuesta anómala
    # ------------------------------------------------------------------ #
    @staticmethod
    def response_is_anomalous(content: str, completion_tokens: int) -> bool:
        """Heurística: ¿la respuesta tras compresión es anómala (degradada)?

        Se activa cuando la respuesta está vacía, sin contenido útil, o el motor
        reporta 0 tokens de completion. La guardia de chat.py usa esto para reintentar
        con el prompt original y marcar ``compression_reversed``.
        """
        if completion_tokens is not None and completion_tokens <= 0:
            return True
        if content is None:
            return True
        stripped = content.strip()
        if not stripped:
            return True
        return len(stripped) < _REVERSAL_MIN_CHARS

    # ------------------------------------------------------------------ #
    # Compresor determinista seguro
    # ------------------------------------------------------------------ #
    @staticmethod
    def _deterministic_compress(text: str, aggressiveness: str = "medium") -> str:
        # 1. Blindar URLs y placeholders para que la normalización no los toque.
        shields: dict[str, str] = {}

        def _shield(m: re.Match) -> str:
            key = f"\x00SHIELD{len(shields)}\x00"
            shields[key] = m.group(0)
            return key

        protected = _URL_RE.sub(_shield, text)
        protected = _PLACEHOLDER_RE.sub(_shield, protected)

        # 2. Normalización de espacios — NUNCA borra '#' ni '//'.
        protected = re.sub(r"[ \t]+", " ", protected)        # colapsar espacios/tabs
        protected = re.sub(r" *\n *", "\n", protected)       # recortar bordes de línea
        if aggressiveness in ("medium", "high"):
            protected = re.sub(r"\n{3,}", "\n\n", protected)  # máx. 2 saltos consecutivos
        if aggressiveness == "high":
            protected = re.sub(r"\n{2,}", "\n", protected)    # colapsar líneas en blanco
        protected = protected.strip()

        # 3. Restaurar los spans blindados.
        for key, original in shields.items():
            protected = protected.replace(key, original)
        return protected

    # ------------------------------------------------------------------ #
    # Módulo local headroom (US5) — SmartCrusher (Rust), sin tokens ni torch
    # ------------------------------------------------------------------ #
    @staticmethod
    def _headroom_compress(text: str) -> Tuple[str, int, str]:
        """Local compression via the headroom SmartCrusher module (no tokens, no torch).

        SmartCrusher crushes structured/redundant content (JSON, logs, tool
        outputs, RAG chunks, arrays of repeated items). For free prose it
        typically yields no savings — the caller then falls back to the
        deterministic compressor. Returns (compressed, tokens_saved, applied)
        where ``applied`` is ``headroom`` or ``none``.
        """
        crusher = _get_headroom_crusher()
        if crusher is None or not text:
            return text, 0, "none"
        stripped = text.lstrip()
        # SmartCrusher opera sobre documentos JSON/estructurados.
        if not (stripped.startswith("{") or stripped.startswith("[")):
            return text, 0, "none"
        try:
            compressed = crusher.compact_document_json(text)
        except Exception as e:  # fail-open
            logger.warning(f"headroom compact failed ({e}) — falling back")
            return text, 0, "none"
        if not compressed or len(compressed) >= len(text):
            return text, 0, "none"
        saved = max(0, count_tokens(text) - count_tokens(compressed))
        return compressed, saved, ("headroom" if saved > 0 else "none")

    # ------------------------------------------------------------------ #
    # Helper para la calculadora de decisión (US2)
    # ------------------------------------------------------------------ #
    @staticmethod
    def analyze(
        text: str,
        model: str | None = None,
        threshold: int = DEFAULT_THRESHOLD,
        aggressiveness: str = "medium",
        strategy: str = "deterministic",
    ) -> dict:
        """Return a token breakdown for the calculator.

        With ``strategy="deterministic"`` (default) it estimates via the safe
        local prose compressor. With ``strategy="headroom"`` it runs the headroom
        SmartCrusher module (local, no tokens) and reports what really applied.

        ``cost_saved_usd`` is left None here; the ``costs`` API fills it using
        the model's input rate. ``veredicto`` is preliminary (ratio-based) and
        refined by the API when the rate is unknown.
        """
        original_tokens = count_tokens(text, model)
        if not text or original_tokens < threshold:
            return {
                "tokens_original": original_tokens,
                "tokens_compressed": original_tokens,
                "tokens_saved": 0,
                "cost_saved_usd": None,
                "would_compress": False,
                "veredicto": "no_conviene",
                "ratio": 0.0,
                "strategy_applied": "none",
            }

        if strategy == "headroom":
            compressed, saved, applied = OptimizationService._headroom_compress(text)
            compressed_tokens = count_tokens(compressed, model)
            ratio = round(saved / original_tokens, 4) if original_tokens else 0.0
            return {
                "tokens_original": original_tokens,
                "tokens_compressed": compressed_tokens,
                "tokens_saved": saved,
                "cost_saved_usd": None,
                "would_compress": saved > 0,
                "veredicto": "conviene" if ratio >= 0.10 else "no_conviene",
                "ratio": ratio,
                "strategy_applied": applied,
            }

        compressed = OptimizationService._deterministic_compress(text, aggressiveness)
        compressed_tokens = count_tokens(compressed, model)
        tokens_saved = max(0, original_tokens - compressed_tokens)
        ratio = round(tokens_saved / original_tokens, 4) if original_tokens else 0.0
        would_compress = tokens_saved > 0
        # Veredicto preliminar basado en ratio; la API refina si no hay rate.
        veredicto = "conviene" if ratio >= 0.10 else "no_conviene"
        return {
            "tokens_original": original_tokens,
            "tokens_compressed": compressed_tokens,
            "tokens_saved": tokens_saved,
            "cost_saved_usd": None,
            "would_compress": would_compress,
            "veredicto": veredicto,
            "ratio": ratio,
            "strategy_applied": "deterministic" if would_compress else "none",
        }