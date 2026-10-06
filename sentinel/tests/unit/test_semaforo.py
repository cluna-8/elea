"""Semáforo derivado de la ficha de cumplimiento (069 FR-002a, FR-003; T016).

Función pura: misma entrada ⇒ misma salida, sin I/O ni reloj implícito (`hoy` se inyecta).
"""
from datetime import date

import pytest

from sentinel.catalog.semaforo import semaforo

HOY = date(2026, 10, 1)


def ficha(**kw):
    base = dict(inference_jurisdiction="EU", logs_jurisdiction="EU", trains_on_data=False,
                transfer_mechanism="n/a", eu_region_contracted=False)
    base.update(kw)
    return base


def dpa(exp=date(2027, 1, 1), region="EU", activo=True):
    return {"expiration_date": exp, "processing_region": region, "is_active": activo}


def run(f, d=None, agregador=False, hoy=HOY):
    return semaforo(f, d, es_agregador=agregador, hoy=hoy)


# --- local -------------------------------------------------------------------

def test_local_es_admisible_sin_dpa_ni_mas_datos():
    r = run({"inference_jurisdiction": "local"})
    assert r == {"estado": "eu_ok", "motivos": ["local"]}


# --- admisible UE completo ---------------------------------------------------

def test_ue_completa_con_dpa_vigente_es_admisible():
    assert run(ficha(), dpa())["estado"] == "eu_ok"


@pytest.mark.parametrize("transfer", ["n/a", "dpf", "scc"])
def test_mecanismos_de_transferencia_validos(transfer):
    assert run(ficha(transfer_mechanism=transfer), dpa())["estado"] == "eu_ok"


@pytest.mark.parametrize("logs", ["EU", "local", "none", "ES"])
def test_registros_ue_locales_o_inexistentes(logs):
    assert run(ficha(logs_jurisdiction=logs), dpa())["estado"] == "eu_ok"


def test_inferencia_en_pais_miembro_cuenta_como_ue():
    assert run(ficha(inference_jurisdiction="FR"), dpa())["estado"] == "eu_ok"


# --- estándar: cada condición que falla aporta su motivo -----------------------

@pytest.mark.parametrize("campo,valor,motivo", [
    ("inference_jurisdiction", "US", "inferencia_fuera_ue"),
    ("logs_jurisdiction", "US", "registros_fuera_ue"),
    ("trains_on_data", True, "entrena_con_datos"),
    ("transfer_mechanism", "none", "transferencia_sin_mecanismo"),
])
def test_condicion_que_falla_da_estandar_con_motivo(campo, valor, motivo):
    r = run(ficha(**{campo: valor}), dpa())
    assert r["estado"] == "standard"
    assert motivo in r["motivos"]


def test_sin_dpa_es_estandar():
    r = run(ficha(), None)
    assert (r["estado"], r["motivos"]) == ("standard", ["sin_dpa"])


def test_dpa_de_region_no_ue_es_estandar():
    r = run(ficha(), dpa(region="US"))
    assert r["estado"] == "standard" and "dpa_region_no_ue" in r["motivos"]


def test_dpa_inactivo_es_estandar():
    r = run(ficha(), dpa(activo=False))
    assert r["estado"] == "standard" and "dpa_inactivo" in r["motivos"]


# --- vencimiento del DPA (UTC, inclusive) --------------------------------------

def test_dpa_vigente_el_mismo_dia_del_vencimiento():
    assert run(ficha(), dpa(exp=HOY))["estado"] == "eu_ok"


def test_dpa_vencido_al_dia_siguiente_sin_que_nadie_edite():
    r = run(ficha(), dpa(exp=date(2026, 9, 30)))
    assert (r["estado"], r["motivos"]) == ("standard", ["dpa_vencido"])


def test_dpa_sin_fecha_de_vencimiento_no_vence():
    assert run(ficha(), dpa(exp=None))["estado"] == "eu_ok"


# --- sin clasificar ---------------------------------------------------------------

def test_ficha_vacia_es_sin_clasificar():
    r = run({})
    assert r["estado"] == "unclassified"
    assert "dato_desconocido:inference_jurisdiction" in r["motivos"]


@pytest.mark.parametrize("campo,valor", [
    ("logs_jurisdiction", "unknown"), ("logs_jurisdiction", None),
    ("trains_on_data", None), ("transfer_mechanism", "unknown"),
])
def test_dato_necesario_desconocido_es_sin_clasificar(campo, valor):
    r = run(ficha(**{campo: valor}), dpa())
    assert r["estado"] == "unclassified"
    assert f"dato_desconocido:{campo}" in r["motivos"]


def test_un_dato_desconocido_pesa_mas_que_uno_incumplido():
    # FR-003: «sin clasificar» es cualquier dato necesario sin cargar, aunque otro ya incumpla; una
    # ficha a medio llenar no se trata como clasificada.
    r = run(ficha(trains_on_data=True, logs_jurisdiction="unknown"), dpa())
    assert (r["estado"], r["motivos"]) == ("unclassified", ["dato_desconocido:logs_jurisdiction"])


def test_ficha_a_medio_llenar_sin_dpa_es_sin_clasificar_no_estandar():
    r = run({"inference_jurisdiction": "EU"}, None)
    assert r["estado"] == "unclassified"


def test_inferencia_desconocida_es_sin_clasificar_aunque_el_resto_cuadre():
    assert run(ficha(inference_jurisdiction="unknown"), dpa())["estado"] == "unclassified"


# --- agregadores (FR-002a) -----------------------------------------------------------

def test_agregador_sin_region_ue_contratada_nunca_es_admisible():
    r = run(ficha(eu_region_contracted=False), dpa(), agregador=True)
    assert (r["estado"], r["motivos"]) == ("standard", ["agregador"])


def test_agregador_con_region_ue_contratada_puede_ser_admisible():
    assert run(ficha(eu_region_contracted=True), dpa(), agregador=True)["estado"] == "eu_ok"


def test_agregador_con_dato_de_region_sin_cargar_es_sin_clasificar():
    r = run(ficha(eu_region_contracted=None), dpa(), agregador=True)
    assert r["estado"] == "unclassified"
    assert "dato_desconocido:eu_region_contracted" in r["motivos"]


def test_agregador_no_se_salva_por_inferencia_local():
    r = run({"inference_jurisdiction": "local", "eu_region_contracted": False}, agregador=True)
    assert r["estado"] == "standard" and "agregador" in r["motivos"]


# --- ficha obsoleta (cambió el proveedor o el modelo real) -----------------------------

def test_ficha_desactualizada_vuelve_a_sin_clasificar_aunque_cuadre_todo():
    r = semaforo(ficha(), dpa(), es_agregador=False, hoy=HOY, desactualizada=True)
    assert (r["estado"], r["motivos"]) == ("unclassified", ["ficha_desactualizada"])


# --- pureza -------------------------------------------------------------------------

def test_no_muta_sus_entradas_y_es_determinista():
    f, d = ficha(), dpa()
    f0, d0 = dict(f), dict(d)
    assert run(f, d) == run(f, d)
    assert f == f0 and d == d0


def test_acepta_fechas_iso_y_mayusculas():
    d = {"expiration_date": "2027-01-01", "processing_region": "eu", "is_active": True}
    assert run(ficha(inference_jurisdiction="eu", logs_jurisdiction="Eu"), d)["estado"] == "eu_ok"
