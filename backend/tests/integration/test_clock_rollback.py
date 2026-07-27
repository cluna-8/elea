"""Integration tests de la marca monotónica anti-rollback de reloj
(spec 021, T031 — FR-023).

La marca (último ts de licencia/audit visto) persiste en
``license_runtime_state``: si un tick llega con ``now`` ANTERIOR a la marca,
se emite ``license_clock_rollback_suspected`` (una vez por episodio) y la
creación de seats queda degradada mientras dure la sospecha; cuando el reloj
vuelve a superar la marca, el episodio cierra. Best-effort declarado: quien
controla la DB puede borrar la marca — el ancla es la cadena (T039) + true-up.
"""
from datetime import datetime, timedelta, timezone

import pytest

from migration_harness import require_postgres
from seat_gate_harness import (
    admin_headers,
    build_app_client,
    current_seats,
    license_audit_events,
    mock_engine,
    restore_suite_license,
    set_license,
)

require_postgres()

DB = "basa_test_clock_rollback"

T_NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
T_PAST = T_NOW - timedelta(hours=2)
T_LATER = T_NOW + timedelta(minutes=5)


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    headers = admin_headers(client)
    yield client, factory, headers
    cleanup()


@pytest.fixture(autouse=True)
def _restore():
    from src.licensing import reconcile
    yield
    reconcile.reset_for_tests()
    restore_suite_license()


def _rollback_events(factory):
    return [e for e in license_audit_events(factory)
            if e["event_type"] == "license_clock_rollback_suspected"]


def test_rollback_detected_degrades_and_recovers(harness, monkeypatch, tmp_path):
    from src.licensing import reconcile
    client, factory, headers = harness
    recorder = mock_engine(monkeypatch)
    set_license(monkeypatch, tmp_path, max_seats=current_seats(factory) + 10)

    reconcile.run_once(session_factory=factory, now=T_NOW)  # marca := T_NOW
    assert not reconcile.clock_rollback_suspected()

    # Reloj retrocedido → evento + degradado (creación bloqueada, FR-023).
    reconcile.run_once(session_factory=factory, now=T_PAST)
    assert reconcile.clock_rollback_suspected()
    assert len(_rollback_events(factory)) == 1
    resp = client.post("/api/v1/keys", headers=headers, json={"name": "rollback-bloquea"})
    assert resp.status_code == 403, resp.text
    assert "reloj" in resp.json()["detail"] or "clock" in resp.json()["detail"]
    assert recorder.generate_key_calls == []

    # Mismo episodio: otro tick atrasado NO duplica el evento.
    reconcile.run_once(session_factory=factory, now=T_PAST + timedelta(minutes=1))
    assert len(_rollback_events(factory)) == 1

    # El reloj supera la marca → episodio cerrado, creación rehabilitada.
    reconcile.run_once(session_factory=factory, now=T_LATER)
    assert not reconcile.clock_rollback_suspected()
    resp = client.post("/api/v1/keys", headers=headers, json={"name": "post-rollback"})
    assert resp.status_code == 201, resp.text


def test_micro_inversion_between_workers_no_es_rollback(harness, monkeypatch, tmp_path):
    """Tolerancia FR-023 (fix del ensayo 2026-07-27): con N workers, el tick de uno
    puede capturar `now` un instante ANTES de que otro commitee un evento que avanza
    la marca. Esa inversión de segundos NO es el ataque que la marca persigue (retrasar
    el reloj horas/días para estirar la licencia) y degradaba la creación con 403
    hasta el próximo tick — reproducido en una instalación recién arrancada: bootstrap
    de admin → alta del primer usuario → 403 con todos los relojes sanos."""
    from src.licensing import reconcile
    client, factory, headers = harness
    mock_engine(monkeypatch)
    set_license(monkeypatch, tmp_path, max_seats=current_seats(factory) + 10)

    # Tiempos RELATIVOS, no fechas fijas: el arranque del módulo (bootstrap de admin,
    # lifespan) ya pudo avanzar la marca con el reloj REAL, así que un "pasado" absoluto
    # dispararía el episodio por el estado previo y no por lo que este test prueba.
    base = datetime.now(timezone.utc) + timedelta(minutes=10)
    reconcile.run_once(session_factory=factory, now=base)  # marca := base (por delante de todo)
    assert not reconcile.clock_rollback_suspected()
    eventos_antes = len(_rollback_events(factory))

    # Inversión de 5s (carrera entre workers): dentro de la tolerancia → sin episodio.
    reconcile.run_once(session_factory=factory, now=base - timedelta(seconds=5))
    assert not reconcile.clock_rollback_suspected()
    assert len(_rollback_events(factory)) == eventos_antes
    resp = client.post("/api/v1/keys", headers=headers, json={"name": "micro-inversion-ok"})
    assert resp.status_code == 201, resp.text

    # Y la marca NO retrocedió: un atraso REAL (más allá de la tolerancia) sigue
    # detectándose contra la marca original.
    reconcile.run_once(
        session_factory=factory,
        now=base - timedelta(seconds=reconcile.CLOCK_ROLLBACK_TOLERANCE_SECONDS + 30))
    assert reconcile.clock_rollback_suspected()
    assert len(_rollback_events(factory)) == eventos_antes + 1


def test_mark_survives_process_restart(harness, monkeypatch, tmp_path):
    """La marca vive en DB: un 'reinicio' (estado en memoria limpio) con el
    reloj atrasado sigue detectándose — ese es el punto del anti-rollback."""
    from src.licensing import entitlement, reconcile
    _client, factory, _headers = harness
    set_license(monkeypatch, tmp_path, max_seats=current_seats(factory) + 10)

    reconcile.run_once(session_factory=factory, now=T_LATER)  # marca := T_LATER
    before = len(_rollback_events(factory))

    # 'Reinicio': módulos en memoria limpios; la DB conserva la marca.
    reconcile.reset_for_tests()
    entitlement.reset_for_tests()
    set_license(monkeypatch, tmp_path, max_seats=current_seats(factory) + 10)

    reconcile.run_once(session_factory=factory, now=T_NOW)  # T_NOW < marca persistida
    assert reconcile.clock_rollback_suspected()
    assert len(_rollback_events(factory)) == before + 1
