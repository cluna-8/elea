"""Catálogo de entidades custom (spec 016, extensión post-implementación).

Permite sumar patrones estructurados nuevos (regex + contexto) al motor de
detección real SIN tocar código ni redeployar — viven en
``Guardian.config.custom_entities`` (guardian_type="pii_masking"), el mismo
lugar donde ya vivía ``custom_names``. Un asistente de IA puede REDACTAR un
borrador a partir de una descripción en lenguaje natural (``draft_entity``),
pero el borrador NUNCA se activa solo: `create_custom_entity` es un paso
separado y explícito (revisión humana obligatoria, Constraint de seguridad —
un regex generado por IA y activado sin mirar es exactamente el tipo de riesgo
que este producto existe para evitar).

Seguridad del regex (antes de aceptar CUALQUIER patrón, generado por IA o
tipeado a mano): compila, tiene un largo acotado, y se prueba con un timeout
corto contra strings adversariales típicos de ReDoS (grupos anidados con
cuantificador) ANTES de poder guardarse — un patrón que cuelga el proceso de
detección en producción es un DoS real sobre el firewall completo.
"""
import asyncio
import functools
import logging
import multiprocessing as mp
import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..models.guardian import Guardian
from ..services.guardian_service import GuardianService
from . import ai_engine_client
from . import _redos_worker

logger = logging.getLogger("basa-secure-gateway.entity-catalog")

MAX_PATTERN_LEN = 200
REGEX_TIMEOUT_S = 2.0
# Strings adversariales cortos: si el regex tarda más de REGEX_TIMEOUT_S contra
# alguno de estos, se rechaza. No es un analizador estático de ReDoS (eso es un
# proyecto en sí mismo) — es un backstop de tiempo real, suficiente para
# atrapar los casos catastróficos típicos (cuantificadores anidados).
_ADVERSARIAL_INPUTS = ["a" * 40 + "!", "0" * 40 + "!", ("ab" * 25) + "!"]

# Heurística estática (best-effort, no exhaustiva): cuantificador anidado dentro
# de un grupo que a su vez está cuantificado — la forma más común de ReDoS
# catastrófico ((a+)+, (a*)*, (a+)*, (a*)+...). Se corre ANTES de ejecutar nada.
_NESTED_QUANTIFIER_RE = re.compile(r"\([^()]*[+*][^()]*\)[+*]")


# ── Aislamiento del threadpool (#106, defensa en profundidad) ──────────────────
# Modelo de amenaza: NO DoS anónimo. `POST /custom-entities` y `draft_entity` están
# admin-gated, así que el atacante es un ADMIN HOSTIL o una PROMPT INJECTION (las
# listas de test strings del draft las escribe el LLM desde `description`). Aun así
# el riesgo es real: cada validación ReDoS spawnea subprocesos y BLOQUEA su hilo hasta
# ~REGEX_TIMEOUT_S por input; `POST /custom-entities` es un handler que corría en el
# threadpool anyio de Starlette (~40 hilos compartidos con TODOS los endpoints `def`
# síncronos), así que un pico de validaciones catastróficas dejaba sin hilos al resto
# del backend.
#
# Solución: un executor DEDICADO y ACOTADO (cola propia + `max_workers` chico) al que
# se derivan TODAS las validaciones ReDoS/subprocesos, vía `run_in_executor` desde los
# handlers `async`. Con esto (1) el event loop no se bloquea, (2) el threadpool anyio
# general NUNCA lo toca una validación, y (3) la concurrencia de validaciones (y por
# ende de subprocesos `spawn`) queda topeada — un pico hostil se ENCOLA en este executor
# en vez de starvar los hilos de los demás endpoints. `max_workers` NO es un semáforo
# suelto adrede: un `Semaphore` acotaría los subprocesos pero dejaría a los hilos
# llamantes bloqueados en `acquire()` (seguirían consumiendo el threadpool general); un
# executor propio además REUBICA los hilos fuera de ese pool, que es lo que aísla.
REDOS_VALIDATION_CONCURRENCY = max(1, min(8, int(os.environ.get("REDOS_VALIDATION_CONCURRENCY", "3"))))
_VALIDATION_EXECUTOR = ThreadPoolExecutor(
    max_workers=REDOS_VALIDATION_CONCURRENCY, thread_name_prefix="redos-validation")


async def _offload_bounded(fn, *args):
    """Corre `fn(*args)` (bloqueante: spawnea subprocesos y los espera) en el executor
    DEDICADO y ACOTADO de validación ReDoS, no en el threadpool anyio general (#106).
    Solo se llama desde código `async` (hay loop corriendo)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_VALIDATION_EXECUTOR, fn, *args)


class UnsafePatternError(ValueError):
    """El patrón no compila, tiene forma catastrófica conocida, es demasiado
    largo, o no responde a tiempo (riesgo ReDoS)."""


class InvalidEntityTypeError(ValueError):
    """`entity_type` no cumple el formato requerido para viajar seguro dentro
    del placeholder `[TIPO_idx_nonce]` (FR-017)."""


class DuplicateEntityTypeError(ValueError):
    """Ya existe una entidad custom ACTIVA con el mismo `entity_type` (FR-016,
    SC-008) — se rechaza la creación en vez de dejar una activación fantasma."""


MAX_ENTITY_TYPE_LEN = 64
# El placeholder es [TIPO_idx_nonce] (PH_TYPE_RE en basa_guardian_policy.py) —
# TIPO debe ser MAYÚSCULAS/dígitos/guion_bajo, empezando con letra, sin '[' ']'
# ni '_' pegado a un patrón de nonce que confunda el parser de carry-split.
_ENTITY_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _validate_entity_type(entity_type: str) -> str:
    """Normaliza a mayúsculas y valida el formato — levanta InvalidEntityTypeError
    si no es seguro para el formato de placeholder. Se llama SIEMPRE antes de
    persistir, igual que `validate_pattern_safety` con el regex (FR-017)."""
    normalized = (entity_type or "").strip().upper()
    if not normalized or len(normalized) > MAX_ENTITY_TYPE_LEN:
        raise InvalidEntityTypeError(
            f"entity_type vacío o mayor a {MAX_ENTITY_TYPE_LEN} caracteres.")
    if not _ENTITY_TYPE_RE.match(normalized):
        raise InvalidEntityTypeError(
            f"entity_type '{entity_type}' inválido — debe ser MAYÚSCULAS/dígitos/guion_bajo, "
            "empezando con una letra (p.ej. HISTORIA_CLINICA_ES). Esto evita romper el formato "
            "del placeholder reversible [TIPO_idx_nonce] usado por el enmascaramiento."
        )
    return normalized


# Tramo FINAL del presupuesto `timeout_s`, NO un extra: `_run_in_process` le descuenta
# esta misma cantidad al `join`, así que un patrón nunca dispone de más de
# `REGEX_TIMEOUT_S` en total (si esto se sumara, el umbral real pasaría a ser 2.2s y
# `REGEX_TIMEOUT_S` sería mentira — hallazgo del review del #98).
# Lo que se acepta durante la gracia es un resultado COMPLETO que llega tarde, nunca
# cómputo extra: el worker hace `put` como última sentencia, de modo que si hay dato en
# la cola el match ya estaba decidido; lo único que faltaba era cruzar el pipe.
_QUEUE_GRACE_S = 0.2

# Piso del `join` para que un `timeout_s` chico (tests) no quede en cero o negativo al
# descontarle la gracia.
_MIN_JOIN_S = 0.1

# Techo del `join` final tras `kill()` (#106). Sin timeout, un hijo en estado D
# (uninterruptible sleep — I/O de disco/FS colgado) NO responde ni al SIGKILL y el
# `p.join()` pelado colgaría el hilo PARA SIEMPRE. Con techo, tras el intento best-effort
# el hilo se libera; si el hijo sigue vivo se loguea y se abandona (lo cosechará el
# `_cleanup()` de un `start()` futuro cuando por fin muera) — nunca se bloquea el hilo.
_KILL_JOIN_TIMEOUT_S = 2.0

# Serializa el ciclo de vida de los subprocesos ENTRE HILOS (#98). Restricción no
# deducible del código: `Process.start()` llama por dentro a
# `multiprocessing.process._cleanup()`, que recorre el set GLOBAL `_children` y cosecha
# con `waitpid(WNOHANG)` a los hijos de CUALQUIER hilo, no solo a los propios. Entre ese
# `waitpid` y la asignación de `returncode` hay una ventana en la que otro hilo que
# consulte SU hijo recibe ECHILD, `poll()` devuelve None e `is_alive()` MIENTE: reporta
# vivo un proceso que ya terminó bien. Como todo `_cleanup()` ocurre dentro de `start()`,
# tomar este mismo lock antes de preguntar por la vida garantiza no observar nunca ese
# estado a medio actualizar. Sin el lock, dos altas concurrentes de entidad custom (la
# ruta POST /custom-entities es `def`, o sea threadpool de FastAPI) rechazaban un regex
# sano con un 422 espurio "no respondió a tiempo": ~2-8 falsos timeouts cada 120
# subprocesos, y ~43% de fallo en el test de concurrencia del catálogo.
#
# INVARIANTE (#98/#106): TODO ciclo de vida de un `multiprocessing.Process` en el backend
# —`start()` y las consultas de vida (`is_alive`/`poll`)— debe pasar por este lock (o por
# `_sigue_vivo`). Un `ProcessPoolExecutor` o un `Process.start()` suelto en OTRO servicio del
# mismo proceso reintroduce la carrera de `_cleanup()` descrita arriba (su `start()` cosecha
# NUESTROS hijos sin tomar este lock). Hoy NO hay lint/test que lo impida; queda como
# follow-up deliberado del #106 (un meta-guard/linter es desproporcionado para este PR).
_PROC_LIFECYCLE_LOCK = threading.Lock()


def _sigue_vivo(p) -> bool:
    """Consulta de vida a prueba de la carrera de `_cleanup()` (#98) — ver
    `_PROC_LIFECYCLE_LOCK`. Nunca preguntar `p.is_alive()` suelto desde un hilo."""
    with _PROC_LIFECYCLE_LOCK:
        return p.is_alive()


def _run_in_process(pattern: str, text: str, timeout_s: float = REGEX_TIMEOUT_S) -> Optional[bool]:
    """Corre `re.search(pattern, text)` en un PROCESO aparte (contexto `spawn`) —
    no un hilo. Se probó primero con un hilo + `future.result(timeout=...)`: NO
    alcanza, porque el motor `re` de stdlib no libera el GIL durante el
    backtracking — un hilo catastrófico bloquea a TODOS los hilos del proceso,
    incluido el que controla el timeout, así que ni el propio watchdog llega a
    correr a tiempo (bug real, encontrado probando `(a|aa)+$` con curl — colgó
    el proceso entero en vez de rechazar en ~1s). Un proceso aparte tiene su
    propio GIL: si no termina a tiempo, se mata de verdad con `terminate()`/`kill()`.

    `spawn` (no `fork`): forkear desde un proceso con threads vivos (FastAPI/
    uvicorn) puede heredar locks tomados por otros hilos que nunca se liberan
    en el hijo (otro bug real encontrado antes que este). El worker vive en
    `_redos_worker.py`, sin imports pesados, para que el arranque de `spawn`
    (que sí tiene que reimportar el módulo) sea rápido y no infle el timeout.

    Devuelve: `None` si no respondió a tiempo (o crasheó) — el caller decide qué
    hacer con la ambigüedad; `True`/`False` = resultado REAL de `re.search`."""
    ctx = mp.get_context("spawn")
    q: "mp.Queue" = ctx.Queue()
    p = ctx.Process(target=_redos_worker.match_worker, args=(pattern, text, q))
    try:
        with _PROC_LIFECYCLE_LOCK:
            p.start()
        # `join` va FUERA del lock a propósito: es la espera larga y serializarla
        # ahogaría a los demás hilos. Que su `poll()` interno pierda la carrera y no
        # registre el `returncode` es inocuo, porque quien decide abajo es la cola.
        # Se acorta en `_QUEUE_GRACE_S` para que join + gracia sumen `timeout_s` y el
        # presupuesto TOTAL siga siendo el que promete `REGEX_TIMEOUT_S`.
        p.join(max(timeout_s - _QUEUE_GRACE_S, _MIN_JOIN_S))

        # El resultado en la cola MANDA sobre `is_alive()` (#98): en la carrera descrita
        # en `_PROC_LIFECYCLE_LOCK` el hijo ya terminó y ya dejó su resultado — lo único
        # equivocado es la contabilidad del padre. Preguntar primero por la cola
        # convierte ese caso en la respuesta correcta en vez de en un falso "no
        # respondió a tiempo".
        try:
            return q.get(timeout=_QUEUE_GRACE_S)
        except Exception:
            return None  # nada dentro del presupuesto -> resultado desconocido
    finally:
        # El hijo no sobrevive a esta función, salga por donde salga (#98). Hoy el
        # camino de la cola implica que ya terminó (el `put` del worker es su última
        # sentencia), así que este bloque no se activa — pero el contrato del docstring
        # es "si no termina a tiempo, se mata de verdad", y con un `return` temprano
        # afuera del `finally` ese contrato dependía de un detalle del worker. Si el
        # worker evoluciona (reportar progreso parcial, reusar el proceso), sin esto
        # quedaría un proceso colgado por cada validación.
        if _sigue_vivo(p):
            p.terminate()
            p.join(timeout=_KILL_JOIN_TIMEOUT_S)
            if _sigue_vivo(p):
                p.kill()
                # `join` ACOTADO, no pelado (#106): un hijo en estado D ignora el SIGKILL
                # y un `p.join()` sin timeout colgaría este hilo indefinidamente. Se compone
                # con `_PROC_LIFECYCLE_LOCK` (#98) igual que el `join` de arriba: la espera va
                # FUERA del lock (no serializar la espera larga), solo `_sigue_vivo` lo toma.
                p.join(timeout=_KILL_JOIN_TIMEOUT_S)
                if _sigue_vivo(p):
                    logger.warning(
                        "Subproceso de validación ReDoS %s sigue vivo tras terminate()+kill() "
                        "y join(timeout=%ss) — probable estado D (uninterruptible). Se abandona "
                        "best-effort para no bloquear el hilo; lo cosechará un start() futuro.",
                        getattr(p, "pid", "?"), _KILL_JOIN_TIMEOUT_S,
                    )


def _matches_within_timeout(pattern: str, text: str, timeout_s: float = REGEX_TIMEOUT_S) -> bool:
    """Usado por `validate_pattern_safety`: solo importa si TERMINÓ a tiempo, no
    el resultado del match (los strings adversariales son fijos, no reales)."""
    return _run_in_process(pattern, text, timeout_s) is not None


def validate_pattern_safety(pattern: str) -> None:
    """Levanta UnsafePatternError si el patrón no es seguro para correr en
    producción sobre texto de terceros. Se llama SIEMPRE antes de persistir,
    sin excepción para patrones "solo de prueba" — no hay modo simulado.

    Dos capas: (1) heurística estática de cuantificadores anidados — instantánea,
    sin ejecutar nada; (2) ejecución real contra strings adversariales cortos con
    timeout por hilo — atrapa casos que la heurística no reconoce. Ninguna de las
    dos es una prueba formal de ausencia de ReDoS (eso requeriría un analizador
    de autómatas propio, fuera de alcance) — es un backstop pragmático."""
    if not pattern or len(pattern) > MAX_PATTERN_LEN:
        raise UnsafePatternError(f"Patrón vacío o mayor a {MAX_PATTERN_LEN} caracteres.")
    if _NESTED_QUANTIFIER_RE.search(pattern):
        raise UnsafePatternError(
            "El patrón tiene un cuantificador anidado dentro de un grupo cuantificado "
            "(forma típica de ReDoS catastrófico, p.ej. (a+)+). Reescribilo sin anidar "
            "cuantificadores."
        )
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        raise UnsafePatternError(f"Regex inválido: {e}") from e

    for adversarial in _ADVERSARIAL_INPUTS:
        if not _matches_within_timeout(compiled, adversarial):
            raise UnsafePatternError(
                "El patrón no respondió a tiempo contra un input adversarial "
                "(riesgo de denegación de servicio). Simplificalo antes de guardarlo."
            )


MAX_TEST_STRING_LEN = 300
# Cap de CANTIDAD de test strings (#106). `MAX_TEST_STRING_LEN` topea el LARGO de cada
# string, NO cuántas hay: `test_pattern` spawnea UN subproceso por string, y en el path
# `draft_entity` las listas las escribe el LLM desde `description` (influenciables por
# prompt injection). Sin techo, ~100 strings = ~7 min de un hilo bloqueado. Se truncan a
# este cap ANTES de spawnear nada, y el recorte se REPORTA en el resultado (honesto, no
# silencioso), nunca se descarta en silencio.
MAX_TEST_STRINGS = 25


def test_pattern(pattern: str, positives: List[str], negatives: List[str]) -> Dict[str, Any]:
    """Corre el patrón (ya validado como seguro contra los 3 strings adversariales
    fijos) contra los casos de prueba — que pueden venir de la IA, no de un humano.
    `validate_pattern_safety` no es una prueba universal de ausencia de ReDoS (solo
    prueba largos fijos ~40-45 chars); un test_positive/test_negative más largo
    podría igual colgarse contra un patrón "safe" a esa longitud (blowup polinómico,
    no solo exponencial) — mismo backstop de proceso+timeout que `validate_pattern_safety`,
    aplicado acá también, más un cap de largo para no legitimar strings absurdos.

    Cap de CANTIDAD (#106): un subproceso por string sin techo es un DoS de hilo si la
    lista viene inflada (LLM/prompt injection). Se trunca a `MAX_TEST_STRINGS` ANTES de
    spawnear, y el recorte se reporta (`truncated`) en vez de descartarse en silencio.
    El cap vive acá —en la frontera que spawnea— para proteger a CUALQUIER caller, no
    solo a `draft_entity`."""
    positives = list(positives or [])
    negatives = list(negatives or [])
    pos_total, neg_total = len(positives), len(negatives)
    truncated = pos_total > MAX_TEST_STRINGS or neg_total > MAX_TEST_STRINGS
    positives = positives[:MAX_TEST_STRINGS]
    negatives = negatives[:MAX_TEST_STRINGS]

    def _run(t: str) -> bool:
        t = t[:MAX_TEST_STRING_LEN]
        result = _run_in_process(pattern, t)
        return bool(result)  # None (timeout/ambiguo) -> "no matcheó", nunca "sí matcheó"

    pos_results = [{"text": t, "matched": _run(t)} for t in positives]
    neg_results = [{"text": t, "matched": _run(t)} for t in negatives]
    all_positives_matched = all(r["matched"] for r in pos_results)
    all_negatives_clean = all(not r["matched"] for r in neg_results)
    return {
        "positives": pos_results,
        "negatives": neg_results,
        "all_positives_matched": all_positives_matched,
        "all_negatives_clean": all_negatives_clean,
        "looks_correct": all_positives_matched and all_negatives_clean,
        # Aviso honesto: se probaron a lo sumo `MAX_TEST_STRINGS` por lista; si el caller
        # (o el LLM) mandó más, `truncated` es True y `*_total` dice cuántos se recibieron.
        "truncated": truncated,
        "max_test_strings": MAX_TEST_STRINGS,
        "positives_total": pos_total,
        "negatives_total": neg_total,
    }


_DRAFT_SYSTEM_PROMPT = """Sos un asistente que ayuda a un compliance officer a definir un patrón de \
detección de datos personales/estructurados (PII) para un firewall de IA. Te dan una descripción en \
lenguaje natural de qué dato hay que detectar en texto en español. Respondé EXCLUSIVAMENTE con un JSON \
(sin markdown, sin texto alrededor) con esta forma exacta:

{
  "entity_type": "NOMBRE_EN_MAYUSCULAS_CON_GUION_BAJO",
  "regex": "patrón Python re, con \\\\b límites de palabra donde tenga sentido, SIN flags inline",
  "score": 0.0 a 1.0 (confianza base del patrón solo, sin contexto),
  "context": ["2 a 5 palabras en español que suelen aparecer cerca de este dato"],
  "test_positive": ["3 ejemplos de texto que DEBERÍAN matchear el regex"],
  "test_negative": ["3 ejemplos de texto parecido que NO deberían matchear (para chequear falsos positivos)"]
}

Reglas: el regex nunca debe ser catastróficamente lento (evitá cuantificadores anidados tipo (a+)+); \
preferí patrones acotados en longitud; si el dato no tiene un formato estructurado real (p.ej. "temas \
sensibles" en vez de un ID con formato), respondé igual con tu mejor esfuerzo pero con "score" bajo (< 0.5)."""


async def draft_entity(description: str) -> Dict[str, Any]:
    """Pide al motor de IA (mismo AIEngineClient que ya usa el backend, vía LiteLLM)
    un borrador de patrón a partir de una descripción en lenguaje natural. NO
    persiste nada — el resultado se valida (seguridad + test cases) y se devuelve
    para revisión humana."""
    import json

    payload = {
        "model": "gemini-2.5-flash-lite",
        "messages": [
            {"role": "system", "content": _DRAFT_SYSTEM_PROMPT},
            {"role": "user", "content": description},
        ],
        "stream": False,
        "max_tokens": 500,
        "temperature": 0.1,
    }
    try:
        data = await ai_engine_client._post("/v1/chat/completions", payload)
    except ai_engine_client.AIEngineClientError as e:
        raise UnsafePatternError(f"El motor de IA no está disponible para redactar el borrador: {e}") from e

    # Todo lo que depende de la FORMA de la respuesta del motor de IA (no solo el
    # JSON parsing) va en un único bloque protegido — una respuesta 200 pero con
    # forma inesperada (choices vacío, score no-numérico, etc.) es tan posible
    # como un JSON malformado, y debe terminar igual en un 422 prolijo, no en un
    # 500 (bug encontrado en review: el float()/indexado vivían FUERA del try).
    try:
        raw_content = data["choices"][0]["message"]["content"]
        # Tolerante a que el modelo envuelva el JSON en ```json ... ``` pese a la instrucción.
        cleaned = raw_content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        draft = json.loads(cleaned)
        pattern = draft.get("regex", "")
        score = float(draft.get("score", 0.5))
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as e:
        raise UnsafePatternError(f"El motor de IA devolvió un borrador no parseable: {e}") from e

    # `validate_pattern_safety` y `test_pattern` corren regex en subprocesos y los
    # esperan con `join(timeout)` — sincrónico y de hasta ~15-20s con un patrón malicioso.
    # Este es el ÚNICO endpoint `async def` que los llama: hacerlo en línea congelaba el
    # event loop del backend entero (nadie más era atendido mientras tanto). Se derivan al
    # executor DEDICADO y ACOTADO (#106): fuera del threadpool anyio general y con la
    # concurrencia de validaciones topeada, para que un pico hostil no starve al backend.
    await _offload_bounded(validate_pattern_safety, pattern)  # UnsafePatternError -> el draft NO se devuelve

    # Cap de CANTIDAD sobre las listas del LLM (#106): `test_pattern` trunca a
    # `MAX_TEST_STRINGS` y lo reporta. Se devuelven las listas REALMENTE probadas (las
    # mismas truncadas), no las crudas — coherente con `test_result`, sin mentir sobre qué
    # se ejecutó.
    raw_positive = list(draft.get("test_positive") or [])
    raw_negative = list(draft.get("test_negative") or [])
    test_result = await _offload_bounded(test_pattern, pattern, raw_positive, raw_negative)

    return {
        "entity_type": draft.get("entity_type", "CUSTOM"),
        "regex": pattern,
        "score": max(0.0, min(1.0, score)),
        "context": draft.get("context", []),
        "test_positive": raw_positive[:MAX_TEST_STRINGS],
        "test_negative": raw_negative[:MAX_TEST_STRINGS],
        "test_result": test_result,
        "ai_generated": True,
    }


def _select_pii_guardian(db: Session, tenant_id, *, for_update: bool) -> Optional[Guardian]:
    """LA fila `pii_masking` que gobierna, con el MISMO desempate determinista que los
    lectores de tráfico (#104) y de chat (#119): la ACTIVA más antigua
    (`is_active=true ORDER BY created_at, id LIMIT 1`).

    Por qué acá también (#119): el catálogo custom tiene que ESCRIBIRSE en la misma fila que
    TODOS los planos LEEN. Antes esto era `.first()` sin orden ni filtro de actividad, así que
    con dos `pii_masking` activos el panel podía escribir una entidad custom en una fila y el
    tráfico leer OTRA — la entidad no aplicaba, en silencio (hallazgo BAJO del gate del #118).

    Fallback deliberado (sin filtrar `is_active`) cuando NO hay ninguna fila activa: mantiene
    operativo el catálogo (crear/listar/borrar) aunque el admin tenga el guardián apagado
    —comportamiento previo al #119 con un único guardián—. No reintroduce el bug: si hay al
    menos UNA activa gana esa (el único caso donde el determinismo importa, porque los lectores
    sólo miran filas activas); sin ninguna activa los lectores tampoco leen nada, así que no hay
    divergencia posible — la entidad simplemente no aplica hasta que se active la fila, que es
    justo lo que un guardián apagado debe hacer."""
    base = (db.query(Guardian)
            .filter(Guardian.tenant_id == tenant_id,
                    Guardian.guardian_type == "pii_masking")
            .order_by(Guardian.created_at, Guardian.id))
    activa = base.filter(Guardian.is_active.is_(True))
    if for_update:
        activa = activa.with_for_update()
    guardian = activa.first()
    if guardian is not None:
        return guardian
    if for_update:
        base = base.with_for_update()
    return base.first()


def _pii_guardian(db: Session, tenant_id, *, for_update: bool = False) -> Guardian:
    """`for_update=True` (T045): toma un lock de fila Postgres (`SELECT ... FOR
    UPDATE`) para las operaciones de escritura (create/delete) — sin esto, dos
    requests concurrentes leen el mismo `custom_entities`, cada una modifica su
    copia en memoria y comitea, y la que comitea después pisa a la primera
    (lost update). El lock serializa: la segunda transacción espera a que la
    primera comitee antes de leer, así que ve la lista ya actualizada.

    La fila la elige `_select_pii_guardian` (la ACTIVA más antigua): ver ahí el porqué del
    desempate determinista del #119 —escritor y lectores tienen que coincidir en LA misma fila."""
    guardian = _select_pii_guardian(db, tenant_id, for_update=for_update)
    if guardian is None:
        # Auto-provisiona el catálogo por default (mismo que dispara GET /guardians) —
        # sin esto, pedir el catálogo de entidades custom ANTES de haber abierto el
        # panel de guardianes una vez rompía con un 500 (bug encontrado con curl).
        GuardianService.get_or_create_default_guardians(db)
        guardian = _select_pii_guardian(db, tenant_id, for_update=for_update)
    if not guardian:
        raise ValueError("No existe el guardián de enmascaramiento PII para este tenant.")
    return guardian


def list_custom_entities(db: Session, tenant_id) -> List[Dict[str, Any]]:
    guardian = _pii_guardian(db, tenant_id)
    return guardian.config.get("custom_entities", [])


def create_custom_entity(
    db: Session, tenant_id, *, name: str, entity_type: str, regex: str,
    score: float = 0.5, context: Optional[List[str]] = None,
    region: str = "eu", ai_generated: bool = False,
) -> Dict[str, Any]:
    """Persiste un patrón YA REVISADO por un humano (venga de un borrador de IA
    editado/aceptado, o tipeado a mano) — este es el único punto donde algo se
    vuelve activo en el firewall real."""
    validate_pattern_safety(regex)  # re-valida siempre, no confía en que el caller ya lo hizo
    normalized_type = _validate_entity_type(entity_type)  # T043 (FR-017)

    # T045: lock de fila — desde acá hasta el commit, ninguna otra transacción
    # puede leer/escribir esta misma fila de Guardian (Postgres FOR UPDATE).
    guardian = _pii_guardian(db, tenant_id, for_update=True)
    custom_entities = guardian.config.get("custom_entities", [])

    # T044 (FR-016/SC-008): rechazar duplicados de entity_type entre ACTIVAS —
    # más simple y determinístico que confiar en que Presidio dedupe recognizers
    # ad-hoc por nombre (no verificado) y más honesto que dejar una activación
    # fantasma sin ningún aviso al compliance officer.
    if any(e.get("entity_type") == normalized_type and e.get("status") == "active"
           for e in custom_entities):
        raise DuplicateEntityTypeError(
            f"Ya existe una entidad custom activa con entity_type '{normalized_type}'. "
            "Editá o desactivá la existente antes de crear otra con el mismo tipo."
        )

    entity = {
        "id": str(uuid.uuid4()),
        "name": name,
        "entity_type": normalized_type,
        "regex": regex,
        "score": max(0.0, min(1.0, score)),
        "context": context or [],
        "region": region,
        "ai_generated": ai_generated,
        "status": "active",
    }
    custom_entities.append(entity)
    guardian.config = {**guardian.config, "custom_entities": custom_entities}
    flag_modified(guardian, "config")
    db.commit()
    logger.info("Nueva entidad custom '%s' (%s) agregada al catálogo del tenant %s",
                name, normalized_type, tenant_id)
    return entity


async def create_custom_entity_async(db: Session, tenant_id, **kwargs) -> Dict[str, Any]:
    """Envoltorio `async` de `create_custom_entity` para el handler `POST /custom-entities`
    (#106). Deriva TODO el cuerpo bloqueante (la validación ReDoS —que spawnea subprocesos y
    puede tardar ~12s con un regex catastrófico— y el commit) al executor DEDICADO y ACOTADO,
    NO al threadpool anyio general. Así un admin hostil que dispare N altas con regex
    catastróficos ya no puede dejar sin hilos al resto de los endpoints síncronos: sus
    validaciones se ENCOLAN en este executor (concurrencia topeada a REDOS_VALIDATION_CONCURRENCY)
    mientras el event loop y el threadpool general siguen atendiendo todo lo demás.

    La Session se usa exclusivamente dentro del hilo del executor (uso secuencial de un solo
    hilo, no compartida en concurrencia) — patrón estándar de FastAPI async + Session sync.
    Se re-valida el regex adentro (invariante de `create_custom_entity`), no se debilita."""
    return await _offload_bounded(functools.partial(create_custom_entity, db, tenant_id, **kwargs))


def delete_custom_entity(db: Session, tenant_id, entity_id: str) -> None:
    guardian = _pii_guardian(db, tenant_id, for_update=True)  # T045
    custom_entities = guardian.config.get("custom_entities", [])
    remaining = [e for e in custom_entities if e.get("id") != entity_id]
    if len(remaining) == len(custom_entities):
        raise ValueError("Entidad custom no encontrada.")
    guardian.config = {**guardian.config, "custom_entities": remaining}
    flag_modified(guardian, "config")
    db.commit()
