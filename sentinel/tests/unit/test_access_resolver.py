"""Resolutor puro de modelos permitidos (069 T040; D6/D7; FR-010…FR-014a)."""
import pytest

from sentinel.access.resolver import (RISK_ORDER, AccessSnapshot, PermitidosNoResueltos, Profile, Rule,
                                      effective_risk_level, evaluate_profile, modelos_permitidos)

T = "t-1"


def E(pid, *, estado="eu_ok", provider="anthropic", cap="standard", jur="EU"):
    return {"id": f"id-{pid}", "public_id": pid, "name": pid, "provider": provider, "capability": cap,
            "semaforo": {"estado": estado}, "jurisdiccion": jur}


ENTRIES = [E("a", estado="eu_ok", provider="anthropic", cap="frontier", jur="DE"),
           E("b", estado="standard", provider="openai", cap="standard", jur="US"),
           E("c", estado="unclassified", provider="deepseek", cap="small", jur="unknown"),
           E("d", estado="eu_ok", provider="mistral", cap="small", jur="EU")]
ALL = frozenset("abcd")


def P(pid, kind, *rules):
    return Profile(pid, kind, pid, tuple(Rule(*r) for r in rules))


def snap(profiles=(), assignments=None, ceilings=None, key_profiles=None):
    return AccessSnapshot(T, {p.id: p for p in profiles}, assignments or {}, ceilings or {},
                          key_profiles or {})


def run(s, **kw):
    kw.setdefault("user_risk", "minimal")
    return modelos_permitidos(s, ENTRIES, **kw)


# ── perfil ────────────────────────────────────────────────────────────────────

def test_sin_include_es_vacio():
    assert evaluate_profile(P("x", "company", ("exclude", "proveedor", "openai")), ENTRIES) == frozenset()


def test_include_menos_exclude():
    p = P("x", "company", ("include", "semaforo", "eu_ok"), ("include", "semaforo", "standard"),
          ("exclude", "proveedor", "mistral"))
    assert evaluate_profile(p, ENTRIES) == {"a", "b"}


@pytest.mark.parametrize("sel,val,esperado", [
    ("semaforo", "unclassified", {"c"}), ("proveedor", "openai", {"b"}),
    ("capacidad", "small", {"c", "d"}), ("entrada", "a", {"a"}), ("entrada", "id-b", {"b"}),
    ("jurisdiccion", "EU", {"a", "d"}),            # EU incluye países miembros (DE)
    ("jurisdiccion", "DE", {"a"}),                 # un país no satisface a la zona
    ("jurisdiccion", "US", {"b"}),
])
def test_selectores(sel, val, esperado):
    assert evaluate_profile(P("x", "company", ("include", sel, val)), ENTRIES) == esperado


# ── sin política ──────────────────────────────────────────────────────────────

def test_sin_perfiles_ni_techos_no_restringe():
    r = run(snap())
    assert r.restringe is False and r.ids == ALL


# ── capas de empresa ──────────────────────────────────────────────────────────

CP = [P("eu", "company", ("include", "semaforo", "eu_ok")),
      P("us", "company", ("include", "proveedor", "openai")),
      P("solo_c", "company", ("include", "entrada", "c"))]


def test_organizacion_aplica_si_no_hay_mas_especifico():
    r = run(snap(CP, {("tenant", T): ["eu"]}), user_id="u1", group_id="g1")
    assert r.restringe and r.ids == {"a", "d"}
    assert [p["origen"] for p in r.perfiles] == ["tenant"]


def test_union_de_los_perfiles_de_la_primera_capa_no_vacia():
    r = run(snap(CP, {("tenant", T): ["eu"], ("group", "g1"): ["eu", "us"]}), user_id="u1", group_id="g1")
    assert r.ids == {"a", "b", "d"} and {p["origen"] for p in r.perfiles} == {"group"}


def test_usuario_pisa_a_grupo_y_organizacion_no_se_acumulan():
    s = snap(CP, {("tenant", T): ["eu"], ("group", "g1"): ["us"], ("user", "u1"): ["solo_c"]})
    assert run(s, user_id="u1", group_id="g1").ids == {"c"}
    assert run(s, user_id="u2", group_id="g1").ids == {"b"}        # otro usuario: cae al grupo
    assert run(s, user_id="u2", group_id="g2").ids == {"a", "d"}   # otro grupo: cae a la organización


def test_capa_con_perfil_sin_modelos_es_no_vacia_y_deja_vacio():
    s = snap(CP + [P("nada", "company")], {("tenant", T): ["eu"], ("user", "u1"): ["nada"]})
    r = run(s, user_id="u1")
    assert r.restringe and r.ids == frozenset()


# ── techo ─────────────────────────────────────────────────────────────────────

CE = [P("c_min", "ceiling", ("include", "capacidad", "frontier"), ("include", "capacidad", "standard"),
        ("include", "capacidad", "small")),
      P("c_lim", "ceiling", ("include", "semaforo", "eu_ok"), ("include", "semaforo", "standard")),
      P("c_h3", "ceiling", ("include", "semaforo", "eu_ok")),
      P("c_h1", "ceiling", ("include", "entrada", "d"))]
CEIL = {"minimal": "c_min", "limited": "c_lim", "high_risk_annex3": "c_h3", "high_risk_annex1": "c_h1"}


def test_orden_de_rigor_documentado():
    assert RISK_ORDER == ("minimal", "limited", "high_risk_annex3", "high_risk_annex1")


@pytest.mark.parametrize("risk,esperado", [("minimal", ALL), ("limited", {"a", "b", "d"}),
                                           ("high_risk_annex3", {"a", "d"}), ("high_risk_annex1", {"d"})])
def test_techo_por_nivel(risk, esperado):
    r = run(snap(CE, ceilings=CEIL), user_risk=risk)
    assert r.restringe and r.ids == esperado
    assert r.techo["risk_level"] == risk and r.techo["origen"] == "user" and r.techo["count"] == len(esperado)


def test_nivel_sin_techo_definido_no_restringe():
    r = run(snap(CE, ceilings={"high_risk_annex1": "c_h1"}), user_risk="minimal")
    assert r.restringe is False and r.ids == ALL and r.techo["origen"] == "sin_techo"


@pytest.mark.parametrize("u,k,nivel,origen", [
    ("minimal", "high_risk_annex1", "high_risk_annex1", "key"),     # la llave endurece
    ("high_risk_annex1", "minimal", "high_risk_annex1", "user"),    # la llave NO relaja
    ("limited", "high_risk_annex3", "high_risk_annex3", "key"),
    ("high_risk_annex3", "high_risk_annex1", "high_risk_annex1", "key"),
    ("high_risk_annex1", "high_risk_annex3", "high_risk_annex1", "user"),
    ("limited", None, "limited", "user"), ("limited", "", "limited", "user"),
])
def test_riesgo_efectivo_el_mas_estricto(u, k, nivel, origen):
    assert effective_risk_level(u, k) == (nivel, origen)


def test_la_llave_minimal_no_relaja_a_una_persona_de_alto_riesgo():
    r = run(snap(CE, ceilings=CEIL), user_risk="high_risk_annex1", key_risk="minimal")
    assert r.ids == {"d"}


@pytest.mark.parametrize("u", [None, "", "inventado"])
def test_riesgo_desconocido_es_la_interseccion_de_todos_los_techos(u):
    r = run(snap(CE, ceilings=CEIL), user_risk=u)
    assert r.ids == {"d"} and r.techo["risk_level"] is None and r.techo["origen"] == "desconocido"


def test_llave_con_clasificacion_desconocida_endurece_al_maximo():
    assert run(snap(CE, ceilings=CEIL), user_risk="minimal", key_risk="raro").ids == {"d"}


def test_desconocido_sin_techos_definidos_no_restringe():
    assert run(snap(), user_risk=None).restringe is False


def test_empresa_y_techo_se_intersectan():
    r = run(snap(CP + CE, {("tenant", T): ["eu"]}, CEIL), user_risk="limited")
    assert r.ids == {"a", "d"}


# ── llave ─────────────────────────────────────────────────────────────────────

def test_perfil_de_llave_solo_achica():
    kp = [P("k_b", "key", ("include", "entrada", "b")), P("k_a", "key", ("include", "entrada", "a"))]
    s = snap(CP + kp, {("tenant", T): ["eu"]}, key_profiles={"k1": "k_b", "k2": "k_a"})
    assert run(s, key_id="k1").ids == frozenset()          # b no está en el efectivo del dueño
    assert run(s, key_id="k2").ids == {"a"} and run(s, key_id="k2").llave == {"profile_id": "k_a"}
    assert run(s, key_id="otra").ids == {"a", "d"}


def test_perfil_de_llave_sin_politica_de_empresa_restringe():
    s = snap([P("k_b", "key", ("include", "entrada", "b"))], key_profiles={"k1": "k_b"})
    r = run(s, key_id="k1")
    assert r.restringe and r.ids == {"b"}


# ── fallas ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("s,kw", [
    (snap(assignments={("tenant", T): ["fantasma"]}), {}),
    (snap(CP, assignments={("tenant", T): ["eu"]}, ceilings={"minimal": "eu"}), {}),     # tipo equivocado
    (snap(ceilings={"minimal": "fantasma"}), {}),
    (snap(key_profiles={"k1": "fantasma"}), {"key_id": "k1"}),
])
def test_datos_inconsistentes_levantan_excepcion(s, kw):
    with pytest.raises(PermitidosNoResueltos):
        run(s, **kw)


def test_selector_desconocido_levanta():
    s = snap([P("x", "company", ("include", "magia", "z"))], {("tenant", T): ["x"]})
    with pytest.raises(PermitidosNoResueltos):
        run(s)
