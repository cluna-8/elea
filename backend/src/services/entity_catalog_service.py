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
import logging
import re
import signal
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..models.guardian import Guardian
from . import ai_engine_client

logger = logging.getLogger("basa-secure-gateway.entity-catalog")

MAX_PATTERN_LEN = 200
REGEX_TIMEOUT_S = 1.0
# Strings adversariales cortos: si el regex tarda más de REGEX_TIMEOUT_S contra
# alguno de estos, se rechaza. No es un analizador estático de ReDoS (eso es un
# proyecto en sí mismo) — es un backstop de tiempo real, suficiente para
# atrapar los casos catastróficos típicos (cuantificadores anidados).
_ADVERSARIAL_INPUTS = ["a" * 30 + "!", "0" * 30 + "!", ("ab" * 20) + "!"]


class UnsafePatternError(ValueError):
    """El patrón no compila, es demasiado largo, o no responde a tiempo (riesgo ReDoS)."""


class _RegexTimeout(Exception):
    pass


def _alarm_handler(signum, frame):
    raise _RegexTimeout()


def _run_with_timeout(fn, *args, timeout_s: float = REGEX_TIMEOUT_S):
    """Corta la ejecución con SIGALRM — backstop real de proceso, no cooperativo
    (un regex catastrófico no "coopera" liberando el hilo)."""
    old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
    try:
        signal.setitimer(signal.ITIMER_REAL, timeout_s)
        return fn(*args)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)


def validate_pattern_safety(pattern: str) -> None:
    """Levanta UnsafePatternError si el patrón no es seguro para correr en
    producción sobre texto de terceros. Se llama SIEMPRE antes de persistir,
    sin excepción para patrones "solo de prueba" — no hay modo simulado."""
    if not pattern or len(pattern) > MAX_PATTERN_LEN:
        raise UnsafePatternError(f"Patrón vacío o mayor a {MAX_PATTERN_LEN} caracteres.")
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        raise UnsafePatternError(f"Regex inválido: {e}") from e

    for adversarial in _ADVERSARIAL_INPUTS:
        try:
            _run_with_timeout(compiled.search, adversarial)
        except _RegexTimeout:
            raise UnsafePatternError(
                "El patrón no respondió a tiempo contra un input adversarial "
                "(riesgo de denegación de servicio — posible cuantificador anidado). "
                "Simplificalo antes de guardarlo."
            )


def test_pattern(pattern: str, positives: List[str], negatives: List[str]) -> Dict[str, Any]:
    """Corre el patrón (ya validado como seguro) contra los casos de prueba.
    Devuelve el detalle de qué pasó y qué no — la UI/reviewer humano decide si
    el patrón está listo con esta evidencia, no se auto-aprueba nada."""
    compiled = re.compile(pattern)
    pos_results = [{"text": t, "matched": bool(compiled.search(t))} for t in positives]
    neg_results = [{"text": t, "matched": bool(compiled.search(t))} for t in negatives]
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

    raw_content = data["choices"][0]["message"]["content"]
    try:
        # Tolerante a que el modelo envuelva el JSON en ```json ... ``` pese a la instrucción.
        cleaned = raw_content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        draft = json.loads(cleaned)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        raise UnsafePatternError(f"El motor de IA devolvió un borrador no parseable: {e}") from e

    pattern = draft.get("regex", "")
    validate_pattern_safety(pattern)  # levanta UnsafePatternError si no es seguro — el draft NO se devuelve
    test_result = test_pattern(pattern, draft.get("test_positive", []), draft.get("test_negative", []))

    return {
        "entity_type": draft.get("entity_type", "CUSTOM"),
        "regex": pattern,
        "score": float(draft.get("score", 0.5)),
        "context": draft.get("context", []),
        "test_positive": draft.get("test_positive", []),
        "test_negative": draft.get("test_negative", []),
        "test_result": test_result,
        "ai_generated": True,
    }


def _pii_guardian(db: Session, tenant_id) -> Guardian:
    guardian = db.query(Guardian).filter(
        Guardian.tenant_id == tenant_id, Guardian.guardian_type == "pii_masking"
    ).first()
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

    guardian = _pii_guardian(db, tenant_id)
    entity = {
        "id": str(uuid.uuid4()),
        "name": name,
        "entity_type": entity_type.upper(),
        "regex": regex,
        "score": max(0.0, min(1.0, score)),
        "context": context or [],
        "region": region,
        "ai_generated": ai_generated,
        "status": "active",
    }
    custom_entities = guardian.config.get("custom_entities", [])
    custom_entities.append(entity)
    guardian.config = {**guardian.config, "custom_entities": custom_entities}
    flag_modified(guardian, "config")
    db.commit()
    logger.info("Nueva entidad custom '%s' (%s) agregada al catálogo del tenant %s",
                name, entity_type, tenant_id)
    return entity


def delete_custom_entity(db: Session, tenant_id, entity_id: str) -> None:
    guardian = _pii_guardian(db, tenant_id)
    custom_entities = guardian.config.get("custom_entities", [])
    remaining = [e for e in custom_entities if e.get("id") != entity_id]
    if len(remaining) == len(custom_entities):
        raise ValueError("Entidad custom no encontrada.")
    guardian.config = {**guardian.config, "custom_entities": remaining}
    flag_modified(guardian, "config")
    db.commit()
