"""E3 de la 069: los destinos de la redirección SON las entradas del catálogo (T179–T182).

`GET /redirect/destinations` lista el catálogo (activas, de texto, visibles para la organización), las reglas
validan sus destinos contra él, la vista previa resuelve una entrada con el mismo código del plano de datos y
los escritores de la 068 (`POST`/`PATCH`/`revoke`/`enable`/`offer`) responden 410 apuntando al catálogo.

Montada con la costura S1 real y SQLite en memoria con las dos metadatas (sin Postgres ni Docker):

    backend/.venv/bin/python -m pytest sentinel/tests/contract/test_redirect_destinos_catalogo.py
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
from sentinel.redirect import credentials  # noqa: E402
from sentinel.redirect import models as m  # noqa: E402
from sentinel.redirect.api import admin  # noqa: E402

sys.path.insert(0, str(ROOT / "sentinel" / "tests"))
from redirect_fixtures import seed_entry  # noqa: E402

T1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
T2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
SECRET = "sk-secreto-de-la-entrada-NO-DEBE-VOLVER"


class _Store:
    def __init__(self):
        self.bumps = []

    def bump(self, tenant=None):
        self.bumps.append(tenant)


def _build(monkeypatch, *, catalog_tables=True):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    m.RedirectBase.metadata.create_all(engine)
    if catalog_tables:
        cm.CatalogBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    store = _Store()
    monkeypatch.setattr(admin, "SESSION_FACTORY", Session)
    monkeypatch.setattr(admin, "STORE", store)
    monkeypatch.delenv("REDIRECT_OPERATOR_TENANT", raising=False)
    app = FastAPI()
    assert mount_plugin_routers(app, "sentinel.redirect.api") == 1
    who = {"user": None}
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    client = TestClient(app)

    def call(method, path, role=None, tenant=T1, **kw):
        who["user"] = (SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant, role=role, display_label=None)
                       if role else None)
        return client.request(method, "/api/v1/redirect" + path, **kw)

    def seed(**kw):
        with Session() as s:
            return seed_entry(s, **kw)

    return SimpleNamespace(call=call, Session=Session, store=store, seed=seed)


@pytest.fixture
def api(monkeypatch):
    return _build(monkeypatch)


@pytest.fixture
def api_sin_catalogo(monkeypatch):
    return _build(monkeypatch, catalog_tables=False)


def _ids(resp):
    assert resp.status_code == 200, resp.text
    return [d["id"] for d in resp.json()["data"]]


def _legacy_row(api, **kw):
    """Una fila que la 068 dejó en su tabla propia (ya no se escribe por la API)."""
    base = dict(id=uuid.uuid4(), level="tenant", tenant_id=T1, name="Fila vieja", provider="openai_compatible",
                real_model="viejo", protocol_family="openai_chat", api_base="http://viejo/v1",
                credential_encrypted=json.dumps({"api_key": "sk-viejo"}), provider_options={},
                capability_profile={}, status="active")
    base.update(kw)
    base["id"] = uuid.UUID(str(base["id"]))
    with api.Session() as s:
        s.add(m.RedirectDestination(**base))
        s.commit()
    return str(base["id"])


# ── (a) la lista sale del catálogo ───────────────────────────────────────────────────────────────

def test_la_lista_es_el_catalogo_activo_de_texto_visible_para_la_organizacion(api):
    sol = api.seed(name="GPT 6.1 Sol", provider="azure", real_model="gpt-6.1-sol", api_base="https://az/",
                   protocol_family="openai_chat", credential={"api_key": SECRET}, unsupported=["temperature"],
                   context_window=400000)
    luna = api.seed(name="GPT 6 Luna", credential={"api_key": SECRET})
    archivada = api.seed(name="Vieja", status="archived", credential={"api_key": SECRET})
    inactiva = api.seed(name="En pausa", status="inactive", credential={"api_key": SECRET})
    embeddings = api.seed(name="Embeddings", role="embeddings", credential={"api_key": SECRET})
    ajena = api.seed(name="De otra org", tenant=T2, credential={"api_key": SECRET})
    ofrecida = api.seed(name="De la instalación", level="installation", offered_to=[T1],
                        credential={"api_key": SECRET})
    a_todas = api.seed(name="Para todas", level="installation", offered_to=["*"], credential={"api_key": SECRET})
    sin_oferta = api.seed(name="Sin oferta", level="installation", credential={"api_key": SECRET})
    a_otra = api.seed(name="Solo otra org", level="installation", offered_to=[T2], credential={"api_key": SECRET})

    r = api.call("GET", "/destinations", "tenant_admin")
    assert r.status_code == 200, r.text
    ids = {d["id"] for d in r.json()["data"]}
    assert ids == {sol["id"], luna["id"], ofrecida["id"], a_todas["id"]}
    for oculta in (archivada, inactiva, embeddings, ajena, sin_oferta, a_otra):
        assert oculta["id"] not in ids, oculta
    # id = id de la entrada; modelo real, ventana, credencial y lista de parámetros salen de la entrada
    d = next(x for x in r.json()["data"] if x["id"] == sol["id"])
    assert (d["name"], d["provider"], d["real_model"], d["api_base"]) == (
        "GPT 6.1 Sol", "azure", "gpt-6.1-sol", "https://az/")
    assert d["context_window"] == 400000 and d["unsupported_params"] == ["temperature"]
    assert d["has_credential"] is True and d["status"] == "active" and d["public_id"] == sol["public_id"]
    assert SECRET not in r.text
    # otra organización ve lo suyo y lo ofrecido a ella
    assert set(_ids(api.call("GET", "/destinations", "tenant_admin", tenant=T2))) == {
        ajena["id"], a_todas["id"], a_otra["id"]}


def test_el_operador_ve_solo_lo_que_la_organizacion_puede_usar(api, monkeypatch):
    """La lista y la validación de reglas comparten fuente: lo que se muestra se puede elegir."""
    api.seed(name="Sin oferta", level="installation", credential={"api_key": SECRET})
    propia = api.seed(name="Propia", credential={"api_key": SECRET})
    assert _ids(api.call("GET", "/destinations", "super_admin")) == [propia["id"]]


def test_un_destino_bloqueado_por_defecto_se_lista_marcado(api):
    ds = api.seed(name="DS", provider="deepseek", api_base=None, blocked_by_default=True,
                  credential={"api_key": SECRET})
    d = api.call("GET", "/destinations", "tenant_admin").json()["data"][0]
    assert d["id"] == ds["id"] and d["blocked_by_default"] is True and d["enabled_at"] is None


def test_lectura_para_cumplimiento_y_nada_para_clientes(api):
    api.seed(credential={"api_key": SECRET})
    assert api.call("GET", "/destinations", "compliance_officer").status_code == 200
    assert api.call("GET", "/destinations", "client").status_code == 403
    assert api.call("GET", "/destinations").status_code == 401


# ── (b) reglas y vista previa con una entrada del catálogo ───────────────────────────────────────

def _flujo(api, destino, *, tier="opus", public_id="claude-opus-5-5"):
    pub = api.call("POST", "/published-models", "tenant_admin",
                   json={"face": "claude", "public_id": public_id, "family_tier": tier})
    assert pub.status_code == 201, pub.text
    rule = api.call("POST", "/rules", "tenant_admin",
                    json={"published_model_id": pub.json()["id"], "targets": [destino]})
    return pub.json(), rule


def test_regla_opus_hacia_una_entrada_del_catalogo_y_vista_previa(api):
    sol = api.seed(name="GPT 6.1 Sol", provider="azure", real_model="gpt-6.1-sol", api_base="https://az/",
                   credential={"api_key": SECRET}, unsupported=["temperature"])
    _, rule = _flujo(api, sol["id"])
    assert rule.status_code == 201, rule.text
    assert rule.json()["targets"] == [sol["id"]]
    assert api.call("PUT", "/policy/tenant/*", "tenant_admin", json={"state": "on"}).status_code == 200
    prev = api.call("POST", "/resolve-preview", "tenant_admin",
                    json={"face": "claude", "public_id": "claude-opus-5-5", "tenant_region": "eu"})
    assert prev.status_code == 200, prev.text
    body = prev.json()
    assert body["result"] == "resolved" and body["destination_id"] == sol["id"]
    assert body["destination_name"] == "GPT 6.1 Sol"
    assert body["engine_model"] == credentials.family_model("azure", "gpt-6.1-sol")
    assert SECRET not in prev.text


@pytest.mark.parametrize("motivo,kw", [
    ("archivada", {"status": "archived"}),
    ("inactiva", {"status": "inactive"}),
    ("de otro tipo", {"role": "embeddings"}),
    ("de otra organización", {"tenant": T2}),
    ("de instalación sin oferta", {"level": "installation"}),
])
def test_una_regla_no_puede_apuntar_a_lo_que_no_esta_en_la_lista(api, motivo, kw):
    ent = api.seed(credential={"api_key": SECRET}, **kw)
    _, rule = _flujo(api, ent["id"])
    assert rule.status_code == 422, motivo
    assert "destino no disponible" in rule.json()["detail"]


def test_una_regla_no_puede_apuntar_a_un_id_que_no_existe_en_el_catalogo(api):
    _, rule = _flujo(api, str(uuid.uuid4()))
    assert rule.status_code == 422


def test_cambiar_los_destinos_de_una_regla_se_valida_contra_el_catalogo(api):
    uno, dos = api.seed(name="Uno", credential={"api_key": SECRET}), api.seed(name="Dos", credential={"api_key": SECRET})
    pub, rule = _flujo(api, uno["id"])
    rid = rule.json()["id"]
    r = api.call("PATCH", f"/rules/{rid}", "tenant_admin", json={"targets": [dos["id"], uno["id"]]})
    assert r.status_code == 200 and r.json()["targets"] == [dos["id"], uno["id"]]
    assert api.call("PATCH", f"/rules/{rid}", "tenant_admin",
                    json={"targets": [str(uuid.uuid4())]}).status_code == 422


# ── (5) destino que ya no está: se reporta, no se rompe ──────────────────────────────────────────

def test_una_regla_cuyo_destino_se_archivo_lo_reporta_y_la_vista_previa_no_resuelve(api):
    ent = api.seed(name="Se va", credential={"api_key": SECRET})
    otro = api.seed(name="Se queda", credential={"api_key": SECRET})
    pub, rule = _flujo(api, ent["id"])
    assert api.call("PUT", "/policy/tenant/*", "tenant_admin", json={"state": "on"}).status_code == 200
    with api.Session() as s:                                   # el administrador la archiva en Modelos
        s.get(cm.CatalogEntry, uuid.UUID(ent["id"])).status = "archived"
        s.commit()
    rules = api.call("GET", "/rules", "tenant_admin")
    assert rules.status_code == 200
    warns = rules.json()["data"][0]["warnings"]
    assert warns == [{"code": "destination_unavailable", "destination_id": ent["id"]}]
    lst = api.call("GET", "/destinations", "tenant_admin")
    assert _ids(lst) == [otro["id"]]
    assert {"code": "destination_unavailable", "destination_id": ent["id"]} in lst.json()["warnings"]
    prev = api.call("POST", "/resolve-preview", "tenant_admin",
                    json={"face": "claude", "public_id": "claude-opus-5-5"})
    assert prev.status_code == 200
    assert prev.json()["result"] == "unavailable"
    assert prev.json()["skipped"] == [{"destination_id": ent["id"], "reason": "revoked"}]


def test_una_regla_con_un_id_sin_entrada_no_da_500(api):
    """Un id que quedó en la regla y ya no existe en el catálogo (p. ej. un destino de la 068 sin par)."""
    otro = api.seed(name="Otro", credential={"api_key": SECRET})
    huerfano = str(uuid.uuid4())
    pub = api.call("POST", "/published-models", "tenant_admin",
                   json={"face": "claude", "public_id": "claude-opus-5-5", "family_tier": "opus"}).json()
    with api.Session() as s:
        s.add(m.RedirectRule(id=uuid.uuid4(), tenant_id=T1, published_model_id=uuid.UUID(pub["id"]),
                             scope_type="tenant", scope_value="*", targets=[huerfano, otro["id"]],
                             strategy="order"))
        s.commit()
    api.call("PUT", "/policy/tenant/*", "tenant_admin", json={"state": "on"})
    rules = api.call("GET", "/rules", "tenant_admin")
    assert rules.status_code == 200
    assert rules.json()["data"][0]["warnings"] == [{"code": "destination_unavailable", "destination_id": huerfano}]
    prev = api.call("POST", "/resolve-preview", "tenant_admin",
                    json={"face": "claude", "public_id": "claude-opus-5-5", "tenant_region": "eu"})
    assert prev.status_code == 200 and prev.json()["destination_id"] == otro["id"]   # el siguiente sí sirve


def test_la_oferta_retirada_sigue_avisando_como_antes(api):
    inst = api.seed(name="Compartida", level="installation", offered_to=[T1], credential={"api_key": SECRET})
    _, rule = _flujo(api, inst["id"])
    assert rule.status_code == 201, rule.text
    with api.Session() as s:                                   # el operador retira la oferta en Modelos
        s.query(cm.CatalogOffer).delete()
        s.commit()
    warns = api.call("GET", "/rules", "tenant_admin").json()["data"][0]["warnings"]
    assert warns == [{"code": "offer_withdrawn", "destination_id": inst["id"]}]


# ── compatibilidad con la tabla propia de la 068 ─────────────────────────────────────────────────

def test_una_fila_vieja_con_el_mismo_id_que_su_entrada_no_rompe_nada(api):
    ent = api.seed(name="Qwen UE", real_model="qwen-catalogo", credential={"api_key": SECRET})
    _legacy_row(api, id=ent["id"], name="Qwen UE", real_model="qwen-viejo")
    r = api.call("GET", "/destinations", "tenant_admin")
    assert _ids(r) == [ent["id"]]
    assert r.json()["data"][0]["real_model"] == "qwen-catalogo"        # manda el catálogo
    _, rule = _flujo(api, ent["id"])
    assert rule.status_code == 201


def test_una_fila_vieja_sin_entrada_no_se_lista_ni_se_acepta_en_reglas(api):
    api.seed(name="Alguna", credential={"api_key": SECRET})             # el catálogo existe y no la tiene
    huerfana = _legacy_row(api)
    assert huerfana not in _ids(api.call("GET", "/destinations", "tenant_admin"))
    _, rule = _flujo(api, huerfana)
    assert rule.status_code == 422


def test_sin_las_tablas_del_catalogo_rige_la_tabla_de_la_068(api_sin_catalogo):
    """Migración del catálogo sin aplicar: la tabla propia es el respaldo y la API no se cae."""
    vieja = _legacy_row(api_sin_catalogo)
    r = api_sin_catalogo.call("GET", "/destinations", "tenant_admin")
    assert _ids(r) == [vieja]
    _, rule = _flujo(api_sin_catalogo, vieja)
    assert rule.status_code == 201, rule.text


# ── (d) los escritores de la 068 responden 410 y apuntan al catálogo ─────────────────────────────

CUERPO = {"name": "Nuevo", "provider": "openai_compatible", "real_model": "x", "protocol_family": "openai_chat",
          "api_base": "http://x/v1", "credential": {"api_key": "sk-x"}}


@pytest.mark.parametrize("method,path,body,destino", [
    ("POST", "/destinations", CUERPO, "/api/v1/catalog/entries"),
    ("PATCH", "/destinations/{id}", {"name": "otro"}, "/api/v1/catalog/entries/{id}"),
    ("POST", "/destinations/{id}/revoke", {"reason": "fuga"}, "/api/v1/catalog/entries/{id}/archive"),
    ("POST", "/destinations/{id}/enable", {"reason": "evaluación firmada"}, "/api/v1/catalog/entries/{id}/enable"),
    ("PUT", "/destinations/{id}/offer", {"tenants": ["*"]}, "/api/v1/catalog/entries/{id}/offers"),
])
def test_los_escritores_de_destinos_responden_410_y_apuntan_al_catalogo(api, method, path, body, destino):
    ent = api.seed(credential={"api_key": SECRET})
    r = api.call(method, path.format(id=ent["id"]), "super_admin", json=body)
    assert r.status_code == 410, r.text
    detail = r.json()["detail"]
    assert destino.format(id=ent["id"]) in detail and "Modelos" in detail
    with api.Session() as s:                          # y no escribieron nada: ni tabla propia ni catálogo
        assert s.query(m.RedirectDestination).count() == 0
        assert s.query(cm.CatalogEntry).count() == 1
        assert s.query(m.RedirectConfigAudit).count() == 0
    assert api.store.bumps == []


def test_el_410_no_se_salta_con_un_rol_que_no_escribe(api):
    """Primero manda el rol: un cliente sigue recibiendo 403, no una pista sobre el catálogo."""
    assert api.call("POST", "/destinations", "client", json=CUERPO).status_code == 403
    assert api.call("POST", "/destinations", json=CUERPO).status_code == 401
    assert api.call("POST", "/destinations", "tenant_admin", json=CUERPO).status_code == 410
