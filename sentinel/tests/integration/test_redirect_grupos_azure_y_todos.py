"""057 R40 — no siempre son tres modelos: el alcance por GRUPO y el filtro de acceso por proveedor.

Requisito del owner: algunos grupos ven todos los modelos (Azure + Kimi por OpenRouter, etc.) y otros solo los de Azure.
Dos grupos reales de una misma empresa, pasarela y guard reales, catálogo real, upstream falso:

- grupo **TODOS** (`g-todos`): ve `claude-opus/sonnet/haiku` (a Azure) más un id extra `claude-sonnet-4-6-kimi` (a Kimi K3);
- grupo **AZURE** (`g-azure`): solo ve los tres que van a Azure. `/v1/models` de cada llave lista solo lo suyo y un pedido
  de AZURE al id de TODOS da el error neutro, sin nombrar destinos;
- una regla de un grupo no aplica a otro, y un grupo restringido a Azure por su perfil de acceso (selector `proveedor`)
  nunca llega a Kimi aunque una regla de la empresa lo mande ahí (con otro destino detrás de la regla, cae a ese).

Todo es dato (publicados, reglas con alcance de grupo, perfil de acceso): ningún cambio de código ni de modelo de datos.
"""
import json

import pytest

from sentinel.access import bridge
from sentinel.access import resolver as access
from sentinel.redirect import models as rm
from sentinel.tests import redirect_fixtures as fx
from sentinel.tests.catalog_fixtures import T1
from sentinel.tests.integration.test_redirect_sonnet_azure_a_kimi import (
    KIMI_K3, NOMBRE_KIMI, SECRETO_AZURE, SECRETO_OR, armar_mundo)
from sentinel.tests.integration import test_redirect_sonnet_azure_a_kimi as base
from src.api import gateway_plugins as gp

TODOS, AZURE = "g-todos", "g-azure"
TRES = ["claude-haiku-4-5", "claude-opus-5-5", "claude-sonnet-4-6"]
EXTRA = "claude-sonnet-4-6-kimi"
TIERS = {"claude-haiku-4-5": "haiku", "claude-opus-5-5": "opus", "claude-sonnet-4-6": "sonnet", EXTRA: "sonnet"}


def _publicar(s, azure, kimi):
    """Los tres ids de la familia, para toda la empresa, a Azure; el extra, solo para el grupo TODOS, a Kimi."""
    regla_extra = None
    for pid, tier in TIERS.items():
        solo_grupo = pid == EXTRA
        pub = rm.RedirectPublishedModel(
            tenant_id=T1, face="claude", public_id=pid, family_tier=tier, is_family_default=not solo_grupo,
            scope_type="group" if solo_grupo else "tenant", scope_value=TODOS if solo_grupo else "*")
        s.add(pub)
        s.flush()
        regla = rm.RedirectRule(tenant_id=T1, published_model_id=pub.id,
                                scope_type="group" if solo_grupo else "tenant", scope_value=TODOS if solo_grupo else "*",
                                targets=[kimi["id"] if solo_grupo else azure["id"]])
        s.add(regla)
        s.flush()
        regla_extra = regla.id if solo_grupo else regla_extra
    return regla_extra


@pytest.fixture
def mundo(monkeypatch):
    quien = {"group": TODOS}
    m = armar_mundo(monkeypatch, _publicar, quien)
    yield m
    gp.clear_gateway_plugins()


def _ids(resp):
    assert resp.status_code == 200, resp.text
    return sorted(x["id"] for x in resp.json()["data"])


def _pide(m, grupo, modelo):
    m.quien["group"] = grupo
    return m.cliente.post("/gw/v1/messages", headers=m.cabeceras, json={
        "model": modelo, "max_tokens": 64, "messages": [{"role": "user", "content": "hola"}]})


def _selector(m, grupo):
    m.quien["group"] = grupo
    return m.cliente.get("/gw/v1/models", headers=m.cabeceras)


# ── (a) publicados y reglas con alcance de grupo ──────────────────────────────────────────────

def test_v1_models_de_cada_grupo_lista_solo_lo_suyo(mundo):
    assert _ids(_selector(mundo, TODOS)) == sorted(TRES + [EXTRA])
    assert _ids(_selector(mundo, AZURE)) == TRES


def test_un_pedido_del_grupo_azure_al_id_de_todos_da_el_error_neutro_sin_nombrar_destinos(mundo):
    r = _pide(mundo, AZURE, EXTRA)
    assert r.status_code == 404 and r.json()["error"]["type"] == "not_found_error"
    plano = r.text.lower()
    for filtrado in (KIMI_K3, NOMBRE_KIMI, "kimi", "openrouter", "azure", "gpt-5.1", "destino", EXTRA):
        assert filtrado.lower() not in plano, f"el error nombró {filtrado!r}: {r.text}"
    assert not base.Engine.sent or "kimi" not in json.dumps(base.Engine.sent[-1]["body"]).lower(), "nada salió al destino"


def test_el_grupo_todos_llega_a_kimi_con_el_id_extra_y_a_azure_con_los_tres(mundo):
    base.Engine.sent.clear()
    assert _pide(mundo, TODOS, EXTRA).status_code == 200
    g = mundo.al_guard(base.Engine.sent[-1])
    assert g["api_key"] == SECRETO_OR and KIMI_K3 in g["model"]
    for pid in TRES:
        assert _pide(mundo, TODOS, pid).status_code == 200
        assert mundo.al_guard(base.Engine.sent[-1])["api_key"] == SECRETO_AZURE


def test_el_grupo_azure_llega_a_azure_con_los_tres(mundo):
    for pid in TRES:
        assert _pide(mundo, AZURE, pid).status_code == 200
        assert mundo.al_guard(base.Engine.sent[-1])["api_key"] == SECRETO_AZURE


def test_la_regla_de_un_grupo_no_aplica_a_otro_aunque_pida_el_mismo_id_del_tier(mundo):
    """TODOS mueve su sonnet a Kimi con una regla propia del grupo; AZURE sigue en Azure con el mismo id."""
    with mundo.api.Session() as s:
        pub = s.query(rm.RedirectPublishedModel).filter_by(public_id="claude-sonnet-4-6").one()
        s.add(rm.RedirectRule(tenant_id=T1, published_model_id=pub.id, scope_type="group", scope_value=TODOS,
                              targets=[mundo.kimi["id"]]))
        s.commit()
    assert _pide(mundo, TODOS, "claude-sonnet-4-6").status_code == 200
    assert mundo.al_guard(base.Engine.sent[-1])["api_key"] == SECRETO_OR
    assert _pide(mundo, AZURE, "claude-sonnet-4-6").status_code == 200
    assert mundo.al_guard(base.Engine.sent[-1])["api_key"] == SECRETO_AZURE


# ── (b) el grupo que solo puede ir a Azure no llega a Kimi ────────────────────────────────────

@pytest.fixture
def solo_azure(mundo, monkeypatch):
    """Perfil de acceso de empresa «Solo Azure» (selector `proveedor`) asignado al grupo AZURE (069 US2)."""
    entradas = [{"public_id": e["public_id"], "provider": e["provider"], "id": e["id"]} for e in (mundo.azure, mundo.kimi)]
    snap = access.AccessSnapshot(
        tenant_id=str(T1),
        profiles={"p-azure": access.Profile(id="p-azure", kind="company", name="Solo Azure",
                                            rules=(access.Rule("include", "proveedor", "azure"),))},
        assignments={("group", AZURE): ["p-azure"]})
    monkeypatch.setattr(bridge, "RESOLVER", lambda tenant, **kw: access.modelos_permitidos(
        snap, entradas, group_id=kw.get("group_id"), user_id=kw.get("user_id"), key_id=kw.get("key_id")).ids
        if (kw.get("group_id") or kw.get("user_id")) else None)
    monkeypatch.setattr(bridge, "CATALOG", lambda tenant: {e["public_id"]: e for e in entradas})
    return mundo


def _regla_de_empresa_a_kimi(m, targets):
    """La empresa manda `claude-sonnet-4-6` a Kimi (con `targets` en ese orden): lo que haría un administrador distraído."""
    with m.api.Session() as s:
        pub = s.query(rm.RedirectPublishedModel).filter_by(public_id="claude-sonnet-4-6").one()
        regla = s.query(rm.RedirectRule).filter_by(published_model_id=pub.id, scope_type="tenant").one()
        regla.targets = [m.kimi["id"] if t == "kimi" else m.azure["id"] for t in targets]
        s.commit()


def test_una_regla_de_la_empresa_a_kimi_no_manda_al_grupo_azure_a_kimi_da_error_neutro(solo_azure):
    _regla_de_empresa_a_kimi(solo_azure, ["kimi"])
    base.Engine.sent.clear()
    r = _pide(solo_azure, AZURE, "claude-sonnet-4-6")
    assert r.status_code == 403 and r.json()["error"]["type"] == "permission_error"
    assert not base.Engine.sent, "nada salió hacia el destino"
    for filtrado in ("kimi", "openrouter", NOMBRE_KIMI, KIMI_K3, SECRETO_OR):
        assert filtrado.lower() not in r.text.lower()
    # el grupo sin restricción sí llega a Kimi con la misma regla
    assert _pide(solo_azure, TODOS, "claude-sonnet-4-6").status_code == 200
    assert solo_azure.al_guard(base.Engine.sent[-1])["api_key"] == SECRETO_OR


def test_con_azure_detras_de_la_regla_el_grupo_restringido_cae_a_azure(solo_azure):
    _regla_de_empresa_a_kimi(solo_azure, ["kimi", "azure"])
    assert _pide(solo_azure, AZURE, "claude-sonnet-4-6").status_code == 200
    g = solo_azure.al_guard(base.Engine.sent[-1])
    assert g["api_key"] == SECRETO_AZURE and SECRETO_OR not in json.dumps(g, default=str)
    decision = g["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]
    assert decision["destination_id"] == solo_azure.azure["id"]


def test_el_selector_del_grupo_restringido_no_lista_el_id_que_solo_iria_a_kimi(solo_azure):
    with solo_azure.api.Session() as s:                    # el id extra, ahora para toda la empresa y solo a Kimi
        for tabla in (rm.RedirectPublishedModel, rm.RedirectRule):
            for fila in s.query(tabla).filter_by(scope_type="group", scope_value=TODOS):
                fila.scope_type, fila.scope_value = "tenant", "*"
        s.commit()
    assert _ids(_selector(solo_azure, TODOS)) == sorted(TRES + [EXTRA])
    assert _ids(_selector(solo_azure, AZURE)) == TRES
