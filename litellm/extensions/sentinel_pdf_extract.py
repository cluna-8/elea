"""Extractor de texto de PDF para el enmascarado forzado (S14; research R29 3b) — PROCESO HIJO.

Lo lanza `sentinel_guardian_policy` como `python -I <este archivo> <límites…>`, un hijo por PDF: el PDF entra
por la entrada estándar (bytes crudos) y el texto sale por la salida estándar (UTF-8). Es un archivo
AUTOCONTENIDO (solo biblioteca estándar y `pypdf`): no importa nada del motor ni de la base, no lee
credenciales y no escribe nada fuera de su salida.

Por qué un proceso y no un hilo (QA v2 N4): la entrada es del cliente y `pypdf` es síncrono; un hilo no se
puede matar al vencer el plazo ni acotar en memoria, y el bucle de eventos del motor atiende a todas las
empresas. Los límites del sistema operativo se fijan ANTES de importar `pypdf`:

- `RLIMIT_AS`  = memoria máxima (MB);
- `RLIMIT_CPU` = plazo + 5 s (el plazo de reloj lo aplica quien lo lanza, con kill).

Protocolo de salida (el código de salida es el veredicto; la salida estándar es solo el texto):

    0  ok              texto en la salida estándar (puede ser vacío: «sin texto»)
    3  resource_limit  expansión, memoria, páginas o texto por encima de los topes
    4  protected       PDF cifrado/protegido
    5  error           corrupto o cualquier otro fallo del parser
    6  unavailable     `pypdf` no está instalado

El texto nunca se escribe en la salida de error ni en ningún registro.
"""
import sys

EXIT_OK = 0
EXIT_RESOURCE_LIMIT = 3
EXIT_PROTECTED = 4
EXIT_ERROR = 5
EXIT_UNAVAILABLE = 6


def _argumentos(argv):
    """`clave=valor` posicionales fijos: memoria_mb cpu_s max_paginas max_flujo max_texto."""
    memoria_mb, cpu_s, max_paginas, max_flujo, max_texto = (int(x) for x in argv[1:6])
    return memoria_mb, cpu_s, max_paginas, max_flujo, max_texto


def _fijar_limites(memoria_mb, cpu_s):
    import resource
    # RLIMIT_AS y RLIMIT_CPU primero: todo lo que viene después (incluido el import de pypdf) ya corre acotado.
    resource.setrlimit(resource.RLIMIT_AS, (memoria_mb * 1024 * 1024, memoria_mb * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))


def main(argv):
    memoria_mb, cpu_s, max_paginas, max_flujo, max_texto = _argumentos(argv)
    _fijar_limites(memoria_mb, cpu_s)
    datos = sys.stdin.buffer.read()
    try:
        import pypdf
    except ImportError:
        return EXIT_UNAVAILABLE
    except MemoryError:
        return EXIT_RESOURCE_LIMIT
    try:
        from pypdf.errors import LimitReachedError
    except ImportError:                                  # pragma: no cover — pypdf viejo
        LimitReachedError = ()
    import io

    try:
        # Tope de descompresión por flujo (la 6.19.0 trae 75 MB por defecto en cada filtro).
        # `overwrite_configuration` existe desde la 6.x; sin ella la versión no sirve y falla cerrado.
        pypdf.overwrite_configuration(
            maximum_declared_stream_length=max_flujo,
            array_based_stream_maximum_output_length=max_flujo,
            jbig2_maximum_output_length=max_flujo,
            lzw_maximum_output_length=max_flujo,
            run_length_maximum_output_length=max_flujo,
            zlib_maximum_output_length=max_flujo,
            image_maximum_buffer_size=max_flujo,
        )
        lector = pypdf.PdfReader(io.BytesIO(datos))
        if lector.is_encrypted:
            return EXIT_PROTECTED
        if len(lector.pages) > max_paginas:
            return EXIT_RESOURCE_LIMIT
        escritos = 0
        salida = sys.stdout.buffer
        partes = []
        for pagina in lector.pages:
            texto = pagina.extract_text() or ""
            escritos += len(texto) + 1
            if escritos > max_texto:
                return EXIT_RESOURCE_LIMIT
            partes.append(texto)
        salida.write("\n".join(partes).encode("utf-8", errors="replace"))
        salida.flush()
        return EXIT_OK
    except MemoryError:
        return EXIT_RESOURCE_LIMIT
    except LimitReachedError:
        return EXIT_RESOURCE_LIMIT
    except Exception as exc:  # noqa: BLE001 — cualquier fallo del parser ⇒ no analizable
        nombre = type(exc).__name__
        if "NotDecrypted" in nombre or "Decrypt" in nombre:
            return EXIT_PROTECTED
        return EXIT_ERROR


if __name__ == "__main__":
    try:
        codigo = main(sys.argv)
    except MemoryError:
        codigo = EXIT_RESOURCE_LIMIT
    except Exception:  # noqa: BLE001
        codigo = EXIT_ERROR
    sys.stdout.flush()
    sys.exit(codigo)
