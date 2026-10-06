"""Paridad del semáforo entre la API de administración y `/internal/model-catalog` (069 T020; FR-003a),
más el contrato del canal interno (T032): sin credenciales, aislamiento por organización y rechazo
sin el secreto interno. (La paridad con el bloqueo de residencia de proyectos se suma con T034.)
"""
import sys
import uuid
from datetime import date
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
from sentinel.catalog.api import admin, internal  # noqa: E402
from sentinel.redirect import models as rm  # noqa: E402

T1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
T2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
SECRET_VALUE = "sk-secreto-NO-DEBE-SALIR"
INTERNAL = "interno-compartido"


class _Version:
    def __init__(self):
        self.n = 0

    def bump(self, tenant=None):
        self.n += 1

    def current(self, tenant):
        return self.n


@pytest.fixture
def api(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    cm.CatalogBase.metadata.create_all(engine)
    rm.RedirectBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    ver, dpas = _Version(), {}
    for mod in (admin, internal):
        monkeypatch.setattr(mod, "SESSION_FACTORY", Session)
        monkeypatch.setattr(mod, "DPA_LOOKUP", lambda db, tenant, dpa_id: dpas.get(str(dpa_id)))
        monkeypatch.setattr(mod, "TODAY", lambda: date(2026, 10, 1))
    monkeypatch.setattr(admin, "ENCRYPT", lambda s: "cifrado:" + s[::-1])
    monkeypatch.setattr(admin, "DECRYPT", lambda b: b[len("cifrado:"):][::-1])
    monkeypatch.setattr(internal, "DECRYPT", lambda b: b[len("cifrado:"):][::-1])
    monkeypatch.setattr(admin, "STORE", ver)
    monkeypatch.setattr(internal, "VERSION", ver)
    monkeypatch.setenv("SENTINEL_ENGINE_MASTER_KEY", INTERNAL)
    monkeypatch.setenv("CATALOG_DIRECT_ENABLED", "1")     # la ruta de la credencial solo existe con la ruta directa (057 T090)
    app = FastAPI()
    assert mount_plugin_routers(app, "sentinel.catalog.api") == 6      # admin + interno
    who = {"user": None}
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    client = TestClient(app)

    def admin_call(method, path, role, tenant=T1, **kw):
        who["user"] = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant, role=role, display_label=None)
        return client.request(method, "/api/v1/catalog" + path, **kw)

    def catalog(tenant=T1, secret=INTERNAL):
        h = {"X-Sentinel-Internal": secret} if secret is not None else {}
        return client.get(f"/api/v1/internal/model-catalog?tenant={tenant}", headers=h)

    return SimpleNamespace(admin=admin_call, catalog=catalog, dpas=dpas, Session=Session, client=client)


def _mk(api, name, tenant=T1, role="tenant_admin", **kw):
    body = {"level": "tenant", "name": name, "provider": "deepseek", "real_model": "m-" + name,
            "protocol_family": "openai_chat",
            "credential": {"new": {"name": "k-" + name, "value": SECRET_VALUE}}}
    body.update(kw)
    r = api.admin("POST", "/entries", role, tenant=tenant, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _sheet(api, entry, role="compliance_officer", tenant=T1, **kw):
    s = {"inference_jurisdiction": "EU", "logs_jurisdiction": "EU", "trains_on_data": False,
         "transfer_mechanism": "n/a"}
    s.update(kw)
    r = api.admin("PUT", f"/entries/{entry['id']}/sheet", role, tenant=tenant, json=s)
    assert r.status_code == 200, r.text


# ── seguridad del canal ───────────────────────────────────────────────────────────

def test_sin_el_secreto_interno_no_se_responde(api):
    assert api.catalog(secret=None).status_code in (401, 403, 404)
    assert api.catalog(secret="otro").status_code in (401, 403, 404)


# ── contenido ──────────────────────────────────────────────────────────────────────

def test_el_catalogo_interno_va_por_id_publico_y_nunca_lleva_credenciales(api):
    e = _mk(api, "DS Uno")
    body = api.catalog().json()
    assert body["version"]
    item = body["entries"]["ds-uno"]
    assert item["entry_id"] == e["id"] and item["provider"] == "deepseek" and item["real_model"] == "m-DS Uno"
    assert item["protocol_family"] == "openai_chat" and item["semaforo"]["estado"] == "unclassified"
    blob = api.catalog().text
    for prohibido in (SECRET_VALUE, "ciphertext", "fingerprint", "cifrado:", "credential_id", "env_name"):
        assert prohibido not in blob


def test_el_catalogo_interno_lleva_limites_base_y_tipo_para_el_guard(api):
    cl = _mk(api, "Con Limites", limits={"timeout": 20, "num_retries": 1, "rpm": 30}, base_model="base-x")
    assert api.admin("PATCH", f"/entries/{cl['id']}", "tenant_admin", json={"role": "embeddings"}).status_code == 200
    _mk(api, "Sin Limites")
    e = api.catalog().json()["entries"]
    assert e["con-limites"]["limits"] == {"timeout": 20, "num_retries": 1, "rpm": 30}
    assert e["con-limites"]["base_model"] == "base-x" and e["con-limites"]["role"] == "embeddings"
    assert e["sin-limites"]["limits"] == {} and e["sin-limites"]["base_model"] is None
    assert e["sin-limites"]["role"] == "text"


def test_paridad_semaforo_api_e_interno_en_todos_los_estados(api):
    ok = _mk(api, "Ok")
    d1, d2 = str(uuid.uuid4()), str(uuid.uuid4())
    api.dpas[d1] = {"expiration_date": date(2027, 1, 1), "processing_region": "EU", "is_active": True}
    api.dpas[d2] = {"expiration_date": date(2026, 9, 30), "processing_region": "EU", "is_active": True}
    _sheet(api, ok, dpa_registry_id=d1)
    venc = _mk(api, "Vencido")
    _sheet(api, venc, dpa_registry_id=d2)
    std = _mk(api, "Std")
    _sheet(api, std, inference_jurisdiction="US")
    _mk(api, "Sin clasificar")
    local = _mk(api, "Local", provider="ollama", api_base="http://ollama:11434", credential=None)
    _sheet(api, local, inference_jurisdiction="local", logs_jurisdiction="local", trains_on_data=False)
    via_api = {e["public_id"]: e["semaforo"] for e in api.admin("GET", "/entries", "tenant_admin").json()["data"]}
    via_int = {k: v["semaforo"] for k, v in api.catalog().json()["entries"].items()}
    assert via_api == via_int
    assert {s["estado"] for s in via_int.values()} == {"eu_ok", "standard", "unclassified"}
    assert via_int["vencido"]["motivos"] == ["dpa_vencido"] and via_int["local"]["motivos"] == ["local"]


# ── aislamiento y filtros ──────────────────────────────────────────────────────────

def test_una_organizacion_no_ve_las_entradas_de_otra(api):
    _mk(api, "Mio")
    _mk(api, "Ajeno", tenant=T2)
    assert set(api.catalog(T1).json()["entries"]) == {"mio"}
    assert set(api.catalog(T2).json()["entries"]) == {"ajeno"}


def test_las_de_instalacion_solo_si_se_ofrecen(api):
    inst = _mk(api, "Inst", level="installation", role="super_admin")
    assert api.catalog(T2).json()["entries"] == {}
    api.admin("PUT", f"/entries/{inst['id']}/offers", "super_admin", json={"tenants": [str(T2)]})
    assert set(api.catalog(T2).json()["entries"]) == {"inst"}
    assert api.catalog(T1).json()["entries"] == {}


def test_inactivas_archivadas_y_sin_credencial_no_se_sirven(api):
    a = _mk(api, "Activa")
    b = _mk(api, "Apagada")
    c = _mk(api, "Archivada")
    api.admin("PATCH", f"/entries/{b['id']}", "tenant_admin", json={"status": "inactive"})
    api.admin("POST", f"/entries/{c['id']}/archive", "tenant_admin", json={"reason": "obsoleta"})
    assert set(api.catalog().json()["entries"]) == {"activa"} and a


def test_modelo_local_sin_credencial_si_se_sirve(api):
    _mk(api, "Local", provider="ollama", api_base="http://ollama:11434", credential=None)
    assert "local" in api.catalog().json()["entries"]


def test_la_propia_gana_ante_una_ofrecida_con_el_mismo_id(api):
    inst = _mk(api, "Compartido", level="installation", role="super_admin", real_model="de-instalacion")
    api.admin("PUT", f"/entries/{inst['id']}/offers", "super_admin", json={"tenants": [str(T1)]})
    mine = _mk(api, "Compartido", real_model="propio", credential={"new": {"name": "otra", "value": "x"}})
    assert api.catalog().json()["entries"]["compartido"]["entry_id"] == mine["id"]


def test_la_version_cambia_con_cada_escritura(api):
    v0 = api.catalog().json()["version"]
    _mk(api, "Uno")
    assert api.catalog().json()["version"] != v0


def test_tenant_malformado_es_422(api):
    r = api.catalog(tenant="no-es-uuid")
    assert r.status_code == 422


# ── canal de credencial para el guard (069 T033, D2) y interruptor de clientes directos ──────

def _cred_call(api, tenant, entry_id, secret=INTERNAL):
    h = {"X-Sentinel-Internal": secret} if secret is not None else {}
    return api.client.get(f"/api/v1/internal/model-credential?tenant={tenant}&entry_id={entry_id}", headers=h)


def test_el_catalogo_interno_dice_si_los_clientes_directos_estan_habilitados(api, monkeypatch):
    monkeypatch.delenv("CATALOG_DIRECT_ENABLED", raising=False)
    assert api.catalog().json()["direct"] is False          # apagado por defecto
    monkeypatch.setenv("CATALOG_DIRECT_ENABLED", "1")
    assert api.catalog().json()["direct"] is True


def test_la_credencial_se_entrega_solo_con_el_secreto_interno_y_sin_cache(api):
    e = _mk(api, "DS Uno")
    assert _cred_call(api, T1, e["id"], secret=None).status_code == 404
    assert _cred_call(api, T1, e["id"], secret="otro").status_code == 404
    r = _cred_call(api, T1, e["id"])
    assert r.status_code == 200 and r.json() == {"credential": {"api_key": SECRET_VALUE}}
    assert "no-store" in r.headers["cache-control"]


def test_la_credencial_respeta_el_aislamiento_y_lo_que_se_sirve(api):
    mio = _mk(api, "Mio")
    ajeno = _mk(api, "Ajeno", tenant=T2)
    assert _cred_call(api, T1, ajeno["id"]).status_code == 404            # de otra organización
    api.admin("PATCH", f"/entries/{mio['id']}", "tenant_admin", json={"status": "inactive"})
    assert _cred_call(api, T1, mio["id"]).status_code == 404              # apagada: no se sirve
    assert _cred_call(api, T1, uuid.uuid4()).status_code == 404


def test_modelo_sin_credencial_devuelve_credencial_vacia(api):
    e = _mk(api, "Local", provider="ollama", api_base="http://ollama:11434", credential=None)
    assert _cred_call(api, T1, e["id"]).json() == {"credential": {}}


# ── la residencia de proyectos de la base usa el MISMO semáforo (T034, FR-003a) ───────────

@pytest.mark.skip(reason='Pieza de la base de Sentinel (src.services.residency_heuristic, 069 T034) que Eleia no trae; la paridad del semaforo con la region la cubre T-E (T063). 057 T017')
def test_el_resolutor_de_residencia_da_el_mismo_semaforo_que_la_api(api):
    from src.services import residency_heuristic as rh
    ok = _mk(api, "Ok")
    d = str(uuid.uuid4())
    api.dpas[d] = {"expiration_date": date(2027, 1, 1), "processing_region": "EU", "is_active": True}
    _sheet(api, ok, dpa_registry_id=d)
    _mk(api, "Sin clasificar")
    try:
        rh.register_semaforo_resolver(internal.semaforo_for)
        cfg = {"model_list": []}
        assert rh.decide("ok", tenant_id=str(T1), config=cfg).source == "semaforo"
        assert rh.decide("ok", tenant_id=str(T1), config=cfg).allowed
        via_api = {e["public_id"]: e["semaforo"] for e in api.admin("GET", "/entries", "tenant_admin").json()["data"]}
        assert internal.semaforo_for(str(T1), "ok") == via_api["ok"]
        assert internal.semaforo_for(str(T1), "sin-clasificar")["estado"] == "unclassified"
        assert internal.semaforo_for(str(T1), "no-existe") is None
        assert rh.decide("ok", tenant_id=str(T2), config=cfg).source != "semaforo"   # otra organización: no la ve
    finally:
        rh.register_semaforo_resolver(None)
