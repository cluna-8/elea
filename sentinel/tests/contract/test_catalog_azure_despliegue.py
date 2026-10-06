"""Catálogo de Azure verificable (057 T022; FR-020, research R9; contracts/admin-api.md §azure).

- La credencial de Azure es una **adoptada**: la clave se referencia por variable del servidor (`env:AZURE_API_KEY`, con
  nombres fuera de la lista negra) junto con su `api_version`; el secreto no se duplica ni se guarda.
- Al dar de alta o editar una entrada `azure`, el catálogo verifica que `real_model` sea un despliegue del recurso. Si no
  existe, la entrada queda `inactive` con «El despliegue <x> no existe en el recurso configurado» (nunca el «Resource not
  found» opaco), y `POST …/entries/{id}/check` la vuelve a verificar. La prueba (16 tokens por la ruta del guard) es
  inyectable: acá un doble, sin red ni Docker.
"""
import json
import uuid

import pytest

from sentinel.catalog import models as cm
from sentinel.catalog import validation as cv
from sentinel.catalog.api import admin
from sentinel.tests.catalog_fixtures import T1, T2, make_api

ENV_KEY = "env:AZURE_API_KEY"
API_VERSION = "2025-04-01-preview"
BASE = "https://recurso-demo.openai.azure.com"
MSG = "El despliegue {} no existe en el recurso configurado"


class Probe:
    """Doble de la prueba de despliegue: contesta lo guionado y registra cada llamada."""

    def __init__(self):
        self.guion = {}                     # real_model -> {"status": ..., "detail": ...}
        self.llamadas = []

    def __call__(self, entry, credential):
        self.llamadas.append((entry.real_model, dict(credential), entry.api_base))
        return self.guion.get(entry.real_model, {"status": "ok"})


@pytest.fixture
def api(monkeypatch):
    a = make_api(monkeypatch)
    a.probe = Probe()
    monkeypatch.setattr(admin, "DEPLOYMENT_PROBE", a.probe)
    return a


def _cred(**fields):
    return {"new": {"name": fields.pop("name", "azure-recurso"),
                    "value": {"api_key": ENV_KEY, "api_version": API_VERSION, **fields}}}


def _azure(api, real_model="gpt-5.1-chat", name=None, role="super_admin", level="installation", tenant=T1,
           credential=None, **kw):
    body = {"level": level, "name": name or f"Azure {real_model}", "provider": "azure", "real_model": real_model,
            "protocol_family": "openai_chat", "api_base": BASE, "credential": credential or _cred(),
            "capability": "standard", "role": "text", "context_window": 400000}
    body.update(kw)
    return api.call("POST", "/entries", role, tenant=tenant, json=body)


def _vista(api, e, role="super_admin", tenant=T1):
    return api.call("GET", f"/entries/{e['id']}", role, tenant=tenant).json()


# ── credencial adoptada: variable del servidor + api_version, sin duplicar el secreto ─────────────

def test_la_credencial_adoptada_referencia_la_variable_y_no_guarda_ningun_secreto(api):
    r = _azure(api)
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["has_credential"] is True and e["credential"]["kind"] == "secret"
    with api.Session() as s:
        row = s.query(cm.Credential).one()
        guardado = json.loads(admin._decrypt(row.ciphertext))
    assert guardado == {"api_key": ENV_KEY, "api_version": API_VERSION}      # solo la referencia y la versión
    assert "AZURE_API_KEY" in json.dumps(guardado) and not any(
        v.startswith("sk-") or len(v) > 40 for v in guardado.values())
    assert "AZURE_API_KEY" not in json.dumps(e)                                # la vista nunca trae el contenido


def test_varias_entradas_comparten_la_misma_credencial(api):
    a = _azure(api, "gpt-5.1-chat").json()
    r = api.call("POST", "/entries", "super_admin", json={
        "level": "installation", "name": "Azure gpt-5.4-mini", "provider": "azure", "real_model": "gpt-5.4-mini",
        "protocol_family": "openai_chat", "api_base": BASE, "credential": {"id": a["credential"]["id"]}})
    assert r.status_code == 201, r.text
    with api.Session() as s:
        assert s.query(cm.Credential).count() == 1


@pytest.mark.parametrize("variable", ["FERNET_SECRET_KEY", "LITELLM_MASTER_KEY", "SENTINEL_ENGINE_MASTER_KEY",
                                      "POSTGRES_PASSWORD", "DATABASE_URL", "REDIRECT_INTERNAL_KEY", "JWT_SECRET_KEY"])
def test_la_credencial_adoptada_no_puede_apuntar_a_secretos_de_la_plataforma(api, variable):
    r = _azure(api, credential=_cred(api_key=f"env:{variable}"))
    assert r.status_code == 422, r.text
    assert api.probe.llamadas == []


@pytest.mark.parametrize("valor", ["env:azure_minuscula", "env:", "env:1AZURE", "env:AZURE KEY"])
def test_la_referencia_a_variable_tiene_que_ser_un_nombre_valido(api, valor):
    assert _azure(api, credential=_cred(api_key=valor)).status_code == 422


def test_azure_exige_api_version_y_api_base(api):
    sin_version = {"new": {"name": "sin-version", "value": {"api_key": ENV_KEY}}}
    assert _azure(api, credential=sin_version).status_code == 422
    assert _azure(api, api_base=None).status_code == 422


def test_una_empresa_no_puede_referenciar_variables_del_servidor(api):
    r = _azure(api, role="tenant_admin", level="tenant")
    assert r.status_code in (403, 422), r.text
    assert api.probe.llamadas == []


def test_la_vista_no_trae_el_valor_de_la_credencial(api):
    texto = _azure(api).text
    assert "AZURE_API_KEY" not in texto and API_VERSION not in texto


# ── verificación del despliegue ───────────────────────────────────────────────────────────────────

def test_un_real_model_sin_despliegue_deja_la_entrada_inactiva_con_el_motivo(api):
    api.probe.guion["gpt-5.6-luna"] = {"status": "not_found", "detail": "Resource not found"}
    r = _azure(api, "gpt-5.6-luna")
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["status"] == "inactive"
    assert e["deployment_check"]["status"] == "not_found"
    assert e["deployment_check"]["message"] == MSG.format("gpt-5.6-luna")
    assert "Resource not found" not in json.dumps(e)                    # nunca el texto opaco del proveedor
    assert e["deployment_check"]["checked_at"]
    v = _vista(api, e)
    assert v["status"] == "inactive" and v["deployment_check"]["message"] == MSG.format("gpt-5.6-luna")


def test_un_despliegue_que_existe_queda_activo_y_verificado(api):
    e = _azure(api, "gpt-5.1-chat").json()
    assert e["status"] == "active" and e["deployment_check"]["status"] == "ok" and e["deployment_check"]["checked_at"]
    assert e["deployment_check"].get("message") in (None, "")


def test_si_no_se_puede_verificar_la_entrada_no_se_apaga(api):
    api.probe.guion["gpt-4o-mini"] = {"status": "error", "detail": "timeout"}
    e = _azure(api, "gpt-4o-mini").json()
    assert e["status"] == "active" and e["deployment_check"]["status"] == "error"
    assert "timeout" not in json.dumps(e["deployment_check"])                 # el detalle del motor no se expone


def test_una_entrada_inactiva_por_despliegue_no_se_sirve_a_la_redireccion_ni_al_motor(api):
    from sentinel.catalog import store as cs
    from sentinel.catalog.api import internal
    api.probe.guion["gpt-5.6-luna"] = {"status": "not_found"}
    e = _azure(api, "gpt-5.6-luna").json()
    api.call("PUT", f"/entries/{e['id']}/offers", "super_admin", json={"tenants": ["*"]})
    with api.Session() as s:
        assert cs.redirect_destinations(s, T1) == []
    internal.SESSION_FACTORY = api.Session
    try:
        assert "gpt-5.6-luna" not in internal.build(str(T1))["entries"]
    finally:
        internal.SESSION_FACTORY = None


def test_la_prueba_recibe_la_credencial_sin_resolver_y_la_base_del_recurso(api):
    _azure(api, "gpt-5.1-chat")
    (real_model, cred, base) = api.probe.llamadas[0]
    assert real_model == "gpt-5.1-chat" and base == BASE
    assert cred == {"api_key": ENV_KEY, "api_version": API_VERSION}        # el valor real lo resuelve el motor


def test_las_entradas_de_otros_proveedores_no_se_verifican_ni_traen_el_campo(api):
    r = api.call("POST", "/entries", "tenant_admin", json={
        "level": "tenant", "name": "Otro", "provider": "anthropic", "real_model": "m", "protocol_family": "anthropic_messages",
        "credential": {"new": {"name": "k", "value": "valor-inventado-de-prueba"}}})
    assert r.status_code == 201 and "deployment_check" not in r.json()
    assert api.probe.llamadas == []


def test_la_verificacion_queda_en_el_registro_de_cambios_sin_secretos(api):
    api.probe.guion["x"] = {"status": "not_found"}
    e = _azure(api, "x").json()
    filas = [a for a in api.audit("catalog_entry") if a["action"] == "deployment_check"]
    assert filas and filas[0]["after"]["status"] == "not_found"
    assert "AZURE_API_KEY" not in json.dumps(filas) and "api_key" not in json.dumps(filas)


# ── re-verificar: POST …/check, editar el modelo real ─────────────────────────────────────────────

def test_check_reactiva_la_entrada_cuando_el_despliegue_aparece(api):
    api.probe.guion["gpt-5.6-luna"] = {"status": "not_found"}
    e = _azure(api, "gpt-5.6-luna").json()
    assert e["status"] == "inactive"
    api.probe.guion["gpt-5.6-luna"] = {"status": "ok"}                       # el operador lo creó en Azure
    r = api.call("POST", f"/entries/{e['id']}/check", "super_admin")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active" and r.json()["deployment_check"]["status"] == "ok"
    assert _vista(api, e)["status"] == "active"


def test_check_sigue_inactiva_si_el_despliegue_no_existe(api):
    api.probe.guion["gpt-5.6-luna"] = {"status": "not_found"}
    e = _azure(api, "gpt-5.6-luna").json()
    r = api.call("POST", f"/entries/{e['id']}/check", "super_admin")
    assert r.status_code == 200 and r.json()["status"] == "inactive"
    assert r.json()["deployment_check"]["message"] == MSG.format("gpt-5.6-luna")
    assert len(api.probe.llamadas) == 2


def test_check_no_apaga_una_entrada_activa_por_un_error_de_red(api):
    e = _azure(api, "gpt-5.1-chat").json()
    api.probe.guion["gpt-5.1-chat"] = {"status": "error"}
    r = api.call("POST", f"/entries/{e['id']}/check", "super_admin")
    assert r.json()["status"] == "active" and r.json()["deployment_check"]["status"] == "error"


def test_check_apaga_una_entrada_activa_cuyo_despliegue_dejo_de_existir(api):
    e = _azure(api, "gpt-5.1-chat").json()
    api.probe.guion["gpt-5.1-chat"] = {"status": "not_found"}
    assert api.call("POST", f"/entries/{e['id']}/check", "super_admin").json()["status"] == "inactive"


def test_corregir_el_modelo_real_verifica_de_nuevo_y_activa(api):
    api.probe.guion["gpt-5.6-lunaa"] = {"status": "not_found"}
    e = _azure(api, "gpt-5.6-lunaa").json()
    assert e["status"] == "inactive"
    r = api.call("PATCH", f"/entries/{e['id']}", "super_admin", json={"real_model": "gpt-5.6-luna"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active" and r.json()["deployment_check"]["status"] == "ok"


def test_activar_a_mano_una_entrada_sin_despliegue_no_la_activa(api):
    api.probe.guion["gpt-5.6-luna"] = {"status": "not_found"}
    e = _azure(api, "gpt-5.6-luna").json()
    r = api.call("PATCH", f"/entries/{e['id']}", "super_admin", json={"status": "active"})
    assert r.status_code == 200 and r.json()["status"] == "inactive"


def test_editar_solo_el_nombre_no_vuelve_a_verificar(api):
    e = _azure(api, "gpt-5.1-chat").json()
    n = len(api.probe.llamadas)
    assert api.call("PATCH", f"/entries/{e['id']}", "super_admin", json={"name": "Otro nombre"}).status_code == 200
    assert len(api.probe.llamadas) == n


def test_apagar_a_mano_una_entrada_verificada_no_la_enciende(api):
    e = _azure(api, "gpt-5.1-chat").json()
    r = api.call("PATCH", f"/entries/{e['id']}", "super_admin", json={"status": "inactive"})
    assert r.json()["status"] == "inactive"


def test_check_exige_rol_de_administracion_y_alcance(api):
    e = _azure(api, "gpt-5.1-chat").json()
    for role in ("lectura", "client"):
        assert api.call("POST", f"/entries/{e['id']}/check", role).status_code == 403
    assert api.call("POST", f"/entries/{e['id']}/check", None).status_code == 401
    assert api.call("POST", f"/entries/{e['id']}/check", "tenant_admin", tenant=T2).status_code == 404   # no la ve


def test_check_de_una_entrada_que_no_es_azure_es_409(api):
    r = api.call("POST", "/entries", "tenant_admin", json={
        "level": "tenant", "name": "Otro", "provider": "anthropic", "real_model": "m", "protocol_family": "anthropic_messages",
        "credential": {"new": {"name": "k", "value": "valor-inventado-de-prueba"}}})
    assert api.call("POST", f"/entries/{r.json()['id']}/check", "tenant_admin").status_code == 409


def test_el_cliente_no_puede_escribir_el_resultado_de_la_verificacion(api):
    r = _azure(api, "gpt-5.1-chat", provider_options={"deployment_check": {"status": "ok"}})
    assert r.status_code == 422
    e = _azure(api, "gpt-5.1-chat").json()
    r = api.call("PATCH", f"/entries/{e['id']}", "super_admin", json={"provider_options": {"deployment_check": {"status": "ok"}}})
    assert r.status_code == 422


def test_editar_provider_options_conserva_el_resultado_de_la_verificacion(api):
    api.probe.guion["gpt-5.6-luna"] = {"status": "not_found"}
    e = _azure(api, "gpt-5.6-luna").json()
    r = api.call("PATCH", f"/entries/{e['id']}", "super_admin", json={"provider_options": {"nota": "x"}})
    assert r.status_code == 200 and r.json()["deployment_check"]["status"] == "not_found"


# ── clasificación de la respuesta del recurso (sin red) ───────────────────────────────────────────

@pytest.mark.parametrize("status,body,esperado", [
    (200, '{"choices": []}', "ok"),
    (404, '{"error": {"code": "DeploymentNotFound", "message": "The API deployment for this resource does not exist."}}', "not_found"),
    (404, '{"error": {"code": "404", "message": "Resource not found"}}', "not_found"),
    (404, "litellm.NotFoundError: AzureException NotFoundError - Resource not found", "not_found"),
    (400, '{"error": {"code": "DeploymentNotFound"}}', "not_found"),
    (401, '{"error": {"message": "Access denied due to invalid subscription key"}}', "error"),
    (403, "forbidden", "error"),
    (429, '{"error": {"message": "rate limit"}}', "error"),
    (500, "boom", "error"),
    (404, "otra cosa", "error"),                                   # un 404 sin la forma del despliegue no se interpreta
    (0, "", "error"),
])
def test_clasificacion_de_la_respuesta_de_la_prueba(status, body, esperado):
    assert cv.classify_deployment_response(status, body) == esperado


def test_el_mensaje_nombra_el_despliegue_sin_inventar_nada_mas():
    assert cv.deployment_not_found_message("gpt-5.6-luna") == MSG.format("gpt-5.6-luna")


def test_la_prueba_real_sin_motor_configurado_no_revienta_ni_inventa_un_resultado(monkeypatch):
    monkeypatch.delenv("REDIRECT_INTERNAL_KEY", raising=False)
    entry = cm.CatalogEntry(id=uuid.uuid4(), provider="azure", real_model="x", api_base=BASE)
    out = admin.default_deployment_probe(entry, {"api_key": ENV_KEY, "api_version": API_VERSION})
    assert out["status"] == "error"
