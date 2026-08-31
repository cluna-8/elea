"""Lectura de configuración por entorno de la superficie de licencia (spec 021).

Trampa que motiva este módulo, MEDIDA contra el sistema real: ``os.getenv(V, D)``
devuelve ``''`` cuando ``V`` está SETEADA PERO VACÍA — el default NO se aplica.
En la 021 eso no es cosmético: con ``SENTINEL_LICENSE_PUBLIC_KEYS_FILE=`` el keyset
embebido queda anulado, ``Path('')`` resuelve a ``'.'`` y leer un directorio
levanta ``LicenseReadError``; en RUNTIME esa excepción entra por el carril de
BLIP TRANSITORIO de ``refresh()`` (histéresis) y conserva ``active`` tres ticks
antes de degradar culpando a I/O en vez de a la configuración.

Regla de la superficie: **una variable vacía es indistinguible de una ausente**
— las dos significan "el operador no configuró esto" y vale el default del
producto. Es el criterio que ``_read_blob`` ya aplicaba al token inline.
"""
import os


def env_or_default(name: str, default: str) -> str:
    """``os.getenv`` con el default aplicado también a valor vacío/en blanco.

    Devuelve el valor TAL CUAL cuando la variable está configurada (no lo
    normaliza ni le hace strip): sólo decide si CUENTA como configurada.
    """
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value
