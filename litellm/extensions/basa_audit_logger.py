"""BasaAuditLogger — auditoría metadata-only desde el motor (spec 014 US3).

``CustomLogger.async_log_success_event`` (firma confirmada, research T005) persiste
un ``AuditLog`` (tabla de la 013, misma DB) por request del motor: verdicto, tipos de
entidad enmascarada, tokens, costo, latencia, identidad tenant/client/tool.

**Scrub explícito (Constraint C1 / FR-015)**: JAMÁS se persiste texto de prompt ni el
mapa ``pii_tokens`` — se eliminan del payload antes de armar el INSERT, y el INSERT
solo lleva columnas de metadata. Test negativo en la suite.

Feed del monitor (FR-016/FR-017): eventos efímeros (metadata + previews acotados ya
ENMASCARADOS) publicados a una lista Redis con TTL corto — el backend los sirve en
``/gw/monitor``. Nada del feed contiene PII cruda.
"""
import json
import os
from datetime import datetime, timezone

from litellm.integrations.custom_logger import CustomLogger

_INSERT_AUDIT_SQL = """
INSERT INTO audit_logs (
    id, tenant_id, timestamp, user_id, api_key_id, model,
    prompt_tokens, completion_tokens, cost_usd, pii_detected, masked_entities,
    compliance_status, latency_ms, user_group_id
) VALUES (
    gen_random_uuid(), $1::uuid, NOW(), $2::uuid, $3::uuid, $4,
    $5, $6, $7, $8, $9::jsonb, $10, $11, $12::uuid
)
"""

_MONITOR_KEY = "basa:gw:events"
_MONITOR_CAP = 100
_MONITOR_TTL_S = 300  # efímero: la vitrina no persiste nada (C1)
_DISPLAY_CAP = 2000


def _scrub(metadata: dict) -> dict:
    """Devuelve metadata sin material sensible: pii_tokens (mapa reversible) y
    cualquier texto crudo NUNCA se auditan."""
    clean = dict(metadata or {})
    clean.pop("pii_tokens", None)
    return clean


class BasaAuditLogger(CustomLogger):
    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        try:
            await self._log(kwargs, response_obj, start_time, end_time)
        except Exception as exc:  # la auditoría no debe voltear la respuesta al cliente
            print(f"[basa-audit] fallo al auditar (no fatal): {exc}")

    async def _log(self, kwargs, response_obj, start_time, end_time):
        from litellm.proxy.proxy_server import prisma_client
        if prisma_client is None:
            return

        data = kwargs.get("litellm_params", {}) or {}
        proxy_md = (data.get("metadata") or {})
        # La identidad Basa viaja en el UserAPIKeyAuth.metadata (custom_auth) que el
        # proxy propaga como user_api_key_metadata dentro del metadata del request.
        basa = (proxy_md.get("user_api_key_metadata") or {}).get("basa") or {}

        request_md = {}
        for key in ("litellm_metadata", "metadata"):
            home = kwargs.get(key) or data.get(key)
            if isinstance(home, dict):
                request_md.update(home)
        request_md = _scrub(request_md)

        usage = getattr(response_obj, "usage", None)
        prompt_tokens = completion_tokens = 0
        if usage is not None:
            get = usage.get if isinstance(usage, dict) else (lambda k, d=None: getattr(usage, k, d))
            prompt_tokens = get("prompt_tokens") or get("input_tokens") or 0
            completion_tokens = get("completion_tokens") or get("output_tokens") or 0

        cost = kwargs.get("response_cost") or 0
        try:
            latency_ms = int((end_time - start_time).total_seconds() * 1000)
        except Exception:
            latency_ms = 0

        masked = request_md.get("basa_masked_entities") or []
        compliance = (request_md.get("basa_compliance") or {}).get("status") or "passed"

        await prisma_client.db.query_raw(
            _INSERT_AUDIT_SQL,
            basa.get("tenant_id") or "00000000-0000-0000-0000-000000000001",
            basa.get("client_id"),
            basa.get("key_id"),
            kwargs.get("model") or data.get("model") or "desconocido",
            int(prompt_tokens or 0),
            int(completion_tokens or 0),
            float(cost),
            bool(masked),
            json.dumps(masked),
            compliance,
            latency_ms,
            basa.get("group_id"),
        )

        await self._publish_monitor_event(basa, masked, compliance, kwargs)

    async def _publish_monitor_event(self, basa, masked, compliance, kwargs):
        """Feed efímero del monitor (vitrina, Principio VIII): metadata + preview
        ENMASCARADO (el texto que vio el upstream — nunca los valores originales)."""
        try:
            import redis.asyncio as redis_lib
        except ImportError:
            return
        try:
            client = redis_lib.Redis(host=os.getenv("REDIS_HOST", "redis"),
                                     port=int(os.getenv("REDIS_PORT", "6379")))
            messages = (kwargs.get("messages") or
                        (kwargs.get("litellm_params", {}) or {}).get("messages") or [])
            preview = ""
            for msg in reversed(messages):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    content = msg.get("content")
                    if isinstance(content, str):
                        preview = content[:_DISPLAY_CAP]
                    elif isinstance(content, list):
                        preview = " ".join(
                            b.get("text", "") for b in content
                            if isinstance(b, dict) and isinstance(b.get("text"), str)
                        )[:_DISPLAY_CAP]
                    break
            event = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "tool": basa.get("tool_type") or basa.get("ua_tool"),
                "client": basa.get("client_username"),
                "tenant": basa.get("tenant_slug"),
                "model": kwargs.get("model"),
                "compliance_status": compliance,
                "masked_entities": masked,
                "masked_preview": preview,  # ya enmascarado: es lo que vio el upstream
            }
            pipe = client.pipeline()
            pipe.lpush(_MONITOR_KEY, json.dumps(event, ensure_ascii=False))
            pipe.ltrim(_MONITOR_KEY, 0, _MONITOR_CAP - 1)
            pipe.expire(_MONITOR_KEY, _MONITOR_TTL_S)
            await pipe.execute()
            await client.aclose()
        except Exception:
            pass  # el monitor es vitrina: jamás afecta la request
basa_audit_logger_instance = BasaAuditLogger()
