"""Resolver puro: precedencia, publicación, reglas y elegibilidad (data-model §0/§4/§5; T029/T041/T043)."""
import pytest

from sentinel.redirect.residency import Posture
from sentinel.redirect.resolver import (
    Resolved,
    Unavailable,
    effective_state,
    find_published,
    published_models,
    resolve,
    select_rule,
)
from sentinel.redirect.scopes import RequestScope

SCOPE = RequestScope(tenant_id="t1", connection_id="k1", user_id="u1", group_ids=("g2", "g1"))
EU = Posture(mode="allowlist", jurisdictions=frozenset({"EU"}))
OFF = Posture(mode="off")


def pol(scope_type, scope_value, state, tenant_id="t1"):
    return {"tenant_id": tenant_id, "scope_type": scope_type, "scope_value": scope_value, "state": state}


# --- estado de política --------------------------------------------------------

def test_state_default_off():
    assert effective_state([], SCOPE) == "off"


def test_state_precedence_connection_user_group_tenant():
    rows = [pol("tenant", "*", "on"), pol("group", "g1", "shadow"), pol("user", "u1", "off"),
            pol("connection", "k1", "on")]
    assert effective_state(rows, SCOPE) == "on"
    assert effective_state(rows[:3], SCOPE) == "off"
    assert effective_state(rows[:2], SCOPE) == "shadow"
    assert effective_state(rows[:1], SCOPE) == "on"


def test_state_ignores_foreign_rows():
    rows = [pol("tenant", "*", "on", tenant_id="t2"), pol("user", "otro", "on"), pol("group", "g9", "on")]
    assert effective_state(rows, SCOPE) == "off"


def test_state_group_tie_is_deterministic():
    rows = [pol("group", "g2", "on"), pol("group", "g1", "shadow")]
    # entre grupos gana el id menor (orden lexicográfico), sin depender del orden de entrada
    assert effective_state(rows, SCOPE) == "shadow"
    assert effective_state(list(reversed(rows)), SCOPE) == "shadow"


def test_invalid_state_rejected():
    with pytest.raises(ValueError):
        effective_state([pol("tenant", "*", "maybe")], SCOPE)


# --- publicación -----------------------------------------------------------------

def pub(pid, public_id, scope_type="tenant", scope_value="*", face="claude", **kw):
    return {"id": pid, "tenant_id": "t1", "face": face, "public_id": public_id,
            "scope_type": scope_type, "scope_value": scope_value, **kw}


def test_publication_union_and_override():
    rows = [pub("p1", "claude-sonnet-4-5", label="tenant"),
            pub("p2", "claude-opus-4-1"),
            pub("p3", "claude-sonnet-4-5", "user", "u1", label="user"),
            pub("p4", "pro", face="openai_generic"),
            pub("p5", "secreto", "user", "otro")]
    got = published_models(rows, SCOPE, face="claude")
    assert [r["public_id"] for r in got] == ["claude-opus-4-1", "claude-sonnet-4-5"]
    assert got[1]["label"] == "user"
    assert find_published(rows, SCOPE, "claude", "claude-sonnet-4-5")["id"] == "p3"
    assert find_published(rows, SCOPE, "claude", "secreto") is None
    assert [r["public_id"] for r in published_models(rows, SCOPE)] == ["claude-opus-4-1", "claude-sonnet-4-5", "pro"]


# --- reglas ----------------------------------------------------------------------

def rule(rid, targets, pm=None, tier=None, rc=None, scope_type="tenant", scope_value="*"):
    return {"id": rid, "tenant_id": "t1", "published_model_id": pm, "family_tier": tier,
            "request_class": rc, "scope_type": scope_type, "scope_value": scope_value, "targets": targets}


def test_rule_class_beats_general_same_scope():
    rules = [rule("r1", ["a"], pm="p1"), rule("r2", ["b"], pm="p1", rc="subagent")]
    assert select_rule(rules, SCOPE, published_model_id="p1", family_tier="sonnet", request_class="subagent")["id"] == "r2"
    assert select_rule(rules, SCOPE, published_model_id="p1", family_tier="sonnet", request_class="main")["id"] == "r1"
    assert select_rule(rules, SCOPE, published_model_id="p1", family_tier="sonnet", request_class=None)["id"] == "r1"


def test_rule_scope_beats_class():
    rules = [rule("r1", ["a"], pm="p1", rc="subagent"), rule("r2", ["b"], pm="p1", scope_type="user", scope_value="u1")]
    assert select_rule(rules, SCOPE, published_model_id="p1", family_tier=None, request_class="subagent")["id"] == "r2"


def test_rule_tier_fallback():
    rules = [rule("r1", ["a"], tier="haiku"), rule("r2", ["b"], tier="sonnet", rc="compaction")]
    assert select_rule(rules, SCOPE, published_model_id="pX", family_tier="haiku", request_class="main")["id"] == "r1"
    assert select_rule(rules, SCOPE, published_model_id="pX", family_tier="sonnet", request_class="compaction")["id"] == "r2"
    assert select_rule(rules, SCOPE, published_model_id="pX", family_tier="sonnet", request_class="main") is None
    assert select_rule(rules, SCOPE, published_model_id="pX", family_tier="opus", request_class=None) is None


def test_rule_for_id_beats_tier_rule_even_less_specific():
    rules = [rule("rt", ["a"], tier="sonnet", scope_type="connection", scope_value="k1"),
             rule("rp", ["b"], pm="p1")]
    assert select_rule(rules, SCOPE, published_model_id="p1", family_tier="sonnet", request_class=None)["id"] == "rp"


# --- resolución completa y elegibilidad ------------------------------------------

def destination(did, *, level="tenant", tenant_id="t1", status="active", has_credential=True,
                inf="EU", ent="EU", provider="openrouter", blocked=False, enabled_at=None,
                protocol_family="openai_chat", api_base="https://openrouter.ai/api/v1", **kw):
    return {"id": did, "level": level, "tenant_id": tenant_id, "status": status,
            "has_credential": has_credential, "inference_jurisdiction": inf, "entity_jurisdiction": ent,
            "provider": provider, "real_model": f"model-{did}", "blocked_by_default": blocked,
            "enabled_at": enabled_at, "protocol_family": protocol_family, "api_base": api_base,
            "name": f"Destino {did}", **kw}


def run(targets, dests, offers=(), posture=EU, face="claude", public_id="claude-sonnet-4-5", rc=None):
    published = [pub("p1", "claude-sonnet-4-5", family_tier="sonnet")]
    rules = [rule("r1", targets, pm="p1")]
    return resolve(scope=SCOPE, face=face, public_id=public_id, request_class=rc,
                   published_rows=published, rules=rules,
                   destinations={d["id"]: d for d in dests}, offers=list(offers), posture=posture)


def test_resolve_first_eligible():
    r = run(["a", "b"], [destination("a"), destination("b")])
    assert isinstance(r, Resolved)
    assert r.destination["id"] == "a" and r.target_index == 0 and r.substitution_reason is None
    assert r.engine_model == "rdx-chatcompat/model-a"
    assert r.rule_id == "r1" and r.fidelity == "translated" and r.forced_masking is False


def test_resolve_native_fidelity():
    r = run(["a"], [destination("a", provider="anthropic", protocol_family="anthropic_messages", api_base=None)])
    assert r.fidelity == "native" and r.engine_model == "rdx-anthropic/model-a"


@pytest.mark.parametrize("bad,reason", [
    (dict(status="inactive"), "inactive"),
    (dict(status="revoked"), "revoked"),
    (dict(has_credential=False), "no_credential"),
    (dict(blocked=True), "blocked_by_default"),
    (dict(tenant_id="t2"), "not_found"),
])
def test_resolve_skips_ineligible(bad, reason):
    r = run(["a", "b"], [destination("a", **bad), destination("b")])
    assert r.destination["id"] == "b" and r.target_index == 1
    assert r.substitution_reason == "fallback_unavailable"
    assert r.skipped == (("a", reason),)


def test_blocked_by_default_enabled_is_usable():
    r = run(["a"], [destination("a", blocked=True, enabled_at="2026-09-25T00:00:00Z")])
    assert isinstance(r, Resolved)


def test_ollama_needs_no_secret_but_needs_base():
    ok = run(["a"], [destination("a", provider="ollama", has_credential=False, api_base="http://h:11434/v1")])
    assert isinstance(ok, Resolved)
    bad = run(["a"], [destination("a", provider="ollama", has_credential=False, api_base=None)])
    assert isinstance(bad, Unavailable) and bad.skipped == (("a", "no_credential"),)


def test_installation_destination_requires_offer():
    d = destination("a", level="installation", tenant_id=None)
    r = run(["a", "b"], [d, destination("b")])
    assert r.destination["id"] == "b" and r.substitution_reason == "offer_withdrawn"
    r2 = run(["a"], [d], offers=[{"destination_id": "a", "tenant_id": "t1"}])
    assert r2.destination["id"] == "a"
    r3 = run(["a"], [d], offers=[{"destination_id": "a", "tenant_id": "*"}])
    assert r3.destination["id"] == "a"
    r4 = run(["a"], [d], offers=[{"destination_id": "a", "tenant_id": "t2"}])
    assert isinstance(r4, Unavailable) and r4.error_class == "unavailable"


def test_offer_can_carry_tenant_enablement_of_blocked():
    d = destination("a", level="installation", tenant_id=None, blocked=True)
    r = run(["a"], [d], offers=[{"destination_id": "a", "tenant_id": "t1", "enabled_at": "x"}])
    assert isinstance(r, Resolved)


def test_residency_fallback_and_reason():
    r = run(["a", "b"], [destination("a", inf="US", ent="US"), destination("b")])
    assert r.destination["id"] == "b" and r.substitution_reason == "residency"
    assert r.jurisdiction_served == "EU" and r.residency_mode == "allowlist"


def test_all_targets_fail_by_residency_is_region_error():
    r = run(["a", "b"], [destination("a", inf="US"), destination("b", inf=None)])
    assert isinstance(r, Unavailable)
    assert r.kind == "no_eligible_target" and r.error_class == "residency"


def test_mixed_failures_are_unavailable():
    r = run(["a", "b"], [destination("a", inf="US"), destination("b", status="inactive")])
    assert r.error_class == "unavailable"


def test_missing_destination_id_in_targets():
    r = run(["ghost"], [])
    assert isinstance(r, Unavailable) and r.skipped == (("ghost", "not_found"),)


def test_not_published_and_no_rule():
    r = run(["a"], [destination("a")], public_id="claude-haiku-9")
    assert isinstance(r, Unavailable) and r.kind == "not_published" and r.error_class == "unavailable"
    r2 = resolve(scope=SCOPE, face="claude", public_id="claude-sonnet-4-5", request_class=None,
                 published_rows=[pub("p1", "claude-sonnet-4-5", family_tier="sonnet")], rules=[],
                 destinations={}, offers=[], posture=EU)
    assert r2.kind == "no_rule"


def test_offregion_masked_sets_forced_masking():
    p = Posture(mode="offregion_masked", home=frozenset({"EU"}))
    r = run(["a"], [destination("a", inf="US", ent="US")], posture=p)
    assert r.forced_masking is True and r.residency_mode == "offregion_masked"


def test_deterministic():
    dests = [destination("a", inf="US"), destination("b"), destination("c")]
    results = {run(["a", "b", "c"], dests).destination["id"] for _ in range(20)}
    assert results == {"b"}
