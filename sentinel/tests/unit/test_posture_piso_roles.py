"""T098 (057 QA A8, FR-023, FR-028; research R30; data-model §1): las filas del admin de empresa no bajan el piso.

Una fila de `tenant_admin` menos estricta que la efectiva se rechaza (`posture_less_strict`) y, si existiera, no
amplía el alcance ni quita el forzado; una igual o más estricta se acepta. Una `allowlist` del admin no quita el
forzado que impone una fila de cumplimiento. El 422 de la API, en `contract/test_redirect_posture_floor_api.py`."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from residency_fixtures import SCOPE, dest, posture, region_row, relaxation, row, verdict  # noqa: E402

from sentinel.redirect import residency  # noqa: E402

AMERICA = dest("US", "US", "US")
UE = dest("DE", "DE", "DE")


def admin(mode, jurisdictions=()):
    return row(mode, jurisdictions, role="tenant_admin")


def less_strict(candidate, default, rows=(), scope=SCOPE):
    p = posture(rows, regions=[region_row(default)], scope=scope)
    return residency.is_less_strict(candidate, p, region_codes=posture(regions=[region_row(default)]).region_codes)


# ── lo que el admin no puede aflojar, en cada valor de default_posture ─────────────────────────────

@pytest.mark.parametrize("modo,jur", [("off", []), ("offregion_masked", []), ("offregion_masked", ["US"])])
def test_con_reject_offregion_una_fila_del_admin_menos_estricta_se_rechaza(modo, jur):
    assert less_strict(admin(modo, jur), "reject_offregion")


def test_con_reject_offregion_una_off_del_admin_si_existiera_no_abre_un_destino_fuera():
    d = verdict([admin("off")], UE, regions=[region_row("reject_offregion")])
    assert not d.allowed
    assert not verdict([admin("offregion_masked")], UE, regions=[region_row("reject_offregion")]).allowed


def test_con_masked_all_una_off_o_una_offregion_masked_del_admin_se_rechazan():
    assert less_strict(admin("off"), "masked_all")
    assert less_strict(admin("offregion_masked"), "masked_all")    # su home resuelto (la región) no es ∅ (QA A1)


def test_con_masked_all_una_fila_off_del_admin_no_quita_el_forzado():
    for fila in (admin("off"), admin("offregion_masked"), admin("allowlist", ["US"])):
        assert verdict([fila], AMERICA, regions=[region_row("masked_all")]).forced_masking


def test_con_allow_una_offregion_masked_del_admin_se_acepta_y_fuerza_el_enmascarado():
    assert not less_strict(admin("offregion_masked"), "allow")
    d = verdict([admin("offregion_masked", ["AR"])], AMERICA, regions=[region_row("allow")])
    assert d.allowed and d.forced_masking
    assert not less_strict(admin("allowlist", ["US"]), "allow")
    assert not less_strict(admin("off"), "allow")              # igual de estricta (off = off): se acepta


def test_con_masked_offregion_una_offregion_masked_con_casa_menor_o_igual_se_acepta():
    assert not less_strict(admin("offregion_masked", ["AR"]), "masked_offregion")      # casa ⊆ región: más estricta
    assert less_strict(admin("off"), "masked_offregion")


# ── allowlist del admin ─────────────────────────────────────────────────────────────────────────────

def test_una_allowlist_del_admin_contenida_en_la_efectiva_interseca_y_se_acepta():
    base = [row("allowlist", ["US", "BR"])]
    assert not less_strict(admin("allowlist", ["US"]), "masked_all", rows=base)
    p = posture(base + [admin("allowlist", ["US"])], regions=[region_row("masked_all")])
    assert p.jurisdictions == frozenset({"US"})


def test_una_allowlist_del_admin_que_se_solapa_sin_inclusion_se_rechaza():
    base = [row("allowlist", ["US", "BR"])]
    assert less_strict(admin("allowlist", ["US", "CA"]), "masked_all", rows=base)
    assert less_strict(admin("allowlist", ["DE"]), "masked_all", rows=base)


def test_una_allowlist_del_admin_sobre_una_efectiva_de_otro_modo_mas_laxo_se_acepta():
    # efectiva = offregion_masked (masked_all); allowlist es de modo más estricto (068): se acepta
    assert not less_strict(admin("allowlist", ["US"]), "masked_all")


# ── una allowlist del admin no quita el forzado que impone una fila de cumplimiento (U5) ───────────

def test_allowlist_del_admin_no_quita_el_forzado_de_una_fila_de_cumplimiento():
    rows = [row("offregion_masked", ["AR"]), admin("allowlist", ["US"])]
    d = verdict(rows, AMERICA, regions=[region_row("allow")])
    assert d.allowed and d.forced_masking


def test_allowlist_del_admin_con_reject_offregion_y_sin_relajacion_tampoco_quita_el_forzado_de_cumplimiento():
    rows = [row("offregion_masked", ["AR"]), admin("allowlist", ["US"])]
    d = verdict(rows, AMERICA, regions=[region_row("reject_offregion")])
    assert d.allowed and d.forced_masking


# ── cumplimiento sí puede ampliar el alcance, sin quitar el piso ───────────────────────────────────

def test_cumplimiento_amplia_el_alcance_respecto_del_default_sin_quitar_el_piso():
    d = verdict([row("off")], UE, regions=[region_row("masked_all")])
    assert d.allowed and d.forced_masking
    d = verdict([row("allowlist", ["US", "DE"])], UE, regions=[region_row("reject_offregion")])
    assert d.allowed


def test_cumplimiento_no_se_rechaza_por_menos_estricta():
    # la validación de «menos estricta» es solo de la API para el admin de empresa
    p = posture([row("off")], regions=[region_row("masked_all")])
    assert p.mode == "off" and p.floor == frozenset()


# ── sin jurisdicción de inferencia ⇒ 403 con una fila off (de cualquier rol) y con una relajación ───

@pytest.mark.parametrize("rol", ["tenant_admin", "compliance_officer", "super_admin"])
def test_destino_sin_inferencia_es_403_con_una_fila_off_de_cualquier_rol(rol):
    sin = dest(None, "US", "US", id="d-sin")
    assert not verdict([row("off", role=rol)], sin, regions=[region_row("masked_all")]).allowed


def test_destino_sin_inferencia_es_403_con_una_relajacion_vigente():
    sin = dest("unknown", "US", "US", id="d-sin")
    d = verdict((), sin, regions=[region_row("masked_all")], relaxations=[relaxation("d-sin")])
    assert not d.allowed


# ── filas del admin en otro alcance ────────────────────────────────────────────────────────────────

def test_la_efectiva_de_un_alcance_incluye_las_filas_del_tenant():
    from sentinel.redirect.scopes import RequestScope
    user = RequestScope(tenant_id="t1", user_id="u1")
    base = [row("allowlist", ["US"])]
    assert less_strict(admin("allowlist", ["US", "BR"]), "masked_all", rows=base, scope=user)
