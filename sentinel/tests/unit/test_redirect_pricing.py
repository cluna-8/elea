"""Precio del tráfico redirigido (hallazgo del spike S1 de la 069, research D23).

Sin precio, el motor registra costo 0 para lo servido por comodín y el presupuesto de la llave no
se descuenta. El precio viaja firmado en la autorización y el guard lo fija por pedido; si el
destino no tiene precio propio, se usa el mapa de precios del motor por proveedor y modelo real."""
import pytest

from sentinel.engine import redirect_guard as g
from sentinel.redirect import authz

MODEL = "rdx-chatcompat/deepseek/deepseek-chat-v3-0324"

KEY = "k" * 48
NOW = 1_800_000_000.0


def token(**kw):
    args = dict(request_id="req-1", scope="t1/connection:k1", destination_id="d1", model=MODEL,
                provider="openrouter", credential={"api_key": "sk-destino"}, api_base=None,
                forced_masking=False, decision={"public_id": "pro", "face": "openai_generic"},
                key=KEY, now=NOW)
    args.update(kw)
    return authz.issue(**args)


def request(tok=None, model=MODEL, **extra):
    hdrs = {"content-type": "application/json"}
    if tok is not None:
        hdrs["X-Redirect-Authz"] = tok
    data = {"model": model, "messages": [{"role": "user", "content": "hola"}],
            "proxy_server_request": {"headers": dict(hdrs)}, "metadata": {"headers": dict(hdrs)}}
    data.update(extra)
    return data

COST_MAP = {"openrouter/deepseek/deepseek-chat-v3-0324":
            {"input_cost_per_token": 2.9e-07, "output_cost_per_token": 1.14e-06}}


def apply(data, **kw):
    kw.setdefault("key", KEY)
    kw.setdefault("now", NOW)
    kw.setdefault("environ", {})
    kw.setdefault("cost_map", COST_MAP)
    return g.apply_redirect(data, **kw)


def decision(data):
    return data["metadata"][g.DECISION_KEY]["extensions"]["redirect"]


def test_el_precio_viaja_firmado():
    tok = token(model=MODEL, price={"input_per_mtok": 0.5, "output_per_mtok": 2.0})
    grant = authz.verify(tok, key=KEY, now=NOW)
    assert grant.price == {"input_per_mtok": 0.5, "output_per_mtok": 2.0}
    assert authz.verify(token(model=MODEL), key=KEY, now=NOW).price is None


def test_precio_del_destino_gana():
    data = apply(request(token(model=MODEL, price={"input_per_mtok": 0.5, "output_per_mtok": 2.0}), model=MODEL))
    assert data["input_cost_per_token"] == pytest.approx(0.5e-6)
    assert data["output_cost_per_token"] == pytest.approx(2.0e-6)
    assert decision(data)["pricing"] == "destination"


def test_sin_precio_propio_usa_el_mapa_del_motor():
    data = apply(request(token(model=MODEL), model=MODEL))
    assert data["input_cost_per_token"] == pytest.approx(2.9e-07)
    assert data["output_cost_per_token"] == pytest.approx(1.14e-06)
    assert decision(data)["pricing"] == "engine_map"


def test_sin_precio_conocido_queda_marcado():
    data = apply(request(token(model="rdx-chatcompat/modelo-local", provider="openai_compatible",
                                api_base="http://local/v1"), model="rdx-chatcompat/modelo-local"))
    assert "input_cost_per_token" not in data and "output_cost_per_token" not in data
    assert decision(data)["pricing"] == "none"


@pytest.mark.parametrize("campo", ["input_cost_per_token", "output_cost_per_token",
                                   "input_cost_per_second", "output_cost_per_second"])
def test_el_cliente_no_puede_fijar_el_precio(campo):
    data = apply(request(token(model="rdx-chatcompat/modelo-local", provider="openai_compatible",
                                api_base="http://local/v1"), model="rdx-chatcompat/modelo-local",
                         **{campo: 0.0}))
    assert campo not in data
    data = apply(request(token(model=MODEL), model=MODEL, input_cost_per_token=0.0))
    assert data["input_cost_per_token"] == pytest.approx(2.9e-07)


def test_mapa_del_motor_ausente_no_rompe():
    data = apply(request(token(model=MODEL), model=MODEL), cost_map={})
    assert decision(data)["pricing"] == "none"
