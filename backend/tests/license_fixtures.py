"""Emisor de licencias DE PRUEBA para la suite (spec 021).

Simula el lado FIRMANTE (el portal de emisión de Basa): genera pares Ed25519,
arma el keyset PEM indexado por ``key_id`` y firma payloads ``.lic`` con el
mismo contrato wire que el producto verifica (JSON canónico ``sort_keys`` +
separadores compactos + firma detached base64url en ``sig``).

El contrato de canonicalización está DUPLICADO a propósito respecto de
``src/licensing/token.py``: el emisor real vive fuera de la caja (FR-002) y el
contract test del formato (T037) es quien fija el wire entre ambos lados.

La clave privada de estos pares existe sólo en memoria/tmp del test runner:
NUNCA se commitea (Constraint C5).
"""
import base64
import json
import os
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
SUITE_KID = "basa-test-suite"


def canonical_payload_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def generate_keypair():
    priv = Ed25519PrivateKey.generate()
    return priv, priv.public_key()


def public_key_pem(pub) -> str:
    return pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def keyset_pem(keys: dict) -> str:
    """Keyset multi-clave: cada bloque PEM precedido por su ``# key_id:`` (FR-007)."""
    blocks = [f"# key_id: {kid}\n{public_key_pem(pub)}" for kid, pub in keys.items()]
    return "\n".join(blocks)


def make_payload(**overrides) -> dict:
    payload = {
        "schema": 1,
        "lic_id": "lic_test_0001",
        "kid": SUITE_KID,
        "tenant_id": DEFAULT_TENANT_ID,
        "distributor_id": "d_basa",
        "pool_id": "pool_basa_directo",
        "max_seats": 500,
        "feature_flags": ["monitor"],
        "not_before": "2026-01-01T00:00:00Z",
        "expiry": "2099-01-01T00:00:00Z",
        "grace_days": 14,
    }
    payload.update(overrides)
    return payload


def sign_license(priv, payload: dict) -> str:
    """Firma detached sobre el payload canónico; el .lic en disco lleva el
    payload legible + ``sig`` (la firma cubre la forma canónica, no el pretty)."""
    sig = priv.sign(canonical_payload_bytes(payload))
    doc = dict(payload)
    doc["sig"] = base64.urlsafe_b64encode(sig).decode("ascii")
    return json.dumps(doc, indent=2)


def issue_files(dirpath, payload_overrides=None, *, kid=SUITE_KID, extra_keys=None):
    """Emite keyset.pem + token .lic en ``dirpath``. Devuelve (keyset_path,
    lic_path, priv) para que el test pueda re-firmar/tamperear."""
    dirpath = Path(dirpath)
    priv, pub = generate_keypair()
    keys = {kid: pub}
    if extra_keys:
        keys.update(extra_keys)
    overrides = dict(payload_overrides or {})
    overrides.setdefault("kid", kid)
    payload = make_payload(**overrides)
    keyset_path = dirpath / "keyset.pem"
    lic_path = dirpath / "token.lic"
    keyset_path.write_text(keyset_pem(keys))
    lic_path.write_text(sign_license(priv, payload))
    return keyset_path, lic_path, priv


def install_default_test_license():
    """Licencia dev de la SUITE: entitlement válido para el tenant default con
    max_seats alto, para que el fail-closed de la 021 no bloquee los tests
    preexistentes de creación. Los tests negativos overridean el env y llaman
    a ``entitlement.initialize(force=True)`` (restaurando al salir)."""
    tmp = Path(tempfile.mkdtemp(prefix="basa-license-suite-"))
    keyset_path, lic_path, _priv = issue_files(tmp)
    os.environ.setdefault("BASA_LICENSE_PUBLIC_KEYS_FILE", str(keyset_path))
    os.environ.setdefault("BASA_LICENSE_TOKEN_FILE", str(lic_path))
    return tmp
