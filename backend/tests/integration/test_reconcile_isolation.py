"""Integration tests del aislamiento por tenant de la reconciliación
(spec 021, T023 — SC-009, FR-017).

Con múltiples tenants en el mismo deployment, el ``over_seat`` de uno NO
afecta el estado del otro: ni infla su conteo (cada tenant se cuenta aislado
con la MISMA definición de seat), ni le cambia el estado publicado, ni le
bloquea la creación. Los eventos de audit nombran al tenant correcto.
"""
import pytest

from migration_harness import DEFAULT_TENANT, require_postgres
from seat_gate_harness import (
    admin_headers,
    build_app_client,
    current_seats,
    mock_engine,
    restore_suite_license,
    seed_active_seats,
    set_license,
)

require_postgres()

DB = "basa_test_reconcile_iso"


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


def _create_tenant(factory, slug):
    from src.models.tenant import Tenant
    db = factory()
    try:
        row = Tenant(name=slug, slug=slug)
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _license_audit_rows(factory):
    """(tenant_id, entry) de cada evento de licencia — para afirmar QUIÉN."""
    from src.models.audit import AuditLog
    db = factory()
    try:
        rows = (db.query(AuditLog)
                .filter(AuditLog.model == "license")
                .order_by(AuditLog.timestamp).all())
        return [(row.tenant_id, row.guardian_events[0]) for row in rows]
    finally:
        db.close()


def test_unlicensed_tenant_over_seat_does_not_touch_licensed_one(harness, monkeypatch, tmp_path):
    """Drift en el tenant B (seats sin entitlement, fail-closed) → B over_seat;
    el tenant licenciado sigue ok, con SU conteo, y su creación habilitada."""
    from src.licensing import reconcile
    client, factory, headers = harness
    tenant_b = _create_tenant(factory, "iso-tenant-b")
    seed_active_seats(factory, 2, prefix="iso-b", tenant_id=tenant_b)

    base = current_seats(factory)  # cuenta SOLO el tenant default (aislado)
    set_license(monkeypatch, tmp_path, max_seats=base + 2)

    statuses = reconcile.run_once(session_factory=factory)
    licensed = statuses[str(DEFAULT_TENANT)]
    assert licensed.status == reconcile.RECON_OK
    assert licensed.seats_used == base  # los seats de B no inflan el conteo de A (FR-017)
    other = statuses[str(tenant_b)]
    assert other.status == reconcile.RECON_OVER_SEAT
    assert other.seats_used == 2

    # SC-009 conductual: el over_seat de B no bloquea crear en el licenciado.
    recorder = mock_engine(monkeypatch)
    resp = client.post("/api/v1/keys", headers=headers, json={"name": "iso-sigue-ok"})
    assert resp.status_code == 201, resp.text
    assert len(recorder.generate_key_calls) == 1


def test_licensed_tenant_drift_does_not_mark_other_tenant(harness, monkeypatch, tmp_path):
    """Drift en el tenant licenciado → over_seat SOLO ahí; un tenant limpio
    publica ok y el audit del drift nombra al tenant correcto."""
    from src.licensing import reconcile
    _client, factory, _headers = harness
    tenant_c = _create_tenant(factory, "iso-tenant-c")

    base = current_seats(factory)
    set_license(monkeypatch, tmp_path, max_seats=base)  # tope EXACTO al conteo real
    seed_active_seats(factory, 1, prefix="iso-a")       # default queda base+1 > base

    statuses = reconcile.run_once(session_factory=factory)
    assert statuses[str(DEFAULT_TENANT)].status == reconcile.RECON_OVER_SEAT
    assert statuses[str(tenant_c)].status == reconcile.RECON_OK

    over_rows = [(tid, e) for tid, e in _license_audit_rows(factory)
                 if e["event_type"] == "license_over_seat"]
    # El evento nombra al tenant drifteado, con SUS números (la DB del módulo
    # es compartida: otros tenants pueden tener sus propios eventos).
    drifted = [e for tid, e in over_rows if tid == DEFAULT_TENANT]
    assert drifted, "falta el evento de audit del drift del tenant licenciado"
    assert drifted[-1]["seats_used"] == base + 1
    assert drifted[-1]["max_seats"] == base
    assert all(tid != tenant_c for tid, _ in over_rows)  # jamás al tenant limpio
