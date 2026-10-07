"""T098 (057 QA A8, FR-023; research R30): la API rechaza con 422 `posture_less_strict` una fila del admin de empresa
menos estricta que la efectiva de su alcance, y acepta una igual o más estricta. La semántica del piso, en
`unit/test_posture_piso_roles.py`."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import redirect_api_fixtures as fx  # noqa: E402

AMERICA = ("US", "AR", "LATAM")


def post(api, mode, jur=(), role="tenant_admin", **kw):
    return api.call("POST", "/postures", role, json={"mode": mode, "jurisdictions": list(jur), "reason": "prueba de piso", **kw})


def make(monkeypatch, default):
    return fx.make_api(monkeypatch, profile="latam_ar", region=default, jurisdictions=AMERICA)


def assert_less_strict(r):
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "posture_less_strict"


@pytest.mark.parametrize("modo,jur", [("off", []), ("offregion_masked", []), ("offregion_masked", ["US"])])
def test_con_reject_offregion_una_fila_menos_estricta_del_admin_es_422(monkeypatch, modo, jur):
    assert_less_strict(post(make(monkeypatch, "reject_offregion"), modo, jur))


def test_con_masked_all_una_off_o_una_offregion_masked_es_422(monkeypatch):
    api = make(monkeypatch, "masked_all")
    assert_less_strict(post(api, "off"))
    assert_less_strict(post(api, "offregion_masked"))                  # su home resuelto (la región) no es ∅
    assert_less_strict(post(api, "offregion_masked", ["AR"]))


def test_con_masked_all_una_allowlist_se_acepta(monkeypatch):
    assert post(make(monkeypatch, "masked_all"), "allowlist", ["US"]).status_code == 201


def test_con_allow_una_offregion_masked_del_admin_se_acepta_y_una_off_tambien(monkeypatch):
    api = make(monkeypatch, "allow")
    assert post(api, "off").status_code == 201                         # igual de estricta que la efectiva (off)
    assert post(api, "offregion_masked", ["AR"]).status_code == 201     # más estricta
    assert_less_strict(post(api, "off"))                               # ahora la efectiva ya es offregion_masked


def test_una_allowlist_que_se_solapa_sin_inclusion_es_422_y_la_contenida_se_acepta(monkeypatch):
    api = make(monkeypatch, "reject_offregion")                        # efectiva: allowlist de la región
    assert post(api, "allowlist", ["US", "DE"]).status_code == 422
    assert post(api, "allowlist", ["US"]).status_code == 201
    assert_less_strict(post(api, "allowlist", ["US", "AR"]))            # la efectiva ya es [US]: ahora se solapa


def test_cumplimiento_si_puede_ampliar_el_alcance(monkeypatch):
    api = make(monkeypatch, "reject_offregion")
    assert post(api, "off", role="compliance_officer").status_code == 201
    assert post(api, "allowlist", ["US", "DE"], role="super_admin").status_code == 201


def test_la_efectiva_de_un_alcance_incluye_las_filas_de_cumplimiento_del_tenant(monkeypatch):
    api = make(monkeypatch, "masked_all")
    assert post(api, "allowlist", ["US"], role="compliance_officer").status_code == 201
    user = "44444444-4444-4444-4444-444444444444"
    r = api.call("POST", "/postures", "tenant_admin",
                 json={"scope_type": "user", "scope_value": user, "mode": "allowlist", "jurisdictions": ["US", "AR"],
                       "reason": "ampliar no se puede"})
    assert_less_strict(r)


def test_sin_region_resuelta_toda_fila_del_admin_es_menos_estricta(monkeypatch):
    api = fx.make_api(monkeypatch, profile=None, region=None)
    assert_less_strict(post(api, "allowlist", ["US"]))


def test_el_operador_declarado_escribe_como_autoridad_de_instalacion_y_no_se_valida(monkeypatch):
    """Paridad con la 068: el operador por entorno escribe filas como autoridad (no es el admin que solo endurece)."""
    api = make(monkeypatch, "masked_all")
    monkeypatch.setenv("REDIRECT_OPERATOR_TENANT", str(fx.T1))
    r = post(api, "off")
    assert r.status_code == 201 and r.json()["created_by_role"] == "super_admin"
