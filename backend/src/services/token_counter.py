"""Real token counting via tiktoken, with a safe char-based fallback.

Used by the compression layer (Ahorro de Costes IA) and the cost calculator
to measure tokens accurately instead of the old chars//4 estimate.
"""
import logging

logger = logging.getLogger("sentinel-secure-gateway.token_counter")

try:
    import tiktoken
    _HAS_TIKTOKEN = True
except ImportError:  # pragma: no cover - fallback path
    _HAS_TIKTOKEN = False
    logger.warning("tiktoken not installed — falling back to char-based estimate (chars/4).")

_DEFAULT_ENCODING = "cl100k_base"


def count_tokens(text: str, model: str | None = None) -> int:
    """Return the token count of ``text`` for ``model`` (best-effort encoding).

    Falls back to len(text)//4 if tiktoken is unavailable or the encoding
    cannot be resolved. Never raises.
    """
    if not text:
        return 0
    if not _HAS_TIKTOKEN:
        return max(0, len(text) // 4)
    try:
        enc = None
        if model:
            try:
                enc = tiktoken.encoding_for_model(model)
            except Exception:
                enc = None
        if enc is None:
            enc = tiktoken.get_encoding(_DEFAULT_ENCODING)
        return len(enc.encode(text))
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"tiktoken count failed ({e}) — fallback chars/4")
        return max(0, len(text) // 4)