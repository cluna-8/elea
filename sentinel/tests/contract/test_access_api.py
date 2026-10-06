"""API `/api/v1/access/*` (contracts/admin-perfiles.md; 069 T042). Roles, aislamiento por organización,
sujeto sin modelos, advertencia de llave y techos solo de cumplimiento. SQLite en memoria."""
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
pytest.importorskip("src.auth.rbac", reason="requiere el venv del backend")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from src.auth.session import get_current_user  # noqa: E402
from src.plugins import mount_plugin_routers  # noqa: E402

from sentinel.access import models as am  # noqa: E402
from sentinel.access import runtime as rt  # noqa: E402
from sentinel.access.api import admin  # noqa: E402
from sentinel.common.snapshot_version import SnapshotVersion  # noqa: E402
from sentinel.redirect import models as rm  # noqa: E402

T1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
T2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
U1 = "aaaaaaaa-0000-0000-0000-000000000001"
G1 = "bbbbbbbb-0000-0000-0000-000000000001"
K1 = "cccccccc-0000-0000-0000-000000000001"
RISKS = {}


def E(pid, estado, provider, cap="standard", jur="EU"):
    return {"id": f"id-{pid}", "public_id": pid, "name": pid.upper(), "provider": provider,
            "capability": cap, "semaforo": {"estado": estado}, "jurisdiccion": jur}


CATALOG = [E("a", "eu_ok", "anthropic", "frontier", "DE"), E("b", "standard", "openai", jur="US"),
           E("c", "unclassified", "deepseek", "small", "unknown")]


def _user(role, tenant=T1):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant, role=role, display_label=None)


@pytest.fixture
def api(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    am.AccessBase.metadata.create_all(engine)
    rm.RedirectBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    version = SnapshotVersion("access", redis_factory=lambda: None)
    monkeypatch.setattr(rt, "SESSION_FACTORY", Session)
    monkeypatch.setattr(rt, "VERSION", version)
    monkeypatch.setattr(rt, "ENTRIES", lambda tenant: CATALOG)
    RISKS.clear()
    RISKS.update(user_risk="minimal", key_risk=None)
    monkeypatch.setattr(admin, "SUBJECT_EXISTS", lambda db, tenant, st, sid: str(sid) in (U1, G1))
    monkeypatch.setattr(admin, "KEY_EXISTS", lambda db, tenant, kid: str(kid) == K1)
    monkeypatch.setattr(admin, "ACTOR", lambda db, tenant, u, g, k: {
        "user_id": u, "group_id": g, "key_id": k, **RISKS})
    app = FastAPI()
    assert mount_plugin_routers(app, "sentinel.catalog.api") == 6
    who = {"user": None}
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    client = TestClient(app)

    def call(method, path, role=None, tenant=T1, **kw):
        who["user"] = _user(role, tenant) if role else None
        return client.request(method, "/api/v1/access" + path, **kw)

    return SimpleNamespace(call=call, Session=Session, version=version)


def _profile(api, kind="company", name="Perfil", rules=None, role=None, tenant=T1):
    role = role or ("compliance_officer" if kind == "ceiling" else "tenant_admin")
    rules = rules if rules is not None else [{"effect": "include", "selector": "semaforo", "value": "eu_ok"}]
    r = api.call("POST", "/profiles", role, tenant=tenant, json={"kind": kind, "name": name, "rules": rules})
    assert r.status_code == 201, r.text
    return r.json()


def _by_name(api, role="tenant_admin", **kw):
    return {p["name"]: p for p in api.call("GET", "/profiles", role, **kw).json()["data"]}


# ── sesión y roles ────────────────────────────────────────────────────────────

def test_sin_sesion_es_401(api):
    assert api.call("GET", "/profiles").status_code == 401


def test_cliente_no_entra(api):
    assert api.call("GET", "/profiles", "client").status_code == 403


@pytest.mark.parametrize("role", ["tenant_admin", "compliance_officer", "lectura"])
def test_leen_admin_cumplimiento_y_lectura(api, role):
    for path in ("/profiles", "/ceilings", f"/assignments/user/{U1}", f"/keys/{K1}/profile"):
        assert api.call("GET", path, role).status_code == 200, (role, path)


def test_admin_escribe_company_y_key_pero_no_ceiling(api):
    assert api.call("POST", "/profiles", "tenant_admin",
                    json={"kind": "company", "name": "x", "rules": []}).status_code == 201
    assert api.call("POST", "/profiles", "tenant_admin",
                    json={"kind": "key", "name": "k", "rules": []}).status_code == 201
    assert api.call("POST", "/profiles", "tenant_admin",
                    json={"kind": "ceiling", "name": "c", "rules": []}).status_code == 403


def test_cumplimiento_escribe_ceiling_pero_no_company(api):
    assert api.call("POST", "/profiles", "compliance_officer",
                    json={"kind": "ceiling", "name": "c", "rules": []}).status_code == 201
    assert api.call("POST", "/profiles", "compliance_officer",
                    json={"kind": "company", "name": "x", "rules": []}).status_code == 403


def test_lectura_no_escribe_nada(api):
    assert api.call("POST", "/profiles", "lectura",
                    json={"kind": "company", "name": "x", "rules": []}).status_code == 403
    assert api.call("PUT", "/ceilings", "lectura", json={}).status_code == 403
    assert api.call("PUT", f"/assignments/user/{U1}", "lectura", json={"profiles": []}).status_code == 403
    assert api.call("PUT", f"/keys/{K1}/profile", "lectura", json={"profile_id": None}).status_code == 403


# ── perfiles ──────────────────────────────────────────────────────────────────

def test_primer_acceso_siembra_los_perfiles_de_la_organizacion(api):
    d = _by_name(api)
    assert set(d) == {"Todos salvo bloqueados", "Solo admisibles UE"}
    todos, ue = d["Todos salvo bloqueados"], d["Solo admisibles UE"]
    assert todos["seeded"] and ue["seeded"] and todos["kind"] == "company" and todos["version"] == 1
    assert todos["allows"] == 3 and ue["allows"] == 1
    assert ue["rules"] == [{"effect": "include", "selector": "semaforo", "value": "eu_ok"}]
    assert len(api.call("GET", "/profiles", "tenant_admin").json()["data"]) == 2    # no se duplica


def test_forma_exacta_del_perfil(api):
    p = _profile(api, name="Mi perfil")
    assert set(p) == {"id", "kind", "name", "rules", "archived", "seeded", "allows", "version"}
    assert p["archived"] is False and p["seeded"] is False and p["allows"] == 1


def test_perfil_de_otra_organizacion_es_404_y_no_se_lista(api):
    p = _profile(api, name="de T1")
    assert "de T1" not in _by_name(api, tenant=T2)
    assert api.call("PATCH", f"/profiles/{p['id']}", "tenant_admin", tenant=T2,
                    json={"name": "x"}).status_code == 404
    assert api.call("POST", f"/profiles/{p['id']}/archive", "tenant_admin", tenant=T2,
                    json={"reason": "motivo"}).status_code == 404
    # la otra organización tiene sus propios perfiles sembrados
    assert set(_by_name(api, tenant=T2)) == {"Todos salvo bloqueados", "Solo admisibles UE"}


@pytest.mark.parametrize("rule", [
    {"effect": "permitir", "selector": "semaforo", "value": "eu_ok"},
    {"effect": "include", "selector": "magia", "value": "x"},
    {"effect": "include", "selector": "semaforo", "value": "rojo"},
    {"effect": "include", "selector": "capacidad", "value": "enorme"},
    {"effect": "include", "selector": "proveedor", "value": "acme"},
    {"effect": "include", "selector": "entrada", "value": " "},
])
def test_reglas_invalidas_422(api, rule):
    r = api.call("POST", "/profiles", "tenant_admin", json={"kind": "company", "name": "x", "rules": [rule]})
    assert r.status_code == 422


def test_tipo_y_nombre_invalidos_422_y_nombre_repetido_409(api):
    assert api.call("POST", "/profiles", "tenant_admin",
                    json={"kind": "otro", "name": "x", "rules": []}).status_code == 422
    assert api.call("POST", "/profiles", "tenant_admin",
                    json={"kind": "company", "name": " ", "rules": []}).status_code == 422
    _profile(api, name="dup")
    assert api.call("POST", "/profiles", "tenant_admin",
                    json={"kind": "company", "name": "dup", "rules": []}).status_code == 409


def test_patch_cambia_nombre_y_reglas_y_sube_la_version(api):
    p = _profile(api, name="p")
    r = api.call("PATCH", f"/profiles/{p['id']}", "tenant_admin", json={
        "name": "p2", "rules": [{"effect": "include", "selector": "proveedor", "value": "openai"}]})
    assert r.status_code == 200
    j = r.json()
    assert j["name"] == "p2" and j["version"] == 2 and j["allows"] == 1
    assert j["rules"] == [{"effect": "include", "selector": "proveedor", "value": "openai"}]


def test_archivar_exige_motivo_y_sale_del_listado(api):
    p = _profile(api, name="p")
    assert api.call("POST", f"/profiles/{p['id']}/archive", "tenant_admin",
                    json={"reason": "ab"}).status_code == 422
    r = api.call("POST", f"/profiles/{p['id']}/archive", "tenant_admin", json={"reason": "ya no se usa"})
    assert r.status_code == 200 and r.json()["archived"] is True
    assert "p" not in _by_name(api)
    assert "p" in {x["name"] for x in api.call("GET", "/profiles?include_archived=true",
                                               "tenant_admin").json()["data"]}
    assert api.call("PATCH", f"/profiles/{p['id']}", "tenant_admin", json={"name": "z"}).status_code == 409


def test_archivar_un_perfil_asignado_es_409_con_los_sujetos(api):
    p = _profile(api, name="p")
    api.call("PUT", f"/assignments/user/{U1}", "tenant_admin", json={"profiles": [p["id"]]})
    r = api.call("POST", f"/profiles/{p['id']}/archive", "tenant_admin", json={"reason": "motivo"})
    assert r.status_code == 409
    assert r.json()["subjects"] == [{"subject_type": "user", "subject_id": U1}]


def test_toda_escritura_audita_y_sube_la_version(api):
    v0 = api.version.current(str(T1))
    p = _profile(api, name="p")
    v1 = api.version.current(str(T1))
    api.call("PATCH", f"/profiles/{p['id']}", "tenant_admin", json={"name": "q"})
    v2 = api.version.current(str(T1))
    assert v0 != v1 != v2
    with api.Session() as db:
        acts = [(a.entity, a.action) for a in db.query(rm.RedirectConfigAudit).all()]
    assert ("access_profile", "create") in acts and ("access_profile", "update") in acts


# ── techos (solo cumplimiento) ────────────────────────────────────────────────

def test_techos_forma_y_solo_cumplimiento(api):
    r = api.call("GET", "/ceilings", "tenant_admin")
    assert r.json() == {"data": {"minimal": None, "limited": None, "high_risk_annex1": None,
                                 "high_risk_annex3": None}}
    c = _profile(api, "ceiling", "techo")
    assert api.call("PUT", "/ceilings", "tenant_admin", json={"minimal": c["id"]}).status_code == 403
    r = api.call("PUT", "/ceilings", "compliance_officer", json={"high_risk_annex1": c["id"]})
    assert r.status_code == 200 and r.json()["data"]["high_risk_annex1"] == c["id"]
    assert api.call("GET", "/ceilings", "lectura").json()["data"]["high_risk_annex1"] == c["id"]
    # parcial: lo que no vino no cambia; null lo quita
    api.call("PUT", "/ceilings", "compliance_officer", json={"limited": c["id"]})
    r = api.call("PUT", "/ceilings", "compliance_officer", json={"high_risk_annex1": None}).json()["data"]
    assert r["high_risk_annex1"] is None and r["limited"] == c["id"]


def test_techo_exige_perfil_ceiling_propio_y_vigente(api):
    co = _profile(api, "company", "emp")
    assert api.call("PUT", "/ceilings", "compliance_officer", json={"minimal": co["id"]}).status_code == 422
    ajeno = _profile(api, "ceiling", "ajeno", tenant=T2)
    assert api.call("PUT", "/ceilings", "compliance_officer", json={"minimal": ajeno["id"]}).status_code == 404
    assert api.call("PUT", "/ceilings", "compliance_officer", json={"nivel_raro": None}).status_code == 422


def test_perfil_usado_como_techo_no_se_archiva(api):
    c = _profile(api, "ceiling", "techo")
    api.call("PUT", "/ceilings", "compliance_officer", json={"minimal": c["id"]})
    r = api.call("POST", f"/profiles/{c['id']}/archive", "compliance_officer", json={"reason": "motivo"})
    assert r.status_code == 409 and r.json()["subjects"][0]["subject_type"] == "ceiling"


# ── asignaciones ──────────────────────────────────────────────────────────────

def test_asignacion_de_usuario_grupo_y_organizacion(api):
    p = _profile(api, name="p")
    for st, sid in (("user", U1), ("group", G1), ("tenant", str(T1))):
        assert api.call("GET", f"/assignments/{st}/{sid}", "lectura").json() == {
            "subject_type": st, "subject_id": sid, "profiles": []}
        r = api.call("PUT", f"/assignments/{st}/{sid}", "tenant_admin", json={"profiles": [p["id"]]})
        assert r.status_code == 200 and r.json()["profiles"] == [p["id"]]
        assert api.call("GET", f"/assignments/{st}/{sid}", "lectura").json()["profiles"] == [p["id"]]
    # reemplaza: lista vacía = sin asignación propia
    api.call("PUT", f"/assignments/user/{U1}", "tenant_admin", json={"profiles": []})
    assert api.call("GET", f"/assignments/user/{U1}", "lectura").json()["profiles"] == []


def test_asignacion_sujetos_ajenos_o_invalidos_404(api):
    assert api.call("GET", f"/assignments/tenant/{T2}", "tenant_admin").status_code == 404   # otra org
    assert api.call("GET", f"/assignments/user/{uuid.uuid4()}", "tenant_admin").status_code == 404
    assert api.call("GET", f"/assignments/robot/{U1}", "tenant_admin").status_code == 404
    assert api.call("GET", "/assignments/user/no-es-uuid", "tenant_admin").status_code == 404


def test_asignar_perfil_ajeno_archivado_o_de_otro_tipo(api):
    ajeno = _profile(api, name="ajeno", tenant=T2)
    c = _profile(api, "ceiling", "techo")
    assert api.call("PUT", f"/assignments/user/{U1}", "tenant_admin",
                    json={"profiles": [ajeno["id"]]}).status_code == 404
    assert api.call("PUT", f"/assignments/user/{U1}", "tenant_admin",
                    json={"profiles": [c["id"]]}).status_code == 422


def test_sujeto_sin_modelos_422_salvo_confirmacion(api):
    vacio = _profile(api, name="vacio", rules=[])
    r = api.call("PUT", f"/assignments/user/{U1}", "tenant_admin", json={"profiles": [vacio["id"]]})
    assert r.status_code == 422 and r.json()["empty"] is True and r.json()["detail"]
    assert api.call("GET", f"/assignments/user/{U1}", "tenant_admin").json()["profiles"] == []
    r = api.call("PUT", f"/assignments/user/{U1}", "tenant_admin",
                 json={"profiles": [vacio["id"]], "confirm_empty": True})
    assert r.status_code == 200 and r.json()["profiles"] == [vacio["id"]]


# ── llave ─────────────────────────────────────────────────────────────────────

def test_perfil_de_llave_y_advertencia_si_pretende_ampliar(api):
    ue = _by_name(api)["Solo admisibles UE"]
    api.call("PUT", f"/assignments/tenant/{T1}", "tenant_admin", json={"profiles": [ue["id"]]})
    ampliar = _profile(api, "key", "k_b", [{"effect": "include", "selector": "entrada", "value": "b"}])
    r = api.call("PUT", f"/keys/{K1}/profile", "tenant_admin", json={"profile_id": ampliar["id"]})
    assert r.status_code == 200
    j = r.json()
    assert j["key_id"] == K1 and j["profile_id"] == ampliar["id"] and len(j["warnings"]) == 1
    assert "b" in j["warnings"][0] and "achica" in j["warnings"][0]
    assert api.call("GET", f"/keys/{K1}/profile", "lectura").json() == {"key_id": K1,
                                                                       "profile_id": ampliar["id"]}
    # el efectivo igual recorta: b no está en el efectivo del dueño
    e = api.call("GET", f"/effective?key={K1}", "tenant_admin").json()
    assert e["permitidos"] == [] and e["llave"] == {"profile_id": ampliar["id"]}


def test_perfil_de_llave_que_achica_no_advierte_y_se_puede_quitar(api):
    ach = _profile(api, "key", "k_a", [{"effect": "include", "selector": "entrada", "value": "a"}])
    r = api.call("PUT", f"/keys/{K1}/profile", "tenant_admin", json={"profile_id": ach["id"]}).json()
    assert r["warnings"] == []
    r = api.call("PUT", f"/keys/{K1}/profile", "tenant_admin", json={"profile_id": None}).json()
    assert r == {"key_id": K1, "profile_id": None, "warnings": []}


def test_llave_ajena_404_y_perfil_de_otro_tipo_422(api):
    assert api.call("PUT", f"/keys/{uuid.uuid4()}/profile", "tenant_admin",
                    json={"profile_id": None}).status_code == 404
    co = _profile(api, name="emp")
    assert api.call("PUT", f"/keys/{K1}/profile", "tenant_admin", json={"profile_id": co["id"]}).status_code == 422


# ── efectivo y vista previa ───────────────────────────────────────────────────

def test_efectivo_sin_politica_no_restringe(api):
    j = api.call("GET", "/effective", "compliance_officer").json()
    assert j["restringe"] is False and {p["public_id"] for p in j["permitidos"]} == {"a", "b", "c"}
    assert set(j) == {"permitidos", "restringe", "techo", "perfiles", "llave", "version"}
    assert set(j["permitidos"][0]) == {"id", "public_id", "name", "provider", "semaforo"}
    assert j["techo"] == {"risk_level": "minimal", "origen": "sin_techo", "count": None}


def test_efectivo_con_perfil_de_empresa_y_techo(api):
    todos = _by_name(api)["Todos salvo bloqueados"]
    api.call("PUT", f"/assignments/tenant/{T1}", "tenant_admin", json={"profiles": [todos["id"]]})
    c = _profile(api, "ceiling", "techo_h1", [{"effect": "include", "selector": "entrada", "value": "a"}])
    api.call("PUT", "/ceilings", "compliance_officer", json={"high_risk_annex1": c["id"]})
    RISKS["user_risk"] = "high_risk_annex1"
    j = api.call("GET", f"/effective?user={U1}", "tenant_admin").json()
    assert j["restringe"] and [p["public_id"] for p in j["permitidos"]] == ["a"]
    assert j["techo"] == {"risk_level": "high_risk_annex1", "origen": "user", "count": 1}
    assert j["perfiles"] == [{"id": todos["id"], "name": "Todos salvo bloqueados", "origen": "tenant"}]
    RISKS["user_risk"] = "minimal"
    assert len(api.call("GET", f"/effective?user={U1}", "tenant_admin").json()["permitidos"]) == 3


def test_efectivo_solo_admin_y_cumplimiento(api):
    assert api.call("GET", "/effective", "lectura").status_code == 403


def test_preview_permitido_y_no_permitido(api):
    ue = _by_name(api)["Solo admisibles UE"]
    api.call("PUT", f"/assignments/user/{U1}", "tenant_admin", json={"profiles": [ue["id"]]})
    r = api.call("POST", "/preview", "tenant_admin", json={"user": U1, "model": "a"}).json()
    assert r["allowed"] is True and r["motivo"] is None
    r = api.call("POST", "/preview", "tenant_admin", json={"user": U1, "model": "b"}).json()
    assert r["allowed"] is False and r["motivo"] == "profile_not_allowed"
    assert r["permitidos_origen"]["restringe"] is True
    assert r["permitidos_origen"]["perfiles"][0]["origen"] == "user"
    assert api.call("POST", "/preview", "tenant_admin", json={"user": U1, "model": "zzz"}).status_code == 404


def test_aislamiento_efectivo_no_ve_perfiles_de_otra_organizacion(api):
    ue1 = _by_name(api)["Solo admisibles UE"]
    api.call("PUT", f"/assignments/tenant/{T1}", "tenant_admin", json={"profiles": [ue1["id"]]})
    j = api.call("GET", "/effective", "tenant_admin", tenant=T2).json()
    assert j["restringe"] is False and len(j["permitidos"]) == 3


def test_falla_del_resolutor_es_503(api):
    with api.Session() as db:
        db.add(am.AiActCeiling(tenant_id=T1, risk_level="minimal", profile_id=uuid.uuid4()))
        db.commit()
    assert api.call("GET", "/effective", "tenant_admin").status_code == 503


def test_asignacion_de_organizacion_acepta_asterisco_y_devuelve_el_id_que_vino(api):
    p = _profile(api, name="p")
    r = api.call("PUT", "/assignments/tenant/*", "tenant_admin", json={"profiles": [p["id"]]})
    assert r.status_code == 200 and r.json() == {"subject_type": "tenant", "subject_id": "*",
                                                 "profiles": [p["id"]]}
    # el mismo conjunto se ve por el UUID real y por «*»
    assert api.call("GET", f"/assignments/tenant/{T1}", "lectura").json()["profiles"] == [p["id"]]
    assert api.call("GET", "/assignments/tenant/*", "lectura").json()["subject_id"] == "*"
    # «*» es la organización DE LA SESIÓN: otra organización no ve ni toca la de T1
    assert api.call("GET", "/assignments/tenant/*", "lectura", tenant=T2).json()["profiles"] == []
    assert api.call("GET", f"/assignments/tenant/{T2}", "lectura").status_code == 404
    assert api.call("GET", "/assignments/user/*", "lectura").status_code == 404
