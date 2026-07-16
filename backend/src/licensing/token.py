"""Formato del artefacto de licencia ``.lic`` (spec 021, FR-001).

Wire (fijado en research.md): JSON con nombres compactos (``lic_id``/``kid``)
+ firma Ed25519 detached en el campo ``sig``, calculada sobre el JSON CANÓNICO
del payload (sin ``sig``): claves ordenadas, separadores compactos, UTF-8.

Este módulo sólo PARSEA y define el esquema; la verificación criptográfica
vive en ``verifier.py`` y el firmante fuera de la caja (FR-002).
"""
import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

WIRE_SIG_FIELD = "sig"

# Versión del formato wire soportada por ESTA caja. Un schema desconocido se
# rechaza (fail-closed): un .lic v2 legítimamente firmado con semántica nueva
# jamás debe interpretarse en silencio con semántica v1.
SUPPORTED_SCHEMA = 1

# FR-001: campos mínimos del artefacto (issued_at es opcional ≈ not_before).
REQUIRED_FIELDS = (
    "schema", "lic_id", "kid", "tenant_id", "distributor_id", "pool_id",
    "max_seats", "not_before", "expiry", "grace_days", "feature_flags",
)


class LicenseError(Exception):
    """Base de todos los errores de licencia."""


class LicenseMalformedError(LicenseError):
    """Token ausente, corrupto, o con esquema inválido (FR-006)."""


def canonical_payload_bytes(payload: dict) -> bytes:
    """Forma canónica firmada: la firma cubre ESTO, no el JSON del disco."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _parse_ts(value, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise LicenseMalformedError(f"licencia: '{field_name}' debe ser timestamp ISO 8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LicenseMalformedError(f"licencia: '{field_name}' no es ISO 8601: {value!r}") from exc
    if parsed.tzinfo is None:
        raise LicenseMalformedError(f"licencia: '{field_name}' debe llevar timezone (UTC)")
    return parsed


@dataclass(frozen=True)
class LicenseToken:
    """Payload verificado del ``.lic``, con nombres conceptuales de la spec."""

    schema: int
    license_id: str
    key_id: str
    tenant_id: str
    distributor_id: str
    pool_id: str
    max_seats: int
    feature_flags: Tuple[str, ...]
    not_before: datetime
    expiry: datetime
    grace_days: int
    issued_at: Optional[datetime]

    @classmethod
    def from_payload(cls, payload: dict) -> "LicenseToken":
        missing = [f for f in REQUIRED_FIELDS if f not in payload]
        if missing:
            raise LicenseMalformedError(f"licencia: faltan campos obligatorios: {missing}")
        if payload["schema"] != SUPPORTED_SCHEMA:
            raise LicenseMalformedError(
                f"licencia: schema {payload['schema']!r} no soportado "
                f"(esta versión entiende schema={SUPPORTED_SCHEMA})"
            )
        if not isinstance(payload["max_seats"], int) or isinstance(payload["max_seats"], bool) \
                or payload["max_seats"] < 0:
            raise LicenseMalformedError("licencia: 'max_seats' debe ser un entero >= 0")
        if not isinstance(payload["grace_days"], int) or isinstance(payload["grace_days"], bool) \
                or payload["grace_days"] < 0:
            raise LicenseMalformedError("licencia: 'grace_days' debe ser un entero >= 0")
        if not isinstance(payload["feature_flags"], list):
            raise LicenseMalformedError("licencia: 'feature_flags' debe ser una lista")
        for text_field in ("lic_id", "kid", "tenant_id", "distributor_id", "pool_id"):
            if not isinstance(payload[text_field], str) or not payload[text_field]:
                raise LicenseMalformedError(f"licencia: '{text_field}' debe ser string no vacío")
        issued_at = payload.get("issued_at")
        return cls(
            schema=payload["schema"],
            license_id=payload["lic_id"],
            key_id=payload["kid"],
            tenant_id=payload["tenant_id"],
            distributor_id=payload["distributor_id"],
            pool_id=payload["pool_id"],
            max_seats=payload["max_seats"],
            feature_flags=tuple(payload["feature_flags"]),
            not_before=_parse_ts(payload["not_before"], "not_before"),
            expiry=_parse_ts(payload["expiry"], "expiry"),
            grace_days=payload["grace_days"],
            issued_at=_parse_ts(issued_at, "issued_at") if issued_at is not None else None,
        )

    def feature_enabled(self, flag: str) -> bool:
        """Flag ausente = OFF (fail-closed, edge case de la spec)."""
        return flag in self.feature_flags


def split_signed_document(blob) -> Tuple[dict, bytes]:
    """Separa el ``.lic`` en (payload, firma). Cualquier defecto estructural →
    LicenseMalformedError (nunca se distingue "corrupto" de "ausente" hacia
    afuera: ambos terminan fail-closed, FR-006)."""
    if isinstance(blob, bytes):
        try:
            blob = blob.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LicenseMalformedError("licencia: el token no es UTF-8") from exc
    if not isinstance(blob, str) or not blob.strip():
        raise LicenseMalformedError("licencia: token vacío")
    try:
        document = json.loads(blob)
    except json.JSONDecodeError as exc:
        raise LicenseMalformedError("licencia: el token no es JSON") from exc
    if not isinstance(document, dict):
        raise LicenseMalformedError("licencia: el token debe ser un objeto JSON")
    payload = dict(document)
    sig_b64 = payload.pop(WIRE_SIG_FIELD, None)
    if not isinstance(sig_b64, str) or not sig_b64:
        raise LicenseMalformedError("licencia: falta la firma 'sig'")
    try:
        signature = base64.urlsafe_b64decode(sig_b64)
    except (ValueError, TypeError) as exc:
        raise LicenseMalformedError("licencia: firma 'sig' no es base64url") from exc
    return payload, signature
