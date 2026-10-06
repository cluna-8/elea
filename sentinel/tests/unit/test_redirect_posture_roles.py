"""T055 (057 FR-023, FR-031a; US3 esc. 7; QA A6; research R30): roles de la postura y de la región.

Cumplimiento y super-admin escriben y relajan; el admin de empresa solo agrega filas que endurecen, no cambia
`default_posture` ni crea relajaciones por destino —**también con `REDIRECT_OPERATOR_TENANT` definida** (rol real)—
y todo cambio lleva motivo. Que el admin de empresa pueda dar de alta un `compliance_officer` o un `super_admin`
(`backend/src/api/users.py:413-414`) es un arreglo aparte en la base, fuera de la 057 (QA v2 N3, R30)."""
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import redirect_api_fixtures as fx  # noqa: E402
from redirect_api_fixtures import T1  # noqa: E402


@pytest.fixture
def api(monkeypatch):
    return fx.make_api(monkeypatch, profile="latam_ar", region="masked_all", jurisdictions=("US", "AR", "LATAM"))


def _region_id(api):
    return api.call("GET", "/regions", "compliance_officer").json()["data"][0]["id"]


# ── filas de postura ────────────────────────────────────────────────────────────────────────────────

def test_cumplimiento_y_super_admin_escriben_cualquier_fila(api):
    for role in ("compliance_officer", "super_admin"):
        r = api.call("POST", "/postures", role, json={"mode": "off", "reason": "relevamiento legal"})
        assert r.status_code == 201, (role, r.text)
        assert r.json()["created_by_role"] == role


def test_el_admin_de_empresa_agrega_una_fila_que_endurece(api):
    r = api.call("POST", "/postures", "tenant_admin",
                 json={"mode": "allowlist", "jurisdictions": ["US"], "reason": "solo EE. UU."})
    assert r.status_code == 201 and r.json()["created_by_role"] == "tenant_admin"


def test_con_masked_all_una_fila_del_admin_incluida_una_allowlist_no_quita_el_forzado(api):
    api.call("POST", "/postures", "tenant_admin",
             json={"mode": "allowlist", "jurisdictions": ["US"], "reason": "solo EE. UU."})
    prev = api.call("POST", "/resolve-preview", "tenant_admin",
                    json={"face": "openai_generic", "public_id": "nada"})
    assert prev.status_code == 200
    eff = api.call("GET", "/postures", "tenant_admin").json()["effective_tenant_redirected"]
    assert eff["mode"] == "allowlist" and eff["forced_everywhere"] is True       # el piso de masked_all sigue


def test_el_admin_no_cambia_ni_borra_filas_ajenas_ni_las_propias(api):
    pid = api.call("POST", "/postures", "tenant_admin",
                   json={"mode": "allowlist", "jurisdictions": ["US"], "reason": "x y z"}).json()["id"]
    assert api.call("PATCH", f"/postures/{pid}", "tenant_admin",
                    json={"mode": "off", "reason": "relajar"}).status_code == 403
    assert api.call("DELETE", f"/postures/{pid}", "tenant_admin", json={"reason": "borrar"}).status_code == 403


def test_el_admin_no_acepta_entidades_ajenas(api):
    r = api.call("POST", "/postures", "tenant_admin",
                 json={"mode": "allowlist", "jurisdictions": ["US"], "accept_foreign_entity": True, "reason": "ok ok"})
    assert r.status_code == 403


def test_el_motivo_es_obligatorio(api):
    for role in ("tenant_admin", "compliance_officer", "super_admin"):
        assert api.call("POST", "/postures", role, json={"mode": "allowlist", "jurisdictions": ["US"]}
                        ).status_code == 422
        assert api.call("POST", "/postures", role, json={"mode": "allowlist", "jurisdictions": ["US"],
                                                          "reason": ""}).status_code == 422


# ── default_posture (relajación por región) ─────────────────────────────────────────────────────────

def test_el_admin_de_empresa_no_cambia_default_posture(api):
    rid = _region_id(api)
    r = api.call("PATCH", f"/regions/{rid}", "tenant_admin",
                 json={"default_posture": "masked_offregion", "reason": "relajar"})
    assert r.status_code == 403
    r = api.call("POST", "/regions", "tenant_admin",
                 json={"name": "PROPIA", "level": "tenant", "jurisdictions": ["AR"], "region_profiles": ["latam_ar"],
                       "default_posture": "allow", "reason": "relajar"})
    assert r.status_code == 403


def test_el_operador_declarado_por_entorno_tampoco_cambia_default_posture(api, monkeypatch):
    """Rol real, no `_is_super` (QA A6): `REDIRECT_OPERATOR_TENANT` no le da al admin de empresa lo de cumplimiento."""
    monkeypatch.setenv("REDIRECT_OPERATOR_TENANT", str(T1))
    rid = _region_id(api)
    assert api.call("PATCH", f"/regions/{rid}", "tenant_admin",
                    json={"default_posture": "masked_offregion", "reason": "relajar"}).status_code == 403
    caps = api.call("GET", "/capabilities", "tenant_admin").json()
    assert caps == {"operator": True, "manages_regions": False}


def test_el_operador_tampoco_crea_relajaciones_por_destino(api, monkeypatch):
    monkeypatch.setenv("REDIRECT_OPERATOR_TENANT", str(T1))
    d = api.seed(level="tenant", inference="US", entity="US", zero_data_retention=True)
    r = api.call("POST", "/masking-relaxations", "tenant_admin",
                 json={"entry_id": d["id"], "level": "tenant", "reason": "alojador con retención cero"})
    assert r.status_code == 403


def test_cumplimiento_cambia_default_posture_de_su_empresa_con_una_fila_propia(api):
    r = api.call("POST", "/regions", "compliance_officer",
                 json={"name": "PROPIA", "level": "tenant", "jurisdictions": ["US", "AR", "LATAM"],
                       "region_profiles": ["latam_ar"], "default_posture": "masked_offregion",
                       "reason": "relajación por región aprobada por cumplimiento"})
    assert r.status_code == 201, r.text
    eff = api.call("GET", "/regions/effective", "tenant_admin").json()
    assert eff["source"] == "tenant" and eff["default_posture"] == "masked_offregion"
    otra = api.call("GET", "/regions/effective", "tenant_admin", tenant=fx.T2).json()
    assert otra["source"] == "installation" and otra["default_posture"] == "masked_all"


def test_super_admin_cambia_la_fila_de_instalacion_y_afecta_a_todas_las_empresas(api):
    rid = _region_id(api)
    r = api.call("PATCH", f"/regions/{rid}", "super_admin",
                 json={"default_posture": "masked_offregion", "reason": "decisión de la instalación"})
    assert r.status_code == 200 and r.json()["default_posture"] == "masked_offregion"
    assert api.call("GET", "/regions/effective", "tenant_admin", tenant=fx.T2).json()["default_posture"] \
        == "masked_offregion"


def test_cumplimiento_no_toca_la_fila_de_instalacion(api):
    rid = _region_id(api)
    assert api.call("PATCH", f"/regions/{rid}", "compliance_officer",
                    json={"default_posture": "allow", "reason": "relajar"}).status_code == 403


# ── relajación por destino ──────────────────────────────────────────────────────────────────────────

def test_cumplimiento_crea_la_relajacion_de_su_empresa_y_el_admin_solo_la_lee(api):
    d = api.seed(level="tenant", inference="US", entity="US", zero_data_retention=True)
    body = {"entry_id": d["id"], "level": "tenant", "reason": "alojador en EE. UU. con retención cero"}
    assert api.call("POST", "/masking-relaxations", "tenant_admin", json=body).status_code == 403
    r = api.call("POST", "/masking-relaxations", "compliance_officer", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["created_by_role"] == "compliance_officer"
    lista = api.call("GET", "/masking-relaxations", "tenant_admin").json()["data"]
    assert [x["entry_id"] for x in lista] == [d["id"]] and lista[0]["revoked_at"] is None
    assert api.call("DELETE", f"/masking-relaxations/{r.json()['id']}", "tenant_admin",
                    json={"reason": "revocar"}).status_code == 403


def test_super_admin_crea_relajaciones_de_instalacion_y_cumplimiento_no(api):
    d = api.seed(level="installation", offered_to=["*"], inference="US", entity="US", zero_data_retention=True)
    body = {"entry_id": d["id"], "level": "installation", "reason": "decisión de la instalación"}
    assert api.call("POST", "/masking-relaxations", "compliance_officer", json=body).status_code == 403
    assert api.call("POST", "/masking-relaxations", "super_admin", json=body).status_code == 201
