import os
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status, Header
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.tenant import DEFAULT_TENANT_ID

logger = logging.getLogger("basa-secure-gateway.session")

# Dedicated JWT secret — MUST be set in the environment (JWT_SECRET_KEY). We never fall back
# to a hard-coded/predictable key (security: fail-closed). We also never reuse the Fernet
# key, so a compromise of one secret does not imply a compromise of the other.
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24


def _ensure_secret() -> str:
    """Fail-closed: refuse to issue/decode JWTs without a dedicated secret in prod."""
    if not SECRET_KEY or len(SECRET_KEY) < 32:
        raise RuntimeError(
            "JWT_SECRET_KEY is missing or too short (>=32 chars required). "
            "Set it in the environment (.env) — do NOT reuse FERNET_SECRET_KEY."
        )
    return SECRET_KEY


def create_session_token(user_id: str, role: str, username: str, tenant_id: str) -> str:
    """Issues a session JWT. ``tenant_id`` is REQUIRED (T005/FR-011): every session carries
    its tenant so downstream (SSO issuance, per-request GUC) never has to guess. No silent
    default at issuance — the caller supplies the authenticated user's tenant."""
    payload = {
        "sub": user_id,
        "role": role,
        "username": username,
        "tenant": str(tenant_id),
        "exp": datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, _ensure_secret(), algorithm=ALGORITHM)


def decode_session_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, _ensure_secret(), algorithms=[ALGORITHM])
    except JWTError:
        return None
    except RuntimeError:
        # No JWT secret configured — cannot validate any token.
        return None


def session_tenant(payload: dict) -> str:
    """Tenant of a decoded session payload. Tolerates pre-T005 tokens (issued without the
    ``tenant`` claim) for the ≤24 h it takes them to expire: falls back to the default tenant
    and LOGS the fallback so it is never silent. After the transitional window every live
    token carries the claim and this never fires."""
    tenant = payload.get("tenant")
    if tenant:
        return tenant
    logger.info(
        "session token without 'tenant' claim — defaulting to %s (pre-T005 token, "
        "≤24h transitional)",
        DEFAULT_TENANT_ID,
    )
    return str(DEFAULT_TENANT_ID)


def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Resolves the current user from a session JWT Bearer token.
    Returns None if no valid session token is present (not a 401 —
    callers decide whether auth is required).
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()

    # Check if this is a virtual key (sha256 hash matches an APIKey)
    # Virtual keys don't carry a user session — skip
    from ..models.budget import APIKey
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    if db.query(APIKey).filter(APIKey.key_hash == key_hash).first():
        return None

    payload = decode_session_token(token)
    if not payload:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id, User.is_active == True).first()
