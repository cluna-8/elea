"""El scheduler de la purga (spec 018, FR-001 — T011).

Espeja al ÚNICO scheduler que el producto ya tiene (`licensing/reconcile.py`) y suma la
compuerta que reconcile no necesita: el master switch `BASA_PURGE_ENABLED`. Un job que hace
DELETE retroactivo no se enciende con un pull de imagen, así que la purga arranca sólo si el
operador dijo «sí» de forma explícita Y el intervalo es positivo.

Todo lo que arranca un thread acá lo hace con `interval_seconds` y `session_factory`
EXPLÍCITOS y con `run_once` doblado: ningún test del scheduler puede rozar la DB VIVA del
compose (`SessionLocal`) — que es exactamente lo que este job borraría. La suite además lo
deja apagado por default (`conftest.py` fuerza `BASA_PURGE_ENABLED=false`).
"""
import threading

import pytest

from src.services import retention_scheduler


@pytest.fixture(autouse=True)
def _sin_thread_colgado():
    # Red de seguridad: ningún test deja un thread daemon vivo para el siguiente.
    yield
    retention_scheduler.reset_for_tests()


def _run_once_inerte(*, session_factory=None):
    """Doble de `run_once` que no toca nada: el thread lo llama una vez y se duerme."""
    return None


# ── Doble compuerta de apagado ───────────────────────────────────────────────────────
def test_desactivado_por_enabled_false(monkeypatch):
    monkeypatch.setenv("BASA_PURGE_ENABLED", "false")

    def _no_debe_correr(*, session_factory=None):  # pragma: no cover - no debe invocarse
        raise AssertionError("run_once no debe correr con el scheduler desactivado")

    monkeypatch.setattr(retention_scheduler, "run_once", _no_debe_correr)
    # Intervalo positivo válido: lo único que apaga es el master switch.
    assert retention_scheduler.start_scheduler(interval_seconds=1, session_factory=object()) is None
    assert not retention_scheduler.scheduler_running()


def test_desactivado_por_intervalo_no_positivo(monkeypatch):
    # Encendido por env, pero el intervalo cierra la otra compuerta (igual que reconcile).
    monkeypatch.setenv("BASA_PURGE_ENABLED", "true")
    monkeypatch.setattr(retention_scheduler, "run_once", _run_once_inerte)

    assert retention_scheduler.start_scheduler(interval_seconds=0, session_factory=object()) is None
    assert retention_scheduler.start_scheduler(interval_seconds=-5, session_factory=object()) is None
    assert not retention_scheduler.scheduler_running()


# ── start / stop / running ───────────────────────────────────────────────────────────
def test_start_stop_y_running(monkeypatch):
    monkeypatch.setenv("BASA_PURGE_ENABLED", "true")
    monkeypatch.setattr(retention_scheduler, "run_once", _run_once_inerte)

    th = retention_scheduler.start_scheduler(interval_seconds=60, session_factory=object())
    try:
        assert th is not None and th.is_alive()
        assert retention_scheduler.scheduler_running()
    finally:
        retention_scheduler.stop_scheduler()
    assert not retention_scheduler.scheduler_running()


def test_start_es_idempotente(monkeypatch):
    # Con N workers ya hay un purgador por proceso; dentro del proceso no se duplica.
    monkeypatch.setenv("BASA_PURGE_ENABLED", "true")
    monkeypatch.setattr(retention_scheduler, "run_once", _run_once_inerte)

    th1 = retention_scheduler.start_scheduler(interval_seconds=60, session_factory=object())
    try:
        th2 = retention_scheduler.start_scheduler(interval_seconds=60, session_factory=object())
        assert th1 is not None
        assert th1 is th2
    finally:
        retention_scheduler.stop_scheduler()


# ── El _loop corre run_once con la session_factory que se le pasó ─────────────────────
def test_el_loop_invoca_run_once_con_la_session_factory(monkeypatch):
    monkeypatch.setenv("BASA_PURGE_ENABLED", "true")
    llamada = threading.Event()
    recibido = {}

    def _fake(*, session_factory=None):
        recibido["session_factory"] = session_factory
        llamada.set()

    monkeypatch.setattr(retention_scheduler, "run_once", _fake)
    centinela = object()
    retention_scheduler.start_scheduler(interval_seconds=0.01, session_factory=centinela)
    try:
        assert llamada.wait(timeout=5), "el _loop nunca invocó run_once"
        assert recibido["session_factory"] is centinela
    finally:
        retention_scheduler.stop_scheduler()


# ── Una corrida que explota NO mata el thread ────────────────────────────────────────
def test_una_corrida_que_explota_no_mata_el_thread(monkeypatch):
    monkeypatch.setenv("BASA_PURGE_ENABLED", "true")
    reintento = threading.Event()
    contador = {"n": 0}

    def _revienta(*, session_factory=None):
        contador["n"] += 1
        if contador["n"] >= 2:
            reintento.set()  # llegó a la 2da corrida ⇒ sobrevivió a la 1ra excepción
        raise RuntimeError("corrida reventada")

    monkeypatch.setattr(retention_scheduler, "run_once", _revienta)
    retention_scheduler.start_scheduler(interval_seconds=0.01, session_factory=object())
    try:
        assert reintento.wait(timeout=5), "el thread no reintentó tras la excepción"
        assert retention_scheduler.scheduler_running(), \
            "una corrida que explotó se llevó puesto el thread"
    finally:
        retention_scheduler.stop_scheduler()


# ── El lifespan de la app cablea start en el arranque y stop en el shutdown ───────────
def test_lifespan_cablea_la_purga(monkeypatch):
    from fastapi.testclient import TestClient

    import src.main as main

    calls = []
    monkeypatch.setattr(retention_scheduler, "start_scheduler", lambda *a, **k: calls.append("start"))
    monkeypatch.setattr(retention_scheduler, "stop_scheduler", lambda: calls.append("stop"))
    with TestClient(main.app):
        assert calls == ["start"]
    assert calls == ["start", "stop"]
