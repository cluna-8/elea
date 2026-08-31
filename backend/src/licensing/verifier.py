"""Verificación Ed25519 100% OFFLINE del ``.lic`` (spec 021, FR-003/004/005/007).

Cero llamadas de red: lectura de fichero local + criptografía en memoria.
El producto embebe SÓLO claves públicas (``SentinelPublicKeySet``, indexadas por
``key_id`` para rotación); la privada de firma vive del lado de Sentinel (FR-002).
"""
from pathlib import Path
from typing import Dict, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from .token import (
    LicenseError,
    LicenseMalformedError,
    LicenseToken,
    canonical_payload_bytes,
    split_signed_document,
)


class LicenseUnknownKeyError(LicenseError):
    """El ``kid`` del token no está en el keyset embebido."""


class LicenseSignatureError(LicenseError):
    """La firma Ed25519 no valida contra la pública seleccionada."""


class LicenseTenantMismatchError(LicenseError):
    """Token legítimo pero de OTRO tenant: no habilita este deployment (FR-005)."""


class SentinelPublicKeySet:
    """Conjunto de claves públicas Ed25519 indexadas por ``key_id`` (FR-007).

    Formato del fichero: bloques PEM ``PUBLIC KEY``, cada uno precedido por un
    comentario ``# key_id: <kid>``. Soportar N claves permite rotar la clave de
    Sentinel sin romper cajas ya desplegadas.
    """

    def __init__(self, keys: Dict[str, Ed25519PublicKey]):
        if not keys:
            raise LicenseError("keyset vacío: no hay claves públicas embebidas")
        self._keys = dict(keys)

    @classmethod
    def from_pem_file(cls, path) -> "SentinelPublicKeySet":
        text = Path(path).read_text(encoding="utf-8")
        keys: Dict[str, Ed25519PublicKey] = {}
        current_kid: Optional[str] = None
        block_lines = []
        in_block = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                comment = stripped.lstrip("#").strip()
                if comment.lower().startswith("key_id:"):
                    current_kid = comment.split(":", 1)[1].strip()
                continue
            if stripped == "-----BEGIN PUBLIC KEY-----":
                in_block = True
                block_lines = [stripped]
                continue
            if stripped == "-----END PUBLIC KEY-----":
                block_lines.append(stripped)
                in_block = False
                if not current_kid:
                    raise LicenseError(
                        f"keyset {path}: bloque PEM sin '# key_id:' precedente"
                    )
                key = load_pem_public_key("\n".join(block_lines).encode("ascii"))
                if not isinstance(key, Ed25519PublicKey):
                    raise LicenseError(
                        f"keyset {path}: la clave '{current_kid}' no es Ed25519"
                    )
                keys[current_kid] = key
                current_kid = None
                continue
            if in_block and stripped:
                block_lines.append(stripped)
        return cls(keys)

    def get(self, key_id: str) -> Optional[Ed25519PublicKey]:
        return self._keys.get(key_id)

    def key_ids(self):
        return sorted(self._keys)


def verify_license_blob(blob, keyset: SentinelPublicKeySet,
                        expected_tenant_id: Optional[str] = None) -> LicenseToken:
    """Verifica el ``.lic`` completo: estructura → firma → esquema → tenant.

    Orden deliberado: la firma se verifica sobre el payload canónico ANTES de
    interpretar su contenido; el mismatch de tenant se evalúa sólo sobre un
    token criptográficamente válido (un token forjado nunca llega ahí).
    """
    payload, signature = split_signed_document(blob)
    kid = payload.get("kid")
    if not isinstance(kid, str) or not kid:
        raise LicenseMalformedError("licencia: falta 'kid' para seleccionar la clave")
    public_key = keyset.get(kid)
    if public_key is None:
        raise LicenseUnknownKeyError(
            f"licencia: key_id '{kid}' no está en el keyset embebido {keyset.key_ids()}"
        )
    try:
        public_key.verify(signature, canonical_payload_bytes(payload))
    except InvalidSignature as exc:
        raise LicenseSignatureError("licencia: la firma Ed25519 no valida") from exc
    token = LicenseToken.from_payload(payload)
    if expected_tenant_id is not None and token.tenant_id != str(expected_tenant_id):
        raise LicenseTenantMismatchError(
            "licencia: el tenant del token no coincide con el del deployment"
        )
    return token
