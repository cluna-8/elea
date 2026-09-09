"""Saneo de errores del motor (spec 043 US6 — T058, Constitución VII: ningún nombre de
motor/proveedor externo en la API pública, mensajes de error, logs ni UI).

Antes esto vivía duplicado inline en `api/chat.py` (dos ocurrencias) y el plano `/gw`
(`api/gateway.py`) no lo aplicaba en absoluto — un error del motor pasando por el
passthrough salía con "litellm"/"LiteLLM" en el texto. Un solo lugar, aplicado en los dos
planos, para que no vuelvan a divergir (mismo criterio que la 027 ya aplicó a la
atribución compartida entre chat.py y gateway.py)."""
import re

_REEMPLAZOS = (("litellm", "Sentinel Gateway"), ("LiteLLM", "Sentinel Gateway"))

# Bug real encontrado en revisión (09-sep): antes esto era `"litellm." in out` (substring
# sin anclar en TODO el mensaje) seguido de `out.split(":", 1)` — cortaba en el PRIMER ":"
# de todo el string, sin importar dónde apareciera "litellm.". Un mensaje real como
# "Upstream timeout: contacting litellm.internal proxy failed" perdía "Upstream timeout"
# entero, aunque ese ":" no tuviera nada que ver con el prefijo de módulo. Ancladado al
# INICIO del string (con espacio en blanco inicial tolerado): solo el patrón real
# `litellm.<Clase>: <resto>` que emiten las excepciones de la librería (ver
# `litellm/exceptions.py`) se recorta.
_PREFIJO_MODULO_RE = re.compile(r"^\s*litellm\.\S+:\s*")


def sanitize_engine_error(text: str) -> str:
    """Reemplaza menciones al motor por el nombre neutro del producto, y si el mensaje
    trae el patrón `litellm.<algo>: <resto>` (una excepción de la librería, prefijo de
    módulo Python) AL INICIO del texto, se queda solo con el resto — el prefijo de módulo
    no aporta nada al usuario y es exactamente el tipo de detalle interno que la
    Constitución VII prohíbe exponer."""
    if not isinstance(text, str) or not text:
        return text
    out = _PREFIJO_MODULO_RE.sub("", text, count=1)
    for viejo, nuevo in _REEMPLAZOS:
        out = out.replace(viejo, nuevo)
    return out
