"""Niveles de destino y ofertas (T043; FR-005a/005b).

- BYOK invisible entre tenants (FR-005a);
- retiro de oferta ⇒ fallback o inactivo **con aviso al tenant-admin** (FR-005b): el aviso es DERIVADO al
  leer (decisión del owner, 2-oct): `GET /rules` y `GET /destinations` anotan lo afectado con
  `warnings: [{code: "offer_withdrawn", destination_id}]` cuando un destino de instalación que una regla del
  tenant usa ya no está ofrecido a la organización. Sin tabla nueva: siempre refleja la oferta vigente.
- 069 E3: los destinos son entradas del catálogo y las ofertas son `ext_catalog_offer` (se dan en Modelos, no por
  esta API: `PUT /redirect/destinations/{id}/offer` responde 410); estos tests siembran el catálogo.

Montado con la costura S1 real y los guardas de rol del backend, como `contract/test_redirect_admin_api.py`
(sesión SQLite en memoria, sin Postgres ni Docker: la RLS la cubren los tests de migración).
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
CODE = "offer_withdrawn"


class _Store:
    def bump(self, tenant=None):
        pass


@pytest.fixture
def api(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    m.RedirectBase.metadata.create_all(engine)
    cm.CatalogBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(admin, "SESSION_FACTORY", Session)
    monkeypatch.setattr(admin, "STORE", _Store())
    app = FastAPI()
    assert mount_plugin_routers(app, "sentinel.redirect.api") == 1
    who = {"user": None}
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    client = TestClient(app)

    def call(method, path, role=None, tenant=T1, **kw):
        who["user"] = (SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant, role=role, display_label=None)
                       if role else None)
        return client.request(method, "/api/v1/redirect" + path, **kw)

    return SimpleNamespace(call=call, Session=Session)


def _installation(api, name="Compartido"):
    with api.Session() as s:
        return seed_entry(s, level="installation", name=name, credential_kind="env_ref",
                          env_name="REDIRECT_CRED_QWEN")["id"]


def _propio(api, name="Propio", tenant=T1):
    with api.Session() as s:
        return seed_entry(s, name=name, tenant=tenant, credential={"api_key": SECRET})["id"]


def _offer(api, dest, tenants):
    """Lo que hace el operador en Modelos (`PUT /catalog/entries/{id}/offers`): reemplaza las ofertas."""
    with api.Session() as s:
        s.query(cm.CatalogOffer).filter(cm.CatalogOffer.entry_id == uuid.UUID(dest)).delete()
        for t in tenants:
            s.add(cm.CatalogOffer(id=uuid.uuid4(), entry_id=uuid.UUID(dest),
                                  tenant_id=None if t == "*" else uuid.UUID(str(t))))
        s.commit()


def _rule(api, targets, *, tenant=T1, public_id="pro"):
    pub = api.call("POST", "/published-models", "tenant_admin", tenant=tenant,
                   json={"face": "openai_generic", "public_id": public_id})
    assert pub.status_code == 201, pub.text
    r = api.call("POST", "/rules", "tenant_admin", tenant=tenant,
                 json={"published_model_id": pub.json()["id"], "targets": targets})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _rules(api, role="tenant_admin", tenant=T1):
    r = api.call("GET", "/rules", role, tenant=tenant)
    assert r.status_code == 200
    return {x["id"]: x for x in r.json()["data"]}


def _warn(dest):
    return {"code": CODE, "destination_id": dest}


# ── FR-005a: BYOK invisible, instalación solo por oferta ──────────────────────

def test_byok_de_un_tenant_no_aparece_ni_se_usa_desde_otro(api):
    d = _propio(api)
    assert api.call("GET", "/destinations", "tenant_admin", tenant=T2).json()["data"] == []
    # y no entra en las reglas del otro tenant
    assert api.call("POST", "/rules", "tenant_admin", tenant=T2,
                    json={"family_tier": "sonnet", "targets": [d]}).status_code == 422


def test_destino_de_instalacion_solo_con_oferta_y_sin_credenciales(api):
    inst = _installation(api)
    assert api.call("GET", "/destinations", "tenant_admin").json()["data"] == []
    _offer(api, inst, [T1])
    lst = api.call("GET", "/destinations", "tenant_admin")
    assert [d["id"] for d in lst.json()["data"]] == [inst]
    assert api.call("GET", "/destinations", "tenant_admin", tenant=T2).json()["data"] == []
    assert "env:REDIRECT_CRED_QWEN" not in lst.text and SECRET not in lst.text


# ── FR-005b: retiro de oferta ⇒ fallback + aviso ──────────────────────────────

def test_con_oferta_vigente_no_hay_aviso(api):
    inst = _installation(api)
    _offer(api, inst, [T1])
    rid = _rule(api, [inst])
    assert _rules(api)[rid]["warnings"] == []
    body = api.call("GET", "/destinations", "tenant_admin").json()
    assert body["warnings"] == [] and all(d["warnings"] == [] for d in body["data"])


def test_retirar_la_oferta_avisa_en_la_regla_afectada(api):
    inst = _installation(api)
    otra = _propio(api, "Propio")
    _offer(api, inst, [T1])
    afectada = _rule(api, [inst, otra], public_id="pro")
    intacta = _rule(api, [otra], public_id="mini")
    _offer(api, inst, [T2])                                       # el operador la retira de T1
    rules = _rules(api)
    assert rules[afectada]["warnings"] == [_warn(inst)]
    assert rules[intacta]["warnings"] == []
    assert rules[afectada]["targets"] == [inst, otra]             # la regla no se reescribe sola


def test_el_aviso_lo_ven_los_roles_que_leen_reglas_y_nadie_ajeno(api):
    inst = _installation(api)
    _offer(api, inst, [T1])
    rid = _rule(api, [inst])
    _offer(api, inst, [T2])
    for role in ("tenant_admin", "compliance_officer"):
        assert _rules(api, role)[rid]["warnings"] == [_warn(inst)], role
    assert api.call("GET", "/rules", "client").status_code == 403
    assert _rules(api, tenant=T2) == {}                           # el otro tenant no ve reglas ni avisos de T1


def test_el_aviso_es_por_tenant(api):
    inst = _installation(api)
    _offer(api, inst, [T1, T2])
    r1, r2 = _rule(api, [inst], tenant=T1), _rule(api, [inst], tenant=T2)
    _offer(api, inst, [T2])                                       # solo se retira a T1
    assert _rules(api, tenant=T1)[r1]["warnings"] == [_warn(inst)]
    assert _rules(api, tenant=T2)[r2]["warnings"] == []


def test_oferta_a_todos_no_avisa_y_volver_a_ofrecer_borra_el_aviso(api):
    inst = _installation(api)
    _offer(api, inst, [T1])
    rid = _rule(api, [inst])
    _offer(api, inst, [T2])
    assert _rules(api)[rid]["warnings"] == [_warn(inst)]
    _offer(api, inst, ["*"])
    assert _rules(api)[rid]["warnings"] == []
    _offer(api, inst, [T2])
    assert _rules(api)[rid]["warnings"] == [_warn(inst)]
    _offer(api, inst, [T1])
    assert _rules(api)[rid]["warnings"] == []


def test_destinos_de_instalacion_distintos_se_avisan_por_separado(api):
    a, b = _installation(api, "A"), _installation(api, "B")
    _offer(api, a, [T1])
    _offer(api, b, [T1])
    rid = _rule(api, [a, b])
    _offer(api, b, [T2])
    assert _rules(api)[rid]["warnings"] == [_warn(b)]
    _offer(api, a, [T2])
    assert sorted(w["destination_id"] for w in _rules(api)[rid]["warnings"]) == sorted([a, b])


def test_un_destino_propio_nunca_avisa(api):
    propio = _propio(api)
    rid = _rule(api, [propio])
    assert _rules(api)[rid]["warnings"] == []


def test_el_aviso_no_expone_el_destino_retirado(api):
    """Solo código + id (que la regla del tenant ya contiene): ni nombre, ni jurisdicción, ni credencial."""
    inst = _installation(api, name="Nombre-interno-del-operador")
    _offer(api, inst, [T1])
    rid = _rule(api, [inst])
    _offer(api, inst, [T2])
    r = api.call("GET", "/rules", "tenant_admin")
    assert _rules(api)[rid]["warnings"] == [_warn(inst)]
    assert "Nombre-interno-del-operador" not in r.text and "REDIRECT_CRED_QWEN" not in r.text
    d = api.call("GET", "/destinations", "tenant_admin")
    assert "Nombre-interno-del-operador" not in d.text and "REDIRECT_CRED_QWEN" not in d.text and SECRET not in d.text


def test_destinos_avisa_arriba_aunque_el_retirado_ya_no_se_liste(api):
    inst = _installation(api)
    _offer(api, inst, [T1])
    _rule(api, [inst])
    _offer(api, inst, [T2])
    body = api.call("GET", "/destinations", "tenant_admin").json()
    assert body["data"] == []                                     # sigue sin verse (FR-005a)
    assert body["warnings"] == [_warn(inst)]


def test_destinos_sin_reglas_que_lo_usen_no_avisa(api):
    inst = _installation(api)
    _offer(api, inst, [T1])
    _offer(api, inst, [T2])
    assert api.call("GET", "/destinations", "tenant_admin").json()["warnings"] == []


def test_el_operador_tampoco_ve_en_la_lista_lo_que_su_organizacion_ya_no_puede_usar(api):
    """La lista es lo que la organización puede usar (E3): el operador ve lo mismo que su regla puede elegir; el
    aviso de las reglas de SU tenant va arriba, junto a la lista."""
    inst = _installation(api)
    _offer(api, inst, [T1])
    _rule(api, [inst])
    assert [d["id"] for d in api.call("GET", "/destinations", "super_admin").json()["data"]] == [inst]
    _offer(api, inst, [T2])
    body = api.call("GET", "/destinations", "super_admin").json()
    assert body["data"] == [] and body["warnings"] == [_warn(inst)]


def test_el_aviso_no_se_guarda_ni_entra_en_la_auditoria(api):
    inst = _installation(api)
    _offer(api, inst, [T1])
    rid = _rule(api, [inst])
    _offer(api, inst, [T2])
    assert "warnings" not in api.call("PATCH", f"/rules/{rid}", "tenant_admin",
                                      json={"strategy": "cheapest"}).json()
    assert _rules(api)[rid]["warnings"] == [_warn(inst)]


# ── el fallback sigue siendo el que el tenant eligió ─────────────────────────

def test_retiro_con_fallback_propio_sirve_el_fallback_y_lo_dice(api):
    inst = _installation(api)
    propio = _propio(api, "Propio")
    _offer(api, inst, [T1])
    _rule(api, [inst, propio])
    api.call("PUT", "/policy/tenant/*", "tenant_admin", json={"state": "on", "reason": "piloto"})
    _offer(api, inst, [T2])
    prev = api.call("POST", "/resolve-preview", "tenant_admin",
                    json={"face": "openai_generic", "public_id": "pro"}).json()
    assert prev["result"] == "resolved" and prev["destination_id"] == propio
    assert prev["substitution_reason"] is not None                # se sirvió un fallback, y la vista previa lo marca
    assert [s["destination_id"] for s in prev["skipped"]] == [inst]


def test_retiro_sin_fallback_deja_el_alias_inactivo_y_no_cae_en_otro_destino(api):
    inst = _installation(api)
    ajeno_a_la_regla = _propio(api, "No elegido")
    _offer(api, inst, [T1])
    _rule(api, [inst])
    api.call("PUT", "/policy/tenant/*", "tenant_admin", json={"state": "on", "reason": "piloto"})
    _offer(api, inst, [T2])
    prev = api.call("POST", "/resolve-preview", "tenant_admin",
                    json={"face": "openai_generic", "public_id": "pro"}).json()
    assert prev["result"] == "unavailable"
    assert [s["destination_id"] for s in prev["skipped"]] == [inst]
    assert ajeno_a_la_regla not in json.dumps(prev)               # nunca otro destino no elegido por el tenant
