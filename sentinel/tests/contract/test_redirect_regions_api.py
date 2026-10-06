"""API de regiones y relajaciones por destino (057 T052, T055, T060; contracts/admin-api.md; FR-008, FR-021, FR-031a).

Altas, ediciones y bajas con motivo y registro de cambios (`entity = region` / `masking_relaxation`), los 409 de
nombre y perfil repetidos, los 422 de las precondiciones de la relajación (jurisdicciones de inferencia, entidad y
control, retención cero y lista de proveedores en un agregador) y la región efectiva."""
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import redirect_api_fixtures as fx  # noqa: E402
from redirect_api_fixtures import T1, T2  # noqa: E402

from sentinel.redirect import models as m  # noqa: E402


@pytest.fixture
def api(monkeypatch):
    return fx.make_api(monkeypatch, profile="latam_ar", region="masked_all", jurisdictions=("US", "AR", "LATAM"))


def REGION(**kw):
    body = {"name": "OTRA", "level": "installation", "jurisdictions": ["us", "ar"], "region_profiles": ["Otra"],
            "default_posture": "masked_all", "is_zone": True, "reason": "región de prueba"}
    body.update(kw)
    return body


# ── regiones ────────────────────────────────────────────────────────────────────────────────────────

def test_la_lectura_es_del_admin_cumplimiento_y_super_admin(api):
    for role in ("tenant_admin", "compliance_officer", "super_admin"):
        r = api.call("GET", "/regions", role)
        assert r.status_code == 200 and r.json()["data"][0]["default_posture"] == "masked_all"
    assert api.call("GET", "/regions", None).status_code == 401
    assert api.call("GET", "/regions", "client").status_code == 403


def test_alta_normaliza_y_deja_el_registro_con_motivo(api):
    r = api.call("POST", "/regions", "super_admin", json=REGION())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["jurisdictions"] == ["US", "AR"] and body["region_profiles"] == ["otra"] and body["level"] == "installation"
    [aud] = api.audits("region")
    assert (aud.action, aud.reason, aud.actor_role) == ("create", "región de prueba", "super_admin")
    assert aud.after["name"] == "OTRA" and None in api.store.bumps          # instalación: invalida a todas las empresas


def test_alta_de_empresa_por_cumplimiento_invalida_solo_su_cache(api):
    r = api.call("POST", "/regions", "compliance_officer", json=REGION(level="tenant"))
    assert r.status_code == 201 and r.json()["tenant_id"] == str(T1)
    assert str(T1) in api.store.bumps and None not in api.store.bumps


@pytest.mark.parametrize("campo,valor", [
    ("name", "con espacio"), ("name", "minuscula"), ("name", ""), ("jurisdictions", []), ("jurisdictions", ["", " "]),
    ("jurisdictions", ["no valido!"]), ("default_posture", "otra"), ("level", "global"), ("reason", ""),
])
def test_alta_invalida_es_422(api, campo, valor):
    assert api.call("POST", "/regions", "super_admin", json=REGION(**{campo: valor})).status_code == 422


def test_409_si_el_nombre_o_un_perfil_ya_estan_tomados_en_el_nivel(api):
    assert api.call("POST", "/regions", "super_admin", json=REGION()).status_code == 201
    assert api.call("POST", "/regions", "super_admin", json=REGION(region_profiles=["otro"])).status_code == 409  # nombre
    assert api.call("POST", "/regions", "super_admin", json=REGION(name="TERCERA")).status_code == 409           # perfil
    assert api.call("POST", "/regions", "super_admin", json=REGION(name="CUARTA", region_profiles=["latam_ar"])
                    ).status_code == 409                                                          # perfil del seed
    # el mismo perfil en otro nivel es la fila de la empresa que gana sobre la de instalación
    assert api.call("POST", "/regions", "compliance_officer",
                    json=REGION(name="PROPIA", level="tenant", region_profiles=["latam_ar"])).status_code == 201


def test_patch_cambia_campos_menos_el_nivel_y_deja_antes_y_despues(api):
    rid = api.call("GET", "/regions", "super_admin").json()["data"][0]["id"]
    r = api.call("PATCH", f"/regions/{rid}", "super_admin",
                 json={"default_posture": "masked_offregion", "jurisdictions": ["us"], "reason": "ajuste"})
    assert r.status_code == 200 and r.json()["jurisdictions"] == ["US"]
    aud = api.audits("region")[-1]
    assert aud.before["default_posture"] == "masked_all" and aud.after["default_posture"] == "masked_offregion"
    assert api.call("PATCH", f"/regions/{rid}", "super_admin", json={"level": "tenant", "reason": "ajuste"}
                    ).status_code == 422
    assert api.call("PATCH", f"/regions/{rid}", "super_admin", json={"default_posture": "allow"}).status_code == 422


def test_la_fila_de_otra_empresa_no_se_ve_ni_se_edita(api):
    propia = api.call("POST", "/regions", "compliance_officer",
                      json=REGION(name="PROPIA", level="tenant", region_profiles=["propia"])).json()["id"]
    assert [r["name"] for r in api.call("GET", "/regions", "tenant_admin", tenant=T2).json()["data"]] == ["LATAM_AR"]
    assert api.call("PATCH", f"/regions/{propia}", "compliance_officer", tenant=T2,
                    json={"default_posture": "allow", "reason": "intruso"}).status_code == 404


def test_delete_con_motivo_y_409_si_resuelve_el_perfil_de_la_instalacion(api):
    rid = api.call("GET", "/regions", "super_admin").json()["data"][0]["id"]
    assert api.call("DELETE", f"/regions/{rid}", "super_admin", json={"reason": "borrar"}).status_code == 409
    otra = api.call("POST", "/regions", "super_admin", json=REGION()).json()["id"]
    assert api.call("DELETE", f"/regions/{otra}", "super_admin", json={}).status_code == 422
    r = api.call("DELETE", f"/regions/{otra}", "super_admin", json={"reason": "ya no se usa"})
    assert r.status_code == 200
    assert api.audits("region")[-1].action == "delete" and api.audits("region")[-1].reason == "ya no se usa"


def test_regions_effective_dice_la_region_el_origen_y_la_salud(api):
    eff = api.call("GET", "/regions/effective", "tenant_admin").json()
    assert eff["source"] == "installation" and eff["region"]["name"] == "LATAM_AR"
    assert eff["default_posture"] == "masked_all" and eff["health"] == "ok" and "US" in eff["jurisdictions"]


def test_regions_effective_sin_fila_informa_el_respaldo(monkeypatch):
    api = fx.make_api(monkeypatch, profile="latam_ar", region=None)
    eff = api.call("GET", "/regions/effective", "tenant_admin").json()
    assert (eff["source"], eff["default_posture"], eff["health"], eff["region"]) == \
           ("fallback", "code_fallback", "region_row_missing", None)
    assert sorted(eff["jurisdictions"]) == ["AR", "LATAM"]


def test_regions_effective_sin_perfil_informa_region_sin_resolver(monkeypatch):
    api = fx.make_api(monkeypatch, profile=None, region=None)
    eff = api.call("GET", "/regions/effective", "tenant_admin").json()
    assert (eff["source"], eff["health"], eff["jurisdictions"]) == ("unresolved", "region_unresolved", [])


# ── relajaciones por destino: precondiciones (FR-031a, R24) ─────────────────────────────────────────

def _body(entry, level="tenant", reason="alojador nombrado con retención cero"):
    return {"entry_id": entry["id"], "level": level, "reason": reason}


def test_alta_valida_deja_el_registro(api):
    d = api.seed(inference="US", entity="US", control="US", zero_data_retention=True)
    r = api.call("POST", "/masking-relaxations", "compliance_officer", json=_body(d))
    assert r.status_code == 201 and r.json()["entry_id"] == d["id"]
    [aud] = api.audits("masking_relaxation")
    assert (aud.action, aud.reason, aud.actor_role) == ("create", "alojador nombrado con retención cero", "compliance_officer")
    assert str(T1) in api.store.bumps


@pytest.mark.parametrize("faltante,kw", [
    ("inference_jurisdiction", {"inference": None}),
    ("entity_jurisdiction", {"entity": None}),
    ("control_jurisdiction", {"control": None}),
    ("zero_data_retention", {"zero_data_retention": None}),
    ("zero_data_retention", {"zero_data_retention": False}),
])
def test_alta_con_la_ficha_incompleta_es_422_con_el_motivo(api, faltante, kw):
    base = dict(inference="US", entity="US", control="US", zero_data_retention=True)
    d = api.seed(**{**base, **kw})
    r = api.call("POST", "/masking-relaxations", "compliance_officer", json=_body(d))
    assert r.status_code == 422, r.text
    assert faltante in r.json()["detail"]["motivo"]
    assert api.audits("masking_relaxation") == []


def test_un_agregador_sin_lista_de_proveedores_es_422_y_con_lista_se_acepta(api):
    ok = dict(inference="US", entity="US", control="US", zero_data_retention=True, provider="openrouter",
              is_aggregator=True)
    sin = api.seed(name="sin lista", **ok)
    r = api.call("POST", "/masking-relaxations", "compliance_officer", json=_body(sin))
    assert r.status_code == 422 and "providers_allowlist" in r.json()["detail"]["motivo"]
    con = api.seed(name="con lista", provider_options={"providers_allowlist": ["acme"]}, **ok)
    assert api.call("POST", "/masking-relaxations", "compliance_officer", json=_body(con)).status_code == 201


def test_un_destino_sin_inferencia_nunca_se_relaja(api):
    d = api.seed(inference="unknown", entity="US", control="US", zero_data_retention=True)
    assert api.call("POST", "/masking-relaxations", "compliance_officer", json=_body(d)).status_code == 422


def test_la_entrada_tiene_que_ser_visible_para_la_empresa(api):
    ajena = api.seed(level="tenant", tenant=T2, inference="US", entity="US", zero_data_retention=True)
    assert api.call("POST", "/masking-relaxations", "compliance_officer", json=_body(ajena)).status_code == 404
    sin_oferta = api.seed(level="installation", inference="US", entity="US", zero_data_retention=True)
    assert api.call("POST", "/masking-relaxations", "compliance_officer", json=_body(sin_oferta)).status_code == 404
    assert api.call("POST", "/masking-relaxations", "compliance_officer",
                    json={"entry_id": str(uuid.uuid4()), "level": "tenant", "reason": "no existe"}).status_code == 404


def test_el_nivel_instalacion_exige_una_entrada_de_instalacion(api):
    propia = api.seed(level="tenant", inference="US", entity="US", zero_data_retention=True)
    assert api.call("POST", "/masking-relaxations", "super_admin", json=_body(propia, "installation")
                    ).status_code == 422


def test_una_segunda_vigente_para_la_misma_entrada_es_409(api):
    d = api.seed(inference="US", entity="US", zero_data_retention=True)
    assert api.call("POST", "/masking-relaxations", "compliance_officer", json=_body(d)).status_code == 201
    assert api.call("POST", "/masking-relaxations", "compliance_officer", json=_body(d)).status_code == 409


def test_la_baja_revoca_y_no_borra_la_fila(api):
    d = api.seed(inference="US", entity="US", zero_data_retention=True)
    rid = api.call("POST", "/masking-relaxations", "compliance_officer", json=_body(d)).json()["id"]
    assert api.call("DELETE", f"/masking-relaxations/{rid}", "compliance_officer", json={}).status_code == 422
    r = api.call("DELETE", f"/masking-relaxations/{rid}", "compliance_officer", json={"reason": "ya no hace falta"})
    assert r.status_code == 200 and r.json()["revoked_at"] and r.json()["revoke_reason"] == "ya no hace falta"
    with api.Session() as s:
        assert s.query(m.RedirectMaskingRelaxation).count() == 1
    assert api.audits("masking_relaxation")[-1].action == "revoke"
    assert api.call("DELETE", f"/masking-relaxations/{rid}", "compliance_officer", json={"reason": "otra vez"}
                    ).status_code == 409                                     # ya revocada
    # tras la baja se puede volver a relajar (con otro motivo, queda el historial)
    assert api.call("POST", "/masking-relaxations", "compliance_officer", json=_body(d)).status_code == 201
    assert len(api.call("GET", "/masking-relaxations", "tenant_admin").json()["data"]) == 2


def test_la_lista_no_muestra_las_de_otra_empresa(api):
    d = api.seed(inference="US", entity="US", zero_data_retention=True)
    api.call("POST", "/masking-relaxations", "compliance_officer", json=_body(d))
    assert api.call("GET", "/masking-relaxations", "tenant_admin", tenant=T2).json()["data"] == []
