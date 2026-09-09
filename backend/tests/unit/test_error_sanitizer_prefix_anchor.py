"""Bug real encontrado en revisión (09-sep): `sanitize_engine_error` cortaba en el PRIMER
":" de TODO el mensaje si "litellm." aparecía en cualquier posición — no solo cuando era
el prefijo real de módulo (`litellm.<Clase>: <resto>`). Librería pura, sin red/DB."""
from src.services.error_sanitizer import sanitize_engine_error


def test_prefijo_real_de_modulo_se_recorta():
    assert sanitize_engine_error("litellm.BadRequestError: falta el modelo") == "falta el modelo"


def test_colon_anterior_no_relacionado_ya_no_se_pisa():
    # Bug real: antes esto devolvía "contacting Sentinel Gateway.internal proxy failed"
    # (perdía "Upstream timeout" porque cortaba en el PRIMER ":" de todo el string).
    entrada = "Upstream timeout: contacting litellm.internal proxy failed"
    salida = sanitize_engine_error(entrada)
    assert salida.startswith("Upstream timeout"), salida
    assert "litellm" not in salida.lower()


def test_sin_prefijo_de_modulo_solo_reemplaza_el_nombre():
    assert sanitize_engine_error("timeout hablando con litellm") == "timeout hablando con Sentinel Gateway"


def test_no_string_no_rompe():
    assert sanitize_engine_error(None) is None
    assert sanitize_engine_error("") == ""
