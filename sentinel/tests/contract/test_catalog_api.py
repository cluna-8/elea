"""API de administración `/api/v1/catalog/*` (contracts/admin-catalogo.md; 069 T017).

Montada con la costura S1 real y los guardas de rol reales del backend; sesión SQLite en memoria
(la RLS la cubren los tests de migración). Corre con el venv del backend.
"""
import json
import sys
import uuid
from datetime import date, timedelta
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

from sentinel.catalog import models as cm  # noqa: E402
from sentinel.catalog.api import admin  # noqa: E402
from sentinel.redirect import models as rm  # noqa: E402

T1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
T2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
SECRET = "sk-or-secreto-del-proveedor-NO-DEBE-VOLVER"


def _user(role, tenant=T1):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant, role=role, display_label=None)


class _Store:
    def __init__(self):
        self.bumps = []

    def bump(self, tenant=None):
        self.bumps.append(tenant)


@pytest.fixture
def api(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    cm.CatalogBase.metadata.create_all(engine)
    rm.RedirectBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    store = _Store()
    dpas = {}
    monkeypatch.setattr(admin, "SESSION_FACTORY", Session)
    monkeypatch.setattr(admin, "ENCRYPT", lambda s: "cifrado:" + s[::-1])
    monkeypatch.setattr(admin, "DECRYPT", lambda b: b[len("cifrado:"):][::-1])
    monkeypatch.setattr(admin, "STORE", store)
    monkeypatch.setattr(admin, "DPA_LOOKUP", lambda db, tenant, dpa_id: dpas.get(str(dpa_id)))
    monkeypatch.setattr(admin, "TODAY", lambda: date(2026, 10, 1))
    app = FastAPI()
    assert mount_plugin_routers(app, "sentinel.catalog.api") == 6
    who = {"user": None}
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    client = TestClient(app)

    def call(method, path, role=None, tenant=T1, **kw):
        who["user"] = _user(role, tenant) if role else None
        return client.request(method, "/api/v1/catalog" + path, **kw)

    return SimpleNamespace(call=call, Session=Session, store=store, dpas=dpas)


def _entry(**kw):
    body = {"level": "tenant", "name": "OpenRouter GLM", "provider": "openrouter",
            "real_model": "z-ai/glm-4.6", "protocol_family": "openai_chat",
            "credential": {"new": {"name": "or-key", "value": SECRET}},
            "capability": "standard", "role": "text", "context_window": 128000}
    body.update(kw)
    return body


def _create(api, role="tenant_admin", tenant=T1, **kw):
    r = api.call("POST", "/entries", role, tenant=tenant, json=_entry(**kw))
    assert r.status_code == 201, r.text
    return r.json()


def _full_sheet(**kw):
    s = {"inference_jurisdiction": "EU", "logs_jurisdiction": "EU", "trains_on_data": False,
         "transfer_mechanism": "n/a", "zero_data_retention": True}
    s.update(kw)
    return s


# ── sesión y roles ────────────────────────────────────────────────────────────

def test_sin_sesion_es_401(api):
    assert api.call("GET", "/entries").status_code == 401


@pytest.mark.parametrize("role", ["client"])
def test_cliente_no_entra(api, role):
    assert api.call("GET", "/entries", role).status_code == 403


@pytest.mark.parametrize("role", ["tenant_admin", "compliance_officer", "lectura"])
def test_leen_admin_cumplimiento_y_lectura(api, role):
    assert api.call("GET", "/entries", role).status_code == 200


@pytest.mark.parametrize("role", ["compliance_officer", "lectura", "client"])
def test_solo_el_admin_da_de_alta(api, role):
    assert api.call("POST", "/entries", role, json=_entry()).status_code == 403


def test_entrada_de_instalacion_solo_operador(api):
    body = _entry(level="installation", credential={"env_ref": "REDIRECT_CRED_OR"})
    assert api.call("POST", "/entries", "tenant_admin", json=body).status_code == 403
    r = api.call("POST", "/entries", "super_admin", json=body)
    assert r.status_code == 201 and r.json()["tenant_id"] is None and r.json()["level"] == "installation"


# ── alta (US1: OpenRouter con DPA, región y vencimiento desde la consola) ──────

def test_alta_devuelve_201_sin_secreto_y_sin_clasificar(api):
    d = _create(api)
    assert d["has_credential"] is True and d["credential"]["kind"] == "secret"
    assert d["credential"]["fingerprint"] and SECRET not in json.dumps(d)
    assert d["is_aggregator"] is True                     # OpenRouter se declara agregador (FR-002a)
    assert d["semaforo"]["estado"] == "unclassified"      # nace sin clasificar (FR-039)
    assert d["status"] == "active" and d["source"] == "console"
    assert api.store.bumps == [str(T1)]                   # el plano de datos ve el cambio sin reinicio


def test_el_secreto_se_guarda_cifrado_y_nunca_vuelve(api):
    d = _create(api)
    for path in ("/entries", f"/entries/{d['id']}", "/credentials", f"/entries/{d['id']}/sheet"):
        r = api.call("GET", path, "tenant_admin")
        assert r.status_code == 200 and SECRET not in r.text, path
    with api.Session() as s:
        blob = s.query(cm.Credential).one().ciphertext
    assert blob.startswith("cifrado:") and SECRET not in blob


def test_proveedor_o_protocolo_desconocidos_son_422(api):
    assert api.call("POST", "/entries", "tenant_admin", json=_entry(provider="marte")).status_code == 422
    assert api.call("POST", "/entries", "tenant_admin",
                    json=_entry(protocol_family="telepatia")).status_code == 422


def test_proveedor_que_exige_credencial_o_base(api):
    assert api.call("POST", "/entries", "tenant_admin",
                    json=_entry(credential=None)).status_code == 422
    r = api.call("POST", "/entries", "tenant_admin",
                 json=_entry(provider="hosted_vllm", name="vllm", credential={"new": {"name": "v", "value": "x"}}))
    assert r.status_code == 422                                   # falta api_base
    r = api.call("POST", "/entries", "tenant_admin",
                 json=_entry(provider="hosted_vllm", name="vllm", api_base="http://vllm:8000/v1",
                             credential={"new": {"name": "v", "value": "x"}}))
    assert r.status_code == 201


def test_nombre_duplicado_en_la_organizacion_es_409(api):
    _create(api)
    assert api.call("POST", "/entries", "tenant_admin",
                    json=_entry(credential={"new": {"name": "otra", "value": "x"}})).status_code == 409


def test_nombre_se_reutiliza_tras_archivar(api):
    d = _create(api)
    assert api.call("POST", f"/entries/{d['id']}/archive", "tenant_admin", json={"reason": "obsoleto"}).status_code == 200
    _create(api, credential={"new": {"name": "or-key-2", "value": "x"}})


def test_env_ref_es_solo_del_operador(api):
    body = _entry(credential={"env_ref": "REDIRECT_CRED_OR"})
    assert api.call("POST", "/entries", "tenant_admin", json=body).status_code == 403
    body["level"] = "installation"
    assert api.call("POST", "/entries", "super_admin", json=body).status_code == 201


def test_credencial_existente_se_reutiliza_entre_modelos(api):
    a = _create(api)
    b = _create(api, name="OpenRouter Qwen", real_model="qwen/qwen3", credential={"id": a["credential"]["id"]})
    assert b["credential"]["id"] == a["credential"]["id"]
    creds = api.call("GET", "/credentials", "tenant_admin").json()["data"]
    assert len(creds) == 1 and sorted(creds[0]["in_use_by"]) == ["OpenRouter GLM", "OpenRouter Qwen"]


def test_credencial_ajena_no_se_puede_usar(api):
    otra = _create(api, tenant=T2, credential={"new": {"name": "ajena", "value": "x"}})
    r = api.call("POST", "/entries", "tenant_admin", json=_entry(credential={"id": otra["credential"]["id"]}))
    assert r.status_code in (404, 422)


def test_id_publico_por_defecto_es_el_slug_del_nombre_y_se_puede_fijar(api):
    d = _create(api)
    assert d["public_id"] == "openrouter-glm"
    e = _create(api, name="Otro", public_id="mi-modelo", credential={"id": d["credential"]["id"]})
    assert e["public_id"] == "mi-modelo"


@pytest.mark.parametrize("bad", ["con espacio", "rdx-interno", "rdx-x/y"])
def test_id_publico_invalido_es_422(api, bad):
    r = api.call("POST", "/entries", "tenant_admin", json=_entry(public_id=bad))
    assert r.status_code == 422


def test_id_publico_repetido_es_409_aunque_el_nombre_cambie(api):
    d = _create(api)
    r = api.call("POST", "/entries", "tenant_admin",
                 json=_entry(name="Distinto", public_id=d["public_id"], credential={"id": d["credential"]["id"]}))
    assert r.status_code == 409


# ── ficha y semáforo (FR-002, FR-003, FR-002a) ──────────────────────────────────

def test_ficha_completa_con_dpa_vigente_es_admisible(api):
    d = _create(api, provider="deepseek", name="DS UE", real_model="deepseek-chat",
                credential={"new": {"name": "ds", "value": "k"}})
    dpa = str(uuid.uuid4())
    api.dpas[dpa] = {"expiration_date": date(2027, 1, 1), "processing_region": "EU", "is_active": True}
    r = api.call("PUT", f"/entries/{d['id']}/sheet", "tenant_admin",
                 json=_full_sheet(dpa_registry_id=dpa))
    assert r.status_code == 200, r.text
    assert r.json()["semaforo"] == {"estado": "eu_ok", "motivos": []}
    assert api.call("GET", f"/entries/{d['id']}", "lectura").json()["semaforo"]["estado"] == "eu_ok"


def test_dpa_que_vence_cambia_el_semaforo_sin_editar_nada(api, monkeypatch):
    d = _create(api, provider="deepseek", name="DS UE", real_model="deepseek-chat",
                credential={"new": {"name": "ds", "value": "k"}})
    dpa = str(uuid.uuid4())
    api.dpas[dpa] = {"expiration_date": date(2026, 10, 1), "processing_region": "EU", "is_active": True}
    api.call("PUT", f"/entries/{d['id']}/sheet", "tenant_admin", json=_full_sheet(dpa_registry_id=dpa))
    assert api.call("GET", f"/entries/{d['id']}", "tenant_admin").json()["semaforo"]["estado"] == "eu_ok"
    monkeypatch.setattr(admin, "TODAY", lambda: date(2026, 10, 2))
    s = api.call("GET", f"/entries/{d['id']}", "tenant_admin").json()["semaforo"]
    assert s == {"estado": "standard", "motivos": ["dpa_vencido"]}


def test_openrouter_agregador_no_es_admisible_sin_region_ue_contratada(api):
    d = _create(api)
    dpa = str(uuid.uuid4())
    api.dpas[dpa] = {"expiration_date": date(2027, 1, 1), "processing_region": "EU", "is_active": True}
    r = api.call("PUT", f"/entries/{d['id']}/sheet", "tenant_admin",
                 json=_full_sheet(dpa_registry_id=dpa, eu_region_contracted=False))
    assert r.json()["semaforo"] == {"estado": "standard", "motivos": ["agregador"]}
    r = api.call("PUT", f"/entries/{d['id']}/sheet", "tenant_admin",
                 json=_full_sheet(dpa_registry_id=dpa, eu_region_contracted=True))
    assert r.json()["semaforo"]["estado"] == "eu_ok"


def test_el_semaforo_no_se_puede_escribir(api):
    d = _create(api)
    r = api.call("PUT", f"/entries/{d['id']}/sheet", "tenant_admin",
                 json=_full_sheet(semaforo={"estado": "eu_ok"}))
    assert r.status_code == 422
    r = api.call("PATCH", f"/entries/{d['id']}", "tenant_admin", json={"semaforo": "eu_ok"})
    assert r.status_code == 422


def test_cumplimiento_tambien_edita_la_ficha_pero_lectura_no(api):
    d = _create(api)
    assert api.call("PUT", f"/entries/{d['id']}/sheet", "compliance_officer", json=_full_sheet()).status_code == 200
    assert api.call("PUT", f"/entries/{d['id']}/sheet", "lectura", json=_full_sheet()).status_code == 403
    assert api.call("PUT", f"/entries/{d['id']}/sheet", "client", json=_full_sheet()).status_code == 403


def test_la_ficha_registra_quien_y_cuando_y_versiona(api):
    d = _create(api)
    r1 = api.call("PUT", f"/entries/{d['id']}/sheet", "tenant_admin", json=_full_sheet()).json()
    r2 = api.call("PUT", f"/entries/{d['id']}/sheet", "tenant_admin", json=_full_sheet(trains_on_data=True)).json()
    assert r1["sheet"]["classified_by"] and r1["sheet"]["classified_at"]
    assert r1["sheet"]["classification_version"] != r2["sheet"]["classification_version"]


def test_dpa_inexistente_es_422(api):
    d = _create(api)
    r = api.call("PUT", f"/entries/{d['id']}/sheet", "tenant_admin",
                 json=_full_sheet(dpa_registry_id=str(uuid.uuid4())))
    assert r.status_code == 422


def test_cambiar_proveedor_o_modelo_deja_la_ficha_obsoleta(api):
    d = _create(api)
    api.call("PUT", f"/entries/{d['id']}/sheet", "tenant_admin", json=_full_sheet())
    r = api.call("PATCH", f"/entries/{d['id']}", "tenant_admin", json={"real_model": "otro/modelo"})
    assert r.status_code == 200
    assert r.json()["sheet"]["classification_version"] == "stale"
    assert r.json()["semaforo"] == {"estado": "unclassified", "motivos": ["ficha_desactualizada"]}
    r = api.call("PUT", f"/entries/{d['id']}/sheet", "tenant_admin", json=_full_sheet())
    assert r.json()["sheet"]["classification_version"] != "stale"


# ── edición, archivo y visibilidad (FR-001a) ──────────────────────────────────────

def test_editar_desactivar_y_archivar(api):
    d = _create(api)
    r = api.call("PATCH", f"/entries/{d['id']}", "tenant_admin", json={"status": "inactive", "context_window": 64000})
    assert r.status_code == 200 and r.json()["status"] == "inactive" and r.json()["context_window"] == 64000
    assert api.call("POST", f"/entries/{d['id']}/archive", "tenant_admin", json={}).status_code == 422
    a = api.call("POST", f"/entries/{d['id']}/archive", "tenant_admin", json={"reason": "ya no se usa"})
    assert a.status_code == 200 and a.json()["status"] == "archived"
    assert api.call("PATCH", f"/entries/{d['id']}", "tenant_admin", json={"status": "active"}).status_code == 409
    assert d["id"] not in [e["id"] for e in api.call("GET", "/entries", "tenant_admin").json()["data"]]
    assert d["id"] in [e["id"] for e in api.call("GET", "/entries?include_archived=true", "tenant_admin").json()["data"]]


def test_una_organizacion_no_ve_las_entradas_de_otra(api):
    d = _create(api)
    assert api.call("GET", "/entries", "tenant_admin", tenant=T2).json()["data"] == []
    assert api.call("GET", f"/entries/{d['id']}", "tenant_admin", tenant=T2).status_code == 404
    assert api.call("PATCH", f"/entries/{d['id']}", "tenant_admin", tenant=T2, json={"status": "inactive"}).status_code == 404
    assert api.call("GET", "/credentials", "tenant_admin", tenant=T2).json()["data"] == []


def test_entrada_de_instalacion_visible_solo_si_se_ofrece_y_sin_credencial(api):
    d = _create(api, role="super_admin", level="installation", name="OR instalación",
                credential={"new": {"name": "or-inst", "value": SECRET}})
    assert api.call("GET", "/entries", "tenant_admin", tenant=T2).json()["data"] == []
    r = api.call("PUT", f"/entries/{d['id']}/offers", "super_admin", json={"tenants": [str(T2)]})
    assert r.status_code == 200 and r.json()["tenants"] == [str(T2)]
    vistas = api.call("GET", "/entries", "tenant_admin", tenant=T2).json()["data"]
    assert [e["id"] for e in vistas] == [d["id"]]
    assert vistas[0]["has_credential"] is True and "credential" not in vistas[0]
    assert SECRET not in json.dumps(vistas)
    assert api.call("GET", "/credentials", "tenant_admin", tenant=T2).json()["data"] == []
    assert api.call("GET", "/entries", "tenant_admin", tenant=T1).json()["data"] == []   # no se la ofrecieron


def test_la_organizacion_no_edita_la_ficha_ni_la_entrada_de_instalacion(api):
    d = _create(api, role="super_admin", level="installation", name="OR inst",
                credential={"new": {"name": "or-inst", "value": "x"}})
    api.call("PUT", f"/entries/{d['id']}/offers", "super_admin", json={"tenants": [str(T2)]})
    assert api.call("PUT", f"/entries/{d['id']}/sheet", "tenant_admin", tenant=T2, json=_full_sheet()).status_code == 403
    assert api.call("PATCH", f"/entries/{d['id']}", "tenant_admin", tenant=T2, json={"status": "inactive"}).status_code == 403
    assert api.call("PUT", f"/entries/{d['id']}/sheet", "super_admin", json=_full_sheet()).status_code == 200


def test_ofertas_solo_del_operador_y_solo_de_entradas_de_instalacion(api):
    prop = _create(api)
    assert api.call("PUT", f"/entries/{prop['id']}/offers", "super_admin", json={"tenants": [str(T2)]}).status_code == 409
    inst = _create(api, role="super_admin", level="installation", name="I",
                   credential={"new": {"name": "i", "value": "x"}})
    assert api.call("PUT", f"/entries/{inst['id']}/offers", "tenant_admin", json={"tenants": [str(T2)]}).status_code == 403


def test_retirar_la_oferta_saca_la_entrada_a_esa_organizacion(api):
    d = _create(api, role="super_admin", level="installation", name="I",
                credential={"new": {"name": "i", "value": "x"}})
    api.call("PUT", f"/entries/{d['id']}/offers", "super_admin", json={"tenants": [str(T2)]})
    api.call("PUT", f"/entries/{d['id']}/offers", "super_admin", json={"tenants": []})
    assert api.call("GET", "/entries", "tenant_admin", tenant=T2).json()["data"] == []
    assert api.store.bumps[-1] is None                     # cambio de nivel instalación


# ── credenciales ────────────────────────────────────────────────────────────────

def test_alta_y_reemplazo_de_credencial_solo_dejan_huella(api):
    r = api.call("POST", "/credentials", "tenant_admin", json={"name": "k1", "kind": "secret", "value": SECRET})
    assert r.status_code == 201 and SECRET not in r.text
    cid, fp1 = r.json()["id"], r.json()["fingerprint"]
    r = api.call("POST", f"/credentials/{cid}/replace", "tenant_admin", json={"value": SECRET + "-v2"})
    assert r.status_code == 200 and SECRET not in r.text and r.json()["fingerprint"] != fp1
    with api.Session() as s:
        audits = [(a.entity, a.action, json.dumps([a.before, a.after])) for a in s.query(rm.RedirectConfigAudit)]
    assert [(e, a) for e, a, _ in audits] == [("credential", "create"), ("credential", "replace")]
    assert all(SECRET not in blob for _, _, blob in audits)
    assert fp1 in audits[1][2]                             # sí queda la huella anterior


def test_revocar_en_uso_sin_reemplazo_es_409(api):
    d = _create(api)
    r = api.call("POST", f"/credentials/{d['credential']['id']}/revoke", "tenant_admin", json={})
    assert r.status_code == 409 and d["name"] in r.text
    assert api.call("GET", f"/entries/{d['id']}", "tenant_admin").json()["has_credential"] is True


def test_revocar_con_reemplazo_reapunta_las_entradas(api):
    d = _create(api)
    nuevo = api.call("POST", "/credentials", "tenant_admin", json={"name": "k2", "kind": "secret", "value": "x"}).json()
    r = api.call("POST", f"/credentials/{d['credential']['id']}/revoke", "tenant_admin",
                 json={"replacement_id": nuevo["id"]})
    assert r.status_code == 200
    assert api.call("GET", f"/entries/{d['id']}", "tenant_admin").json()["credential"]["id"] == nuevo["id"]


def test_revocar_desactivando_las_entradas(api):
    d = _create(api)
    r = api.call("POST", f"/credentials/{d['credential']['id']}/revoke", "tenant_admin",
                 json={"deactivate_entries": True})
    assert r.status_code == 200
    got = api.call("GET", f"/entries/{d['id']}", "tenant_admin").json()
    assert got["status"] == "inactive" and got["has_credential"] is False


def test_revocar_sin_uso_es_directo(api):
    c = api.call("POST", "/credentials", "tenant_admin", json={"name": "k1", "kind": "secret", "value": "x"}).json()
    assert api.call("POST", f"/credentials/{c['id']}/revoke", "tenant_admin", json={}).status_code == 200
    assert api.call("GET", "/credentials", "tenant_admin").json()["data"] == []


def test_reemplazo_de_otra_organizacion_no_vale(api):
    d = _create(api)
    ajena = api.call("POST", "/credentials", "tenant_admin", tenant=T2,
                     json={"name": "k", "kind": "secret", "value": "x"}).json()
    r = api.call("POST", f"/credentials/{d['credential']['id']}/revoke", "tenant_admin",
                 json={"replacement_id": ajena["id"]})
    assert r.status_code in (404, 422)


def test_cambios_quedan_en_el_registro_sin_secretos(api):
    d = _create(api)
    api.call("PUT", f"/entries/{d['id']}/sheet", "tenant_admin", json=_full_sheet())
    api.call("PATCH", f"/entries/{d['id']}", "tenant_admin", json={"status": "inactive"})
    with api.Session() as s:
        audits = [(a.entity, a.action, a.actor_role) for a in s.query(rm.RedirectConfigAudit)]
        todo = json.dumps([[a.before, a.after] for a in s.query(rm.RedirectConfigAudit)])
    assert ("catalog_entry", "create", "tenant_admin") in audits
    assert ("catalog_sheet", "update", "tenant_admin") in audits
    assert ("catalog_entry", "update", "tenant_admin") in audits
    assert SECRET not in todo


# ── habilitar bloqueadas por defecto y vigencia del DPA en la vista ────────────────

def test_la_vista_trae_vigencia_y_region_del_dpa_pero_no_el_documento(api):
    d = _create(api, provider="deepseek", name="DS", real_model="m", credential={"new": {"name": "k", "value": "x"}})
    dpa = str(uuid.uuid4())
    api.dpas[dpa] = {"expiration_date": date(2027, 1, 1), "processing_region": "EU", "is_active": True,
                     "document_reference": "secreto-interno"}
    r = api.call("PUT", f"/entries/{d['id']}/sheet", "tenant_admin", json=_full_sheet(dpa_registry_id=dpa)).json()
    assert r["dpa"] == {"expiration_date": "2027-01-01", "processing_region": "EU", "is_active": True}
    assert "secreto-interno" not in json.dumps(r)


def test_entrada_bloqueada_por_defecto_se_habilita_con_motivo(api):
    d = _create(api, provider="deepseek", name="DS", real_model="m", credential={"new": {"name": "k", "value": "x"}})
    assert d["blocked_by_default"] is True and d["enabled_at"] is None
    assert api.call("POST", f"/entries/{d['id']}/enable", "tenant_admin", json={}).status_code == 422
    assert api.call("POST", f"/entries/{d['id']}/enable", "lectura", json={"reason": "ok ok"}).status_code == 403
    r = api.call("POST", f"/entries/{d['id']}/enable", "compliance_officer", json={"reason": "DPA firmado"})
    assert r.status_code == 200 and r.json()["enabled_at"]


def test_habilitar_una_no_bloqueada_es_409(api):
    d = _create(api)
    assert api.call("POST", f"/entries/{d['id']}/enable", "tenant_admin", json={"reason": "porque sí"}).status_code == 409


def test_organizacion_habilita_la_de_instalacion_solo_en_su_oferta(api):
    d = _create(api, role="super_admin", level="installation", provider="deepseek", name="DS inst",
                real_model="m", credential={"new": {"name": "k", "value": "x"}})
    api.call("PUT", f"/entries/{d['id']}/offers", "super_admin", json={"tenants": [str(T2)]})
    r = api.call("POST", f"/entries/{d['id']}/enable", "compliance_officer", tenant=T2, json={"reason": "habilitado"})
    assert r.status_code == 200
    with api.Session() as s:
        offer = s.query(cm.CatalogOffer).filter(cm.CatalogOffer.tenant_id == T2).one()
        assert offer.enabled_at is not None and s.get(cm.CatalogEntry, uuid.UUID(d["id"])).enabled_at is None


def test_dos_modelos_con_la_misma_referencia_de_entorno_comparten_la_credencial(api):
    """Hallazgo en nix: el operador dio de alta un modelo de imagen y otro de audio con la misma referencia
    `REDIRECT_CRED_OPENAI` y el segundo chocaba con «ya hay una credencial con ese nombre»."""
    a = _create(api, role="super_admin", level="installation", name="Imagen", provider="openai",
                real_model="gpt-image-1", credential={"env_ref": "REDIRECT_CRED_OPENAI"})
    b = _create(api, role="super_admin", level="installation", name="Audio", provider="openai",
                real_model="tts-1", credential={"env_ref": "REDIRECT_CRED_OPENAI"})
    assert a["credential"]["id"] == b["credential"]["id"]
    with api.Session() as s:
        assert s.query(cm.Credential).count() == 1


# ── selector de DPA (T156) ────────────────────────────────────────────────────

def _dpa_row(tenant, provider="Azure OpenAI", **kw):
    row = {"id": uuid.uuid4(), "tenant_id": tenant, "provider_name": provider, "dpa_type": "standard",
           "processing_region": "EU", "expiration_date": date(2027, 1, 1), "is_active": True}
    row.update(kw)
    return row


def test_lista_de_dpas_trae_proveedor_region_y_vigencia(api, monkeypatch):
    mine = _dpa_row(T1)
    vencido = _dpa_row(T1, provider="OpenAI", expiration_date=date(2026, 9, 1))
    ajeno = _dpa_row(T2, provider="Otro")
    monkeypatch.setattr(admin, "DPA_LIST", lambda db, tenant: [mine, vencido, ajeno])
    r = api.call("GET", "/dpas", "lectura")
    assert r.status_code == 200, r.text
    data = {d["provider_name"]: d for d in r.json()["data"]}
    assert set(data) == {"Azure OpenAI", "OpenAI"}                     # el DPA de otra organización no sale
    assert data["Azure OpenAI"]["id"] == str(mine["id"])
    assert data["Azure OpenAI"]["processing_region"] == "EU" and data["Azure OpenAI"]["vigente"] is True
    assert data["OpenAI"]["vigente"] is False                          # vencido al 1-oct-2026
    assert "document_reference" not in data["Azure OpenAI"]            # solo metadatos, nunca el documento


def test_lista_de_dpas_requiere_sesion(api):
    assert api.call("GET", "/dpas").status_code == 401


def test_la_ficha_rechaza_un_dpa_de_otra_organizacion(api):
    d = _create(api)
    ajeno = str(uuid.uuid4())
    api.dpas[ajeno] = {"tenant_id": T2, "expiration_date": date(2027, 1, 1),
                       "processing_region": "EU", "is_active": True}
    r = api.call("PUT", f"/entries/{d['id']}/sheet", "tenant_admin", json=_full_sheet(dpa_registry_id=ajeno))
    assert r.status_code == 422


# ── parámetros no soportados de la ficha (069 enmienda T162–T165) ──────────────

def test_la_entrada_nace_sin_parametros_no_soportados(api):
    assert _create(api)["unsupported_params"] == []             # nada precargado por modelo


def test_alta_con_parametros_no_soportados_los_normaliza_y_los_devuelve(api):
    e = _create(api, unsupported_params=[" temperature ", "top_p", "temperature"])
    assert e["unsupported_params"] == ["temperature", "top_p"]
    assert api.call("GET", f"/entries/{e['id']}", "tenant_admin").json()["unsupported_params"] == ["temperature", "top_p"]


def test_el_admin_edita_y_vacia_la_lista(api):
    e = _create(api)
    r = api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json={"unsupported_params": ["temperature"]})
    assert r.status_code == 200 and r.json()["unsupported_params"] == ["temperature"]
    assert api.store.bumps, "el cambio sube la versión: el guard y la pasarela lo ven en segundos"
    r = api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json={"unsupported_params": None})
    assert r.json()["unsupported_params"] == []


def test_patch_sin_el_campo_no_toca_la_lista(api):
    e = _create(api, unsupported_params=["temperature"])
    r = api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json={"capability": "frontier"})
    assert r.json()["unsupported_params"] == ["temperature"]


@pytest.mark.parametrize("bad", ["temperature", [3], ["Temp"], ["model"], ["messages"], ["api_key"],
                                 ["input_cost_per_token"], ["output_cost_per_token"], ["timeout"], ["num_retries"],
                                 ["user_api_key_hash"]])
def test_lista_invalida_es_422_en_alta_y_en_edicion(api, bad):
    assert api.call("POST", "/entries", "tenant_admin", json=_entry(unsupported_params=bad)).status_code == 422
    e = _create(api, name="otra")
    assert api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json={"unsupported_params": bad}).status_code == 422


def test_solo_administracion_edita_la_lista(api):
    e = _create(api)
    for role in ("compliance_officer", "lectura"):
        r = api.call("PATCH", f"/entries/{e['id']}", role, json={"unsupported_params": ["temperature"]})
        assert r.status_code == 403


def test_el_cambio_queda_auditado_en_la_entrada(api):
    e = _create(api)
    api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json={"unsupported_params": ["temperature"]})
    with api.Session() as s:
        upd = [a for a in s.query(rm.RedirectConfigAudit) if (a.entity, a.action) == ("catalog_entry", "update")][-1]
    assert upd.before["unsupported_params"] == [] and upd.after["unsupported_params"] == ["temperature"]


def test_el_destino_de_la_pasarela_y_el_catalogo_servido_llevan_la_lista(api):
    from sentinel.catalog import store as cs
    e = _create(api, unsupported_params=["temperature"])
    with api.Session() as s:
        row = s.get(cm.CatalogEntry, uuid.UUID(e["id"]))
        assert cs.entry_to_destination(row, None, None)["unsupported_params"] == ["temperature"]


def test_el_catalogo_servido_al_motor_lleva_la_lista(api, monkeypatch):
    """`/internal/model-catalog` (lo que lee el guard de los clientes directos): sin credenciales y con la lista."""
    from sentinel.catalog.api import internal
    monkeypatch.setattr(internal, "SESSION_FACTORY", api.Session)
    monkeypatch.setattr(internal, "DPA_LOOKUP", lambda db, tenant, dpa_id: None)
    monkeypatch.setattr(internal, "TODAY", lambda: date(2026, 10, 1))
    marcada = _create(api, name="Con marca", unsupported_params=["temperature"])
    limpia = _create(api, name="Sin marca", credential={"new": {"name": "otra-key", "value": SECRET}})
    entries = internal.build(str(T1))["entries"]
    assert entries[marcada["public_id"]]["unsupported_params"] == ["temperature"]
    assert entries[limpia["public_id"]]["unsupported_params"] == []
    assert SECRET not in json.dumps(entries)
