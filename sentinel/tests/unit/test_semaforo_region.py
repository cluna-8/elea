"""Semáforo del catálogo contra la región del perfil (057 T059/T063; FR-030a; research R16, R26).

La regla ya no es «admisible UE» fija: se evalúa contra las jurisdicciones de la región efectiva de la empresa
(`sentinel_redirect_region`, empresa > instalación; sin fila, el respaldo fijo del perfil). El valor interno `eu_ok`
se conserva (paridad de API y de tests); la etiqueta visible sale de la región: la API suma `region_label` (el nombre
de la región, p. ej. `AMERICAS`) y el panel muestra «Dentro de <región>», nunca «Admisible» ni «Cumple» (la región es
criterio de riesgo, no de legalidad). Con una región de una fila, «dentro» exige también entidad y control (R25).
Sin región resuelta ninguna jurisdicción está dentro: nunca cae a la UE. Con el perfil `eu` y sin fila, todo
queda como era (retrocompatible).
"""
import uuid
from datetime import date

import pytest

from sentinel.catalog.semaforo import semaforo
from sentinel.redirect import models as rm
from sentinel.tests.catalog_fixtures import T1, T2, create_entry, make_api

HOY = date(2026, 10, 1)
AMERICAS = frozenset({"US", "CA", "MX", "AR", "BR", "CL", "LATAM"})
EU = frozenset({"EU"})


def ficha(**kw):
    base = dict(inference_jurisdiction="US", logs_jurisdiction="US", trains_on_data=False, transfer_mechanism="n/a",
                entity_jurisdiction="US", control_jurisdiction="US", eu_region_contracted=False)
    base.update(kw)
    return base


def dpa(region="US"):
    return {"expiration_date": date(2027, 1, 1), "processing_region": region, "is_active": True}


def run(f, d=None, **kw):
    return semaforo(f, d if d is not None else dpa(), hoy=HOY, **kw)


# ── la regla pura contra un conjunto de jurisdicciones ───────────────────────────────────────────

def test_sin_region_la_regla_es_la_de_siempre():
    assert run(ficha(inference_jurisdiction="EU", logs_jurisdiction="EU"), dpa("EU"))["estado"] == "eu_ok"
    r = run(ficha())
    assert r["estado"] == "standard" and "inferencia_fuera_ue" in r["motivos"]


def test_una_ficha_dentro_de_la_region_es_eu_ok_el_valor_interno_se_conserva():
    r = run(ficha(), region=AMERICAS, region_strict=True)
    assert r == {"estado": "eu_ok", "motivos": []}


def test_una_ficha_de_la_ue_con_region_americas_queda_en_estandar():
    r = run(ficha(inference_jurisdiction="DE", logs_jurisdiction="FR"), dpa("DE"), region=AMERICAS, region_strict=True)
    assert r["estado"] == "standard"
    assert {"inferencia_fuera_region", "registros_fuera_region", "dpa_region_no_region"} <= set(r["motivos"])


def test_un_pais_de_la_zona_satisface_a_la_region_y_la_zona_no_a_un_pais():
    assert run(ficha(inference_jurisdiction="BR", logs_jurisdiction="AR"), dpa("CL"), region=AMERICAS,
               region_strict=True)["estado"] == "eu_ok"
    pais = frozenset({"AR"})
    r = run(ficha(inference_jurisdiction="LATAM", entity_jurisdiction="AR", control_jurisdiction="AR",
                  logs_jurisdiction="AR"), dpa("AR"), region=pais, region_strict=True)
    assert r["estado"] == "standard" and "inferencia_fuera_region" in r["motivos"]


def test_sin_region_resuelta_ninguna_jurisdiccion_esta_dentro_ni_cae_a_la_ue():
    for jur in ("EU", "DE", "US", "AR"):
        r = run(ficha(inference_jurisdiction=jur, logs_jurisdiction=jur), dpa(jur), region=frozenset(),
                region_strict=True)
        assert r["estado"] == "standard", jur
        assert "inferencia_fuera_region" in r["motivos"]


def test_la_inferencia_local_sigue_siendo_admisible_en_cualquier_region():
    assert run({"inference_jurisdiction": "local"}, region=AMERICAS, region_strict=True) == {
        "estado": "eu_ok", "motivos": ["local"]}
    assert run({"inference_jurisdiction": "local"}, region=frozenset(), region_strict=True)["estado"] == "eu_ok"


def test_con_region_de_fila_la_entidad_y_el_control_tambien_cuentan_r25():
    sin_control = run(ficha(control_jurisdiction=None), region=AMERICAS, region_strict=True)
    assert sin_control["estado"] == "unclassified"
    assert "dato_desconocido:control_jurisdiction" in sin_control["motivos"]
    sin_entidad = run(ficha(entity_jurisdiction="unknown"), region=AMERICAS, region_strict=True)
    assert sin_entidad["estado"] == "unclassified" and "dato_desconocido:entity_jurisdiction" in sin_entidad["motivos"]
    r = run(ficha(entity_jurisdiction="DE"), region=AMERICAS, region_strict=True)
    assert r["estado"] == "standard" and "entidad_fuera_region" in r["motivos"]
    r = run(ficha(control_jurisdiction="DE"), region=AMERICAS, region_strict=True)
    assert r["estado"] == "standard" and "control_fuera_region" in r["motivos"]


def test_sin_strict_la_entidad_y_el_control_no_se_miran_respaldo_fijo():
    assert run(ficha(entity_jurisdiction=None, control_jurisdiction=None), region=AMERICAS)["estado"] == "eu_ok"


def test_la_region_ue_conserva_los_motivos_de_siempre():
    r = run(ficha(), region=EU)
    assert "inferencia_fuera_ue" in r["motivos"] and "dpa_region_no_ue" in r["motivos"]


def test_los_motivos_nunca_dicen_admisible_ni_cumple():
    r = run(ficha(inference_jurisdiction="DE"), region=AMERICAS, region_strict=True)
    assert not any(p in " ".join(r["motivos"]) for p in ("admisible", "cumple"))


# ── la API y el canal interno ────────────────────────────────────────────────────────────────────

FICHA_API = {"provider_legal_entity": "Operadora Ejemplo", "inference_jurisdiction": "US", "entity_jurisdiction": "US",
             "control_jurisdiction": "US", "logs_jurisdiction": "US", "zero_data_retention": True,
             "trains_on_data": False, "transfer_mechanism": "n/a"}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("SENTINEL_ENTITY_REGION", "latam_ar")
    return make_api(monkeypatch)


def _region(api, *, nombre="AMERICAS", tenant=None, jurisdictions=("US", "CA", "AR", "BR", "LATAM"),
            perfiles=("latam_ar", "latam", "us")):
    with api.Session() as s:
        s.add(rm.RedirectRegion(level="tenant" if tenant else "installation", tenant_id=tenant, name=nombre,
                                jurisdictions=list(jurisdictions), region_profiles=list(perfiles),
                                default_posture="masked_all", is_zone=True))
        s.commit()


def _entrada(api, ficha_over=None, dpa_region="US", name="Modelo", tenant=T1):
    e = create_entry(api, "tenant_admin", tenant, provider="anthropic", protocol_family="anthropic_messages",
                     real_model="modelo-x", name=name,
                     credential={"new": {"name": f"c-{uuid.uuid4().hex[:6]}", "value": "valor-inventado-de-prueba"}})
    dpa_id = str(uuid.uuid4())
    api.dpas[dpa_id] = {"tenant_id": tenant, "expiration_date": date(2027, 1, 1), "processing_region": dpa_region,
                        "is_active": True}
    r = api.call("PUT", f"/entries/{e['id']}/sheet", "compliance_officer", tenant=tenant,
                 json={**FICHA_API, "dpa_registry_id": dpa_id, **(ficha_over or {})})
    assert r.status_code == 200, r.text
    return e


def _vista(api, e, tenant=T1):
    return api.call("GET", f"/entries/{e['id']}", "tenant_admin", tenant=tenant).json()


def test_la_api_evalua_contra_la_region_de_la_fila_y_trae_su_etiqueta(api):
    _region(api)
    v = _vista(api, _entrada(api))
    assert v["semaforo"] == {"estado": "eu_ok", "motivos": []}
    assert v["region_label"] == "AMERICAS" and v["in_region"] is True


def test_una_entrada_de_la_ue_no_es_eu_ok_en_americas(api):
    _region(api)
    v = _vista(api, _entrada(api, {"inference_jurisdiction": "DE", "logs_jurisdiction": "DE"}, dpa_region="DE"))
    assert v["semaforo"]["estado"] == "standard" and v["region_label"] == "AMERICAS"


def test_con_region_de_fila_sin_control_la_entrada_queda_sin_clasificar(api):
    _region(api)
    v = _vista(api, _entrada(api, {"control_jurisdiction": None}))
    assert v["semaforo"]["estado"] == "unclassified"
    assert "dato_desconocido:control_jurisdiction" in v["semaforo"]["motivos"] and v["in_region"] is False


def test_la_region_de_la_empresa_gana_sobre_la_de_instalacion_y_otra_empresa_no_la_ve(api):
    _region(api, nombre="AMERICAS")
    _region(api, nombre="CONO-SUR", tenant=T1, jurisdictions=("AR", "BR"))
    e1 = _entrada(api, name="Uno")
    v = _vista(api, e1)
    assert v["region_label"] == "CONO-SUR" and v["semaforo"]["estado"] == "standard"     # US ya no está dentro
    e2 = _entrada(api, name="Dos", tenant=T2)
    v2 = _vista(api, e2, tenant=T2)
    assert v2["region_label"] == "AMERICAS" and v2["semaforo"]["estado"] == "eu_ok"


def test_perfil_eu_sin_fila_es_la_regla_de_siempre(api, monkeypatch):
    monkeypatch.setenv("SENTINEL_ENTITY_REGION", "eu")
    e = _entrada(api, {"inference_jurisdiction": "DE", "logs_jurisdiction": "FR", "entity_jurisdiction": None,
                       "control_jurisdiction": None}, dpa_region="DE")
    v = _vista(api, e)
    assert v["semaforo"] == {"estado": "eu_ok", "motivos": []}      # sin exigir entidad ni control: respaldo fijo
    assert v["region_label"] == "EU"


def test_sin_region_resuelta_nada_es_eu_ok_ni_cae_a_la_ue(api, monkeypatch):
    monkeypatch.delenv("SENTINEL_ENTITY_REGION")
    e = _entrada(api, {"inference_jurisdiction": "DE", "logs_jurisdiction": "DE"}, dpa_region="DE")
    v = _vista(api, e)
    assert v["semaforo"]["estado"] == "standard" and v["region_label"] is None and v["in_region"] is False


def test_el_canal_interno_da_el_mismo_semaforo_que_la_api(api, monkeypatch):
    from sentinel.catalog.api import internal
    monkeypatch.setattr(internal, "SESSION_FACTORY", api.Session)
    monkeypatch.setattr(internal, "DPA_LOOKUP", lambda db, tenant, dpa_id: api.dpas.get(str(dpa_id)))
    monkeypatch.setattr(internal, "TODAY", lambda: date(2026, 10, 1))
    _region(api)
    ok = _entrada(api, name="Dentro")
    fuera = _entrada(api, {"inference_jurisdiction": "DE", "logs_jurisdiction": "DE"}, dpa_region="DE", name="Fuera")
    ficha_vacia = _entrada(api, {"control_jurisdiction": None}, name="Sin control")
    entradas = internal.build(str(T1))["entries"]
    for e in (ok, fuera, ficha_vacia):
        assert entradas[e["public_id"]]["semaforo"] == _vista(api, e)["semaforo"], e["name"]
    assert entradas[ok["public_id"]]["semaforo"]["estado"] == "eu_ok"


def test_el_texto_de_la_etiqueta_no_lo_arma_el_servidor_con_admisible_ni_cumple(api):
    _region(api)
    v = _vista(api, _entrada(api))
    texto = str(v).lower()
    assert "admisible" not in texto and "cumple" not in texto
