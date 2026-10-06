"""SC-010 (informativa): demora agregada hasta el primer contenido con la política encendida.

Presupuesto: ≤ 50 ms p95 contra un upstream falso instantáneo, sin adjuntos (spec SC-010, plan §Performance
Goals). **Qué mide y qué no (QA §6)**: mide el trabajo del plugin dentro de la pasarela en proceso (resolver,
normalizar, firmar la autorización, envolver el stream), con el motor reemplazado por un doble que contesta al
instante: NO mide la red, el motor, el enmascarado ni el destino real. La medición con PDF bajo forzado la hace
T097 (`test_masking_pdf_overhead.py`), y la de punta a punta contra Azure, T045/T083.

    cd <repo> && PYTHONPATH=.:backend LITELLM_MODE=PRODUCTION backend/.venv/bin/python -m pytest \\
        sentinel/tests/perf/test_redirect_overhead.py -q -s
    REDIRECT_PERF_REPORT=/tmp/overhead.json …                     # además escribe el reporte en JSON
"""
import json
import os
import statistics
import time

import httpx

REAL_CLIENT = httpx.AsyncClient          # antes de que el arnés lo reemplace por el motor falso

import pytest  # noqa: E402

from sentinel.redirect import stream  # noqa: E402
from sentinel.redirect.plugin import RedirectPlugin  # noqa: E402
from sentinel.tests import corpus_claude as corpus  # noqa: E402
from sentinel.tests import gw_harness as h  # noqa: E402
from sentinel.tests import redirect_fixtures as fx  # noqa: E402

BUDGET_P95_MS = 50.0
WARMUP, SAMPLES, ROUNDS = 20, 200, 3


def p95(values):
    values = sorted(values)
    return values[min(len(values) - 1, int(round(0.95 * (len(values) - 1))))]


async def _first_content_ms(app, n):
    doc = corpus.load("claude_code_messages_beta")
    headers = {"Authorization": f"Bearer {h.VK}", "anthropic-version": "2023-06-01"}
    out = []
    async with REAL_CLIENT(transport=httpx.ASGITransport(app=app), base_url="http://gw") as client:
        for i in range(WARMUP + n):
            t0 = time.perf_counter()
            async with client.stream("POST", "/gw/v1/messages?beta=true", headers=headers, json=doc["body"]) as r:
                assert r.status_code == 200
                async for _ in r.aiter_raw():
                    elapsed = (time.perf_counter() - t0) * 1000
                    break
            if i >= WARMUP:
                out.append(elapsed)
    return out


@pytest.fixture
def env(monkeypatch):
    e = h.gateway_env(monkeypatch)
    e.engine.stream_chunks = (b'event: message_start\ndata: {"type":"message_start","message":{"id":"m","model":"x",'
                              b'"usage":{"input_tokens":3}}}\n\n', b'event: message_stop\ndata: {"type":"message_stop"}\n\n')
    yield e
    h.close_env()


async def test_demora_agregada_hasta_el_primer_contenido_con_la_politica_encendida(env):
    app = env.client.app
    deltas, base_all, on_all = [], [], []
    for _ in range(ROUNDS):
        h.gp.clear_gateway_plugins()
        base = await _first_content_ms(app, SAMPLES)                 # sin plugin: lo de siempre
        h.gp.clear_gateway_plugins()
        env.register(fx.snapshot("on"))
        on = await _first_content_ms(app, SAMPLES)                   # política encendida, destino traducido
        deltas.append(p95(on) - p95(base))
        base_all += base
        on_all += on
    added = statistics.median(deltas)
    report = {"sc": "SC-010", "kind": "plugin en proceso con motor falso instantáneo (no la ruta real)",
              "samples_per_round": SAMPLES, "rounds": ROUNDS, "budget_p95_ms": BUDGET_P95_MS,
              "baseline_p50_ms": round(statistics.median(base_all), 3), "baseline_p95_ms": round(p95(base_all), 3),
              "on_p50_ms": round(statistics.median(on_all), 3), "on_p95_ms": round(p95(on_all), 3),
              "added_p95_ms_per_round": [round(d, 3) for d in deltas], "added_p95_ms_median": round(added, 3)}
    print("\nSC-010 " + json.dumps(report, ensure_ascii=False))
    if os.environ.get("REDIRECT_PERF_REPORT"):
        with open(os.environ["REDIRECT_PERF_REPORT"], "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    assert added <= BUDGET_P95_MS, report


async def test_los_hooks_del_plugin_por_si_solos_cuestan_una_fraccion_del_presupuesto(monkeypatch):
    """El mismo trabajo sin la pasarela: resolver + normalizar + firmar + envolver el primer evento."""
    doc = corpus.load("claude_code_messages_beta")
    plugin = RedirectPlugin(store=fx.store(fx.snapshot("on")), ping_after=15.0)
    monkeypatch.setenv("REDIRECT_INTERNAL_KEY", fx.INTERNAL_KEY)
    first = (b'event: message_start\ndata: {"type":"message_start","message":{"model":"x","usage":{}}}\n\n',)

    async def one():
        t0 = time.perf_counter()
        ctx = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5")
        await plugin.pre_request(ctx)
        plugin.pre_engine(ctx, json.loads(json.dumps(doc["body"])), {"x-test": "1"})

        async def src():
            for c in first:
                yield c

        async for _ in plugin.wrap_stream(ctx, src()):
            break
        return (time.perf_counter() - t0) * 1000

    for _ in range(WARMUP):
        await one()
    samples = [await one() for _ in range(SAMPLES)]
    print(f"\nSC-010 hooks del plugin: p50={statistics.median(samples):.3f} ms p95={p95(samples):.3f} ms")
    assert p95(samples) <= BUDGET_P95_MS / 2
