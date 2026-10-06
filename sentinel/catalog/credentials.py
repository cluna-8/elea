"""Almacén de credenciales del catálogo (069 T026; FR-005, FR-005a; research D3).

Un solo almacén cifrado para todos los modelos: la credencial es un dict con la forma de su
proveedor (`redirect.credentials.SHAPES`), guardado como JSON cifrado con `encryption_service`
(MultiFernet, rotable). Reutilizable entre entradas. **Solo escritura**: ninguna función de este
módulo devuelve el valor al exterior; las vistas llevan solo la huella.

Lo que sí puede salir de aquí hacia el plano de datos es el dict descifrado (`resolve`), y solo para
el guard/pasarela, nunca para una respuesta HTTP.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping, Optional

from sentinel.redirect import credentials as rc

from . import models as cm


class CredentialInUse(Exception):
    """Revocar una credencial que usan entradas activas, sin reemplazo ni desactivación (FR-005a)."""

    def __init__(self, entries: list[str]):
        super().__init__("credencial en uso por: " + ", ".join(entries))
        self.entries = entries


def to_dict(value: Any) -> dict:
    """`value` de la API → dict de credencial: una cadena es la `api_key`; un objeto se respeta."""
    if isinstance(value, str):
        return {"api_key": value}
    if isinstance(value, Mapping):
        return dict(value)
    raise rc.CredentialError("la credencial debe ser una cadena o un objeto con los campos del proveedor")


def fingerprint(cred: Mapping[str, Any]) -> str:
    """Últimos 4 del hash de la credencial: identifica cuál es sin revelarla (registro de cambios)."""
    canon = json.dumps(dict(cred), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()[-4:]


# La lista negra de variables y el formato admitido viven en UN solo lugar (la usa también el guard
# del motor al resolver `env:`): `sentinel/engine/redirect_credentials.py`.
ENV_DENYLIST = rc.ENV_DENYLIST
ENV_DENY_FRAGMENTS = rc.ENV_DENY_FRAGMENTS


def _check_any_env(env_name: str) -> None:
    if not rc.env_name_allowed(env_name):
        raise rc.CredentialError("variable de entorno no permitida como credencial")


def env_ref_dict(env_name: str, *, allow_any_env: bool = False) -> dict:
    """Una referencia a variable del servidor equivale a `{"api_key": "env:<NOMBRE>"}`.

    Regla general: el nombre empieza con `REDIRECT_CRED_` (la valida el motor). `allow_any_env` es
    SOLO de la adopción de modelos del `config.yaml` (`api/legacy.py`): admite cualquier nombre
    salvo la lista negra `ENV_DENYLIST` y los que contienen `ENV_DENY_FRAGMENTS`.
    """
    if allow_any_env:
        _check_any_env(env_name)
        return {"api_key": rc.ENV_PREFIX + env_name}
    ref = rc.ENV_PREFIX + env_name
    rc.validate_credential("openai_compatible", {"api_key": ref}, level="installation")  # valida el nombre
    return {"api_key": ref}


def create(db, *, level: str, tenant_id, name: str, kind: str, value: Any = None,
           env_name: Optional[str] = None, user_id=None,
           encrypt: Callable[[str], str], allow_any_env: bool = False) -> cm.Credential:
    if kind == "env_ref":
        if level != "installation":
            raise rc.CredentialError("las referencias a variables del servidor son solo de instalación")
        cred = env_ref_dict(env_name or "", allow_any_env=allow_any_env)
        row = cm.Credential(level=level, tenant_id=tenant_id, name=name, kind="env_ref",
                            env_name=env_name, fingerprint=fingerprint(cred), created_by=user_id)
    else:
        cred = to_dict(value)
        if not cred:
            raise rc.CredentialError("credencial vacía")
        row = cm.Credential(level=level, tenant_id=tenant_id, name=name, kind="secret",
                            ciphertext=encrypt(json.dumps(cred, sort_keys=True)),
                            fingerprint=fingerprint(cred), created_by=user_id)
    db.add(row)
    db.flush()
    return row


def resolve(row: cm.Credential, decrypt: Callable[[str], str]) -> dict:
    """Dict de credencial listo para validar o enviar al plano de datos (NO para una respuesta)."""
    if row.kind == "env_ref":
        return env_ref_dict(row.env_name, allow_any_env=True)   # ya validada al crear; la lista negra se reaplica
    return json.loads(decrypt(row.ciphertext))


def validate_for(provider: str, cred: Mapping[str, Any], level: str) -> None:
    rc.validate_credential(provider, cred, level=level)


def replace(db, row: cm.Credential, value: Any, *, encrypt: Callable[[str], str]) -> dict:
    """Reemplaza el secreto. Devuelve `{before, after}` con solo huellas."""
    if row.kind != "secret":
        raise rc.CredentialError("una referencia a variable del servidor no se reemplaza: se revoca")
    cred = to_dict(value)
    before = fingerprint_of(row)
    row.ciphertext = encrypt(json.dumps(cred, sort_keys=True))
    row.fingerprint = fingerprint(cred)
    db.flush()
    return {"before": before, "after": fingerprint_of(row)}


def fingerprint_of(row: cm.Credential) -> dict:
    return {"name": row.name, "kind": row.kind, "fingerprint": row.fingerprint, "status": row.status}


def in_use_by(db, row: cm.Credential) -> list[cm.CatalogEntry]:
    return db.query(cm.CatalogEntry).filter(cm.CatalogEntry.credential_id == row.id,
                                            cm.CatalogEntry.status != "archived").all()


def revoke(db, row: cm.Credential, *, replacement: Optional[cm.Credential] = None,
           deactivate_entries: bool = False) -> list[cm.CatalogEntry]:
    """Revoca. En uso ⇒ exige reemplazo o desactivar (FR-005a); nunca deja entradas activas sin
    credencial en silencio. Devuelve las entradas tocadas."""
    uses = in_use_by(db, row)
    if uses and replacement is None and not deactivate_entries:
        raise CredentialInUse([e.name for e in uses])
    for e in uses:
        if replacement is not None:
            e.credential_id = replacement.id
        else:
            e.credential_id, e.status = None, "inactive"
    row.status, row.ciphertext = "revoked", None          # el secreto se destruye; la fila queda
    db.flush()
    return uses
