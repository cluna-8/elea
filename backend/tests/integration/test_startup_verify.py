"""Integration tests de la verificación de licencia al ARRANQUE (spec 021, T008).

Cubre SC-002 (fail-closed ausente/corrupto/mismatch, con audit) y SC-013
(expiry degrada — grace/expired al boot — nunca mata el proceso). La emisión
del evento va contra el AuditLog inmutable real (Postgres migrado a head).
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from license_fixtures import issue_files, make_payload
from migration_harness import DEFAULT_TENANT, fresh_db, owner_engine, require_postgres, run_alembic

require_postgres()

DB = "basa_test_license_startup"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(scope="module")
def factory():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    engine = owner_engine(DB)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def _restore_entitlement():
    """El singleton es estado global del proceso: restaurar la licencia dev de
    la suite al salir para no contaminar otros tests."""
    yield
    from src.licensing import entitlement
    entitlement.initialize(force=True, emit_audit=False)


def _boot(monkeypatch, factory, keyset_path=None, lic_path=None):
    """Simula el gate de arranque: env de la 020 + initialize(force)."""
    from src.licensing import entitlement
    monkeypatch.delenv("BASA_LICENSE_TOKEN", raising=False)
    if keyset_path is not None:
        monkeypatch.setenv("BASA_LICENSE_PUBLIC_KEYS_FILE", str(keyset_path))
    if lic_path is None:
        monkeypatch.setenv("BASA_LICENSE_TOKEN_FILE", "/no/existe/token.lic")
    else:
        monkeypatch.setenv("BASA_LICENSE_TOKEN_FILE", str(lic_path))
    return entitlement.initialize(force=True, session_factory=factory)


def _license_events(factory):
    from src.models.audit import AuditLog
    db = factory()
    try:
        rows = (db.query(AuditLog)
                .filter(AuditLog.model == "license")
                .order_by(AuditLog.timestamp).all())
        return [(row.guardian_events[0], row.compliance_status) for row in rows]
    finally:
        db.close()


def test_valid_token_loads_entitlement(monkeypatch, factory, tmp_path):
    keyset_path, lic_path, _ = issue_files(tmp_path)
    state = _boot(monkeypatch, factory, keyset_path, lic_path)
    assert state.status == "active"
    assert state.token is not None
    assert state.token.max_seats == 500
    assert str(state.token.tenant_id) == str(DEFAULT_TENANT)
    event, compliance = _license_events(factory)[-1]
    assert event["event_type"] == "license_loaded"
    assert event["license_id"] == "lic_test_0001"
    assert compliance == "passed"


def test_tampered_token_boots_degraded_failclosed(monkeypatch, factory, tmp_path):
    keyset_path, lic_path, _ = issue_files(tmp_path)
    doc = json.loads(lic_path.read_text())
    doc["max_seats"] = 9999
    lic_path.write_text(json.dumps(doc))
    state = _boot(monkeypatch, factory, keyset_path, lic_path)
    assert state.status == "invalid"
    assert state.token is None  # NUNCA "token roto = ilimitado"
    event, compliance = _license_events(factory)[-1]
    assert event["event_type"] == "license_invalid"
    assert compliance == "blocked_by_policy"


def test_absent_token_boots_degraded_failclosed(monkeypatch, factory, tmp_path):
    keyset_path, _, _ = issue_files(tmp_path)
    state = _boot(monkeypatch, factory, keyset_path, lic_path=None)
    assert state.status == "missing"
    assert state.token is None
    event, _ = _license_events(factory)[-1]
    assert event["event_type"] == "license_missing"


def test_tenant_mismatch_rejected_with_audit(monkeypatch, factory, tmp_path):
    keyset_path, lic_path, _ = issue_files(
        tmp_path, {"tenant_id": "99999999-0000-0000-0000-000000000009"})
    state = _boot(monkeypatch, factory, keyset_path, lic_path)
    assert state.status == "mismatch"
    assert state.token is None
    event, compliance = _license_events(factory)[-1]
    assert event["event_type"] == "license_tenant_mismatch"
    assert compliance == "blocked_by_policy"
    # metadata-only pero útil: de qué tenant era el token que no correspondía
    assert "99999999" in (event.get("reason") or "")


def test_expired_within_grace_boots_in_grace_not_invalid(monkeypatch, factory, tmp_path):
    """SC-013: vencida DENTRO de grace → entitlement CARGADO con estado grace,
    proceso vivo (initialize retorna, no levanta)."""
    now = datetime.now(timezone.utc)
    keyset_path, lic_path, _ = issue_files(tmp_path, {
        "expiry": _iso(now - timedelta(days=5)), "grace_days": 14})
    state = _boot(monkeypatch, factory, keyset_path, lic_path)
    assert state.status == "grace"
    assert state.token is not None  # el entitlement SE CARGA (no es invalid)
    event, compliance = _license_events(factory)[-1]
    assert event["event_type"] == "license_grace"
    assert compliance == "flagged_high_risk"


def test_expired_beyond_grace_boots_expired_never_dies(monkeypatch, factory, tmp_path):
    """SC-013: vencida MÁS ALLÁ de grace → expired + degradado, 0 exits."""
    now = datetime.now(timezone.utc)
    keyset_path, lic_path, _ = issue_files(tmp_path, {
        "expiry": _iso(now - timedelta(days=30)), "grace_days": 14})
    state = _boot(monkeypatch, factory, keyset_path, lic_path)
    assert state.status == "expired"
    assert state.token is not None
    event, _ = _license_events(factory)[-1]
    assert event["event_type"] == "license_expired"


def test_inline_token_env_takes_precedence(monkeypatch, factory, tmp_path):
    """FR-026: el token también puede inyectarse INLINE (BASA_LICENSE_TOKEN);
    tiene prioridad sobre el fichero y un inline de sólo whitespace cae al
    fichero."""
    from src.licensing import entitlement
    keyset_path, lic_path, _ = issue_files(tmp_path)
    monkeypatch.setenv("BASA_LICENSE_PUBLIC_KEYS_FILE", str(keyset_path))
    # inline válido + fichero roto → gana el inline
    monkeypatch.setenv("BASA_LICENSE_TOKEN", lic_path.read_text())
    monkeypatch.setenv("BASA_LICENSE_TOKEN_FILE", "/no/existe/token.lic")
    state = entitlement.initialize(force=True, session_factory=factory)
    assert state.status == "active"
    # inline de sólo whitespace + fichero válido → cae al fichero
    monkeypatch.setenv("BASA_LICENSE_TOKEN", "   ")
    monkeypatch.setenv("BASA_LICENSE_TOKEN_FILE", str(lic_path))
    state = entitlement.initialize(force=True, session_factory=factory)
    assert state.status == "active"


def test_dev_key_rejected_without_explicit_optin(monkeypatch, factory, tmp_path):
    """Guard anti-neutralización: la licencia dev del repo (kid basa-dev-*) es
    PÚBLICA — sin el opt-in BASA_ALLOW_DEV_LICENSE=true se rechaza como
    invalid, aunque la firma valide. Con el opt-in (dev/demo) carga normal."""
    keyset_path, lic_path, _ = issue_files(tmp_path, kid="basa-dev-2026")
    monkeypatch.delenv("BASA_ALLOW_DEV_LICENSE", raising=False)
    state = _boot(monkeypatch, factory, keyset_path, lic_path)
    assert state.status == "invalid"
    assert "BASA_ALLOW_DEV_LICENSE" in (state.reason or "")
    assert state.token is None

    monkeypatch.setenv("BASA_ALLOW_DEV_LICENSE", "true")
    state = _boot(monkeypatch, factory, keyset_path, lic_path)
    assert state.status == "active"


def test_audit_events_are_metadata_only(monkeypatch, factory, tmp_path):
    """FR-024: cero token crudo / firma / claves en el audit."""
    keyset_path, lic_path, _ = issue_files(tmp_path)
    signature_b64 = json.loads(lic_path.read_text())["sig"]
    _boot(monkeypatch, factory, keyset_path, lic_path)
    for event, _ in _license_events(factory):
        serialized = json.dumps(event)
        assert signature_b64 not in serialized
        assert "BEGIN PUBLIC KEY" not in serialized
        assert "sig" not in event
