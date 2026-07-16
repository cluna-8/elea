"""Unit tests del verificador Ed25519 offline (spec 021, T006).

Cubre FR-003 (verificación contra la pública embebida), FR-005 (mismatch de
tenant), FR-006 (ausente/corrupto → rechazo) y FR-007 (rotación por key_id).
Todo en memoria/tmp: cero red, cero DB.
"""
import base64
import json

import pytest

from license_fixtures import (
    SUITE_KID,
    generate_keypair,
    issue_files,
    keyset_pem,
    make_payload,
    sign_license,
)

from src.licensing.token import LicenseMalformedError, LicenseToken
from src.licensing.verifier import (
    BasaPublicKeySet,
    LicenseSignatureError,
    LicenseTenantMismatchError,
    LicenseUnknownKeyError,
    verify_license_blob,
)


@pytest.fixture()
def issued(tmp_path):
    keyset_path, lic_path, priv = issue_files(tmp_path)
    keyset = BasaPublicKeySet.from_pem_file(keyset_path)
    return keyset, lic_path.read_text(), priv


def test_valid_signature_parses_token(issued):
    keyset, blob, _priv = issued
    token = verify_license_blob(blob, keyset)
    assert isinstance(token, LicenseToken)
    assert token.license_id == "lic_test_0001"
    assert token.key_id == SUITE_KID
    assert token.tenant_id == "00000000-0000-0000-0000-000000000001"
    assert token.max_seats == 500
    assert token.grace_days == 14
    assert token.feature_enabled("monitor")
    # flag ausente = OFF (fail-closed)
    assert not token.feature_enabled("modulo-inexistente")


def test_tampered_payload_rejected(issued):
    """Un byte alterado del payload tras la firma → LicenseSignatureError."""
    keyset, blob, _priv = issued
    doc = json.loads(blob)
    doc["max_seats"] = doc["max_seats"] + 1  # el cliente se "auto-amplía" seats
    tampered = json.dumps(doc)
    with pytest.raises(LicenseSignatureError):
        verify_license_blob(tampered, keyset)


def test_tampered_signature_rejected(issued):
    keyset, blob, _priv = issued
    doc = json.loads(blob)
    sig = bytearray(base64.urlsafe_b64decode(doc["sig"]))
    sig[0] ^= 0x01  # un bit
    doc["sig"] = base64.urlsafe_b64encode(bytes(sig)).decode("ascii")
    with pytest.raises(LicenseSignatureError):
        verify_license_blob(json.dumps(doc), keyset)


def test_tenant_mismatch_rejected(issued):
    """Token legítimo de OTRO tenant no habilita este deployment (FR-005)."""
    keyset, blob, _priv = issued
    with pytest.raises(LicenseTenantMismatchError):
        verify_license_blob(blob, keyset, expected_tenant_id="99999999-0000-0000-0000-000000000009")


def test_matching_tenant_accepted(issued):
    keyset, blob, _priv = issued
    token = verify_license_blob(
        blob, keyset, expected_tenant_id="00000000-0000-0000-0000-000000000001"
    )
    assert token.tenant_id == "00000000-0000-0000-0000-000000000001"


@pytest.mark.parametrize("blob", [
    "",                          # vacío
    "esto no es json",           # corrupto
    "{}",                        # sin campos ni firma
    json.dumps({"schema": 1}),   # sin sig
])
def test_absent_or_corrupt_rejected(issued, blob):
    keyset, _blob, _priv = issued
    with pytest.raises(LicenseMalformedError):
        verify_license_blob(blob, keyset)


def test_missing_required_field_rejected(tmp_path):
    """Payload firmado pero sin un campo obligatorio (FR-001) → malformado."""
    priv, pub = generate_keypair()
    payload = make_payload()
    del payload["max_seats"]
    blob = sign_license(priv, payload)
    keyset = BasaPublicKeySet({SUITE_KID: pub})
    with pytest.raises(LicenseMalformedError):
        verify_license_blob(blob, keyset)


def test_key_rotation_by_key_id(tmp_path):
    """Token firmado con la clave A se verifica contra el set {A, B} vía key_id
    (FR-007: rotación sin romper cajas desplegadas)."""
    priv_a, pub_a = generate_keypair()
    _priv_b, pub_b = generate_keypair()
    payload = make_payload(kid="basa-2026-a")
    blob = sign_license(priv_a, payload)
    pem = tmp_path / "keyset.pem"
    pem.write_text(keyset_pem({"basa-2026-a": pub_a, "basa-2026-b": pub_b}))
    keyset = BasaPublicKeySet.from_pem_file(pem)
    token = verify_license_blob(blob, keyset)
    assert token.key_id == "basa-2026-a"


def test_unknown_key_id_rejected(issued, tmp_path):
    """El kid del token no está en el keyset embebido → rechazo explícito."""
    _keyset, blob, _priv = issued
    _priv_c, pub_c = generate_keypair()
    keyset_otro = BasaPublicKeySet({"otra-clave": pub_c})
    with pytest.raises(LicenseUnknownKeyError):
        verify_license_blob(blob, keyset_otro)


def test_signature_from_wrong_key_rejected(tmp_path):
    """Mismo kid pero firmado con OTRA privada (suplantación) → firma inválida."""
    priv_falso, _pub_falso = generate_keypair()
    _priv_real, pub_real = generate_keypair()
    blob = sign_license(priv_falso, make_payload())
    keyset = BasaPublicKeySet({SUITE_KID: pub_real})
    with pytest.raises(LicenseSignatureError):
        verify_license_blob(blob, keyset)
