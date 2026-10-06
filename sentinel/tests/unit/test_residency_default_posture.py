"""T053 (057 FR-027, FR-031; research R23): postura por defecto del tráfico redirigido sin postura explícita.

Los cuatro valores de `default_posture`, el piso de enmascarado que las filas explícitas no quitan, el destino sin
jurisdicción de inferencia siempre rechazado y el tráfico no redirigido en `off`. Las relajaciones, en
`test_residency_relajacion.py`; el respaldo sin fila de región, en `test_residency_respaldo_sin_region.py`."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from residency_fixtures import dest, posture, region_row, row, verdict  # noqa: E402

AMERICA = dest("US", "US", "US")                  # dentro de AMERICAS
BRASIL = dest("BR", "BR", "BR")
UE = dest("DE", "DE", "DE")
CHINA = dest("CN", "CN", "CN")


def v(default, destination, rows=(), **kw):
    return verdict(rows, destination, regions=[region_row(default)], **kw)


# ── reject_offregion: sin forzado dentro, 403 fuera ────────────────────────────────────────────────

def test_reject_offregion_deja_pasar_dentro_sin_forzado():
    d = v("reject_offregion", AMERICA)
    assert d.allowed and not d.forced_masking


@pytest.mark.parametrize("fuera", [UE, CHINA])
def test_reject_offregion_rechaza_fuera_de_region(fuera):
    d = v("reject_offregion", fuera)
    assert not d.allowed and d.reason == "residency"


# ── masked_offregion: forzado solo fuera de región ─────────────────────────────────────────────────

def test_masked_offregion_fuerza_solo_fuera():
    assert not v("masked_offregion", AMERICA).forced_masking
    for fuera in (UE, CHINA):
        d = v("masked_offregion", fuera)
        assert d.allowed and d.forced_masking


def test_masked_offregion_una_entidad_o_control_ajenos_cuentan_como_fuera():
    assert v("masked_offregion", dest("US", "US", "CN")).forced_masking
    assert v("masked_offregion", dest("US", "CN", "US")).forced_masking
    assert v("masked_offregion", dest("US", "US", None)).forced_masking       # control sin cargar: fuera


# ── masked_all: forzado y fail-closed en todo destino ──────────────────────────────────────────────

@pytest.mark.parametrize("destino", [AMERICA, BRASIL, UE, CHINA], ids=["EEUU", "Brasil", "UE", "China"])
def test_masked_all_fuerza_en_todo_destino_por_igual(destino):
    d = v("masked_all", destino)
    assert d.allowed and d.forced_masking


def test_masked_all_se_implementa_como_offregion_masked_con_casa_vacia():
    p = posture(regions=[region_row("masked_all")])
    assert p.mode == "offregion_masked" and p.home == frozenset()
    assert p.default_applied == "masked_all" and p.explicit is False


# ── allow ──────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("destino", [AMERICA, UE, CHINA])
def test_allow_no_fuerza_ni_rechaza(destino):
    d = v("allow", destino)
    assert d.allowed and not d.forced_masking


# ── con cualquier valor, sin jurisdicción de inferencia ⇒ 403 ──────────────────────────────────────

@pytest.mark.parametrize("default", ["reject_offregion", "masked_offregion", "masked_all", "allow"])
@pytest.mark.parametrize("inf", [None, "", "unknown", "UNKNOWN"])
def test_sin_jurisdiccion_de_inferencia_se_rechaza_con_cualquier_valor(default, inf):
    d = v(default, dest(inf, "US", "US"))
    assert not d.allowed and d.reason == "residency"


# ── el tráfico no redirigido sin postura queda en off ──────────────────────────────────────────────

def test_el_no_redirigido_sin_postura_queda_off():
    p = posture(regions=[region_row("masked_all")], redirected=False)
    assert p.mode == "off" and p.default_applied is None
    d = verdict((), CHINA, regions=[region_row("masked_all")], redirected=False)
    assert d.allowed and not d.forced_masking


# ── filas explícitas: la postura sale de las filas, el forzado queda como piso ─────────────────────

def test_con_filas_explicitas_la_postura_sale_de_las_filas():
    p = posture([row("allowlist", ["US"])], regions=[region_row("masked_all")])
    assert p.mode == "allowlist" and p.jurisdictions == frozenset({"US"})
    assert p.explicit is True and p.default_applied is None


def test_una_allowlist_restringe_el_alcance_y_los_destinos_de_la_lista_siguen_enmascarados():
    rows = [row("allowlist", ["US"])]
    dentro = verdict(rows, AMERICA, regions=[region_row("masked_all")])
    assert dentro.allowed and dentro.forced_masking            # piso de masked_all
    fuera = verdict(rows, BRASIL, regions=[region_row("masked_all")])
    assert not fuera.allowed and fuera.reason == "residency"   # la lista restringe


def test_una_fila_off_de_cumplimiento_amplia_el_alcance_pero_no_quita_el_piso_de_masked_all():
    d = verdict([row("off")], CHINA, regions=[region_row("masked_all")])
    assert d.allowed and d.forced_masking


def test_el_piso_de_masked_offregion_solo_fuerza_fuera_de_la_region():
    rows = [row("off")]
    assert not verdict(rows, AMERICA, regions=[region_row("masked_offregion")]).forced_masking
    assert verdict(rows, CHINA, regions=[region_row("masked_offregion")]).forced_masking


def test_con_reject_offregion_o_allow_una_fila_off_de_cumplimiento_si_reemplaza_al_default():
    assert verdict([row("off")], CHINA, regions=[region_row("reject_offregion")]).allowed
    assert not verdict([row("off")], CHINA, regions=[region_row("allow")]).forced_masking


def test_una_fila_off_de_cumplimiento_no_habilita_un_destino_sin_jurisdiccion_de_inferencia():
    d = verdict([row("off")], dest(None, "US", "US"), regions=[region_row("masked_all")])
    assert not d.allowed


def test_una_fila_offregion_masked_de_cumplimiento_con_casa_propia_fuerza_fuera_de_ella():
    rows = [row("offregion_masked", ["AR"])]
    assert verdict(rows, dest("AR", "AR", "AR"), regions=[region_row("allow")]).forced_masking is False
    assert verdict(rows, AMERICA, regions=[region_row("allow")]).forced_masking is True


def test_offregion_masked_sin_jurisdicciones_resuelve_su_casa_a_la_region():
    rows = [row("offregion_masked")]
    p = posture(rows, regions=[region_row("allow")])
    assert p.home == posture(regions=[region_row("allow")]).region_codes


# ── auditoría ──────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("default", ["reject_offregion", "masked_offregion", "masked_all", "allow"])
def test_default_posture_applied_solo_sin_postura_explicita(default):
    assert posture(regions=[region_row(default)]).default_applied == default
    assert posture([row("off")], regions=[region_row(default)]).default_applied is None


def test_ningun_resultado_nombra_destinos():
    d = v("reject_offregion", dest("CN", "CN", "CN", id="d-secreto"))
    assert "d-secreto" not in repr(d) and "CN" not in repr(d.reason)
