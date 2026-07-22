"""Routing GDPR defensivo (fix pre-piloto, 2026-07-22).

El mapeo EU_MODEL_MAPPING renombra a aliases "-eu" que pueden no existir en el
catálogo del cliente (hallazgo de la auditoría del piloto: con gdpr_mode=True
default, pedir gpt-4o en el playground rompía con "modelo desconocido"). El
renombrado solo puede aplicarse si el destino existe en el catálogo vigente.
"""
from src.services.routing_service import EU_MODEL_MAPPING, RoutingService


def test_gdpr_off_no_toca_el_modelo():
    assert RoutingService.get_route_model("gpt-4o", False, {"gpt-4o"}) == "gpt-4o"


def test_renombra_cuando_el_destino_existe():
    disponibles = {"gpt-4o", "gpt-4o-eu"}
    assert RoutingService.get_route_model("gpt-4o", True, disponibles) == "gpt-4o-eu"


def test_NO_renombra_a_un_alias_fuera_del_catalogo():
    # El caso del piloto: el catálogo del cliente no define gpt-4o-eu.
    disponibles = {"gpt-4o", "gpt-4o-mini", "ollama-qwen3-4b"}
    assert RoutingService.get_route_model("gpt-4o", True, disponibles) == "gpt-4o"


def test_catalogo_vacio_es_fail_safe():
    # Config ilegible → set vacío → nunca renombrar (jamás pedir un fantasma).
    assert RoutingService.get_route_model("gpt-4o", True, set()) == "gpt-4o"


def test_modelo_sin_mapeo_pasa_intacto():
    disponibles = {"gemini-2.5-flash"}
    assert RoutingService.get_route_model("gemini-2.5-flash", True, disponibles) == "gemini-2.5-flash"


def test_sin_catalogo_conserva_comportamiento_legacy():
    # available_models=None → comportamiento histórico (sin verificación).
    assert RoutingService.get_route_model("gpt-4o", True) == EU_MODEL_MAPPING["gpt-4o"]
