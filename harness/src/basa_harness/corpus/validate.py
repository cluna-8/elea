"""Validador del corpus PII — el gate de calidad del dataset (spec 035, T009).

Implementa el «Validador» de ``contracts/corpus-format.md`` (regla 8): enum de tipos,
spans dentro de rango y sin duplicados exactos, checksum ``value == text[start:end]``
(post-NFC), normalización NFC verificada, docs limpios presentes y regresiones del #63
presentes. Devuelve una lista de errores accionables (cadena por error); lista vacía =
dataset válido. El dataset no se versiona sin este validador en verde.

Nota de ruta: el contrato cita ``harness/src/corpus/validate.py``; el scaffold del
módulo (T001) usa el paquete ``basa_harness`` (``harness/src/basa_harness/corpus/``).
Se sigue el scaffold — diferencia cosmética de layout señalada al orquestador.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Union

from . import oracle
from .oracle import ENTITY_TYPES

_SOURCES = frozenset({"generated", "regression-63", "handmade"})
_DIFFICULTIES = frozenset({"easy", "medium", "hard"})
# Caracteres que no deben colgar en los bordes de un span (regla 2: spans ajustados).
_DANGLING = " \t\n\r.,;:"

# FIX-C6: validación de CHECKSUM del valor por tipo estructurado. Sin esto, una entrada
# MANUAL con un NIF de letra incorrecta (o IBAN/tarjeta/teléfono inválido) pasaría el
# gate y el detector real la perdería → el recall del runner del core mentiría. Solo
# aplica a `entities` (etiquetas positivas), NUNCA a `forbidden` (hard-negatives, que
# a propósito NO son valores válidos de ese tipo — p.ej. FAC-2026-* como PHONE_NUMBER).
_STRUCTURED_CHECKS = {
    "ES_NIF": (oracle.is_valid_nif, "NIF con letra de control inválida"),
    "ES_NIE": (oracle.is_valid_nie, "NIE con letra de control inválida"),
    "IBAN_CODE": (oracle.is_valid_iban_es, "IBAN con control mod-97 inválido"),
    "CREDIT_CARD": (lambda v: oracle.is_valid_luhn(v.replace(" ", "")),
                    "tarjeta que no pasa Luhn"),
    "PHONE_NUMBER": (lambda v: oracle.PHONE_RE.fullmatch(v) is not None,
                     "teléfono que no matchea el reconocedor nacional español"),
}


def validate_doc(doc: object, *, index: Union[int, str, None] = None) -> list[str]:
    """Valida un único documento. Devuelve la lista (posiblemente vacía) de errores."""
    tag = f"[doc {index}]" if index is not None else "[doc]"
    errors: list[str] = []

    if not isinstance(doc, dict):
        return [f"{tag} no es un objeto JSON"]

    doc_id = doc.get("id")
    if isinstance(doc_id, str) and doc_id:
        tag = f"[{doc_id}]"
    else:
        errors.append(f"{tag} falta 'id' (string no vacío)")

    text = doc.get("text")
    if not isinstance(text, str):
        errors.append(f"{tag} 'text' ausente o no es string")
        return errors  # sin texto no se pueden validar spans

    if unicodedata.normalize("NFC", text) != text:
        errors.append(f"{tag} 'text' no está en NFC")

    # Metadatos top-level (regla 5).
    if doc.get("source") not in _SOURCES:
        errors.append(f"{tag} 'source' inválido: {doc.get('source')!r} (esperado {sorted(_SOURCES)})")
    if doc.get("difficulty") not in _DIFFICULTIES:
        errors.append(f"{tag} 'difficulty' inválido: {doc.get('difficulty')!r}")
    if doc.get("lang") != "es":
        errors.append(f"{tag} 'lang' debe ser 'es', es {doc.get('lang')!r}")
    if doc.get("region") != "eu":
        errors.append(f"{tag} 'region' debe ser 'eu', es {doc.get('region')!r}")

    entities = doc.get("entities")
    if not isinstance(entities, list):
        errors.append(f"{tag} 'entities' ausente o no es lista")
        entities = []

    n = len(text)
    seen_spans: set[tuple[int, int]] = set()
    for i, ent in enumerate(entities):
        errors += _validate_span(ent, text, n, tag, f"entities[{i}]",
                                 require_value=True, seen=seen_spans)

    forbidden = doc.get("forbidden", [])
    if forbidden is not None and not isinstance(forbidden, list):
        errors.append(f"{tag} 'forbidden' no es lista")
        forbidden = []
    seen_forbidden: set[tuple[int, int]] = set()
    for i, fb in enumerate(forbidden or []):
        errors += _validate_span(fb, text, n, tag, f"forbidden[{i}]",
                                 require_value=False, seen=seen_forbidden)

    return errors


def _validate_span(item: object, text: str, n: int, tag: str, where: str, *,
                   require_value: bool, seen: set) -> list[str]:
    errors: list[str] = []
    if not isinstance(item, dict):
        return [f"{tag} {where} no es un objeto"]

    etype = item.get("entity_type")
    if etype not in ENTITY_TYPES:
        errors.append(f"{tag} {where} entity_type desconocido: {etype!r} "
                      f"(enum cerrado {sorted(ENTITY_TYPES)})")

    start, end = item.get("start"), item.get("end")
    if not isinstance(start, int) or not isinstance(end, int) or isinstance(start, bool) \
            or isinstance(end, bool):
        errors.append(f"{tag} {where} start/end deben ser enteros: {start!r}/{end!r}")
        return errors
    if not (0 <= start < end <= n):
        errors.append(f"{tag} {where} span fuera de rango [0,{n}]: [{start},{end})")
        return errors

    if (start, end) in seen:
        errors.append(f"{tag} {where} span duplicado exacto [{start},{end})")
    seen.add((start, end))

    substr = text[start:end]
    if substr != substr.strip() or (substr and (substr[0] in _DANGLING or substr[-1] in _DANGLING)):
        errors.append(f"{tag} {where} span con espacios/puntuación colgante: {substr!r}")

    value = item.get("value")
    if require_value and value is None:
        errors.append(f"{tag} {where} falta 'value' (obligatorio en entities)")
    if value is not None:
        if not isinstance(value, str):
            errors.append(f"{tag} {where} 'value' no es string")
        elif value != substr:
            errors.append(f"{tag} {where} checksum roto: value={value!r} != text[{start}:{end}]={substr!r}")
        # FIX-C6: checksum estructural del valor, solo para entidades positivas.
        elif require_value and etype in _STRUCTURED_CHECKS:
            ok, motivo = _STRUCTURED_CHECKS[etype]
            if not ok(value):
                errors.append(f"{tag} {where} {motivo}: {value!r} — el detector real no lo detectaría")

    return errors


def validate_dataset(path: Union[str, Path], *, require_clean: bool = True,
                     require_regressions: bool = True) -> list[str]:
    """Valida un dataset JSONL entero. Devuelve errores accionables (vacío = válido).

    Args:
        path: ruta al ``.jsonl``.
        require_clean: exige al menos un doc limpio (``entities: []``) — falsos
            positivos globales (regla 4).
        require_regressions: exige al menos un doc ``source == "regression-63"``
            (regla 8). Poné ``False`` para validar lotes puramente generados.
    """
    path = Path(path)
    errors: list[str] = []
    docs: list[dict] = []

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        return [f"no se pudo leer {path}: {e}"]
    if raw.startswith("﻿"):
        errors.append(f"{path}: el archivo tiene BOM (debe ser UTF-8 sin BOM)")

    ids: set[str] = set()
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"línea {lineno}: JSON inválido: {e}")
            continue
        docs.append(doc)
        errors += validate_doc(doc, index=lineno)
        if isinstance(doc, dict):
            did = doc.get("id")
            if isinstance(did, str):
                if did in ids:
                    errors.append(f"línea {lineno}: 'id' duplicado: {did!r}")
                ids.add(did)

    if not docs:
        errors.append(f"{path}: el dataset está vacío")
        return errors

    if require_clean and not any(
            isinstance(d, dict) and d.get("entities") == [] for d in docs):
        errors.append(f"{path}: no hay ningún doc limpio (entities: []) — regla 4")
    if require_regressions and not any(
            isinstance(d, dict) and d.get("source") == "regression-63" for d in docs):
        errors.append(f"{path}: no hay regresiones del #63 (source: 'regression-63') — regla 8")

    return errors
