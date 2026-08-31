"""Integration tests de la reconciliación de seats (spec 021, T022 — SC-005).

Drift inyectado por DB directa (``COUNT(activas) > max_seats``) → la siguiente
corrida marca ``over_seat``, dispara el degradado (la creación queda bloqueada
por el ESTADO publicado, aunque el conteo vivo baje del tope) y emite audit con
``seats_used`` vs ``max_seats``; al corregir, la siguiente corrida vuelve a
``ok`` y la creación se rehabilita. El audit es POR TRANSICIÓN: dos corridas
seguidas en over_seat no duplican el evento.
"""
import time

import pytest

from migration_harness import DEFAULT_TENANT, require_postgres
from seat_gate_harness import (
    admin_headers,
    build_app_client,
    create_tenant,
    current_seats,
    license_audit_events,
    mock_engine,
    restore_suite_license,
    seed_active_seats,
    set_license,
)

require_postgres()

DB = "sentinel_test_reconcile"


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


def _deactivate(factory, ids):
    """Corrección del drift por la misma vía que lo creó: DB directa."""
    from src.models.budget import APIKey
    db = factory()
    try:
        db.query(APIKey).filter(APIKey.id.in_(ids)).update(
            {"is_active": False}, synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _over_seat_events(factory):
    return [e for e in license_audit_events(factory)
            if e["event_type"] == "license_over_seat"]


def test_drift_marks_over_seat_degrades_and_recovers(harness, monkeypatch, tmp_path):
    from src.licensing import reconcile
    client, factory, headers = harness
    recorder = mock_engine(monkeypatch)
    base = current_seats(factory)
    max_seats = base + 2
    set_license(monkeypatch, tmp_path, max_seats=max_seats)

    # Sin drift: la corrida publica ok para el tenant licenciado.
    statuses = reconcile.run_once(session_factory=factory)
    assert statuses[str(DEFAULT_TENANT)].status == reconcile.RECON_OK

    # Drift por DB directa: base+3 > max_seats. La SIGUIENTE corrida lo marca
    # (SC-005) con seats_used vs max_seats en el audit.
    ids = seed_active_seats(factory, 3, prefix="drift")
    statuses = reconcile.run_once(session_factory=factory)
    entry = statuses[str(DEFAULT_TENANT)]
    assert entry.status == reconcile.RECON_OVER_SEAT
    assert entry.seats_used == base + 3
    assert entry.max_seats == max_seats
    events = _over_seat_events(factory)
    assert events, "falta el evento de audit license_over_seat"
    assert events[-1]["seats_used"] == base + 3
    assert events[-1]["max_seats"] == max_seats

    # Audit por transición, no por corrida: re-correr en over_seat no duplica.
    reconcile.run_once(session_factory=factory)
    assert len(_over_seat_events(factory)) == len(events)

    # Degradado (FR-016/FR-020): con over_seat PUBLICADO la creación se bloquea
    # aunque el conteo vivo baje del tope — el estado manda hasta reconciliar.
    _deactivate(factory, ids[:3])
    assert current_seats(factory) < max_seats
    resp = client.post("/api/v1/keys", headers=headers, json={"name": "degradado-bloquea"})
    assert resp.status_code == 403, resp.text
    assert "over_seat" in resp.json()["detail"]
    assert recorder.generate_key_calls == []  # 0 provisioning en degradado

    # Correccion reconciliada → ok + audit de resolución + creación rehabilitada.
    statuses = reconcile.run_once(session_factory=factory)
    assert statuses[str(DEFAULT_TENANT)].status == reconcile.RECON_OK
    resolved = [e for e in license_audit_events(factory)
                if e["event_type"] == "license_over_seat_resolved"]
    assert resolved, "falta el evento de audit de la vuelta a ok"
    resp = client.post("/api/v1/keys", headers=headers, json={"name": "post-recovery"})
    assert resp.status_code == 201, resp.text


def test_midrun_failure_does_not_duplicate_transition_audit(harness, monkeypatch, tmp_path):
    """Hardening post-review: si la corrida muere DESPUÉS de auditar la
    transición de un tenant (p.ej. conexión caída contando el siguiente), el
    estado ya publicado evita re-emitir el mismo evento en el reintento —
    audit POR transición incluso bajo errores transitorios."""
    from src.licensing import reconcile
    _client, factory, _headers = harness
    # run_once itera por Tenant.id ASC: el default (…0001) va primero y el
    # tenant extra (uuid4) después — la caída ocurre tras auditar el default.
    extra = create_tenant(factory, "midrun-extra")
    base = current_seats(factory)
    set_license(monkeypatch, tmp_path, max_seats=base)
    seed_active_seats(factory, 1, prefix="midrun")  # drift: base+1 > base
    before = len(_over_seat_events(factory))

    real_count = reconcile.count_active_seats

    def flaky_count(db, tenant_id):
        if str(tenant_id) == str(extra):
            raise RuntimeError("conexión caída simulada")
        return real_count(db, tenant_id)

    monkeypatch.setattr(reconcile, "count_active_seats", flaky_count)
    with pytest.raises(RuntimeError):
        reconcile.run_once(session_factory=factory)
    events_after_crash = len(_over_seat_events(factory)) - before
    assert events_after_crash == 1, "la transición del default debió auditarse antes de la caída"

    monkeypatch.setattr(reconcile, "count_active_seats", real_count)
    reconcile.run_once(session_factory=factory)  # reintento sano
    assert len(_over_seat_events(factory)) - before == 1  # UNA transición = UN evento


def test_scheduler_runs_periodically(harness, monkeypatch, tmp_path):
    from src.licensing import reconcile
    _client, factory, _headers = harness
    set_license(monkeypatch, tmp_path, max_seats=current_seats(factory) + 5)

    reconcile.start_scheduler(interval_seconds=0.05, session_factory=factory)
    try:
        deadline = time.time() + 5
        seen = set()
        while time.time() < deadline and len(seen) < 2:
            entry = reconcile.get_tenant_status(DEFAULT_TENANT)
            if entry is not None:
                seen.add(entry.checked_at)
            time.sleep(0.02)
        # ≥2 checked_at distintos = corrió al menos dos veces (periódico, no one-shot).
        assert len(seen) >= 2, "el scheduler no re-corrió la reconciliación"
    finally:
        reconcile.stop_scheduler()
    assert not reconcile.scheduler_running()


def test_scheduler_disabled_by_env(monkeypatch):
    from src.licensing import reconcile
    monkeypatch.setenv("SENTINEL_LICENSE_RECONCILE_INTERVAL_SECONDS", "0")
    assert reconcile.start_scheduler() is None
    assert not reconcile.scheduler_running()


def test_app_lifespan_wires_scheduler(monkeypatch):
    """T025: el arranque real de la app arranca el scheduler; el shutdown lo para."""
    from fastapi.testclient import TestClient

    import src.main as main
    from src.licensing import reconcile

    calls = []
    monkeypatch.setattr(reconcile, "start_scheduler", lambda **kw: calls.append("start"))
    monkeypatch.setattr(reconcile, "stop_scheduler", lambda: calls.append("stop"))
    with TestClient(main.app):
        assert calls == ["start"]
    assert calls == ["start", "stop"]
