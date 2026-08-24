"""Deployment key (spec 021 US5, T041 — FR-029).

Par Ed25519 PROPIO de cada deployment: se genera en el install (primer uso),
la privada vive en volumen/secret (``BASA_DEPLOYMENT_KEY_FILE``) y JAMÁS en el
repo ni en config en claro; la pública se registra en el onboarding (lado
Basa). Firma SOLO evidencia (true-up export) — nunca licencias (la clave de
firma de licencias es de Basa y no toca la caja, Constraint C5).
"""
import logging
import stat
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .env import env_or_default

logger = logging.getLogger(__name__)

DEPLOYMENT_KEY_ENV = "BASA_DEPLOYMENT_KEY_FILE"
DEFAULT_KEY_PATH = "/app/config/licenses/deployment_key.pem"


class DeploymentKeyError(Exception):
    pass


def key_path() -> Path:
    return Path(env_or_default(DEPLOYMENT_KEY_ENV, DEFAULT_KEY_PATH))


def ensure_deployment_key() -> Ed25519PrivateKey:
    """Carga la privada del deployment; la GENERA si no existe (install-time).
    PEM sin passphrase en un path de volumen/secret, permisos 0600."""
    path = key_path()
    if path.exists():
        try:
            key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        except (ValueError, OSError) as exc:
            raise DeploymentKeyError(f"deployment key ilegible en {path}: {exc}") from exc
        if not isinstance(key, Ed25519PrivateKey):
            raise DeploymentKeyError(f"deployment key en {path} no es Ed25519")
        return key
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.write_bytes(pem)
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600: sólo el proceso del backend
    logger.info("deployment key generada en %s (registrá la pública en el onboarding)", path)
    return key


def public_key_pem() -> str:
    """PEM de la pública — lo que el onboarding registra del lado de Basa."""
    return ensure_deployment_key().public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


def sign(data: bytes) -> bytes:
    return ensure_deployment_key().sign(data)
