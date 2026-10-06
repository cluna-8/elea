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


def dest(inf="EU", ent="EU", ctrl="__ent__"):
    """`ctrl` (jurisdicción de control, 057 FR-028a) sigue a la entidad salvo que el test la fije."""
    return {"id": "d1", "inference_jurisdiction": inf, "entity_jurisdiction": ent,
            "control_jurisdiction": ent if ctrl == "__ent__" else ctrl}


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


def test_default_allowlist_region_for_redirected_con_reject_offregion():
    """Paridad con la 068: la fila de región con la postura de fábrica `reject_offregion` da la allowlist de la región."""
    region = {"level": "installation", "tenant_id": None, "name": "LATAM-AR", "jurisdictions": ["LATAM", "AR"],
              "region_profiles": ["latam_ar"], "default_posture": "reject_offregion", "is_zone": False}
    p = effective_posture([], SCOPE, redirected=True, tenant_region="latam_ar", regions=[region])
    assert p.mode == "allowlist"
    assert p.jurisdictions == frozenset({"LATAM", "AR"})
    assert p.explicit is False


def test_default_redirected_sin_fila_de_region_rige_el_respaldo_en_codigo():
    """Cambio respecto de la 068 (057 QA B2, R28): sin fila, enmascarado forzado y alcance de la región."""
    p = effective_posture([], SCOPE, redirected=True, tenant_region="latam_ar")
    assert p.code_fallback and p.mode == "offregion_masked" and p.cap == frozenset({"LATAM", "AR"})
    assert p.explicit is False


def test_default_redirected_without_region_is_fail_closed():
    p = effective_posture([], SCOPE, redirected=True, tenant_region=None)
    assert p.blocked
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


# --- T054 (057 FR-024, FR-026, FR-028, FR-028a; US3 esc. 1–2, 11): allowlist, entidad y control --------------

def _mk(mode, **kw):
    return Posture(mode=mode, redirected=True, **kw)


def test_allowlist_sobre_el_destino_y_sobre_sus_fallbacks():
    """Cada destino de una regla se evalúa por separado: el de afuera se salta y el siguiente en región sirve."""
    p = _mk("allowlist", jurisdictions=frozenset({"EU"}))
    assert not evaluate(p, dest("US", "US")).allowed
    assert evaluate(p, dest("DE", "DE")).allowed


def test_sin_jurisdiccion_de_inferencia_queda_fuera_de_toda_allowlist():
    p = _mk("allowlist", jurisdictions=frozenset({"EU", "US"}))
    for faltante in (None, "", "unknown"):
        d = evaluate(p, dest(faltante, "EU"))
        assert not d.allowed and d.reason == "residency"


def test_la_mas_restrictiva_gana_e_interseccion_de_listas():
    rows = [row("tenant", "*", "allowlist", ["EU", "US"]), row("group", "g1", "allowlist", ["US"])]
    p = effective_posture(rows, SCOPE, redirected=True, tenant_region="eu")
    assert p.jurisdictions == frozenset({"US"})
    assert not evaluate(p, dest("DE", "DE")).allowed


def test_entidad_ajena_y_su_aceptacion():
    p = _mk("allowlist", jurisdictions=frozenset({"EU"}))
    assert evaluate(p, dest("EU", "US", "US")).reason == "foreign_entity"
    assert evaluate(_mk("allowlist", jurisdictions=frozenset({"EU"}), accept_foreign_entity=True),
                    dest("EU", "US", "US")).allowed


@pytest.mark.parametrize("control", [None, "", "unknown", "CN"])
def test_control_fuera_de_la_lista_o_sin_cargar_es_entidad_ajena_bajo_allowlist(control):
    p = _mk("allowlist", jurisdictions=frozenset({"EU"}))
    d = evaluate(p, dest("EU", "EU", control))
    assert not d.allowed and d.reason == "foreign_entity"
    assert evaluate(_mk("allowlist", jurisdictions=frozenset({"EU"}), accept_foreign_entity=True),
                    dest("EU", "EU", control)).allowed


@pytest.mark.parametrize("control", [None, "unknown", "CN"])
def test_control_fuera_o_sin_cargar_es_fuera_de_region_bajo_offregion_masked(control):
    p = _mk("offregion_masked", home=frozenset({"EU"}))
    assert evaluate(p, dest("EU", "EU", control)).forced_masking
    assert not evaluate(p, dest("EU", "EU", "DE")).forced_masking        # el control en la zona sí cuenta como dentro


def test_modelo_no_registrado_es_inalcanzable_con_allowlist():
    """Un destino que la instantánea no tiene (`not_found`) nunca es elegible: la allowlist no lo vuelve alcanzable."""
    from sentinel.redirect.resolver import check_target
    p = _mk("allowlist", jurisdictions=frozenset({"EU"}))
    assert check_target(None, [], SCOPE, p)[0] == "not_found"


def test_el_resolver_salta_el_destino_fuera_de_region_y_sirve_el_fallback():
    from sentinel.redirect import resolver
    base = {"level": "tenant", "tenant_id": "t1", "status": "active", "provider": "azure_ai", "real_model": "m",
            "protocol_family": "openai_chat", "has_credential": True, "api_base": "https://x.example.com", "role": "text"}
    fuera = {**base, **dest("US", "US"), "id": "a"}
    dentro = {**base, **dest("DE", "DE"), "id": "b"}
    scope = SCOPE
    pub = {"id": "p1", "tenant_id": "t1", "scope_type": "tenant", "scope_value": "*", "face": "openai_generic",
           "public_id": "x", "family_tier": None}
    rule = {"id": "r1", "tenant_id": "t1", "scope_type": "tenant", "scope_value": "*", "published_model_id": "p1",
            "targets": ["a", "b"]}
    p = _mk("allowlist", jurisdictions=frozenset({"EU"}))
    res = resolver.resolve(scope=scope, face="openai_generic", public_id="x", request_class=None,
                           published_rows=[pub], rules=[rule], destinations={"a": fuera, "b": dentro},
                           offers=[], posture=p)
    assert isinstance(res, resolver.Resolved) and res.destination["id"] == "b"
    assert res.substitution_reason == "residency"
    solo_fuera = resolver.resolve(scope=scope, face="openai_generic", public_id="x", request_class=None,
                                  published_rows=[pub], rules=[{**rule, "targets": ["a"]}],
                                  destinations={"a": fuera}, offers=[], posture=p)
    assert isinstance(solo_fuera, resolver.Unavailable) and solo_fuera.error_class == "residency"
