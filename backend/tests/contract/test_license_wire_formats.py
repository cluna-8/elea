"""Contract tests de los formatos WIRE de licencia (spec 021, T037).

Tres artefactos cross-party cuya forma NO puede cambiar sin coordinación:

1. **Token .lic** (Basa → caja): payload canónico + ``sig`` — lo emite el
   tooling de Basa (KMS en prod, scripts/issue_dev_license.py en dev) y lo
   verifica la caja offline.
2. **Evento de audit de licencia** (caja → evidencia): entrada encadenada en
   ``guardian_events`` — la lee el true-up y la auditoría del cliente.
3. **TrueUpExport** (caja → Basa): payload canónico + ``sig`` de la deployment
   key — lo verifica Basa en renovación (FR-029).

Rotación de claves (contrato operativo, T037): el keyset PEM embebido indexa
por ``key_id`` (bloques ``# key_id: <kid>``); una licencia declara su ``kid``
y la caja elige esa pública. Rotar = publicar keyset nuevo (kid viejo + nuevo)
en la siguiente release, emitir licencias nuevas con el kid nuevo, y retirar
el kid viejo cuando no queden licencias vivas firmadas con él. La deployment
key NO rota por keyset: se regenera con el install y se re-registra la pública
en el onboarding.
"""
import json

import pytest

from license_fixtures import issue_files

# ── 1. Token .lic ──────────────────────────────────────────────────────────────

TOKEN_REQUIRED = {"schema", "lic_id", "kid", "tenant_id", "distributor_id", "pool_id",
                  "max_seats", "not_before", "expiry", "grace_days", "feature_flags", "sig"}


def test_lic_wire_format(tmp_path):
    _keyset, lic_path, _priv = issue_files(tmp_path)
    doc = json.loads(lic_path.read_text())
    assert TOKEN_REQUIRED.issubset(doc.keys()), sorted(TOKEN_REQUIRED - set(doc))
    assert doc["schema"] == 1
    assert isinstance(doc["max_seats"], int) and isinstance(doc["grace_days"], int)
    # La firma cubre la forma CANÓNICA (sort_keys/separators), no el pretty.
    from src.licensing.token import canonical_payload_bytes, split_signed_document
    payload, sig = split_signed_document(lic_path.read_text())
    assert sig  # detached, base64 en el doc
    canonical_payload_bytes(payload)  # no levanta = canonicalizable


# ── 2. Evento de audit encadenado ─────────────────────────────────────────────

EVENT_REQUIRED = {"event_type", "license_id", "seats_used", "max_seats", "reason",
                  "ts", "prev_hash", "seq"}
EVENT_TYPES = {"license_loaded", "license_grace", "license_expired", "license_invalid",
               "license_tenant_mismatch", "license_missing", "license_seat_limit_exceeded",
               "license_over_seat", "license_over_seat_resolved",
               "license_clock_rollback_suspected", "license_genesis_anchored"}


def test_license_audit_event_schema_constants():
    from src.licensing import audit_events as ae
    declared = {getattr(ae, name) for name in dir(ae) if name.startswith("EVENT_")}
    assert declared == EVENT_TYPES, ("cambió el catálogo de eventos de licencia — "
                                     "coordinar con true-up/auditoría antes de mover esto")


def test_license_audit_entry_hashing_is_stable():
    """El hash de una entrada es función SOLO de su forma canónica: si esto
    cambia, TODA cadena previa deja de verificar. Vectores fijos de regresión —
    el segundo con reason NO-ASCII (string real de producción) pinna la
    dimensión unicode (ensure_ascii): un vector solo-ASCII hashea idéntico con
    ensure_ascii=True/False y no la detectaría."""
    from src.licensing.audit_events import entry_hash
    from src.licensing.token import canonical_payload_bytes
    entry = {"event_type": "license_loaded", "license_id": "lic_fixed", "seats_used": 1,
             "max_seats": 2, "reason": None, "ts": "2026-07-20T00:00:00+00:00",
             "prev_hash": "0" * 64, "seq": 1}
    assert entry_hash(entry) == entry_hash(json.loads(json.dumps(entry)))
    assert entry_hash(entry) == "17b4d0ec822c2fee52cea5fd7e54d92a86a2ad99838fe84ebf0c8120ae6f54d7"

    unicode_entry = {**entry, "seq": 2,
                     "reason": "reconciliación: seats activos por encima del entitlement"}
    # Bytes canónicos pinneados: UTF-8 crudo (ensure_ascii=False), sort_keys,
    # separadores compactos — byte a byte, no solo el hash.
    assert canonical_payload_bytes(unicode_entry) == (
        b'{"event_type":"license_loaded","license_id":"lic_fixed","max_seats":2,'
        b'"prev_hash":"' + b"0" * 64 + b'","reason":"reconciliaci\xc3\xb3n: seats '
        b'activos por encima del entitlement","seats_used":1,"seq":2,'
        b'"ts":"2026-07-20T00:00:00+00:00"}'
    )
    assert entry_hash(unicode_entry) == "a046337805372db2b22a63d5cf863affc664938e89ebcdf3d2bfebba6ccb4764"


# ── 3. TrueUpExport ───────────────────────────────────────────────────────────

TRUEUP_REQUIRED = {"schema", "kind", "tenant_id", "license_id", "distributor_id",
                   "pool_id", "license_status", "max_seats", "seats_used",
                   "generated_at", "genesis_license_id", "hash_head", "counter",
                   "range", "events", "sig"}


def test_trueup_wire_format(monkeypatch, tmp_path):
    from src.licensing import deployment_key, trueup_export
    monkeypatch.setenv(deployment_key.DEPLOYMENT_KEY_ENV, str(tmp_path / "dk.pem"))

    class _FakeQuery:
        def filter(self, *a, **k):
            return self
        def all(self):
            return []
        def one_or_none(self):
            return None
        def scalar(self):
            return 0

    class _FakeSession:
        def query(self, *a, **k):
            return _FakeQuery()
        def close(self):
            pass

    doc = trueup_export.generate_signed_export(session_factory=_FakeSession)
    assert set(doc.keys()) == TRUEUP_REQUIRED, sorted(set(doc) ^ TRUEUP_REQUIRED)
    assert doc["kind"] == "basa-trueup" and doc["schema"] == 1
    assert set(doc["range"].keys()) == {"from_seq", "to_seq"}
    # Round-trip JSON (el archivo que viaja) verifica igual.
    trueup_export.verify_export(json.loads(json.dumps(doc)), deployment_key.public_key_pem())
    with pytest.raises(trueup_export.TrueUpError):
        trueup_export.verify_export({**doc, "seats_used": 99}, deployment_key.public_key_pem())