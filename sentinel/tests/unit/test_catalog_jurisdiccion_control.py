"""Entidad responsable y jurisdicción de control en el catálogo (057 T087; FR-028a, D12; research R25).

La ficha acepta y devuelve `control_jurisdiction`; `provider_legal_entity` es la entidad responsable;
`in_region` de la entrada es verdadero solo si la inferencia, la entidad **y** el control están en la región
efectiva; con el control vacío o fuera, es falso. Cambiar el campo queda en el registro de cambios, re-evalúa las
reglas de habilitación y revoca una relajación por destino cuya ficha deja de cumplir las precondiciones. Ningún
código nombra un país de preocupación (esas jurisdicciones son reglas, vacías en Eleia).
"""
import pathlib
import re
import uuid
from types import SimpleNamespace

import pytest

from sentinel.catalog import models as cm
from sentinel.catalog import relaxation as rx
from sentinel.catalog import region as cr
from sentinel.catalog import store as cs
from sentinel.redirect import models as rm
from sentinel.tests.catalog_fixtures import T1, T2, create_entry, make_api

REGION_AR = "latam_ar"
FICHA_BASE = {"provider_legal_entity": "Operadora Ejemplo S.A.", "inference_jurisdiction": "AR",
              "entity_jurisdiction": "AR", "control_jurisdiction": "AR", "logs_jurisdiction": "AR",
              "zero_data_retention": True, "trains_on_data": False, "transfer_mechanism": "n/a"}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("SENTINEL_ENTITY_REGION", REGION_AR)
    return make_api(monkeypatch)


def _alta(api, **kw):
    return create_entry(api, "tenant_admin", T1, provider="anthropic", protocol_family="anthropic_messages",
                        real_model="modelo-x", name=kw.pop("name", "Modelo X"), credential={"new": {
                            "name": f"c-{uuid.uuid4().hex[:6]}", "value": "valor-inventado-de-prueba"}}, **kw)


def _put(api, entry, role="compliance_officer", tenant=T1, **campos):
    return api.call("PUT", f"/entries/{entry['id']}/sheet", role, tenant=tenant, json={**FICHA_BASE, **campos})


def _vista(api, entry, role="tenant_admin", tenant=T1):
    return api.call("GET", f"/entries/{entry['id']}", role, tenant=tenant).json()


# ── la ficha acepta y devuelve el control; la entidad responsable ──────────────────────────────────

def test_la_ficha_nueva_nace_sin_control_cargado(api):
    e = _alta(api)
    assert e["sheet"]["control_jurisdiction"] is None
    assert e["sheet"]["provider_legal_entity"] is None


def test_la_ficha_guarda_y_devuelve_entidad_responsable_y_las_tres_jurisdicciones(api):
    e = _alta(api)
    r = _put(api, e, control_jurisdiction="ar")
    assert r.status_code == 200, r.text
    ficha = r.json()["sheet"]
    assert ficha["provider_legal_entity"] == "Operadora Ejemplo S.A."          # entidad responsable
    assert (ficha["inference_jurisdiction"], ficha["entity_jurisdiction"], ficha["control_jurisdiction"]) == ("AR", "AR", "AR")
    assert _vista(api, e)["sheet"]["control_jurisdiction"] == "AR"
    assert api.call("GET", f"/entries/{e['id']}/sheet", "tenant_admin").json()["sheet"]["control_jurisdiction"] == "AR"


def test_el_control_acepta_vacio_y_rechaza_valores_largos(api):
    e = _alta(api)
    assert _put(api, e, control_jurisdiction=None).json()["sheet"]["control_jurisdiction"] is None
    assert _put(api, e, control_jurisdiction="").json()["sheet"]["control_jurisdiction"] is None
    assert _put(api, e, control_jurisdiction="X" * 9).status_code == 422


# ── in_region exige inferencia, entidad y control ─────────────────────────────────────────────────

@pytest.mark.parametrize("inf,ent,ctl,esperado", [
    ("AR", "AR", "AR", True),
    ("BR", "BR", "BR", True),                  # LATAM ⊇ BR (zona fija de la región latam_ar)
    ("AR", "AR", None, False),                 # control sin cargar: no cuenta como en región
    ("AR", "AR", "US", False),                 # controlada desde fuera de la región
    ("AR", "US", "AR", False),                 # entidad fuera
    ("US", "AR", "AR", False),                 # inferencia fuera
    ("AR", None, "AR", False),
])
def test_in_region_exige_inferencia_entidad_y_control(api, inf, ent, ctl, esperado):
    e = _alta(api)
    _put(api, e, inference_jurisdiction=inf, entity_jurisdiction=ent, control_jurisdiction=ctl)
    assert _vista(api, e)["in_region"] is esperado


def test_una_entrada_sin_clasificar_no_esta_en_region(api):
    assert _alta(api)["in_region"] is False


def test_in_region_sin_perfil_de_region_resuelto_es_falso(api, monkeypatch):
    monkeypatch.delenv("SENTINEL_ENTITY_REGION")
    e = _alta(api)
    _put(api, e)
    assert _vista(api, e)["in_region"] is False


def test_in_region_usa_la_region_cargada_como_dato(api):
    """Con una fila de región (instalación) que resuelve el perfil, sus jurisdicciones reemplazan a las fijas."""
    e = _alta(api)
    _put(api, e, inference_jurisdiction="US", entity_jurisdiction="US", control_jurisdiction="US")
    assert _vista(api, e)["in_region"] is False                       # latam_ar fijo = {LATAM, AR}
    with api.Session() as s:
        s.add(rm.RedirectRegion(level="installation", name="AMERICAS", is_zone=True, default_posture="masked_all",
                                jurisdictions=["US", "AR", "LATAM"], region_profiles=[REGION_AR]))
        s.commit()
    assert _vista(api, e)["in_region"] is True


def test_la_region_de_la_empresa_gana_sobre_la_de_instalacion(api):
    e = _alta(api)
    _put(api, e)
    with api.Session() as s:
        s.add_all([
            rm.RedirectRegion(level="installation", name="AMERICAS", jurisdictions=["AR"], region_profiles=[REGION_AR]),
            rm.RedirectRegion(level="tenant", tenant_id=T1, name="SOLO-BR", jurisdictions=["BR"], region_profiles=[REGION_AR]),
        ])
        s.commit()
    assert _vista(api, e)["in_region"] is False                       # la de T1 solo tiene BR
    assert _vista(api, e, role="tenant_admin", tenant=T1)["in_region"] is False


def test_los_codigos_efectivos_de_la_region_son_dato_o_el_respaldo_fijo(api):
    with api.Session() as s:                                                                 # una sesión = un pedido
        assert cr.effective_codes(s, T1, REGION_AR) == frozenset({"LATAM", "AR"})          # respaldo fijo
        assert cr.effective_codes(s, T1, None) == frozenset()                                # sin resolver
        s.add(rm.RedirectRegion(level="installation", name="AMERICAS", jurisdictions=["us", "AR"],
                                region_profiles=[REGION_AR, "us"]))
        s.commit()
    with api.Session() as s:
        assert cr.effective_codes(s, T1, REGION_AR) == frozenset({"US", "AR"})
        assert cr.effective_codes(s, T2, "us") == frozenset({"US", "AR"})


# ── cambiar el campo: registro, reglas de habilitación y relajaciones ─────────────────────────────

def test_cambiar_el_control_queda_en_el_registro_de_cambios(api):
    e = _alta(api)
    _put(api, e, control_jurisdiction="AR")
    _put(api, e, control_jurisdiction="US")
    filas = [a for a in api.audit("catalog_sheet")]
    assert filas[-1]["before"]["sheet"]["control_jurisdiction"] == "AR"
    assert filas[-1]["after"]["sheet"]["control_jurisdiction"] == "US"
    assert filas[-1]["actor_role"] == "compliance_officer"


def test_cambiar_el_control_re_evalua_las_reglas_de_habilitacion(api):
    e = _alta(api)
    assert api.call("POST", "/enablement-rules", "super_admin", json={
        "kind": "jurisdiction", "value": "ZZ", "level": "installation", "reason": "criterio de la instalación"}).status_code == 201
    assert _put(api, e, control_jurisdiction="AR").json()["blocked_by_default"] is False
    assert _put(api, e, control_jurisdiction="ZZ").json()["blocked_by_default"] is True
    assert _put(api, e, control_jurisdiction="AR").json()["blocked_by_default"] is False


def _relajar(api, entry, *, tenant=T1, level="tenant"):
    with api.Session() as s:
        s.add(rm.RedirectMaskingRelaxation(
            level=level, tenant_id=None if level == "installation" else tenant, entry_id=uuid.UUID(entry["id"]),
            reason="destino con retención cero contratada", created_by_role="compliance_officer"))
        s.commit()


def _relajaciones(api):
    with api.Session() as s:
        return [(r.revoked_at is not None, r.revoke_reason) for r in s.query(rm.RedirectMaskingRelaxation)]


@pytest.mark.parametrize("campo,valor", [
    ("control_jurisdiction", None), ("entity_jurisdiction", None), ("inference_jurisdiction", "unknown"),
    ("zero_data_retention", None), ("zero_data_retention", False),
])
def test_una_ficha_que_deja_de_cumplir_las_precondiciones_revoca_la_relajacion(api, campo, valor):
    e = _alta(api)
    _put(api, e)
    _relajar(api, e)
    assert _relajaciones(api) == [(False, None)]
    assert _put(api, e, **{campo: valor}).status_code == 200
    assert _relajaciones(api) == [(True, "precondicion_incumplida")]
    (fila,) = [a for a in api.audit("masking_relaxation")]
    assert fila["action"] == "revoke" and fila["reason"] == "precondicion_incumplida"


def test_una_ficha_que_sigue_cumpliendo_conserva_la_relajacion(api):
    e = _alta(api)
    _put(api, e)
    _relajar(api, e)
    _put(api, e, notes="se actualizó el contrato", logs_jurisdiction="US")
    assert _relajaciones(api) == [(False, None)]
    assert api.audit("masking_relaxation") == []


def test_la_revocacion_alcanza_tambien_a_la_relajacion_de_instalacion(api):
    e = _alta(api)
    _put(api, e)
    _relajar(api, e, level="installation")
    _put(api, e, control_jurisdiction=None)
    assert _relajaciones(api) == [(True, "precondicion_incumplida")]


def test_un_agregador_exige_ademas_la_lista_de_proveedores_permitidos(api):
    e = create_entry(api, "tenant_admin", T1, provider="openrouter", protocol_family="openai_chat",
                     real_model="proveedor/modelo", name="Agregador",
                     credential={"new": {"name": "c-agr", "value": "valor-inventado-de-prueba"}})
    _put(api, e)
    entry = SimpleNamespace(is_aggregator=True, provider_options={})
    sheet = SimpleNamespace(**{**FICHA_BASE, "inference_jurisdiction": "AR"})
    assert rx.unmet_preconditions(entry, sheet) == ["providers_allowlist"]
    entry.provider_options = {"providers_allowlist": ["uno"]}
    assert rx.unmet_preconditions(entry, sheet) == []


def test_las_precondiciones_nombran_cada_dato_que_falta():
    entry = SimpleNamespace(is_aggregator=False, provider_options={})
    vacia = SimpleNamespace(inference_jurisdiction="unknown", entity_jurisdiction=None, control_jurisdiction="",
                            zero_data_retention=None)
    assert rx.unmet_preconditions(entry, vacia) == [
        "inference_jurisdiction", "entity_jurisdiction", "control_jurisdiction", "zero_data_retention"]
    assert rx.unmet_preconditions(entry, None) == [
        "inference_jurisdiction", "entity_jurisdiction", "control_jurisdiction", "zero_data_retention"]


# ── el destino que ve la redirección trae el control ──────────────────────────────────────────────

def test_el_destino_de_la_redirección_incluye_el_control(api):
    e = _alta(api)
    _put(api, e, control_jurisdiction="AR")
    with api.Session() as s:
        (d,) = cs.redirect_destinations(s, T1)
    assert d["control_jurisdiction"] == "AR" and d["entity_jurisdiction"] == "AR"


def test_el_destino_sin_control_lo_trae_vacio(api):
    e = _alta(api)
    _put(api, e, control_jurisdiction=None)
    with api.Session() as s:
        (d,) = cs.redirect_destinations(s, T1)
    assert d["control_jurisdiction"] is None


# ── genérico: ningún código nombra un país de preocupación ────────────────────────────────────────

def test_ningun_codigo_nombra_un_pais_de_preocupacion():
    raiz = pathlib.Path(cm.__file__).resolve().parent
    fuentes = [raiz / "habilitacion.py", raiz / "region.py", raiz / "relaxation.py", raiz / "store.py",
               raiz / "validation.py", raiz / "api" / "admin.py"]
    patron = re.compile(r"\b(china|chino|china|rpc|rusia|ruso|iran|corea del norte)\b", re.IGNORECASE)
    for f in fuentes:
        assert not patron.search(f.read_text()), f.name
