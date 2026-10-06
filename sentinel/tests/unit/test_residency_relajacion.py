"""T053 (057 FR-028a, FR-031, FR-031a; research R24): relajaciones del enmascarado forzado.

Por región (cambiar `default_posture` de `masked_all` a `masked_offregion`: quita el forzado solo a los destinos
en región) y por destino (una fila vigente sobre la entrada: ese destino sale sin forzado). Límites: no habilita
un destino sin jurisdicción de inferencia, no saca a un destino de una *solo jurisdicciones permitidas* y una
relajación cuya ficha ya no cumple no tiene efecto. Las precondiciones al crearla (422) y los roles, en
`contract/test_redirect_regions_api.py` y `test_redirect_posture_roles.py`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from residency_fixtures import dest, posture, region_row, relaxation, row, verdict  # noqa: E402

from sentinel.redirect.resolver import check_target  # noqa: E402

EN_REGION = dest("US", "US", "US", id="d-region")
FUERA = dest("DE", "DE", "DE", id="d-fuera")
CONTROL_AJENO = dest("US", "US", "CN", id="d-control")


# ── por región (FR-028a, FR-031a) ──────────────────────────────────────────────────────────────────

def test_relajar_por_region_quita_el_forzado_solo_a_los_destinos_en_region():
    regions = [region_row("masked_offregion")]
    assert not verdict((), EN_REGION, regions=regions).forced_masking
    assert verdict((), FUERA, regions=regions).forced_masking


def test_con_masked_all_el_mismo_destino_en_region_sale_forzado():
    assert verdict((), EN_REGION, regions=[region_row("masked_all")]).forced_masking


def test_una_entrada_con_control_fuera_de_la_region_no_pierde_el_forzado_con_la_relajacion_por_region():
    d = verdict((), CONTROL_AJENO, regions=[region_row("masked_offregion")])
    assert d.allowed and d.forced_masking


def test_la_relajacion_por_region_queda_marcada_en_la_decision_si_el_destino_esta_en_region():
    assert verdict((), EN_REGION, regions=[region_row("masked_offregion")]).masking_relaxation == "region"
    assert verdict((), FUERA, regions=[region_row("masked_offregion")]).masking_relaxation is None
    assert verdict((), EN_REGION, regions=[region_row("masked_all")]).masking_relaxation is None


def test_in_region_se_informa_con_inferencia_entidad_y_control():
    regions = [region_row("masked_all")]
    assert verdict((), EN_REGION, regions=regions).in_region is True
    assert verdict((), CONTROL_AJENO, regions=regions).in_region is False
    assert verdict((), FUERA, regions=regions).in_region is False


# ── por destino (FR-031a) ──────────────────────────────────────────────────────────────────────────

def test_una_relajacion_por_destino_quita_el_forzado_de_ese_destino_y_solo_de_ese():
    kw = dict(regions=[region_row("masked_all")], relaxations=[relaxation("d-region")])
    d = verdict((), EN_REGION, **kw)
    assert d.allowed and not d.forced_masking and d.masking_relaxation == "destination"
    otro = verdict((), dest("US", "US", "US", id="otro"), **kw)
    assert otro.forced_masking


def test_la_relajacion_por_destino_quita_el_forzado_venga_del_piso_o_de_una_fila():
    kw = dict(regions=[region_row("masked_all")], relaxations=[relaxation("d-fuera")])
    assert not verdict([row("offregion_masked", ["AR"])], FUERA, **kw).forced_masking
    assert not verdict((), FUERA, **kw).forced_masking


def test_la_relajacion_por_destino_no_vuelve_alcanzable_un_destino_fuera_de_una_allowlist():
    d = verdict([row("allowlist", ["AR"])], FUERA, regions=[region_row("masked_all")],
                relaxations=[relaxation("d-fuera")])
    assert not d.allowed and d.reason == "residency"


def test_la_relajacion_por_destino_no_habilita_un_destino_sin_jurisdiccion_de_inferencia():
    sin = dest(None, "US", "US", id="d-sin")
    assert not verdict((), sin, regions=[region_row("masked_all")], relaxations=[relaxation("d-sin")]).allowed
    assert not verdict([row("off")], sin, regions=[region_row("masked_all")],
                       relaxations=[relaxation("d-sin")]).allowed


def test_la_relajacion_de_otra_empresa_no_aplica():
    ajena = relaxation("d-region", tenant_id="t2", level="tenant")
    d = verdict((), EN_REGION, regions=[region_row("masked_all")], relaxations=[ajena])
    assert d.forced_masking


def test_la_relajacion_de_la_empresa_aplica_a_su_empresa():
    propia = relaxation("d-region", tenant_id="t1", level="tenant")
    assert not verdict((), EN_REGION, regions=[region_row("masked_all")], relaxations=[propia]).forced_masking


def test_una_relajacion_no_cambia_la_postura_solo_jurisdicciones_permitidas():
    rows = [row("allowlist", ["AR"])]
    kw = dict(regions=[region_row("reject_offregion")], relaxations=[relaxation("d-fuera")])
    assert not verdict(rows, FUERA, **kw).allowed                          # fuera de la lista: sigue fuera
    assert verdict(rows, dest("AR", "AR", "AR", id="d-fuera"), **kw).allowed


def test_la_relajacion_de_un_destino_con_la_ficha_incumplida_no_llega_a_la_instantanea():
    """`store._valid_relaxations` solo incluye las que cumplen las precondiciones (FR-031a): sin entrada en la
    instantánea, el resolver no ve ninguna relajación y el destino sale forzado."""
    d = verdict((), EN_REGION, regions=[region_row("masked_all")], relaxations=[])
    assert d.forced_masking


def test_el_resolver_deja_el_forzado_y_la_relajacion_en_la_decision(monkeypatch):
    from sentinel.redirect.scopes import RequestScope
    scope = RequestScope(tenant_id="t1")
    p = posture(regions=[region_row("masked_all")], relaxations=[relaxation("d-region")], scope=scope)
    destino = {**EN_REGION, "level": "installation", "status": "active", "provider": "azure_ai", "real_model": "m",
               "has_credential": True, "api_base": "https://x.example.com", "role": "text"}
    offers = [{"destination_id": "d-region", "tenant_id": "*", "enabled_at": None}]
    motivo, decision = check_target(destino, offers, scope, p)
    assert motivo is None and decision.forced_masking is False and decision.masking_relaxation == "destination"
