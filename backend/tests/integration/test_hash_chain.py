"""Integration tests de la cadena de hashes del audit de licencia
(spec 021, T039 — SC-011, FR-028).

Cada evento de licencia se encadena: ``prev_hash`` = hash del evento anterior,
génesis anclada al ``license_id``; el hash-head y el contador monotónico se
persisten (``license_runtime_state``) y avanzan con cada evento. Borrar un
evento INTERMEDIO o editar un campo por DB directa rompe un eslabón y el
verificador lo reporta.

CONTRATO (limitación documentada, FR-028): el truncado de COLA (borrar los
últimos N eventos Y retroceder head+contador de forma consistente) o el wipe
TOTAL de la cadena NO es detectable localmente — quien controla el runtime
controla la DB. Su detección es la CONTINUIDAD ENTRE EXPORTS de true-up
(T040): un export firmado previo ancla head+contador fuera de la caja, y el
verificador lado-Basa rechaza un export posterior cuyo contador retrocede o
cuyo head previo no es ancestro. El ancla final es contractual (EULA).
"""
import pytest

from migration_harness import require_postgres
from seat_gate_harness import (
    build_app_client,
    restore_suite_license,
    set_license,
)

require_postgres()

DB = "basa_test_hash_chain"


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    yield client, factory, cleanup
    cleanup()


@pytest.fixture(autouse=True)
def _restore():
    from src.licensing import reconcile
    yield
    reconcile.reset_for_tests()
    restore_suite_license()


def _emit(factory, n, prefix="ev"):
    """Emite n eventos de licencia reales por el canal del producto."""
    from src.licensing.audit_events import EVENT_SEAT_LIMIT, emit_license_event
    db = factory()
    try:
        for i in range(n):
            emit_license_event(db, EVENT_SEAT_LIMIT, license_id="lic_test_0001",
                               seats_used=10 + i, max_seats=10,
                               reason=f"{prefix}-{i}")
    finally:
        db.close()


def _chained_rows(factory):
    """[(row_id, entry)] de eventos encadenados, orden por seq."""
    from src.models.audit import AuditLog
    db = factory()
    try:
        rows = db.query(AuditLog).filter(AuditLog.model == "license").all()
        out = [(r.id, r.guardian_events[0]) for r in rows
               if r.guardian_events and "seq" in r.guardian_events[0]]
        return sorted(out, key=lambda t: t[1]["seq"])
    finally:
        db.close()


def _state(factory):
    from src.models.license_state import LicenseRuntimeState
    db = factory()
    try:
        return db.query(LicenseRuntimeState).filter_by(id=1).one_or_none()
    finally:
        db.close()


def test_chain_links_persist_and_advance(harness, monkeypatch, tmp_path):
    """Relativo al estado preexistente: el arranque de la app ya encadena su
    license_loaded — la cadena arranca ANTES que este test, y eso es correcto."""
    from src.licensing.audit_events import entry_hash, genesis_anchor, verify_chain
    _client, factory, _cleanup = harness
    set_license(monkeypatch, tmp_path)  # licencia de suite (lic_test_0001)

    base_state = _state(factory)
    base_counter = base_state.event_counter if base_state else 0
    base_head = base_state.hash_head if base_state else None

    _emit(factory, 1, prefix="primero")
    rows = _chained_rows(factory)
    state = _state(factory)
    # Génesis anclada al license_id registrado (el PRIMER eslabón de todos).
    assert rows[0][1]["seq"] == 1
    assert rows[0][1]["prev_hash"] == genesis_anchor(state.genesis_license_id)
    # El evento nuevo apunta al head previo; head/contador avanzan y persisten.
    mine = rows[-1][1]
    assert mine["seq"] == base_counter + 1
    if base_head is not None:
        assert mine["prev_hash"] == base_head
    head_1 = state.hash_head
    assert head_1 == entry_hash(mine)
    assert state.event_counter == base_counter + 1

    _emit(factory, 2, prefix="mas")
    rows = _chained_rows(factory)
    state = _state(factory)
    assert state.event_counter == base_counter + 3
    assert state.hash_head == entry_hash(rows[-1][1])
    assert rows[-2][1]["prev_hash"] == head_1  # eslabón: cada evento apunta al head anterior

    db = factory()
    try:
        report = verify_chain(db)
    finally:
        db.close()
    assert report["ok"], report


def test_deleting_intermediate_event_breaks_chain(harness, monkeypatch, tmp_path):
    from src.licensing.audit_events import verify_chain
    from src.models.audit import AuditLog
    _client, factory, _cleanup = harness
    set_license(monkeypatch, tmp_path)
    _emit(factory, 3, prefix="del")
    rows = _chained_rows(factory)
    victim_id = rows[-2][0]  # INTERMEDIO (el último no: eso sería truncado de cola)

    db = factory()
    try:
        db.query(AuditLog).filter(AuditLog.id == victim_id).delete()
        db.commit()
        report = verify_chain(db)
    finally:
        db.close()
    assert not report["ok"]
    assert any("seq" in issue or "eslabón" in issue for issue in report["issues"]), report


def test_editing_event_field_breaks_chain(harness, monkeypatch, tmp_path):
    from sqlalchemy.orm.attributes import flag_modified

    from src.licensing.audit_events import verify_chain
    from src.models.audit import AuditLog
    _client, factory, _cleanup = harness
    set_license(monkeypatch, tmp_path)
    _emit(factory, 2, prefix="edit")
    rows = _chained_rows(factory)
    victim_id, victim_entry = rows[-2]

    db = factory()
    try:
        row = db.query(AuditLog).filter(AuditLog.id == victim_id).one()
        entry = dict(row.guardian_events[0])
        entry["seats_used"] = 999  # tamper: maquillar el conteo histórico
        row.guardian_events = [entry]
        flag_modified(row, "guardian_events")
        db.commit()
        report = verify_chain(db)
    finally:
        db.close()
    assert not report["ok"]
    assert any("hash" in issue for issue in report["issues"]), report
