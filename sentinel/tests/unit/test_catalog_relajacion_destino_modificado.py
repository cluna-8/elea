"""La relajación por destino cae si cambia el destino (057 H2 del QA de T-B; FR-031a, FR-023, data-model §3).

Cumplimiento relaja el enmascarado forzado hacia *ese alojador*. El administrador de empresa, que sí edita la
entrada (`api_base`, proveedor, modelo), no puede apuntarla a otro alojador sin perder la relajación: al cambiar
`provider`, `api_base`, `real_model`, `is_aggregator` o la lista de proveedores permitidos, la relajación vigente se
revoca en el mismo cambio con `revoke_reason = destino_modificado` y queda en el registro de cambios. La fila no se
borra (historial). Editar cualquier otro campo no la toca. Archivar la entrada también la revoca.
"""
import uuid

import pytest

from sentinel.catalog import relaxation as rx
from sentinel.redirect import models as rm
from sentinel.tests.catalog_fixtures import T1, T2, make_api

BASE = "https://api.alojador-ejemplo.com/v1"
FICHA = {"provider_legal_entity": "Operadora Ejemplo S.A.", "inference_jurisdiction": "AR",
         "entity_jurisdiction": "AR", "control_jurisdiction": "AR", "logs_jurisdiction": "AR",
         "zero_data_retention": True, "trains_on_data": False, "transfer_mechanism": "n/a"}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("SENTINEL_ENTITY_REGION", "latam_ar")
    return make_api(monkeypatch)


def _alta(api, tenant=T1, level="tenant", role="tenant_admin"):
    r = api.call("POST", "/entries", role, tenant=tenant, json={
        "level": level, "name": "Modelo alojado", "provider": "openai_compatible", "real_model": "modelo-x",
        "protocol_family": "openai_chat", "api_base": BASE, "is_aggregator": True,
        "provider_options": {"providers_allowlist": ["Alojador-A", "alojador-b"]},
        "credential": {"new": {"name": f"c-{uuid.uuid4().hex[:6]}", "value": "valor-inventado-de-prueba"}}})
    assert r.status_code == 201, r.text
    entry = r.json()
    quien = "super_admin" if level == "installation" else "compliance_officer"
    assert api.call("PUT", f"/entries/{entry['id']}/sheet", quien, tenant=tenant, json=FICHA).status_code == 200
    return entry


def _relajar(api, entry, *, tenant=T1, level="tenant"):
    with api.Session() as s:
        s.add(rm.RedirectMaskingRelaxation(
            level=level, tenant_id=None if level == "installation" else tenant, entry_id=uuid.UUID(entry["id"]),
            reason="alojador con retención cero contratada", created_by_role="compliance_officer"))
        s.commit()


def _estado(api):
    with api.Session() as s:
        return [(r.revoked_at is not None, r.revoke_reason) for r in s.query(rm.RedirectMaskingRelaxation)]


VIGENTE, REVOCADA = (False, None), (True, rx.REVOKE_REASON_DESTINO)


def test_la_constante_del_motivo():
    assert rx.REVOKE_REASON_DESTINO == "destino_modificado"


@pytest.mark.parametrize("cambio", [
    {"api_base": "https://otro-host.ejemplo.com/v1"},
    {"provider": "openrouter"},
    {"real_model": "otro-modelo"},
    {"is_aggregator": False},
    {"provider_options": {"providers_allowlist": ["alojador-c"]}},
    {"provider_options": {"providers_allowlist": ["alojador-a"]}},
    {"provider_options": {}},
], ids=["api_base", "provider", "real_model", "is_aggregator", "providers_allowlist_otro",
        "providers_allowlist_quita_uno", "providers_allowlist_vacia"])
def test_cambiar_la_identidad_del_destino_revoca_la_relajacion(api, cambio):
    e = _alta(api)
    _relajar(api, e)
    assert _estado(api) == [VIGENTE]
    r = api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json=cambio)
    assert r.status_code == 200, r.text
    assert _estado(api) == [REVOCADA]
    (fila,) = api.audit("masking_relaxation")
    assert fila["action"] == "revoke" and fila["reason"] == "destino_modificado"
    assert fila["after"]["changed"] == [next(iter(cambio)) if next(iter(cambio)) != "provider_options"
                                        else "providers_allowlist"]
    assert BASE not in str(fila) and "otro-host" not in str(fila)          # solo nombres de campo, nunca valores


@pytest.mark.parametrize("cambio", [
    {"name": "Otro nombre visible"},
    {"price_input": 1.5, "price_output": 2.0},
    {"context_window": 64000},
    {"capability": "frontier"},
    {"features": {"cache_control": True}},
    {"provider_options": {"providers_allowlist": ["ALOJADOR-B", " alojador-a "]}},   # mismo conjunto, otro orden/forma
    {"api_base": BASE},                                                               # la misma base
    {"real_model": "modelo-x"},
], ids=["name", "precios", "context_window", "capability", "features", "allowlist_mismo_conjunto",
        "misma_base", "mismo_modelo"])
def test_un_cambio_que_no_toca_la_identidad_conserva_la_relajacion(api, cambio):
    e = _alta(api)
    _relajar(api, e)
    assert api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json=cambio).status_code == 200
    assert _estado(api) == [VIGENTE]
    assert api.audit("masking_relaxation") == []


def test_apagar_o_encender_la_entrada_no_es_cambiar_el_destino(api):
    e = _alta(api)
    _relajar(api, e)
    assert api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json={"status": "inactive"}).status_code == 200
    assert _estado(api) == [VIGENTE]


def test_la_relajacion_de_otra_entrada_no_se_toca(api):
    e = _alta(api)
    otra = api.call("POST", "/entries", "tenant_admin", json={
        "level": "tenant", "name": "Otro modelo", "provider": "openai_compatible", "real_model": "m2",
        "protocol_family": "openai_chat", "api_base": BASE,
        "credential": {"new": {"name": "c-otra", "value": "valor-inventado-de-prueba"}}}).json()
    _relajar(api, otra)
    assert api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json={"real_model": "x"}).status_code == 200
    assert _estado(api) == [VIGENTE]


def test_la_relajacion_de_instalacion_cae_si_el_operador_cambia_el_destino(api):
    e = _alta(api, level="installation", role="super_admin")
    _relajar(api, e, level="installation")
    r = api.call("PATCH", f"/entries/{e['id']}", "super_admin", json={"api_base": "https://otro.ejemplo.com/v1"})
    assert r.status_code == 200, r.text
    assert _estado(api) == [REVOCADA]


def test_la_revocacion_no_borra_la_fila_y_no_revoca_dos_veces(api):
    e = _alta(api)
    _relajar(api, e)
    api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json={"real_model": "uno"})
    api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json={"real_model": "dos"})
    assert _estado(api) == [REVOCADA]
    assert len(api.audit("masking_relaxation")) == 1


def test_una_relajacion_revocada_por_el_cambio_no_vuelve_al_deshacerlo(api):
    e = _alta(api)
    _relajar(api, e)
    api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json={"api_base": "https://otro.ejemplo.com/v1"})
    api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json={"api_base": BASE})
    assert _estado(api) == [REVOCADA]


def test_archivar_la_entrada_revoca_la_relajacion(api):
    e = _alta(api)
    _relajar(api, e)
    assert api.call("POST", f"/entries/{e['id']}/archive", "tenant_admin",
                    json={"reason": "ya no se usa"}).status_code == 200
    assert _estado(api) == [(True, rx.REVOKE_REASON_ARCHIVADA)]
    (fila,) = api.audit("masking_relaxation")
    assert fila["action"] == "revoke" and fila["reason"] == "entrada_archivada"


def test_el_cambio_queda_en_el_registro_con_el_actor(api):
    e = _alta(api)
    _relajar(api, e)
    api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json={"real_model": "otro"})
    (fila,) = api.audit("masking_relaxation")
    assert fila["actor_role"] == "tenant_admin" and fila["tenant_id"] == T1
    assert fila["before"]["level"] == "tenant"


def test_otra_empresa_no_ve_ni_revoca_la_relajacion_ajena(api):
    e = _alta(api)
    _relajar(api, e)
    assert api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", tenant=T2,
                    json={"real_model": "otro"}).status_code == 404
    assert _estado(api) == [VIGENTE]
