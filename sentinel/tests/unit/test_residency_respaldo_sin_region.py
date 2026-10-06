"""T094 (057 QA B2, FR-031; research R28): respaldo en código sin fila de región.

Sin fila que resuelva la región, el pedido redirigido sale forzado y fail-closed en todo destino con el alcance
limitado a `region_codes(región)`; sin región resuelta, 403 a todo lo redirigido (nunca cae a `eu`). Ninguna fila,
de ningún rol, ni una relajación por destino lo relaja. La ruta `/health` y los tres sitios que resolvían `eu`
(plugin, `list_postures`, `run_fidelity`) están en `contract/test_redirect_health_y_region.py`."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from residency_fixtures import dest, posture, region_row, relaxation, row, verdict  # noqa: E402

from sentinel.redirect import residency  # noqa: E402

LATAM = dest("AR", "AR", "AR")
FUERA = dest("DE", "DE", "DE")


# ── región conocida pero sin fila ──────────────────────────────────────────────────────────────────

def test_sin_fila_el_destino_dentro_del_alcance_sale_enmascarado():
    d = verdict((), LATAM, region="latam_ar", regions=[])
    assert d.allowed and d.forced_masking


def test_sin_fila_un_destino_fuera_del_alcance_es_403():
    d = verdict((), FUERA, region="latam_ar", regions=[])
    assert not d.allowed and d.reason == "residency"


def test_el_respaldo_es_offregion_masked_con_casa_vacia_y_alcance_acotado():
    p = posture(region="latam_ar", regions=[])
    assert p.mode == "offregion_masked" and p.home == frozenset()
    assert p.code_fallback and p.default_applied == "code_fallback"
    assert p.cap == frozenset({"LATAM", "AR"})


def test_region_eu_resuelta_sin_fila_es_row_missing_con_alcance_eu_no_region_unresolved():
    p = posture(region="eu", regions=[region_row()])        # el seed de Eleia es AMERICAS: no hay fila para eu
    assert p.code_fallback and p.region_status == "region_row_missing"
    assert p.cap == frozenset({"EU"})
    assert verdict((), dest("DE", "DE", "DE"), region="eu", regions=[region_row()]).allowed
    assert not verdict((), dest("US", "US", "US"), region="eu", regions=[region_row()]).allowed


def test_el_no_redirigido_sigue_off_como_hoy():
    p = posture(region="latam_ar", regions=[], redirected=False)
    assert p.mode == "off" and not p.code_fallback and p.default_applied is None
    d = verdict((), FUERA, region="latam_ar", regions=[], redirected=False)
    assert d.allowed and not d.forced_masking


def test_destino_sin_jurisdiccion_de_inferencia_es_403_tambien_en_el_respaldo():
    assert not verdict((), dest(None, "AR", "AR"), region="latam_ar", regions=[]).allowed


# ── región sin resolver ────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("region", [None, "", "  "])
def test_sin_region_todo_lo_redirigido_es_403(region):
    p = posture(region=region, regions=[region_row()])
    assert p.blocked and p.region_status == "region_unresolved" and p.default_applied == "code_fallback"
    for d in (LATAM, FUERA, dest("US", "US", "US")):
        r = residency.evaluate(p, d)
        assert not r.allowed and r.reason == "residency"


def test_sin_region_el_no_redirigido_sigue_pasando():
    assert verdict((), FUERA, region=None, regions=[], redirected=False).allowed


# ── una sola función para los tres sitios (QA v2 N5) ───────────────────────────────────────────────

def test_resolve_profile_no_cae_a_eu(monkeypatch):
    monkeypatch.delenv("SENTINEL_ENTITY_REGION", raising=False)
    assert residency.resolve_profile() is None
    assert residency.resolve_profile(None) is None
    monkeypatch.setenv("SENTINEL_ENTITY_REGION", "  LATAM_AR ")
    assert residency.resolve_profile() == "latam_ar"
    assert residency.resolve_profile("us") == "us"          # la región de la identidad gana sobre la instalación
    monkeypatch.setenv("SENTINEL_ENTITY_REGION", "")
    assert residency.resolve_profile() is None


# ── ninguna fila lo relaja ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rol", ["tenant_admin", "compliance_officer", "super_admin"])
@pytest.mark.parametrize("fila", [row("off"), row("offregion_masked"), row("allowlist", ["AR"])])
def test_ninguna_fila_quita_el_forzado_mientras_rige_el_respaldo(rol, fila):
    fila = {**fila, "created_by_role": rol}
    d = verdict([fila], LATAM, region="latam_ar", regions=[])
    assert d.forced_masking


@pytest.mark.parametrize("rol", ["tenant_admin", "compliance_officer", "super_admin"])
def test_ninguna_fila_amplia_el_alcance_del_respaldo(rol):
    for fila in (row("off", role=rol), row("allowlist", ["US", "DE", "LATAM"], role=rol)):
        d = verdict([fila], FUERA, region="latam_ar", regions=[])
        assert not d.allowed, f"{fila['mode']} de {rol} amplió el alcance"


def test_una_relajacion_por_destino_valida_tampoco_quita_el_forzado_bajo_el_respaldo():
    d = verdict((), dest("AR", "AR", "AR", id="d1"), region="latam_ar", regions=[],
                relaxations=[relaxation("d1")])
    assert d.allowed and d.forced_masking and d.masking_relaxation is None


def test_con_la_fila_de_region_el_respaldo_deja_de_regir():
    p = posture(region="latam_ar", regions=[region_row("masked_all")])
    assert not p.code_fallback and p.region_status == "ok" and p.default_applied == "masked_all"
