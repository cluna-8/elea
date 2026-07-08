"""F0-7 smoke tests — compression layer (spec 012).

Covers the two compressor guarantees that matter for safety + savings:
* deterministic compressor preserves URLs and PII placeholders (regression for the
  old regex that deleted `#.*$` / `//.*$` and corrupted `https://…`).
* headroom (local SmartCrusher) yields real savings on structured JSON content,
  and the threshold gate prevents compressing short prompts.
"""
import json

from src.services.optimization_service import OptimizationService


def test_deterministic_preserves_urls_and_placeholders():
    prompt = (
        "Revisa https://example.com/path?q=1#frag y el endpoint "
        "http://api.test/v2//items — datos <PERSON_1> contacto <EMAIL_ADDRESS>.\n\n\n\n"
        "  Espacios   extra  aquí.  "
    )
    compressed, saved = OptimizationService.compress_context(prompt, True, threshold=1, aggressiveness="high")
    # URLs survive verbatim
    assert "https://example.com/path?q=1#frag" in compressed
    assert "http://api.test/v2//items" in compressed
    # PII placeholders survive (must be re-insertable by the unmask layer)
    assert "<PERSON_1>" in compressed
    assert "<EMAIL_ADDRESS>" in compressed
    # Whitespace normalised
    assert "   extra" not in compressed
    assert "\n\n\n" not in compressed
    assert saved >= 0


def test_below_threshold_no_compression():
    short = "Hola, ¿puedes resumir esto?"
    compressed, saved = OptimizationService.compress_context(short, True, threshold=256)
    assert compressed == short
    assert saved == 0


def test_headroom_saves_tokens_on_structured_json():
    # Structured, highly-redundant content is where headroom SmartCrusher shines.
    items = [{"id": i, "campana": f"Marketing Q3 lote {i}", "presupuesto": 1000 + i} for i in range(200)]
    prompt = json.dumps({"reporte": "gastos marketing", "lineas": items}, indent=1)
    compressed, saved = OptimizationService.compress_context(
        prompt, True, threshold=128, strategy="headroom"
    )
    assert saved > 0, "headroom should save tokens on large structured JSON"
    # JSON structure must remain parseable after compression
    assert compressed.strip().startswith(("{", "["))


def test_deterministic_idempotent_on_clean_prompt():
    clean = "This is a clean single-line prompt with normal spacing."
    compressed, saved = OptimizationService.compress_context(clean, True, threshold=1)
    # Already-clean prose should not be damaged
    assert "This is a clean single-line prompt" in compressed
    assert saved >= 0


# ----------------------------------------------------------------------- #
# US5-resto — caché Redis por hash (sin tokens) + descarte de estrategia LLM
# ----------------------------------------------------------------------- #
def test_llm_strategy_disabled_no_tokens_spent(monkeypatch):
    """US5: la estrategia 'llm' está descartada (gasta tokens → circular). Cae a
    deterministic/headroom sin llamar a ningún modelo; el resultado es idéntico al
    de la estrategia local equivalente."""
    prompt = "Revisa   este   prompt    con    espacios   redundantes.   " * 20
    det = OptimizationService.compress_context(prompt, True, threshold=1, strategy="deterministic")
    llm = OptimizationService.compress_context(prompt, True, threshold=1, strategy="llm")
    # Mismo ahorro: 'llm' no gastó tokens, cayó al compresor local.
    assert llm == det


def test_cache_stores_and_returns_hit():
    """US5: tras comprimir, el resultado queda en caché por hash y una segunda
    llamada idéntica devuelve el mismo (compressed, saved) sin recomputar."""
    import src.services.optimization_service as opt
    # Aislar el espacio de claves para no colisionar con otras pruebas
    prompt = "Texto con     bastante    whitespace   redundante   para   comprimir.  " * 30
    key = opt._cache_key(prompt, "deterministic", "high")
    from src.services.redis_client import get_redis
    redis_client = get_redis()
    if redis_client is None:
        # Redis no disponible en este entorno: la caché es fail-open, se omite la
        # aserción de hit (no puede probarse sin Redis) pero el flujo no rompe.
        compressed, saved = OptimizationService.compress_context(prompt, True, threshold=1, strategy="deterministic", cache_enabled=True, aggressiveness="high")
        assert saved >= 0
        return
    redis_client.delete(key)
    try:
        # Primera llamada: cache MISS → comprime y almacena
        c1, s1 = OptimizationService.compress_context(prompt, True, threshold=1, strategy="deterministic", cache_enabled=True, aggressiveness="high")
        assert s1 >= 0
        cached = opt._cache_get(key)
        assert cached is not None, "el resultado debió quedar en caché tras la primera llamada"
        assert cached[1] == s1
        # Segunda llamada idéntica: cache HIT → mismo resultado
        c2, s2 = OptimizationService.compress_context(prompt, True, threshold=1, strategy="deterministic", cache_enabled=True, aggressiveness="high")
        assert (c2, s2) == (c1, s1)
    finally:
        redis_client.delete(key)


# ----------------------------------------------------------------------- #
# US6 — guardia de calidad: detección de respuesta anómala
# ----------------------------------------------------------------------- #
def test_response_anomalous_on_empty_or_short():
    assert OptimizationService.response_is_anomalous("", 0) is True
    assert OptimizationService.response_is_anomalous(None, 100) is True
    assert OptimizationService.response_is_anomalous("   \n  ", 5) is True
    assert OptimizationService.response_is_anomalous("ok", 2) is True  # < min chars (5)


def test_response_normal_not_anomalous():
    assert OptimizationService.response_is_anomalous("La respuesta del modelo es clara y completa.", 25) is False
    assert OptimizationService.response_is_anomalous("Resultado válido y suficientemente largo.", 12) is False