"""Catálogo de entidades custom (extensión post-016): validación de seguridad del
regex (compila / largo / ReDoS con timeout), test_pattern, y el ciclo
create/list/delete sobre un Guardian fake (sin Postgres real — DB stub mínimo)."""
import pytest

from src.services import entity_catalog_service as svc


# ── validate_pattern_safety ────────────────────────────────────────────────────

def test_validate_pattern_safety_accepts_simple_regex():
    svc.validate_pattern_safety(r"\b[A-Z]{2}\d{6}\b")  # no debe levantar


def test_validate_pattern_safety_rejects_invalid_regex():
    with pytest.raises(svc.UnsafePatternError):
        svc.validate_pattern_safety(r"[unclosed")


def test_validate_pattern_safety_rejects_empty():
    with pytest.raises(svc.UnsafePatternError):
        svc.validate_pattern_safety("")


def test_validate_pattern_safety_rejects_too_long():
    with pytest.raises(svc.UnsafePatternError):
        svc.validate_pattern_safety("a" * (svc.MAX_PATTERN_LEN + 1))


def test_validate_pattern_safety_rejects_nested_quantifier_via_heuristic():
    # Clásico ReDoS: grupo anidado con cuantificador — lo atrapa la heurística
    # estática, instantáneo, sin ejecutar nada.
    with pytest.raises(svc.UnsafePatternError, match="cuantificador anidado"):
        svc.validate_pattern_safety(r"(a+)+$")


def test_validate_pattern_safety_rejects_ambiguous_alternation_via_execution():
    # ReDoS por alternancia ambigua — la heurística NO lo reconoce (no hay
    # '+'/'*' dentro del grupo); lo atrapa la ejecución real con timeout.
    assert not svc._NESTED_QUANTIFIER_RE.search(r"(a|aa)+$")
    with pytest.raises(svc.UnsafePatternError, match="denegación de servicio"):
        svc.validate_pattern_safety(r"(a|aa)+$")


# ── test_pattern ────────────────────────────────────────────────────────────────

def test_test_pattern_reports_matches_and_misses():
    result = svc.test_pattern(
        r"\bHC-\d{6}\b",
        positives=["su historia es HC-123456", "HC-000001"],
        negatives=["HC-12", "sin nada que ver"],
    )
    assert result["all_positives_matched"] is True
    assert result["all_negatives_clean"] is True
    assert result["looks_correct"] is True


def test_test_pattern_flags_false_negative():
    result = svc.test_pattern(r"\bHC-\d{7}\b", positives=["HC-123456"], negatives=[])
    assert result["all_positives_matched"] is False
    assert result["looks_correct"] is False


# ── draft_entity (AI, mockeado) ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_draft_entity_parses_and_validates_ai_response(monkeypatch):
    fake_response = {
        "choices": [{"message": {"content": (
            '{"entity_type": "HISTORIA_CLINICA_ES", "regex": "\\\\bHC-\\\\d{6}\\\\b", '
            '"score": 0.7, "context": ["historia clinica", "hc"], '
            '"test_positive": ["HC-123456"], "test_negative": ["HC-12"]}'
        )}}]
    }

    async def fake_post(path, payload):
        assert path == "/v1/chat/completions"
        return fake_response

    monkeypatch.setattr(svc.ai_engine_client, "_post", fake_post)

    draft = await svc.draft_entity("número de historia clínica española")
    assert draft["entity_type"] == "HISTORIA_CLINICA_ES"
    assert draft["ai_generated"] is True
    assert draft["test_result"]["looks_correct"] is True


@pytest.mark.asyncio
async def test_draft_entity_rejects_unsafe_ai_generated_regex(monkeypatch):
    """Un borrador de IA con un regex catastrófico NUNCA debe devolverse como
    válido — la validación de seguridad corre SIEMPRE, sin excepción para el
    contenido generado por IA."""
    fake_response = {
        "choices": [{"message": {"content": (
            '{"entity_type": "X", "regex": "(a+)+$", "score": 0.5, '
            '"context": [], "test_positive": [], "test_negative": []}'
        )}}]
    }

    async def fake_post(path, payload):
        return fake_response

    monkeypatch.setattr(svc.ai_engine_client, "_post", fake_post)

    with pytest.raises(svc.UnsafePatternError):
        await svc.draft_entity("algo raro")


@pytest.mark.asyncio
async def test_draft_entity_handles_unavailable_ai_engine(monkeypatch):
    async def fake_post(path, payload):
        raise svc.ai_engine_client.AIEngineClientError("motor caído")

    monkeypatch.setattr(svc.ai_engine_client, "_post", fake_post)

    with pytest.raises(svc.UnsafePatternError):
        await svc.draft_entity("algo")


@pytest.mark.asyncio
async def test_draft_entity_handles_non_numeric_score_without_500(monkeypatch):
    """Regresión: antes, un score no-numérico ('score': 'alto') crasheaba con
    ValueError sin capturar (el float() vivía fuera del try/except) — la ruta
    HTTP devolvía un 500 en vez de un 422 prolijo."""
    fake_response = {
        "choices": [{"message": {"content": (
            '{"entity_type": "X", "regex": "\\\\bHC-\\\\d{6}\\\\b", "score": "alto", '
            '"context": [], "test_positive": [], "test_negative": []}'
        )}}]
    }

    async def fake_post(path, payload):
        return fake_response

    monkeypatch.setattr(svc.ai_engine_client, "_post", fake_post)

    with pytest.raises(svc.UnsafePatternError):
        await svc.draft_entity("algo")


@pytest.mark.asyncio
async def test_draft_entity_handles_empty_choices_without_500(monkeypatch):
    """Regresión: choices=[] crasheaba con IndexError sin capturar."""
    async def fake_post(path, payload):
        return {"choices": []}

    monkeypatch.setattr(svc.ai_engine_client, "_post", fake_post)

    with pytest.raises(svc.UnsafePatternError):
        await svc.draft_entity("algo")


# ── create/list/delete sobre un Guardian fake (sin Postgres real) ──────────────

class _FakeGuardian:
    def __init__(self, config):
        self.config = config


class _FakeQuery:
    def __init__(self, guardian):
        self._guardian = guardian

    def filter(self, *args, **kwargs):
        return self

    def with_for_update(self):
        return self  # el fake no simula locking real, solo que el método existe

    def first(self):
        return self._guardian


class _FakeSession:
    def __init__(self, guardian):
        self._guardian = guardian
        self.committed = False

    def query(self, model):
        return _FakeQuery(self._guardian)

    def commit(self):
        self.committed = True


def test_create_list_delete_custom_entity_roundtrip(monkeypatch):
    guardian = _FakeGuardian(config={"custom_names": []})
    db = _FakeSession(guardian)
    # flag_modified toca el estado interno de SQLAlchemy — no aplica a un fake,
    # se neutraliza para este test unitario.
    monkeypatch.setattr(svc, "flag_modified", lambda *a, **k: None)

    created = svc.create_custom_entity(
        db, "tenant-x", name="Historia Clínica ES", entity_type="historia_clinica_es",
        regex=r"\bHC-\d{6}\b", score=0.7, context=["historia clínica"],
    )
    assert created["entity_type"] == "HISTORIA_CLINICA_ES"
    assert created["status"] == "active"
    assert db.committed is True

    listed = svc.list_custom_entities(db, "tenant-x")
    assert len(listed) == 1 and listed[0]["id"] == created["id"]

    svc.delete_custom_entity(db, "tenant-x", created["id"])
    assert svc.list_custom_entities(db, "tenant-x") == []


def test_create_custom_entity_rejects_unsafe_regex_even_pre_reviewed(monkeypatch):
    guardian = _FakeGuardian(config={})
    db = _FakeSession(guardian)
    monkeypatch.setattr(svc, "flag_modified", lambda *a, **k: None)

    with pytest.raises(svc.UnsafePatternError):
        svc.create_custom_entity(
            db, "tenant-x", name="Malo", entity_type="X", regex=r"(a+)+$",
        )


def test_delete_custom_entity_raises_when_not_found(monkeypatch):
    guardian = _FakeGuardian(config={"custom_entities": []})
    db = _FakeSession(guardian)
    with pytest.raises(ValueError):
        svc.delete_custom_entity(db, "tenant-x", "no-existe")


# ── T043: sanitización de entity_type (FR-017) ─────────────────────────────────

def test_validate_entity_type_accepts_normalizes_case():
    assert svc._validate_entity_type("historia_clinica_es") == "HISTORIA_CLINICA_ES"


@pytest.mark.parametrize("bad", ["", "  ", "MI TIPO", "TIPO]RARO", "1EMPIEZA_CON_DIGITO",
                                 "tipo-con-guion", "a" * (svc.MAX_ENTITY_TYPE_LEN + 1)])
def test_validate_entity_type_rejects_invalid_formats(bad):
    with pytest.raises(svc.InvalidEntityTypeError):
        svc._validate_entity_type(bad)


def test_create_custom_entity_rejects_invalid_entity_type(monkeypatch):
    guardian = _FakeGuardian(config={"custom_entities": []})
    db = _FakeSession(guardian)
    monkeypatch.setattr(svc, "flag_modified", lambda *a, **k: None)

    with pytest.raises(svc.InvalidEntityTypeError):
        svc.create_custom_entity(
            db, "tenant-x", name="Malo", entity_type="TIPO]RARO", regex=r"\bHC-\d{6}\b",
        )
    assert db.committed is False  # rechazado ANTES de tocar la DB


# ── T044: unicidad de entity_type entre activas (FR-016, SC-008) ──────────────

def test_create_custom_entity_rejects_duplicate_active_entity_type(monkeypatch):
    guardian = _FakeGuardian(config={"custom_entities": [{
        "id": "existing-id", "name": "Historia Clínica v1", "entity_type": "HISTORIA_CLINICA_ES",
        "regex": r"\bHC-\d{6}\b", "score": 0.7, "context": [], "region": "eu",
        "ai_generated": False, "status": "active",
    }]})
    db = _FakeSession(guardian)
    monkeypatch.setattr(svc, "flag_modified", lambda *a, **k: None)

    with pytest.raises(svc.DuplicateEntityTypeError):
        svc.create_custom_entity(
            db, "tenant-x", name="Historia Clínica v2", entity_type="historia_clinica_es",
            regex=r"\bHC-\d{7}\b",
        )
    assert len(svc.list_custom_entities(db, "tenant-x")) == 1  # no se agregó la duplicada


def test_create_custom_entity_allows_same_type_if_existing_is_not_active(monkeypatch):
    guardian = _FakeGuardian(config={"custom_entities": [{
        "id": "existing-id", "name": "Vieja", "entity_type": "HISTORIA_CLINICA_ES",
        "regex": r"\bHC-\d{6}\b", "score": 0.7, "context": [], "region": "eu",
        "ai_generated": False, "status": "inactive",
    }]})
    db = _FakeSession(guardian)
    monkeypatch.setattr(svc, "flag_modified", lambda *a, **k: None)

    created = svc.create_custom_entity(
        db, "tenant-x", name="Nueva", entity_type="historia_clinica_es", regex=r"\bHC-\d{7}\b",
    )
    assert created["status"] == "active"
    assert len(svc.list_custom_entities(db, "tenant-x")) == 2
