"""S14 — PDF hostil fuera del bucle de eventos (057 T105; QA v2 N4; research R29 3b; Principio I).

La entrada es del cliente y `pypdf` es síncrono, mientras el guardrail corre en el bucle asíncrono del motor:
la extracción corre en un PROCESO HIJO por PDF (`sentinel_pdf_extract.py`) con `RLIMIT_AS`, `RLIMIT_CPU`,
plazo con kill, semáforo, topes por PDF y por pedido y caché por SHA-256. Cualquier fallo ⇒ no analizable con
su nombre de tipo (contracts/costuras-base.md §S14): tope de expansión, de memoria o de texto ⇒
`pdf_resource_limit`; plazo ⇒ `pdf_timeout`; salida no cero o corrupto ⇒ `pdf_error`; tope por pedido o plazo
total ⇒ `pdf_request_limit`.

Los PDFs se GENERAN en el test (sin binarios versionados). Sin `pypdf` instalado (imagen base del motor) el
mismo archivo verifica la rama «sin `pypdf` ⇒ no analizable» (`kind_esperado`), sin saltear nada.
"""
import asyncio
import os
import sys
import time
import zlib

import pytest

import s14_helpers as h
from s14_helpers import DNI, policy  # noqa: E402

SECRETO = "TEXTO-SECRETO-DEL-PDF-9931"


@pytest.fixture(autouse=True)
def _estado_limpio(monkeypatch):
    for nombre in list(os.environ):
        if nombre.startswith("MASKING_PDF_"):
            monkeypatch.delenv(nombre)
    policy.reset_pdf_state()
    yield
    policy.reset_pdf_state()


@pytest.fixture
def hijos(monkeypatch):
    """Espía el único punto donde se lanza un hijo: procesos, y cuántos viven a la vez."""
    visto = {"lanzados": [], "vivos": 0, "max_vivos": 0}
    original = policy._spawn_pdf_child

    async def _espia(argv):
        proc = await original(argv)
        visto["lanzados"].append(proc)
        visto["vivos"] += 1
        visto["max_vivos"] = max(visto["max_vivos"], visto["vivos"])
        espera = proc.wait

        async def _wait():
            try:
                return await espera()
            finally:
                if proc.returncode is not None and not getattr(proc, "_contado", False):
                    proc._contado = True
                    visto["vivos"] -= 1

        proc.wait = _wait
        return proc

    monkeypatch.setattr(policy, "_spawn_pdf_child", _espia)
    return visto


async def _enmascarar(*pdfs: bytes):
    cuerpo = {"model": "m", "messages": [{"role": "user", "content": [
        {"type": "text", "text": "mirá"}, *[h.bloque_pdf(p) for p in pdfs]]}]}
    tally = policy.MaskingTally()
    cuerpo, _ = await policy.mask_body(
        cuerpo, h.analizador(), policy.PlaceholderMap(), scope="full", fmt="anthropic", tally=tally)
    return cuerpo, tally


def _muertos(procesos):
    for proc in procesos:
        with pytest.raises(ProcessLookupError):
            os.kill(proc.pid, 0)


async def _con_testigo(corrutina):
    """Corre `corrutina` mientras una testigo hace tic cada 10 ms; devuelve (resultado, mayor atraso)."""
    atraso = {"max": 0.0}
    parar = asyncio.Event()

    async def tic():
        previo = time.monotonic()
        while not parar.is_set():
            await asyncio.sleep(0.01)
            ahora = time.monotonic()
            atraso["max"] = max(atraso["max"], ahora - previo - 0.01)
            previo = ahora

    testigo = asyncio.create_task(tic())
    await asyncio.sleep(0.05)
    try:
        resultado = await corrutina
    finally:
        parar.set()
        await testigo
    return resultado, atraso["max"]


# ── valores por defecto del contrato ─────────────────────────────────────────────────

def test_valores_por_defecto_del_contrato():
    cfg = policy.pdf_config()
    assert (cfg.max_pages, cfg.max_bytes) == (200, 20 * 1024 * 1024)
    assert (cfg.max_memory_mb, cfg.timeout_s, cfg.max_concurrency) == (512, 20.0, 2)
    assert (cfg.max_stream_bytes, cfg.max_text_chars) == (25 * 1024 * 1024, 2_000_000)
    assert (cfg.max_per_request, cfg.request_deadline_s, cfg.cache_entries) == (5, 30.0, 32)


def test_variables_invalidas_caen_al_valor_por_defecto(monkeypatch):
    monkeypatch.setenv("MASKING_PDF_TIMEOUT_S", "no-es-un-numero")
    monkeypatch.setenv("MASKING_PDF_MAX_PAGES", "-3")
    cfg = policy.pdf_config()
    assert cfg.timeout_s == 20.0 and cfg.max_pages == 200


# ── (a) bomba de compresión ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_bomba_de_compresion_por_encima_del_tope_de_expansion(monkeypatch, hijos):
    monkeypatch.setenv("MASKING_PDF_MAX_STREAM_BYTES", "1000000")
    pdf = h.pdf_bomba_de_compresion(30_000_000)
    assert len(pdf) < 100_000, "el PDF es chico; lo grande es lo que se expande"
    (cuerpo, tally), atraso = await _con_testigo(_enmascarar(pdf))
    assert tally.unanalyzable == 1 and tally.kinds == [h.kind_esperado("pdf_resource_limit")]
    assert atraso < 0.1, f"el bucle de eventos se atrasó {atraso:.3f}s"
    _muertos(hijos["lanzados"])


# ── (b) páginas densas: dentro de los topes, pero el trabajo vence el plazo ────────────

@pytest.mark.asyncio
async def test_b_paginas_densas_vencen_el_plazo_y_el_hijo_muere(monkeypatch, hijos):
    monkeypatch.setenv("MASKING_PDF_TIMEOUT_S", "1")
    pdf = h.pdf_paginas_densas(paginas=3, operadores=40_000)
    t0 = time.monotonic()
    (cuerpo, tally), atraso = await _con_testigo(_enmascarar(pdf))
    assert tally.kinds == [h.kind_esperado("pdf_timeout")] and tally.unanalyzable == 1
    assert time.monotonic() - t0 < 6, "el plazo corta: no espera a que termine el parser"
    assert atraso < 0.1, f"el bucle de eventos se atrasó {atraso:.3f}s durante la extracción"
    _muertos(hijos["lanzados"])


# ── (c) memoria agotada ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_c_memoria_agotada_es_resource_limit(monkeypatch, hijos):
    monkeypatch.setenv("MASKING_PDF_MAX_MEMORY_MB", "200")
    monkeypatch.setenv("MASKING_PDF_MAX_STREAM_BYTES", "1000000000")   # que no corte antes la expansión
    pdf = h.pdf_bomba_de_compresion(450_000_000)
    (cuerpo, tally), atraso = await _con_testigo(_enmascarar(pdf))
    assert tally.kinds == [h.kind_esperado("pdf_resource_limit")]
    assert atraso < 0.1
    _muertos(hijos["lanzados"])


# ── (d) texto extraído por encima del tope ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_d_texto_por_encima_del_tope_de_caracteres(monkeypatch):
    monkeypatch.setenv("MASKING_PDF_MAX_TEXT_CHARS", "100")
    _, tally = await _enmascarar(h.pdf_con_texto("x" * 500))
    assert tally.kinds == [h.kind_esperado("pdf_resource_limit")]


# ── (e) hijo que termina con salida no cero ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_e_hijo_con_salida_no_cero_es_pdf_error(monkeypatch):
    monkeypatch.setattr(policy, "_pdf_child_argv",
                        lambda cfg, plazo: [sys.executable, "-c", "import sys; sys.exit(7)"])
    _, tally = await _enmascarar(h.pdf_con_texto("hola"))
    assert tally.kinds == [h.kind_esperado("pdf_error")]


# ── (f) tope por pedido y plazo total ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_f_mas_pdf_que_el_tope_por_pedido(monkeypatch):
    monkeypatch.setenv("MASKING_PDF_MAX_PER_REQUEST", "2")
    cuerpo, tally = await _enmascarar(*[h.pdf_con_texto(f"pagina {i}") for i in range(3)])
    if h.HAY_PYPDF:
        assert tally.unanalyzable == 1 and tally.kinds == ["pdf_request_limit"]
        tipos = [b["type"] for b in cuerpo["messages"][0]["content"]]
        assert tipos == ["text", "text", "text", "document"], \
            "los dos primeros se extraen; el tercero queda sin extraer"
    else:
        assert tally.unanalyzable == 3 and tally.kinds == ["pdf_unavailable"]


@pytest.mark.asyncio
async def test_f_plazo_total_del_pedido_incluye_la_espera_del_semaforo(monkeypatch, hijos):
    monkeypatch.setenv("MASKING_PDF_MAX_CONCURRENCY", "1")
    monkeypatch.setenv("MASKING_PDF_REQUEST_DEADLINE_S", "0.5")
    semaforo = policy._pdf_semaphore(policy.pdf_config())
    await semaforo.acquire()        # otro pedido tiene el único lugar
    try:
        t0 = time.monotonic()
        _, tally = await _enmascarar(h.pdf_con_texto("espera"))
    finally:
        semaforo.release()
    assert tally.kinds == [h.kind_esperado("pdf_request_limit")], \
        "esperó el semáforo y se le acabó el plazo total del pedido"
    assert time.monotonic() - t0 < 2
    assert hijos["lanzados"] == [], "el pedido que no consiguió lugar no lanzó hijo"


# ── (g) el mismo PDF reenviado se resuelve desde la caché ─────────────────────────────

@pytest.mark.asyncio
async def test_g_el_pdf_hostil_reenviado_sale_de_la_cache_sin_lanzar_otro_hijo(monkeypatch, hijos):
    monkeypatch.setenv("MASKING_PDF_TIMEOUT_S", "1")
    pdf = h.pdf_paginas_densas(paginas=3, operadores=40_000)
    _, primero = await _enmascarar(pdf)
    lanzados = len(hijos["lanzados"])
    t0 = time.monotonic()
    _, segundo = await _enmascarar(pdf)
    assert primero.kinds == segundo.kinds == [h.kind_esperado("pdf_timeout")]
    assert len(hijos["lanzados"]) == lanzados, "el turno siguiente no relanza el parser"
    assert time.monotonic() - t0 < 0.5, "resuelto desde la caché"


@pytest.mark.asyncio
async def test_g_la_cache_es_acotada_y_por_hash(monkeypatch, hijos):
    monkeypatch.setenv("MASKING_PDF_CACHE_ENTRIES", "2")
    pdfs = [h.pdf_con_texto(f"documento {i}") for i in range(3)]
    for pdf in pdfs:
        await _enmascarar(pdf)
    assert len(policy._PDF_CACHE) <= 2
    antes = len(hijos["lanzados"])
    await _enmascarar(pdfs[2])
    assert len(hijos["lanzados"]) == antes, "el último sigue en la caché"


# ── lo que no puede pasar ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_con_concurrencia_2_un_tercer_pdf_espera(monkeypatch, hijos):
    monkeypatch.setenv("MASKING_PDF_MAX_CONCURRENCY", "2")
    monkeypatch.setattr(policy, "_pdf_child_argv", lambda cfg, plazo: [
        sys.executable, "-c", "import sys,time; sys.stdin.buffer.read(); time.sleep(0.6); print('ok')"])
    resultados = await asyncio.gather(*[
        _enmascarar(h.pdf_con_texto(f"distinto {i}")) for i in range(3)])
    if h.HAY_PYPDF:
        assert hijos["max_vivos"] == 2, "nunca más de MAX_CONCURRENCY hijos a la vez"
        assert len(hijos["lanzados"]) == 3
        assert all(t.unanalyzable == 0 for _, t in resultados)
    _muertos(hijos["lanzados"])


@pytest.mark.asyncio
async def test_el_pedido_siguiente_con_un_pdf_sano_se_extrae_bien(monkeypatch, hijos):
    monkeypatch.setenv("MASKING_PDF_TIMEOUT_S", "1")
    await _enmascarar(h.pdf_paginas_densas(paginas=3, operadores=40_000))
    monkeypatch.setenv("MASKING_PDF_TIMEOUT_S", "20")
    cuerpo, tally = await _enmascarar(h.pdf_con_texto(f"DNI {DNI} sano"))
    if h.HAY_PYPDF:
        assert tally.unanalyzable == 0
        texto = cuerpo["messages"][0]["content"][1]["text"]
        assert "sano" in texto and DNI not in texto


@pytest.mark.asyncio
async def test_ningun_texto_del_pdf_aparece_en_logs_ni_en_el_informe(caplog):
    caplog.set_level("DEBUG")
    cuerpo, tally = await _enmascarar(h.pdf_con_texto(f"{SECRETO} dni {DNI}"), h.pdf_sin_texto())
    assert SECRETO not in caplog.text and DNI not in caplog.text
    informe = repr((tally.unanalyzable, tally.kinds, tally.detected, tally.masked))
    assert SECRETO not in informe and DNI not in informe


@pytest.mark.asyncio
async def test_el_hijo_corre_sin_las_variables_del_motor(monkeypatch):
    """Sin credenciales: el hijo no hereda el entorno del motor (llaves, secretos internos)."""
    monkeypatch.setenv("SENTINEL_INTERNAL_SECRET", "no-debe-llegar-al-hijo")
    capturado = {}
    original = policy._spawn_pdf_child

    async def _espia(argv):
        capturado["argv"] = argv
        return await original(argv)

    monkeypatch.setattr(policy, "_spawn_pdf_child", _espia)
    await _enmascarar(h.pdf_con_texto("hola"))
    if h.HAY_PYPDF:
        assert capturado["argv"][1] == "-I", "modo aislado de Python"
        entorno = policy._pdf_child_env()
        assert "SENTINEL_INTERNAL_SECRET" not in entorno
        assert set(entorno) <= {"PATH", "LD_LIBRARY_PATH", "LANG", "LC_ALL"}, "solo lo mínimo para arrancar"


def test_el_modulo_hijo_existe_y_no_importa_nada_del_motor():
    ruta = policy._pdf_child_path()
    assert ruta.endswith("sentinel_pdf_extract.py") and os.path.isfile(ruta)
    fuente = open(ruta, encoding="utf-8").read()
    import ast
    importados = set()
    for nodo in ast.walk(ast.parse(fuente)):
        if isinstance(nodo, ast.Import):
            importados |= {a.name.split(".")[0] for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom):
            importados.add((nodo.module or "").split(".")[0])
    assert importados <= {"sys", "resource", "io", "pypdf"}, importados
    # RLIMIT_AS y RLIMIT_CPU se fijan ANTES de importar pypdf.
    assert fuente.index("setrlimit(resource.RLIMIT_AS") < fuente.index("        import pypdf")
    assert fuente.index("setrlimit(resource.RLIMIT_CPU") < fuente.index("        import pypdf")
