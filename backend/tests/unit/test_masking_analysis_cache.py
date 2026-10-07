"""S17 — caché de análisis por segmento del enmascarado forzado (057 T109; research R34; contracts/costuras-base.md §S17).

Decisión del owner (2026-10-06): el enmascarado forzado sigue con alcance COMPLETO (el cliente reenvía el historial y los
datos viven en los `tool_result`); la latencia se resuelve con una caché del resultado de analizar cada segmento. Lo que
fija este archivo:

· el mismo segmento se analiza UNA vez (entre pedidos y dentro del pedido); el turno N+1 de una conversación solo analiza lo nuevo,
  también el análisis previo por tipo, que bajo forzado corre por segmento y por la misma caché;
· un cambio de configuración (región, nombres o entidades propias, URL del analizador, sal) invalida; otra empresa no comparte;
· la caché guarda SOLO detecciones (inicio, fin, tipo, puntaje): ni texto, ni valor detectado, ni placeholder;
· el resultado es idéntico con y sin caché; una falla del analizador no se cachea; el regex de respaldo de `degrade` no entra;
· LRU acotada por entradas y TTL; apagada o con variables inválidas ⇒ comportamiento de siempre."""
import copy
import json
import re

import pytest

import s14_helpers as h  # noqa: F401  (instala el doble de litellm antes de importar el guardrail)
from s14_helpers import DNI_PUNTOS
from extensions import sentinel_guardian_policy as policy  # noqa: E402
from extensions import sentinel_guardrail  # noqa: E402

gpolicy = sentinel_guardrail.policy          # la copia del módulo de política que usa el guardrail (nombre plano)
DNI_RE = re.compile(r"\b\d{2}\.\d{3}\.\d{3}\b")
ENV = ("MASKING_ANALYSIS_CACHE_ENABLED", "MASKING_ANALYSIS_CACHE_MAX_ENTRIES", "MASKING_ANALYSIS_CACHE_TTL_S",
       "MASKING_ANALYSIS_CACHE_SALT")


class Analizador:
    """Analizador simulado: cuenta llamadas y caracteres (lo que cobra el sidecar real); detecta DNI con puntos."""

    def __init__(self, falla=False):
        self.calls, self.chars, self.textos, self.falla = 0, 0, [], falla

    async def __call__(self, text, *args, **kwargs):
        self.calls += 1
        self.chars += len(text)
        self.textos.append(text)
        if self.falla:
            raise policy.NlpUnavailableError("simulado")
        return [{"start": m.start(), "end": m.end(), "entity_type": "DNI", "score": 0.85} for m in DNI_RE.finditer(text)]


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    for nombre in ENV:
        monkeypatch.delenv(nombre, raising=False)
    for mod in (policy, gpolicy):
        mod.reset_analysis_cache()
    yield
    for mod in (policy, gpolicy):
        mod.reset_analysis_cache()


class _Identidad:
    def __init__(self, **sentinel):
        self.metadata = {"sentinel": {"region": "latam_ar", **sentinel}}


@pytest.fixture(autouse=True)
def _sin_efectos_laterales(monkeypatch):
    async def _nada(*_a, **_k):
        return None

    monkeypatch.setattr(sentinel_guardrail, "_auditar_bloqueo", _nada)
    monkeypatch.setattr(sentinel_guardrail, "_marcar_nlp_degradado", _nada)


@pytest.fixture
def nlp(monkeypatch):
    """El analizador «real» del guardrail (el sidecar) reemplazado por el simulado."""
    simulado = Analizador()
    monkeypatch.setattr(sentinel_guardrail, "_PRESIDIO_URL", "http://nlp.invalid")
    monkeypatch.setattr(gpolicy, "presidio_analyze", simulado)
    return simulado


def _turno(n_nuevos=0, base=6):
    """Conversación de Claude Code: `base` pares asistente/herramienta + `n_nuevos` más; `system` y herramientas grandes."""
    mensajes = [{"role": "user", "content": f"Revisá el cliente con DNI {DNI_PUNTOS} y arreglá el login."}]
    for i in range(base + n_nuevos):
        mensajes.append({"role": "assistant", "content": [
            {"type": "text", "text": f"Leo el archivo {i}."},
            {"type": "tool_use", "id": f"toolu_{i:03d}", "name": "Read", "input": {"file_path": f"/repo/m{i}.py"}}]})
        mensajes.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"toolu_{i:03d}", "content": f"# archivo {i}\n" + "x = 1\n" * 30}]})
    return {"model": "claude-sonnet-4-5", "max_tokens": 64, "system": "Sos un asistente de código. " * 20,
            "messages": mensajes,
            "tools": [{"name": "Read", "description": "Lee un archivo. " * 10,
                       "input_schema": {"type": "object", "properties": {"file_path": {"type": "string",
                                                                                      "description": "Ruta."}}}}]}


async def _hook(data, *, identidad=None, forzado=True):
    home = sentinel_guardrail._metadata_home(data, "anthropic_messages")
    if forzado:
        gpolicy.mark_forced_masking(home)
    salida = await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(
        identidad or _Identidad(), None, data, "anthropic_messages")
    return salida, data["litellm_metadata"]["masking_report"]


# ── 1. una sola vez ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_el_mismo_segmento_se_analiza_una_vez_aunque_se_pida_varias():
    a = Analizador()
    cache = policy.AnalysisCache(max_entries=10, ttl_s=60)
    f = policy.cached_analyze(a, cache=cache, version="v1", scope="t1")
    for _ in range(3):
        assert await f(f"DNI {DNI_PUNTOS}") == [{"start": 4, "end": 14, "entity_type": "DNI", "score": 0.85}]
    assert a.calls == 1
    otro = policy.cached_analyze(a, cache=cache, version="v1", scope="t1")       # otro pedido, misma caché
    await otro(f"DNI {DNI_PUNTOS}")
    assert a.calls == 1


@pytest.mark.asyncio
async def test_el_mismo_segmento_se_analiza_una_vez_entre_pedidos_del_guardrail(nlp):
    await _hook(_turno())
    primera = nlp.calls
    assert primera > 0
    await _hook(_turno())
    assert nlp.calls == primera, "el segundo pedido idéntico no debía llamar al analizador"


@pytest.mark.asyncio
async def test_el_turno_n_mas_1_solo_analiza_lo_nuevo_tambien_el_analisis_previo(nlp):
    await _hook(_turno(0))
    textos_turno1 = set(nlp.textos)
    nlp.calls, nlp.chars, nlp.textos = 0, 0, []
    await _hook(_turno(2))                                   # dos pares nuevos (asistente + resultado)
    assert nlp.calls > 0
    assert not (set(nlp.textos) & textos_turno1), "se volvió a analizar un segmento ya visto"
    assert all("6" in t or "7" in t for t in nlp.textos), nlp.textos     # solo los pares nuevos (6 y 7)
    assert nlp.chars < sum(len(t) for t in textos_turno1) / 2


@pytest.mark.asyncio
async def test_bajo_forzado_no_hay_una_segunda_pasada_por_el_texto_unido(nlp):
    """Antes el análisis previo mandaba un texto unido de hasta 16 000 caracteres además de los segmentos."""
    data = _turno()
    await _hook(data)
    unido = "\n".join(policy._collect_texts(_turno(), "anthropic", skip=sentinel_guardrail._INTERNAL_BODY_KEYS))
    assert len(nlp.textos) == len(set(nlp.textos)), "cada segmento se analiza una sola vez por pedido"
    assert all(len(t) < len(unido) for t in nlp.textos)


# ── 2. invalidación ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_cambio_de_configuracion_invalida():
    a = Analizador()
    cache = policy.AnalysisCache(max_entries=100, ttl_s=60)
    v = lambda **kw: policy.analysis_config_version(**{"region": "latam_ar", "custom_names": [], "custom_entities": [],
                                                       "analyzer_url": "http://a", "salt": "", **kw})
    versiones = [v(), v(region="eu"), v(custom_names=["Acme"]), v(custom_entities=[{"name": "X"}]),
                 v(analyzer_url="http://b"), v(salt="2")]
    assert len(set(versiones)) == len(versiones)
    assert v() == v(), "la versión es determinista"
    assert v(custom_names=["a", "b"]) == v(custom_names=["b", "a"]), "el orden de los nombres no cambia el resultado"
    for ver in versiones:
        await policy.cached_analyze(a, cache=cache, version=ver, scope="t")("texto igual")
    assert a.calls == len(versiones)


@pytest.mark.asyncio
async def test_la_sal_de_la_variable_entra_en_la_version(monkeypatch):
    base = policy.analysis_config_version(region="eu", custom_names=[], custom_entities=[], analyzer_url="u")
    monkeypatch.setenv("MASKING_ANALYSIS_CACHE_SALT", "otra")
    assert policy.analysis_config_version(region="eu", custom_names=[], custom_entities=[], analyzer_url="u") != base


@pytest.mark.asyncio
async def test_el_cambio_de_nombres_propios_de_la_empresa_invalida_en_el_guardrail(nlp):
    await _hook(_turno())
    llamadas = nlp.calls
    await _hook(_turno(), identidad=_Identidad(custom_names=["Acme"]))
    assert nlp.calls == 2 * llamadas, "con otra lista de nombres propios todo se vuelve a analizar"


@pytest.mark.asyncio
async def test_otra_empresa_no_comparte_entradas():
    a = Analizador()
    cache = policy.AnalysisCache(max_entries=10, ttl_s=60)
    await policy.cached_analyze(a, cache=cache, version="v", scope="empresa-1")("mismo texto")
    await policy.cached_analyze(a, cache=cache, version="v", scope="empresa-2")("mismo texto")
    assert a.calls == 2


# ── 3. lo que guarda ───────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_la_cache_no_contiene_texto_ni_valores_ni_placeholders(nlp):
    data = _turno()
    textos = list(policy._collect_texts(copy.deepcopy(data), "anthropic", with_scans=True,
                                        skip=sentinel_guardrail._INTERNAL_BODY_KEYS))
    salida, informe = await _hook(data)
    cache = gpolicy.get_analysis_cache()
    assert len(cache) > 0
    volcado = json.dumps(cache.dump_for_tests(), ensure_ascii=False)
    assert DNI_PUNTOS not in volcado and "30123456" not in volcado
    for t in (t for t in textos if len(t) >= 12):             # los cortos («64», «Read») podrían ser parte de un hash
        assert t not in volcado, "un segmento completo quedó guardado"
    assert "archivo" not in volcado and "Sos un asistente" not in volcado
    for ph in re.findall(r"\[[A-Z_]+_\d+_[0-9a-f]{4}\]", json.dumps(salida)):
        assert ph not in volcado
    assert "DNI_" not in volcado
    for clave, valor in cache.dump_for_tests().items():
        assert re.fullmatch(r"[0-9a-f]{64}", clave)
        assert all(isinstance(d, (list, tuple)) and len(d) == 4 and isinstance(d[0], int) and isinstance(d[1], int)
                   and isinstance(d[2], str) and isinstance(d[3], float) for d in valor)


# ── 4. equivalencia ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_el_resultado_es_identico_con_y_sin_cache():
    sin = Analizador()
    con = Analizador()
    cache = policy.AnalysisCache(max_entries=1000, ttl_s=60)
    cuerpo_a, cuerpo_b = _turno(1), _turno(1)
    t1, t2 = policy.MaskingTally(), policy.MaskingTally()
    r_sin, m_sin = await policy.mask_body(cuerpo_a, sin, policy.PlaceholderMap(nonce="n001"),
                                          scope="full", fmt="anthropic", tally=t1)
    cached = policy.cached_analyze(con, cache=cache, version="v", scope="t")
    r_con, m_con = await policy.mask_body(cuerpo_b, cached, policy.PlaceholderMap(nonce="n001"),
                                          scope="full", fmt="anthropic", tally=t2)
    assert r_con == r_sin and m_con == m_sin
    assert (t1.detected, t1.masked, t1.unanalyzable) == (t2.detected, t2.masked, t2.unanalyzable)
    # y un segundo pedido servido casi todo desde la caché sale igual que el primero
    cuerpo_c = _turno(1)
    r_c, m_c = await policy.mask_body(cuerpo_c, policy.cached_analyze(con, cache=cache, version="v", scope="t"),
                                      policy.PlaceholderMap(nonce="n001"), scope="full", fmt="anthropic",
                                      tally=policy.MaskingTally())
    assert r_c == r_sin and m_c == m_sin


@pytest.mark.asyncio
async def test_el_informe_del_guardrail_es_el_mismo_con_la_cache_apagada(nlp, monkeypatch):
    _, con = await _hook(_turno())
    monkeypatch.setenv("MASKING_ANALYSIS_CACHE_ENABLED", "false")
    gpolicy.reset_analysis_cache()
    _, sin = await _hook(_turno())
    assert con == sin


@pytest.mark.asyncio
async def test_apagada_no_guarda_nada_y_cada_pedido_analiza_todo(nlp, monkeypatch):
    monkeypatch.setenv("MASKING_ANALYSIS_CACHE_ENABLED", "false")
    await _hook(_turno())
    primera = nlp.calls
    await _hook(_turno())
    assert nlp.calls == 2 * primera and len(gpolicy.get_analysis_cache()) == 0


# ── 5. fallas ──────────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_una_falla_del_analizador_no_se_cachea_y_sube_igual():
    a = Analizador(falla=True)
    cache = policy.AnalysisCache(max_entries=10, ttl_s=60)
    f = policy.cached_analyze(a, cache=cache, version="v", scope="t")
    with pytest.raises(policy.NlpUnavailableError):
        await f("algo")
    assert len(cache) == 0
    a.falla = False
    assert await f("algo") == []
    assert a.calls == 2


@pytest.mark.asyncio
async def test_el_regex_de_respaldo_de_degrade_no_entra_en_la_cache(nlp):
    nlp.falla = True
    data = {"model": "claude-sonnet-4-5", "max_tokens": 8, "messages": [{"role": "user", "content": f"DNI {DNI_PUNTOS}"}]}
    salida, informe = await _hook(data, identidad=_Identidad(nlp_fail_mode="degrade"), forzado=False)
    assert informe["degraded"] is True and DNI_PUNTOS not in json.dumps(salida["messages"])
    assert len(gpolicy.get_analysis_cache()) == 0


@pytest.mark.asyncio
async def test_un_segmento_con_demasiadas_detecciones_no_se_cachea():
    class Muchas:
        calls = 0

        async def __call__(self, text):
            self.calls += 1
            return [{"start": i, "end": i + 1, "entity_type": "X", "score": 0.5} for i in range(1001)]

    a = Muchas()
    cache = policy.AnalysisCache(max_entries=10, ttl_s=60)
    await policy.cached_analyze(a, cache=cache, version="v", scope="t")("x" * 2000)
    assert len(cache) == 0


# ── 6. límites: LRU, TTL, variables ────────────────────────────────────────────────────────────

def test_lru_acotada_por_entradas_y_el_acceso_renueva():
    cache = policy.AnalysisCache(max_entries=2, ttl_s=60)
    cache.put("a", [(0, 1, "X", 0.5)])
    cache.put("b", [(0, 1, "X", 0.5)])
    assert cache.get("a") is not None                      # a pasa a ser la más reciente
    cache.put("c", [(0, 1, "X", 0.5)])                     # desaloja b
    assert cache.get("b") is None and cache.get("a") is not None and cache.get("c") is not None
    assert len(cache) == 2


def test_ttl_con_reloj_inyectado():
    ahora = [1000.0]
    cache = policy.AnalysisCache(max_entries=5, ttl_s=10, clock=lambda: ahora[0])
    cache.put("a", [(0, 1, "X", 0.5)])
    ahora[0] += 9
    assert cache.get("a") is not None
    ahora[0] += 2
    assert cache.get("a") is None and len(cache) == 0


def test_la_lectura_devuelve_copias_que_el_llamador_puede_mutar():
    cache = policy.AnalysisCache(max_entries=5, ttl_s=60)
    cache.put("a", [(0, 1, "X", 0.5)])
    uno = cache.get("a")
    uno.append("basura")
    assert cache.get("a") == [(0, 1, "X", 0.5)]


@pytest.mark.parametrize("variable,valor", [("MASKING_ANALYSIS_CACHE_MAX_ENTRIES", "abc"),
                                            ("MASKING_ANALYSIS_CACHE_MAX_ENTRIES", "-3"),
                                            ("MASKING_ANALYSIS_CACHE_TTL_S", "x"),
                                            ("MASKING_ANALYSIS_CACHE_TTL_S", "0"),
                                            ("MASKING_ANALYSIS_CACHE_ENABLED", "quizás")])
def test_valores_invalidos_dan_los_de_por_defecto(monkeypatch, variable, valor):
    monkeypatch.setenv(variable, valor)
    cfg = policy.analysis_cache_config()
    assert (cfg.enabled, cfg.max_entries, cfg.ttl_s) == (True, 20000, 3600.0)


def test_variables_validas(monkeypatch):
    monkeypatch.setenv("MASKING_ANALYSIS_CACHE_MAX_ENTRIES", "50")
    monkeypatch.setenv("MASKING_ANALYSIS_CACHE_TTL_S", "12.5")
    monkeypatch.setenv("MASKING_ANALYSIS_CACHE_ENABLED", "false")
    cfg = policy.analysis_cache_config()
    assert (cfg.enabled, cfg.max_entries, cfg.ttl_s) == (False, 50, 12.5)
