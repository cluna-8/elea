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
import logging
import multiprocessing as mp
import re
import threading
import uuid
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


# Gracia para leer el resultado del hijo DESPUÉS de que `join()` volvió (#98). No es
# tiempo de cómputo: el hijo ya terminó, es solo margen para que el dato termine de
# cruzar el pipe de la Queue. En el camino feliz `get()` devuelve al instante y no
# suma latencia; solo se paga entero cuando el hijo murió sin reportar.
_QUEUE_GRACE_S = 0.2

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
    with _PROC_LIFECYCLE_LOCK:
        p.start()
    # `join` va FUERA del lock a propósito: es la espera larga (hasta `timeout_s`) y
    # serializarla ahogaría a los demás hilos. Que su `poll()` interno pierda la carrera
    # y no registre el `returncode` es inocuo, porque quien decide acá abajo es la cola.
    p.join(timeout_s)

    # El resultado en la cola MANDA sobre `is_alive()` (#98): en la carrera descrita en
    # `_PROC_LIFECYCLE_LOCK` el hijo ya terminó y ya dejó su resultado — lo único
    # equivocado es la contabilidad del padre. Preguntar primero por la cola convierte
    # ese caso en la respuesta correcta en vez de en un falso "no respondió a tiempo".
    try:
        return q.get(timeout=_QUEUE_GRACE_S)
    except Exception:
        pass  # sin resultado: recién ahora tiene sentido preguntar si sigue corriendo

    if _sigue_vivo(p):
        p.terminate()
        p.join(timeout=2.0)
        if _sigue_vivo(p):
            p.kill()
            p.join()
        return None
    return None  # el proceso murió sin reportar -> resultado desconocido


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


def test_pattern(pattern: str, positives: List[str], negatives: List[str]) -> Dict[str, Any]:
    """Corre el patrón (ya validado como seguro contra los 3 strings adversariales
    fijos) contra los casos de prueba — que pueden venir de la IA, no de un humano.
    `validate_pattern_safety` no es una prueba universal de ausencia de ReDoS (solo
    prueba largos fijos ~40-45 chars); un test_positive/test_negative más largo
    podría igual colgarse contra un patrón "safe" a esa longitud (blowup polinómico,
    no solo exponencial) — mismo backstop de proceso+timeout que `validate_pattern_safety`,
    aplicado acá también, más un cap de largo para no legitimar strings absurdos."""
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
    # event loop del backend entero (nadie más era atendido mientras tanto). En hilo
    # aparte, el bloqueo queda contenido en la request que lo provocó.
    await asyncio.to_thread(validate_pattern_safety, pattern)  # UnsafePatternError -> el draft NO se devuelve
    test_result = await asyncio.to_thread(
        test_pattern, pattern, draft.get("test_positive", []), draft.get("test_negative", []))

    return {
        "entity_type": draft.get("entity_type", "CUSTOM"),
        "regex": pattern,
        "score": max(0.0, min(1.0, score)),
        "context": draft.get("context", []),
        "test_positive": draft.get("test_positive", []),
        "test_negative": draft.get("test_negative", []),
        "test_result": test_result,
        "ai_generated": True,
    }


def _pii_guardian(db: Session, tenant_id, *, for_update: bool = False) -> Guardian:
    """`for_update=True` (T045): toma un lock de fila Postgres (`SELECT ... FOR
    UPDATE`) para las operaciones de escritura (create/delete) — sin esto, dos
    requests concurrentes leen el mismo `custom_entities`, cada una modifica su
    copia en memoria y comitea, y la que comitea después pisa a la primera
    (lost update). El lock serializa: la segunda transacción espera a que la
    primera comitee antes de leer, así que ve la lista ya actualizada."""
    query = db.query(Guardian).filter(
        Guardian.tenant_id == tenant_id, Guardian.guardian_type == "pii_masking"
    )
    if for_update:
        query = query.with_for_update()
    guardian = query.first()
    if not guardian:
        # Auto-provisiona el catálogo por default (mismo que dispara GET /guardians) —
        # sin esto, pedir el catálogo de entidades custom ANTES de haber abierto el
        # panel de guardianes una vez rompía con un 500 (bug encontrado con curl).
        GuardianService.get_or_create_default_guardians(db)
        query = db.query(Guardian).filter(
            Guardian.tenant_id == tenant_id, Guardian.guardian_type == "pii_masking"
        )
        if for_update:
            query = query.with_for_update()
        guardian = query.first()
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


def delete_custom_entity(db: Session, tenant_id, entity_id: str) -> None:
    guardian = _pii_guardian(db, tenant_id, for_update=True)  # T045
    custom_entities = guardian.config.get("custom_entities", [])
    remaining = [e for e in custom_entities if e.get("id") != entity_id]
    if len(remaining) == len(custom_entities):
        raise ValueError("Entidad custom no encontrada.")
    guardian.config = {**guardian.config, "custom_entities": remaining}
    flag_modified(guardian, "config")
    db.commit()
