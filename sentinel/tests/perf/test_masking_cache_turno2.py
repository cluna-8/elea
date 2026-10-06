"""Demora del turno 2 de una conversación con la caché de análisis (S17; 057 T113; research R34) — medición local, sin Docker.

Una conversación sintética de Claude Code (60 herramientas, `system` grande y 24 turnos de herramienta ≈ 93 000 caracteres
a analizar, la misma de `test_masking_pdf_overhead.py`) pasa por el guardrail REAL bajo enmascarado forzado, con el analizador
SIMULADO: un detector regex que cuenta llamadas y caracteres (lo que cobra el sidecar real). El tiempo «modelado» es
`caracteres / MASKING_PERF_NLP_CPS` (330 caracteres/s, `.env.example`): una cuenta y no una medición del sidecar, que se toma en
la corrida con Docker (T045/T083).

Lo que mide: el turno 1 en frío, el turno 2 (la misma conversación con dos turnos de herramienta más) con la caché y sin ella, y
un pedido idéntico repetido. Lo que exige: el turno 2 solo analiza lo nuevo, el resultado es idéntico con y sin caché (con S13 el
mapa de marcadores es el mismo en los dos) y no sale ningún dato en claro.

    PYTHONPATH=.:backend LITELLM_MODE=PRODUCTION backend/.venv/bin/python -m pytest \\
        sentinel/tests/perf/test_masking_cache_turno2.py -q -s
    MASKING_PERF_REPORT=/tmp/cache.json …            # además escribe el reporte en JSON
"""
import json
import os
import re
import sys
import time

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "backend", "tests", "unit"))

import s14_helpers as h  # noqa: E402  (doble de litellm)
from extensions import sentinel_guardrail  # noqa: E402
from sentinel.tests.perf.test_masking_pdf_overhead import _pedido_tipico_de_claude_code  # noqa: E402

gpolicy = sentinel_guardrail.policy
NLP_CPS = float(os.environ.get("MASKING_PERF_NLP_CPS", "330"))
DNI, REF, CLAVE = h.DNI, "conv-turno-2", "k" * 48
DNI_RE = re.compile(r"\b\d{8}\b")


class _Identidad:
    metadata = {"sentinel": {"region": "latam_ar", "tenant_id": "t1", "key_id": "k1"}}


class _Analizador:
    """Detector regex con contadores: llamadas y caracteres que cobraría el sidecar real."""

    def __init__(self):
        self.calls, self.chars, self.textos = 0, 0, []

    def reset(self):
        self.calls, self.chars, self.textos = 0, 0, []

    async def __call__(self, text, *args, **kwargs):
        self.calls += 1
        self.chars += len(text)
        self.textos.append(text)
        return [{"start": m.start(), "end": m.end(), "entity_type": "DNI", "score": 0.85} for m in DNI_RE.finditer(text)]


@pytest.fixture
def entorno(monkeypatch):
    monkeypatch.setenv("MASKING_NONCE_KEY", CLAVE)
    monkeypatch.delenv("MASKING_ANALYSIS_CACHE_ENABLED", raising=False)
    analizador = _Analizador()

    async def _nada(*_a, **_k):
        return None

    monkeypatch.setattr(sentinel_guardrail, "_auditar_bloqueo", _nada)
    monkeypatch.setattr(sentinel_guardrail, "_marcar_nlp_degradado", _nada)
    monkeypatch.setattr(sentinel_guardrail, "_PRESIDIO_URL", "http://nlp.invalid")
    monkeypatch.setattr(gpolicy, "presidio_analyze", analizador)
    gpolicy.reset_analysis_cache()
    yield analizador
    gpolicy.reset_analysis_cache()


async def _turno(analizador, turnos):
    """Un pedido de la conversación con `turnos` pares de herramienta; devuelve (métricas, cuerpo saliente, informe)."""
    cuerpo = _pedido_tipico_de_claude_code(turnos=turnos)
    cuerpo["litellm_metadata"] = {"sentinel_conversation_ref": REF}
    gpolicy.mark_forced_masking(sentinel_guardrail._metadata_home(cuerpo, "anthropic_messages"))
    analizador.reset()
    t0 = time.perf_counter()
    salida = await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(
        _Identidad(), None, cuerpo, "anthropic_messages")
    ms = (time.perf_counter() - t0) * 1000
    assert isinstance(salida, dict), f"el pedido se bloqueó: {salida!r}"
    informe = cuerpo["litellm_metadata"]["masking_report"]
    saliente = {k: v for k, v in salida.items() if k not in ("litellm_metadata", "metadata")}
    medida = {"analyzer_calls": analizador.calls, "analyzed_chars": analizador.chars,
              "modeled_nlp_s_at_cps": round(analizador.chars / NLP_CPS, 1), "wall_ms": round(ms, 1)}
    return medida, saliente, informe, set(analizador.textos)


@pytest.mark.asyncio
async def test_el_turno_2_solo_analiza_lo_nuevo_y_el_resultado_es_el_mismo_con_y_sin_cache(entorno, monkeypatch):
    informe_final = {"nlp_chars_per_s_modelado": NLP_CPS, "analizador": "regex simulado con contadores"}

    # con caché: turno 1 en frío, turno 2 con dos turnos de herramienta más, y el turno 2 repetido
    t1, _, rep1, textos1 = await _turno(entorno, 24)
    t2, salida2_con, rep2, textos2 = await _turno(entorno, 26)
    t2b, salida2b, _, _ = await _turno(entorno, 26)
    # sin caché: el mismo turno 2, todo se analiza (cada segmento una vez por pedido)
    monkeypatch.setenv("MASKING_ANALYSIS_CACHE_ENABLED", "false")
    gpolicy.reset_analysis_cache()
    s2, salida2_sin, rep2s, _ = await _turno(entorno, 26)

    informe_final.update(turno1_en_frio=t1, turno2_con_cache=t2, turno2_repetido_con_cache=t2b, turno2_sin_cache=s2,
                         aprovechamiento={"chars_no_reanalizados_turno2": s2["analyzed_chars"] - t2["analyzed_chars"],
                                          "reduccion_pct": round(100 * (1 - t2["analyzed_chars"] / s2["analyzed_chars"]), 1)})
    print("\nMASKING_CACHE_TURNO2 " + json.dumps(informe_final, ensure_ascii=False, indent=2))
    if os.environ.get("MASKING_PERF_REPORT"):
        with open(os.environ["MASKING_PERF_REPORT"], "w", encoding="utf-8") as fh:
            json.dump(informe_final, fh, ensure_ascii=False, indent=2)

    # el orden de magnitud del pedido: ~93 000 caracteres (E2)
    assert 80_000 <= t1["analyzed_chars"] <= 110_000, t1
    # el turno 2 SOLO analiza lo nuevo: nada de lo del turno 1 se vuelve a analizar y es una fracción chica
    assert not (textos1 & textos2), "el turno 2 volvió a analizar segmentos del turno 1"
    assert t2["analyzed_chars"] < 0.08 * t1["analyzed_chars"], (t1, t2)
    assert t2["analyzer_calls"] < 0.15 * t1["analyzer_calls"], (t1, t2)
    assert t2["modeled_nlp_s_at_cps"] < 0.1 * t1["modeled_nlp_s_at_cps"]
    assert t2b["analyzer_calls"] == 0, "el mismo pedido repetido no debía llamar al analizador"
    # sin caché el turno 2 paga todo otra vez (lo que ahorra la caché)
    assert s2["analyzed_chars"] > 0.9 * t1["analyzed_chars"], (t1, s2)
    # resultado idéntico con y sin caché (mismo mapa de marcadores por S13) y sin datos en claro
    assert json.dumps(salida2_con, sort_keys=True) == json.dumps(salida2_sin, sort_keys=True)
    assert json.dumps(salida2_con, sort_keys=True) == json.dumps(salida2b, sort_keys=True)
    assert DNI not in json.dumps(salida2_con)
    for rep in (rep1, rep2, rep2s):
        assert rep["scope"] == "full" and rep["unanalyzable"] == 0 and rep["completed"] is True
    assert rep2 == rep2s
