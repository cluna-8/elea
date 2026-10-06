"""Ficha: los campos de residencia y retención son solo de cumplimiento (057 T099; FR-023, research R30; QA A7).

`provider_legal_entity`, `entity_jurisdiction`, `control_jurisdiction`, `inference_jurisdiction` y
`zero_data_retention` los escriben `compliance_officer` y `super_admin` (con registro de cambios); el admin de empresa
edita el resto de la ficha y recibe 403 si el cuerpo **cambia** alguno de esos cinco campos (el formulario reenvía la
ficha entera: repetir el valor vigente no es un cambio). Con `REDIRECT_OPERATOR_TENANT` definida, el `tenant_admin`
del tenant operador sigue sin poder: la autoridad de instalación derivada de esa variable no alcanza.
"""
import uuid

import pytest

from sentinel.tests.catalog_fixtures import T1, T2, create_entry, make_api

RESTRINGIDOS = {
    "provider_legal_entity": ("Operadora Ejemplo S.A.", "Otra Entidad S.A."),
    "entity_jurisdiction": ("AR", "BR"),
    "control_jurisdiction": ("AR", "BR"),
    "inference_jurisdiction": ("AR", "BR"),
    "zero_data_retention": (True, False),
}
LIBRES = {
    "logs_jurisdiction": ("AR", "BR"),
    "trains_on_data": (False, True),
    "transfer_mechanism": ("n/a", "scc"),
    "eu_region_contracted": (True, False),
    "notes": ("nota inicial", "nota nueva"),
}
BASE = {"provider_legal_entity": "Operadora Ejemplo S.A.", "entity_jurisdiction": "AR", "control_jurisdiction": "AR",
        "inference_jurisdiction": "AR", "zero_data_retention": True, "logs_jurisdiction": "AR",
        "trains_on_data": False, "transfer_mechanism": "n/a", "eu_region_contracted": True, "notes": "nota inicial"}


@pytest.fixture
def api(monkeypatch):
    return make_api(monkeypatch)


@pytest.fixture
def entrada(api):
    e = create_entry(api, "tenant_admin", T1, provider="openrouter", protocol_family="openai_chat",
                     real_model="proveedor/modelo", name="Modelo ficha",
                     credential={"new": {"name": f"c-{uuid.uuid4().hex[:6]}", "value": "valor-inventado-de-prueba"}})
    assert api.call("PUT", f"/entries/{e['id']}/sheet", "compliance_officer", json=BASE).status_code == 200
    return e


def _put(api, entrada, role, tenant=T1, **cambios):
    return api.call("PUT", f"/entries/{entrada['id']}/sheet", role, tenant=tenant, json={**BASE, **cambios})


def _ficha(api, entrada, role="compliance_officer"):
    return api.call("GET", f"/entries/{entrada['id']}/sheet", role).json()["sheet"]


# ── el admin de empresa ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("campo", sorted(RESTRINGIDOS))
def test_el_admin_de_empresa_no_cambia_los_campos_de_residencia_ni_retencion(api, entrada, campo):
    antes = _ficha(api, entrada)
    r = _put(api, entrada, "tenant_admin", **{campo: RESTRINGIDOS[campo][1]})
    assert r.status_code == 403, r.text
    assert campo in r.json()["detail"] or "cumplimiento" in r.json()["detail"]
    assert _ficha(api, entrada) == antes                                  # no se guardó nada, ni lo permitido


@pytest.mark.parametrize("campo", sorted(LIBRES))
def test_el_admin_de_empresa_sigue_editando_el_resto_de_la_ficha(api, entrada, campo):
    r = _put(api, entrada, "tenant_admin", **{campo: LIBRES[campo][1]})
    assert r.status_code == 200, r.text
    assert r.json()["sheet"][campo] == LIBRES[campo][1]


def test_el_admin_reenvia_la_ficha_entera_sin_tocar_los_restringidos(api, entrada):
    """El formulario manda todo: repetir lo vigente en los cinco campos no es un cambio."""
    r = _put(api, entrada, "tenant_admin", notes="solo cambió la nota", logs_jurisdiction="BR")
    assert r.status_code == 200 and r.json()["sheet"]["notes"] == "solo cambió la nota"


def test_repetir_el_valor_con_otra_forma_tampoco_es_un_cambio(api, entrada):
    r = _put(api, entrada, "tenant_admin", entity_jurisdiction="ar", control_jurisdiction=" ar ",
             provider_legal_entity="  Operadora Ejemplo S.A.  ")
    assert r.status_code == 200, r.text


def test_cargar_un_dato_restringido_por_primera_vez_tambien_es_de_cumplimiento(api):
    e = create_entry(api, "tenant_admin", T1, provider="anthropic", protocol_family="anthropic_messages",
                     real_model="m", name="Sin ficha", credential={"new": {"name": "c-sf", "value": "valor-inventado-de-prueba"}})
    r = api.call("PUT", f"/entries/{e['id']}/sheet", "tenant_admin",
                 json={"inference_jurisdiction": "AR", "transfer_mechanism": "n/a"})
    assert r.status_code == 403
    r = api.call("PUT", f"/entries/{e['id']}/sheet", "tenant_admin",
                 json={"inference_jurisdiction": "unknown", "transfer_mechanism": "n/a", "notes": "x"})
    assert r.status_code == 200                                           # no tocar los cinco sí se puede


def test_el_403_no_deja_registro_de_cambios_ni_sube_la_version(api, entrada):
    filas, bumps = len(api.audit("catalog_sheet")), len(api.store.bumps)
    assert _put(api, entrada, "tenant_admin", inference_jurisdiction="BR").status_code == 403
    assert len(api.audit("catalog_sheet")) == filas and len(api.store.bumps) == bumps


# ── cumplimiento y super-admin ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("role", ["compliance_officer", "super_admin"])
@pytest.mark.parametrize("campo", sorted(RESTRINGIDOS))
def test_cumplimiento_y_super_admin_escriben_los_campos_restringidos_con_registro(api, entrada, role, campo):
    r = _put(api, entrada, role, **{campo: RESTRINGIDOS[campo][1]})
    assert r.status_code == 200, r.text
    assert r.json()["sheet"][campo] == RESTRINGIDOS[campo][1]
    ultimo = api.audit("catalog_sheet")[-1]
    assert ultimo["actor_role"] == role
    assert ultimo["before"]["sheet"][campo] == RESTRINGIDOS[campo][0]
    assert ultimo["after"]["sheet"][campo] == RESTRINGIDOS[campo][1]


@pytest.mark.parametrize("role", ["lectura", "client", None])
def test_los_demas_roles_siguen_sin_poder_escribir_la_ficha(api, entrada, role):
    assert _put(api, entrada, role, notes="x").status_code in (401, 403)


# ── REDIRECT_OPERATOR_TENANT no da autoridad sobre estos campos ───────────────────────────────────

def test_el_tenant_admin_del_tenant_operador_tampoco_puede(api, entrada, monkeypatch):
    monkeypatch.setenv("REDIRECT_OPERATOR_TENANT", str(T1))
    r = _put(api, entrada, "tenant_admin", control_jurisdiction="BR")
    assert r.status_code == 403
    assert _put(api, entrada, "tenant_admin", notes="la nota sí").status_code == 200


def test_un_super_admin_de_otra_empresa_si_puede_con_su_propia_entrada(api):
    e = create_entry(api, "tenant_admin", T2, provider="anthropic", protocol_family="anthropic_messages",
                     real_model="m", name="De T2", credential={"new": {"name": "c-t2", "value": "valor-inventado-de-prueba"}})
    r = api.call("PUT", f"/entries/{e['id']}/sheet", "super_admin", tenant=T2, json=BASE)
    assert r.status_code == 200
