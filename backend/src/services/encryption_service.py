import os
import logging

logger = logging.getLogger("sentinel-secure-gateway.encryption")

_key = os.getenv("FERNET_SECRET_KEY", "").strip()
_fernet = None

if _key:
    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(_key.encode())
    except Exception as e:
        logger.warning("Fernet init failed, service_api_key_encrypted will be unavailable: %s", e)


class CifradoNoDisponible(RuntimeError):
    """No hay servicio de cifrado: `FERNET_SECRET_KEY` ausente, vacía o **inválida**.

    Es un fallo de despliegue, no de la petición. Quien la atrape debe cortar SIN escribir
    —un 503— y dejar la fila exactamente como estaba.

    Lo de «inválida» es la mitad que se subestima: el compose de producción exige la
    variable con `${FERNET_SECRET_KEY:?...}`, que corta con la variable ausente o vacía
    pero **acepta cualquier cadena no vacía**. Una clave con el formato equivocado pasa ese
    guard, `Fernet(...)` levanta acá arriba, queda un warning en el arranque y `_fernet` en
    None. O sea: el guard del compose es de FORMA y este es el único punto donde se
    comprueba la VALIDEZ.
    """


def encrypt(value: str) -> str | None:
    """Cifra `value`. Devuelve `None` **sólo** cuando no hay nada que cifrar.

    Levanta `CifradoNoDisponible` si el servicio de cifrado no está disponible (issue #283).

    Antes esta función colapsaba las dos causas en el mismo `None`, y ese `None` era una
    señal de error **in-band** que nada obligaba a mirar. Dos de los tres callers no la
    miraban: `POST /guardians` devolvía **201** con la credencial del admin tirada, y
    `PUT /guardians/{id}` devolvía **200** dejando en NULL una credencial que **estaba
    funcionando** —cifrada cuando el despliegue todavía tenía un Fernet sano—, sin forma de
    recuperarla porque el texto en claro nunca se guardó. Con la separación, olvidarse de
    la causa grave ya no es silencioso: propaga.

    `decrypt()` **no** cambia a propósito. Su `None` va en la dirección contraria —es la
    señal fail-closed del lado lectura: el gateway no inyecta la credencial y el pedido
    sube sin ella, así que nadie se sirve— y convertirlo en excepción cambiaría un camino
    que hoy degrada bien.
    """
    if not value:
        return None
    if _fernet is None:
        raise CifradoNoDisponible(
            "FERNET_SECRET_KEY ausente, vacía o inválida — no hay servicio de cifrado"
        )
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str | None:
    if not _fernet or not value:
        return None
    try:
        return _fernet.decrypt(value.encode()).decode()
    except Exception:
        logger.warning("Failed to decrypt service API key")
        return None
