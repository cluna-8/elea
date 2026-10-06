"""Demora del enmascarado forzado de alcance completo (S14) — medición INFORMATIVA (057 T097; research R29; QA G2).

Se reporta junto a SC-010 (`test_redirect_overhead.py`: ≤ 50 ms p95 sin adjuntos, que mide el plugin y no el
enmascarado). Acá se mide lo que SC-010 deja afuera: el trabajo del guardrail bajo la señal de forzado.

    · un PDF de 10 y uno de 50 páginas con texto (incluye el arranque del proceso hijo con `pypdf`);
    · un pedido típico de Claude Code de SOLO TEXTO: `system` y descripciones de herramientas grandes, un
      historial largo con `tool_use`/`tool_result`.

**Qué mide y qué no**: usa el detector regex de la base (`default_analyze`) — el piso del costo del recorrido —
y CUENTA las llamadas al analizador y los caracteres analizados, que son lo que el sidecar real cobra. NO mide
el sidecar de entidades (no está en este arnés): el tiempo «modelado» es `caracteres / MASKING_PERF_NLP_CPS`
(330 caracteres/s, el rendimiento medido del analizador, `.env.example`), una cuenta y no una medición. Las
cifras reales con el analizador activo se toman en la corrida con Docker del tramo (T045/T083).

No fija presupuestos: informa. Solo falla si el enmascarado deja datos en claro o el pedido sale no analizable.

    cd <repo> && PYTHONPATH=.:backend LITELLM_MODE=PRODUCTION backend/.venv/bin/python -m pytest \\
        sentinel/tests/perf/test_masking_pdf_overhead.py -q -s
    MASKING_PERF_REPORT=/tmp/masking.json …            # además escribe el reporte en JSON
"""
import json
import os
import statistics
import sys
import time

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "backend", "tests", "unit"))

import s14_helpers as h  # noqa: E402  (PDFs generados a mano; doble de litellm)
from extensions import sentinel_guardian_policy as policy  # noqa: E402

ROUNDS = 5
NLP_CPS = float(os.environ.get("MASKING_PERF_NLP_CPS", "330"))
DNI = h.DNI


class _AnalizadorContado:
    """El detector regex con contadores: llamadas y caracteres que cobraría el sidecar real."""

    def __init__(self):
        self.calls = 0
        self.chars = 0

    async def __call__(self, text):
        self.calls += 1
        self.chars += len(text)
        return await policy.default_analyze(text, region="latam_ar")


def _pedido_tipico_de_claude_code(turnos=24, herramientas=60):
    descripcion = ("Lee un archivo del sistema de archivos local. Usa rutas absolutas. Por defecto lee hasta "
                   "2000 líneas desde el inicio; con offset y limit se leen tramos largos. Los resultados se "
                   "devuelven con números de línea. ") * 4
    esquema = {"type": "object", "required": ["file_path"], "properties": {
        "file_path": {"type": "string", "description": "Ruta absoluta del archivo a leer."},
        "offset": {"type": "integer", "description": "Línea desde la que empezar a leer."},
        "limit": {"type": "integer", "description": "Cantidad de líneas a leer."}}}
    mensajes = [{"role": "user", "content": f"Revisá el cliente con DNI {DNI} y arreglá el error de login."}]
    for i in range(turnos):
        mensajes.append({"role": "assistant", "content": [
            {"type": "text", "text": f"Voy a leer el archivo {i}."},
            {"type": "tool_use", "id": f"toolu_{i:04d}", "name": "Read",
             "input": {"file_path": f"/repo/src/modulo_{i}.py", "limit": 200}}]})
        mensajes.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"toolu_{i:04d}",
             "content": f"# archivo {i}\n" + "def funcion():\n    return 42\n" * 40}]})
    return {
        "model": "claude-sonnet-4-5", "max_tokens": 8192, "stream": True,
        "system": [{"type": "text", "text": "Sos Claude Code, la CLI oficial. " * 300,
                    "cache_control": {"type": "ephemeral"}}],
        "messages": mensajes,
        # Cada cadena es distinta: el analizador memoriza por texto dentro del pedido y repetir descripciones
        # regalaría aciertos que un pedido real no tiene.
        "tools": [{"name": f"Herramienta{i}", "description": f"Herramienta {i}. " + descripcion,
                   "input_schema": {**esquema, "properties": {
                       **esquema["properties"],
                       "file_path": {"type": "string", "description": f"Ruta absoluta del archivo {i}."}}}}
                  for i in range(herramientas)],
    }


async def _medir(cuerpo_fn, rondas=ROUNDS):
    tiempos, ultimo = [], None
    for _ in range(rondas):
        cuerpo = cuerpo_fn()
        analizador = _AnalizadorContado()
        tally = policy.MaskingTally()
        policy.reset_pdf_state()                      # sin caché: se mide la extracción, no el acierto
        t0 = time.perf_counter()
        cuerpo, _ = await policy.mask_body(cuerpo, analizador, policy.PlaceholderMap(), scope="full",
                                           fmt="anthropic", tally=tally)
        tiempos.append((time.perf_counter() - t0) * 1000)
        ultimo = (cuerpo, analizador, tally)
    cuerpo, analizador, tally = ultimo
    return {
        "median_ms": round(statistics.median(tiempos), 1), "min_ms": round(min(tiempos), 1),
        "max_ms": round(max(tiempos), 1), "analyzer_calls": analizador.calls,
        "analyzed_chars": analizador.chars,
        "modeled_nlp_s_at_cps": round(analizador.chars / NLP_CPS, 1),
        "unanalyzable": tally.unanalyzable, "unanalyzable_kinds": tally.kinds,
    }, cuerpo


def _pdf_de_paginas(n):
    return h.pdf_con_texto(*[f"Pagina {i}: ficha del cliente con DNI {DNI}. " + "Texto de relleno del documento. " * 60
                             for i in range(n)])


@pytest.mark.asyncio
async def test_demora_del_forzado_con_pdf_y_con_un_pedido_tipico_de_solo_texto():
    informe = {"nlp_chars_per_s_modelado": NLP_CPS, "analizador": "regex de la base (piso del recorrido)",
               "pypdf": h.HAY_PYPDF}

    medida, cuerpo = await _medir(_pedido_tipico_de_claude_code)
    informe["claude_code_solo_texto"] = {**medida, "bytes": len(json.dumps(cuerpo)),
                                         "herramientas": 60, "turnos": 24}
    assert medida["unanalyzable"] == 0
    assert DNI not in json.dumps(cuerpo), "el DNI del primer turno salió en claro"

    for paginas in (10, 50):
        pdf = _pdf_de_paginas(paginas)

        def _con_pdf(pdf=pdf):
            return {"model": "m", "messages": [{"role": "user", "content": [
                {"type": "text", "text": "resumí el documento"}, h.bloque_pdf(pdf)]}]}

        medida, cuerpo = await _medir(_con_pdf, rondas=3)
        informe[f"pdf_{paginas}_paginas"] = {**medida, "pdf_bytes": len(pdf)}
        if h.HAY_PYPDF:
            assert medida["unanalyzable"] == 0, medida
            assert DNI not in json.dumps(cuerpo)
        else:
            assert medida["unanalyzable_kinds"] == ["pdf_unavailable"]

    print("\nMASKING_PDF_OVERHEAD " + json.dumps(informe, ensure_ascii=False, indent=2))
    if os.environ.get("MASKING_PERF_REPORT"):
        with open(os.environ["MASKING_PERF_REPORT"], "w", encoding="utf-8") as fh:
            json.dump(informe, fh, ensure_ascii=False, indent=2)
