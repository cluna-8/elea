"""Bloque corpus del harness ITV (spec 035, #107).

Artefacto compartido con el core: (a) canarios/mezclas de tráfico del harness y (b)
el gate de precision/recall del NLP del core contra la imagen real de sentinel-nlp. El
contrato del formato vive en ``specs/035-load-harness/contracts/corpus-format.md``.
"""
from __future__ import annotations

from .canaries import generate_canaries
from .generator import GENERATOR_VERSION, generate
from .validate import validate_dataset, validate_doc

__all__ = [
    "generate",
    "GENERATOR_VERSION",
    "generate_canaries",
    "validate_dataset",
    "validate_doc",
]
