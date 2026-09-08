"""Saneo de errores del motor (spec 043 US6 — T058, Constitución VII: ningún nombre de
motor/proveedor externo en la API pública, mensajes de error, logs ni UI).

Antes esto vivía duplicado inline en `api/chat.py` (dos ocurrencias) y el plano `/gw`
(`api/gateway.py`) no lo aplicaba en absoluto — un error del motor pasando por el
passthrough salía con "litellm"/"LiteLLM" en el texto. Un solo lugar, aplicado en los dos
planos, para que no vuelvan a divergir (mismo criterio que la 027 ya aplicó a la
atribución compartida entre chat.py y gateway.py)."""
import re

_REEMPLAZOS = (("litellm", "Sentinel Gateway"), ("LiteLLM", "Sentinel Gateway"))


def sanitize_engine_error(text: str) -> str:
    """Reemplaza menciones al motor por el nombre neutro del producto, y si el mensaje
    trae el patrón `litellm.<algo>: <resto>` (una excepción de la librería, prefijo de
    módulo Python), se queda solo con el resto — el prefijo de módulo no aporta nada al
    usuario y es exactamente el tipo de detalle interno que la Constitución VII prohíbe
    exponer."""
    if not isinstance(text, str) or not text:
        return text
    out = text
    if "litellm." in out:
        parts = out.split(":", 1)
        if len(parts) > 1:
            out = parts[1].strip()
    for viejo, nuevo in _REEMPLAZOS:
        out = out.replace(viejo, nuevo)
    return out
