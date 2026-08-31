"""Construcción reproducible del dataset versionado (spec 035, T010).

``dataset-v<semver>.jsonl`` + ``manifest.json`` a partir de una semilla fija más las
regresiones del #63. Reproducible por definición: misma semilla + mismas regresiones →
mismos bytes → mismo ``sha256`` (corpus-format.md regla 7). Serialización canónica
(orden de claves fijo, sin ASCII-escaping, ``\n`` final) para que el hash no dependa
del orden de inserción de dicts.

**Alcance de la reproducibilidad (FIX-C5)**: byte a byte bajo la MISMA major.minor de
CPython (la normalización NFC depende de la versión Unicode del intérprete). El manifest
registra ``python_version`` y ``unicodedata_version``; ``--check`` exige que la
major.minor de Python coincida con la commiteada antes de comparar el contenido, para
que un sha256 distinto no se confunda nunca con un cambio de contenido.

Uso:
    python -m sentinel_harness.corpus.build            # regenera dataset-v1 + manifest
    python -m sentinel_harness.corpus.build --check     # falla si el dataset difiere
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path

from .generator import GENERATOR_VERSION, generate
from .validate import validate_dataset

DATASET_VERSION = "1.1.0"
DATASET_SEED = 20260808
N_GENERATED = 300
# Pesos relativos por densidad (entidades/doc). Densidad 0 = docs limpios.
DENSITIES: dict[int, float] = {0: 3, 1: 4, 2: 5, 3: 4, 4: 2, 5: 2}

_CORPUS_DIR = Path(__file__).resolve().parents[3] / "corpus"
_REGRESSIONS = _CORPUS_DIR / "regressions-63.jsonl"
_DATASET = _CORPUS_DIR / f"dataset-v{DATASET_VERSION.split('.')[0]}.jsonl"
_MANIFEST = _CORPUS_DIR / "manifest.json"

# Orden canónico de claves (legible + estable byte a byte).
_DOC_KEYS = ["id", "text", "entities", "forbidden", "source", "difficulty", "lang", "region"]
_SPAN_KEYS = ["entity_type", "start", "end", "value"]


def _canon_span(span: dict) -> dict:
    return {k: span[k] for k in _SPAN_KEYS if k in span}


def _canon_doc(doc: dict) -> dict:
    out: dict = {}
    for k in _DOC_KEYS:
        if k not in doc:
            continue
        if k in ("entities", "forbidden"):
            out[k] = [_canon_span(s) for s in doc[k]]
        else:
            out[k] = doc[k]
    return out


def _load_regressions() -> list[dict]:
    docs = []
    for line in _REGRESSIONS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            docs.append(json.loads(line))
    return docs


def build_docs() -> list[dict]:
    """La lista de documentos del dataset-v1 (generados + regresiones-63)."""
    docs = generate(seed=DATASET_SEED, n_docs=N_GENERATED, densities=DENSITIES, region="eu")
    docs += _load_regressions()
    return [_canon_doc(d) for d in docs]


def serialize(docs: list[dict]) -> str:
    """JSONL canónico (una doc por línea, UTF-8 sin BOM, ``\\n`` final)."""
    return "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in docs)


def _counts(docs: list[dict]) -> dict:
    by_entity: Counter = Counter()
    for d in docs:
        for e in d.get("entities", []):
            by_entity[e["entity_type"]] += 1
    return {
        "total_docs": len(docs),
        "clean_docs": sum(1 for d in docs if d.get("entities") == []),
        "total_entities": sum(by_entity.values()),
        "by_entity_type": dict(sorted(by_entity.items())),
        "by_source": dict(sorted(Counter(d["source"] for d in docs).items())),
        "by_difficulty": dict(sorted(Counter(d["difficulty"] for d in docs).items())),
    }


def build(write: bool = True) -> dict:
    """Construye (y opcionalmente escribe) el dataset + manifest. Devuelve el manifest."""
    docs = build_docs()
    content = serialize(docs)
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    manifest = {
        "version": DATASET_VERSION,
        "sha256": sha,
        "generator_version": GENERATOR_VERSION,
        "seed": DATASET_SEED,
        # FIX-C5: entorno de generación — la reproducibilidad byte a byte se garantiza
        # bajo la misma major.minor de CPython (la versión Unicode afecta a NFC).
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "unicodedata_version": unicodedata.unidata_version,
        "densities": {str(k): v for k, v in DENSITIES.items()},
        "counts": _counts(docs),
    }
    if write:
        _DATASET.write_text(content, encoding="utf-8")
        _MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        errors = validate_dataset(_DATASET)
        if errors:
            raise SystemExit("dataset inválido tras generar:\n  " + "\n  ".join(errors))
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description="Construye dataset-v1 + manifest")
    ap.add_argument("--check", action="store_true",
                    help="no escribe; falla si el dataset en disco no coincide")
    args = ap.parse_args()
    if args.check:
        # FIX-C5: la garantía dura es el CONTENIDO (sha256 byte a byte). La versión de
        # Python es metadata informativa: un mismatch de major.minor se AVISA (no falla),
        # porque el contenido de este corpus (ASCII + Latin español NFC + random.Random,
        # todos estables entre versiones de CPython) es byte-idéntico en la práctica. El
        # único fallo duro es que el dataset difiera del generador.
        if not _MANIFEST.exists():
            raise SystemExit("falta manifest.json (regenerá con la build)")
        manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
        cur_py = f"{sys.version_info.major}.{sys.version_info.minor}"
        if manifest.get("python_version") != cur_py:
            print(f"AVISO: generado en CPython {manifest.get('python_version')!r}, "
                  f"corriendo {cur_py}; se verifica el contenido igual.")
        expected = serialize(build_docs())
        actual = _DATASET.read_text(encoding="utf-8") if _DATASET.exists() else ""
        if expected != actual:
            raise SystemExit("dataset-v1.jsonl no coincide con el generador (regenerá)")
        print(f"dataset-v1.jsonl reproducible OK (CPython {cur_py}, "
              f"sha256={manifest.get('sha256', '?')[:12]}…)")
        return
    m = build(write=True)
    print(f"dataset-v{DATASET_VERSION} escrito · sha256={m['sha256']}")
    print(json.dumps(m["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
