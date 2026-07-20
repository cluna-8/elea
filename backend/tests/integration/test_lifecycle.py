"""Integration tests del ciclo de vida de licencia con reloj INYECTADO
(spec 021, T026 — SC-006; FR-018/019/020/021).

`active → grace → expired` computado con reloj local (offline): en grace la
creación se bloquea pero el tráfico existente sigue; en expired el default es
read-only-para-creación; el toggle `BASA_LICENSE_HARD_BLOCK=true` endurece
expired/over_seat a bloqueo total del tráfico /gw (grace JAMÁS corta tráfico,
FR-019). Cada transición deja UN evento de audit (idempotente por estado).
"""
from datetime import datetime, timezone

import pytest

from migration_harness import DEFAULT_TENANT, require_postgres
from seat_gate_harness import (
    admin_headers,
    build_app_client,
    clear_monotonic_mark,
    current_seats,
    license_audit_events,
    mock_engine,
    restore_suite_license,
    seed_active_seats,
    set_license,
)

require_postgres()

DB = "basa_test_lifecycle"

EXPIRY = "2027-01-01T00:00:00Z"
GRACE_DAYS = 7

T_ACTIVE = datetime(2026, 12, 1, tzinfo=timezone.utc)
T_GRACE = datetime(2027, 1, 3, tzinfo=timezone.utc)      # expiry + 2d, dentro del grace de 7d
T_EXPIRED = datetime(2027, 1, 20, tzinfo=timezone.utc)   # más allá de expiry + grace


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    headers = admin_headers(client)
    yield client, factory, headers
    cleanup()


@pytest.fixture(autouse=True)
def _restore(harness):
    from src.licensing import reconcile
    yield
    _client, factory, _headers = harness
    clear_monotonic_mark(factory)  # los relojes 2027 inyectados no arman rollback en el test siguiente
    reconcile.reset_for_tests()
    restore_suite_license()


def _count_events(factory, event_type):
    return len([e for e in license_audit_events(factory)
                if e["event_type"] == event_type])


def test_lifecycle_transitions_block_creation_and_audit(harness, monkeypatch, tmp_path):
    from src.licensing import entitlement
    client, factory, headers = harness
    recorder = mock_engine(monkeypatch)
    set_license(monkeypatch, tmp_path, expiry=EXPIRY, grace_days=GRACE_DAYS)
    grace_before = _count_events(factory, "license_grace")
    expired_before = _count_events(factory, "license_expired")

    # ACTIVE: la creación funciona.
    state = entitlement.refresh(now=T_ACTIVE, session_factory=factory)
    assert state.status == entitlement.STATUS_ACTIVE
    resp = client.post("/api/v1/keys", headers=headers, json={"name": "activa-crea"})
    assert resp.status_code == 201, resp.text

    # GRACE: creación bloqueada + transición auditada; el tráfico existente
    # sigue (FR-019) — la Connection creada en active se sigue sirviendo.
    state = entitlement.refresh(now=T_GRACE, session_factory=factory)
    assert state.status == entitlement.STATUS_GRACE
    resp = client.post("/api/v1/keys", headers=headers, json={"name": "grace-bloquea"})
    assert resp.status_code == 403, resp.text
    assert "license_creation_blocked" in resp.json()["detail"]
    assert _count_events(factory, "license_grace") == grace_before + 1
    listed = client.get("/api/v1/keys", headers=headers)
    assert listed.status_code == 200
    assert any(k["name"] == "activa-crea" for k in listed.json())

    # Idempotente: re-evaluar en el MISMO estado no duplica el evento (FR-022
    # audita transiciones, no ticks).
    entitlement.refresh(now=T_GRACE, session_factory=factory)
    assert _count_events(factory, "license_grace") == grace_before + 1

    # EXPIRED: degradado read-only-para-creación + transición auditada.
    state = entitlement.refresh(now=T_EXPIRED, session_factory=factory)
    assert state.status == entitlement.STATUS_EXPIRED
    resp = client.post("/api/v1/keys", headers=headers, json={"name": "expired-bloquea"})
    assert resp.status_code == 403, resp.text
    assert _count_events(factory, "license_expired") == expired_before + 1

    # Cero provisioning en TODOS los rechazos: solo la creación de active pasó.
    assert len(recorder.generate_key_calls) == 1


def test_reconcile_tick_advances_lifecycle(harness, monkeypatch, tmp_path):
    """T025→T029: el tick de la reconciliación ES el reloj del ciclo de vida —
    un proceso vivo transiciona sin reinicio y publica expired por tenant."""
    from src.licensing import entitlement, reconcile
    _client, factory, _headers = harness
    set_license(monkeypatch, tmp_path, expiry=EXPIRY, grace_days=GRACE_DAYS)
    assert entitlement.get_state().status == entitlement.STATUS_ACTIVE

    reconcile.run_once(session_factory=factory, now=T_GRACE)
    assert entitlement.get_state().status == entitlement.STATUS_GRACE

    statuses = reconcile.run_once(session_factory=factory, now=T_EXPIRED)
    assert entitlement.get_state().status == entitlement.STATUS_EXPIRED
    assert statuses[str(DEFAULT_TENANT)].status == reconcile.RECON_EXPIRED


def test_hard_block_toggle_cuts_gw_traffic(harness, monkeypatch, tmp_path):
    """FR-020: default read-only-para-creación (ni expired corta tráfico); con
    el toggle, expired corta TODO /gw con 403 SIN tocar upstream; grace jamás
    corta (FR-019)."""
    from src.licensing import degraded, entitlement
    client, factory, _headers = harness
    set_license(monkeypatch, tmp_path, expiry=EXPIRY, grace_days=GRACE_DAYS)

    # Default (toggle apagado): expired NO corta el tráfico.
    entitlement.refresh(now=T_EXPIRED, session_factory=factory)
    assert degraded.hard_block_reason() is None

    monkeypatch.setenv("BASA_LICENSE_HARD_BLOCK", "true")
    # Grace no corta tráfico ni con el toggle activo (FR-019).
    entitlement.refresh(now=T_GRACE, session_factory=factory)
    assert degraded.hard_block_reason() is None

    # Expired + toggle: TODAS las rutas de servicio /gw cortan 403 antes de
    # rutear o tocar upstream — incl. count_tokens (reenvía el body VERBATIM
    # sin enmascarar) y la superficie DLP de la extensión. El discovery
    # (GET /gw) queda abierto para diagnóstico.
    entitlement.refresh(now=T_EXPIRED, session_factory=factory)
    for method, path in [
        ("post", "/api/v1/gw/v1/messages"),
        ("post", "/api/v1/gw/v1/messages/count_tokens"),
        ("get", "/api/v1/gw/v1/models"),
        ("get", "/api/v1/gw/whoami"),
        ("post", "/api/v1/gw/inspect"),
    ]:
        resp = getattr(client, method)(path, **({"json": {"model": "claude-x", "messages": []}}
                                                if method == "post" else {}))
        assert resp.status_code == 403, f"{path}: {resp.status_code} {resp.text}"
        assert "license_degraded" in resp.text
    assert client.get("/api/v1/gw").status_code == 200  # discovery abierto


def test_hard_block_on_over_seat_with_generic_message(harness, monkeypatch, tmp_path):
    """FR-020 cubre over_seat; el 403 corre ANTES de autenticar, así que el
    cliente recibe un mensaje FIJO — sin seats ni estado interno."""
    from src.licensing import degraded, reconcile
    client, factory, _headers = harness
    base = current_seats(factory)
    set_license(monkeypatch, tmp_path, max_seats=base)
    seed_active_seats(factory, 1, prefix="hard")  # drift: base+1 > base
    monkeypatch.setenv("BASA_LICENSE_HARD_BLOCK", "true")

    assert degraded.hard_block_reason() is None  # sin reconciliar aún, no corta
    reconcile.run_once(session_factory=factory)
    reason = degraded.hard_block_reason()
    assert reason is not None and "over_seat" in reason  # detalle: SOLO server-side
    resp = client.post("/api/v1/gw/v1/messages", json={"model": "claude-x", "messages": []})
    assert resp.status_code == 403, resp.text
    assert "license_degraded" in resp.text
    assert "seats" not in resp.text          # ni conteos…
    assert "over_seat" not in resp.text      # …ni el estado interno al cliente


def test_transient_read_blip_keeps_valid_state(harness, monkeypatch, tmp_path):
    """Hardening post-review: un blip de I/O leyendo el token en UN tick (p.ej.
    rotación de secret no atómica) NO degrada un estado con firma validada, no
    publica over_seat espurio ni contamina el AuditLog append-only."""
    import os as _os

    from src.licensing import entitlement, reconcile
    _client, factory, _headers = harness
    set_license(monkeypatch, tmp_path, expiry=EXPIRY, grace_days=GRACE_DAYS)
    assert entitlement.get_state().status == entitlement.STATUS_ACTIVE
    events_before = len(license_audit_events(factory))

    lic_path = _os.environ["BASA_LICENSE_TOKEN_FILE"]
    _os.rename(lic_path, lic_path + ".mv")  # el fichero desaparece durante el tick
    try:
        statuses = reconcile.run_once(session_factory=factory, now=T_ACTIVE)
        assert entitlement.get_state().status == entitlement.STATUS_ACTIVE  # conservado
        assert statuses[str(DEFAULT_TENANT)].status == reconcile.RECON_OK   # sin over_seat espurio
        assert len(license_audit_events(factory)) == events_before          # sin filas espurias
    finally:
        _os.rename(lic_path + ".mv", lic_path)

    statuses = reconcile.run_once(session_factory=factory, now=T_ACTIVE)    # tick sano
    assert entitlement.get_state().status == entitlement.STATUS_ACTIVE
    assert statuses[str(DEFAULT_TENANT)].status == reconcile.RECON_OK
    assert len(license_audit_events(factory)) == events_before


def test_persistent_read_failure_degrades_fail_closed(harness, monkeypatch, tmp_path):
    """La histéresis NO neutraliza el fail-closed: tras READ_FAILURE_TOLERANCE
    ticks seguidos con el material ilegible, el estado degrada a missing (y la
    vuelta del fichero lo restaura, con ambas transiciones auditadas)."""
    import os as _os

    from src.licensing import entitlement, reconcile
    _client, factory, _headers = harness
    set_license(monkeypatch, tmp_path, expiry=EXPIRY, grace_days=GRACE_DAYS)

    lic_path = _os.environ["BASA_LICENSE_TOKEN_FILE"]
    _os.rename(lic_path, lic_path + ".mv")
    try:
        for _ in range(entitlement.READ_FAILURE_TOLERANCE):
            reconcile.run_once(session_factory=factory, now=T_ACTIVE)
            assert entitlement.get_state().status == entitlement.STATUS_ACTIVE
        reconcile.run_once(session_factory=factory, now=T_ACTIVE)  # tolerancia agotada
        assert entitlement.get_state().status == entitlement.STATUS_MISSING
    finally:
        _os.rename(lic_path + ".mv", lic_path)

    reconcile.run_once(session_factory=factory, now=T_ACTIVE)
    assert entitlement.get_state().status == entitlement.STATUS_ACTIVE
