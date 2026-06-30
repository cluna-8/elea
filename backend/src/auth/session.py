import os
import hashlib
from datetime import datetime, timedelta
from typing import Optional
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status, Header
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User

SECRET_KEY = os.getenv("FERNET_SECRET_KEY", "basa-jwt-secret-fallback-2025")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24


def create_session_token(user_id: str, role: str, username: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "username": username,
        "exp": datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_session_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


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
