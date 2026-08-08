"""Catálogo de entidades custom (extensión post-016): validación de seguridad del
regex (compila / largo / ReDoS con timeout), test_pattern, y el ciclo
create/list/delete sobre un Guardian fake (sin Postgres real — DB stub mínimo)."""
import asyncio
import json
import threading
import time

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


# ── concurrencia: carrera de multiprocessing bajo hilos (#98) ──────────────────

def test_validate_pattern_safety_no_rechaza_patrones_sanos_entre_hilos():
    """Regresión #98: cada match corre en un subproceso, y `Process.start()` cosecha
    con `waitpid` a los hijos de OTROS hilos; en la ventana entre ese `waitpid` y la
    asignación del `returncode`, `is_alive()` reporta VIVO un proceso que ya terminó
    bien, y el validador lo lee como "no respondió a tiempo" → rechaza un regex SANO.

    La concurrencia de acá es la de producción, no de laboratorio: `POST
    /custom-entities` es un `def`, así que FastAPI lo corre en su threadpool y dos
    altas simultáneas ya alcanzan. Se lanzan 120 subprocesos (8 hilos x 5 rondas x 3
    inputs adversariales), el mismo volumen con el que se midió el bug: ~2-8 falsos
    timeouts cada 120, y ~43% de fallo en el test de concurrencia del catálogo.
    """
    hilos_n, rondas = 8, 5
    errores = []

    def _validar(i):
        for ronda in range(rondas):
            try:
                svc.validate_pattern_safety(rf"\bZZ{i}-\d{{4}}\b")  # sano, debe pasar
            except Exception as e:
                errores.append(f"hilo {i} ronda {ronda}: {e!r}")

    hilos = [threading.Thread(target=_validar, args=(i,)) for i in range(hilos_n)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=120)

    # Un `join` con timeout que expira NO falla solo: sin este assert, un hilo colgado
    # se leería como "no hubo errores" y el test pasaría en falso.
    assert not [h for h in hilos if h.is_alive()], "quedaron hilos sin terminar"
    assert errores == [], f"patrones sanos rechazados (carrera #98): {errores}"


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


# ── Hardening #106: DoS del threadpool + cap de cantidad + join acotado ─────────
# Modelo de amenaza: NO DoS anónimo. `POST /custom-entities` y `draft_entity` están
# admin-gated; el atacante es un ADMIN HOSTIL o una PROMPT INJECTION (las listas de test
# strings del draft las escribe el LLM desde `description`). Defensa en profundidad real.

# (b) join(timeout) tras kill(): un hijo que NO muere no cuelga el hilo para siempre.

class _FakeUnkillableProc:
    """Simula un subproceso en estado D (uninterruptible): ignora terminate()/kill() y
    NUNCA reporta que murió. Sus `join()` no duermen — verificamos que el código PASA un
    timeout finito (no un `join()` pelado), no el reloj de pared."""
    def __init__(self):
        self.pid = 4242
        self.started = False
        self.terminated = False
        self.killed = False
        self.joins = []  # timeouts con los que se llamó a join()

    def start(self):
        self.started = True

    def is_alive(self):
        return True  # nunca muere

    def join(self, timeout=None):
        self.joins.append(timeout)  # no bloquea: solo registra el timeout recibido

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class _FakeEmptyQueue:
    def get(self, timeout=None):
        raise Exception("empty")  # nada en la cola -> _run_in_process resuelve "desconocido"


class _FakeSpawnCtx:
    def __init__(self, proc):
        self._proc = proc

    def Queue(self):
        return _FakeEmptyQueue()

    def Process(self, target, args):
        return self._proc


def test_run_in_process_join_after_kill_is_bounded(monkeypatch):
    """#106 hallazgo 3: `p.kill(); p.join()` sin timeout colgaría el hilo PARA SIEMPRE si el
    hijo quedó en estado D. Con el fix, el join final lleva `_KILL_JOIN_TIMEOUT_S` y el hilo
    se libera aunque el hijo nunca muera (best-effort, se loguea)."""
    proc = _FakeUnkillableProc()
    monkeypatch.setattr(svc.mp, "get_context", lambda method: _FakeSpawnCtx(proc))

    start = time.monotonic()
    result = svc._run_in_process("x", "y", timeout_s=0.5)
    elapsed = time.monotonic() - start

    assert result is None  # cola vacía -> desconocido (nunca "matcheó")
    assert proc.terminated and proc.killed  # recorrió el camino de matar de verdad
    assert proc.joins, "no se llamó a join()"
    # NINGÚN join es pelado: un `join(None)` es exactamente el que colgaría el hilo.
    assert all(t is not None for t in proc.joins), f"join sin timeout (colgaría): {proc.joins}"
    # El join final (tras kill) usa el techo del #106.
    assert proc.joins[-1] == svc._KILL_JOIN_TIMEOUT_S
    # No colgó: con joins no-op el retorno es inmediato (holgura amplia sobre el tope real).
    assert elapsed < 5.0


# (a) cap de CANTIDAD de test strings (prompt injection influye las listas del LLM).

def test_test_pattern_caps_number_of_test_strings(monkeypatch):
    """#106 hallazgo 2: `test_pattern` spawnea UN subproceso por string; sin techo, una lista
    inflada (LLM/prompt injection) = ~7 min de hilo. Se truncan a `MAX_TEST_STRINGS` ANTES de
    spawnear, y el recorte se reporta (honesto, no silencioso)."""
    calls = []
    monkeypatch.setattr(svc, "_run_in_process",
                        lambda pattern, text, *a, **k: (calls.append(text) or True))

    over = svc.MAX_TEST_STRINGS + 30
    result = svc.test_pattern(
        r"m-\d+",
        positives=[f"m-{i}" for i in range(over)],
        negatives=[f"n-{i}" for i in range(svc.MAX_TEST_STRINGS + 5)],
    )

    # No se spawnea un subproceso por string sin límite: cap por lista.
    assert len(result["positives"]) == svc.MAX_TEST_STRINGS
    assert len(result["negatives"]) == svc.MAX_TEST_STRINGS
    assert len(calls) == 2 * svc.MAX_TEST_STRINGS
    # Aviso honesto, no descarte silencioso.
    assert result["truncated"] is True
    assert result["max_test_strings"] == svc.MAX_TEST_STRINGS
    assert result["positives_total"] == over


def test_test_pattern_small_lists_not_truncated(monkeypatch):
    """Happy-path del cap: listas por debajo del techo NO se marcan truncadas."""
    monkeypatch.setattr(svc, "_run_in_process", lambda pattern, text, *a, **k: True)
    result = svc.test_pattern(r"m-\d+", positives=["m-1", "m-2"], negatives=["n-1"])
    assert result["truncated"] is False
    assert result["positives_total"] == 2 and result["negatives_total"] == 1


@pytest.mark.asyncio
async def test_draft_entity_caps_ai_test_strings(monkeypatch):
    """#106 hallazgo 2 en el path que importa: las listas del draft las escribe el LLM. Un
    draft con MÁS de `MAX_TEST_STRINGS` no spawnea N subprocesos ilimitados — se truncan y el
    draft devuelve SOLO lo realmente probado, con el flag `truncated`."""
    n = svc.MAX_TEST_STRINGS + 40
    fake_response = {"choices": [{"message": {"content": json.dumps({
        "entity_type": "HISTORIA_CLINICA_ES", "regex": r"\bHC-\d{6}\b", "score": 0.7,
        "context": [], "test_positive": [f"HC-{i:06d}" for i in range(n)], "test_negative": [],
    })}}]}

    async def fake_post(path, payload):
        return fake_response

    monkeypatch.setattr(svc.ai_engine_client, "_post", fake_post)
    calls = []
    monkeypatch.setattr(svc, "_run_in_process",
                        lambda pattern, text, *a, **k: (calls.append(text) or True))

    draft = await svc.draft_entity("historia clínica")

    # El draft devuelve lo REALMENTE probado (truncado), no las N listas crudas del LLM.
    assert len(draft["test_positive"]) == svc.MAX_TEST_STRINGS
    assert len(draft["test_result"]["positives"]) == svc.MAX_TEST_STRINGS
    assert draft["test_result"]["truncated"] is True
    assert draft["test_result"]["positives_total"] == n
    # Subprocesos acotados: 3 de validate_pattern_safety (inputs adversariales fijos) +
    # a lo sumo MAX_TEST_STRINGS de las positives, NO uno por cada uno de los N del LLM.
    assert len(calls) == 3 + svc.MAX_TEST_STRINGS


# (c) aislamiento: la validación corre en un executor dedicado y ACOTADO, no en el
#     threadpool anyio general -> un pico hostil se encola, no starva al backend.

def test_validation_executor_is_dedicated_and_bounded():
    """#106 hallazgo 1: existe un executor propio y su límite está en el rango de diseño
    (2-4). El `max_workers` ES el semáforo efectivo sobre las validaciones/subprocesos."""
    assert svc._VALIDATION_EXECUTOR._max_workers == svc.REDOS_VALIDATION_CONCURRENCY
    assert 2 <= svc.REDOS_VALIDATION_CONCURRENCY <= 4


@pytest.mark.asyncio
async def test_offload_bounded_caps_concurrency():
    """El aislamiento se APLICA: aunque se disparen muchas más validaciones que `max_workers`,
    nunca corren más de N a la vez — la (N+1) espera. Determinista: el executor no puede
    exceder su `max_workers`."""
    n = svc.REDOS_VALIDATION_CONCURRENCY
    lock = threading.Lock()
    state = {"cur": 0, "max": 0}

    def _work(_i):
        with lock:
            state["cur"] += 1
            state["max"] = max(state["max"], state["cur"])
        time.sleep(0.05)  # fuerza solapamiento para que el pico realmente alcance N
        with lock:
            state["cur"] -= 1
        return True

    await asyncio.gather(*[svc._offload_bounded(_work, i) for i in range(n * 3)])

    # Nunca más de N validaciones concurrentes (aislamiento real, no teórico).
    assert state["max"] <= n
    # Y el límite se alcanza: con 3xN tareas solapadas el pico llega a N (no quedó en 1).
    assert state["max"] == n
