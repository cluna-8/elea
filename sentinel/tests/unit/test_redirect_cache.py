"""Caché de respuestas del motor con la política encendida (T048/T060; FR-034, research D11).

El motor tiene `cache: true` (`litellm/config.yaml`, Redis). Su clave sale del modelo, los mensajes y
los parámetros — NO de la credencial, la base ni el alcance —, así que sin ayuda dos tenants que piden
el mismo `rdx-<familia>/<modelo>` compartirían respuesta, y dos destinos que sirven el mismo nombre de
modelo desde otra jurisdicción también. El guard fija, para todo `rdx-*`, el control de caché del
pedido: un `namespace` que liga alcance + destino (la clave cambia) y, si el pedido llevó mapa de
enmascarado, `no-cache` + `no-store` (la respuesta trae marcadores de OTRO pedido).
"""
import pytest

from sentinel.engine import redirect_guard as g
from sentinel.redirect import authz

KEY = "k" * 48
NOW = 1_800_000_000.0
MODEL = "rdx-chatcompat/qwen"
CLEAN = {"completed": True, "degraded": False, "detected": 0, "masked": 0}
MASKED = {"completed": True, "degraded": False, "detected": 2, "masked": 2}


def token(**kw):
    args = dict(request_id="req-1", scope="t1/connection:k1", destination_id="d1", model=MODEL,
                provider="openrouter", credential={"api_key": "sk-destino"}, api_base=None,
                provider_options={"providers_allowlist": ["acme-us"]},
                forced_masking=False, decision={"public_id": "pro"}, key=KEY, now=NOW)
    args.update(kw)
    return authz.issue(**args)


def request(tok, report=CLEAN, model=MODEL, **extra):
    hdrs = {"X-Redirect-Authz": tok}
    data = {"model": model, "messages": [{"role": "user", "content": "hola"}],
            "proxy_server_request": {"headers": dict(hdrs)},
            "metadata": {"headers": dict(hdrs)}}
    if report is not None:
        data["metadata"]["masking_report"] = report
    data.update(extra)
    return data


def apply(data, **kw):
    return g.apply_redirect(data, key=KEY, now=NOW, environ={}, **kw)


def namespace(**tok_kw):
    return apply(request(token(**tok_kw)))["cache"]["namespace"]


# ── destino + alcance en la clave ─────────────────────────────────────────────

def test_sin_mapa_la_clave_lleva_namespace_y_se_puede_cachear():
    out = apply(request(token()))
    assert out["cache"].keys() == {"namespace"}
    assert out["cache"]["namespace"].startswith("rdx:")
    assert "no-cache" not in out["cache"] and "no-store" not in out["cache"]


def test_mismo_alcance_y_destino_comparten_clave():
    assert namespace() == namespace(request_id="otro-pedido")


def test_otro_destino_otra_clave():
    assert namespace(destination_id="d2") != namespace(destination_id="d1")


def test_otro_alcance_otra_clave():
    assert namespace(scope="t2/connection:k1") != namespace(scope="t1/connection:k1")
    assert namespace(scope="t1/connection:k2") != namespace(scope="t1/connection:k1")
    assert namespace(scope="t1/user:u1") != namespace(scope="t1/tenant:*")


def test_mismo_id_de_destino_con_otra_base_o_proveedor_otra_clave():
    """Un destino editado en sitio (misma fila, otro endpoint/jurisdicción) no hereda respuestas."""
    base = namespace(api_base="https://eu.example/v1")
    assert namespace(api_base="https://us.example/v1") != base
    assert namespace(provider="ollama", api_base="http://o.local") != namespace(provider="openrouter", api_base="http://o.local")   # misma familia, otro proveedor


def test_el_namespace_no_expone_ids_ni_secretos():
    ns = namespace(scope="t1/connection:k1", destination_id="d1", credential={"api_key": "sk-secreto"})
    assert "t1" not in ns and "k1" not in ns and "d1" not in ns and "sk-secreto" not in ns


def test_no_hay_ambiguedad_por_separadores():
    """('a:b','c') y ('a','b:c') no pueden dar la misma clave."""
    assert namespace(scope="a:b", destination_id="c") != namespace(scope="a", destination_id="b:c")


# ── bypass con mapa de enmascarado ────────────────────────────────────────────

@pytest.mark.parametrize("report", [
    MASKED,                                                       # hay mapa: marcadores de este pedido
    {**MASKED, "masked": 1, "detected": 1},
    {"completed": True, "degraded": True, "detected": 0, "masked": 0},      # degradado a regex
    {"completed": False, "degraded": False, "detected": 0, "masked": 0},    # el paso no terminó
    {"completed": True, "degraded": False, "detected": 3, "masked": 0},     # detectó y no enmascaró
    {"completed": True},                                           # incompleto
    {"completed": True, "degraded": False, "detected": "x", "masked": "y"},
    "sí",
    None,                                                          # sin informe ⇒ no se sabe ⇒ no se cachea
])
def test_con_mapa_o_sin_garantia_se_salta_la_cache(report):
    out = apply(request(token(), report=report))
    assert out["cache"] == {"no-cache": True, "no-store": True}


def test_el_bypass_no_deja_namespace_que_un_hit_pudiera_usar():
    out = apply(request(token(), report=MASKED))
    assert "namespace" not in out["cache"]


def test_informe_sembrado_por_el_cliente_en_el_otro_campo_no_habilita_la_cache():
    """anthropic_messages: el informe vale solo en `litellm_metadata` (lo escribe la base)."""
    data = request(token(), report=None)
    data["metadata"]["masking_report"] = CLEAN          # lo siembra el cliente en un campo del body
    out = apply(data, call_type="anthropic_messages")
    assert out["cache"] == {"no-cache": True, "no-store": True}


def test_informe_de_la_base_en_litellm_metadata_habilita_la_cache():
    data = request(token(), report=None)
    data["litellm_metadata"] = {"masking_report": CLEAN}
    assert apply(data, call_type="anthropic_messages")["cache"]["namespace"].startswith("rdx:")


# ── el cliente no manda sobre la caché ────────────────────────────────────────

@pytest.mark.parametrize("client_cache", [
    {"namespace": "compartido"}, {"no-cache": False, "no-store": False}, {"ttl": 86400},
    {"s-maxage": 10**9}, {"use-cache": True}, "x",
])
def test_lo_que_el_cliente_manda_en_cache_se_descarta(client_cache):
    out = apply(request(token(), cache=client_cache))
    assert out["cache"].keys() == {"namespace"} and out["cache"]["namespace"] != "compartido"
    out = apply(request(token(), report=MASKED, cache=client_cache))
    assert out["cache"] == {"no-cache": True, "no-store": True}


def test_el_cliente_no_puede_fijar_el_namespace_por_metadata():
    out = apply(request(token(), metadata={"redis_namespace": "compartido", "masking_report": CLEAN}))
    assert out["cache"]["namespace"].startswith("rdx:")      # `cache.namespace` gana sobre `redis_namespace`


# ── sin política / sin autorización no cambia nada ────────────────────────────

def test_modelo_no_redirigido_no_se_toca():
    data = {"model": "gpt-4o", "messages": [], "cache": {"ttl": 5}, "proxy_server_request": {"headers": {}}}
    assert apply(data)["cache"] == {"ttl": 5}


def test_sombra_no_cambia_la_cache():
    """Modo sombra: el pedido sale igual que con la política off (incluida la caché del motor)."""
    tok = token(model="modelo-base", decision={"public_id": "pro", "shadow_destination_id": "d9"})
    data = request(tok, model="modelo-base")
    assert "cache" not in apply(data)


def test_rechazo_no_llega_a_la_cache():
    with pytest.raises(g.GuardRejection):
        apply(request("v1.mal.formado"))


# ── con la caché REAL del motor ───────────────────────────────────────────────

def _real_key(data):
    """Clave que arma `litellm.caching.Cache` (misma lógica en 1.92.0 y 1.95.x: modelo + mensajes +
    parámetros, más `cache.namespace`)."""
    litellm_cache = pytest.importorskip("litellm.caching.caching")
    cache = litellm_cache.Cache(type="local")
    kwargs = {"model": data["model"], "messages": data["messages"], "cache": data["cache"],
              "metadata": {"model_group": data["model"]}}
    return cache.get_cache_key(**kwargs)


def test_con_la_cache_real_dos_alcances_no_comparten_clave():
    """Sin el guard, la clave era idéntica (no entra credencial ni alcance): ese era el defecto."""
    pytest.importorskip("litellm.caching.caching")
    a = apply(request(token(scope="t1/connection:k1")))
    b = apply(request(token(scope="t2/connection:k9")))
    assert _real_key(a) != _real_key(b)
    sin_guard = {"model": MODEL, "messages": a["messages"], "cache": {}}
    assert _real_key(sin_guard) == _real_key(dict(sin_guard))     # control: sin el guard, la clave era la misma


def test_con_la_cache_real_dos_destinos_del_mismo_modelo_no_comparten_clave():
    pytest.importorskip("litellm.caching.caching")
    a = apply(request(token(destination_id="d-ue", api_base="https://eu.example/v1")))
    b = apply(request(token(destination_id="d-us", api_base="https://us.example/v1")))
    assert _real_key(a) != _real_key(b)


def test_con_la_cache_real_mismo_alcance_y_destino_si_aciertan():
    pytest.importorskip("litellm.caching.caching")
    a = apply(request(token(request_id="r1")))
    b = apply(request(token(request_id="r2")))
    assert _real_key(a) == _real_key(b)
