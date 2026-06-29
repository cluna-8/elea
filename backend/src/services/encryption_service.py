import os
import logging

logger = logging.getLogger("basa-secure-gateway.encryption")

_key = os.getenv("FERNET_SECRET_KEY", "").strip()
_fernet = None

if _key:
    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(_key.encode())
    except Exception as e:
        logger.warning("Fernet init failed, service_api_key_encrypted will be unavailable: %s", e)


def encrypt(value: str) -> str | None:
    if not _fernet or not value:
        return None
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str | None:
    if not _fernet or not value:
        return None
    try:
        return _fernet.decrypt(value.encode()).decode()
    except Exception:
        logger.warning("Failed to decrypt service API key")
        return None
