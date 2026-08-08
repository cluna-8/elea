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
(excepción acotada del Principio II — base_url clients). Ese fail-open vale para la
ATRIBUCIÓN y solo para ella: desde la 027 el mismo header decide qué postura de
gobernanza se aplica, y ahí la ausencia de tenant atribuible resuelve **fail-closed**
(ver ``_resolve_governance_profile``) — omitir un header opcional no puede ser la forma
de elegirse una postura más laxa.

**Secreto OAuth (FR-025, Constraint C5):** el token nunca vive en ``config.yaml``. En
el caso normal lo pone el cliente (header, verbatim). En el caso gestionado por Basa,
la Connection referencia un secreto Fernet (``oauth_credential_ref``) que se descifra
en memoria; jamás en claro en disco.

**Gobernanza configurable (spec 027 US2, T026):** este plano deja de leer un booleano
suelto de masking y pasa a resolver el **Profile** del tenant
(``resolve_tenant_profile``) para ``(modo efectivo, superficie)``. Tres consecuencias
observables: (1) el piso —interceptar/registrar, evaluar AI-Act, detectar PII, bloquear
secretos— corre SIEMPRE, también con el enmascarado apagado (la PII se detecta y se
registra como "detectada, no enmascarada por configuración", D8); (2) cada pedido lleva
su **atribución** (``applied_layers`` + ``blocked_by_layer``) a la fila de auditoría y al
evento del monitor, en vez del ``guardian_events`` fijo que decía "PROXY" pasara lo que
pasara; (3) ``X-Basa-Redact`` pasa a ser **solo restrictivo**: puede forzar el masking
ON para ese pedido, pero su "off" se ignora con telemetría — ningún input por-request
controlado por el cliente puede relajar la postura del admin (research D5).
"""
import asyncio
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
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import or_

from ..database import SessionLocal, tenant_context
from ..licensing.degraded import require_not_hard_blocked
from ..models.budget import APIKey
from ..models.tenant import DEFAULT_TENANT_ID, Tenant
from ..services import encryption_service
from ..services.audit_service import (
    AUDIT_FAIL_CLOSED,
    AuditService,
    AuditUnavailableError,
    audit_fail_mode,
    audit_writable,
    record_audit_loss,
    record_nlp_degradation,
)
# Gobernanza (spec 027): SIEMPRE por la puerta del backend (governance_catalog), nunca
# importando `extensions.basa_governance` a mano — un segundo camino de import carga el
# módulo dos veces y deja dos catálogos en memoria (ver el docstring de esa puerta).
from ..services.governance_catalog import (
    ON,
    Profile,
    ROUTE_GATEWAY_PASSTHROUGH,
    VERDICT_ALLOW,
    VERDICT_BLOCK,
    VERDICT_FLAG,
    VERDICT_MASK,
    build_attribution,
    map_effective_mode,
    resolve_profile,
)
from ..services.governance_resolution import (
    build_connection_overrides,
    load_tenant_decisions,
    resolve_tenant_profile,
)
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
# Subset de la decisión de ruteo que ve la vitrina (spec 030, contrato del evento). El
# objeto decisión completo (data-model §2) lleva además `requested` y `reason`: eso va al
# Debugger Técnico y a la columna durable, no al feed efímero. Ver `_publish_monitor`.
_ROUTING_EVENT_KEYS = ("route", "score", "model_selected", "degraded")
# Pseudo-modelo del plano chat: el motor NO lo conoce (research R9).
_AUTO_MODEL = "auto"

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


def _textos_enmascarables(bloque: dict) -> list:
    """Strings de un bloque de content que el enmascarado SÍ transforma.

    **Espejo exacto de ``policy._mask_content``** — y tiene que seguir siéndolo. Ese es el
    contrato: cada string que este helper devuelve es un string que ``mask_body`` reescribe,
    o sea que leerlo del body ya enmascarado es seguro.

    Por qué es load-bearing (hallazgo ALTO del review adversarial del #63): antes se
    recogía ``b.get("text")`` de CUALQUIER dict del content, sin mirar el ``type``, mientras
    el masker sólo toca ``type == "text"`` y ``type == "tool_result"``. Un bloque
    ``{"type": "image", "text": "Sr. Juan Pérez, juan@clinica.es"}`` —forma válida de la API,
    y trivial de construir para un cliente— viajaba SIN enmascarar y salía LITERAL a la
    vitrina y a Redis por el atajo ``ya_enmascarado`` de ``_safe_preview``. C1 prohíbe
    exactamente eso: PII cruda en el monitor.

    Nota deliberada: ``policy.extract_inspect_text`` sigue siendo más amplio (recoge todo
    ``text``) y está bien así — ese texto alimenta DETECTORES (AI-Act, secretos, conteo de
    PII), donde mirar de más es conservador. Acá se MUESTRA, y mostrar de más es una fuga."""
    tipo = bloque.get("type")
    if tipo == "text":
        return [bloque["text"]] if isinstance(bloque.get("text"), str) else []
    if tipo == "tool_result":
        contenido = bloque.get("content")
        if isinstance(contenido, str):
            return [contenido]
        if isinstance(contenido, list):
            return [sub["text"] for sub in contenido
                    if isinstance(sub, dict) and sub.get("type") == "text"
                    and isinstance(sub.get("text"), str)]
    return []


def _last_user_text(body: dict) -> str:
    """Turno user más reciente, aplanado a texto (para el preview del monitor).

    Sólo los strings que el enmascarado transforma (``_textos_enmascarables``): lo que este
    helper devuelve termina en la vitrina, así que no puede incluir un campo que el masker
    nunca tocó."""
    messages = body.get("messages")
    for msg in reversed(messages if isinstance(messages, list) else []):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [texto for b in content if isinstance(b, dict)
                     for texto in _textos_enmascarables(b)]
            return "\n".join(p for p in parts if p)
    return ""


async def _safe_preview(body: dict, nlp: Optional[dict] = None,
                        ya_enmascarado: bool = False) -> str:
    """Preview del turno user SIEMPRE enmascarado (Constraint C1): el monitor jamás
    muestra PII cruda, aun en modo detección. Usa un mapa desechable (no toca el body
    reenviado).

    Usa el MISMO analizador que la política del pedido (issue #63): con el sidecar NLP
    configurado, un preview enmascarado con regex mostraría en la vitrina justo lo que el
    regex no caza —un nombre sin tratamiento, un móvil español sin +34— mientras el tráfico
    real sí quedaba protegido. La vitrina no puede ser la superficie menos protegida.

    Con el analyzer CAÍDO este camino es fail-open a ``""`` **y jamás cae al regex**, ni
    siquiera con ``nlp_fail_mode = degrade``: una preview sub-enmascarada es una fuga de PII
    a Redis y al monitor (C1), y una preview vacía no filtra nada. La degradación a regex es
    una decisión sobre el TRÁFICO (que el cliente necesita para trabajar), no sobre una
    vitrina de la que nadie depende.

    ``ya_enmascarado`` evita el pase de detección REDUNDANTE. ``evaluate_request_policy``
    muta el body in-place, así que cuando el enmascarado corrió con el detector real el texto
    que se lee acá **ya viene con placeholders** y volver a analizarlo no puede encontrar nada
    nuevo: sólo cuesta otro viaje al sidecar por pedido. Con el detector NLP configurado ese
    viaje no es gratis —es el componente más caro del camino caliente— y duplicarlo para una
    vitrina sería pagar el doble por lo mismo. El caller sólo lo pasa en `True` cuando el
    enmascarado REALMENTE corrió y con el detector real: en el camino de bloqueo (body crudo)
    y en el degradado a regex se sigue haciendo el pase propio."""
    text = _last_user_text(body)[:_DISPLAY_CAP]
    if not text:
        return ""
    if ya_enmascarado:
        # El texto ya lleva placeholders; sólo falta el scrub de credenciales, que es regex
        # pura y no depende de ningún detector (C1: una credencial jamás llega a la vitrina).
        return policy.redact_secrets(text)
    analyze, _usa_nlp = _build_analyze(nlp)
    try:
        masked = await policy.mask_text(text, analyze, policy.PlaceholderMap())
        return policy.redact_secrets(masked)  # una credencial jamás llega a la vitrina (C1)
    except Exception:  # noqa: BLE001 — incluye NlpUnavailableError, a propósito (ver docstring)
        return ""  # vitrina: nunca arriesgar mostrar el original si el masker falla


def _anthropic_error(message: str, status_code: int = 400):
    return JSONResponse(
        status_code=status_code,
        content={"type": "error", "error": {"type": "invalid_request_error", "message": message}},
    )


# ── política (paridad EXACTA con BasaGuardrail.async_pre_call_hook) ────────────────
#
# Detección NLP en ESTE plano (issue #63). Hasta el fix, todo `/gw` corría
# `policy.default_analyze` —el regex de dev/demo— aunque `NLP_ANALYZER_URL` estuviera
# configurada y el sidecar sano: el docstring del módulo prometía «paridad EXACTA con
# BasaGuardrail.async_pre_call_hook» y el motor sí usaba el NLP real. Resultado observable:
# el mismo prompt salía enmascarado por byok (motor) y sub-enmascarado por suscripción
# (gateway), sin que nada lo dijera. La paridad se restituye en UN solo punto de decisión
# (`_build_analyze`) para que los tres call-sites de este archivo no puedan volver a divergir.


def nlp_analyzer_url() -> str:
    """URL del sidecar de detección NLP, o cadena vacía si no está configurada.

    Se lee POR LLAMADA y no se congela al importar (a diferencia del motor, que corre en una
    imagen pinneada): mismo criterio que `audit_fail_mode()` — un `compose up -d` con la env
    cambiada surte efecto sin rebuild, y los tests la pueden monkeypatchear sin recargar el
    módulo. Cadena vacía = modo regex de desarrollo EXPLÍCITO (Constraint SC-2)."""
    return (os.environ.get("NLP_ANALYZER_URL") or "").strip()


def _build_analyze(nlp: Optional[dict]):
    """``(analyze, usa_nlp)`` — el ÚNICO punto donde este plano elige detector.

    Réplica de la decisión del motor (`basa_guardrail.async_pre_call_hook`, paso 3): con
    `NLP_ANALYZER_URL` seteada se llama al sidecar con los `custom_names`/`custom_entities`
    del guardián `pii_masking` y la región configurada; sin ella, el regex de dev.

    ``nlp`` es el contexto que resolvió `_resolve_attribution` (una sola lectura por pedido,
    en la sesión que ese helper ya abría). ``None`` ⇒ se usa el sidecar igual, pero sin
    listas personalizadas: no tener la config del guardián no puede degradar el detector."""
    url = nlp_analyzer_url()
    if not url:
        return policy.default_analyze, False
    cfg = nlp or {}
    custom_names = cfg.get("custom_names") or []
    custom_entities = cfg.get("custom_entities") or []
    # Misma env y mismo default que el motor (spec 016): la región no puede diferir entre
    # planos o el mismo texto detectaría entidades distintas según por dónde entró.
    region = os.environ.get("BASA_ENTITY_REGION", policy.DEFAULT_REGION)

    async def _analyze(text: str) -> list:
        return await policy.presidio_analyze(text, url, custom_names, region,
                                             custom_entities=custom_entities)

    return _analyze, True


def _as_profile(profile) -> Profile:
    """Acepta un ``Profile`` o el booleano de masking legado (013) y devuelve SIEMPRE un
    ``Profile``.

    El booleano existía antes de la 027 y sigue siendo lo que muchos callers tienen en la
    mano (``profile.is_on('pii_masking')``). Traducirlo acá —como override de nivel
    Connection, que es el nivel donde vivía ese toggle— evita dos firmas conviviendo y
    garantiza que **toda** entrada a la política produzca atribución: sin esto, un caller
    con el booleano no tendría perfil y la 027 volvería a tener pedidos sin registro de
    capas (SC-005). ``None`` ⇒ postura por defecto de producto (piso + masking on)."""
    if isinstance(profile, Profile):
        return profile
    overrides = build_connection_overrides(profile) if profile is not None else {}
    return resolve_profile(map_effective_mode(ROUTE_GATEWAY_PASSTHROUGH), None, (),
                           surface_trusted=False, connection_overrides=overrides)


async def _count_detected_pii(inspect_text: str, analyze=None) -> Optional[int]:
    """Cuenta la PII del pedido **sin tocar el body** — el piso ``pii_detection`` (D8).

    Con el enmascarado apagado, antes de la 027 no corría ningún detector: el pedido
    salía verbatim y la auditoría no sabía que llevaba datos personales. FR-002 lo
    prohíbe: detectar es piso, transformar es la capa gobernable. Se enmascara sobre un
    ``PlaceholderMap`` **desechable** (mismo patrón que ``_safe_preview``) y se tira el
    texto: solo sobrevive el contador.

    ``None`` si el detector falla: sin veredicto la capa se reporta ``not_configured`` —
    "no pudimos confirmar que corrió"— en vez de afirmar un cero que sería una mentira
    tranquilizadora. Con el analyzer NLP caído ese ``None`` **es** la respuesta correcta y no
    se sustituye por un conteo de regex (issue #63): este contador vive en el camino donde el
    enmascarado está APAGADO por decisión, así que un número sacado de otro detector diría
    "encontramos N" cuando lo cierto es "no pudimos mirar con lo que corresponde"."""
    if not inspect_text:
        return 0
    if analyze is None:
        analyze, _usa_nlp = _build_analyze(None)
    try:
        pmap = policy.PlaceholderMap()
        await policy.mask_text(inspect_text, analyze, pmap)
        return len(pmap.ph_to_orig)
    except Exception as exc:  # noqa: BLE001
        # C1: se loguea el hecho, jamás el texto ni el valor detectado.
        logger.warning("gateway: detección de PII (piso) falló; capa sin veredicto: %s", exc)
        return None


def _verdict(decision: str, count: Optional[int] = None) -> dict:
    """Elemento de veredicto para ``build_attribution``: código + contador, nada más (C1)."""
    return {"decision": decision, "count": count} if count else {"decision": decision}


async def evaluate_request_policy(body: dict, profile=None, nlp: Optional[dict] = None):
    """Aplica la política Basa a un body Anthropic, en el MISMO orden que el guardrail
    del motor: (1) AI-Act Art.5 → block, (2) secretos → block, (3) PII → detección
    (piso) → enmascarado reversible **solo si** el perfil lo tiene encendido.

    ``profile`` es el ``Profile`` resuelto por la 027 (o el booleano legado de masking,
    ver ``_as_profile``). Devuelve ``(block_reason|None, compliance_status, ph_to_orig,
    masked_entities, attribution)`` — la ``Attribution`` es el quinto elemento nuevo: las
    dos columnas ``applied_layers``/``blocked_by_layer`` ya con su forma final.
    Muta ``body`` in-place cuando enmascara (igual que ``mask_body`` en el motor).

    **Los veredictos se reportan de lo que REALMENTE pasó, no de lo que se deseaba**: una
    capa que no llegó a correr (porque una anterior bloqueó) NO se reporta, y
    ``build_attribution`` la marca ``not_configured``. Ese es el punto entero de la 027:
    "no la aplicamos" y "no corrió" dejan de ser indistinguibles.

    ``nlp`` (issue #63) es el contexto de detección del tenant —``custom_names``,
    ``custom_entities`` y ``nlp_fail_mode``— que ``_resolve_attribution`` resolvió en la
    sesión que ya abría por pedido. ``None`` es válido (lo usan los tests y el call-site de
    la superficie browser): el detector NLP se elige igual por env, sin listas personalizadas
    y con ``nlp_fail_mode`` en su default ``block``."""
    profile = _as_profile(profile)
    analyze, _usa_nlp = _build_analyze(nlp)
    # El piso `interception_audit` es la propiedad que hace del producto un firewall:
    # llegado este punto el pedido está interceptado y va a auditarse, así que su
    # veredicto es afirmable siempre.
    verdicts: dict = {"interception_audit": _verdict(VERDICT_ALLOW)}
    inspect_text = policy.extract_inspect_text(body)

    verdict = policy.evaluate_ai_act(inspect_text)
    if verdict["status"] == "blocked_prohibited":
        verdicts["ai_act_evaluation"] = _verdict(VERDICT_BLOCK)
        return (verdict["reason"], "blocked_prohibited", {}, [],
                build_attribution(profile, verdicts))
    verdicts["ai_act_evaluation"] = _verdict(
        VERDICT_FLAG if verdict["status"] == "flagged_high_risk" else VERDICT_ALLOW)

    secrets = policy.detect_secrets(inspect_text)
    if secrets:
        verdicts["secret_detection"] = _verdict(VERDICT_BLOCK, len(secrets))
        reason = (f"Petición bloqueada: material secreto detectado ({', '.join(secrets)}). "
                  "Las credenciales nunca deben enviarse a un modelo.")
        return reason, "blocked_secret", {}, [], build_attribution(profile, verdicts)
    verdicts["secret_detection"] = _verdict(VERDICT_ALLOW)

    status = verdict["status"]  # passed | flagged_high_risk
    ph_to_orig: dict = {}
    masked_entities: list = []
    if profile.is_on("pii_masking"):
        # El `PlaceholderMap` se crea acá —y no dentro de `mask_body`— porque el camino de
        # degradación del #63 continúa con el MISMO mapa: `mask_body` recorre los turnos de a
        # uno, así que una caída del analyzer a mitad de camino deja parte del body ya
        # enmascarada. Con un mapa nuevo (otro nonce) esos placeholders no tendrían original
        # al que volver y saldrían CRUDOS al cliente en el unmask de la respuesta.
        pmap = policy.PlaceholderMap()
        try:
            _, ph_to_orig = await policy.mask_body(body, analyze, pmap)
        except policy.NlpUnavailableError:
            fail_mode = policy.resolve_nlp_fail_mode(nlp)
            if fail_mode == policy.NLP_FAIL_BLOCK:
                # Fail-closed (default, y lo que ya hacía el motor desde la 016): sin
                # detección NLP confiable no hay garantía de protección. El bloqueo se
                # atribuye a `pii_detection` —la capa que falló— con el MISMO vocabulario del
                # motor, para que la fila durable de los dos planos sea indistinguible.
                verdicts["pii_detection"] = _verdict(VERDICT_BLOCK)
                return (policy.NLP_BLOCK_MESSAGE, policy.STATUS_NLP_BLOCKED, {}, [],
                        build_attribution(profile, verdicts))
            # `degrade`: se sigue sirviendo con el regex de dev, pero JAMÁS en silencio —
            # marca de estado en Redis + `logger.error` (los dos dentro de
            # `record_nlp_degradation`) + `compliance_status` propio en la fila durable de
            # ESTA transacción, que es lo que hace consultable el hecho después.
            # #8 (#105): `record_nlp_degradation` usa el cliente Redis SÍNCRONO, y esta rama
            # corre en CADA request mientras el analyzer está caído. Llamarla inline bloquea el
            # event loop del worker en cada pedido degradado si Redis está lento. Se despacha a
            # un hilo (mismo patrón que `entity_catalog_service`) para no frenar el loop; con
            # los timeouts acotados de `redis_client` el hilo tampoco queda pegado. Best-effort:
            # jamás propaga, así que el pedido degradado se sirve igual pase lo que pase con la
            # marca.
            await asyncio.to_thread(record_nlp_degradation, reason="gateway/mask_body")
            _, ph_to_orig = await policy.mask_body(body, policy.default_analyze, pmap)
            # El estado de degradación PISA `passed`/`flagged_high_risk`: entre "salió sin
            # novedad" y "salió con media protección", lo segundo es lo que el officer tiene
            # que ver en la columna. El flag de AI-Act no se pierde — sigue en
            # `applied_layers` como veredicto `flag` de `ai_act_evaluation`.
            status = policy.STATUS_NLP_DEGRADED
        if ph_to_orig:
            masked_entities = _entity_counts(ph_to_orig)
        detected: Optional[int] = len(ph_to_orig)
        verdicts["pii_masking"] = _verdict(VERDICT_MASK if ph_to_orig else VERDICT_ALLOW,
                                           len(ph_to_orig))
    else:
        # D8: el enmascarado apagado es una postura legítima, pero la detección es piso.
        # `pii_masking` queda SIN veredicto ⇒ `skipped` (apagada por decisión), y
        # `pii_detection` lleva el hallazgo: esa combinación ES el registro "datos
        # personales detectados, no enmascarados por configuración" (FR-002).
        detected = await _count_detected_pii(inspect_text, analyze)
    if detected is not None:
        verdicts["pii_detection"] = _verdict(VERDICT_FLAG if detected else VERDICT_ALLOW,
                                             detected)
    return None, status, ph_to_orig, masked_entities, build_attribution(profile, verdicts)


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
    con la key Basa). Sesión efímera propia; nunca levanta.

    Desde la 027 la misma sesión trae también las **decisiones de gobernanza** del tenant
    resuelto: la postura se resuelve por pedido y meterlas acá es lo que evita abrir una
    segunda sesión en el camino caliente. Consecuencia asumida: el tráfico anónimo (sin
    ``X-Basa-Key``), que antes no tocaba la base, ahora hace una lectura indexada por
    tenant — el precio de que la postura del admin también gobierne ese tráfico."""
    ident = {
        "tenant_id": str(DEFAULT_TENANT_ID), "user_id": None, "group_id": None,
        "api_key_id": None, "client_username": None, "tenant_slug": None,
        "group_name": None, "key_label": None,
        "tool_type": None, "redact_enabled": None, "oauth_credential_ref": None,
        # Decisiones de gobernanza del tenant (spec 027): viajan con la identidad para
        # NO abrir una segunda sesión por pedido — el perfil se resuelve después, en
        # memoria, con la cascada pura.
        "governance_decisions": (),
        # Contexto de detección NLP del tenant (issue #63): `custom_names`,
        # `custom_entities` y `nlp_fail_mode` del guardián `pii_masking`. Viaja por el MISMO
        # canal y por la MISMA razón que las decisiones de gobernanza — una lectura por
        # pedido en la sesión que este helper ya abre, en vez de N queries en el camino
        # caliente. Es el equivalente en este plano a lo que `custom_auth` le pasa al motor
        # dentro de `user_api_key_metadata.basa`.
        "nlp": {},
    }
    db = SessionLocal()
    try:
        if basa_key and basa_key.startswith("sk-"):
            # `expires_at` es DateTime naive-UTC (convención del modelo 013): se compara
            # contra un "ahora" naive-UTC, la MISMA forma que la fuente única de verdad de
            # "key activa no expirada" (``seat_counter.count_active_seats``). Comparar la
            # columna naive contra un datetime aware dejaría la resolución colgada de la
            # zona horaria de la sesión Postgres.
            ahora = datetime.now(timezone.utc).replace(tzinfo=None)
            key = db.query(APIKey).filter(
                APIKey.key_hash == hash_key(basa_key),
                APIKey.is_active.is_(True),
                # US8a: una key VENCIDA cae al fallback anónimo igual que una inexistente.
                # Sin este filtro, una key con `is_active=True` y `expires_at` en el pasado
                # se resolvía (atribución + login válidos); con él, `whoami`/`inspect`
                # responden el MISMO 401 indistinguible que con una key que no existe — sin
                # oráculo que revele "vencida". `expires_at` NULL = sin vencimiento.
                or_(APIKey.expires_at.is_(None), APIKey.expires_at > ahora),
            ).first()
            if key:
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
        # También para el tráfico anónimo: sin ``X-Basa-Key`` el pedido se audita contra
        # el tenant por defecto, y en una instalación de un solo tenant ESE es el tenant
        # cuya postura configuró el admin. Saltear la lectura acá dejaría al tráfico sin
        # atribución fuera de la gobernanza que el admin cree haber configurado.
        ident["governance_decisions"] = _governance_rows(db, ident["tenant_id"])
        ident["nlp"] = _nlp_context(db, ident["tenant_id"],
                                    atribuible=_tenant_atribuible(ident))
    except Exception as exc:  # noqa: BLE001
        logger.warning("gateway: atribución best-effort falló (%s); sigo anónimo", exc)
    finally:
        db.close()
    return ident


def _nlp_context(db, tenant_id, atribuible: bool = False) -> dict:
    """Config de detección del guardián ``pii_masking`` del tenant (issue #63).

    UNA consulta por pedido, sobre la sesión que ``_resolve_attribution`` ya tiene abierta:
    el mismo precio que la 027 aceptó pagar para que la postura del admin gobierne también
    al tráfico anónimo. Es la puerta del backend equivalente al subquery que ``custom_auth``
    ya hace para el motor, así que los dos planos leen exactamente la misma fila.

    **Fail-closed**: si la lectura falla, dict vacío ⇒ sin listas personalizadas y
    ``nlp_fail_mode`` en su default ``block``. No poder leer la config sólo puede quitar
    relajaciones, nunca concederlas — mismo criterio que ``_governance_rows``.

    **Sin tenant atribuible, ``nlp_fail_mode`` se fuerza a ``block``** (hallazgo ALTO del
    review adversarial). Es la MISMA barrera que la 027 ya aplica al perfil de gobernanza en
    ``_resolve_governance_profile`` (``Profile.from_dict(..., trusted=False)``: sobreviven
    las decisiones que AGREGAN protección, se descartan las que RELAJAN), y falta acá por el
    mismo motivo por el que hacía falta allá. ``X-Basa-Key`` es OPCIONAL en esta ruta —la
    credencial es el OAuth—, así que sin esta línea, en una instalación multi-tenant,
    **omitir el header** bastaba para caer al ``DEFAULT_TENANT_ID``: si ESE tenant tiene
    ``degrade``, un cliente cuyo admin configuró ``block`` conseguía que su tráfico se
    sirviera con regex tirando abajo el sidecar. La atribución puede degradarse a anónima;
    la postura no puede degradarse a "la de otro".

    ``custom_names``/``custom_entities`` del tenant de fallback SÍ se conservan: sólo pueden
    AGREGAR entidades a enmascarar, nunca quitar. La barrera descarta relajaciones, no datos."""
    try:
        from ..models.guardian import Guardian
        # issue #104: `ORDER BY (created_at, id)` — sin él, con dos `pii_masking` activos el
        # `.first()` devolvía una fila ARBITRARIA y este plano podía leer una postura distinta
        # a la del motor o a la que publica `/health`. Mismo desempate «determinista» que
        # `_IDENTITY_SQL` ya aplica al presupuesto: los cuatro lectores eligen la MISMA fila.
        fila = (db.query(Guardian.config)
                .filter(Guardian.tenant_id == tenant_id,
                        Guardian.guardian_type == "pii_masking",
                        Guardian.is_active.is_(True))
                .order_by(Guardian.created_at, Guardian.id)
                .first())
        cfg = (fila[0] if fila else None) or {}
        return {
            "custom_names": cfg.get("custom_names") or [],
            "custom_entities": cfg.get("custom_entities") or [],
            # Crudo: quien decide es `policy.resolve_nlp_fail_mode`, que tiene el default
            # fail-closed en UN solo lugar para los dos planos. Salvo sin tenant atribuible,
            # donde la barrera de la 027 obliga al valor más protector.
            policy.NLP_FAIL_MODE_KEY: (cfg.get(policy.NLP_FAIL_MODE_KEY) if atribuible
                                       else policy.NLP_FAIL_BLOCK),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("gateway: config de detección NLP no legible (%s); defaults "
                       "fail-closed (nlp_fail_mode=block, sin listas personalizadas)", exc)
        return {}


# Campos que el resolutor lee de cada fila de decisión. Se copian a un dict PLANO a
# propósito: las filas ORM quedan desprendidas al cerrar la sesión, y el resolutor acepta
# Mappings tal cual — así el camino caliente nunca puede toparse con un lazy-load muerto.
_GOVERNANCE_ROW_FIELDS = ("tenant_id", "scope_type", "scope_value", "layer_key", "decision")


def _governance_rows(db, tenant_id) -> tuple:
    """Decisiones de gobernanza del tenant, ya desprendidas del ORM. **Fail-closed**: si
    la lectura falla, conjunto vacío ⇒ defaults de producto (piso + masking on). No poder
    leer solo puede quitar relajaciones: degrada hacia más protección, jamás hacia menos."""
    try:
        return tuple({f: getattr(row, f, None) for f in _GOVERNANCE_ROW_FIELDS}
                     for row in load_tenant_decisions(db, tenant_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("gateway: postura de gobernanza no legible (%s); defaults de producto", exc)
        return ()


# User-Agent → ``tool_type`` del CHECK de la Connection. Señal **spoofeable** (D5): se usa
# SOLO con ``surface_trusted=False``, donde una fila de superficie que RELAJA queda inerte
# y únicamente las que AGREGAN protección aplican. Lo que `detect_tool` no sepa mapear a un
# token del enum cae a ``None`` y la cascada arranca en el modo (fallback explícito).
_UA_TO_SURFACE = {
    "Claude Code": "claude-code",
    "GitHub Copilot": "copilot",
    "Cursor": "cursor",
}


def _resolve_surface(ident: dict, ua_tool: Optional[str]):
    """``(superficie, confiable)``. Confiable = el ``tool_type`` que el admin provisionó en
    la Connection (resuelta por ``X-Basa-Key``); todo lo demás sale del User-Agent, que el
    cliente elige, y por eso entra como no confiable."""
    tool_type = ident.get("tool_type")
    if ident.get("api_key_id") and tool_type:
        return tool_type, True
    return _UA_TO_SURFACE.get(ua_tool or ""), False


def _redact_header_override(header_val: Optional[str]) -> Optional[str]:
    """``X-Basa-Redact`` — **solo restrictivo** (cierre del bypass, research D5/T026).

    El header es un override **por-request controlado por el cliente**: puede FORZAR el
    enmascarado (agregar protección con una señal no confiable siempre es legal) pero su
    "off" se **ignora**, porque relajar la postura del admin desde un header sería exactamente
    el vector que la regla de superficie confiable prohíbe — cualquiera con acceso al
    endpoint apagaba el control más fuerte del producto escribiendo ``X-Basa-Redact: 0``.

    Devuelve ``ON`` (forzar) o ``None`` (no hay override). El "off" ignorado se cuenta y se
    loguea **metadata-only** (C1: ni texto del pedido ni identidad en el mensaje) para que
    la degradación no sea silenciosa: un cliente que insiste con off es una señal de
    configuración vieja, no un error del pedido.

    **Nivel warning, no info** (hallazgo de la verificación adversarial de la US2): el
    logger del backend corre con nivel efectivo WARNING en el contenedor, así que el
    ``logger.info`` anterior no se veía en ningún lado y la telemetría que el contrato pide
    ("el off se ignora **con telemetría**", resolutor #5) era decorativa. Un intento de
    relajar la postura por un canal no confiable merece verse: no es tráfico normal."""
    if header_val is None:
        return None
    if header_val.strip().lower() in ("1", "true", "yes", "on"):
        return ON
    _REDACT_OFF_IGNORED["count"] += 1
    logger.warning("gateway: X-Basa-Redact=off IGNORADO (override por-request no puede "
                   "relajar la postura del administrador; spec 027). total=%d",
                   _REDACT_OFF_IGNORED["count"])
    return None


# Telemetría del header ignorado: un contador por proceso, sin identidad ni contenido.
_REDACT_OFF_IGNORED = {"count": 0}


def redact_off_ignored_count() -> int:
    """Cuántas veces se ignoró un ``X-Basa-Redact: off`` en este proceso.

    Mismo patrón que ``malformed_verdict_counters`` del catálogo: contador metadata-only +
    accesor público. Existe para que la degradación sea **consultable** y no solo
    logueable — un log que nadie agrega no falsifica nada. Es el punto de lectura de los
    tests y del día que la vista de estado quiera mostrar "hay integraciones pidiendo
    apagar el enmascarado" (no se cablea acá: el discovery ``GET /gw`` es público y un
    contador operativo no va en una respuesta anónima)."""
    return _REDACT_OFF_IGNORED["count"]


def reset_redact_off_ignored() -> None:
    """Solo para los tests: el contador es global por proceso."""
    _REDACT_OFF_IGNORED["count"] = 0


def _tenant_atribuible(ident: dict) -> bool:
    """¿Este pedido está atribuido a un tenant de verdad, o cayó al tenant por defecto?

    Atribuible = ``X-Basa-Key`` resolvió una Connection activa (``api_key_id``). Sin eso,
    ``_resolve_attribution`` deja el ``DEFAULT_TENANT_ID`` como fallback anónimo: sirve
    para AUDITAR (dónde archivar la fila), no para decidir **de qué tenant se aplica la
    postura** — el cliente elegiría el tenant simplemente omitiendo un header opcional."""
    return bool(ident.get("api_key_id"))


def _resolve_governance_profile(ident: dict, ua_tool: Optional[str],
                                redact_header: Optional[str],
                                route: str = ROUTE_GATEWAY_PASSTHROUGH) -> Profile:
    """Postura efectiva de ESTE pedido (spec 027 T026).

    - **Modo** desde el ruteo EFECTIVO, jamás desde ``upstream_mode`` crudo: acá solo llega
      suscripción (byok se rutea al motor unas líneas antes de la política), así que la
      ruta es ``gateway-passthrough`` por construcción del plano. ``route`` es explícito
      para el otro call-site de este plano (la superficie browser, ``inspect.py``), que
      declara su propia ruta en vez de heredar una constante escondida.
    - **Superficie** del ``tool_type`` de la Connection (confiable) o del User-Agent (no
      confiable) — ver ``_resolve_surface``.
    - **Overrides de nivel Connection**: el toggle ``redact_enabled`` en TRI-ESTADO crudo
      (``None`` = heredar, no "True"), más el header cuando fuerza ON. El header entra al
      mismo nivel Connection porque es el más alto de la cascada y solo puede agregar.

    **Sin tenant atribuible, la resolución es fail-closed** (hallazgo MEDIA de la
    verificación adversarial de la US2). Esta ruta se autentica con el OAuth de
    suscripción, no con ``X-Basa-Key``: ese header es OPCIONAL, y hasta la 027 solo decidía
    a nombre de quién se auditaba ([D-014], fail-open deliberado **para atribución**). Al
    pasar a decidir también las ``governance_decisions``, un cliente de una instalación
    multi-tenant conseguía elegir la postura que le aplicaba con solo **omitir** el header:
    caía al ``DEFAULT_TENANT_ID`` y se resolvía con la postura de ese tenant, que puede ser
    más laxa que la de su admin. La atribución puede degradarse a anónima; el enforcement
    no puede degradarse a "la postura de otro".

    Criterio elegido: cuando el tenant no es atribuible, la postura resuelta se pasa por
    ``Profile.from_dict(..., trusted=False)`` — la barrera que ya existe para las señales no
    confiables (hallazgo A2 del Foundational). Efecto: **se conservan las decisiones que
    AGREGAN protección y se descartan todas las que RELAJAN**, que caen al
    ``default_decision`` del registry. O sea el máximo de {postura del tenant por defecto,
    defaults de producto}: la resolución nunca puede ser más laxa que el producto recién
    instalado, y la relajación pasa a exigir lo mismo que exige la regla de superficie de
    D5 — un dato provisionado por el admin (una Connection) viajando con el pedido.

    Dos cosas que este criterio NO hace, a propósito: (a) no mira la postura de otros
    tenants para buscar "la más estricta de la instalación" —sería una lectura cross-tenant,
    prohibida por Constitución III—; (b) no rechaza el pedido: esta ruta es fail-open en
    IDENTIDAD por diseño ([D-014]), así que el tráfico anónimo sigue pasando, solo que
    gobernado con el perfil más protector disponible. En instalaciones single-tenant el
    precio es visible y aceptado: una relajación configurada en ``tenant_default`` (p.ej.
    ``pii_masking=off``) no aplica al tráfico sin ``X-Basa-Key``; para obtenerla hay que
    emitir la Connection, que es exactamente el dato del admin que la regla exige.

    No abre sesión: las filas ya vinieron con la identidad. Sin decisiones legibles, la
    cascada resuelve los defaults de producto (piso + masking on)."""
    surface, trusted = _resolve_surface(ident, ua_tool)
    overrides = dict(build_connection_overrides(ident.get("redact_enabled")))
    if _redact_header_override(redact_header) == ON:
        overrides["pii_masking"] = ON
    profile = resolve_tenant_profile(
        None, ident.get("tenant_id"),
        mode=map_effective_mode(route),
        surface=surface, surface_trusted=trusted,
        connection_overrides=overrides,
        decisions=ident.get("governance_decisions") or (),
    )
    if _tenant_atribuible(ident):
        return profile
    # `trusted=False` = "esto viene de un canal que no autentica al tenant": se ignoran las
    # relajaciones y sobreviven solo las decisiones que agregan capas.
    return Profile.from_dict(profile.to_dict(), trusted=False)


# ── auditoría (metadata-only, C1) + feed del monitor (US3) ────────────────────────

_AUDIT_503_DETAIL = ("auditoría no disponible — la instalación exige registro "
                     "(audit_fail=closed)")


def _audit_no_disponible():
    """503 honesto del contrato (§Semántica closed), con la FORMA de error de Anthropic.

    El cuerpo importa tanto como el código: las coding tools parsean ``error.message`` y un
    503 con otro shape lo muestran como "respuesta inesperada del proxy", que es justo la
    confusión que este modo intenta evitar. El motivo va explícito para que el operador sepa
    que el corte es de auditoría y no del proveedor."""
    return _anthropic_error(f"[Basa Gateway] {_AUDIT_503_DETAIL}", 503)


def _audit_precheck_ok() -> bool:
    """¿Puede seguir este pedido? (contrato §Semántica closed, D4).

    En ``open`` devuelve True SIN tocar la base: esa instalación eligió continuidad con
    pérdida contada, así que cobrarle un ``SELECT 1`` por pedido sería pagar por una
    pregunta cuya respuesta no cambia nada.

    En ``closed`` es el pre-check literal de FR-005 —«rechazar ANTES de llamar al
    proveedor»—: si la base de auditoría no responde, el pedido no sale del gateway y no se
    gasta dinero en tráfico que después nadie va a poder registrar. Sesión propia y corta
    (este plano no tiene ``get_db``: su identidad es el OAuth del cliente, no una sesión de
    request), cerrada acá mismo para no retener conexión del pool durante una caída.
    """
    if audit_fail_mode() != AUDIT_FAIL_CLOSED:
        return True
    db = SessionLocal()
    try:
        return audit_writable(db)
    except Exception as exc:  # noqa: BLE001 — `audit_writable` ya no propaga; red de seguridad
        logger.error("gateway: el pre-check de auditoría falló (%s) — pedido rechazado (closed)",
                     exc)
        return False
    finally:
        db.close()


def _audit(ident: dict, model: str, in_tok: int, out_tok: int, status: str,
           masked_entities: list, latency_ms: int, attribution=None) -> bool:
    """AuditLog metadata-only en sesión fresca, scopeada al tenant resuelto (el GUC de
    RLS se inyecta por ``tenant_context`` → correcto también bajo la 017). Nunca texto
    de prompt ni el mapa reversible (Constraint C1).

    ``attribution`` (spec 027) trae ``applied_layers`` + ``blocked_by_layer``: qué capas
    corrieron de verdad en ESTE pedido y cuál lo bloqueó. Reemplaza al ``guardian_events``
    que se escribía fijo —``{"guardian": "Basa Passthrough", "action": "PROXY"}``— pasara
    lo que pasara: un registro que decía lo mismo para un pedido enmascarado, uno bloqueado
    por secreto y uno que salió verbatim. ``guardian_events`` queda congelado como legado,
    sin migración (D6).

    **Devuelve si la fila quedó escrita** (spec 031, D5). Antes esta función era el tercer
    tragador en fila: envolvía TODO en un ``except`` con ``logger.warning`` («no fatal»), o
    sea que una base caída borraba el registro del passthrough —el único plano que ya
    auditaba bloqueos— y nadie se enteraba. Ahora el reintento acotado y el contador de
    pérdidas viven en el escritor (``AuditService.log_transaction``) y acá sólo queda la
    traducción a booleano:

    * ``True``  → la fila es durable;
    * ``False`` → no hay fila, y la pérdida YA quedó contada (``basa:audit:lost``) y
      logueada con nivel error por el escritor.

    Sigue sin propagar excepciones —romper el request es decisión del caller, no de la
    auditoría— pero el caller que necesita cortar (modo ``closed``, antes de responder)
    tiene con qué: mira el booleano. ``AuditUnavailableError`` se captura por tipo porque en
    ``closed`` el escritor la lanza DESPUÉS de contar la pérdida: re-contarla acá inflaría
    el contador del health al doble.
    """
    db = SessionLocal()
    try:
        tid = uuid.UUID(ident["tenant_id"]) if ident.get("tenant_id") else DEFAULT_TENANT_ID
        # `pii_detected` refleja DETECCIÓN, no enmascarado (D8/FR-002). Con `pii_masking` off
        # el gateway detecta igual (piso) y `masked_entities` queda vacío; derivarlo solo de
        # ahí haría que la fila dijera "no había PII" mientras la atribución dice que
        # `pii_detection` la marcó — la contradicción durable que 027 elimina.
        pii_detected = bool(masked_entities) or (
            attribution is not None and any(
                isinstance(l, dict) and l.get("layer_code") == "pii_detection"
                and (l.get("count") or 0) > 0
                for l in (attribution.applied_layers or ())
            )
        )
        with tenant_context(tid):
            fila = AuditService.log_transaction(
                db=db, model=model, prompt_tokens=in_tok, completion_tokens=out_tok,
                cost_usd=0.0,  # suscripción = tarifa plana; el costo byok lo mide el motor
                pii_detected=pii_detected, masked_entities=masked_entities,
                compliance_status=status, latency_ms=latency_ms,
                user_id=uuid.UUID(ident["user_id"]) if ident.get("user_id") else None,
                api_key_id=uuid.UUID(ident["api_key_id"]) if ident.get("api_key_id") else None,
                user_group_id=uuid.UUID(ident["group_id"]) if ident.get("group_id") else None,
                processing_purpose="coding-assistant",
                applied_layers=(attribution.applied_layers if attribution else None),
                blocked_by_layer=(attribution.blocked_by_layer if attribution else None),
                tenant_id=tid,
            )
        return fila is not None
    except AuditUnavailableError:
        # Modo `closed`: el escritor agotó los reintentos, ya contó la pérdida y ya la
        # logueó. Acá sólo se traduce a "no hay fila" — quien decide qué hacer con eso es
        # el endpoint (503 antes de responder / seguir si la respuesta ya salió).
        return False
    except Exception as exc:  # noqa: BLE001
        # Fallo ANTES o ALREDEDOR del escritor (identidad ilegible, tenant_context, sesión):
        # el escritor no llegó a correr, así que la pérdida no está contada y hay que
        # contarla acá o este camino volvería a ser un agujero silencioso.
        logger.error("gateway: la fila de auditoría NO se escribió (%s): %s", status, exc,
                     exc_info=exc)
        record_audit_loss(reason=f"gateway/_audit/{status}")
        return False
    finally:
        db.close()


def _publish_monitor(ident: dict, tool: str, model: str, status: str,
                     masked_entities: list, masked_preview: str, surface: Optional[str] = None,
                     attribution=None, routing: Optional[dict] = None):
    """Evento efímero para /gw/monitor — MISMO esquema que basa_audit_logger, así la
    vitrina renderiza el tráfico del passthrough igual que el del motor. Preview ya
    enmascarado (C1). ``surface`` distingue la extensión browser (spec 019 US3). Best-effort.

    Con la 027 el "mismo esquema" deja de ser convención y pasa a ser **contrato** (evento
    §8): ``applied_layers`` + ``blocked_by_layer`` viajan con exactamente el mismo elemento
    de 4 claves que persiste ``audit_logs``, serializado **sin transformar** — extender un
    emisor sin los demás rompe el render uniforme de la vitrina.

    **``routing`` (spec 030 T008) es OPCIONAL y así debe quedar.** El contrato de este
    evento tiene TRES productores —este gateway, el plano chat (``chat.py``, que llama a
    esta misma función) y el ``basa_audit_logger`` del motor— y sólo UNO emite el campo:
    el plano chat, y sólo en los requests que el usuario mandó con el pseudo-modelo
    «auto». Ni el gateway ni el motor lo mandan nunca (por /gw «auto» se resuelve al
    default del router sin clasificar — research R9). Por eso la clave **se omite** en vez
    de viajar en ``null``: presente = "hubo una decisión de ruteo semántico", ausente =
    "este plano no rutea", que son cosas distintas y el consumidor (``monitor.py``) las
    distingue renderizando el chip sólo si está. Los productores previos a la 030 siguen
    siendo válidos sin tocarlos.

    El valor se **proyecta** al subset de la vitrina (``route``/``score``/
    ``model_selected``/``degraded``, contrato ``router-config-api.md`` §evento): el objeto
    decisión completo lleva además ``requested`` y ``reason``, que son del Debugger
    Técnico y de la columna durable, no del feed. La proyección vive acá —en el ÚNICO
    serializador del evento, mismo criterio que la atribución— y no en cada call-site, que
    es la forma de que los tres productores no emitan tres shapes del mismo hecho."""
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
            # Ausencia de atribución = **null**, jamás lista vacía (contrato evento §8, y
            # el mismo criterio que ya documenta el logger del motor): `[]` afirmaría "no
            # corrió ninguna capa", que es mentira —el piso corre siempre— y además haría
            # que los tres productores emitieran tres shapes distintos para el mismo hecho.
            # La vitrina distingue null → "sin registro de capas" (monitor.py, `atribucion`).
            "applied_layers": attribution.applied_layers if attribution else None,
            "blocked_by_layer": attribution.blocked_by_layer if attribution else None,
        }
        if surface:
            event["surface"] = surface
        if isinstance(routing, dict):
            subset = {k: routing[k] for k in _ROUTING_EVENT_KEYS if k in routing}
            if subset:  # dict sin ninguna clave del contrato = no hay nada que contar
                event["routing"] = subset
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


def _resolve_auto_model(body: dict, raw: bytes) -> bytes:
    """«auto» por /gw: se reescribe al ``default_model`` del router y NADA más (spec 030
    T017, research R9). Devuelve el body a mandar al motor — el mismo ``raw`` si no hay
    nada que reescribir.

    Por qué existe: «auto» es un **pseudo-modelo del plano chat**; el motor no lo tiene en
    su catálogo, así que un body con ``model: "auto"`` se lleva un 400 suyo. Los coding
    tools declaran modelo explícito, o sea que esto es la red de seguridad del edge case
    (un cliente que copia el nombre que vio en el Playground), no un camino de producto.

    Por qué NO clasifica: la clasificación semántica es del plano chat (v1 de la spec). Acá
    no se embebe nada —ni una llamada al motor de embeddings, ni el prompt saliendo a
    ningún lado— porque el ruteo por /gw no está especificado y adivinarlo sería peor que
    el default explícito que el admin configuró.

    Fail-soft deliberado: si la config no existe, está corrupta o no declara
    ``default_model``, el body pasa **verbatim** y contesta el motor con su error normal.
    Inventar acá un 4xx propio taparía el error real del motor con uno nuestro, y la
    alternativa —elegir un modelo por nuestra cuenta— mandaría el tráfico a un destino que
    nadie configuró. Queda en el log como aviso, no como silencio."""
    if body.get("model") != _AUTO_MODEL:
        return raw
    try:
        # Import perezoso a propósito: el servicio del router es del plano chat y este
        # módulo se importa desde `inspect.py` y desde `chat.py` — importarlo arriba ata
        # el gateway a una dependencia que sólo necesita en un edge case, y cierra un
        # ciclo cuando el servicio crezca.
        from ..services.auto_router_service import load_config
        default_model = (load_config() or {}).get("default_model") or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("gateway: model=auto y la config del router no se pudo leer (%s) — "
                       "body verbatim al motor", exc)
        return raw
    default_model = default_model.strip() if isinstance(default_model, str) else ""
    if not default_model:
        logger.warning("gateway: model=auto sin default_model configurado — body verbatim al motor")
        return raw
    logger.info("gateway: model=auto → %s (default del router; /gw no clasifica)", default_model)
    return json.dumps({**body, "model": default_model}).encode("utf-8")


async def _byok_proxy(request: Request, raw: bytes, basa_key: Optional[str], is_stream: bool):
    """Router FINO al motor LiteLLM (spec 019 US2). El body va **verbatim** (el motor
    enmascara/bloquea/audita vía BasaGuardrail); el gateway NO aplica política acá para
    no duplicarla. Límite conocido (spike 019 batch 1, issue #27): en rutas bridged
    (modelos no-Claude) el unmask de respuesta del motor NO corre hoy — la respuesta
    puede traer placeholders; fail-safe, fix-spec pendiente."""
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

# Modo degradado DURO (spec 021 US4, FR-020): con el toggle activo y la licencia
# expired/over_seat, la dependency corta el tráfico de las rutas de SERVICIO
# antes de ruteo byok/suscripción, política y upstream (count_tokens reenvía el
# body VERBATIM upstream — también debe cortarse). GET /gw (discovery) queda
# abierto. Default (toggle off): solo la creación de seats se bloquea.
_HARD_BLOCK = [Depends(require_not_hard_blocked)]


@router.post("/v1/messages", dependencies=_HARD_BLOCK)
async def gw_messages(
    request: Request,
    x_basa_key: Optional[str] = Header(None, alias="X-Basa-Key"),
    x_basa_redact: Optional[str] = Header(None, alias="X-Basa-Redact"),
    x_basa_upstream: Optional[str] = Header(None, alias="X-Basa-Upstream"),
):
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
        # Modo `closed` (spec 031, FR-005): el corte por auditoría es del plano que TIENE la
        # sesión de base. El motor hace su propio pre-check contra `/internal/audit/probe`,
        # pero eso ya es un salto de red después de haber aceptado el pedido acá; cortarlo
        # en la puerta es más barato y no depende de que la extensión del motor esté al día.
        if not _audit_precheck_ok():
            return _audit_no_disponible()
        # Único retoque del body en esta ruta: «auto» → default del router (T017/R9). Todo
        # lo demás sigue yendo verbatim al motor, que es quien aplica la política.
        return await _byok_proxy(request, _resolve_auto_model(body, raw), x_basa_key, is_stream)

    ident = _resolve_attribution(x_basa_key)
    tool = policy.detect_tool(request.headers.get("user-agent"))
    # Postura de gobernanza del tenant para (modo efectivo, superficie) — spec 027 T026.
    profile = _resolve_governance_profile(ident, tool, x_basa_redact)

    # ── política: bloquear/enmascarar (misma librería que el motor) ──
    # `ident["nlp"]` (issue #63) lleva el contexto de detección del tenant: con
    # `NLP_ANALYZER_URL` configurada este plano usa el sidecar NLP —igual que el motor— en vez
    # del regex de dev que usaba siempre.
    nlp_ctx = ident.get("nlp") or {}
    block_reason, status, ph_to_orig, masked_entities, attribution = \
        await evaluate_request_policy(body, profile, nlp_ctx)
    # Preview SIEMPRE display-masked (contrato evento §10): se construye sobre un mapa
    # desechable + scrub de secretos pase lo que pase con las capas. Es load-bearing en el
    # camino de bloqueo, donde el bloqueo ocurre ANTES de que corra el enmascarado y el
    # body sigue crudo: sin este pase propio, la vitrina sería el canal de fuga.
    # `ya_enmascarado`: el enmascarado corrió, no hubo bloqueo (el body está mutado) y corrió
    # con el detector REAL. Las tres condiciones importan: sin bloqueo el body sigue crudo;
    # con `pii_masking` apagado nunca se tocó; y en el degradado a regex el pase propio se
    # hace igual, para que la vitrina no herede la cobertura menor de esa ronda.
    ya_enmascarado = (not block_reason and profile.is_on("pii_masking")
                      and status != policy.STATUS_NLP_DEGRADED)
    preview = await _safe_preview(body, nlp_ctx, ya_enmascarado)

    if block_reason:
        latency = int((time.time() - start) * 1000)
        # Registrar → bloquear (FR-001): la fila durable se escribe ANTES de devolver el
        # rechazo, y con la 031 su resultado además decide la respuesta en modo `closed`.
        registrado = _audit(ident, model, 0, 0, status, masked_entities, latency, attribution)
        _publish_monitor(ident, tool, model, status, masked_entities, preview,
                         attribution=attribution)
        logger.info("gateway BLOCK (%s) tool=%s model=%s layer=%s registrado=%s",
                    status, tool, model, attribution.blocked_by_layer, registrado)
        if not registrado and audit_fail_mode() == AUDIT_FAIL_CLOSED:
            # US1 AC4: «se bloqueó y no quedó nada» nunca en silencio. En `closed` el cliente
            # se entera de que el registro falló (el bloqueo se mantiene: sigue sin llamarse
            # al proveedor); en `open` recibe el rechazo de siempre y la pérdida queda en el
            # contador + el health.
            return _audit_no_disponible()
        return _anthropic_error(f"[Basa Gateway] {block_reason}")

    # Pedido permitido: en `closed`, confirmar que se va a poder registrar ANTES de gastar
    # dinero en el proveedor (FR-005, literal). En `open` no cuesta ni un SELECT.
    if not _audit_precheck_ok():
        return _audit_no_disponible()

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
            _audit(ident, model, 0, 0, "upstream_error", masked_entities, latency, attribution)
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
        # El booleano se ignora A PROPÓSITO acá: el proveedor ya respondió y la plata ya se
        # gastó, así que un 503 tardío no des-serviría nada — sólo escondería la respuesta
        # que el cliente ya pagó. El contrato (§closed) lo dice literal: el pre-check corta
        # ANTES; lo que falle después es retry + contador. Mismo criterio en el streaming.
        _audit(ident, model, in_tok, out_tok, final_status, masked_entities, latency, attribution)
        _publish_monitor(ident, tool, model, final_status, masked_entities, preview,
                         attribution=attribution)
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
        _audit(ident, model, 0, 0, "upstream_error", masked_entities, latency, attribution)
        return _anthropic_error(f"[Basa Gateway] No se pudo contactar el modelo upstream: {exc}", 502)

    if up.status_code != 200:
        err_body = await up.aread()
        await up.aclose()
        await client.aclose()
        latency = int((time.time() - start) * 1000)
        _audit(ident, model, 0, 0, "upstream_error", masked_entities, latency, attribution)
        return Response(content=err_body, status_code=up.status_code,
                        media_type=up.headers.get("content-type", "application/json"))

    async def gen():
        """Estrategia A′ (misma que el streaming hook del guardrail): decoder UTF-8
        incremental + buffer de frames + ``rewrite_sse_block`` (carry-split). Con
        ``ph_to_orig`` vacío no hay reemplazos (sólo se extraen tokens de usage), pero
        los frames delta SÍ se re-serializan y un ``[`` al final de un delta se difiere
        un frame (carry de ``[`` pelado, 024) — así no hace falta el regex
        ``_IN_RE/_OUT_RE`` del demo (FR-030)."""
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
                # Framed (review 024): crudo, el parser SSE del cliente lo descartaba.
                yield policy.flush_carry_sse_block(carry, carry_field, ph_to_orig).encode("utf-8")
        finally:
            await up.aclose()
            await client.aclose()
            latency = int((time.time() - start) * 1000)
            _audit(ident, model, in_tok, out_tok, status, masked_entities, latency, attribution)
            _publish_monitor(ident, tool, model, status, masked_entities, preview,
                             attribution=attribution)
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
    nunca se contactaría. F2 sigue intacto: byok sin NINGUNA key sigue siendo 401.

    **Sin pre-check de auditoría (spec 031, decisión explícita).** Estas dos rutas no
    generan fila de auditoría —ni con la base sana— porque no llevan prompt al modelo:
    ``count_tokens`` cuenta y ``models`` lista. Cortarlas en ``closed`` rompería la coding
    tool entera durante una caída sin proteger ningún registro (no hay registro que
    proteger) y sin ahorrar dinero (no hay generación que pagar). El corte vive donde sí hay
    tráfico auditable y facturable: ``/v1/messages``."""
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


@router.post("/v1/messages/count_tokens", dependencies=_HARD_BLOCK)
async def gw_count_tokens(request: Request,
                          x_basa_key: Optional[str] = Header(None, alias="X-Basa-Key"),
                          x_basa_upstream: Optional[str] = Header(None, alias="X-Basa-Upstream")):
    return await _plain_passthrough(request, "/v1/messages/count_tokens", "POST",
                                    _resolve_attribution(x_basa_key), x_basa_upstream, x_basa_key)


@router.get("/v1/models", dependencies=_HARD_BLOCK)
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
        # La entrada de X-Basa-Redact cambió con la 027: prometía un override 1/0 y hoy
        # solo puede AGREGAR protección. Documentarlo acá no es cosmética — el discovery
        # es lo que lee quien integra, y una doc que sigue prometiendo "0 = no enmascarar"
        # produce integraciones que creen haber apagado el masking y no lo apagaron.
        "headers": {"X-Basa-Key": "atribución opcional (tenant/client) para auditoría",
                    "X-Basa-Redact": ("solo restrictivo: 1 fuerza el enmascarado PII de "
                                      "este request; 0 se IGNORA (un override por request "
                                      "no puede relajar la postura del administrador). "
                                      "Para no enmascarar, configurá la capa en Gobernanza."),
                    "X-Basa-Upstream": "forzar modo: byok | subscription-passthrough"},
    }
