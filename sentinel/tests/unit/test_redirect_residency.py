"""Postura de residencia (data-model §0/§1b; FR-001a, 013, 014, 015, 018, 019a)."""
import pytest

from sentinel.redirect.residency import (
    Posture,
    effective_posture,
    evaluate,
    intersect,
    region_codes,
    satisfies,
)
from sentinel.redirect.scopes import RequestScope

SCOPE = RequestScope(tenant_id="t1", connection_id="k1", user_id="u1", group_ids=("g1",))


def row(scope_type, scope_value, mode, jurisdictions=(), accept=False, tenant_id="t1"):
    return {"tenant_id": tenant_id, "scope_type": scope_type, "scope_value": scope_value,
            "mode": mode, "jurisdictions": list(jurisdictions), "accept_foreign_entity": accept}


def dest(inf="EU", ent="EU"):
    return {"id": "d1", "inference_jurisdiction": inf, "entity_jurisdiction": ent}


# --- región → códigos -------------------------------------------------------

@pytest.mark.parametrize("region,codes", [
    ("eu", {"EU"}), ("EU", {"EU"}), ("us", {"US"}), ("latam", {"LATAM"}),
    ("latam_ar", {"LATAM", "AR"}), ("latam_mx", {"LATAM", "MX"}),
    (None, set()), ("", set()), ("marte", set()),
])
def test_region_codes(region, codes):
    assert region_codes(region) == frozenset(codes)


# --- satisfacción e intersección ---------------------------------------------

def test_satisfies_hierarchy():
    assert satisfies("EU", {"EU"})
    assert satisfies("DE", {"EU"})          # país miembro dentro de la zona
    assert not satisfies("EU", {"DE"})      # la zona no garantiza el país
    assert satisfies("AR", {"LATAM"})
    assert not satisfies("US", {"EU"})
    assert not satisfies(None, {"EU"})      # FR-019a
    assert not satisfies("", {"EU"})
    assert satisfies("eu", {"EU"})          # normaliza mayúsculas


def test_intersect_keeps_most_specific():
    assert intersect({"EU"}, {"DE"}) == frozenset({"DE"})
    assert intersect({"EU", "US"}, {"US"}) == frozenset({"US"})
    assert intersect({"EU"}, {"US"}) == frozenset()
    assert intersect({"LATAM", "AR"}, {"LATAM"}) == frozenset({"LATAM", "AR"})


# --- postura efectiva ---------------------------------------------------------

def test_default_off_for_non_redirected():
    p = effective_posture([], SCOPE, redirected=False, tenant_region="eu")
    assert p.mode == "off"


def test_default_allowlist_region_for_redirected():
    p = effective_posture([], SCOPE, redirected=True, tenant_region="latam_ar")
    assert p.mode == "allowlist"
    assert p.jurisdictions == frozenset({"LATAM", "AR"})
    assert p.explicit is False


def test_default_redirected_without_region_is_fail_closed():
    p = effective_posture([], SCOPE, redirected=True, tenant_region=None)
    assert p.mode == "allowlist" and p.jurisdictions == frozenset()
    assert not evaluate(p, dest("EU", "EU")).allowed


def test_explicit_off_replaces_default():
    p = effective_posture([row("tenant", "*", "off")], SCOPE, redirected=True, tenant_region="eu")
    assert p.mode == "off"


def test_most_restrictive_wins_regardless_of_specificity():
    rows = [row("connection", "k1", "off"), row("tenant", "*", "allowlist", ["EU"])]
    p = effective_posture(rows, SCOPE, redirected=True, tenant_region="us")
    assert p.mode == "allowlist" and p.jurisdictions == frozenset({"EU"})


def test_offregion_masked_beats_off():
    rows = [row("user", "u1", "off"), row("group", "g1", "offregion_masked")]
    assert effective_posture(rows, SCOPE, redirected=True, tenant_region="eu").mode == "offregion_masked"


def test_allowlists_intersect():
    rows = [row("tenant", "*", "allowlist", ["EU", "US"]), row("group", "g1", "allowlist", ["EU"])]
    p = effective_posture(rows, SCOPE, redirected=True, tenant_region="eu")
    assert p.jurisdictions == frozenset({"EU"})


def test_rows_of_other_scopes_ignored():
    rows = [row("user", "otro", "allowlist", ["US"]), row("tenant", "*", "allowlist", ["EU"], tenant_id="t2")]
    p = effective_posture(rows, SCOPE, redirected=False, tenant_region="eu")
    assert p.mode == "off"


def test_accept_foreign_entity_requires_all_allowlist_rows():
    rows = [row("tenant", "*", "allowlist", ["EU"], accept=True), row("group", "g1", "allowlist", ["EU"])]
    p = effective_posture(rows, SCOPE, redirected=True, tenant_region="eu")
    assert p.accept_foreign_entity is False
    p2 = effective_posture(rows[:1], SCOPE, redirected=True, tenant_region="eu")
    assert p2.accept_foreign_entity is True


# --- evaluación sobre un destino ----------------------------------------------

def test_off_allows_everything_without_masking():
    d = evaluate(Posture(mode="off"), dest("US", "US"))
    assert d.allowed and not d.forced_masking


def test_allowlist_in_region():
    d = evaluate(Posture(mode="allowlist", jurisdictions=frozenset({"EU"})), dest("DE", "EU"))
    assert d.allowed and not d.forced_masking and d.jurisdiction_served == "DE"


def test_allowlist_out_of_region():
    d = evaluate(Posture(mode="allowlist", jurisdictions=frozenset({"EU"})), dest("US", "US"))
    assert not d.allowed and d.reason == "residency"


def test_allowlist_without_inference_jurisdiction_is_outside():
    d = evaluate(Posture(mode="allowlist", jurisdictions=frozenset({"EU"})), dest(None, "EU"))
    assert not d.allowed and d.reason == "residency"


def test_foreign_entity_requires_acceptance():
    p = Posture(mode="allowlist", jurisdictions=frozenset({"EU"}))
    d = evaluate(p, dest("EU", "US"))
    assert not d.allowed and d.reason == "foreign_entity"
    p2 = Posture(mode="allowlist", jurisdictions=frozenset({"EU"}), accept_foreign_entity=True)
    assert evaluate(p2, dest("EU", "US")).allowed


def test_unknown_entity_treated_as_foreign():
    p = Posture(mode="allowlist", jurisdictions=frozenset({"EU"}))
    assert evaluate(p, dest("EU", None)).reason == "foreign_entity"


def test_offregion_masked_forces_masking_only_outside_home():
    p = Posture(mode="offregion_masked", home=frozenset({"EU"}))
    inside = evaluate(p, dest("EU", "EU"))
    assert inside.allowed and not inside.forced_masking
    outside = evaluate(p, dest("US", "US"))
    assert outside.allowed and outside.forced_masking
    unknown = evaluate(p, dest(None, None))
    assert unknown.allowed and unknown.forced_masking
    foreign_entity = evaluate(p, dest("EU", "US"))
    assert foreign_entity.allowed and foreign_entity.forced_masking


def test_effective_offregion_home_from_rows_or_region():
    rows = [row("tenant", "*", "offregion_masked", ["US"])]
    p = effective_posture(rows, SCOPE, redirected=True, tenant_region="eu")
    assert p.home == frozenset({"US"})
    p2 = effective_posture([row("tenant", "*", "offregion_masked")], SCOPE, redirected=True, tenant_region="eu")
    assert p2.home == frozenset({"EU"})
