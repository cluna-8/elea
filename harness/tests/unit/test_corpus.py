"""Tests del bloque corpus (spec 035, T009): determinismo, densidades, unicidad de
canarios, conformidad con el ORÁCULO (reconocedores reales del producto) y con el
contrato ``corpus-format.md``, más las regresiones del #63.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

import pytest

from basa_harness.corpus import (
    generate,
    generate_canaries,
    validate_dataset,
    validate_doc,
)
from basa_harness.corpus import build, oracle

REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS_DIR = REPO_ROOT / "harness" / "corpus"
POLICY_SRC = REPO_ROOT / "litellm" / "extensions" / "basa_guardian_policy.py"

# Densidades de muestreo amplio para los tests de oráculo/contrato.
_MIX = {0: 1, 1: 2, 2: 2, 3: 2, 4: 1, 5: 1}


def _all_entities(docs):
    for d in docs:
        for e in d["entities"]:
            yield e


# ── Determinismo ──────────────────────────────────────────────────────────────────

def test_determinismo_misma_semilla():
    a = generate(seed=42, n_docs=50, densities=_MIX)
    b = generate(seed=42, n_docs=50, densities=_MIX)
    assert a == b
    # También byte a byte al serializar (US3 comparabilidad).
    assert json.dumps(a, ensure_ascii=False) == json.dumps(b, ensure_ascii=False)


def test_determinismo_semillas_distintas():
    a = generate(seed=42, n_docs=50, densities=_MIX)
    b = generate(seed=43, n_docs=50, densities=_MIX)
    assert a != b


# ── Densidades ──────────────────────────────────────────────────────────────────

def test_densidad_cero_todos_limpios():
    docs = generate(seed=1, n_docs=30, densities={0: 1})
    assert all(d["entities"] == [] for d in docs)
    assert all("forbidden" not in d for d in docs)


def test_densidad_alta_numero_esperado():
    docs = generate(seed=1, n_docs=25, densities={5: 1})
    assert all(len(d["entities"]) == 5 for d in docs)


def test_densidad_mezcla_incluye_limpios_y_poblados():
    docs = generate(seed=7, n_docs=200, densities=_MIX)
    assert any(d["entities"] == [] for d in docs)
    assert any(len(d["entities"]) >= 4 for d in docs)


# ── Canarios ──────────────────────────────────────────────────────────────────────

def test_canarios_disjuntos_entre_runs():
    a = generate_canaries("run-A", 40)
    b = generate_canaries("run-B", 40)
    vals_a = {c["value"] for c in a}
    vals_b = {c["value"] for c in b}
    assert vals_a and vals_b
    assert vals_a.isdisjoint(vals_b)
    assert a[0]["nonce"] != b[0]["nonce"]


def test_canarios_deterministas_por_run():
    assert generate_canaries("run-A", 20) == generate_canaries("run-A", 20)


def test_canarios_llevan_nonce_y_tipo():
    canaries = generate_canaries("run-X", 10)
    nonce = canaries[0]["nonce"]
    for c in canaries:
        assert c["nonce"] == nonce
        assert c["entity_type"] in oracle.ENTITY_TYPES
        assert nonce in c["canary_id"]
    # El nonce viaja literal en al menos los canarios de email (disjunción garantizada).
    assert any(nonce in c["value"] for c in canaries if c["entity_type"] == "EMAIL_ADDRESS")


def test_canarios_son_pii_detectable():
    """Cada canario debe pasar el checksum/regex de su tipo (si no, no probaría el mask)."""
    for c in generate_canaries("run-oracle", 30):
        et, v = c["entity_type"], c["value"]
        if et == "ES_NIF":
            assert oracle.is_valid_nif(v)
        elif et == "IBAN_CODE":
            assert oracle.is_valid_iban_es(v)
        elif et == "CREDIT_CARD":
            assert oracle.is_valid_luhn(v.replace(" ", ""))
        elif et == "PHONE_NUMBER":
            m = oracle.PHONE_RE.search(v)
            assert m and m.group() == v
        elif et == "EMAIL_ADDRESS":
            assert oracle.EMAIL_RE.fullmatch(v)


def test_canarios_10k_disjuntos_tipos_garantizados():
    """FIX-C3: nonce embebido LITERAL → disjunción GARANTIZADA para EMAIL e IBAN incluso
    a 10 000 runs distintos (su formato admite el nonce completo)."""
    from basa_harness.corpus.canaries import GUARANTEED_DISJOINT_TYPES
    n = 10000
    seen: dict[str, set] = {t: set() for t in GUARANTEED_DISJOINT_TYPES}
    for k in range(n):
        for c in generate_canaries(f"run-{k:05d}", 5):  # 1 canario por tipo
            if c["entity_type"] in GUARANTEED_DISJOINT_TYPES:
                seen[c["entity_type"]].add(c["value"])
    for t in GUARANTEED_DISJOINT_TYPES:
        assert len(seen[t]) == n, f"{t}: {n - len(seen[t])} colisión(es) en {n} runs"


def test_canarios_disjuntos_todos_los_tipos():
    """FIX-C3: a 2 000 runs distintos, TODOS los tipos (incl. NIF/teléfono, acotados por
    el techo de su propio formato) son disjuntos con amplio margen."""
    n = 2000
    seen: dict[str, set] = {}
    for k in range(n):
        for c in generate_canaries(f"run-{k:05d}", 5):
            seen.setdefault(c["entity_type"], set()).add(c["value"])
    for t, vals in seen.items():
        assert len(vals) == n, f"{t}: {n - len(vals)} colisión(es) en {n} runs"


def test_canarios_nonce_literal_en_email():
    """El nonce viaja LITERAL en EMAIL/IBAN → dos runs SIEMPRE difieren en esos tipos."""
    a = {c["entity_type"]: c["value"] for c in generate_canaries("run-A", 5)}
    b = {c["entity_type"]: c["value"] for c in generate_canaries("run-B", 5)}
    na = generate_canaries("run-A", 1)[0]["nonce"]
    assert na in a["EMAIL_ADDRESS"]           # nonce presente, literal
    assert a["EMAIL_ADDRESS"] != b["EMAIL_ADDRESS"]
    assert a["IBAN_CODE"] != b["IBAN_CODE"]   # IBAN inyectivo sobre el nonce


# ── Oráculo: los valores generados matchean los reconocedores REALES ───────────────

def test_valores_generados_pasan_el_oraculo():
    docs = generate(seed=2026, n_docs=400, densities={4: 1, 5: 1, 3: 1})
    counts = {}
    for e in _all_entities(docs):
        et, v = e["entity_type"], e["value"]
        counts[et] = counts.get(et, 0) + 1
        if et == "ES_NIF":
            assert oracle.is_valid_nif(v), v
        elif et == "ES_NIE":
            assert oracle.is_valid_nie(v), v
        elif et == "IBAN_CODE":
            assert oracle.is_valid_iban_es(v), v
        elif et == "CREDIT_CARD":
            assert oracle.is_valid_luhn(v.replace(" ", "")), v
        elif et == "PHONE_NUMBER":
            m = oracle.PHONE_RE.search(v)
            assert m and m.group() == v, v  # el value es EXACTAMENTE lo que matchea el oráculo
        elif et == "EMAIL_ADDRESS":
            assert oracle.EMAIL_RE.fullmatch(v), v
        elif et == "PASSPORT":
            assert re.fullmatch(r"[A-Z0-9]{6,9}", v), v
    # se generaron todos los tipos estructurados con checksum
    for et in ("ES_NIF", "ES_NIE", "IBAN_CODE", "CREDIT_CARD", "PHONE_NUMBER"):
        assert counts.get(et, 0) > 0, f"no se generó ningún {et}"


@pytest.mark.skipif(not POLICY_SRC.exists(), reason="fuente del oráculo no disponible")
def test_patron_telefono_no_derivo_del_producto():
    """El patrón replicado debe seguir presente VERBATIM en basa_guardian_policy.py."""
    src = POLICY_SRC.read_text(encoding="utf-8")
    assert oracle.PHONE_PATTERN in src, "PHONE_PATTERN derivó respecto al producto"


# ── FIX-C4: PASSPORT no coexiste con NIF/NIE en el mismo doc ───────────────────────

def test_passport_excluye_nif_nie_en_mismo_doc():
    docs = generate(seed=123, n_docs=600, densities={3: 1, 4: 1, 5: 1})
    for d in docs:
        tipos = {e["entity_type"] for e in d["entities"]}
        if "PASSPORT" in tipos:
            assert not (tipos & {"ES_NIF", "ES_NIE"}), \
                f"{d['id']}: PASSPORT convive con NIF/NIE — ambigüedad de span (FIX-C4)"
    # y que igualmente se siguen generando pasaportes en el lote
    assert any("PASSPORT" in {e["entity_type"] for e in d["entities"]} for d in docs)


# ── FIX-C2: docs limpios genuinamente diversos ────────────────────────────────────

def test_clean_texts_diversos_y_sin_pii():
    from basa_harness.corpus.generator import _CLEAN_TEXTS
    assert len(set(_CLEAN_TEXTS)) >= 15  # no 6 plantillas reusadas ×10
    docs = generate(seed=5, n_docs=300, densities={0: 1})
    textos = {d["text"] for d in docs}
    assert len(textos) >= 15, f"solo {len(textos)} textos limpios distintos"
    for d in docs:
        assert d["entities"] == [] and "forbidden" not in d
        assert not validate_doc(d)


# ── Contrato: cada doc generado pasa el validador ─────────────────────────────────

def test_docs_generados_conformes_al_contrato():
    docs = generate(seed=99, n_docs=250, densities=_MIX)
    for i, d in enumerate(docs):
        errs = validate_doc(d, index=i)
        assert not errs, errs
        # value == text[start:end] en codepoints, y texto NFC
        assert unicodedata.normalize("NFC", d["text"]) == d["text"]
        for e in d["entities"]:
            assert d["text"][e["start"]:e["end"]] == e["value"]


def test_validador_detecta_tipo_desconocido(tmp_path):
    doc = {"id": "x", "text": "hola PEPE", "entities": [
        {"entity_type": "NOT_A_TYPE", "start": 5, "end": 9, "value": "PEPE"}],
        "source": "generated", "difficulty": "easy", "lang": "es", "region": "eu"}
    p = tmp_path / "bad.jsonl"
    p.write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")
    errs = validate_dataset(p, require_regressions=False, require_clean=False)
    assert any("entity_type desconocido" in e for e in errs)


def test_validador_detecta_checksum_de_span_roto(tmp_path):
    doc = {"id": "x", "text": "IBAN aqui", "entities": [
        {"entity_type": "IBAN_CODE", "start": 0, "end": 4, "value": "OTRO"}],
        "source": "generated", "difficulty": "easy", "lang": "es", "region": "eu"}
    p = tmp_path / "bad.jsonl"
    p.write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")
    errs = validate_dataset(p, require_regressions=False, require_clean=False)
    assert any("checksum roto" in e for e in errs)


def test_validador_detecta_texto_no_nfc(tmp_path):
    # "é" descompuesto (e + combining acute) NO es NFC.
    text = "café"
    doc = {"id": "x", "text": text, "entities": [], "source": "generated",
           "difficulty": "easy", "lang": "es", "region": "eu"}
    p = tmp_path / "bad.jsonl"
    p.write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")
    errs = validate_dataset(p, require_regressions=False, require_clean=False)
    assert any("NFC" in e for e in errs)


# ── FIX-C6: el validador comprueba checksums de los tipos estructurados ────────────

def test_validador_rechaza_nif_con_checksum_invalido(tmp_path):
    # 12345678 -> letra correcta 'Z'; usamos 'A' (inválida). El detector real lo perdería.
    doc = {"id": "x", "text": "NIF: 12345678A.", "entities": [
        {"entity_type": "ES_NIF", "start": 5, "end": 14, "value": "12345678A"}],
        "source": "handmade", "difficulty": "easy", "lang": "es", "region": "eu"}
    p = tmp_path / "bad.jsonl"
    p.write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")
    errs = validate_dataset(p, require_regressions=False, require_clean=False)
    assert any("control inválida" in e for e in errs), errs


def test_validador_rechaza_iban_invalido(tmp_path):
    doc = {"id": "x", "text": "IBAN ES9121000418450200051333.", "entities": [
        {"entity_type": "IBAN_CODE", "start": 5, "end": 29,
         "value": "ES9121000418450200051333"}],  # último dígito alterado → mod-97 falla
        "source": "handmade", "difficulty": "easy", "lang": "es", "region": "eu"}
    p = tmp_path / "bad.jsonl"
    p.write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")
    errs = validate_dataset(p, require_regressions=False, require_clean=False)
    assert any("mod-97" in e for e in errs), errs


def test_validador_no_checksumea_forbidden(tmp_path):
    # Un hard-negative FAC-2026-* marcado PHONE_NUMBER NO debe checksum-validarse
    # (a propósito no es un teléfono válido — es la regresión del #63).
    doc = {"id": "x", "text": "Factura FAC-2026-001587.", "entities": [], "forbidden": [
        {"entity_type": "PHONE_NUMBER", "start": 8, "end": 23, "value": "FAC-2026-001587"}],
        "source": "regression-63", "difficulty": "easy", "lang": "es", "region": "eu"}
    p = tmp_path / "f.jsonl"
    p.write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")
    errs = validate_dataset(p, require_regressions=False, require_clean=False)
    assert not errs, errs


# ── FIX-C1: sin dominios reales de cliente en el corpus ───────────────────────────

def test_sin_dominio_real_de_cliente():
    from basa_harness.corpus.generator import _DOMINIOS
    assert "camaravalencia.es" not in _DOMINIOS
    dataset = (CORPUS_DIR / f"dataset-v{build.DATASET_VERSION.split('.')[0]}.jsonl").read_text("utf-8")
    regr = (CORPUS_DIR / "regressions-63.jsonl").read_text("utf-8")
    assert "camaravalencia" not in dataset and "camaravalencia" not in regr


# ── Regresiones del #63 ───────────────────────────────────────────────────────────

def test_regressions63_parsea_y_valida():
    path = CORPUS_DIR / "regressions-63.jsonl"
    errs = validate_dataset(path, require_regressions=True, require_clean=True)
    assert not errs, errs


def test_regressions63_contiene_casos_iban_y_fac():
    path = CORPUS_DIR / "regressions-63.jsonl"
    docs = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert all(d["source"] == "regression-63" for d in docs)
    assert 8 <= len(docs) <= 15

    # el caso canónico del contrato: IBAN entity + forbidden PHONE sobre FAC-2026-*
    iban_doc = next(d for d in docs if d["id"] == "piloto-63-iban-01")
    assert any(e["entity_type"] == "IBAN_CODE" for e in iban_doc["entities"])
    forb = iban_doc["forbidden"]
    assert any(f["entity_type"] == "PHONE_NUMBER" and f["value"].startswith("FAC-2026")
               for f in forb)

    # al menos un FAC/PROP interno marcado como hard-negative de teléfono
    all_forbidden = [f for d in docs for f in d.get("forbidden", [])]
    assert any(f["value"].startswith(("FAC-2026", "PROP-2026")) for f in all_forbidden)

    # al menos 2 docs limpios (falsos positivos globales)
    assert sum(1 for d in docs if d["entities"] == []) >= 2

    # los nombres del incidente etiquetados como PERSON
    personas = {e["value"] for d in docs for e in d["entities"] if e["entity_type"] == "PERSON"}
    assert "Laura Martínez Cifuentes" in personas
    assert "María Gómez Navarro" in personas


# ── Dataset v1 versionado: reproducible y válido ──────────────────────────────────

def test_dataset_v1_reproducible_y_valido():
    dataset = CORPUS_DIR / f"dataset-v{build.DATASET_VERSION.split('.')[0]}.jsonl"
    manifest_path = CORPUS_DIR / "manifest.json"
    assert dataset.exists(), "falta dataset-v1.jsonl (correr python -m basa_harness.corpus.build)"

    # re-generar y comparar byte a byte con lo commiteado
    regen = build.serialize(build.build_docs())
    committed = dataset.read_text(encoding="utf-8")
    assert regen == committed, "el dataset no es reproducible desde el generador"

    # el sha256 del manifest coincide con el contenido
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["sha256"] == hashlib.sha256(committed.encode("utf-8")).hexdigest()
    assert manifest["seed"] == build.DATASET_SEED

    # FIX-C5: el manifest registra el entorno de generación (major.minor + Unicode)
    assert re.fullmatch(r"\d+\.\d+", manifest["python_version"])
    assert isinstance(manifest["unicodedata_version"], str) and manifest["unicodedata_version"]
    assert manifest["generator_version"] == "1.1.0"

    # el dataset pasa el validador completo (docs limpios + regresiones presentes)
    assert not validate_dataset(dataset), validate_dataset(dataset)
