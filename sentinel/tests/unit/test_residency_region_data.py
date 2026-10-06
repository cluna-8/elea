"""T052 (057 FR-008, FR-021, FR-030, FR-051; data-model §1): la región del perfil es un dato.

Empresa > instalación > respaldo fijo de `region_codes`; `latam_ar` ⇒ `AMERICAS`; una jurisdicción `US` o `BR`
satisface `AMERICAS`, una de la UE no; `is_zone` permite usar el nombre de la región como código; un país satisface
a su zona y no al revés; las regiones de nivel empresa no aplican desde otra empresa. El registro de cambios con
motivo lo cubre `contract/test_redirect_regions_api.py`."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from residency_fixtures import AMERICAS_JURISDICTIONS, T1, T2, region_row  # noqa: E402

from sentinel.redirect.residency import intersect, region_codes, resolve_region, satisfies  # noqa: E402


def test_la_region_sale_de_la_fila_y_latam_ar_resuelve_a_americas():
    region = resolve_region("latam_ar", [region_row()], T1)
    assert region.name == "AMERICAS" and region.row_found
    assert region.codes == frozenset(AMERICAS_JURISDICTIONS)
    assert region.default_posture == "masked_all"
    assert region.status == "ok"


def test_perfil_en_mayusculas_o_con_espacios_resuelve_igual():
    assert resolve_region("  LATAM_AR ", [region_row()], T1).name == "AMERICAS"


def test_la_fila_de_la_empresa_gana_sobre_la_de_instalacion():
    propia = region_row("masked_offregion", name="MI-REGION", level="tenant", tenant_id=T1, jurisdictions=("AR", "UY"))
    region = resolve_region("latam_ar", [region_row(), propia], T1)
    assert region.name == "MI-REGION" and region.codes == frozenset({"AR", "UY"})
    assert region.default_posture == "masked_offregion"


def test_la_fila_de_otra_empresa_no_se_ve_ni_aplica():
    ajena = region_row("allow", name="OTRA", level="tenant", tenant_id=T2, jurisdictions=("CN",))
    region = resolve_region("latam_ar", [region_row(), ajena], T1)
    assert region.name == "AMERICAS" and "CN" not in region.codes
    solo_ajena = resolve_region("latam_ar", [ajena], T1)
    assert not solo_ajena.row_found                       # sin fila propia ni de instalación: respaldo
    assert solo_ajena.codes == region_codes("latam_ar")


def test_sin_fila_rige_el_respaldo_fijo_y_el_estado_lo_dice():
    region = resolve_region("latam_ar", [], T1)
    assert region.codes == frozenset({"LATAM", "AR"}) and region.default_posture is None
    assert region.status == "region_row_missing"
    assert resolve_region("eu", [region_row()], T1).status == "region_row_missing"     # QA v2 N9: eu sin fila


def test_sin_perfil_la_region_no_se_resuelve_y_nunca_cae_a_eu():
    region = resolve_region(None, [region_row()], T1)
    assert region.profile is None and region.codes == frozenset() and region.status == "region_unresolved"
    assert resolve_region("", [region_row()], T1).status == "region_unresolved"


@pytest.mark.parametrize("code", ["US", "BR", "AR", "CA", "LATAM", "PE"])
def test_jurisdicciones_de_america_satisfacen_la_region(code):
    region = resolve_region("latam_ar", [region_row()], T1)
    assert satisfies(code, region.codes)


@pytest.mark.parametrize("code", ["DE", "EU", "FR", "CN", "RU", "unknown", None, ""])
def test_la_ue_y_lo_desconocido_no_satisfacen_la_region(code):
    region = resolve_region("latam_ar", [region_row()], T1)
    assert not satisfies(code, region.codes)


def test_is_zone_permite_usar_el_nombre_de_la_region_como_codigo():
    region = resolve_region("latam_ar", [region_row()], T1)
    zonas = region.zones_map
    assert satisfies("US", {"AMERICAS"}, zonas) and satisfies("BR", ["AMERICAS"], zonas)
    assert satisfies("AR", {"AMERICAS"}, zonas)            # por el miembro LATAM → AR (zona dentro de la zona)
    assert not satisfies("DE", {"AMERICAS"}, zonas)
    assert not satisfies("US", {"AMERICAS"})               # sin el dato de la zona, el nombre no significa nada


def test_una_region_que_no_es_zona_no_se_puede_usar_como_codigo():
    fila = region_row(is_zone=False)
    region = resolve_region("latam_ar", [fila], T1)
    assert region.zones_map == {}
    assert not satisfies("US", {"AMERICAS"}, region.zones_map)


def test_un_pais_satisface_a_su_zona_y_no_al_reves():
    zonas = resolve_region("latam_ar", [region_row()], T1).zones_map
    assert satisfies("AR", {"AMERICAS"}, zonas)
    assert not satisfies("AMERICAS", {"AR"}, zonas)
    assert not satisfies("AMERICAS", {"US", "BR"}, zonas)
    assert satisfies("DE", {"EU"}) and not satisfies("EU", {"DE"})        # las zonas fijas siguen igual


def test_la_interseccion_respeta_las_zonas_de_datos():
    zonas = resolve_region("latam_ar", [region_row()], T1).zones_map
    assert intersect({"AMERICAS"}, {"BR"}, zonas) == frozenset({"BR"})
    assert intersect({"AMERICAS"}, {"DE"}, zonas) == frozenset()


def test_las_zonas_que_se_refieren_entre_si_no_ciclan():
    a = region_row(name="A", profiles=("x",), jurisdictions=("B", "AR"))
    b = region_row(name="B", profiles=("y",), jurisdictions=("A", "BR"))
    zonas = resolve_region("x", [a, b], T1).zones_map
    assert satisfies("BR", {"A"}, zonas) and not satisfies("US", {"A"}, zonas)
