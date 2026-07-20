"""Integration tests del export de true-up firmado con la deployment key
(spec 021, T040 — SC-012, FR-028/FR-029).

El export se genera 100% local (sin egress), refleja lo que la caja registró
(seats + historial encadenado + hash-head + contador) y va firmado con la
deployment key (Ed25519, generada en el install, privada en volumen). El
verificador (lado Basa, MISMO módulo) valida: firma; cadena interna; génesis
del onboarding en el PRIMER export; y continuidad entre exports sucesivos —
contador no-decreciente y head previo ANCESTRO — rechazando un export
post-truncado. Metadata-only: 0 PII, 0 token crudo.
"""
import json

import pytest

from migration_harness import require_postgres
from seat_gate_harness import (
    build_app_client,
    clear_license,
    restore_suite_license,
    set_license,
)

require_postgres()

DB = "basa_test_trueup"


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


@pytest.fixture
def dep_key(monkeypatch, tmp_path):
    """Deployment key efímera en tmp (en prod: volumen/secret, jamás repo)."""
    from src.licensing import deployment_key
    monkeypatch.setenv(deployment_key.DEPLOYMENT_KEY_ENV,
                       str(tmp_path / "deployment_key.pem"))
    deployment_key.ensure_deployment_key()
    return deployment_key.public_key_pem()


def _emit(factory, n, prefix="tu"):
    from src.licensing.audit_events import EVENT_SEAT_LIMIT, emit_license_event
    db = factory()
    try:
        for i in range(n):
            emit_license_event(db, EVENT_SEAT_LIMIT, license_id="lic_test_0001",
                               seats_used=5 + i, max_seats=5, reason=f"{prefix}-{i}")
    finally:
        db.close()


def _wipe_chain(factory):
    """Simula el truncado/wipe que la cadena local NO puede detectar (T039):
    borra eventos y resetea el estado — la detección es responsabilidad del
    verificador de continuidad entre exports."""
    from src.models.audit import AuditLog
    from src.models.license_state import LicenseRuntimeState
    db = factory()
    try:
        db.query(AuditLog).filter(AuditLog.model == "license").delete()
        db.query(LicenseRuntimeState).delete()
        db.commit()
    finally:
        db.close()


def test_signed_export_verifies_and_tamper_invalidates(harness, monkeypatch, tmp_path, dep_key):
    from src.licensing import trueup_export
    _client, factory, _cleanup = harness
    set_license(monkeypatch, tmp_path)
    _emit(factory, 3)

    doc = trueup_export.generate_signed_export(session_factory=factory)
    # Refleja lo que la caja registró, con el ancla de la cadena.
    assert doc["kind"] == "basa-trueup"
    assert doc["counter"] >= 3 and doc["hash_head"]
    assert len(doc["events"]) == doc["counter"]
    assert "sig" in doc

    trueup_export.verify_export(doc, dep_key)  # OK: no levanta

    # Un byte alterado (maquillar seats) → firma inválida.
    tampered = json.loads(json.dumps(doc))
    tampered["seats_used"] = (doc["seats_used"] or 0) + 7  # garantiza un cambio real
    with pytest.raises(trueup_export.TrueUpError, match="firma"):
        trueup_export.verify_export(tampered, dep_key)

    # Metadata-only: el token crudo no viaja en el export.
    import os
    raw_blob = open(os.environ["BASA_LICENSE_TOKEN_FILE"], encoding="utf-8").read()
    assert raw_blob not in json.dumps(doc)


def test_first_export_checks_onboarding_genesis(harness, monkeypatch, tmp_path, dep_key):
    from src.licensing import trueup_export
    _client, factory, _cleanup = harness
    set_license(monkeypatch, tmp_path)
    _emit(factory, 1)
    doc = trueup_export.generate_signed_export(session_factory=factory)

    # El PRIMER export valida contra la génesis registrada en el onboarding…
    trueup_export.verify_export(doc, dep_key,
                                expected_genesis_license_id=doc["genesis_license_id"])
    # …y una génesis distinta (otra licencia/caja) se rechaza.
    with pytest.raises(trueup_export.TrueUpError, match="génesis"):
        trueup_export.verify_export(doc, dep_key,
                                    expected_genesis_license_id="lic_de_otra_caja")


def test_unlicensed_first_boot_genesis_gets_anchored(harness, monkeypatch, tmp_path, dep_key):
    """Hardening post-review (no-circular): una caja cuyo PRIMER boot fue sin
    .lic queda con génesis 'unlicensed' — al cargar la licencia real, la cadena
    la ata (license_genesis_anchored) y el primer export valida contra el
    license_id del ONBOARDING (no contra lo que la caja diga); un id ajeno
    sigue rechazándose."""
    from src.licensing import entitlement, trueup_export
    _client, factory, _cleanup = harness
    _wipe_chain(factory)  # caja "nueva": sin fila singleton ni eventos

    # Boot sin licencia → license_missing con license_id=None → génesis 'unlicensed'.
    clear_license(monkeypatch)
    entitlement.initialize(force=True, emit_audit=True, session_factory=factory)

    # Llega la licencia del onboarding → license_loaded dispara el anclaje.
    set_license(monkeypatch, tmp_path)
    entitlement.initialize(force=True, emit_audit=True, session_factory=factory)

    doc = trueup_export.generate_signed_export(session_factory=factory)
    assert doc["genesis_license_id"] == "unlicensed"
    anchored = [e for e in doc["events"] if e["event_type"] == "license_genesis_anchored"]
    assert len(anchored) == 1 and anchored[0]["license_id"] == "lic_test_0001"

    # Valida contra el id que Basa registró en el onboarding (dato EXTERNO)…
    trueup_export.verify_export(doc, dep_key, expected_genesis_license_id="lic_test_0001")
    # …y un license_id ajeno se rechaza aunque la génesis sea 'unlicensed'.
    with pytest.raises(trueup_export.TrueUpError, match="anclaje|génesis"):
        trueup_export.verify_export(doc, dep_key, expected_genesis_license_id="lic_de_otra_caja")


def test_successive_exports_continuity_and_truncation_rejected(harness, monkeypatch, tmp_path, dep_key):
    from src.licensing import trueup_export
    _client, factory, _cleanup = harness
    set_license(monkeypatch, tmp_path)

    _emit(factory, 2, prefix="a")
    first = trueup_export.generate_signed_export(session_factory=factory)
    _emit(factory, 2, prefix="b")
    second = trueup_export.generate_signed_export(session_factory=factory)

    # Continuidad honesta: contador avanza y el head del primero es ancestro.
    trueup_export.verify_export(second, dep_key, previous=first)
    # En sentido inverso el contador RETROCEDE → rechazo.
    with pytest.raises(trueup_export.TrueUpError, match="contador|ancestro"):
        trueup_export.verify_export(first, dep_key, previous=second)

    # Post-truncado: wipe + cadena nueva CON MÁS eventos que el export previo —
    # el contador solo no delata; el head previo ya no es ancestro.
    _wipe_chain(factory)
    _emit(factory, second["counter"] + 1, prefix="c")
    rebuilt = trueup_export.generate_signed_export(session_factory=factory)
    assert rebuilt["counter"] > second["counter"]
    with pytest.raises(trueup_export.TrueUpError, match="ancestro"):
        trueup_export.verify_export(rebuilt, dep_key, previous=second)
