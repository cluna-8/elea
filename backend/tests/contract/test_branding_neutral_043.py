"""Branding neutro (spec 043 US6, T057, contrato 6, Constitución VII) — prueba de
regresión: recorre el OpenAPI publicado (nombres de campo, títulos, descripciones —lo que
un cliente de la API o `/docs` ve) y los nombres de guardianes sembrados, buscando términos
prohibidos. Lista de excepciones EXPLÍCITA y corta (no una allowlist amplia que termine
ocultando fugas nuevas)."""
import json
import re

import pytest

TERMINOS_PROHIBIDOS = ("litellm", "anythingllm", "presidio")

# Excepciones explícitas: identificadores INTERNOS que no son texto libre visible para el
# usuario final — `guardian_type` es un código de enum consumido por el frontend para
# lógica, no un texto que se muestre crudo (el `name` sembrado, sí visible, se corrigió en
# T061); `litellm_params` sigue existiendo como alias `deprecated=True` de compatibilidad
# hacia atrás (contrato 6) — su presencia en el schema es intencional y temporal.
EXCEPCIONES = {
    "guardian_type",  # valor de enum interno (p.ej. "presidio"), no copy
    "litellm_params",  # alias deprecated de compatibilidad, ver ModelCredentialSchema
}


def _recolectar_strings(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k not in EXCEPCIONES:
                out.append(str(k))
            _recolectar_strings(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _recolectar_strings(item, out)
    elif isinstance(obj, str):
        out.append(obj)


def _hallazgos(strings, excepciones_de_valor=()):
    hallazgos = []
    for s in strings:
        low = s.lower()
        for termino in TERMINOS_PROHIBIDOS:
            if termino in low and s not in excepciones_de_valor:
                hallazgos.append((termino, s))
    return hallazgos


def test_openapi_publico_sin_terminos_prohibidos():
    from src.main import app
    schema = app.openapi()
    strings = []
    _recolectar_strings(schema, strings)
    # `litellm_params` como VALOR de un nombre de propiedad también debe excluirse (además
    # de como clave, ya cubierto por EXCEPCIONES en _recolectar_strings).
    hallazgos = _hallazgos(strings, excepciones_de_valor={"litellm_params"})
    assert not hallazgos, f"términos prohibidos en el OpenAPI público: {hallazgos[:20]}"


def test_nombres_de_guardianes_sembrados_sin_terminos_prohibidos():
    from src.services.guardian_service import GuardianService
    import inspect
    fuente = inspect.getsource(GuardianService.get_or_create_default_guardians)
    # Se inspecciona el CÓDIGO fuente en vez de sembrar contra una DB — más rápido, y el
    # `name=` es un literal en el código, no algo que dependa de estado. `\bname=` (con
    # límite de palabra) para no confundir con `engine_guardrail_name=` — ese es el
    # contrato WIRE con el motor (nombre real del guardrail que LiteLLM espera en su
    # config, análogo a `litellm_params`), no el `name` visible del Guardian.
    nombres = re.findall(r'(?<![A-Za-z_])name\s*=\s*"([^"]*)"', fuente)
    hallazgos = _hallazgos(nombres)
    assert not hallazgos, f"términos prohibidos en nombres de guardianes sembrados: {hallazgos}"


@pytest.mark.parametrize("termino", TERMINOS_PROHIBIDOS)
def test_openapi_json_export_no_contiene_el_termino_como_json_crudo(termino):
    """Doble verificación sobre el JSON serializado completo (no solo claves/valores
    recorridos a mano) — atrapa el caso de un término prohibido escondido en un lugar que
    `_recolectar_strings` no visite por algún cambio futuro de forma del schema."""
    from src.main import app
    schema = app.openapi()
    raw = json.dumps(schema)
    # Filtra las excepciones conocidas antes de buscar — reemplazo simple, no regex, para
    # no ocultar apariciones reales adyacentes.
    for excepcion in EXCEPCIONES | {"litellm_params"}:
        raw = raw.replace(excepcion, "")
    assert termino not in raw.lower(), f"'{termino}' aparece en el OpenAPI serializado"
