"""057 T070/T076 (FR-046, FR-049; T127/T128/T133/T134 de Sentinel): precio de lectura y escritura de caché por destino y una
única fuente de precios.

· el precio del destino admite `cache_read_per_mtok` y `cache_write_per_mtok` (opcionales, números ≥ 0);
· `cost_params` los traduce a los parámetros de precio por pedido que el motor honra (`cache_read_input_token_cost`,
  `cache_creation_input_token_cost`) y el costo de un pedido con tokens de caché sale con esos tokens informados;
· sin precio de caché se cobra a precio de entrada completo y la decisión lo marca (`price_cache_missing`);
· la fuente es una sola: la pasarela (precio firmado), el canal por catálogo y el chat de la consola derivan el mismo precio de
  la misma entrada; el cliente no puede fijar ningún costo."""
import pytest

from sentinel.catalog import chat_route
from sentinel.engine import redirect_catalog as catalog_guard
from sentinel.engine import redirect_credentials as rc
from sentinel.engine import redirect_guard as g
from sentinel.redirect import authz

PRECIO = {"input_per_mtok": 1.0, "output_per_mtok": 2.0}
PRECIO_CACHE = {**PRECIO, "cache_read_per_mtok": 0.1, "cache_write_per_mtok": 1.25}
VISTA = {"input": 1e-6, "output": 2e-6, "cache_read": 1e-7, "cache_write": 1.25e-6}


# ── el precio ──────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("precio", [PRECIO, PRECIO_CACHE, {**PRECIO, "cache_read_per_mtok": 0},
                                    {**PRECIO, "cache_write_per_mtok": 3}])
def test_validate_price_admite_los_campos_de_cache_opcionales(precio):
    rc.validate_price(precio)


@pytest.mark.parametrize("precio", [{**PRECIO, "cache_read_per_mtok": -1}, {**PRECIO, "cache_write_per_mtok": "x"},
                                    {**PRECIO, "cache_read_per_mtok": True}, {**PRECIO, "otro": 1},
                                    {"cache_read_per_mtok": 1.0}, {"input_per_mtok": 1.0}])
def test_validate_price_rechaza_lo_demas(precio):
    with pytest.raises(ValueError):
        rc.validate_price(precio)


def test_cost_params_con_precio_de_cache():
    params, fuente = rc.cost_params(PRECIO_CACHE, "openrouter", "glm", {})
    assert fuente == "destination"
    assert params == pytest.approx({"input_cost_per_token": 1e-6, "output_cost_per_token": 2e-6,
                                    "cache_read_input_token_cost": 1e-7, "cache_creation_input_token_cost": 1.25e-6})


def test_cost_params_sin_precio_de_cache_no_inventa_ninguno():
    params, _ = rc.cost_params(PRECIO, "openrouter", "glm", {})
    assert set(params) == {"input_cost_per_token", "output_cost_per_token"}


def test_cost_params_toma_el_precio_de_cache_del_mapa_del_motor():
    mapa = {"openrouter/glm": {"input_cost_per_token": 1e-6, "output_cost_per_token": 2e-6,
                               "cache_read_input_token_cost": 2e-7, "cache_creation_input_token_cost": None}}
    params, fuente = rc.cost_params(None, "openrouter", "glm", mapa)
    assert fuente == "engine_map" and params["cache_read_input_token_cost"] == 2e-7
    assert "cache_creation_input_token_cost" not in params


def test_el_costo_de_un_pedido_con_tokens_de_cache_usa_esos_tokens_y_los_nombres_que_honra_el_motor():
    """Los nombres de parámetro son los que `litellm` reconoce: el mismo costo sale de pasarle a `completion_cost` lo que fija el guard."""
    litellm = pytest.importorskip("litellm")
    from litellm.types.utils import ModelResponse, PromptTokensDetailsWrapper, Usage
    resp = ModelResponse(model="x", usage=Usage(prompt_tokens=1000, completion_tokens=100, total_tokens=1100,
                                                prompt_tokens_details=PromptTokensDetailsWrapper(cached_tokens=800)))
    con, _ = rc.cost_params(PRECIO_CACHE, "openrouter", "glm", {})
    sin, _ = rc.cost_params(PRECIO, "openrouter", "glm", {})
    costo = lambda p: litellm.completion_cost(completion_response=resp, model="glm", custom_llm_provider="openai",  # noqa: E731
                                              custom_cost_per_token=p)
    assert costo(con) == pytest.approx(200 * 1e-6 + 800 * 1e-7 + 100 * 2e-6)
    assert costo(sin) == pytest.approx(1000 * 1e-6 + 100 * 2e-6), "sin precio de caché: todo a precio de entrada"
    assert costo(con) < costo(sin)


# ── el guard ───────────────────────────────────────────────────────────────────────────────────────

KEY = "k" * 48


def _al_guard(price, *, extra=None, provider="openrouter"):
    family = g.credentials.PROVIDER_FAMILY[provider]
    model = family + "/glm"
    tok = authz.issue(request_id="r", scope="t/connection:k", destination_id="d", model=model, provider=provider,
                      credential={"api_key": "sk-d"}, api_base="http://d.local/v1", price=price,
                      provider_options={"providers_allowlist": ["acme-us"]},
                      decision={"public_id": "pro", "face": "openai_generic"}, key=KEY)
    data = {"model": model, "messages": [{"role": "user", "content": "hola"}],
            "proxy_server_request": {"headers": {authz.HEADER: tok}}, "metadata": {}, **(extra or {})}
    out = g.apply_redirect(data, key=KEY, call_type="completion", environ={}, cost_map={})
    return out, out["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]


def test_el_guard_fija_los_costos_de_cache_del_destino_y_no_marca_nada():
    out, rd = _al_guard(PRECIO_CACHE)
    assert out["cache_read_input_token_cost"] == pytest.approx(1e-7)
    assert out["cache_creation_input_token_cost"] == pytest.approx(1.25e-6)
    assert rd["pricing"] == "destination" and "price_cache_missing" not in rd


def test_sin_precio_de_cache_el_guard_lo_marca_en_la_decision():
    out, rd = _al_guard(PRECIO)
    assert "cache_read_input_token_cost" not in out and rd["price_cache_missing"] is True


def test_solo_uno_de_los_dos_precios_de_cache_tambien_se_marca():
    out, rd = _al_guard({**PRECIO, "cache_read_per_mtok": 0.1})
    assert out["cache_read_input_token_cost"] == pytest.approx(1e-7) and rd["price_cache_missing"] is True


def test_sin_ningun_precio_no_hay_nada_que_marcar():
    _, rd = _al_guard(None)
    assert rd["pricing"] == "none" and "price_cache_missing" not in rd


@pytest.mark.parametrize("campo", ["cache_read_input_token_cost", "cache_creation_input_token_cost",
                                   "input_cost_per_token", "output_cost_per_token"])
def test_el_cliente_no_puede_fijar_ningun_costo(campo):
    out, _ = _al_guard(PRECIO, extra={campo: 0.0})
    assert out.get(campo) != 0.0


# ── una única fuente de precios ────────────────────────────────────────────────────────────────────

def test_el_precio_firmado_por_mtok_sale_de_una_sola_funcion():
    assert rc.price_per_mtok(VISTA) == pytest.approx(PRECIO_CACHE)
    assert rc.price_per_mtok({"input": 1e-6, "output": 2e-6, "cache_read": None, "cache_write": None}) == pytest.approx(PRECIO)
    assert rc.price_per_mtok({"input": None, "output": 2e-6}) is None and rc.price_per_mtok(None) is None


def test_el_chat_de_la_consola_y_el_canal_por_catalogo_usan_la_misma_funcion():
    assert chat_route._per_mtok(VISTA) == rc.price_per_mtok(VISTA)
    assert catalog_guard.price_per_mtok is rc.price_per_mtok


def test_el_destino_del_catalogo_lleva_los_precios_de_cache_en_el_precio_de_la_pasarela():
    from types import SimpleNamespace
    from sentinel.catalog import store as cstore
    entry = SimpleNamespace(price_input=1e-6, price_output=2e-6, price_cache_read=1e-7, price_cache_write=1.25e-6)
    assert cstore._price_override(entry) == pytest.approx(PRECIO_CACHE)
    sin = SimpleNamespace(price_input=1e-6, price_output=2e-6, price_cache_read=None, price_cache_write=None)
    assert set(cstore._price_override(sin)) == {"input_per_mtok", "output_per_mtok"}
