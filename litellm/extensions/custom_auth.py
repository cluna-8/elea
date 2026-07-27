"""custom_auth — identidad Basa para el motor (spec 014 US2, FR-009..FR-013).

Resuelve la identidad de cada request contra la ``APIKey`` (=Connection) de la 013:
``sha256(virtual key) → key_hash → tenant/client/group/tool + toggles``, e inyecta esa
identidad en el ``UserAPIKeyAuth`` que después reciben los hooks del guardrail.

**Fail-closed (Constraint C3)**: sin key válida NO hay request — jamás se cae a un
usuario admin por defecto (ese agujero era del demo). La única excepción es la master
key del motor (ops/admin del proxy).

**De dónde sale la identidad** (corregido 2026-07-27, víspera del install de la Cámara):
originalmente esto reusaba el prisma client del propio motor, porque motor y backend
compartían una sola base. Ya no: el motor tiene base PROPIA (``basa_engine``) desde que
su migrador Prisma dropeaba las tablas del producto como "drift" (ensayo 2026-07-22), y
las tablas de identidad —``api_keys``, ``users``, ``groups``, ``tenants``— viven en la
del backend. Consecuencia observada en el perfil de producción: **todo byok daba 401**
con ``relation "api_keys" does not exist``, porque el prisma del motor consulta
``basa_engine``. Nadie lo detectó antes porque el ensayo nunca ejercitó byok (0 keys
registradas).

Ahora la identidad se lee con una conexión PROPIA de sólo lectura a la base del backend
(``BASA_IDENTITY_DATABASE_URL``). Si esa variable no está, se cae al prisma del motor:
es el caso de desarrollo, donde ambos planos comparten base y la consulta funciona.
El SQL es el mismo en los dos caminos.

Registro (gotcha de la research T005: el módulo se resuelve RELATIVO al directorio
del config.yaml, no por sys.path):

    general_settings:
      custom_auth: extensions.custom_auth.user_api_key_auth
"""
import hashlib
import json
import os
import time
from typing import Optional

from fastapi import Request
from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth

# Mapa UA→tool portado 1:1 del demo (_TOOL_UA): primer match gana; el ORDEN es
# semántica observable (claude antes que curl, curl antes que httpx).
TOOL_UA = [
    ("claude", "Claude Code"),
    ("cursor", "Cursor"),
    ("continue", "Continue.dev"),
    ("aider", "aider"),
    ("cline", "Cline"),
    ("roo", "Roo Code"),
    ("codex", "Codex CLI"),
    ("gemini", "Gemini CLI"),
    ("windsurf", "Windsurf"),
    ("postman", "Postman"),
    ("curl", "curl"),
    ("httpx", "API directa"),
    ("python-requests", "API directa"),
    ("node-fetch", "API directa"),
]

_IDENTITY_SQL = """
SELECT k.id::text AS key_id, k.tenant_id::text AS tenant_id, k.user_id::text AS user_id,
       k.group_id::text AS group_id, k.tool_type, k.upstream_mode, k.redact_enabled,
       k.compression_mode AS key_compression_mode, k.allowed_models, k.allowed_tools,
       k.rpm_limit, k.tpm_limit, k.is_active, k.expires_at::text AS expires_at,
       u.username, u.role, u.client_type, u.display_label,
       g.compression_mode AS group_compression_mode,
       t.slug AS tenant_slug, t.compression_mode AS tenant_compression_mode,
       -- spec 016: entity_configs (MASK/BLOCK por tipo) + deny-list de nombres
       -- personalizados, para que el guardrail deje de ignorarlos (política global
       -- por tenant; la cascada fina por client/group es spec 015).
       (SELECT sp.entity_configs FROM security_policies sp
         WHERE sp.tenant_id = k.tenant_id AND sp.is_active = true LIMIT 1) AS entity_configs,
       (SELECT gd.config->'custom_names' FROM guardians gd
         WHERE gd.tenant_id = k.tenant_id AND gd.guardian_type = 'pii_masking'
           AND gd.is_active = true LIMIT 1) AS custom_names,
       -- Catálogo de entidades custom (regex + contexto agregados vía panel/IA,
       -- ver backend/src/services/entity_catalog_service.py) — mismo Guardian.
       (SELECT gd.config->'custom_entities' FROM guardians gd
         WHERE gd.tenant_id = k.tenant_id AND gd.guardian_type = 'pii_masking'
           AND gd.is_active = true LIMIT 1) AS custom_entities
FROM api_keys k
LEFT JOIN users u ON u.id = k.user_id
LEFT JOIN groups g ON g.id = k.group_id
LEFT JOIN tenants t ON t.id = k.tenant_id
WHERE k.key_hash = $1
"""

# Cache TTL corto por key_hash: una resolución de identidad por minuto por key.
_CACHE_TTL_S = 60
_cache: dict = {}


def detect_tool(user_agent: Optional[str]) -> str:
    low = (user_agent or "").lower()
    for needle, name in TOOL_UA:
        if needle in low:
            return name
    return "Desconocido"


def _maybe_json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def _first_not_none(*values):
    for v in values:
        if v is not None:
            return v
    return None


_IDENTITY_URL = os.environ.get("BASA_IDENTITY_URL", "").strip()
_INTERNAL_SECRET = os.environ.get("LITELLM_MASTER_KEY", "")


async def _lookup_identity(key_hash: str) -> Optional[dict]:
    now = time.monotonic()
    hit = _cache.get(key_hash)
    if hit and now - hit[0] < _CACHE_TTL_S:
        return hit[1]

    if _IDENTITY_URL:
        import httpx
        # timeout corto y sin retry: esto está en el camino de auth de cada request.
        # Cualquier fallo levanta → 401 (fail-closed), nunca un usuario por defecto.
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(_IDENTITY_URL, params={"key_hash": key_hash},
                                 headers={"X-Basa-Internal": _INTERNAL_SECRET})
        if r.status_code != 200:
            raise Exception(
                "Basa Gateway: no se pudo resolver la identidad de la Connection "
                f"(plano interno respondió {r.status_code}) — fail-closed.")
        # `row: null` es una respuesta legítima ("no existe esa key"): se cachea como
        # None y el caller lo traduce a 401. Distinto de no haber podido preguntar.
        row = r.json().get("row")
    else:
        # Desarrollo: motor y backend comparten base, el prisma del motor alcanza.
        # Import perezoso: el prisma client existe recién cuando el proxy terminó de bootear
        from litellm.proxy.proxy_server import prisma_client
        if prisma_client is None:
            raise Exception("Basa Gateway: la base de identidad no está disponible (fail-closed).")
        rows = await prisma_client.db.query_raw(_IDENTITY_SQL, key_hash)
        row = rows[0] if rows else None

    _cache[key_hash] = (now, row)
    return row


async def user_api_key_auth(request: Request, api_key: str) -> UserAPIKeyAuth:
    """Firma confirmada contra litellm 1.92.0 (research T005). Excepción → 401."""
    # La key puede venir por Authorization (Bearer) o x-api-key (convención Anthropic)
    api_key = (api_key or "").strip() or (request.headers.get("x-api-key") or "").strip()
    ua_tool = detect_tool(request.headers.get("user-agent"))

    master_key = os.getenv("LITELLM_MASTER_KEY")
    if master_key and api_key == master_key:
        return UserAPIKeyAuth(
            api_key=api_key,
            user_role=LitellmUserRoles.PROXY_ADMIN,
            metadata={"basa": {"identity": "master", "ua_tool": ua_tool}},
        )

    if not api_key:
        raise Exception("Basa Gateway: falta la clave de acceso (fail-closed, sin key no hay request).")

    row = await _lookup_identity(hashlib.sha256(api_key.encode()).hexdigest())
    if row is None:
        raise Exception("Basa Gateway: clave de acceso desconocida.")
    if not row.get("is_active"):
        raise Exception("Basa Gateway: la Connection está revocada.")

    allowed_models = _maybe_json(row.get("allowed_models"))
    # Toggles con semántica NULL=heredar (FR-014); espejo de context_resolution del
    # backend (la centralización fina por policy es spec 015).
    redact_enabled = row.get("redact_enabled")
    basa_identity = {
        "identity": "connection",
        "key_id": row["key_id"],
        "tenant_id": row["tenant_id"],
        "tenant_slug": row.get("tenant_slug"),
        "client_id": row.get("user_id"),
        "client_username": row.get("username"),
        "client_type": row.get("client_type"),
        "group_id": row.get("group_id"),
        "tool_type": row.get("tool_type"),
        "ua_tool": ua_tool,
        "upstream_mode": row.get("upstream_mode"),
        "redact_enabled": redact_enabled if redact_enabled is not None else True,
        "compression_mode": _first_not_none(
            row.get("key_compression_mode"),
            row.get("group_compression_mode"),
            row.get("tenant_compression_mode"),
            "off",
        ),
        "allowed_tools": _maybe_json(row.get("allowed_tools")),
        # spec 016: detección/enforcement real por tipo de entidad (ver basa_guardrail.py)
        "entity_configs": _maybe_json(row.get("entity_configs")) or {},
        "custom_names": _maybe_json(row.get("custom_names")) or [],
        "custom_entities": _maybe_json(row.get("custom_entities")) or [],
    }

    return UserAPIKeyAuth(
        api_key=api_key,
        user_id=row.get("user_id"),
        team_id=row.get("group_id"),
        key_alias=f"basa:{row.get('tool_type')}:{row.get('username') or 'sin-user'}",
        # rpm/tpm y allowlist de modelos: delegados al motor como backstop (Principio VI)
        rpm_limit=row.get("rpm_limit"),
        tpm_limit=row.get("tpm_limit"),
        models=allowed_models if isinstance(allowed_models, list) else [],
        metadata={"basa": basa_identity},
    )
