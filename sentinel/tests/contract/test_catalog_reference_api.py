"""Alta guiada y campos nuevos de la entrada (069 T123/T125/T126/T127; contracts/admin-modelos.md).

Mismo montaje que `test_catalog_api.py` (costura S1 real, roles reales, SQLite) más el motor simulado:
`REFERENCE` apunta a un cliente de listas con `fetch` falso, sin red.
"""
import json
import sys
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
pytest.importorskip("src.auth.rbac", reason="requiere el venv del backend")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from src.auth.session import get_current_user  # noqa: E402
from src.plugins import mount_plugin_routers  # noqa: E402

from sentinel.catalog import models as cm  # noqa: E402
from sentinel.catalog import reference as ref  # noqa: E402
from sentinel.catalog.api import admin  # noqa: E402
from sentinel.catalog.api import reference as refapi  # noqa: E402
from sentinel.redirect import models as rm  # noqa: E402
from test_catalog_reference import DOCS, Clock, Fake  # noqa: E402

T1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
SECRET = "sk-secreto-del-proveedor-NO-DEBE-VOLVER"
SRC = "referencia del motor"


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
    store, fake = _Store(), Fake()
    monkeypatch.setattr(admin, "SESSION_FACTORY", Session)
    monkeypatch.setattr(admin, "ENCRYPT", lambda s: "cifrado:" + s[::-1])
    monkeypatch.setattr(admin, "DECRYPT", lambda b: b[len("cifrado:"):][::-1])
    monkeypatch.setattr(admin, "STORE", store)
    monkeypatch.setattr(admin, "DPA_LOOKUP", lambda db, tenant, dpa_id: None)
    monkeypatch.setattr(admin, "TODAY", lambda: date(2026, 10, 1))
    monkeypatch.setattr(refapi, "REFERENCE", ref.Reference(fetch=fake, clock=Clock()))
    app = FastAPI()
    assert mount_plugin_routers(app, "sentinel.catalog.api") == 6
    who = {"user": None}
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    client = TestClient(app)

    def call(method, path, role=None, tenant=T1, **kw):
        who["user"] = _user(role, tenant) if role else None
        return client.request(method, "/api/v1/catalog" + path, **kw)

    return SimpleNamespace(call=call, Session=Session, store=store, fake=fake)


def _bulk(**kw):
    body = {"provider": "openai", "credential": {"new": {"name": "oa", "value": SECRET}},
            "models": [{"real_model": "gpt-4o", "accept_suggestion": True}]}
    body.update(kw)
    return body


def _entry(**kw):
    body = {"level": "tenant", "name": "GLM", "provider": "zai", "real_model": "glm-4.6",
            "protocol_family": "openai_chat", "credential": {"new": {"name": "z", "value": SECRET}}}
    body.update(kw)
    return body


def _post(api, **kw):
    return api.call("POST", "/entries", "tenant_admin", json=_entry(**kw))


# ── /providers y /providers/{p}/models ────────────────────────────────────────

@pytest.mark.parametrize("role", ["tenant_admin", "compliance_officer", "lectura"])
def test_providers_lo_leen_admin_cumplimiento_y_lectura(api, role):
    r = api.call("GET", "/providers", role)
    assert r.status_code == 200
    j = r.json()
    assert j["available"] is True and j["fetched_at"]
    p = next(x for x in j["data"] if x["provider"] == "openai")
    assert p["supported"] is True and p["example_model"] == "gpt-4o"
    assert p["credential_fields"][0]["key"] == "api_key"
    c = next(x for x in j["data"] if x["provider"] == "cohere")
    assert c["supported"] is False and c["reason"]


def test_providers_sin_sesion_o_cliente(api):
    assert api.call("GET", "/providers").status_code == 401
    assert api.call("GET", "/providers", "client").status_code == 403


def test_motor_caido_providers_available_false_y_alta_manual(api):
    api.fake.down = True
    j = api.call("GET", "/providers", "tenant_admin").json()
    assert j["available"] is False and j["data"]
    m = api.call("GET", "/providers/openai/models", "tenant_admin")
    assert m.status_code == 200 and m.json()["available"] is False and m.json()["data"] == []
    assert _post(api).status_code == 201                               # el alta manual sigue funcionando


def test_modelos_del_proveedor_con_busqueda_y_paginado(api):
    j = api.call("GET", "/providers/openai/models", "lectura", params={"q": "gpt", "limit": 5}).json()
    assert j["total"] == 1 and j["data"][0]["real_model"] == "gpt-4o"
    assert j["data"][0]["price"]["input"] == 2.5e-6 and j["data"][0]["features"]["images"] is True
    j = api.call("GET", "/providers/openai/models", "lectura", params={"limit": 2, "offset": 2}).json()
    assert [m["real_model"] for m in j["data"]] == ["text-embedding-3-small", "whisper-1"]
    assert api.call("GET", "/providers/openai/models", "lectura", params={"limit": 0}).status_code == 422


def test_proveedor_desconocido_en_modelos_es_404(api):
    assert api.call("GET", "/providers/marte/models", "lectura").status_code == 404


# ── /reference/refresh ────────────────────────────────────────────────────────

def test_refresh_solo_admin_y_vuelve_a_leer(api):
    assert api.call("POST", "/reference/refresh", "compliance_officer").status_code == 403
    api.call("GET", "/providers", "tenant_admin")
    n = len(api.fake.calls)
    r = api.call("POST", "/reference/refresh", "tenant_admin")
    assert r.status_code == 200 and r.json()["available"] is True and len(api.fake.calls) == n + 3
    api.fake.down = True
    r = api.call("POST", "/reference/refresh", "tenant_admin")
    assert r.status_code == 200 and r.json()["available"] is True and r.json()["stale"] is True


# ── /entries/bulk ─────────────────────────────────────────────────────────────

def test_bulk_solo_admin(api):
    for role in ("compliance_officer", "lectura", "client"):
        assert api.call("POST", "/entries/bulk", role, json=_bulk()).status_code == 403


def test_bulk_crea_con_sugerencia_fuente_y_fecha(api):
    r = api.call("POST", "/entries/bulk", "tenant_admin", json=_bulk())
    assert r.status_code == 207, r.text
    j = r.json()
    assert j["created"] == 1 and j["failed"] == 0
    res = j["data"][0]
    assert res["real_model"] == "gpt-4o" and res["status"] == 201
    e = res["entry"]
    assert e["name"] == "gpt-4o" and e["public_id"] == "gpt-4o" and e["provider"] == "openai"
    assert e["context_window"] == 128000 and e["max_output"] == 16384 and e["role"] == "text"
    assert e["price"] == {"input": 2.5e-6, "output": 1e-5, "cache_read": 1.25e-6, "cache_write": None,
                          "tiers": None, "source": SRC, "at": "2026-10-01"}
    assert e["features"] == {"images": True, "documents_pdf": True, "tools": True, "cache_control": True}
    assert e["semaforo"]["estado"] == "unclassified" and SECRET not in r.text
    assert api.store.bumps == [str(T1)]


def test_bulk_una_credencial_para_varios_modelos_y_207_parcial(api):
    body = _bulk(models=[
        {"real_model": "gpt-4o", "accept_suggestion": True},
        {"real_model": "text-embedding-3-small", "name": "Embeddings chicos", "public_id": "emb-s",
         "accept_suggestion": True},
        {"real_model": "no-esta-en-la-lista", "accept_suggestion": True},
        {"real_model": "gpt-4o", "accept_suggestion": False},                    # mismo nombre ⇒ 409
    ])
    r = api.call("POST", "/entries/bulk", "tenant_admin", json=body)
    assert r.status_code == 207
    j = r.json()
    assert [x["status"] for x in j["data"]] == [201, 201, 422, 409] and j["created"] == 2 and j["failed"] == 2
    assert j["data"][1]["entry"]["role"] == "embeddings" and j["data"][1]["entry"]["public_id"] == "emb-s"
    assert all("error" in x and "entry" not in x for x in j["data"][2:])
    with api.Session() as s:
        assert s.query(cm.Credential).count() == 1                               # una sola, compartida
        assert s.query(cm.CatalogEntry).count() == 2
        creds = {e.credential_id for e in s.query(cm.CatalogEntry)}
        assert len(creds) == 1


def test_bulk_la_sugerencia_no_pisa_lo_que_el_cuerpo_trae(api):
    body = _bulk(models=[{"real_model": "gpt-4o", "accept_suggestion": True, "price_input": 9e-6,
                          "context_window": 1000, "features": {"images": False}}])
    e = api.call("POST", "/entries/bulk", "tenant_admin", json=body).json()["data"][0]["entry"]
    assert e["price"]["input"] == 9e-6 and e["price"]["output"] == 1e-5      # lo explícito gana; el resto se sugiere
    assert e["context_window"] == 1000 and e["max_output"] == 16384
    assert e["features"]["images"] is False and e["features"]["tools"] is True
    assert e["price"]["source"] == SRC


def test_bulk_sin_aceptar_la_sugerencia_no_trae_nada_del_motor(api):
    body = _bulk(models=[{"real_model": "gpt-4o", "accept_suggestion": False}])
    e = api.call("POST", "/entries/bulk", "tenant_admin", json=body).json()["data"][0]["entry"]
    assert e["context_window"] is None and e["price"]["input"] is None and e["price"]["source"] is None
    assert e["features"] == {} and e["price"]["at"] is None


def test_bulk_precios_todos_explicitos_no_dicen_referencia_del_motor(api):
    body = _bulk(models=[{"real_model": "gpt-4o", "accept_suggestion": True, "price_input": 1e-6,
                          "price_output": 2e-6, "price_cache_read": 1e-7, "price_cache_write": 1e-6}])
    e = api.call("POST", "/entries/bulk", "tenant_admin", json=body).json()["data"][0]["entry"]
    assert e["price"]["input"] == 1e-6 and e["price"]["cache_read"] == 1e-7 and e["price"]["source"] != SRC


def test_bulk_con_el_motor_caido_y_sugerencia_pedida_falla_ese_modelo(api):
    api.fake.down = True
    j = api.call("POST", "/entries/bulk", "tenant_admin", json=_bulk()).json()
    assert j["data"][0]["status"] == 422 and "referencia" in j["data"][0]["error"]
    j = api.call("POST", "/entries/bulk", "tenant_admin", json=_bulk(
        models=[{"real_model": "gpt-4o", "accept_suggestion": False}])).json()
    assert j["data"][0]["status"] == 201


def test_bulk_credencial_existente_y_validaciones_de_toda_la_pedida(api):
    first = api.call("POST", "/entries/bulk", "tenant_admin", json=_bulk()).json()["data"][0]["entry"]
    body = _bulk(credential={"id": first["credential"]["id"]},
                 models=[{"real_model": "whisper-1", "accept_suggestion": True}])
    j = api.call("POST", "/entries/bulk", "tenant_admin", json=body).json()
    assert j["data"][0]["entry"]["role"] == "audio"
    assert api.call("POST", "/entries/bulk", "tenant_admin", json=_bulk(provider="marte")).status_code == 422
    assert api.call("POST", "/entries/bulk", "tenant_admin", json=_bulk(models=[])).status_code == 422
    assert api.call("POST", "/entries/bulk", "tenant_admin", json=_bulk(credential=None)).status_code == 422
    assert api.call("POST", "/entries/bulk", "tenant_admin", json=_bulk(
        provider="azure", credential={"new": {"name": "az", "value": {"api_key": "x", "api_version": "v"}}})
    ).status_code == 422                                                          # azure sin api_base
    assert api.call("POST", "/entries/bulk", "tenant_admin", json=_bulk(campo_raro=1)).status_code == 422


def test_bulk_nivel_instalacion_y_env_ref_son_del_operador(api):
    body = _bulk(level="installation", credential={"env_ref": "REDIRECT_CRED_OA"})
    assert api.call("POST", "/entries/bulk", "tenant_admin", json=body).status_code == 403
    r = api.call("POST", "/entries/bulk", "super_admin", json=body)
    assert r.status_code == 207 and r.json()["data"][0]["entry"]["level"] == "installation"
    assert api.store.bumps[-1] is None


def test_bulk_fila_fallida_no_deja_credencial_huerfana_ni_entrada_a_medias(api):
    body = _bulk(provider="bedrock", credential={"new": {"name": "b", "value": "sin-forma"}})
    assert api.call("POST", "/entries/bulk", "tenant_admin", json=body).status_code == 422
    with api.Session() as s:
        assert s.query(cm.Credential).count() == 0 and s.query(cm.CatalogEntry).count() == 0


# ── campos nuevos de la entrada ───────────────────────────────────────────────

def test_alta_con_campos_nuevos_y_vista(api):
    r = _post(api, limits={"rpm": 60, "timeout": 30, "num_retries": 2}, base_model="glm-4.6-base",
              advanced={"max_tokens": 2048, "extra_headers": {"X-Equipo": "datos"}},
              price_input=1e-6, price_output=2e-6, price_cache_read=1e-7, price_cache_write=1.2e-6,
              price_tiers=[{"up_to_tokens": 200000, "input": 1e-6}, {"input": 2e-6}], role="rerank")
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["limits"] == {"rpm": 60, "timeout": 30, "num_retries": 2} and d["base_model"] == "glm-4.6-base"
    assert d["advanced"]["max_tokens"] == 2048 and d["role"] == "rerank"
    assert d["price"]["cache_read"] == 1e-7 and d["price"]["cache_write"] == 1.2e-6
    assert d["price"]["tiers"] == [{"up_to_tokens": 200000, "input": 1e-6}, {"input": 2e-6}]
    assert d["price"]["at"] == "2026-10-01"
    base = _post(api, name="otro", credential={"new": {"name": "z2", "value": "x"}}).json()
    assert base["limits"] == {} and base["advanced"] == {} and base["base_model"] is None
    assert base["price"]["cache_read"] is None and base["price"]["tiers"] is None


@pytest.mark.parametrize("extra", [
    {"limits": {"qps": 3}}, {"limits": {"rpm": -2}}, {"limits": {"rpm": "x"}},
    {"advanced": {"top_p": 1}}, {"advanced": {"organization": "o"}},
    {"advanced": {"extra_headers": {"Authorization": "Bearer abc"}}},
    {"advanced": {"extra_headers": {"X-Algo": "sk-abcdefghijkl1234"}}},
    {"price_tiers": [{"foo": 1}]}, {"role": "video"}, {"price_cache_read": -1},
])
def test_valores_invalidos_son_422_y_no_repiten_el_valor(api, extra):
    r = _post(api, **extra)
    assert r.status_code == 422
    assert "sk-abcdefghijkl1234" not in r.text


def test_patch_de_los_campos_nuevos(api):
    d = _post(api).json()
    r = api.call("PATCH", f"/entries/{d['id']}", "tenant_admin",
                 json={"limits": {"timeout": 10}, "advanced": {"temperature": 0.1}, "base_model": "b",
                       "price_cache_read": 5e-8, "role": "image"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["limits"] == {"timeout": 10} and j["advanced"] == {"temperature": 0.1} and j["role"] == "image"
    assert j["price"]["cache_read"] == 5e-8 and j["price"]["at"] == "2026-10-01"
    assert api.call("PATCH", f"/entries/{d['id']}", "tenant_admin",
                    json={"advanced": {"extra_headers": {"x-api-key": "z"}}}).status_code == 422
    assert api.call("PATCH", f"/entries/{d['id']}", "tenant_admin", json={"limits": {"x": 1}}).status_code == 422


# ── región UE ─────────────────────────────────────────────────────────────────

def _sheet(api, entry_id, **kw):
    s = {"inference_jurisdiction": "unknown"} | kw
    r = api.call("PUT", f"/entries/{entry_id}/sheet", "compliance_officer", json=s)
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("inference,entity,expected", [
    ("EU", None, True), ("DE", None, True), ("ES", "US", True), ("US", "DE", False), ("LATAM", None, False),
    ("AR", None, False), ("unknown", None, None), ("local", None, None), ("local", "FR", True),
    ("local", "US", None),
])
def test_region_ue_derivada_de_la_jurisdiccion_de_inferencia(api, inference, entity, expected):
    d = _post(api).json()
    assert d["region_ue"] is None                                           # nace sin clasificar
    _sheet(api, d["id"], inference_jurisdiction=inference, entity_jurisdiction=entity)
    assert api.call("GET", f"/entries/{d['id']}", "lectura").json()["region_ue"] is expected


def test_filtro_region_ue_en_la_lista(api):
    ids = {}
    for i, inf in enumerate(("DE", "US", "unknown")):
        ids[inf] = _post(api, name=f"m{i}", credential={"new": {"name": f"c{i}", "value": "x"}}).json()["id"]
        _sheet(api, ids[inf], inference_jurisdiction=inf)

    def names(**p):
        return sorted(e["name"] for e in api.call("GET", "/entries", "lectura", params=p).json()["data"])

    assert names() == ["m0", "m1", "m2"]
    assert names(region_ue="true") == ["m0"]
    assert names(region_ue="false") == ["m1"]                                # «desconocida» no es «no»


# ── alta de un destino OpenRouter desde «Dar de alta modelos» (057 R40; Kimi K3) ─────────────────

KIMI_K3 = "moonshotai/kimi-k3"           # id real en la lista pública de OpenRouter (verificado el 2026-10-07)


def _bulk_openrouter(**kw):
    body = {"provider": "openrouter", "credential": {"new": {"name": "or", "value": SECRET}},
            "models": [{"real_model": KIMI_K3, "name": "Kimi K3", "context_window": 1048576, "max_output": 943718,
                        "price_input": 0.62e-6, "price_output": 15e-6, "features": {"images": True, "tools": True}}]}
    body.update(kw)
    return body


def test_bulk_openrouter_sin_lista_de_proveedores_se_rechaza_por_modelo_con_el_motivo(api):
    r = api.call("POST", "/entries/bulk", "tenant_admin", json=_bulk_openrouter())
    assert r.status_code == 207 and r.json()["created"] == 0
    assert r.json()["data"][0]["status"] == 422 and "providers_allowlist" in r.json()["data"][0]["error"]


def test_bulk_openrouter_con_proveedores_permitidos_da_de_alta_kimi_k3(api):
    body = _bulk_openrouter(provider_options={"providers_allowlist": ["fireworks"]})
    r = api.call("POST", "/entries/bulk", "tenant_admin", json=body)
    assert r.status_code == 207, r.text
    res = r.json()["data"][0]
    assert res["status"] == 201, res
    e = res["entry"]
    assert e["real_model"] == KIMI_K3 and e["provider"] == "openrouter" and e["is_aggregator"] is True
    with api.Session() as sess:
        guardada = sess.query(cm.CatalogEntry).filter_by(real_model=KIMI_K3).one()
        assert guardada.provider_options["providers_allowlist"] == ["fireworks"]
    assert e["features"]["images"] is True and e["price"]["input"] == 0.62e-6 and e["price"]["output"] == 15e-6
    assert e["semaforo"]["estado"] == "unclassified", "nace sin clasificar: la ficha se carga después"
    assert SECRET not in r.text


def test_bulk_openrouter_no_acepta_ir_en_contra_del_cero_retencion(api):
    body = _bulk_openrouter(provider_options={"providers_allowlist": ["fireworks"], "zdr": False})
    r = api.call("POST", "/entries/bulk", "tenant_admin", json=body)
    assert r.json()["data"][0]["status"] == 422 and r.json()["created"] == 0


def test_la_ficha_de_kimi_k3_lleva_la_jurisdiccion_del_proveedor_final_no_la_del_agregador(api):
    body = _bulk_openrouter(provider_options={"providers_allowlist": ["fireworks"]})
    eid = api.call("POST", "/entries/bulk", "tenant_admin", json=body).json()["data"][0]["entry"]["id"]
    ficha = {"provider_legal_entity": "Fireworks AI, Inc.", "entity_jurisdiction": "US", "control_jurisdiction": "US",
             "inference_jurisdiction": "US", "zero_data_retention": True, "trains_on_data": False}
    r = api.call("PUT", f"/entries/{eid}/sheet", "compliance_officer", json=ficha)
    assert r.status_code == 200, r.text
    sheet = api.call("GET", f"/entries/{eid}/sheet", "compliance_officer").json()["sheet"]
    assert sheet["inference_jurisdiction"] == "US" and sheet["provider_legal_entity"] == "Fireworks AI, Inc."
