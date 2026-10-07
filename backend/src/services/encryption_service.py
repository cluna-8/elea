import os
import logging

logger = logging.getLogger("sentinel-secure-gateway.encryption")

def _construir(key: str, previous: list[str]):
    """MultiFernet: cifra con `key`, descifra con `key` y con las `previous` (spec 069 D3).

    Una clave previa inválida se ignora con aviso: no debe tumbar la actual. El formato del token
    es el de Fernet, así que lo ya guardado con una sola clave sigue legible. `None` si no hay
    clave actual o es inválida."""
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet, MultiFernet
        olds = []
        for k in previous:
            try:
                olds.append(Fernet(k.encode()))
            except Exception:
                logger.warning("FERNET_PREVIOUS_KEYS: se ignora una clave con formato inválido")
        return MultiFernet([Fernet(key.encode()), *olds])
    except Exception as e:
        logger.warning("Fernet init failed, service_api_key_encrypted will be unavailable: %s", e)
        return None


# `FERNET_PREVIOUS_KEYS` (coma-separadas) SOLO descifra: permite rotar `FERNET_SECRET_KEY` sin
# perder lo ya cifrado.
_fernet = _construir(
    os.getenv("FERNET_SECRET_KEY", "").strip(),
    [k.strip() for k in os.getenv("FERNET_PREVIOUS_KEYS", "").split(",") if k.strip()],
)


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


class ClaveDeCifradoFaltante(RuntimeError):
    """Hay cifrado, pero ninguna de las claves cargadas descifra este valor.

    Pasa tras rotar `FERNET_SECRET_KEY` olvidando poner la anterior en `FERNET_PREVIOUS_KEYS`.
    `decrypt()` sigue devolviendo `None` (fail-closed, contrato histórico); quien necesite un error
    visible —alta/reemplazo/rotación de credenciales del catálogo— usa `descifrar_estricto`.
    """


def descifrar_estricto(value: str) -> str:
    """Como `decrypt`, pero la causa de un fallo es una excepción y no un `None` mudo."""
    if _fernet is None:
        raise CifradoNoDisponible(
            "FERNET_SECRET_KEY ausente, vacía o inválida — no hay servicio de cifrado"
        )
    try:
        return _fernet.decrypt(value.encode()).decode()
    except Exception as e:
        raise ClaveDeCifradoFaltante(
            "ninguna clave cargada descifra el valor: ¿falta la clave anterior en "
            "FERNET_PREVIOUS_KEYS?") from e


def rotar(value: str) -> str:
    """Recifra `value` con la clave actual (tras mover la anterior a `FERNET_PREVIOUS_KEYS`)."""
    if _fernet is None:
        raise CifradoNoDisponible(
            "FERNET_SECRET_KEY ausente, vacía o inválida — no hay servicio de cifrado"
        )
    try:
        return _fernet.rotate(value.encode()).decode()
    except Exception as e:
        raise ClaveDeCifradoFaltante("ninguna clave cargada descifra el valor a rotar") from e
