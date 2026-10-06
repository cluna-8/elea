"""Routing por costo v1 (069 US10, FR-056): la estrategia `cheapest` de la regla ordena los destinos elegibles."""
import pytest

from sentinel.redirect.residency import Posture
from sentinel.redirect.resolver import Resolved, estimated_cost, resolve
from sentinel.redirect.scopes import RequestScope

SCOPE = RequestScope(tenant_id="t1", connection_id="k1", user_id="u1", group_ids=())
EU = Posture(mode="allowlist", jurisdictions=frozenset({"EU"}))


def dest(did, price=None, **kw):
    d = {"id": did, "level": "tenant", "tenant_id": "t1", "status": "active", "has_credential": True,
         "inference_jurisdiction": "EU", "entity_jurisdiction": "EU", "provider": "openrouter",
         "real_model": f"model-{did}", "blocked_by_default": False, "enabled_at": None,
         "protocol_family": "openai_chat", "api_base": "https://openrouter.ai/api/v1", "name": did, **kw}
    if price is not None:
        d["price_override"] = {"input_per_mtok": price[0], "output_per_mtok": price[1]}
    return d


def run(targets, dests, strategy=None):
    rule = {"id": "r1", "tenant_id": "t1", "published_model_id": "p1", "family_tier": None,
            "request_class": None, "scope_type": "tenant", "scope_value": "*", "targets": targets}
    if strategy is not None:
        rule["strategy"] = strategy
    pub = {"id": "p1", "tenant_id": "t1", "face": "claude", "public_id": "m", "scope_type": "tenant",
           "scope_value": "*"}
    return resolve(scope=SCOPE, face="claude", public_id="m", request_class=None, published_rows=[pub],
                   rules=[rule], destinations={d["id"]: d for d in dests}, offers=[], posture=EU)


def ids(res):
    return [res.destination["id"]] + [a.destination["id"] for a in res.alternatives]


def test_cheapest_ordena_por_precio_de_entrada_mas_salida():
    r = run(["a", "b", "c"], [dest("a", (3, 15)), dest("b", (0.3, 1.2)), dest("c", (1, 5))], "cheapest")
    assert isinstance(r, Resolved) and ids(r) == ["b", "c", "a"]
    assert r.target_index == 1 and r.strategy == "cheapest"
    assert [a.target_index for a in r.alternatives] == [2, 0]
    assert r.substitution_reason == "cost_ordering"


def test_sin_precio_queda_al_final_con_su_orden_relativo():
    r = run(["a", "b", "c", "d"], [dest("a"), dest("b", (2, 8)), dest("c"), dest("d", (1, 1))], "cheapest")
    assert ids(r) == ["d", "b", "a", "c"]


def test_empate_conserva_el_orden_de_la_regla():
    r = run(["a", "b", "c"], [dest("a", (1, 2)), dest("b", (2, 1)), dest("c", (1, 2))], "cheapest")
    assert ids(r) == ["a", "b", "c"]
    assert r.substitution_reason is None          # el orden por costo no cambió el primero


def test_order_es_identico_al_comportamiento_de_hoy():
    dests = [dest("a", (3, 15)), dest("b", (0.3, 1.2))]
    base = run(["a", "b"], dests)
    for strategy in ("order", None):
        r = run(["a", "b"], dests, strategy)
        assert ids(r) == ["a", "b"] and r.substitution_reason is None and r.strategy == "order"
    assert base.strategy == "order"


def test_destino_no_elegible_no_entra_aunque_sea_el_mas_barato():
    r = run(["a", "b", "c"], [dest("a", (3, 15)), dest("b", (0.1, 0.1), status="inactive"),
                              dest("c", (1, 5), has_credential=False)], "cheapest")
    assert ids(r) == ["a"]


def test_no_pisa_otro_motivo_de_sustitucion():
    r = run(["a", "b", "c"], [dest("a", inference_jurisdiction="US", entity_jurisdiction="US"),
                              dest("b", (3, 15)), dest("c", (1, 1))], "cheapest")
    assert ids(r) == ["c", "b"] and r.substitution_reason == "residency"


def test_precio_invalido_cuenta_como_sin_precio():
    assert estimated_cost({"price_override": {"input_per_mtok": "x", "output_per_mtok": 1}}) is None
    assert estimated_cost({"price_override": {"input_per_mtok": 1}}) is None
    assert estimated_cost({}) is None
    assert estimated_cost({"price_override": {"input_per_mtok": 1, "output_per_mtok": 2.5}}) == 3.5


def test_estrategia_desconocida_se_trata_como_order():
    r = run(["a", "b"], [dest("a", (3, 15)), dest("b", (0.3, 1.2))], "otra")
    assert ids(r) == ["a", "b"] and r.strategy == "order"


def test_la_decision_de_auditoria_lleva_la_estrategia():
    from sentinel.redirect.plugin import _decision
    r = run(["a", "b"], [dest("a", (3, 15)), dest("b", (0.3, 1.2))], "cheapest")
    d = _decision("claude", "m", r, request_class=None, shadow=False)
    assert d["strategy"] == "cheapest" and d["substitution_reason"] == "cost_ordering"
