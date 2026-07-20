"""Integration tests (negativos) de la evidencia de licencia en el AuditLog
(spec 021, T030 — SC-007, FR-024/FR-025/FR-028).

Cada transición de licencia deja una fila append-only metadata-only con el
esquema encadenado (``event_type … prev_hash/seq``); CERO token crudo o
claves en la evidencia; y la ruta normal (API) no ofrece borrado/edición del
audit — la inmutabilidad ante DB directa la cubre la cadena (T039).
"""
import json

import pytest

from migration_harness import require_postgres
from seat_gate_harness import (
    admin_headers,
    build_app_client,
    clear_license,
    current_seats,
    mock_engine,
    restore_suite_license,
    seed_active_seats,
    set_license,
)

require_postgres()

DB = "basa_test_audit_tamper"

ENTRY_KEYS = {"event_type", "license_id", "seats_used", "max_seats", "reason",
              "ts", "prev_hash", "seq"}


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


def _license_rows(factory):
    from src.models.audit import AuditLog
    db = factory()
    try:
        rows = (db.query(AuditLog).filter(AuditLog.model == "license")
                .order_by(AuditLog.timestamp).all())
        return [(r.tenant_id, r.guardian_events[0]) for r in rows]
    finally:
        db.close()


def test_every_transition_leaves_chained_metadata_only_evidence(harness, monkeypatch, tmp_path):
    """Provoca las transiciones del ciclo completo y verifica el esquema del
    evento + cero material sensible en TODA la evidencia."""
    from datetime import datetime, timedelta, timezone

    from src.licensing import entitlement, reconcile
    client, factory, headers = harness
    mock_engine(monkeypatch)

    # inválido (token ausente) → license_missing
    clear_license(monkeypatch)
    entitlement.initialize(force=True, emit_audit=True, session_factory=factory)

    # seat-limit → license_seat_limit_exceeded (gate 402)
    lic_state = set_license(monkeypatch, tmp_path, max_seats=current_seats(factory))
    raw_blob = None
    import os
    with open(os.environ["BASA_LICENSE_TOKEN_FILE"], encoding="utf-8") as fh:
        raw_blob = fh.read()
    resp = client.post("/api/v1/keys", headers=headers, json={"name": "tope"})
    assert resp.status_code == 402

    # over-seat → license_over_seat (reconciliación)
    seed_active_seats(factory, 1, prefix="tamper")
    reconcile.run_once(session_factory=factory)

    # grace y expired → license_grace / license_expired (refresh runtime)
    set_license(monkeypatch, tmp_path, expiry="2027-01-01T00:00:00Z", grace_days=7)
    entitlement.refresh(now=datetime(2027, 1, 3, tzinfo=timezone.utc), session_factory=factory)
    entitlement.refresh(now=datetime(2027, 2, 1, tzinfo=timezone.utc), session_factory=factory)

    # reloj atrasado → license_clock_rollback_suspected
    reconcile.run_once(session_factory=factory,
                       now=datetime(2026, 1, 1, tzinfo=timezone.utc))

    rows = _license_rows(factory)
    seen = {e["event_type"] for _, e in rows}
    for expected in ("license_missing", "license_seat_limit_exceeded", "license_over_seat",
                     "license_grace", "license_expired", "license_clock_rollback_suspected"):
        assert expected in seen, f"falta evidencia de {expected}: {sorted(seen)}"

    # Esquema encadenado en TODOS los eventos post-US5.
    for _tenant, entry in rows:
        assert ENTRY_KEYS.issubset(entry.keys()), entry

    # Metadata-only (FR-024/C1): ni el token crudo ni material de claves en
    # NINGÚN campo de NINGÚN evento.
    dumped = json.dumps([e for _, e in rows])
    assert lic_state.token is not None
    lic_doc = json.loads(raw_blob)
    assert lic_doc["sig"], "el .lic de la suite debería venir firmado"
    assert raw_blob not in dumped
    assert lic_doc["sig"] not in dumped  # la FIRMA del token jamás en la evidencia
    assert "BEGIN PRIVATE KEY" not in dumped and "BEGIN PUBLIC KEY" not in dumped


def test_audit_api_offers_no_delete_or_edit(harness):
    """Inmutabilidad por la ruta normal (FR-025): la API de audit no expone
    DELETE/PUT/PATCH — el canal es append-only por construcción."""
    from src.main import app
    mutating = [r for r in app.routes
                if getattr(r, "path", "").startswith("/api/v1/audit")
                and (set(getattr(r, "methods", set())) & {"DELETE", "PUT", "PATCH"})]
    assert mutating == [], [f"{r.methods} {r.path}" for r in mutating]
