"""Plano interno: resolución de identidad de una Connection para el MOTOR.

Por qué existe (2026-07-27, víspera del install de la Cámara): `custom_auth` del motor
resolvía la identidad consultando `api_keys`/`users`/`groups`/`tenants` con el prisma
client del propio motor. Desde que el motor tiene base PROPIA (`basa_engine`, para que su
migrador Prisma no dropee las tablas del producto como "drift" — ensayo 2026-07-22) esas
tablas quedaron fuera de su alcance: **todo byok devolvía 401** con
`relation "api_keys" does not exist`. El ensayo no lo detectaba porque nunca ejercitó byok.

Por qué HTTP y no una segunda conexión SQL desde el motor: la imagen upstream del motor no
trae ningún driver de Postgres y tampoco trae `pip` ni `uv` (está construida con uv y sin
instalador), así que agregar `asyncpg` obligaba a derivar la imagen. HTTP no cuesta nada:
`httpx` ya viene en la imagen. Y además pone el SQL donde vive el esquema que consulta —
el backend es el dueño de estas tablas, el motor sólo necesita el resultado.

Seguridad: el ingress niega /api/v1/internal/* con 404 (Caddyfile.ingress), así que esto
sólo se alcanza por la red de compose. Encima se exige el secreto compartido que ambos
servicios YA tienen (`LITELLM_MASTER_KEY`) — no hay un secreto nuevo que provisionar.
"""
import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db

router = APIRouter(prefix="/internal", tags=["Internal"], include_in_schema=False)

# Mismo SQL que vivía en litellm/extensions/custom_auth.py (_IDENTITY_SQL). Se mueve acá
# porque consulta tablas de ESTA base: una sola copia, del lado del dueño del esquema.
_IDENTITY_SQL = text("""
SELECT k.id::text AS key_id, k.tenant_id::text AS tenant_id, k.user_id::text AS user_id,
       k.group_id::text AS group_id, k.tool_type, k.upstream_mode, k.redact_enabled,
       k.compression_mode AS key_compression_mode, k.allowed_models, k.allowed_tools,
       k.rpm_limit, k.tpm_limit, k.is_active, k.expires_at::text AS expires_at,
       u.username, u.role, u.client_type, u.display_label,
       g.compression_mode AS group_compression_mode,
       t.slug AS tenant_slug, t.compression_mode AS tenant_compression_mode,
       (SELECT sp.entity_configs FROM security_policies sp
         WHERE sp.tenant_id = k.tenant_id AND sp.is_active = true LIMIT 1) AS entity_configs,
       (SELECT gd.config->'custom_names' FROM guardians gd
         WHERE gd.tenant_id = k.tenant_id AND gd.guardian_type = 'pii_masking'
           AND gd.is_active = true LIMIT 1) AS custom_names,
       (SELECT gd.config->'custom_entities' FROM guardians gd
         WHERE gd.tenant_id = k.tenant_id AND gd.guardian_type = 'pii_masking'
           AND gd.is_active = true LIMIT 1) AS custom_entities
FROM api_keys k
LEFT JOIN users u ON u.id = k.user_id
LEFT JOIN groups g ON g.id = k.group_id
LEFT JOIN tenants t ON t.id = k.tenant_id
WHERE k.key_hash = :key_hash
""")


def _require_internal_secret(x_basa_internal: str = Header(default="")) -> None:
    """Fail-closed: si el secreto no está configurado en el backend, NADIE pasa. Un
    default vacío que aceptara la cabecera vacía convertiría esto en un endpoint abierto."""
    expected = os.environ.get("LITELLM_MASTER_KEY", "")
    if not expected or not hmac.compare_digest(x_basa_internal, expected):
        # Mismo 404 que emite el ingress: desde fuera, este endpoint no existe.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


@router.get("/identity", dependencies=[Depends(_require_internal_secret)])
def resolve_identity(key_hash: str = Query(min_length=64, max_length=64),
                     db: Session = Depends(get_db)):
    """Devuelve la fila de identidad de una Connection, o `null` si no existe.

    `null` (200) y no 404: para el motor "no hay tal key" es una respuesta legítima que
    debe traducirse a 401 del lado del cliente, distinta de "no pude preguntar" (que es
    fail-closed y sí es un error de transporte)."""
    row = db.execute(_IDENTITY_SQL, {"key_hash": key_hash}).mappings().first()
    return {"row": dict(row) if row is not None else None}
