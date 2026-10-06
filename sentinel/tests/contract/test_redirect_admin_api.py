"""API de administración `/api/v1/redirect/*` (T049/T061/T062/T067/T076) — roles y auditoría.

Montada con la costura S1 real (`mount_plugin_routers`, `PLUGIN_PACKAGES=sentinel.redirect.api`)
y los guardas de rol reales del backend (`require_role`); la sesión es SQLite en memoria (sin
Postgres ni Docker: la RLS la cubren los tests de migración). Corre con el venv del backend:

    cd sentinel/tests && ../../backend/.venv/bin/python -m pytest contract/test_redirect_admin_api.py
"""
import json
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

from sentinel.catalog import models as cm  # noqa: E402
from sentinel.redirect import models as m  # noqa: E402
from sentinel.redirect.api import admin  # noqa: E402

sys.path.insert(0, str(ROOT / "sentinel" / "tests"))
from redirect_fixtures import seed_entry  # noqa: E402

T1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
T2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
SECRET = "sk-secreto-del-destino-NO-DEBE-VOLVER"


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
    m.RedirectBase.metadata.create_all(engine)
    cm.CatalogBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    store = _Store()
    monkeypatch.setattr(admin, "SESSION_FACTORY", Session)
    monkeypatch.setattr(admin, "STORE", store)
    app = FastAPI()
    assert mount_plugin_routers(app, "sentinel.redirect.api") == 1
    who = {"user": None}
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    client = TestClient(app)

    def call(method, path, role=None, tenant=T1, **kw):
        who["user"] = _user(role, tenant) if role else None
        return client.request(method, "/api/v1/redirect" + path, **kw)

    def seed(**kw):
        """Destino = entrada del catálogo (069 E3): ya no se da de alta por `POST /redirect/destinations`."""
        kw.setdefault("credential", {"api_key": SECRET})
        with Session() as s:
            return seed_entry(s, **kw)

    return SimpleNamespace(call=call, Session=Session, store=store, seed=seed)


def _dest(**kw):
    """Cuerpo que mandaba el alta de la 068: hoy solo sirve para comprobar que responde 410."""
    body = {"name": "Qwen UE", "provider": "openai_compatible", "real_model": "qwen",
            "protocol_family": "openai_chat", "inference_jurisdiction": "de",
            "entity_jurisdiction": "DE", "api_base": "http://destino/v1",
            "credential": {"api_key": SECRET}, "context_window": 128000}
    body.update(kw)
    return body


def _audits(api):
    with api.Session() as s:
        return [(a.entity, a.action, a.before, a.after, a.actor_role)
                for a in s.query(m.RedirectConfigAudit).order_by(m.RedirectConfigAudit.at)]


# ── sesión y roles ────────────────────────────────────────────────────────────

def test_sin_sesion_es_401(api):
    assert api.call("GET", "/destinations").status_code == 401


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/destinations", _dest()),
    ("PUT", "/policy/tenant/*", {"state": "on"}),
    ("POST", "/published-models", {"face": "openai_generic", "public_id": "pro"}),
    ("POST", "/rules", {"family_tier": "sonnet", "targets": [str(uuid.uuid4())]}),
])
def test_cliente_y_dpo_no_escriben_config_de_tenant(api, method, path, body):
    for role in ("client", "compliance_officer"):
        assert api.call(method, path, role, json=body).status_code == 403, role






# ── ofertas, ids, reglas, política ───────────────────────────────────────────

def test_flujo_completo_y_vista_previa(api):
    inst = api.seed(level="installation", name="Compartido", offered_to=[T2], api_base="http://destino/v1")
    # sin oferta, el tenant no lo ve ni puede usarlo en reglas
    assert api.call("GET", "/destinations", "tenant_admin").json()["data"] == []
    with api.Session() as s:                           # el operador lo ofrece en Modelos
        s.add(cm.CatalogOffer(id=uuid.uuid4(), entry_id=uuid.UUID(inst["id"]), tenant_id=T1))
        s.commit()
    assert [d["id"] for d in api.call("GET", "/destinations", "tenant_admin").json()["data"]] == [inst["id"]]
    pub = api.call("POST", "/published-models", "tenant_admin",
                   json={"face": "openai_generic", "public_id": "pro"})
    assert pub.status_code == 201
    assert api.call("POST", "/published-models", "tenant_admin",
                    json={"face": "openai_generic", "public_id": "pro"}).status_code == 409
    assert api.call("POST", "/published-models", "tenant_admin",
                    json={"face": "openai_generic", "public_id": "rdx-x"}).status_code == 422
    rule = api.call("POST", "/rules", "tenant_admin",
                    json={"published_model_id": pub.json()["id"], "targets": [inst["id"]]})
    assert rule.status_code == 201, rule.text
    # un destino no ofrecido no entra en reglas de OTRO tenant
    assert api.call("POST", "/rules", "tenant_admin", tenant=uuid.uuid4(),
                    json={"family_tier": "sonnet", "targets": [inst["id"]]}).status_code == 422
    assert api.call("PUT", "/policy/tenant/*", "tenant_admin",
                    json={"state": "on", "reason": "piloto"}).json()["state"] == "on"
    assert api.call("PUT", "/policy/tenant/*", "tenant_admin", json={"state": "maybe"}).status_code == 422
    prev = api.call("POST", "/resolve-preview", "compliance_officer",
                    json={"face": "openai_generic", "public_id": "pro", "tenant_region": "eu"})
    assert prev.status_code == 200
    assert prev.json()["result"] == "resolved" and prev.json()["engine_model"] == "rdx-chatcompat/qwen"
    assert prev.json()["state"] == "on"
    entities = [(e, a) for e, a, *_ in _audits(api)]
    assert entities == [("published_model", "create"), ("rule", "create"), ("policy", "put")]
    # retirar la oferta (en Modelos) ⇒ la vista previa ya no resuelve
    with api.Session() as s:
        s.query(cm.CatalogOffer).filter(cm.CatalogOffer.tenant_id == T1).delete()
        s.commit()
    prev = api.call("POST", "/resolve-preview", "tenant_admin",
                    json={"face": "openai_generic", "public_id": "pro"})
    assert prev.json()["result"] == "unavailable"


def test_estrategia_por_costo_de_la_regla(api):
    caro = api.seed(name="Caro", real_model="grande", price={"input_per_mtok": 3, "output_per_mtok": 15})
    barato = api.seed(name="Barato", real_model="chico", price={"input_per_mtok": 0.3, "output_per_mtok": 1.2})
    pub = api.call("POST", "/published-models", "tenant_admin",
                   json={"face": "openai_generic", "public_id": "pro"}).json()
    body = {"published_model_id": pub["id"], "targets": [caro["id"], barato["id"]]}
    assert api.call("POST", "/rules", "tenant_admin", json={**body, "strategy": "gratis"}).status_code == 422
    rule = api.call("POST", "/rules", "tenant_admin", json=body)
    assert rule.status_code == 201 and rule.json()["strategy"] == "order"
    rid = rule.json()["id"]
    api.call("PUT", "/policy/tenant/*", "tenant_admin", json={"state": "on"})
    preview = {"face": "openai_generic", "public_id": "pro", "tenant_region": "eu"}
    prev = api.call("POST", "/resolve-preview", "tenant_admin", json=preview).json()
    assert prev["destination_id"] == caro["id"] and prev["strategy"] == "order"
    # estrategia inválida ⇒ 422; lectura no puede cambiarla
    assert api.call("PATCH", f"/rules/{rid}", "tenant_admin", json={"strategy": "gratis"}).status_code == 422
    assert api.call("PATCH", f"/rules/{rid}", "compliance_officer",
                    json={"strategy": "cheapest"}).status_code == 403
    r = api.call("PATCH", f"/rules/{rid}", "tenant_admin", json={"strategy": "cheapest"})
    assert r.status_code == 200 and r.json()["strategy"] == "cheapest"
    assert [x["strategy"] for x in api.call("GET", "/rules", "compliance_officer").json()["data"]] == ["cheapest"]
    prev = api.call("POST", "/resolve-preview", "tenant_admin", json=preview).json()
    assert prev["destination_id"] == barato["id"] and prev["strategy"] == "cheapest"
    assert prev["substitution_reason"] == "cost_ordering"
    upd = [a for a in _audits(api) if a[:2] == ("rule", "update")][-1]
    assert upd[2]["strategy"] == "order" and upd[3]["strategy"] == "cheapest"


def test_etiqueta_se_audita_como_label(api):
    pub = api.call("POST", "/published-models", "tenant_admin",
                   json={"face": "claude", "public_id": "claude-sonnet-4-5", "family_tier": "sonnet"}).json()
    r = api.call("PATCH", f"/published-models/{pub['id']}", "tenant_admin",
                 json={"label": "Sonnet corporativo", "label_mode": "custom"})
    assert r.status_code == 200
    assert _audits(api)[-1][:2] == ("label", "update")
    assert api.call("DELETE", f"/published-models/{pub['id']}", "tenant_admin").status_code == 204
    assert _audits(api)[-1][:2] == ("published_model", "delete")


# ── posturas (FR-014a) ───────────────────────────────────────────────────────

def test_posturas_reglas_de_rol(api):
    body = {"mode": "allowlist", "jurisdictions": ["eu"], "reason": "residencia UE"}
    r = api.call("POST", "/postures", "tenant_admin", json=body)          # agregar: sí
    assert r.status_code == 201 and r.json()["jurisdictions"] == ["EU"]
    assert r.json()["created_by_role"] == "tenant_admin"
    pid = r.json()["id"]
    assert api.call("PATCH", f"/postures/{pid}", "tenant_admin",
                    json={"mode": "off", "reason": "relajar"}).status_code == 403
    assert api.call("DELETE", f"/postures/{pid}", "tenant_admin",
                    json={"reason": "borrar"}).status_code == 403
    assert api.call("POST", "/postures", "tenant_admin",
                    json={**body, "accept_foreign_entity": True}).status_code == 403
    assert api.call("POST", "/postures", "compliance_officer",
                    json={**body, "reason": ""}).status_code == 422
    assert api.call("POST", "/postures", "tenant_admin",
                    json={"mode": "allowlist", "jurisdictions": [], "reason": "vacía"}).status_code == 422
    assert api.call("PATCH", f"/postures/{pid}", "compliance_officer",
                    json={"jurisdictions": ["DE"], "reason": "endurecer"}).json()["jurisdictions"] == ["DE"]
    lst = api.call("GET", "/postures", "compliance_officer").json()
    assert lst["effective_tenant_redirected"]["jurisdictions"] == ["DE"]
    assert api.call("DELETE", f"/postures/{pid}", "super_admin",
                    json={"reason": "fin del piloto"}).status_code == 200
    assert [(e, a) for e, a, *_ in _audits(api)] == [("posture", "create"), ("posture", "update"),
                                                     ("posture", "delete")]
    empty = api.call("GET", "/postures", "tenant_admin", params={"region": "latam_ar"}).json()
    assert empty["effective_tenant_redirected"] == {"mode": "allowlist",
                                                    "jurisdictions": ["AR", "LATAM"], "explicit": False}


# ── Tenant operador de la instalación (REDIRECT_OPERATOR_TENANT) ─────────────────────────
# En una instalación de un solo tenant no existe super_admin: el tenant_admin ES el operador.
# El operador del SERVIDOR lo declara por entorno; quien controla ese entorno ya controla las
# credenciales, así que no abre nada nuevo. Sin la variable: solo super_admin (como siempre).

def test_sin_variable_el_tenant_admin_no_opera_la_instalacion(api, monkeypatch):
    monkeypatch.delenv("REDIRECT_OPERATOR_TENANT", raising=False)
    assert api.call("GET", "/capabilities", role="tenant_admin").json() == {"operator": False}
    assert api.call("GET", "/capabilities", role="super_admin").json() == {"operator": True}


def test_el_tenant_operador_se_declara_por_entorno_y_otro_tenant_no(api, monkeypatch):
    monkeypatch.setenv("REDIRECT_OPERATOR_TENANT", str(T1))
    assert api.call("GET", "/capabilities", role="tenant_admin").json() == {"operator": True}
    assert api.call("GET", "/capabilities", role="tenant_admin", tenant=T2).json() == {"operator": False}






def test_el_operador_escribe_posturas_como_super_admin(api, monkeypatch):
    monkeypatch.setenv("REDIRECT_OPERATOR_TENANT", str(T1))
    r = api.call("POST", "/postures", role="tenant_admin",
                 json={"scope_type": "tenant", "scope_value": "*", "mode": "offregion_masked",
                       "accept_foreign_entity": True, "reason": "prueba del operador"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    r = api.call("DELETE", f"/postures/{pid}", role="tenant_admin", json={"reason": "limpieza"})
    assert r.status_code in (200, 204), r.text


def test_un_cliente_del_tenant_operador_no_gana_nada(api, monkeypatch):
    monkeypatch.setenv("REDIRECT_OPERATOR_TENANT", str(T1))
    assert api.call("GET", "/capabilities", role="client").status_code == 403

