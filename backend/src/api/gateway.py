"""Gateway de PUERTA ÚNICA para coding tools (spec 014 US4 + spec 019 US1/US2).

Un solo endpoint (``/gw/v1/messages``) al que las coding tools apuntan su
``ANTHROPIC_BASE_URL``, con dos rutas según ``upstream_mode`` (013):

    subscription-passthrough │ Claude Code ──► [política Basa] ──► api.anthropic.com
    (014 US4)                │   OAuth del cliente verbatim; la suscripción paga
    ─────────────────────────┼──────────────────────────────────────────────────
    byok (019 US2)           │ Copilot/Cursor ──► [router fino] ──► motor LiteLLM
                             │   sk-basa-… verbatim; el MOTOR aplica la política

**Passthrough (014, excepción de proxy propio del Principio VI):** como LiteLLM
reclama ``Authorization`` como su propia virtual key, el OAuth de suscripción no
puede atravesar el motor; sólo acá el backend reverse-proxya a ``api.anthropic.com``
reenviando el OAuth **verbatim** y aplicando la política del gateway.

**byok (019):** el gateway es un **router fino** al motor — NO aplica política acá
(el motor ya corre ``custom_auth`` + ``BasaGuardrail``, 014 US1-3), evitando el
doble-masking del port literal del demo. Auto-detecta la ruta: una virtual key
``sk-basa-…`` en un header de auth (excl. ``x-basa-*``) o en la URL (``?k=…``,
fallback de Copilot) → byok; si no, passthrough. Selección explícita por
``X-Basa-Upstream``.

**Paridad por librería (FR-022):** el bloqueo y el masking/unmask reversible NO se
reimplementan acá — se invoca la **misma** ``basa_guardian_policy`` que usa
``BasaGuardrail`` en la ruta motor (mismos ``evaluate_ai_act`` / ``detect_secrets`` /
``mask_body`` / ``rewrite_sse_block``), así las dos rutas nunca divergen (contract
test de paridad: ``tests/contract/test_route_parity.py``).

**Identidad ([D-014]):** en esta ruta la credencial ES el OAuth de suscripción, así
que NO se aplica fail-closed (a diferencia de ``byok`` en el motor). ``X-Basa-Key`` es
atribución OPCIONAL: si viene y resuelve, la auditoría lleva tenant/client reales; si
falta, se audita contra el tenant por defecto (anónimo). El GDPR-routing es N/A acá
(excepción acotada del Principio II — base_url clients).

**Secreto OAuth (FR-025, Constraint C5):** el token nunca vive en ``config.yaml``. En
el caso normal lo pone el cliente (header, verbatim). En el caso gestionado por Basa,
la Connection referencia un secreto Fernet (``oauth_credential_ref``) que se descifra
en memoria; jamás en claro en disco.
"""
import codecs
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ..database import SessionLocal, tenant_context
from ..licensing.degraded import hard_block_reason
from ..models.budget import APIKey
from ..models.tenant import DEFAULT_TENANT_ID, Tenant
from ..services import encryption_service
from ..services.audit_service import AuditService
from ..services.key_material import hash_key
from ..services.redis_client import get_redis

# ── Librería PURA compartida (los dos hogares del plan 014: motor y backend) ──────
# En el container backend vive montada en /app/litellm_config/extensions; en local,
# relativa al repo. Se agrega su carpeta a sys.path (idempotente) y se importa igual
# que el guardrail del motor, para NO mantener dos copias de la política.
for _shared in ("/app/litellm_config/extensions",
                os.path.join(os.path.dirname(__file__), "..", "..", "..", "litellm", "extensions")):
    if os.path.isdir(_shared):
        _abs = os.path.abspath(_shared)
        if _abs not in sys.path:
            sys.path.insert(0, _abs)
        break
import basa_guardian_policy as policy  # noqa: E402

router = APIRouter(prefix="/gw", tags=["Firewall Gateway (passthrough OAuth)"])
logger = logging.getLogger("basa-secure-gateway.gateway")

_ANTHROPIC_UPSTREAM = os.getenv("BASA_GW_ANTHROPIC_BASE", "https://api.anthropic.com").rstrip("/")
# Motor LiteLLM (ruta byok): el gateway es la PUERTA ÚNICA (spec 019). En byok NO aplica
# política — sólo rutea al motor, que ya corre custom_auth + BasaGuardrail (014). Evita
# el doble-masking que tendría el port literal del demo (cuyo motor no tenía guardrail).
_LITELLM_UPSTREAM = os.getenv("LITELLM_API_BASE", "http://litellm:4000").rstrip("/")
_DEFAULT_MODE = os.getenv("BASA_GW_UPSTREAM_DEFAULT", "subscription-passthrough").lower()
# Virtual key de Basa en cualquier header de auth (auto-byok, spec 019 US2).
_BASA_KEY_RE = re.compile(r"sk-basa-[A-Za-z0-9._\-]+")
_MONITOR_KEY = "basa:gw:events"       # mismo feed que alimenta /gw/monitor (US3)
_MONITOR_CAP = 100
_MONITOR_TTL_S = 300
_DISPLAY_CAP = 2000

# Headers que jamás se reenvían: hop-by-hop, largo/encoding (httpx los recomputa) y
# los propios de control. TODO lo demás (Authorization OAuth, anthropic-beta,
# user-agent, x-app…) viaja verbatim para no romper el path de la credencial.
_HOP_BY_HOP = {
    "host", "content-length", "connection", "keep-alive", "transfer-encoding",
    "accept-encoding", "te", "trailer", "upgrade", "proxy-authorization",
    "x-basa-key", "x-basa-upstream", "x-basa-team", "x-basa-redact",
}


# ── helpers de request ────────────────────────────────────────────────────────────

def _forward_headers(request: Request) -> dict:
    """Copia los headers del cliente (menos hop-by-hop/control) para que el OAuth de
    suscripción y cada header que la credencial necesita lleguen intactos a Anthropic."""
    out = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
    out["Accept-Encoding"] = "identity"  # SSE sin gzip para poder reescribir/tap tokens
    return out


def _with_query(url: str, request: Request) -> str:
    q = request.url.query
    return f"{url}?{q}" if q else url


def _last_user_text(body: dict) -> str:
    """Turno user más reciente, aplanado a texto (para el preview del monitor)."""
    messages = body.get("messages")
    for msg in reversed(messages if isinstance(messages, list) else []):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [b.get("text", "") for b in content
                     if isinstance(b, dict) and isinstance(b.get("text"), str)]
            return "\n".join(p for p in parts if p)
    return ""


async def _safe_preview(body: dict) -> str:
    """Preview del turno user SIEMPRE enmascarado (Constraint C1): el monitor jamás
    muestra PII cruda, aun en modo detección. Usa un mapa desechable (no toca el body
    reenviado)."""
    text = _last_user_text(body)[:_DISPLAY_CAP]
    if not text:
        return ""
    try:
        masked = await policy.mask_text(text, policy.default_analyze, policy.PlaceholderMap())
        return policy.redact_secrets(masked)  # una credencial jamás llega a la vitrina (C1)
    except Exception:  # noqa: BLE001
        return ""  # vitrina: nunca arriesgar mostrar el original si el masker falla


def _anthropic_error(message: str, status_code: int = 400):
    return JSONResponse(
        status_code=status_code,
        content={"type": "error", "error": {"type": "invalid_request_error", "message": message}},
    )


# ── política (paridad EXACTA con BasaGuardrail.async_pre_call_hook) ────────────────

async def evaluate_request_policy(body: dict, redact_enabled: bool):
    """Aplica la política Basa a un body Anthropic, en el MISMO orden que el guardrail
    del motor: (1) AI-Act Art.5 → block, (2) secretos → block, (3) PII → mask reversible.

    Devuelve ``(block_reason|None, compliance_status, ph_to_orig, masked_entities)``.
    Muta ``body`` in-place cuando enmascara (igual que ``mask_body`` en el motor)."""
    inspect_text = policy.extract_inspect_text(body)

    verdict = policy.evaluate_ai_act(inspect_text)
    if verdict["status"] == "blocked_prohibited":
        return verdict["reason"], "blocked_prohibited", {}, []

    secrets = policy.detect_secrets(inspect_text)
    if secrets:
        reason = (f"Petición bloqueada: material secreto detectado ({', '.join(secrets)}). "
                  "Las credenciales nunca deben enviarse a un modelo.")
        return reason, "blocked_secret", {}, []

    status = verdict["status"]  # passed | flagged_high_risk
    ph_to_orig: dict = {}
    masked_entities: list = []
    if redact_enabled:
        _, ph_to_orig = await policy.mask_body(body, policy.default_analyze)
        if ph_to_orig:
            masked_entities = _entity_counts(ph_to_orig)
    return None, status, ph_to_orig, masked_entities


def _entity_counts(ph_to_orig: dict) -> list:
    """[{'type','count'}] desde el mapa reversible (idéntico al del guardrail)."""
    counts: dict = {}
    for ph in ph_to_orig:
        m = policy.PH_TYPE_RE.match(ph)
        etype = m.group(1) if m else "PII"
        counts[etype] = counts.get(etype, 0) + 1
    return [{"type": t, "count": c} for t, c in counts.items()]


def _unmask_json(payload: dict, ph_to_orig: dict) -> dict:
    """Des-enmascara una respuesta no-streaming (Anthropic o OpenAI-like). Espejo de
    ``BasaGuardrail._unmask_response_inplace`` sobre el dict ya parseado."""
    for blk in payload.get("content", []) or []:
        if not isinstance(blk, dict):
            continue
        btype = blk.get("type")
        if btype == "text" and isinstance(blk.get("text"), str):
            blk["text"] = policy.unmask_text(blk["text"], ph_to_orig)
        elif btype == "thinking" and isinstance(blk.get("thinking"), str):
            blk["thinking"] = policy.unmask_text(blk["thinking"], ph_to_orig)
        elif btype == "tool_use":
            blk["input"] = policy.unmask_deep(blk.get("input"), ph_to_orig)
    for ch in payload.get("choices", []) or []:  # fallback openai-like
        msg = ch.get("message") if isinstance(ch, dict) else None
        if isinstance(msg, dict) and isinstance(msg.get("content"), str):
            msg["content"] = policy.unmask_text(msg["content"], ph_to_orig)
    return payload


# ── identidad opcional (atribución, NO fail-closed — [D-014]) ─────────────────────

def _resolve_attribution(basa_key: Optional[str]) -> dict:
    """Resuelve ``X-Basa-Key`` → tenant/client/toggles para AUDITORÍA. Ausente o
    inválida ⇒ tenant por defecto anónimo (esta ruta se autentica con el OAuth, no
    con la key Basa). Sesión efímera propia; nunca levanta."""
    ident = {
        "tenant_id": str(DEFAULT_TENANT_ID), "user_id": None, "group_id": None,
        "api_key_id": None, "client_username": None, "tenant_slug": None,
        "group_name": None, "key_label": None,
        "tool_type": None, "redact_enabled": None, "oauth_credential_ref": None,
    }
    if not basa_key or not basa_key.startswith("sk-"):
        return ident
    db = SessionLocal()
    try:
        key = db.query(APIKey).filter(
            APIKey.key_hash == hash_key(basa_key), APIKey.is_active.is_(True)
        ).first()
        if not key:
            return ident
        tenant = db.query(Tenant).filter(Tenant.id == key.tenant_id).first()
        ident.update(
            tenant_id=str(key.tenant_id), api_key_id=str(key.id),
            user_id=str(key.user_id) if key.user_id else None,
            group_id=str(key.group_id) if key.group_id else None,
            client_username=(key.user.username if key.user else None),
            tenant_slug=(tenant.slug if tenant else None),
            group_name=(key.group.name if key.group else None),
            key_label=key.name,
            tool_type=key.tool_type, redact_enabled=key.redact_enabled,
            oauth_credential_ref=key.oauth_credential_ref,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("gateway: atribución best-effort falló (%s); sigo anónimo", exc)
    finally:
        db.close()
    return ident


def _resolve_redact(header_val: Optional[str], ident: dict) -> bool:
    """Toggle de masking: override por header ``X-Basa-Redact``, si no el de la
    Connection (NULL=heredar → True hoy, mismo default que el guardrail)."""
    if header_val is not None:
        return header_val.strip().lower() in ("1", "true", "yes", "on")
    key_toggle = ident.get("redact_enabled")
    return True if key_toggle is None else bool(key_toggle)


# ── auditoría (metadata-only, C1) + feed del monitor (US3) ────────────────────────

def _audit(ident: dict, model: str, in_tok: int, out_tok: int, status: str,
           masked_entities: list, latency_ms: int):
    """AuditLog metadata-only en sesión fresca, scopeada al tenant resuelto (el GUC de
    RLS se inyecta por ``tenant_context`` → correcto también bajo la 017). Nunca texto
    de prompt ni el mapa reversible (Constraint C1)."""
    db = SessionLocal()
    try:
        tid = uuid.UUID(ident["tenant_id"]) if ident.get("tenant_id") else DEFAULT_TENANT_ID
        with tenant_context(tid):
            AuditService.log_transaction(
                db=db, model=model, prompt_tokens=in_tok, completion_tokens=out_tok,
                cost_usd=0.0,  # suscripción = tarifa plana; el costo byok lo mide el motor
                pii_detected=bool(masked_entities), masked_entities=masked_entities,
                compliance_status=status, latency_ms=latency_ms,
                user_id=uuid.UUID(ident["user_id"]) if ident.get("user_id") else None,
                api_key_id=uuid.UUID(ident["api_key_id"]) if ident.get("api_key_id") else None,
                user_group_id=uuid.UUID(ident["group_id"]) if ident.get("group_id") else None,
                processing_purpose="coding-assistant",
                guardian_events=[{"guardian": "Basa Passthrough (suscripción)",
                                  "action": "PROXY", "detail": f"status={status}"}],
                tenant_id=tid,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("gateway: audit log falló (no fatal): %s", exc)
    finally:
        db.close()


def _publish_monitor(ident: dict, tool: str, model: str, status: str,
                     masked_entities: list, masked_preview: str, surface: Optional[str] = None):
    """Evento efímero para /gw/monitor — MISMO esquema que basa_audit_logger, así la
    vitrina renderiza el tráfico del passthrough igual que el del motor. Preview ya
    enmascarado (C1). ``surface`` distingue la extensión browser (spec 019 US3). Best-effort."""
    client = get_redis()
    if client is None:
        return
    try:
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": ident.get("tool_type") or tool,
            "client": ident.get("client_username"),
            "tenant": ident.get("tenant_slug"),
            "model": model,
            "compliance_status": status,
            "masked_entities": masked_entities,
            "masked_preview": masked_preview,
        }
        if surface:
            event["surface"] = surface
        pipe = client.pipeline()
        pipe.lpush(_MONITOR_KEY, json.dumps(event, ensure_ascii=False))
        pipe.ltrim(_MONITOR_KEY, 0, _MONITOR_CAP - 1)
        pipe.expire(_MONITOR_KEY, _MONITOR_TTL_S)
        pipe.execute()
    except Exception:  # noqa: BLE001
        pass


# ── upstream: OAuth verbatim (cliente) o gestionado por Basa (Fernet ref) ─────────

def _upstream_headers(request: Request, ident: dict) -> dict:
    """Headers hacia Anthropic. Caso normal: el cliente manda su propio OAuth y viaja
    verbatim. Caso gestionado ([D-014]): si el cliente NO trae credencial y la
    Connection referencia un secreto Fernet, se descifra en memoria y se inyecta."""
    headers = _forward_headers(request)
    has_client_cred = bool(request.headers.get("authorization") or request.headers.get("x-api-key"))
    ref = ident.get("oauth_credential_ref")
    if not has_client_cred and ref:
        token = encryption_service.decrypt(ref)
        if token:
            headers["Authorization"] = f"Bearer {token}"
    return headers


# ── selección de modo: passthrough (suscripción) vs byok (motor) — spec 019 US1/US2 ──

def _normalize_mode(val: Optional[str]) -> str:
    """`byok` o `subscription-passthrough` (glosa histórica del demo: "anthropic")."""
    return "byok" if (val or _DEFAULT_MODE).lower() == "byok" else "subscription-passthrough"


def _detect_mode_and_key(request: Request, x_basa_upstream: Optional[str],
                         x_basa_key: Optional[str]):
    """Auto-byok (US2): si aparece una virtual key ``sk-basa-…`` en un header de auth
    (excluyendo ``x-basa-*``) o en la URL (``?k=…``, fallback de Copilot), enruta a
    **byok** y la usa como identidad. La exclusión de ``x-basa-*`` es **load-bearing**:
    el ``sk-basa`` de atribución de Claude Code viaja SOLO en ``X-Basa-Key`` y NO debe
    sacarlo del passthrough de suscripción. Devuelve ``(mode, basa_key)``."""
    cred = None
    for hn, hv in request.headers.items():
        if hn.lower().startswith("x-basa-"):
            continue
        m = _BASA_KEY_RE.search(hv or "")
        if m:
            cred = m.group(0)
            break
    if not cred:
        m = _BASA_KEY_RE.search(str(request.url))  # key-in-URL (atajo de demo, Copilot)
        if m:
            cred = m.group(0)
    if cred:
        if not x_basa_key:
            x_basa_key = cred
        if not x_basa_upstream:
            x_basa_upstream = "byok"
    return _normalize_mode(x_basa_upstream), x_basa_key


def _byok_headers(request: Request, basa_key: str) -> dict:
    """Headers hacia el motor LiteLLM: la ``sk-basa-…`` del cliente viaja como auth para
    que el ``custom_auth`` del motor resuelva tenant/client (fail-closed suyo). El caller
    garantiza ``basa_key`` presente — byok sin virtual key se rechaza con 401 ANTES de
    llegar acá (F2): el master key del proxy NUNCA es alcanzable desde una ruta de
    cliente (evita el bypass a PROXY_ADMIN que saltaría auth/budgets/atribución)."""
    return {
        "Content-Type": "application/json",
        "Accept-Encoding": "identity",
        "anthropic-version": request.headers.get("anthropic-version", "2023-06-01"),
        "Authorization": f"Bearer {basa_key}",
    }


async def _byok_proxy(request: Request, raw: bytes, basa_key: Optional[str], is_stream: bool):
    """Router FINO al motor LiteLLM (spec 019 US2). El body va **verbatim** (el motor
    enmascara/bloquea/audita vía BasaGuardrail); el gateway NO aplica política acá para
    no duplicarla. La respuesta del motor ya viene des-enmascarada."""
    # F2 fail-closed: byok EXIGE una virtual key. Sin ella no se cae al master key del
    # motor (sería un bypass a PROXY_ADMIN saltando custom_auth/budgets/atribución).
    if not basa_key:
        return _anthropic_error("[Basa Gateway] byok requiere una virtual key (sk-basa-…).", 401)
    url = _with_query(f"{_LITELLM_UPSTREAM}/v1/messages", request)
    headers = _byok_headers(request, basa_key)

    if not is_stream:
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                up = await client.post(url, headers=headers, content=raw)
        except Exception as exc:  # noqa: BLE001
            return _anthropic_error(f"[Basa Gateway] motor no disponible: {exc}", 502)
        return Response(content=up.content, status_code=up.status_code,
                        media_type=up.headers.get("content-type", "application/json"))

    client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0, read=60.0))
    try:
        req = client.build_request("POST", url, headers=headers, content=raw)
        up = await client.send(req, stream=True)
    except Exception as exc:  # noqa: BLE001
        await client.aclose()
        return _anthropic_error(f"[Basa Gateway] motor no disponible: {exc}", 502)
    if up.status_code != 200:
        err = await up.aread()
        await up.aclose()
        await client.aclose()
        return Response(content=err, status_code=up.status_code,
                        media_type=up.headers.get("content-type", "application/json"))

    async def gen():
        try:
            async for chunk in up.aiter_raw():
                yield chunk
        finally:
            await up.aclose()
            await client.aclose()

    return StreamingResponse(gen(), status_code=200,
                             media_type=up.headers.get("content-type", "text/event-stream"))


# ── endpoint principal ────────────────────────────────────────────────────────────

@router.post("/v1/messages")
async def gw_messages(
    request: Request,
    x_basa_key: Optional[str] = Header(None, alias="X-Basa-Key"),
    x_basa_redact: Optional[str] = Header(None, alias="X-Basa-Redact"),
    x_basa_upstream: Optional[str] = Header(None, alias="X-Basa-Upstream"),
):
    # Modo degradado DURO (spec 021 US4, FR-020): con el toggle activo y la
    # licencia expired/over_seat, el tráfico se corta ACÁ — antes de ruteo
    # byok/suscripción, política y upstream. Default (toggle off): solo la
    # creación de seats se bloquea; este passthrough sigue sirviendo.
    degraded = hard_block_reason()
    if degraded is not None:
        return _anthropic_error(f"[Basa Gateway] license_degraded: {degraded}", 403)
    start = time.time()
    raw = await request.body()
    try:
        body = json.loads(raw)
    except Exception:  # noqa: BLE001
        return _anthropic_error("Cuerpo JSON inválido.")
    # Trust boundary: acá entra JSON crudo del cliente (a diferencia de la ruta motor,
    # que recibe un body ya validado por LiteLLM). Un cuerpo no-objeto o un `messages`
    # que no es lista devuelve 400 honesto (como Anthropic), nunca un 500.
    if not isinstance(body, dict):
        return _anthropic_error("Cuerpo inválido: se esperaba un objeto JSON.")
    if body.get("messages") is not None and not isinstance(body.get("messages"), list):
        return _anthropic_error("Cuerpo inválido: 'messages' debe ser una lista.")

    model = body.get("model", "unknown")
    is_stream = bool(body.get("stream"))

    # ── ruteo de puerta única (spec 019): byok → motor (política del motor), else
    # passthrough de suscripción → Anthropic (política del gateway) ──
    mode, x_basa_key = _detect_mode_and_key(request, x_basa_upstream, x_basa_key)
    if mode == "byok":
        return await _byok_proxy(request, raw, x_basa_key, is_stream)

    ident = _resolve_attribution(x_basa_key)
    tool = policy.detect_tool(request.headers.get("user-agent"))
    redact_enabled = _resolve_redact(x_basa_redact, ident)

    # ── política: bloquear/enmascarar (misma librería que el motor) ──
    block_reason, status, ph_to_orig, masked_entities = await evaluate_request_policy(body, redact_enabled)
    preview = await _safe_preview(body)  # tras mask_body: refleja lo que verá el upstream

    if block_reason:
        latency = int((time.time() - start) * 1000)
        _audit(ident, model, 0, 0, status, masked_entities, latency)
        _publish_monitor(ident, tool, model, status, masked_entities, preview)
        logger.info("gateway BLOCK (%s) tool=%s model=%s", status, tool, model)
        return _anthropic_error(f"[Basa Gateway] {block_reason}")

    send_raw = json.dumps(body).encode("utf-8") if ph_to_orig else raw
    url = _with_query(f"{_ANTHROPIC_UPSTREAM}/v1/messages", request)
    up_headers = _upstream_headers(request, ident)

    # ── no-streaming ──
    if not is_stream:
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                up = await client.post(url, headers=up_headers, content=send_raw)
        except Exception as exc:  # noqa: BLE001
            latency = int((time.time() - start) * 1000)
            _audit(ident, model, 0, 0, "upstream_error", masked_entities, latency)
            return _anthropic_error(f"[Basa Gateway] No se pudo contactar el modelo upstream: {exc}", 502)

        in_tok = out_tok = 0
        content_out = up.content
        try:
            payload = up.json()
            usage = payload.get("usage") or {}
            in_tok = int(usage.get("input_tokens") or 0)
            out_tok = int(usage.get("output_tokens") or 0)
            if ph_to_orig and up.status_code == 200:
                content_out = json.dumps(_unmask_json(payload, ph_to_orig)).encode("utf-8")
        except Exception:  # noqa: BLE001
            pass
        final_status = status if up.status_code == 200 else "upstream_error"
        latency = int((time.time() - start) * 1000)
        _audit(ident, model, in_tok, out_tok, final_status, masked_entities, latency)
        _publish_monitor(ident, tool, model, final_status, masked_entities, preview)
        return Response(content=content_out, status_code=up.status_code,
                        media_type=up.headers.get("content-type", "application/json"))

    # ── streaming (SSE) ──
    # Total sin límite (los streams legítimos son largos) pero connect/read ACOTADOS:
    # un upstream que acepta el TCP y luego no manda nada abortaría con 502 en vez de
    # colgar el worker para siempre. Anthropic emite `ping` SSE periódicos → read=60s safe.
    client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0, read=60.0))
    try:
        req = client.build_request("POST", url, headers=up_headers, content=send_raw)
        up = await client.send(req, stream=True)
    except Exception as exc:  # noqa: BLE001
        await client.aclose()
        latency = int((time.time() - start) * 1000)
        _audit(ident, model, 0, 0, "upstream_error", masked_entities, latency)
        return _anthropic_error(f"[Basa Gateway] No se pudo contactar el modelo upstream: {exc}", 502)

    if up.status_code != 200:
        err_body = await up.aread()
        await up.aclose()
        await client.aclose()
        latency = int((time.time() - start) * 1000)
        _audit(ident, model, 0, 0, "upstream_error", masked_entities, latency)
        return Response(content=err_body, status_code=up.status_code,
                        media_type=up.headers.get("content-type", "application/json"))

    async def gen():
        """Estrategia A′ (misma que el streaming hook del guardrail): decoder UTF-8
        incremental + buffer de frames + ``rewrite_sse_block`` (carry-split). Con
        ``ph_to_orig`` vacío pasa los frames intactos y sólo extrae tokens de usage —
        así no hace falta el regex ``_IN_RE/_OUT_RE`` del demo (FR-030)."""
        in_tok = out_tok = 0
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        buffer = ""
        carry = ""
        carry_field: Optional[str] = None
        try:
            async for chunk in up.aiter_raw():
                buffer += decoder.decode(chunk)
                while "\n\n" in buffer:
                    block, buffer = buffer.split("\n\n", 1)
                    if not block.strip():
                        continue
                    out_blocks, carry, carry_field, di, do = policy.rewrite_sse_block(
                        block, carry, carry_field, ph_to_orig)
                    if di is not None:
                        in_tok = di
                    if do is not None:
                        out_tok = do
                    for ob in out_blocks:
                        yield (ob + "\n\n").encode("utf-8")
            buffer += decoder.decode(b"", final=True)
            if buffer.strip():
                out_blocks, carry, carry_field, di, do = policy.rewrite_sse_block(
                    buffer, carry, carry_field, ph_to_orig)
                if di is not None:
                    in_tok = di
                if do is not None:
                    out_tok = do
                for ob in out_blocks:
                    yield (ob + "\n\n").encode("utf-8")
            if carry:  # stream truncado: flush del carry (0 texto perdido, 0 placeholder crudo)
                yield policy.unmask_text(carry, ph_to_orig).encode("utf-8")
        finally:
            await up.aclose()
            await client.aclose()
            latency = int((time.time() - start) * 1000)
            _audit(ident, model, in_tok, out_tok, status, masked_entities, latency)
            _publish_monitor(ident, tool, model, status, masked_entities, preview)
            logger.info("gateway PROXY ok tool=%s model=%s in=%d out=%d masked=%d",
                        tool, model, in_tok, out_tok, len(masked_entities))

    return StreamingResponse(gen(), status_code=200,
                             media_type=up.headers.get("content-type", "text/event-stream"))


# ── passthroughs finos que Claude Code también llama (verbatim, sin política) ─────

async def _plain_passthrough(request: Request, path: str, method: str, ident: dict,
                             x_basa_upstream: Optional[str] = None,
                             x_basa_key: Optional[str] = None):
    """count_tokens / models: reenvío verbatim. Honra auto-byok (Copilot/Cursor no mandan
    header de control): con virtual key → motor; si no → suscripción del cliente. NO se
    enmascara (count_tokens necesita el conteo real; el destino es la propia suscripción).

    ``x_basa_key`` se threadea a ``_detect_mode_and_key`` con la MISMA semántica que
    ``/v1/messages`` (P2): un ruteo byok explícito (``X-Basa-Upstream: byok``) con la
    virtual key SOLO en ``X-Basa-Key`` resuelve byok en vez de un 401 espurio — el scan
    de headers excluye ``x-basa-*`` (load-bearing), así que sin threadear la key el motor
    nunca se contactaría. F2 sigue intacto: byok sin NINGUNA key sigue siendo 401."""
    mode, basa_key = _detect_mode_and_key(request, x_basa_upstream, x_basa_key)
    if mode == "byok":
        # F2: mismo fail-closed que /v1/messages — byok sin virtual key jamás usa el
        # master key del motor (evita el bypass a PROXY_ADMIN en count_tokens/models).
        if not basa_key:
            return _anthropic_error("[Basa Gateway] byok requiere una virtual key (sk-basa-…).", 401)
        url = _with_query(f"{_LITELLM_UPSTREAM}{path}", request)
        up_headers = _byok_headers(request, basa_key)
    else:
        url = _with_query(f"{_ANTHROPIC_UPSTREAM}{path}", request)
        up_headers = _upstream_headers(request, ident)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            if method == "GET":
                up = await client.get(url, headers=up_headers)
            else:
                up = await client.post(url, headers=up_headers, content=await request.body())
        return Response(content=up.content, status_code=up.status_code,
                        media_type=up.headers.get("content-type", "application/json"))
    except Exception as exc:  # noqa: BLE001
        return _anthropic_error(f"[Basa Gateway] upstream: {exc}", 502)


@router.post("/v1/messages/count_tokens")
async def gw_count_tokens(request: Request,
                          x_basa_key: Optional[str] = Header(None, alias="X-Basa-Key"),
                          x_basa_upstream: Optional[str] = Header(None, alias="X-Basa-Upstream")):
    return await _plain_passthrough(request, "/v1/messages/count_tokens", "POST",
                                    _resolve_attribution(x_basa_key), x_basa_upstream, x_basa_key)


@router.get("/v1/models")
async def gw_models(request: Request,
                    x_basa_key: Optional[str] = Header(None, alias="X-Basa-Key"),
                    x_basa_upstream: Optional[str] = Header(None, alias="X-Basa-Upstream")):
    return await _plain_passthrough(request, "/v1/models", "GET",
                                    _resolve_attribution(x_basa_key), x_basa_upstream, x_basa_key)


@router.get("")
async def gw_info():
    """Descubrimiento: apuntar el ANTHROPIC_BASE_URL de una coding tool acá."""
    return {
        "service": "Basa Firewall Gateway (puerta única: passthrough + byok)",
        "usage": "Apuntá ANTHROPIC_BASE_URL de tu coding tool a …/api/v1/gw",
        "endpoints": ["/gw/v1/messages", "/gw/v1/messages/count_tokens", "/gw/v1/models"],
        "modes": {
            "subscription-passthrough": "OAuth del cliente verbatim → api.anthropic.com (la suscripción paga); política del gateway.",
            "byok": "virtual key sk-basa-… → motor LiteLLM (cost tracking + budgets); la política la aplica el motor.",
        },
        "routing": "auto: sk-basa-… en header de auth (excl. x-basa-*) o en ?k=… → byok; si no, passthrough. Override: X-Basa-Upstream.",
        "headers": {"X-Basa-Key": "atribución opcional (tenant/client) para auditoría",
                    "X-Basa-Redact": "override del masking PII por request (1/0)",
                    "X-Basa-Upstream": "forzar modo: byok | subscription-passthrough"},
    }
