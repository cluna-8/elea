"""API admin de la config del auto-router semántico (spec 030, US2 · T011).

Contrato: `specs/030-semantic-auto-router/contracts/router-config-api.md`.
Schema y reglas de validación: `data-model.md` §1.

Dos endpoints sobre el MISMO fichero caliente que lee el runtime del router
(`auto_router.json` del volumen `litellm_config`):

- `GET  /api/v1/chat/router-config` → la config + los campos COMPUTADOS que el panel
  necesita para señalar roturas (`default_model_ok`, `embedding_model_ok`, `target_ok`
  por ruta, `config_error`).
- `PUT  /api/v1/chat/router-config` → valida, escribe atómicamente y devuelve lo releído.

Y un tercero que NO toca el fichero (iteración de UX sobre US2):

- `POST /api/v1/chat/router-config/generate-utterances` → propone frases de calibración
  para una ruta usando el modelo LOCAL del cliente. Ruteo automático significa que el
  humano declara la INTENCIÓN («Código y análisis»), no que se siente a inventar veinte
  ejemplos: eso lo escribe una máquina. Lo devuelto es una PROPUESTA — el guardado sigue
  siendo el PUT, con el admin editando lo que quiera antes.

Tres decisiones que este módulo sostiene:

1. **Los computados no se persisten.** Son una foto del catálogo del motor EN ESTE
   INSTANTE (el admin puede borrar un modelo un segundo después de guardar). Guardarlos
   sería escribir en disco un estado derivado que envejece mal, y por eso el PUT los
   descarta del cuerpo entrante en vez de confiar en que el cliente los omita.
2. **El GET nunca devuelve 500.** Config ausente o corrupta ⇒ 200 con defaults seguros
   (`enabled: false`, rutas vacías) + `config_error: true`. Un panel que revienta con un
   JSON roto deja al admin sin la única pantalla desde la que podría arreglarlo; y el
   runtime ya degrada al default por su cuenta (FR-004), así que el 500 no protegería nada.
3. **La existencia del `target_model` en el catálogo NO se valida al guardar** (data-model
   §1): el catálogo cambia después igual. La ruta rota se SEÑALA (`target_ok: false`) y el
   runtime cae al default.
"""
import copy
import json
import logging
import os
import re
from typing import Any

import httpx
import yaml
from fastapi import APIRouter, Body, Depends, HTTPException, status

from ..auth.rbac import require_role
from ..services import ai_engine_client, auto_router_service
# El catálogo se lee con EXACTAMENTE el mismo helper de path que `GET /chat/models`
# (chat.py): el panel tiene que comparar contra lo que el dropdown ofrece de verdad, no
# contra una segunda resolución de path que puede divergir del plano chat.
#
# `_default_local_model` se REUSA por el mismo motivo, no por comodidad: la pregunta
# «¿cuál es TU modelo local?» ya tiene una respuesta en el producto (la que usa el alta de
# modelos para elegir el respaldo), y dos respuestas distintas a la misma pregunta en una
# instalación con varios Ollama es exactamente lo que confunde al admin.
from .chat import _default_local_model, _get_config_path as _engine_config_path

router = APIRouter(prefix="/chat", tags=["Auto Router"])
logger = logging.getLogger("basa-secure-gateway.router-config")

# Mismo guard que el resto de endpoints de gestión del plano chat (register_model,
# delete_model, PUT /fallbacks): sesión JWT válida y rol efectivo admin o developer.
# Fail-closed: sin credencial 401, con rol insuficiente 403. Las virtual keys (sk-*) no
# resuelven a usuario de sesión, así que tampoco llegan acá — por diseño.
_SOLO_ADMIN = Depends(require_role("admin", "developer"))

# Campos COMPUTADOS: sólo salen en el GET, jamás entran al fichero.
_COMPUTADOS_RAIZ = ("default_model_ok", "embedding_model_ok", "config_error")
_COMPUTADO_RUTA = "target_ok"

# ── Generación de frases de calibración ───────────────────────────────────────────
#
# Generosos a propósito: un modelo local chico razonando sobre 10 frases puede tardar
# bastante más que una llamada de administración, y el admin está mirando un spinner que
# él mismo apretó. Cortar a los 10 s del cliente de administración convertiría un caso
# normal (Ollama frío, primer token tras cargar el modelo en RAM) en un error.
_GEN_TIMEOUT = 90.0
# Alta a propósito: lo que se pide es VARIEDAD de forma. Con temperatura baja el modelo
# devuelve diez maneras de decir lo mismo, que para un clasificador semántico son una
# utterance repetida diez veces.
_GEN_TEMPERATURE = 0.8
_GEN_COUNT_DEFAULT = 10
_GEN_COUNT_MAX = 50
# Tope de frases ya cargadas que viajan en el prompt: sirven para que NO repita, y pasadas
# unas decenas dejan de aportar señal y sólo hacen crecer el contexto de un modelo chico.
_GEN_EXISTING_MAX = 60
# Tope del contenido que se escanea buscando el array. Un modelo con thinking largo puede
# devolver mucho texto y el barrido de corchetes es cuadrático en la cantidad de corchetes.
_GEN_MAX_ESCANEO = 20000
_GEN_MAX_CORCHETES = 40

_SIN_MODELO_LOCAL = (
    "No hay modelo local para generar; escribí las frases a mano o registrá un modelo Ollama."
)

_PROMPT_SISTEMA = """Sos un generador de frases de ejemplo para un clasificador semántico.

Recibís una ruta (nombre y descripción) y devolvés SOLO un array JSON de {count} frases.

Reglas:
- Cada frase es CORTA: entre 5 y 10 palabras.
- Español rioplatense, con voseo ("escribí", "armame", "necesito que me pases").
- Son cosas que un usuario le escribiría a un asistente, no descripciones de la ruta.
- Variadas en forma (pregunta, pedido, orden, queja) pero todas fieles a la intención.
- Sin numeración, sin viñetas, sin comentarios, sin texto antes ni después del array.

Respondé exactamente con este formato: ["primera frase", "segunda frase"]"""

# Viñetas y numeración al principio de línea, para el fallback por líneas.
_RE_VINETA = re.compile(r"^\s*(?:[-*•–]|\d+\s*[.)\-])\s*")
# Etiquetas cortas tipo <think> / </think>: se borran antes de partir por líneas.
_RE_ETIQUETA = re.compile(r"</?[a-zA-Z][^>\n]{0,40}>")

# La clase de excepción se captura AL IMPORTAR y no se resuelve por `httpx.` en el `except`:
# los tests reemplazan el módulo `httpx` de acá por un doble que sólo provee `AsyncClient`,
# y un `except httpx.TimeoutException` contra ese doble explotaría por AttributeError justo
# en el camino de error.
_TIMEOUT_DEL_MOTOR = httpx.TimeoutException


def _catalogo_del_motor() -> set:
    """`model_name`s del catálogo real del motor (`model_list` del config.yaml).

    Si el config no se puede leer se devuelve conjunto vacío: los computados quedan en
    `false` (señal honesta de "no verificable") y el endpoint sigue respondiendo 200.
    """
    try:
        with open(_engine_config_path(), "r") as fichero:
            datos = yaml.safe_load(fichero) or {}
    except Exception as exc:  # noqa: BLE001 — el catálogo es best-effort para el panel
        logger.warning("No se pudo leer el catálogo del motor para los computados: %s", exc)
        return set()
    return {
        entrada.get("model_name")
        for entrada in (datos.get("model_list") or [])
        if isinstance(entrada, dict) and entrada.get("model_name")
    }


def _defaults_seguros() -> dict:
    """Copia PROFUNDA del default del servicio (`enabled: false`, rutas vacías).

    Profunda a propósito: `DEFAULT_CONFIG` es un dict de módulo con una lista mutable
    dentro; una copia superficial la compartiría y un accidente en la respuesta se
    convertiría en un cambio permanente del default del proceso.
    """
    return copy.deepcopy(auto_router_service.DEFAULT_CONFIG)


def _leer_para_panel() -> tuple:
    """(config, config_error). Nunca lanza: el panel siempre recibe algo servible.

    `config_error: true` cubre los dos casos en que lo que hay en disco NO es una config
    válida y el admin está viendo defaults (contrato §GET): fichero ausente y fichero
    ilegible/corrupto. Ausente cuenta porque el fichero viaja en el seed del perfil y lo
    copia el release al volumen: que falte es un despliegue incompleto, no un estado
    normal — y el panel debe decirlo en vez de fingir una config vacía legítima.
    """
    try:
        ruta = auto_router_service.get_config_path()
        if not os.path.exists(ruta):
            logger.info("auto_router.json ausente en %s: el panel recibe defaults seguros", ruta)
            return _defaults_seguros(), True
        return auto_router_service.load_config(), False
    except Exception as exc:  # noqa: BLE001 — contrato: el GET nunca es 500
        logger.warning("auto_router.json ilegible (%s): el panel recibe defaults seguros", exc)
        return _defaults_seguros(), True


def _con_computados(config: dict, *, config_error: bool) -> dict:
    """La config tal cual está en disco + los campos derivados del catálogo.

    Las rutas se copian preservando SÓLO las claves que traen: no se rellenan `description`
    ni `tier` con `null`. Una clave presente con valor nulo rompe a los consumidores que
    hacen `.get(campo, default)` — el default no aplica cuando la clave existe.
    """
    catalogo = _catalogo_del_motor()
    rutas = []
    for ruta in config.get("routes") or []:
        if not isinstance(ruta, dict):
            continue
        salida = dict(ruta)
        salida[_COMPUTADO_RUTA] = salida.get("target_model") in catalogo
        rutas.append(salida)

    respuesta = dict(config)
    respuesta["routes"] = rutas
    respuesta["default_model_ok"] = config.get("default_model") in catalogo
    respuesta["embedding_model_ok"] = config.get("embedding_model") in catalogo
    respuesta["config_error"] = config_error
    return respuesta


def _sin_computados(payload: dict) -> dict:
    """Quita los campos computados del cuerpo entrante (ver decisión 1 del módulo).

    El panel hace GET → editar → PUT con el MISMO objeto, así que los computados vuelven
    aunque el contrato diga que el body va sin ellos. Se descartan en silencio; el resto
    del objeto se respeta tal cual llegó (nada de whitelist: un campo nuevo del schema no
    tiene que morir en este filtro).
    """
    limpio = {clave: valor for clave, valor in payload.items() if clave not in _COMPUTADOS_RAIZ}
    rutas = limpio.get("routes")
    if isinstance(rutas, list):
        limpio["routes"] = [
            {clave: valor for clave, valor in ruta.items() if clave != _COMPUTADO_RUTA}
            if isinstance(ruta, dict) else ruta
            for ruta in rutas
        ]
    return limpio


@router.get("/router-config", dependencies=[_SOLO_ADMIN])
def get_router_config():
    """Config del router + computados. 200 siempre (contrato §GET)."""
    config, config_error = _leer_para_panel()
    return _con_computados(config, config_error=config_error)


@router.put("/router-config", dependencies=[_SOLO_ADMIN])
def put_router_config(payload: dict[str, Any] = Body(...)):
    """Valida (422 con detalle), escribe atómicamente y devuelve el config RELEÍDO.

    Releído y no el entrante: lo que el panel muestra después de guardar tiene que ser lo
    que quedó en disco, que es lo que el runtime va a leer en la siguiente consulta.
    """
    entrante = _sin_computados(payload)

    errores = auto_router_service.validate_config(entrante)
    if errores:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=errores)

    try:
        auto_router_service.save_config(entrante)
    except Exception as exc:  # noqa: BLE001 — escritura fallida se reporta, no se traga
        logger.error("No se pudo guardar auto_router.json: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo guardar la configuración del router.",
        )

    config, config_error = _leer_para_panel()
    return _con_computados(config, config_error=config_error)


# ══ POST /router-config/generate-utterances ═══════════════════════════════════════
#
# Por qué el modelo tiene que ser LOCAL y no "el mejor disponible": las frases se derivan
# del nombre y la descripción de una ruta, que en una instalación real describen el negocio
# del cliente ("Consultas de expedientes de socios", "Reclamos de facturación"). Mandar eso
# a un proveedor externo para ahorrarle tipeo al admin sería regalar justamente lo que el
# producto promete que no sale del host — y encima facturado. Sin modelo local no se
# genera: se lo decimos y el admin escribe a mano.


def _modelo_generador() -> str | None:
    """El modelo LOCAL con el que se generan las frases, o `None` si no hay ninguno.

    Delega en la misma regla que el resto del producto (`_default_local_model`): el
    `default_model` del router si su entrada del catálogo es Ollama, si no el primer local
    declarado en el `model_list`.
    """
    try:
        with open(_engine_config_path(), "r") as fichero:
            datos = yaml.safe_load(fichero) or {}
    except Exception as exc:  # noqa: BLE001 — sin catálogo legible no hay modelo elegible
        logger.warning("No se pudo leer el catálogo del motor para generar frases: %s",
                       type(exc).__name__)
        return None
    return _default_local_model(datos)


def _mensajes_generacion(nombre: str, descripcion: str, count: int, existentes: list) -> list:
    """Los dos mensajes del pedido: reglas fijas en el sistema, la ruta en el usuario."""
    partes = [f"Ruta: {nombre}"]
    if descripcion:
        partes.append(f"Descripción: {descripcion}")
    if existentes:
        listado = "\n".join(f"- {frase}" for frase in existentes)
        partes.append(
            "Estas frases YA están cargadas. Generá frases COMPLEMENTARIAS: no las repitas "
            "ni las reformules, cubrí otras maneras de pedir lo mismo.\n" + listado
        )
    partes.append(f"Devolvé {count} frases nuevas, sólo el array JSON.")
    return [
        {"role": "system", "content": _PROMPT_SISTEMA.format(count=count)},
        {"role": "user", "content": "\n\n".join(partes)},
    ]


def _candidatos_array(texto: str):
    """Subcadenas `[...]` del contenido, de la más CORTA a la más larga por cada apertura.

    Corta primero a propósito: un modelo con thinking suele escribir corchetes en el
    razonamiento antes del array real, y el candidato corto que no sea JSON válido se
    descarta enseguida en vez de tragarse medio contenido.
    """
    recorte = texto[:_GEN_MAX_ESCANEO]
    aperturas = [i for i, c in enumerate(recorte) if c == "["][:_GEN_MAX_CORCHETES]
    cierres = [j for j, c in enumerate(recorte) if c == "]"][:_GEN_MAX_CORCHETES]
    for inicio in aperturas:
        for fin in cierres:
            if fin > inicio:
                yield recorte[inicio:fin + 1]


def _frases_del_array(contenido: str) -> list:
    """El PRIMER array JSON de strings que aparezca en el contenido, o lista vacía.

    Se exige que el array tenga strings no vacíos y no sólo que parsee: un `[1, 2, 3]` del
    razonamiento parsea perfecto y no es lo que se buscaba. Con el filtro, un array así se
    descarta y el barrido sigue hasta el array de frases real.
    """
    for candidato in _candidatos_array(contenido):
        try:
            valor = json.loads(candidato)
        except ValueError:
            continue
        if not isinstance(valor, list):
            continue
        frases = [item.strip() for item in valor if isinstance(item, str) and item.strip()]
        if frases:
            return frases
    return []


def _limpiar_linea(linea: str) -> str:
    """Una línea suelta convertida en frase: sin viñeta, sin corchetes, sin comillas."""
    limpia = _RE_VINETA.sub("", linea).strip()
    limpia = limpia.strip("[]").strip()
    limpia = limpia.rstrip(",").strip()
    limpia = limpia.strip('"').strip("'").strip("“”«»").strip()
    return limpia.rstrip(",").strip()


def _despues_del_razonamiento(contenido: str) -> str:
    """Lo que el modelo escribió DESPUÉS de pensar, cuando el bloque se puede distinguir.

    Sólo para el fallback por líneas: ahí cada línea del razonamiento se convertiría en una
    "frase" y el admin tendría que borrar el monólogo a mano. Si no hay cierre —o no queda
    nada después— se devuelve todo: perder el contenido sería peor que arrastrar ruido.
    """
    _, cierre, despues = contenido.rpartition("</think>")
    return despues if cierre and despues.strip() else contenido


def _frases_de_lineas(contenido: str) -> list:
    """Fallback: líneas no vacías. Peor que el array, pero mejor que devolver nada.

    Existe porque el modelo local es chico y el formateo es lo primero que se le escapa.
    Que el admin reciba diez frases con una que borra de un click es mejor producto que un
    error que lo manda a escribir las diez a mano.
    """
    sin_etiquetas = _RE_ETIQUETA.sub(" ", _despues_del_razonamiento(contenido))
    return [frase for frase in (_limpiar_linea(l) for l in sin_etiquetas.splitlines()) if frase]


def _sin_repetidas(frases: list, existentes: list, count: int) -> list:
    """Dedup case-insensitive contra las existentes y contra sí misma, recortado a `count`.

    Case-insensitive porque para el clasificador «Escribí una función» y «escribí una
    función» son el mismo vector: guardar las dos gasta una llamada de embedding por cada
    una y no agrega ninguna señal.
    """
    vistas = {f.strip().casefold() for f in existentes if isinstance(f, str) and f.strip()}
    salida = []
    for frase in frases:
        clave = frase.casefold()
        if clave in vistas:
            continue
        vistas.add(clave)
        salida.append(frase)
        if len(salida) >= count:
            break
    return salida


def _campos_generacion(payload: dict) -> tuple:
    """(nombre, descripcion, count, existentes) validados. 422 con motivo si algo no va."""
    def _rechazar(motivo):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=motivo)

    nombre = payload.get("name")
    if not isinstance(nombre, str) or not nombre.strip():
        _rechazar("Falta el nombre de la ruta: sin intención declarada no hay nada que generar.")

    descripcion = payload.get("description")
    if descripcion is not None and not isinstance(descripcion, str):
        _rechazar("«description» tiene que ser texto.")

    count = payload.get("count", _GEN_COUNT_DEFAULT)
    if count is None:
        count = _GEN_COUNT_DEFAULT
    # `bool` es subclase de `int`: sin este filtro, `true` pediría 1 frase en silencio.
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= _GEN_COUNT_MAX:
        _rechazar(f"«count» tiene que ser un entero entre 1 y {_GEN_COUNT_MAX}.")

    existentes = payload.get("existing") or []
    if not isinstance(existentes, list):
        _rechazar("«existing» tiene que ser una lista de frases.")
    existentes = [f.strip() for f in existentes if isinstance(f, str) and f.strip()]

    return nombre.strip(), (descripcion or "").strip(), count, existentes[:_GEN_EXISTING_MAX]


async def _pedir_frases(modelo: str, mensajes: list) -> dict:
    """`POST {motor}/v1/chat/completions` con la master key (patrón de `ai_engine_client`).

    Se llama al motor y no a Ollama directo para que la generación pase por el MISMO plano
    que todo lo demás: el catálogo del motor es el que sabe a qué host apunta el modelo
    local del cliente, y duplicar esa resolución acá sería un segundo cableado que envejece
    aparte. `_BASE_URL`/`_headers()` se leen del módulo (no se importan por valor) para que
    la master key siga teniendo un único dueño.
    """
    async with httpx.AsyncClient(timeout=_GEN_TIMEOUT) as cliente:
        respuesta = await cliente.post(
            f"{ai_engine_client._BASE_URL}/v1/chat/completions",
            json={
                "model": modelo,
                "messages": mensajes,
                "temperature": _GEN_TEMPERATURE,
                "stream": False,
            },
            headers=ai_engine_client._headers(),
        )
        respuesta.raise_for_status()
        return respuesta.json()


def _contenido_de(data: dict) -> str:
    """El texto de la respuesta del motor, tolerante al shape (y al thinking separado)."""
    choices = (data or {}).get("choices") or []
    if not choices:
        return ""
    mensaje = (choices[0] or {}).get("message") or {}
    contenido = mensaje.get("content")
    if isinstance(contenido, str) and contenido.strip():
        return contenido
    # Algunos modelos con razonamiento mandan todo por `reasoning_content` y dejan
    # `content` vacío. El array suele estar ahí igual, así que se intenta antes de rendirse.
    alterno = mensaje.get("reasoning_content")
    return alterno if isinstance(alterno, str) else ""


@router.post("/router-config/generate-utterances", dependencies=[_SOLO_ADMIN])
async def generate_utterances(payload: dict[str, Any] = Body(...)):
    """Propone frases de calibración para una ruta con el modelo local. NO guarda nada.

    No toca `auto_router.json` a propósito: el admin tiene que poder pedir frases, borrar
    las que no le gustan y recién ahí guardar con el PUT. Un endpoint que generara Y
    persistiera convertiría un «a ver qué sale» en un cambio de ruteo en producción.
    """
    nombre, descripcion, count, existentes = _campos_generacion(payload)

    modelo = _modelo_generador()
    if not modelo:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=_SIN_MODELO_LOCAL)

    try:
        data = await _pedir_frases(modelo, _mensajes_generacion(nombre, descripcion, count,
                                                                existentes))
    except _TIMEOUT_DEL_MOTOR:
        logger.warning("Generación de frases: el modelo local no respondió a tiempo (%ss)",
                       int(_GEN_TIMEOUT))
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="El modelo local tardó demasiado en responder. Probá de nuevo o escribí "
                   "las frases a mano.",
        )
    except Exception as exc:  # noqa: BLE001 — el motor falla de muchas formas, todas son 502
        # Sin `str(exc)`: el mensaje de httpx y el cuerpo del motor llevan el host interno.
        logger.warning("Generación de frases: el motor falló (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="El motor no pudo generar las frases. Revisá que el modelo local esté "
                   "levantado.",
        )

    contenido = _contenido_de(data)
    frases = _frases_del_array(contenido) or _frases_de_lineas(contenido)
    frases = _sin_repetidas(frases, existentes, count)

    if not frases:
        # 502 y no un 200 con lista vacía: para el panel «no hay nada nuevo» y «el modelo
        # devolvió cualquier cosa» tienen que verse distinto, o el admin aprieta el botón
        # tres veces sin entender por qué no pasa nada.
        logger.warning("Generación de frases para la ruta '%s': el modelo local no devolvió "
                       "frases utilizables", nombre)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="El modelo local no devolvió frases utilizables. Probá de nuevo o escribí "
                   "las frases a mano.",
        )

    # Metadata-only (Principio VII): ruta, cuántas y con qué modelo. Las frases NO se
    # loguean — describen el negocio del cliente y no tienen por qué vivir en el log.
    logger.info("Frases de calibración generadas para la ruta '%s': %d con el modelo local %s",
                nombre, len(frases), modelo)

    return {"utterances": frases, "model_used": modelo}
