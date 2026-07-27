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
import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
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


# ── Auditoría durable del plano MOTOR ────────────────────────────────────────────────
# Mismo motivo que /identity: `audit_logs` (el registro canónico) vive en ESTA base, y
# desde la separación de bases el INSERT del motor fallaba en cada pedido byok con
# "relation audit_logs does not exist" — tragado como no-fatal. Resultado: el tráfico de
# HERRAMIENTAS (la superficie principal del producto) no dejaba rastro durable, sólo la
# vitrina efímera de Redis. Para un producto cuya promesa es "interceptar y REGISTRAR
# todo", ese era el gap más caro del core.

_INSERT_AUDIT_SQL = text("""
INSERT INTO audit_logs (
    id, tenant_id, timestamp, user_id, api_key_id, model,
    prompt_tokens, completion_tokens, cost_usd, pii_detected, masked_entities,
    compliance_status, latency_ms, user_group_id, applied_layers, blocked_by_layer
) VALUES (
    gen_random_uuid(), CAST(:tenant_id AS uuid), NOW(), CAST(:user_id AS uuid),
    CAST(:api_key_id AS uuid), :model,
    :prompt_tokens, :completion_tokens, :cost_usd, :pii_detected,
    CAST(:masked_entities AS jsonb),
    :compliance_status, :latency_ms, CAST(:user_group_id AS uuid),
    CAST(:applied_layers AS jsonb), :blocked_by_layer
)
""")


class AuditEntry(BaseModel):
    """Fila de auditoría que emite el motor. El emisor está autenticado con el secreto
    compartido (misma confianza que cuando insertaba directo en la base), pero el saneo
    por vocabulario se mantiene igual (hallazgo A3 de la 027): la procedencia confiable
    evita la falsificación; el saneo evita que texto libre termine en el JSONB (C1).
    Son dos defensas distintas y hacen falta las dos."""
    tenant_id: str
    user_id: Optional[str] = None
    api_key_id: Optional[str] = None
    model: str = "desconocido"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    pii_detected: bool = False
    masked_entities: list = []
    compliance_status: str = "passed"
    latency_ms: int = 0
    user_group_id: Optional[str] = None
    applied_layers: Optional[list] = None
    blocked_by_layer: Optional[str] = None


def _entidades_saneadas(items: list) -> list:
    """Vocabulario cerrado: sólo {type, count}, con type acotado y count entero. Todo lo
    demás se descarta — jamás texto del pedido en el registro durable."""
    limpias = []
    for it in items[:50]:
        if not isinstance(it, dict):
            continue
        tipo, cuenta = it.get("type"), it.get("count")
        if isinstance(tipo, str) and 0 < len(tipo) <= 64 and isinstance(cuenta, int):
            limpias.append({"type": tipo, "count": cuenta})
    return limpias


@router.post("/audit", dependencies=[Depends(_require_internal_secret)])
def record_audit(entry: AuditEntry, db: Session = Depends(get_db)):
    entidades = _entidades_saneadas(entry.masked_entities)
    db.execute(_INSERT_AUDIT_SQL, {
        "tenant_id": entry.tenant_id,
        "user_id": entry.user_id,
        "api_key_id": entry.api_key_id,
        "model": entry.model[:128],
        "prompt_tokens": entry.prompt_tokens,
        "completion_tokens": entry.completion_tokens,
        "cost_usd": entry.cost_usd,
        "pii_detected": entry.pii_detected,
        "masked_entities": json.dumps(entidades),
        "compliance_status": entry.compliance_status[:64],
        "latency_ms": entry.latency_ms,
        "user_group_id": entry.user_group_id,
        # None ⇒ SQL NULL, no JSON null: NULL significa "pedido sin atribución" (el motor
        # hoy no la produce — T025); [] afirmaría "ninguna capa corrió", que sería mentira.
        "applied_layers": json.dumps(entry.applied_layers) if entry.applied_layers is not None else None,
        "blocked_by_layer": entry.blocked_by_layer[:64] if entry.blocked_by_layer else None,
    })
    db.commit()
    return {"ok": True}
