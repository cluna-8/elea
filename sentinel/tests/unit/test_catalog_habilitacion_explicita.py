"""Habilitación explícita por datos (057 T025; FR-029, research R14, data-model §2).

Una entrada del catálogo nace `blocked_by_default` solo si alguna regla aplicable (proveedor, host de la
API o jurisdicción de inferencia, de entidad o **de control** de la ficha) coincide; habilitarla exige
motivo y rol, y queda en el registro de cambios. Con las tres listas vacías (el valor de Eleia, D1) nada
nace bloqueado y todo el flujo funciona. Ninguna regla está fija en el código: ni «deepseek».
"""
import json
import uuid

import pytest

from sentinel.catalog import habilitacion as hb
from sentinel.catalog import models as cm
from sentinel.catalog import store as cs
from sentinel.redirect import residency, resolver
from sentinel.redirect.scopes import RequestScope
from sentinel.tests.catalog_fixtures import T1, T2, create_entry, make_api

CHINAS = {
    "DeepSeek": dict(provider="deepseek", real_model="deepseek-chat", api_base=None),
    "GLM": dict(provider="zai", real_model="glm-4.6", api_base=None),
    "Qwen": dict(provider="openai_compatible", real_model="qwen3-max",
                 api_base="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
    "Kimi": dict(provider="openai_compatible", real_model="kimi-k2",
                 api_base="https://api.moonshot.cn/v1"),
    "OpenRouter": dict(provider="openrouter", real_model="qwen/qwen3", api_base=None),
}


@pytest.fixture
def api(monkeypatch):
    return make_api(monkeypatch)


def _alta(api, nombre, role="tenant_admin", tenant=T1):
    spec = dict(CHINAS[nombre])
    cred = {"new": {"name": f"cred-{nombre}-{tenant}", "value": "valor-inventado-de-prueba"}}
    return create_entry(api, role, tenant, name=f"{nombre} {tenant}", credential=cred,
                        protocol_family="openai_chat", **spec)


def _regla(api, kind, value, *, role="super_admin", level="installation", tenant=T1,
           reason="decisión de cumplimiento de la instalación"):
    return api.call("POST", "/enablement-rules", role, tenant=tenant,
                    json={"kind": kind, "value": value, "level": level, "reason": reason})


def _ficha(api, entry, role="compliance_officer", tenant=T1, **campos):
    body = {"inference_jurisdiction": "US", "logs_jurisdiction": "US", "transfer_mechanism": "n/a",
            "trains_on_data": False, "zero_data_retention": True, "entity_jurisdiction": "US"}
    body.update(campos)
    r = api.call("PUT", f"/entries/{entry['id']}/sheet", role, tenant=tenant, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _vista(api, entry, role="tenant_admin", tenant=T1):
    r = api.call("GET", f"/entries/{entry['id']}", role, tenant=tenant)
    assert r.status_code == 200, r.text
    return r.json()


def _elegible(api, entry_id, tenant=T1):
    """El destino que ve la redirección: ¿`check_target` lo deja pasar? (None = elegible)."""
    db = api.Session()
    try:
        dests = {d["id"]: d for d in cs.redirect_destinations(db, tenant)}
    finally:
        db.close()
    scope = RequestScope(tenant_id=str(tenant))
    motivo, _ = resolver.check_target(dests.get(entry_id), [], scope, residency.Posture(mode="off"))
    return motivo


# ── con las tres listas vacías (D1 de Eleia): ninguna entrada nace bloqueada ──────────────────────

@pytest.mark.parametrize("nombre", sorted(CHINAS))
def test_con_las_listas_vacias_ninguna_entrada_nace_bloqueada(api, nombre):
    e = _alta(api, nombre)
    assert e["blocked_by_default"] is False
    assert _elegible(api, e["id"]) is None                       # publicación y pedido funcionan
    assert api.call("POST", f"/entries/{e['id']}/enable", "tenant_admin",
                    json={"reason": "no hace falta"}).status_code == 409


def test_sin_reglas_la_api_devuelve_lista_vacia(api):
    r = api.call("GET", "/enablement-rules", "tenant_admin")
    assert r.status_code == 200 and r.json() == {"data": []}


def test_ningun_codigo_nombra_un_proveedor_de_bloqueo():
    """El bloqueo es dato: el código ya no compara con `deepseek` (Principio IV)."""
    import pathlib
    raiz = pathlib.Path(cm.__file__).resolve().parent
    fuentes = [raiz / "api" / "admin.py", raiz / "seed.py", raiz / "api" / "legacy.py", raiz / "habilitacion.py"]
    for f in fuentes:
        assert 'provider == "deepseek"' not in f.read_text(), f.name


# ── reglas: proveedor, host de la API, jurisdicción ───────────────────────────────────────────────

def test_regla_de_proveedor_bloquea_las_altas_y_re_evalua_las_existentes(api):
    antes = _alta(api, "DeepSeek")
    otro = _alta(api, "Kimi")
    r = _regla(api, "provider", "deepseek")
    assert r.status_code == 201, r.text
    assert r.json()["changed"] == 1                              # cuántas entradas cambiaron
    assert _vista(api, antes)["blocked_by_default"] is True
    assert _vista(api, otro)["blocked_by_default"] is False
    nueva = create_entry(api, "tenant_admin", T1, name="DeepSeek reasoner", provider="deepseek",
                         real_model="deepseek-reasoner", protocol_family="openai_chat",
                         credential={"new": {"name": "ds2", "value": "valor-inventado-de-prueba"}})
    assert nueva["blocked_by_default"] is True
    assert _elegible(api, nueva["id"]) == "blocked_by_default"


@pytest.mark.parametrize("host,coincide", [
    ("dashscope-intl.aliyuncs.com", True), ("dashscope.aliyuncs.com", True),
    ("evil.dashscope.aliyuncs.com", False), ("dashscope.aliyuncs.com.evil.net", False),
    ("api.moonshot.cn", False), ("aliyuncs.com", False),
])
def test_host_con_comodin_de_un_solo_nivel(host, coincide):
    assert hb.host_matches("dashscope*.aliyuncs.com", host) is coincide


@pytest.mark.parametrize("patron,host,coincide", [
    ("api.moonshot.cn", "api.moonshot.cn", True), ("api.moonshot.cn", "API.Moonshot.CN", True),
    ("api.moonshot.cn", "x.api.moonshot.cn", False), ("*.example.com", "a.example.com", True),
    ("*.example.com", "a.b.example.com", False), ("*.example.com", "example.com", False),
])
def test_host_exacto_y_comodin_a_la_izquierda(patron, host, coincide):
    assert hb.host_matches(patron, host) is coincide


def test_regla_de_host_bloquea_por_el_api_base(api):
    qwen, kimi = _alta(api, "Qwen"), _alta(api, "Kimi")
    assert _regla(api, "api_host", "dashscope*.aliyuncs.com").status_code == 201
    assert _vista(api, qwen)["blocked_by_default"] is True
    assert _vista(api, kimi)["blocked_by_default"] is False


@pytest.mark.parametrize("campo", ["inference_jurisdiction", "entity_jurisdiction"])
def test_regla_de_jurisdiccion_compara_inferencia_y_entidad_de_la_ficha(api, campo):
    e = _alta(api, "GLM")
    _ficha(api, e, **{campo: "CN"})
    assert _vista(api, e)["blocked_by_default"] is False
    assert _regla(api, "jurisdiction", "CN").json()["changed"] == 1
    assert _vista(api, e)["blocked_by_default"] is True


def test_regla_de_jurisdiccion_compara_tambien_la_de_control(api):
    """La entidad responsable puede estar en EE. UU. y estar controlada desde otra jurisdicción (D12)."""
    e = _alta(api, "GLM")
    _ficha(api, e)                                               # inferencia y entidad en EE. UU.
    db = api.Session()
    sheet = db.get(cm.ComplianceSheet, uuid.UUID(e["id"]))
    sheet.control_jurisdiction = "CN"
    db.commit()
    db.close()
    assert _vista(api, e)["blocked_by_default"] is False         # nada re-evaluó todavía
    assert _regla(api, "jurisdiction", "CN").json()["changed"] == 1
    assert _vista(api, e)["blocked_by_default"] is True


def test_una_jurisdiccion_desconocida_no_coincide_con_ninguna_regla(api):
    e = _alta(api, "GLM")                                        # ficha sin cargar: `unknown`
    assert _regla(api, "jurisdiction", "CN").json()["changed"] == 0
    assert _vista(api, e)["blocked_by_default"] is False


# ── cambiar provider / api_base / ficha re-evalúa ─────────────────────────────────────────────────

def test_cambiar_el_api_base_re_evalua_la_regla(api):
    _regla(api, "api_host", "api.moonshot.cn")
    e = _alta(api, "Qwen")
    assert e["blocked_by_default"] is False
    r = api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json={"api_base": "https://api.moonshot.cn/v1"})
    assert r.status_code == 200 and r.json()["blocked_by_default"] is True
    r = api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json={"api_base": "https://gw.example.net/v1"})
    assert r.json()["blocked_by_default"] is False               # ya no coincide: se desbloquea


def test_cambiar_el_proveedor_re_evalua_la_regla(api):
    _regla(api, "provider", "zai")
    e = _alta(api, "Kimi")
    r = api.call("PATCH", f"/entries/{e['id']}", "tenant_admin",
                 json={"provider": "zai", "api_base": None, "real_model": "glm-4.6"})
    assert r.status_code == 200, r.text
    assert r.json()["blocked_by_default"] is True


def test_pasar_a_bloqueada_borra_una_habilitacion_previa_y_queda_registrado(api):
    e = _alta(api, "Kimi")
    # habilitada antes de que existiera la regla: no estaba bloqueada, así que /enable no aplica; la
    # habilitación que se borra es la de una entrada que ya estuvo bloqueada por otra regla
    _regla(api, "provider", "deepseek")
    d = _alta(api, "DeepSeek")
    assert api.call("POST", f"/entries/{d['id']}/enable", "tenant_admin", json={"reason": "uso aprobado"}).status_code == 200
    assert _elegible(api, d["id"]) is None
    # la ficha pasa a coincidir con una regla de jurisdicción nueva: el cambio de la ficha re-evalúa
    _regla(api, "jurisdiction", "CN")
    _ficha(api, d, inference_jurisdiction="CN")
    v = _vista(api, d)
    assert v["blocked_by_default"] is True and v["enabled_at"] is None
    assert _elegible(api, d["id"]) == "blocked_by_default"
    acciones = [a["action"] for a in api.audit("catalog_entry")]
    assert "enable" in acciones and "block_by_rule" in acciones


def test_cambiar_el_api_base_de_una_entrada_habilitada_exige_habilitar_de_nuevo(api):
    _regla(api, "api_host", "*.moonshot.cn")
    e = _alta(api, "Qwen")
    api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json={"api_base": "https://api.moonshot.cn/v1"})
    assert api.call("POST", f"/entries/{e['id']}/enable", "tenant_admin", json={"reason": "uso aprobado"}).status_code == 200
    api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json={"api_base": "https://otro.moonshot.cn/v1"})
    v = _vista(api, e)
    assert v["blocked_by_default"] is True and v["enabled_at"] is None


def test_borrar_la_regla_desbloquea_lo_que_solo_ella_bloqueaba(api):
    e = _alta(api, "DeepSeek")
    regla = _regla(api, "provider", "deepseek").json()
    assert _vista(api, e)["blocked_by_default"] is True
    r = api.call("DELETE", f"/enablement-rules/{regla['id']}", "super_admin")
    assert r.status_code == 200 and r.json()["changed"] == 1
    assert _vista(api, e)["blocked_by_default"] is False


# ── habilitación desde el panel: motivo, rol, registro de cambios ─────────────────────────────────

def _bloqueada(api):
    _regla(api, "provider", "deepseek")
    return _alta(api, "DeepSeek")


def test_habilitar_exige_motivo(api):
    e = _bloqueada(api)
    assert api.call("POST", f"/entries/{e['id']}/enable", "tenant_admin", json={}).status_code == 422
    assert api.call("POST", f"/entries/{e['id']}/enable", "tenant_admin", json={"reason": " "}).status_code == 422
    assert _vista(api, e)["enabled_at"] is None


@pytest.mark.parametrize("role,estado", [("lectura", 403), ("client", 403), (None, 401),
                                         ("tenant_admin", 200), ("compliance_officer", 200)])
def test_habilitar_exige_un_rol_permitido(api, role, estado):
    e = _bloqueada(api)
    assert api.call("POST", f"/entries/{e['id']}/enable", role, json={"reason": "uso aprobado"}).status_code == estado


def test_habilitar_queda_en_el_registro_de_cambios_con_el_motivo(api):
    e = _bloqueada(api)
    api.call("POST", f"/entries/{e['id']}/enable", "compliance_officer", json={"reason": "uso aprobado por cumplimiento"})
    (fila,) = [a for a in api.audit("catalog_entry") if a["action"] == "enable"]
    assert fila["reason"] == "uso aprobado por cumplimiento" and fila["actor_role"] == "compliance_officer"
    assert _elegible(api, e["id"]) is None


# ── roles de la API de reglas ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("role,estado", [("tenant_admin", 200), ("compliance_officer", 200), ("super_admin", 200),
                                         ("lectura", 403), ("client", 403), (None, 401)])
def test_quien_lee_las_reglas(api, role, estado):
    assert api.call("GET", "/enablement-rules", role).status_code == estado


def test_la_regla_de_instalacion_la_escribe_solo_el_super_admin(api):
    for role in ("tenant_admin", "compliance_officer", "lectura", "client"):
        r = _regla(api, "provider", "deepseek", role=role, level="installation")
        assert r.status_code in (401, 403), (role, r.status_code)
    assert _regla(api, "provider", "deepseek", role="super_admin", level="installation").status_code == 201


@pytest.mark.parametrize("role", ["tenant_admin", "compliance_officer"])
def test_la_empresa_puede_agregar_reglas_propias(api, role):
    r = _regla(api, "provider", "zai", role=role, level="tenant")
    assert r.status_code == 201 and r.json()["tenant_id"] == str(T1) and r.json()["level"] == "tenant"


def test_la_empresa_solo_agrega_el_admin_no_borra_y_cumplimiento_si(api):
    regla = _regla(api, "provider", "zai", role="tenant_admin", level="tenant").json()
    assert api.call("DELETE", f"/enablement-rules/{regla['id']}", "tenant_admin").status_code == 403
    assert api.call("DELETE", f"/enablement-rules/{regla['id']}", "compliance_officer").status_code == 200


def test_las_reglas_de_otra_empresa_no_se_ven_ni_se_aplican(api):
    ajena = _regla(api, "provider", "openrouter", role="compliance_officer", level="tenant", tenant=T2).json()
    assert api.call("GET", "/enablement-rules", "tenant_admin", tenant=T1).json() == {"data": []}
    assert [r["id"] for r in api.call("GET", "/enablement-rules", "tenant_admin", tenant=T2).json()["data"]] == [ajena["id"]]
    mia, suya = _alta(api, "OpenRouter", tenant=T1), _alta(api, "OpenRouter", tenant=T2)
    assert mia["blocked_by_default"] is False                    # la regla de T2 no aplica a T1
    assert suya["blocked_by_default"] is True
    assert api.call("DELETE", f"/enablement-rules/{ajena['id']}", "compliance_officer", tenant=T1).status_code == 404


def test_las_reglas_de_instalacion_se_ven_en_todas_las_empresas_y_aplican_a_todas(api):
    _regla(api, "provider", "deepseek")
    for tenant in (T1, T2):
        assert len(api.call("GET", "/enablement-rules", "tenant_admin", tenant=tenant).json()["data"]) == 1
        assert _alta(api, "DeepSeek", tenant=tenant)["blocked_by_default"] is True


def test_una_regla_de_instalacion_re_evalua_las_entradas_de_todas_las_empresas(api):
    a, b = _alta(api, "DeepSeek", tenant=T1), _alta(api, "DeepSeek", tenant=T2)
    assert _regla(api, "provider", "deepseek").json()["changed"] == 2
    assert _vista(api, a, tenant=T1)["blocked_by_default"] and _vista(api, b, tenant=T2)["blocked_by_default"]


# ── validación y registro de las reglas ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("cuerpo", [
    {"kind": "pais", "value": "CN"},                       # tipo desconocido
    {"kind": "provider", "value": "no-existe"},            # no es un proveedor del catálogo
    {"kind": "api_host", "value": "*"},                    # comodín total
    {"kind": "api_host", "value": "api.*.cn"},             # comodín fuera del primer nivel
    {"kind": "api_host", "value": "https://api.cn/v1"},    # un host, no una URL
    {"kind": "jurisdiction", "value": ""},
])
def test_regla_invalida_es_422(api, cuerpo):
    r = api.call("POST", "/enablement-rules", "super_admin",
                 json={**cuerpo, "level": "installation", "reason": "decisión de cumplimiento"})
    assert r.status_code == 422, r.text


def test_la_regla_exige_motivo_y_no_admite_campos_desconocidos(api):
    base = {"kind": "provider", "value": "deepseek", "level": "installation"}
    assert api.call("POST", "/enablement-rules", "super_admin", json=base).status_code == 422
    assert api.call("POST", "/enablement-rules", "super_admin",
                    json={**base, "reason": "decisión", "extra": 1}).status_code == 422


def test_una_regla_repetida_es_409(api):
    assert _regla(api, "provider", "deepseek").status_code == 201
    assert _regla(api, "provider", "DeepSeek").status_code == 409     # se normaliza


def test_crear_y_borrar_reglas_queda_en_el_registro_de_cambios(api):
    regla = _regla(api, "provider", "deepseek", reason="política de cumplimiento 2026").json()
    api.call("DELETE", f"/enablement-rules/{regla['id']}", "super_admin")
    acciones = [(a["action"], a["reason"]) for a in api.audit("enablement_rule")]
    assert acciones[0] == ("create", "política de cumplimiento 2026") and acciones[1][0] == "delete"


def test_el_plano_de_datos_se_entera_del_cambio(api):
    api.store.bumps.clear()
    _regla(api, "provider", "deepseek")
    assert api.store.bumps, "una regla nueva tiene que subir la versión de la caché"


# ── paridad con Sentinel y seed ───────────────────────────────────────────────────────────────────

def test_el_seed_de_paridad_provider_deepseek_se_comporta_como_sentinel(api):
    db = api.Session()
    r = hb.seed_rules(db, {"providers": ["deepseek"], "api_hosts": [], "jurisdictions": []})
    db.commit()
    db.close()
    assert r == {"created": 1, "skipped": 0}
    assert _alta(api, "DeepSeek")["blocked_by_default"] is True       # como el `== "deepseek"` fijo
    assert _alta(api, "GLM")["blocked_by_default"] is False


def test_el_cargador_del_seed_es_idempotente_y_marca_las_reglas_como_de_seed(api):
    seed = {"providers": ["deepseek"], "api_hosts": ["api.moonshot.cn"], "jurisdictions": ["CN"]}
    db = api.Session()
    assert hb.seed_rules(db, seed) == {"created": 3, "skipped": 0}
    db.commit()
    assert hb.seed_rules(db, seed) == {"created": 0, "skipped": 3}
    db.commit()
    db.close()
    data = api.call("GET", "/enablement-rules", "super_admin").json()["data"]
    assert len(data) == 3 and {r["level"] for r in data} == {"installation"}


def test_el_seed_con_listas_vacias_no_crea_nada(api):
    db = api.Session()
    assert hb.seed_rules(db, {"providers": [], "api_hosts": [], "jurisdictions": []}) == {"created": 0, "skipped": 0}
    db.close()


@pytest.mark.parametrize("seed", [{"providers": ["no-existe"]}, {"api_hosts": ["*"]}, {"otra": []},
                                  {"providers": "deepseek"}, []])
def test_un_seed_invalido_falla_fuerte_y_no_siembra_nada(api, seed):
    db = api.Session()
    with pytest.raises(ValueError):
        hb.seed_rules(db, seed)
    assert db.query(cm.EnablementRule).count() == 0
    db.close()


def test_el_seed_del_catalogo_aplica_las_reglas_vigentes(api):
    from sentinel.catalog.seed import seed_catalog
    db = api.Session()
    hb.seed_rules(db, {"providers": ["deepseek"]})
    r = seed_catalog(db, {"entries": [
        {"name": "DeepSeek", "provider": "deepseek", "real_model": "deepseek-chat", "protocol_family": "openai_chat"},
        {"name": "GLM", "provider": "zai", "real_model": "glm-4.6", "protocol_family": "openai_chat"}]})
    db.commit()
    filas = {e.name: e.blocked_by_default for e in db.query(cm.CatalogEntry)}
    db.close()
    assert r["created"] == ["DeepSeek", "GLM"] and filas == {"DeepSeek": True, "GLM": False}


# ── el seed de Eleia (T028): las tres listas vacías, decisión del owner D1 (2026-10-06) ──────────────


def _seed_eleia():
    import pathlib
    ruta = pathlib.Path(__file__).resolve().parents[3] / "deploy" / "redirect-seeds" / "habilitacion-explicita.yaml"
    return ruta, hb.load_seed_file(ruta)


def test_el_seed_de_eleia_cita_la_decision_y_trae_las_tres_listas_vacias():
    ruta, data = _seed_eleia()
    assert data == {"providers": [], "api_hosts": [], "jurisdictions": []}
    texto = ruta.read_text(encoding="utf-8")
    assert "D1" in texto and "2026-10-06" in texto and "VACÍAS" in texto
    assert "api_key" not in texto and "secret" not in texto.lower()
    import pathlib
    prohibidos = [n.strip().lower() for n in (pathlib.Path(__file__).resolve().parents[3] / "deploy" / "release" /
                  "checks" / "prohibited_names.txt").read_text().splitlines() if n.strip() and not n.startswith("#")]
    assert not [n for n in prohibidos if n in texto.lower()]        # marca neutra (FR-050)


def test_con_el_seed_de_eleia_ninguna_entrada_nace_bloqueada_y_una_regla_posterior_bloquea(api):
    _, data = _seed_eleia()
    db = api.Session()
    assert hb.seed_rules(db, data) == {"created": 0, "skipped": 0}
    db.commit()
    db.close()
    antes = [_alta(api, n) for n in sorted(CHINAS)]
    assert not any(e["blocked_by_default"] for e in antes)
    assert all(_elegible(api, e["id"]) is None for e in antes)
    # una regla cargada después, desde el panel, bloquea como se espera
    assert _regla(api, "provider", "deepseek", role="super_admin").json()["changed"] == 1
    assert _vista(api, antes[0] if antes[0]["provider"] == "deepseek" else
                  next(e for e in antes if e["provider"] == "deepseek"))["blocked_by_default"] is True
    assert sum(_vista(api, e)["blocked_by_default"] for e in antes) == 1
