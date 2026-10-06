"""Autorización interna pasarela→motor (research D14/D15).

Token `v1.<payload b64url>.<hmac b64url>`; HMAC-SHA256 con una llave derivada (HKDF) de
`REDIRECT_INTERNAL_KEY`. Liga: id de pedido, alcance, destino, modelo del motor
(`rdx-<familia>/<real>`), proveedor, base, enmascarado forzado y la decisión de ruteo
(metadata para auditoría S7). La credencial viaja cifrada con Fernet (segunda derivación de
la misma llave); una referencia `env:` viaja como referencia.

Vive en `sentinel/engine/` (se copia plano al motor por S9); la pasarela lo importa vía
`sentinel.redirect.authz`. Dependencias: stdlib + `cryptography` (ya presente en ambas imágenes).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

KEY_ENV = "REDIRECT_INTERNAL_KEY"
HEADER = "x-redirect-authz"
VERSION = "v1"
DEFAULT_TTL = 30
MAX_TTL = 120
CLOCK_SKEW = 5
MIN_KEY_LEN = 32


class AuthzError(Exception):
    code = "authz_invalid"
    public_message = "Destino no autorizado."

    def __init__(self, detail: str = ""):
        super().__init__(detail or self.code)
        self.detail = detail


class AuthzKeyMissing(AuthzError):
    code = "authz_key_missing"
    public_message = "Servicio no disponible temporalmente."


class AuthzMalformed(AuthzError):
    code = "authz_malformed"


class AuthzBadSignature(AuthzError):
    code = "authz_bad_signature"


class AuthzExpired(AuthzError):
    code = "authz_expired"


class AuthzModelMismatch(AuthzError):
    code = "authz_model_mismatch"


@dataclass(frozen=True)
class Grant:
    request_id: str
    scope: str
    destination_id: str
    model: str
    provider: str
    credential: dict = field(repr=False)
    api_base: Optional[str]
    forced_masking: bool
    decision: dict
    issued_at: float
    expires_at: float
    price: Optional[dict] = None    # {"input_per_mtok", "output_per_mtok"} del destino (D23 de la 069)
    # Parámetros del pedido que la ficha del destino declara «no soportados»: el guard los quita (069 enmienda)
    drop_params: tuple = ()


def _secret(key: Optional[str]) -> bytes:
    raw = key if key is not None else os.environ.get(KEY_ENV, "")
    if not raw or len(raw) < MIN_KEY_LEN:
        raise AuthzKeyMissing(f"{KEY_ENV} ausente o corta")
    return raw.encode()


def _derive(secret: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"redirect-authz", info=info).derive(secret)


def _keys(key: Optional[str]):
    s = _secret(key)
    return _derive(s, b"mac"), Fernet(base64.urlsafe_b64encode(_derive(s, b"enc")))


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue(*, request_id: str, scope: str, destination_id: str, model: str, provider: str,
          credential: Mapping[str, Any], api_base: Optional[str] = None, forced_masking: bool = False,
          decision: Optional[Mapping[str, Any]] = None, ttl: int = DEFAULT_TTL,
          key: Optional[str] = None, now: Optional[float] = None,
          price: Optional[Mapping[str, Any]] = None,
          drop_params: Optional[Any] = None) -> str:
    if not (0 < ttl <= MAX_TTL):
        raise ValueError(f"ttl fuera de rango (1..{MAX_TTL})")
    mac_key, fernet = _keys(key)
    now = time.time() if now is None else now
    payload = {
        "rid": request_id, "scope": scope, "dst": destination_id, "mdl": model, "prv": provider,
        "base": api_base, "fm": bool(forced_masking), "dec": dict(decision or {}),
        "cred": fernet.encrypt(json.dumps(dict(credential), sort_keys=True).encode()).decode(),
        "iat": int(now), "exp": int(now) + int(ttl),
    }
    if price:
        payload["prc"] = dict(price)
    if drop_params:
        payload["drp"] = [str(n) for n in drop_params]
    body = _b64e(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    signed = f"{VERSION}.{body}".encode()
    return f"{VERSION}.{body}.{_b64e(hmac.new(mac_key, signed, hashlib.sha256).digest())}"


def verify(token: Any, *, expected_model: Optional[str] = None, key: Optional[str] = None,
           now: Optional[float] = None) -> Grant:
    mac_key, fernet = _keys(key)
    if not isinstance(token, str) or token.count(".") != 2:
        raise AuthzMalformed("forma")
    version, body, mac = token.split(".")
    if version != VERSION:
        raise AuthzMalformed("versión")
    try:
        got = _b64d(mac)
    except Exception:
        raise AuthzMalformed("firma") from None
    want = hmac.new(mac_key, f"{version}.{body}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(got, want):
        raise AuthzBadSignature()
    try:
        p = json.loads(_b64d(body))
        cred = json.loads(fernet.decrypt(p["cred"].encode()))
        iat, exp = float(p["iat"]), float(p["exp"])
        grant = Grant(request_id=p["rid"], scope=p["scope"], destination_id=p["dst"], model=p["mdl"],
                      provider=p["prv"], credential=cred, api_base=p.get("base"),
                      forced_masking=bool(p["fm"]), decision=dict(p.get("dec") or {}),
                      issued_at=iat, expires_at=exp, price=p.get("prc") or None,
                      drop_params=tuple(str(n) for n in (p.get("drp") or ())))
    except (InvalidToken, KeyError, ValueError, TypeError, AttributeError):
        raise AuthzMalformed("contenido") from None
    now = time.time() if now is None else now
    if now > grant.expires_at + CLOCK_SKEW or now < grant.issued_at - CLOCK_SKEW:
        raise AuthzExpired()
    if expected_model is not None and not hmac.compare_digest(
            str(expected_model).encode(), grant.model.encode()):
        raise AuthzModelMismatch()
    return grant
