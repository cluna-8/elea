"""Emisor DEV de licencias (spec 021) — herramienta de repo, NO se despliega.

Simula el portal de emisión de Basa para desarrollo/demo: genera un par
Ed25519, escribe la PÚBLICA en el keyset embebido del producto
(``src/keys/basa_public_keys.pem``, kid ``basa-dev-2026``) y firma la licencia
demo (``config/licenses/dev-demo.lic``) para el tenant default.

La PRIVADA queda en ``scripts/license_out/`` (gitignored) por si hay que
re-emitir sin rotar; si se pierde, correr el script de nuevo rota el par y
re-firma — las cajas con el keyset viejo deben actualizarlo (FR-007).

En producción este flujo NO existe: la clave de firma real vive en KMS/HSM de
Basa y el keyset embebido se reemplaza en el onboarding (020/021). El pack de
fricción de la 020 excluye este script y el kid dev de la imagen prod.

Uso (dentro del container backend, cwd=/app):
    python scripts/issue_dev_license.py
"""
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

APP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_ROOT))

from src.licensing.token import canonical_payload_bytes  # noqa: E402

DEV_KID = "basa-dev-2026"
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

KEYSET_PATH = APP_ROOT / "src" / "keys" / "basa_public_keys.pem"
LICENSE_PATH = APP_ROOT / "config" / "licenses" / "dev-demo.lic"
PRIVATE_OUT = APP_ROOT / "scripts" / "license_out" / "dev_signing_key.pem"

DEV_PAYLOAD = {
    "schema": 1,
    "lic_id": "lic_dev_demo_0001",
    "kid": DEV_KID,
    "tenant_id": DEFAULT_TENANT_ID,
    "distributor_id": "d_basa",          # emisión directa sin canal (FR-001)
    "pool_id": "pool_basa_dev",
    "max_seats": 50,
    "feature_flags": ["monitor"],
    "not_before": "2026-01-01T00:00:00Z",
    # Sin time-bomb en demos: la licencia dev no expira en la práctica; las
    # licencias reales de cliente las emite el portal de Basa con expiry real.
    "expiry": "2099-01-01T00:00:00Z",
    "grace_days": 14,
}


def main() -> None:
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()

    pub_pem = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    KEYSET_PATH.parent.mkdir(parents=True, exist_ok=True)
    KEYSET_PATH.write_text(
        "# BasaPublicKeySet — claves PÚBLICAS Ed25519 del firmante de licencias\n"
        "# (spec 021, FR-002/FR-007). SÓLO públicas: la privada de firma vive del\n"
        "# lado de Basa (KMS/HSM) y NUNCA en la caja ni en este repo.\n"
        f"# El kid '{DEV_KID}' es la clave DEV/DEMO (emitida por\n"
        "# scripts/issue_dev_license.py); en el onboarding de un cliente real se\n"
        "# reemplaza/añade la clave prod de Basa y la imagen prod (020) excluye\n"
        "# la dev.\n"
        f"# generado: {datetime.now(timezone.utc).isoformat()}\n"
        f"# key_id: {DEV_KID}\n"
        f"{pub_pem}"
    )

    payload = dict(DEV_PAYLOAD)
    payload["issued_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    signature = priv.sign(canonical_payload_bytes(payload))
    document = dict(payload)
    document["sig"] = base64.urlsafe_b64encode(signature).decode("ascii")
    LICENSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LICENSE_PATH.write_text(json.dumps(document, indent=2) + "\n")

    PRIVATE_OUT.parent.mkdir(parents=True, exist_ok=True)
    PRIVATE_OUT.write_bytes(priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))

    print(f"keyset  -> {KEYSET_PATH}")
    print(f"licencia-> {LICENSE_PATH} (tenant={payload['tenant_id']}, max_seats={payload['max_seats']})")
    print(f"privada -> {PRIVATE_OUT} (gitignored — NO commitear)")


if __name__ == "__main__":
    main()
