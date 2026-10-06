"""Comparador de costos (FR-032; T109): costo real vs hipotético con `reference_model`.

Una sola fuente de precios (`price`, en producción `BudgetService.calculate_cost`). Función pura
sobre filas de auditoría; el endpoint solo las carga."""
from decimal import Decimal

from sentinel.redirect import costs

D = Decimal
PRICES = {  # USD por millón (entrada, salida): el «modelo real» barato vs el pedido caro
    "claude-opus-4-5": (D("15"), D("75")),
    "deepseek-v4": (D("0.3"), D("1.2")),
    "ref-neutro": (D("2"), D("8")),
}


def price(model, prompt, completion):
    i, o = PRICES.get(model, (D("1"), D("1")))
    return (D(prompt) * i + D(completion) * o) / D(1_000_000)


PUBLISHED = [
    {"face": "claude", "public_id": "claude-opus-4-5", "reference_model": None},
    {"face": "openai_generic", "public_id": "pro", "reference_model": "ref-neutro"},
    {"face": "openai_generic", "public_id": "sin-ref", "reference_model": None},
]
DESTS = {"d1": {"id": "d1", "name": "GLM UE", "real_model": "deepseek-v4"},
         "d2": {"id": "d2", "name": "Otro", "real_model": "otro"}}


def row(public_id="claude-opus-4-5", face="claude", dest="d1", prompt=1000, completion=500, cost=0.0009,
        key="k1", user="u1", shadow=False, **extra):
    redirect = {"public_id": public_id, "face": face, "destination_id": dest, "shadow": shadow}
    redirect = {k: v for k, v in redirect.items() if v is not None}
    r = {"api_key_id": key, "user_id": user, "user_group_id": None, "prompt_tokens": prompt,
         "completion_tokens": completion, "cost_usd": cost,
         "routing_decision": {"extensions": {"redirect": redirect}}}
    r.update(extra)
    return r


def compare(rows, **kw):
    return costs.compare(rows, published=PUBLISHED, destinations=DESTS, price=price, **kw)


def test_known_face_hypothetical_uses_requested_model():
    out = compare([row()])
    t = out["totals"]
    assert t["cost_real"] == 0.0009
    # 1000·15 + 500·75 = 52 500 / 1e6
    assert t["cost_hypothetical"] == 0.0525
    assert t["savings"] == round(0.0525 - 0.0009, 8)
    assert t["requests"] == 1 and t["without_reference"] == 0


def test_neutral_alias_uses_admin_reference_model():
    out = compare([row(public_id="pro", face="openai_generic")])
    assert out["totals"]["cost_hypothetical"] == round((1000 * 2 + 500 * 8) / 1e6, 8)


def test_neutral_alias_without_reference_is_not_invented():
    out = compare([row(public_id="sin-ref", face="openai_generic")])
    t = out["totals"]
    assert t["cost_hypothetical"] is None and t["savings"] is None
    assert t["without_reference"] == 1 and t["cost_real"] == 0.0009
    assert out["by_destination"][0]["cost_hypothetical"] is None


def test_mixed_rows_compare_only_those_with_reference():
    out = compare([row(), row(public_id="sin-ref", face="openai_generic")])
    t = out["totals"]
    assert t["requests"] == 2 and t["without_reference"] == 1
    assert t["cost_hypothetical"] == 0.0525                 # solo suma lo comparable
    assert t["cost_real_comparable"] == 0.0009              # y el real de ESAS filas, para que el ahorro no mienta
    assert t["savings"] == round(0.0525 - 0.0009, 8)


def test_group_by_destination_and_scope():
    rows = [row(dest="d1", key="k1"), row(dest="d1", key="k2"), row(dest="d2", key="k1")]
    out = compare(rows)
    by_dest = {d["destination_id"]: d for d in out["by_destination"]}
    assert by_dest["d1"]["requests"] == 2 and by_dest["d1"]["destination_name"] == "GLM UE"
    assert by_dest["d2"]["requests"] == 1
    by_scope = {(s["scope_type"], s["scope_value"]): s for s in out["by_scope"]}
    assert by_scope[("connection", "k1")]["requests"] == 2
    assert by_scope[("connection", "k2")]["requests"] == 1


def test_scope_falls_back_to_user_then_tenant():
    rows = [row(key=None, user="u9"), row(key=None, user=None)]
    scopes = {(s["scope_type"], s["scope_value"]) for s in compare(rows)["by_scope"]}
    assert scopes == {("user", "u9"), ("tenant", "*")}


def test_non_redirected_and_shadow_rows_are_ignored():
    plain = {"api_key_id": "k1", "prompt_tokens": 1, "completion_tokens": 1, "cost_usd": 1,
             "routing_decision": {"path": "direct"}}
    none = {"api_key_id": "k1", "prompt_tokens": 1, "completion_tokens": 1, "cost_usd": 1,
            "routing_decision": None}
    shadow = row(shadow=True)
    unavailable = row(dest=None)                             # sin destino real: no se sirvió
    out = compare([plain, none, shadow, unavailable])
    assert out["totals"]["requests"] == 0
    assert out["shadow_requests"] == 1


def test_zero_recorded_cost_falls_back_to_real_model_price_and_is_flagged():
    """Hallazgo del spike de la 069: el motor registra 0 si el destino no tiene precio."""
    out = compare([row(cost=0.0)])
    t = out["totals"]
    assert t["cost_real"] == round((1000 * 0.3 + 500 * 1.2) / 1e6, 8)       # precio del modelo REAL del destino
    assert t["estimated_real"] == 1
    assert compare([row(cost=0.0009)])["totals"]["estimated_real"] == 0


def test_unknown_destination_is_listed_not_dropped():
    out = compare([row(dest="borrado")])
    assert out["by_destination"][0]["destination_name"] is None
    assert out["totals"]["requests"] == 1


def test_scope_filter():
    rows = [row(key="k1", user="u1"), row(key="k2", user="u2")]
    assert compare(rows, scope=("connection", "k2"))["totals"]["requests"] == 1
    assert compare(rows, scope=("user", "u1"))["totals"]["requests"] == 1
    assert compare(rows, scope=("tenant", "*"))["totals"]["requests"] == 2


def test_output_is_json_serializable_floats():
    import json
    json.dumps(compare([row(), row(public_id="sin-ref", face="openai_generic")]))


def test_empty_period():
    out = compare([])
    assert out["totals"]["requests"] == 0 and out["by_destination"] == [] and out["by_scope"] == []
    assert out["totals"]["cost_real"] == 0.0 and out["totals"]["cost_hypothetical"] is None
