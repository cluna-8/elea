"""Escritura atómica de los ficheros de configuración que se editan EN CALIENTE.

El `config.yaml` del motor y el `auto_router.json` del router viven en un volumen
compartido y se reescriben desde el panel mientras el stack corre. Una escritura
in-place (`open(path, "w")`) TRUNCA el fichero antes de volcar el contenido nuevo:
si el proceso muere en esa ventana —o alguien reinicia a mitad de guardado— el
fichero queda vacío o cortado y el motor arranca sin catálogo, o sea la instalación
del cliente se queda sin modelos hasta que alguien lo repare a mano.

Por eso TODO escritor de estos ficheros pasa por acá: una sola implementación del
baile temporal + `os.replace`, en vez de una copia por endpoint.
"""
import os
import tempfile
from typing import Callable, TextIO

# Permisos con los que se CREA el fichero si no existía. El despliegue los fija en 664
# (deploy/release/populate_volumes.sh) para que el motor, que corre con otro UID, pueda
# leerlo; `mkstemp` crea 0600, así que sin este chmod la primera escritura dejaría el
# fichero ilegible para el motor.
MODO_POR_DEFECTO = 0o664


def escribir_atomico(destino: str, volcar: Callable[[TextIO], None],
                     *, modo_por_defecto: int = MODO_POR_DEFECTO) -> None:
    """Escribe `destino` de forma ATÓMICA: temporal en el MISMO directorio + `os.replace`.

    `volcar` recibe el temporal ya abierto en modo texto y escribe el contenido; el
    fsync previo al `replace` es lo que hace que el contenido sobreviva a un corte de
    luz, no solo a la muerte del proceso.

    El mismo directorio importa: `os.replace` solo es atómico dentro del sistema de
    ficheros de destino, y acá el destino es un volumen montado. Quien lea mientras
    tanto ve el fichero viejo o el nuevo, nunca uno a medias.

    Permisos y dueño del fichero que YA existía se conservan: el volumen espera
    10001:999 / 664 y un guardado no es el lugar para cambiarlos. El `chown` es
    best-effort porque solo root puede regalar un fichero — cuando el backend es el
    dueño (el caso del despliegue) el dueño ya coincide y no hace falta.
    """
    directorio = os.path.dirname(destino) or "."
    os.makedirs(directorio, exist_ok=True)

    try:
        previo = os.stat(destino)
    except OSError:
        previo = None

    fd, tmp = tempfile.mkstemp(prefix=f".{os.path.basename(destino)}.", suffix=".tmp",
                               dir=directorio)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            volcar(f)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, (previo.st_mode & 0o7777) if previo else modo_por_defecto)
        if previo is not None:
            try:
                os.chown(tmp, previo.st_uid, previo.st_gid)
            except OSError:
                pass
        os.replace(tmp, destino)
    except Exception:
        # El temporal no puede quedar en el volumen: se acumularían en cada fallo y
        # el directorio es el mismo que el motor lista al arrancar.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
