"""Hashing y verificación de contraseñas, con lectura del formato legacy.

Hasta acá ``users.password_hash`` guardaba ``sha256(password)``: sin sal y sin coste de
cómputo, o sea invertible con una rainbow table para cualquier contraseña que no sea
aleatoria, y con el mismo hash para dos usuarios que eligieron la misma. Este módulo pasa
el almacenamiento a bcrypt (sal por hash + factor de trabajo).

**Sigue leyendo el formato viejo a propósito.** Las instalaciones on-prem ya entregadas
tienen la tabla poblada y no hay ventana de mantenimiento para correr un script de
conversión —que además necesitaría las contraseñas en claro, que no existen en ninguna
parte—. La conversión es perezosa: ocurre en el login, el único instante en que la
contraseña en claro pasa por el servidor (ver ``necesita_rehash`` y su uso en
``api/users.login``).

Se usa la librería ``bcrypt`` directamente y NO ``passlib``, aunque passlib esté en
requirements y sea la vía habitual: passlib 1.7.4 (su última release) no puede ni
INICIALIZAR su backend bcrypt contra la librería actual —al cargarlo sondea un bug
histórico con un secreto de más de 72 bytes, y bcrypt 5.0 lanza ``ValueError`` en vez de
truncar—, así que el primer hash sería un 500. ``bcrypt`` ya viene instalada: es el extra
de ``passlib[bcrypt]==1.7.4``, no una dependencia nueva.
"""
import hashlib
import hmac
import re

import bcrypt

MIN_PASSWORD_LEN = 12

# bcrypt sólo considera los primeros 72 bytes del secreto (el resto se ignora por diseño).
_MAX_BYTES_BCRYPT = 72

# Formato legacy: sha256 hex sin sal ni prefijo. Es el ÚNICO otro formato aceptado; todo
# lo demás (centinelas de cuentas que no loguean, restos de seeds) no verifica nunca.
_LEGACY_SHA256 = re.compile(r"\A[0-9a-fA-F]{64}\Z")


def _acotado(raw: str) -> bytes:
    """Secreto en bytes, recortado a lo que bcrypt mira.

    El recorte es explícito porque la librería lanza ``ValueError`` ante un secreto más
    largo en vez de ignorar el sobrante: sin esto, una contraseña de 80 caracteres daría
    un 500 en el alta en lugar de un usuario creado.
    """
    return raw.encode("utf-8")[:_MAX_BYTES_BCRYPT]


def _es_legacy_sha256(stored: str) -> bool:
    return bool(stored) and _LEGACY_SHA256.match(stored) is not None


def hash_password(raw: str) -> str:
    """Hash bcrypt (``$2b$``) listo para guardar en ``users.password_hash``."""
    return bcrypt.hashpw(_acotado(raw), bcrypt.gensalt()).decode("ascii")


def verify_password(raw: str, stored: str) -> bool:
    """¿La contraseña coincide con el hash almacenado? Acepta bcrypt y el legacy sha256.

    Nunca lanza: un ``password_hash`` que no es ninguno de los dos formatos es un "esta
    cuenta no puede loguear", no un error del servidor. Hay filas así en producción a
    propósito (``!seeded-client-no-login`` de los clientes sembrados, que se conectan por
    Connection y no por contraseña).
    """
    if not stored:
        return False
    if _es_legacy_sha256(stored):
        # compare_digest y no ``==``: la comparación no debe filtrar por tiempo cuánto
        # prefijo del hash acertó el candidato.
        return hmac.compare_digest(
            hashlib.sha256(raw.encode("utf-8")).hexdigest(), stored.lower()
        )
    try:
        return bcrypt.checkpw(_acotado(raw), stored.encode("ascii"))
    except (ValueError, TypeError):
        return False


def necesita_rehash(stored: str) -> bool:
    """El hash almacenado está en el formato viejo y el próximo login debe reemplazarlo."""
    return _es_legacy_sha256(stored)


def validar_password(raw: str) -> None:
    """Puerta única de la política de longitud.

    Lanza ``ValueError`` en vez de ``HTTPException`` para que el módulo no dependa de
    FastAPI; el borde HTTP lo traduce a 422 con este mismo mensaje, así el texto que ve
    el usuario vive en un solo lugar.
    """
    if not raw or len(raw) < MIN_PASSWORD_LEN:
        raise ValueError(
            f"La contraseña debe tener al menos {MIN_PASSWORD_LEN} caracteres."
        )
