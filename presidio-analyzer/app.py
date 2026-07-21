"""Servidor propio (thin) sobre `presidio_analyzer.AnalyzerEngine` — spec 016.

Por qué un servidor propio y no la imagen oficial de Microsoft tal cual: necesitamos
un contrato HTTP exacto (`ad_hoc_recognizers` con `deny_list` para nombres
personalizados editables desde el panel + patrones regex para DNI/CUIL/pasaporte,
ver `specs/016-real-nlp-masking/contracts/presidio-analyzer-http.md`) y control total
sobre el modelo NLP cargado (español, `conf/es.yaml`). Es una capa fina sobre la
librería `presidio-analyzer` (no un fork del proyecto Presidio — Principio VII, never
fork: acá Presidio es una dependencia de librería, igual que cualquier otro paquete
pip del repo).

No hace masking/anonimización — solo detecta y devuelve spans. El reemplazo
reversible lo sigue haciendo `basa_guardian_policy.PlaceholderMap` (research.md §1:
el Anonymizer de Presidio hace sustitución irreversible, no sirve al moat del
producto).
"""
import logging
import os
import re
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI
from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider
from pydantic import BaseModel

logger = logging.getLogger("presidio-analyzer-es")

CONF_FILE = os.environ.get("NLP_CONF_FILE", str(Path(__file__).parent / "conf" / "es.yaml"))
LANGUAGE = "es"

_provider = NlpEngineProvider(conf_file=CONF_FILE)
_nlp_engine = _provider.create_engine()
_analyzer = AnalyzerEngine(nlp_engine=_nlp_engine, supported_languages=[LANGUAGE])

app = FastAPI(title="Basa NLP Entity Detector (interno)")


class PatternSpec(BaseModel):
    name: str
    regex: str
    score: float = 0.75


class AdHocRecognizerSpec(BaseModel):
    name: str
    supported_entity: str
    supported_language: str = LANGUAGE
    patterns: Optional[list[PatternSpec]] = None
    deny_list: Optional[list[str]] = None
    # Palabras que, cerca del match, suben el score (p.ej. "pasaporte"/"passport").
    # Clave para patrones de baja precisión propia (formatos que varían por país).
    context: Optional[list[str]] = None


class AnalyzeRequest(BaseModel):
    text: str
    language: str = LANGUAGE
    entities: Optional[list[str]] = None
    ad_hoc_recognizers: Optional[list[AdHocRecognizerSpec]] = None


class DetectedEntity(BaseModel):
    start: int
    end: int
    entity_type: str
    score: float


def _build_ad_hoc(spec: AdHocRecognizerSpec) -> PatternRecognizer:
    patterns = None
    if spec.patterns:
        patterns = [Pattern(name=p.name, regex=p.regex, score=p.score) for p in spec.patterns]
    return PatternRecognizer(
        supported_entity=spec.supported_entity,
        name=spec.name,
        supported_language=spec.supported_language,
        patterns=patterns,
        deny_list=spec.deny_list,
        context=spec.context,
        # Presidio compila los patrones con re.IGNORECASE por default (global_regex_flags) —
        # rompe patrones como PASSPORT ([A-Z0-9]{6,9}) pensados para distinguir mayúsculas de
        # prosa normal: sin esto, la propia palabra "pasaporte" (9 letras minúsculas) matchea
        # su propio patrón. Case-sensitive para reconocedores con patrones; irrelevante para
        # deny_list (Presidio la matchea aparte).
        global_regex_flags=re.DOTALL | re.MULTILINE if patterns else None,
    )


@app.get("/health")
def health():
    return {"status": "ok", "language": LANGUAGE}


@app.post("/analyze", response_model=list[DetectedEntity])
def analyze(req: AnalyzeRequest):
    ad_hoc = [_build_ad_hoc(s) for s in (req.ad_hoc_recognizers or [])]
    results = _analyzer.analyze(
        text=req.text,
        language=req.language,
        entities=req.entities,
        ad_hoc_recognizers=ad_hoc or None,
    )
    return [
        DetectedEntity(start=r.start, end=r.end, entity_type=r.entity_type, score=r.score)
        for r in results
    ]
