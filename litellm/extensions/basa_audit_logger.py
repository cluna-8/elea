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
import sys
from datetime import datetime, timezone

from litellm.integrations.custom_logger import CustomLogger

sys.path.insert(0, os.path.dirname(__file__))
import basa_guardian_policy as policy  # noqa: E402

# Atribución por pedido (spec 027 T029): las DOS columnas nuevas entran acá con el MISMO
# esquema que el productor del gateway. El comentario "MISMO esquema que basa_audit_logger"
# de gateway.py dejó de ser convención y es contrato (evento-monitor-atribucion §8):
# extender un productor sin el otro rompe el render uniforme de la vitrina. Hoy este plano
# las escribe SIEMPRE en NULL — ver `_attribution_del_motor`.
_INSERT_AUDIT_SQL = """
INSERT INTO audit_logs (
    id, tenant_id, timestamp, user_id, api_key_id, model,
    prompt_tokens, completion_tokens, cost_usd, pii_detected, masked_entities,
    compliance_status, latency_ms, user_group_id, applied_layers, blocked_by_layer
) VALUES (
    gen_random_uuid(), $1::uuid, NOW(), $2::uuid, $3::uuid, $4,
    $5, $6, $7, $8, $9::jsonb, $10, $11, $12::uuid, $13::jsonb, $14
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


def _attribution_del_motor():
    """Atribución del pedido en el plano motor: hoy **no la hay** ⇒ ``(None, None)``.

    ``None`` **no** es lista vacía: significa *"este pedido no trae atribución"*, mientras
    que ``[]`` afirmaría "ninguna capa corrió", que sería mentira (el piso corre siempre).
    Por eso las dos columnas quedan SQL NULL y el evento del monitor lleva ``null``: la
    vitrina muestra "sin registro de capas", que es la verdad.

    **Por qué no se lee del metadata-home** (hallazgo A3 de la verificación adversarial de
    la US2, ALTA — atribución falsificable): hasta este fix, la atribución se leía de
    ``metadata['basa_governance']``. Ese home es la fusión de ``litellm_metadata`` y
    ``metadata`` (ver ``_log``), y ``metadata`` es un campo del **body**, o sea un canal que
    escribe el CLIENTE —y que además ganaba el merge—. El saneo que había validaba
    *vocabulario*, no *procedencia*: un cliente con virtual key mandando
    ``{"metadata": {"basa_governance": {"applied_layers": [{"layer_code": "pii_masking",
    "status": "applied", "decision": "mask", "count": 4}]}}}`` conseguía que su pedido
    quedara auditado como si el enmascarado hubiera corrido. Falsificar el registro de
    cumplimiento es exactamente la mentira que la 027 existe para borrar, así que el plano
    motor prefiere **no registrar** antes que registrar algo que no produjo —el mismo
    criterio con el que la spec corta la fila durable del bloqueo hacia la 018
    (data-model §3.4)—.

    **Estado del cableado (2026-07-22)**: el productor propio es **T025**
    (``basa_guardrail.py``), bloqueada por el PR #21, que reescribe el guardrail entero.
    Requisitos para cuando aterrice, para no reabrir A3:

    - La atribución tiene que llegar por un canal que el cliente **no pueda escribir**.
      Verificado en la imagen del motor (``litellm/proxy/litellm_pre_call_utils.py:1580``):
      el proxy **sobrescribe** ``metadata['user_api_key_metadata']`` con la metadata del
      objeto de auth, así que ESE subárbol no es escribible desde el body — pero tampoco
      sirve acá: es la identidad, y ``custom_auth`` la cachea 60 s por ``key_hash``, con lo
      que la atribución de un pedido se filtraría a los siguientes de la misma Connection.
    - Si igual tiene que viajar por metadata, el productor debe **sobreescribir la clave en
      cada pedido**, también cuando no haya nada que reportar. Ojo con los caminos donde el
      guardrail no corre (la API de Responses, issue #28): ahí un valor sembrado por el
      cliente sobreviviría igual. Un canal en proceso, correlacionado por pedido, no tiene
      ese problema.
    - El lector debe volver a sanear por vocabulario cerrado (4 claves de data-model §3.1,
      ``status``/``decision`` de los enums del registry, ``count`` entero y no ``bool``):
      la procedencia confiable evita la falsificación, el saneo evita la fuga de texto al
      JSONB (C1). Son dos defensas distintas y hacen falta las dos.
    """
    return None, None


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
        # La identidad Basa viaja en el UserAPIKeyAuth.metadata (custom_auth) que el
        # proxy propaga como user_api_key_metadata dentro del metadata-home del request
        # — `litellm_metadata` en la ruta anthropic, `metadata` en el resto (024 D3;
        # antes se leía un solo home y los eventos byok bridged salían anónimos).
        basa = policy.proxy_identity_from(data) or policy.proxy_identity_from(kwargs)

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
        applied_layers, blocked_by_layer = _attribution_del_motor()

        # Registro DURABLE, best-effort (nunca voltea la respuesta; el publish a Redis va
        # después pase lo que pase). El audit_logs canónico vive en la base del BACKEND:
        # desde la separación de bases (motor → basa_engine) el INSERT por prisma fallaba
        # en cada pedido byok con "relation audit_logs does not exist", tragado como
        # no-fatal — o sea, el tráfico de HERRAMIENTAS no dejaba rastro durable. Fix
        # 2026-07-27: el motor emite la fila al plano interno del backend (dueño del
        # esquema), mismo patrón y mismo secreto que la resolución de identidad. Sin la
        # env (desarrollo, base compartida) se conserva el INSERT directo por prisma.
        entry = {
            "tenant_id": basa.get("tenant_id") or "00000000-0000-0000-0000-000000000001",
            "user_id": basa.get("client_id"),
            "api_key_id": basa.get("key_id"),
            "model": kwargs.get("model") or data.get("model") or "desconocido",
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "cost_usd": float(cost),
            "pii_detected": bool(masked),
            "masked_entities": masked,
            "compliance_status": compliance,
            "latency_ms": latency_ms,
            "user_group_id": basa.get("group_id"),
            # None (no "null"): SQL NULL = "pedido sin atribución", que es exactamente lo
            # que hoy produce el motor mientras T025 no cablee un productor propio.
            "applied_layers": applied_layers,
            "blocked_by_layer": blocked_by_layer,
        }
        audit_url = os.environ.get("BASA_AUDIT_URL", "").strip()
        if audit_url:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.post(audit_url, json=entry,
                                          headers={"X-Basa-Internal":
                                                   os.environ.get("LITELLM_MASTER_KEY", "")})
                if r.status_code != 200:
                    print(f"[basa-audit] plano interno respondió {r.status_code} (no fatal)")
            except Exception as exc:
                print(f"[basa-audit] POST no fatal (sigue el feed en vivo): {exc}")
        else:
            try:
                await prisma_client.db.query_raw(
                    _INSERT_AUDIT_SQL,
                    entry["tenant_id"], entry["user_id"], entry["api_key_id"],
                    entry["model"], entry["prompt_tokens"], entry["completion_tokens"],
                    entry["cost_usd"], entry["pii_detected"], json.dumps(masked),
                    entry["compliance_status"], entry["latency_ms"], entry["user_group_id"],
                    json.dumps(applied_layers) if applied_layers is not None else None,
                    blocked_by_layer,
                )
            except Exception as exc:
                print(f"[basa-audit] INSERT no fatal (sigue el feed en vivo): {exc}")

        await self._publish_monitor_event(basa, masked, compliance, kwargs,
                                          applied_layers, blocked_by_layer)

    async def _publish_monitor_event(self, basa, masked, compliance, kwargs,
                                     applied_layers=None, blocked_by_layer=None):
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
                # Contrato evento-monitor-atribucion §8: los campos nuevos viajan con el
                # MISMO shape que en la columna y que en el evento del gateway, serializados
                # sin transformar. `null` cuando el pedido no trae atribución — la vitrina
                # muestra "sin atribución", que es la verdad, en vez de una lista vacía que
                # afirmaría "ninguna capa corrió".
                "applied_layers": applied_layers,
                "blocked_by_layer": blocked_by_layer,
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
