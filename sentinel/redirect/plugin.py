"""Plugin de pasarela de la política de redireccionamiento (costura S2; T038/T054/T055/T057–T059).

Registro: `GATEWAY_PLUGINS=sentinel.redirect.plugin` (el backend importa este módulo y toma
`gateway_plugin`). Requiere que el paquete `sentinel` sea importable en el backend (imagen o
volumen + `PYTHONPATH`, ver `sentinel/README.md`).

Contrato de identidad (FR-002): `models_filter` corre SIEMPRE y solo oculta `rdx-*`; todo lo
demás sale temprano si para el alcance del pedido la redirección está `off` y no hay filas de
postura. Sin filas en la base, la pasarela se comporta como sin plugin (salvo re-serializar el
JSON, que la costura hace con cualquier plugin).

Flujo con política `on` (byok, `/v1/messages` = cara Claude, `/v1/chat/completions` = cara
genérica), solo para ids **publicados** — un modelo no publicado sigue su camino normal:
1. `pre_request`: resuelve alcance → regla → destino elegible (resolver puro + residencia) y
   aplica FR-010a (lista de modelos de la llave evaluada sobre el id PÚBLICO: la costura no deja
   responder desde `pre_engine`, así que la evaluación ocurre aquí, antes de reescribir nada).
   Sin destino ⇒ error de cara (404 / 403 residencia) y fila de auditoría del corte.
2. `pre_engine`: quita credenciales/destinos del cliente, normaliza para destinos traducidos,
   reescribe `model = rdx-<familia>/<real>` y agrega `x-redirect-authz` (autorización interna
   firmada con la credencial cifrada, D14/D15).
3. `wrap_stream` (ping + `model` público), `map_response` (no-stream: `model` público) y
   `map_error` (categoría por cara).

Modo `shadow`: el pedido sale igual que con `off`; la decisión hipotética viaja firmada para
el MISMO modelo y el guard del motor solo la registra (`routing_decision.extensions.redirect`
con `shadow=true`). Una falla en sombra nunca afecta al pedido.

Postura en el camino de suscripción (FR-001b, parcial en este MVP): si hay filas de postura,
se evalúa contra la jurisdicción del proveedor original y puede responder 403; con
`offregion_masked` fuera de región fuerza el enmascarado de la pasarela y `nlp_fail_mode=block`.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from sentinel.access import bridge

from . import authz, betas, credentials, residency, resolver, stream, thinking, token_estimate
from .faces import claude as claude_face
from .faces import generic as generic_face
from .scopes import RequestScope, applicable
from .store import RedirectStore, StoreUnavailable, default_store

logger = logging.getLogger("sentinel.redirect.plugin")

STATE_KEY = "sentinel.redirect"
ACCESS_KEY = "sentinel.access"
RDX_PREFIX = "rdx-"
REJECTED_MODEL = "rdx-rejected/capability"     # sin autorización ⇒ el guard lo corta siempre
COUNT_TOKENS_ROUTE = "/v1/messages/count_tokens"
ROUTE_FACE = {"/v1/messages": "claude", COUNT_TOKENS_ROUTE: "claude",
              "/v1/chat/completions": "openai_generic"}
# Proveedor del camino de suscripción (credencial personal reenviada tal cual). Dato del
# producto: inferencia y entidad en EE. UU. — lo único que la postura necesita saber de él.
SUBSCRIPTION_PROVIDER = {"inference_jurisdiction": "US", "entity_jurisdiction": "US",
                         "control_jurisdiction": "US"}
SUBSCRIPTION_PROVIDER_NAME = "anthropic"     # proveedor al que sirve la credencial personal (FR-042)
REQUEST_CLASS_HEADER = "x-request-class"
# Ajustes del normalizador que el administrador tiene que ver en la auditoría: contenido del
# usuario o de una herramienta que el destino no recibió (el resto son campos de protocolo).
# Mismo literal que el corte de un plugin (ya inventariado en el clasificador de retención).
MASKING_SCOPE_FULL = "full"       # S14 (QA B3): con el forzado vigente, el enmascarado alcanza todo el cuerpo
STATUS_REJECTED = "blocked_by_policy"
STATUS_PASSED = "passed"        # tráfico que la política resolvió sin impedirlo (inventariado en el clasificador de retención)
OMITTED_AUDIT = ("images_in_history", "images_in_tool_result", "documents_in_tool_result")


@dataclass
class Plan:
    face: str
    public_id: str
    decision: dict
    shadow: bool = False
    engine_model: Optional[str] = None
    destination: dict = field(default_factory=dict)
    credential: dict = field(default_factory=dict, repr=False)
    forced_masking: bool = False
    scope_label: str = ""
    rejected: Optional[str] = None
    rejection_audited: bool = False
    alternatives: tuple = ()          # destinos elegibles tras el elegido (resolución por capacidad)
    snap: Any = field(default=None, repr=False)
    fidelity: str = "native"


# ── utilidades ────────────────────────────────────────────────────────────────

def hide_rdx(listing: Any) -> Any:
    """`rdx-*` jamás se lista (FR-006a, R13: el motor expande el comodín con todo el catálogo)."""
    if isinstance(listing, dict) and isinstance(listing.get("data"), list):
        data = [m for m in listing["data"]
                if not (isinstance(m, dict) and str(m.get("id", "")).startswith(RDX_PREFIX))]
        if len(data) != len(listing["data"]):
            listing = dict(listing)
            listing["data"] = data
            if "first_id" in listing or "last_id" in listing:
                listing["first_id"] = data[0].get("id") if data else None
                listing["last_id"] = data[-1].get("id") if data else None
    return listing


def hide_not_allowed(listing: Any, permitidos: Optional[frozenset], governed: frozenset) -> Any:
    """Perfil de acceso (069 FR-012): el listado solo muestra lo que la identidad puede usar. Solo se
    ocultan los modelos que el catálogo gobierna; el resto del listado queda intacto."""
    if permitidos is None or not (isinstance(listing, dict) and isinstance(listing.get("data"), list)):
        return listing
    data = [m for m in listing["data"]
            if not (isinstance(m, dict) and m.get("id") in governed and m.get("id") not in permitidos)]
    if len(data) == len(listing["data"]):
        return listing
    listing = dict(listing)
    listing["data"] = data
    if "first_id" in listing or "last_id" in listing:
        listing["first_id"] = data[0].get("id") if data else None
        listing["last_id"] = data[-1].get("id") if data else None
    return listing


def request_scope(ident: dict) -> Optional[RequestScope]:
    tenant = ident.get("tenant_id")
    if not tenant:
        return None
    group = ident.get("group_id")
    return RequestScope(tenant_id=str(tenant),
                        connection_id=str(ident["api_key_id"]) if ident.get("api_key_id") else None,
                        user_id=str(ident["user_id"]) if ident.get("user_id") else None,
                        group_ids=(str(group),) if group else ())


def tenant_region(ident: dict) -> Optional[str]:
    """Región del tenant (su `pii_masking.config.region`) o la de la instalación; **sin región ⇒ `None`**, nunca
    `eu` (057 FR-031; research R28). Es `residency.resolve_profile`, la misma función que usan `list_postures` y la
    prueba de fidelidad: el panel dice lo que hace el tráfico."""
    return residency.resolve_profile((ident.get("nlp") or {}).get("region"))


def _error(face: str, kind: str, **kw) -> JSONResponse:
    if face == "claude":
        status, headers, body = claude_face.error_response(kind, **kw)
    else:
        status, headers, body = generic_face.error_response(kind, **kw)
    return JSONResponse(status_code=status, content=body, headers=headers or None)


# Códigos que emite el guard del motor (`sentinel/engine/redirect_guard.py`): son rechazos de
# Sentinel, no fallas del proveedor, y nunca se presentan como reintentables (069 FR-008d). El
# motor los devuelve dentro del mensaje (repr de Python) o en `provider_specific_fields` (JSON).
_GUARD_CODE_RE = re.compile(r"""['"]code['"]\s*:\s*['"](masking_required|authz_[a-z_]+|family_mismatch|destination_misconfigured)['"]""")
_GUARD_KIND = {"masking_required": "masking_blocked", "destination_misconfigured": "destination_misconfigured"}


def guard_rejection_kind(content) -> Optional[str]:
    text = content.decode("utf-8", "replace") if isinstance(content, (bytes, bytearray)) else str(content or "")
    m = _GUARD_CODE_RE.search(text)
    if not m:
        return None
    code = m.group(1)
    return _GUARD_KIND.get(code, "policy_blocked")


def _error_bytes(face: str, kind: str, **kw):
    resp = _error(face, kind, **kw)
    return resp.status_code, resp.body, {k: v for k, v in resp.headers.items()
                                         if k.lower() not in ("content-length", "content-type")}


def _decision(face: str, public_id: str, res, *, request_class, shadow: bool) -> dict:
    """Solo metadata (FR-033): claves cortas y escalares (S7 `extensions`)."""
    d = {"public_id": public_id, "face": face, "request_class": request_class,
         "shadow": shadow}
    if isinstance(res, resolver.Resolved):
        d["strategy"] = res.strategy
    if isinstance(res, resolver.Resolved):
        dest = res.destination
        d.update(destination_id=dest.get("id"), destination_name=dest.get("name"),
                 fidelity=res.fidelity, rule_id=res.rule_id, residency_mode=res.residency_mode,
                 jurisdiction_served=res.jurisdiction_served,
                 substitution_reason=res.substitution_reason, forced_masking=res.forced_masking)
        if res.in_region is not None:
            d["in_region"] = res.in_region                     # FR-028a: sin nombres de entidad
        if res.masking_relaxation:
            d["masking_relaxation"] = res.masking_relaxation   # R24: region | destination
        if shadow:
            d["shadow_destination_id"] = d.pop("destination_id")
    else:
        d.update(unavailable=res.kind, error_class=res.error_class, rule_id=res.rule_id)
    return {k: (str(v) if v is not None and not isinstance(v, (bool, int, float, str)) else v)
            for k, v in d.items()}


_TIER_WORD = re.compile(r"(?<![a-z])(opus|sonnet|haiku|fable|mythos)(?![a-z])")


def infer_tier(model_id: Any) -> Optional[str]:
    """Tier de un id `claude-*` por su nombre (`claude-sonnet-4-5-20250929` → `sonnet`); `None` si no hay una
    sola palabra de tier. Solo se usa para un id NO publicado (US1 esc. 4, FR-015): cae a la regla por tier."""
    text = str(model_id or "").lower()
    if not text.startswith("claude"):
        return None
    found = set(_TIER_WORD.findall(text))
    return found.pop() if len(found) == 1 else None


def _names_value(names, limit: int = 128) -> str:
    """Lista de nombres para un valor de `extensions` (el plano interno corta a 128 caracteres): los que no
    caben se resumen en `otros_<n>` en vez de quedar cortados a la mitad."""
    out, used = [], 0
    for i, name in enumerate(names):
        if used + len(name) + 1 > limit - len("otros_99") - 1:
            out.append(f"otros_{len(names) - i}")
            break
        out.append(name)
        used += len(name) + 1
    return ",".join(out)


def _audit_block(decision: dict) -> dict:
    return {"extensions": {"redirect": decision}}


def _access_block(model: str) -> dict:
    return {"extensions": {"access": {"blocked": "profile_not_allowed", "requested": model}}}


# ── el plugin ─────────────────────────────────────────────────────────────────

def _signed_provider_options(dest: dict) -> Optional[dict]:
    """Lo que del destino viaja firmado al guard: para `openrouter`, la lista de proveedores permitidos (FR-032)."""
    if dest.get("provider") != "openrouter":
        return None
    allow = [str(p) for p in ((dest.get("provider_options") or {}).get("providers_allowlist") or ())
             if isinstance(p, str) and p.strip()]
    return {"providers_allowlist": allow}


class RedirectPlugin:
    def __init__(self, store: Optional[RedirectStore] = None, *, ping_after: float = stream.DEFAULT_PING_AFTER,
                 clock=time.time, audit=None, estimator=None):
        self._store = store
        self._estimator = estimator or token_estimate.estimate    # `count_tokens` local (T093 de Sentinel)
        self.ping_after = ping_after
        self._clock = clock
        self._audit = audit                     # escritor de filas de la pasarela; None ⇒ el del backend

    def _write_row(self, ctx, model, status: str, decision: dict, what: str) -> None:
        """Escribe una fila metadata-only con el escritor de la pasarela (`routing_decision`, sin
        contenido). NUNCA propaga: la respuesta al cliente sale igual."""
        try:
            writer = self._audit
            if writer is None:
                from src.api import gateway               # el backend: import perezoso, como el motor
                writer = gateway._audit
            writer(ctx.ident or {}, str(model), 0, 0, status, [], 0, None,
                   routing_decision=_audit_block(decision))
        except Exception:  # noqa: BLE001
            logger.exception("redirect: no se pudo auditar %s", what)

    def _audit_rejection(self, ctx, plan: Plan) -> None:
        """Fila de auditoría del rechazo por capacidad (069 FR-008c): motivo, modelo pedido y
        destino evaluado, sin contenido. El rechazo se decide en `pre_engine` y el motor lo corta
        antes de llamar a nadie: el logger del motor corre solo en éxito y el gateway byok no
        audita los errores del motor, así que sin esto no quedaba rastro. Una sola vez por pedido
        y NUNCA propaga: el rechazo al cliente sale igual, como con la fila del 402 del motor."""
        if plan.rejection_audited:
            return
        plan.rejection_audited = True
        self._write_row(ctx, ctx.model or plan.public_id, STATUS_REJECTED, plan.decision,
                        f"el rechazo por capacidad ({plan.rejected})")

    @property
    def store(self) -> RedirectStore:
        return self._store if self._store is not None else default_store()

    async def _snapshot(self, tenant_id: str):
        return await run_in_threadpool(self.store.snapshot, tenant_id)

    # models_filter: SIEMPRE (FR-002 / FR-006a)
    def models_filter(self, ctx, listing):
        listing = hide_rdx(listing)
        view = ctx.state.get(STATE_KEY + ".models_view")
        if view is not None:
            return view
        return hide_not_allowed(listing, *ctx.state.get(ACCESS_KEY, (None, frozenset())))

    async def pre_request(self, ctx):
        scope = request_scope(ctx.ident or {})
        if scope is None:
            return None
        face = ROUTE_FACE.get(ctx.route)
        permitidos, governed = None, frozenset()
        if (face is not None and ctx.route != COUNT_TOKENS_ROUTE) or ctx.route == "/v1/models":
            # Perfil de acceso (069 US2): SIEMPRE, aunque la redirección esté apagada. Si no se pueden
            # resolver los permitidos, el pedido no se sirve (fail-closed, FR-014a). `count_tokens` no se
            # gobierna por perfil (069: no sirve un modelo; test_count_tokens_y_otras_rutas_no_se_tocan).
            try:
                permitidos, governed = await run_in_threadpool(bridge.allowed_for_ident, ctx.ident or {})
            except Exception:  # noqa: BLE001
                logger.exception("acceso: no se pudieron resolver los modelos permitidos")
                return _error(face or generic_face.select_models_view(ctx.request_headers or {}),
                              "policy_unavailable")
            if permitidos is not None:
                ctx.state[ACCESS_KEY] = (permitidos, governed)
        try:
            snap = await self._snapshot(scope.tenant_id)
        except StoreUnavailable as exc:
            return self._access_cut(ctx, face, permitidos, governed, redirected=False) \
                or self._store_down(ctx, scope, exc)
        if snap.empty():
            return self._access_cut(ctx, face, permitidos, governed, redirected=False)
        try:
            state = resolver.effective_state(snap.policy, scope)
        except ValueError:                                # fila corrupta ⇒ fail-closed
            return self._fail_closed(ctx) if ROUTE_FACE.get(ctx.route) else None
        postures = applicable(snap.postures, scope)
        if ctx.route == "/v1/models":
            if state == "on":
                self._build_models_view(ctx, snap, scope, permitidos)
            return None
        if face is None:
            return None                                   # otras rutas: sin cambio
        # un id publicado con la redirección en `on` se decide por sus destinos (más abajo); todo lo
        # demás que el catálogo gobierna se corta acá
        published = resolver.find_published(snap.published, scope, face, ctx.model) if ctx.model else None
        inferred = None
        if published is None and self._tier_fallback_applies(ctx, face, state):
            inferred = self._inferred_row(ctx, scope)             # US1 esc. 4: cae a la regla por tier
        redirected = state == "on" and bool(ctx.model) and (published is not None or inferred is not None)
        cut = self._access_cut(ctx, face, permitidos, governed, redirected=redirected)
        if cut is not None:
            return cut
        if state == "off" and not postures:
            return None
        if ctx.mode == "subscription":
            foreign = self._subscription_foreign(ctx, snap, scope, face, state, permitidos)
            if foreign is not None:
                return foreign
            if not postures:
                return None
            verdict = self._subscription_posture(ctx, snap, scope, face)
            if verdict is None and ctx.route == COUNT_TOKENS_ROUTE and ctx.governance_overrides.get("pii_masking"):
                # FR-041: bajo enmascarado forzado el conteo no se reenvía ni a la suscripción
                return self._count_response(ctx, ctx.routing_decision["extensions"]["redirect"], forced=True)
            return verdict
        if state == "off" or not ctx.model:
            return None                                   # postura sin redirección: US2 (motor)
        extra = {}
        if published is None:
            if inferred is None:
                return None                               # no es un id publicado: camino normal
            snap = dataclasses.replace(snap, published=tuple(snap.published) + (inferred,))
            if inferred.get("family_tier"):
                extra["tier_inferred"] = inferred["family_tier"]
        try:
            cut = await self._resolve(ctx, snap, scope, face, state, permitidos, extra=extra)
            if cut is None and ctx.route == COUNT_TOKENS_ROUTE:
                cut = self._count_tokens(ctx)
            return cut
        except Exception:  # noqa: BLE001
            if state == "shadow":
                logger.exception("redirect: falla en sombra (el pedido sigue igual)")
                return None
            logger.exception("redirect: falla resolviendo con política on")
            return self._fail_closed(ctx)

    def _access_cut(self, ctx, face, permitidos, governed, *, redirected: bool):
        """Corte por perfil de un modelo del catálogo que no es un id publicado servido por la
        redirección. La pasarela audita el corte con `ctx.routing_decision`. Un modelo que el catálogo
        no conoce no está en `governed` y no se gobierna (límite documentado)."""
        model = ctx.model
        if face is None or redirected or permitidos is None or not model:
            return None
        if model not in governed or model in permitidos:
            return None
        ctx.routing_decision = _access_block(model)
        return _error(face, "model_not_allowed")

    def _store_down(self, ctx, scope, exc):
        last = self.store.last_known(scope.tenant_id)
        logger.error("redirect: no se pudo leer la política (%s)", exc)
        if last is None or last.empty():
            return None
        try:
            was_on = resolver.effective_state(last.policy, scope) == "on"
        except ValueError:
            was_on = True
        if was_on and ROUTE_FACE.get(ctx.route) and ctx.mode == "byok":
            return self._fail_closed(ctx)
        return None

    def _fail_closed(self, ctx):
        face = ROUTE_FACE.get(ctx.route, "openai_generic")
        return _error(face, "policy_unavailable")

    def _posture(self, snap, scope, ident, *, redirected: bool):
        return residency.effective_posture(snap.postures, scope, redirected=redirected,
                                           tenant_region=tenant_region(ident), regions=snap.regions,
                                           relaxations=snap.relaxations)

    @staticmethod
    def _tier_fallback_applies(ctx, face, state) -> bool:
        """Solo un id `claude-*` en la cara Claude con la política encendida y la llave del producto: un modelo de
        la base sigue su camino (FR-002) y la suscripción personal también."""
        return (face == "claude" and state == "on" and ctx.mode == "byok" and bool(ctx.model)
                and str(ctx.model).lower().startswith("claude"))

    @staticmethod
    def _inferred_row(ctx, scope) -> dict:
        """Id publicado «virtual» para el id pedido, con el tier inferido de su nombre (sin tier ⇒ sin regla)."""
        tier = infer_tier(ctx.model)
        return {"id": f"inferred:{tier or 'unknown'}", "tenant_id": scope.tenant_id, "scope_type": "tenant",
                "scope_value": "*", "face": "claude", "public_id": ctx.model, "family_tier": tier,
                "is_family_default": False, "label_mode": "destination"}

    async def _resolve(self, ctx, snap, scope, face, state, permitidos=None, extra=None):
        request_class = ctx.request_headers.get(REQUEST_CLASS_HEADER) if ctx.request_headers else None
        posture = self._posture(snap, scope, ctx.ident, redirected=True)
        res = resolver.resolve(scope=scope, face=face, public_id=ctx.model,
                               request_class=request_class, published_rows=snap.published,
                               rules=snap.rules, destinations=snap.destinations,
                               offers=snap.offers, posture=posture, permitidos=permitidos)
        shadow = state == "shadow"
        decision = _decision(face, ctx.model, res, request_class=request_class, shadow=shadow)
        if posture.default_applied:
            decision["default_posture_applied"] = posture.default_applied    # R23, R28: solo sin postura explícita
        decision.update(extra or {})
        ctx.routing_decision = _audit_block(decision)
        if shadow:
            ctx.state[STATE_KEY] = Plan(face=face, public_id=ctx.model, decision=decision,
                                        shadow=True, scope_label=scope.label())
            return None
        if isinstance(res, resolver.Unavailable):
            if res.error_class == "not_allowed":
                ctx.routing_decision["extensions"].update(_access_block(ctx.model)["extensions"])
                return _error(face, "model_not_allowed")
            return _error(face, "region" if res.error_class == "residency" else "not_available")
        allowed = await run_in_threadpool(self.store.key_allowed_models, (ctx.ident or {}).get("api_key_id"))
        if allowed and ctx.model not in allowed:                  # FR-010a sobre el id público
            decision["unavailable"] = "key_model_not_allowed"
            return _error(face, "not_available")
        dest = res.destination
        cred = await run_in_threadpool(self.store.credential, snap, dest["id"])
        if res.forced_masking:
            # FR-027: el forzado enciende el enmascarado del plano de la pasarela (sin bajar jamás lo que la
            # empresa configuró) y la verificación fail-closed; el guard del motor la exige con `masking_report`
            ctx.governance_overrides.update(pii_masking=True, nlp_fail_mode="block", masking_scope=MASKING_SCOPE_FULL)
            decision["masking_scope"] = MASKING_SCOPE_FULL           # S14: alcance completo (lo verifica el guard)
        ctx.state[STATE_KEY] = Plan(face=face, public_id=ctx.model, decision=decision,
                                    engine_model=res.engine_model, destination=dest, credential=cred,
                                    forced_masking=res.forced_masking, scope_label=scope.label(),
                                    alternatives=res.alternatives, snap=snap, fidelity=res.fidelity)
        return None

    def _count_tokens(self, ctx):
        """T093 de Sentinel (FR-041): a un destino traducido, o con enmascarado forzado vigente (a cualquier
        destino), el conteo no se reenvía: su cuerpo es la conversación entera. Se responde una estimación
        local o 404. A un nativo sin forzado se reenvía (el id sale reescrito por `pre_engine`)."""
        plan: Optional[Plan] = ctx.state.get(STATE_KEY)
        if plan is None or plan.shadow:
            return None
        translated = resolver.fidelity("claude", plan.destination) == "translated"
        if not (translated or plan.forced_masking):
            plan.decision["count_tokens_mode"] = "forwarded"
            return None
        return self._count_response(ctx, plan.decision, forced=plan.forced_masking,
                                    profile=(plan.destination.get("capability_profile") or {}) if translated else None)

    def _count_response(self, ctx, decision: dict, *, forced: bool, profile=None):
        body = ctx.body if isinstance(getattr(ctx, "body", None), dict) else None
        tokens = None
        if body is not None:
            if profile is not None:                      # el destino recibe el cuerpo ya normalizado
                try:
                    body, _ = claude_face.normalize_for_translated(body, profile, max_output=0)
                except claude_face.CapabilityRejected:
                    pass                                 # el conteo no rechaza: se estima el pedido tal cual
            try:
                tokens = self._estimator(body)
            except Exception:  # noqa: BLE001
                logger.exception("redirect: falla estimando count_tokens")
        if tokens is None:
            decision["count_tokens_mode"] = "not_found"
            status = STATUS_REJECTED if forced else STATUS_PASSED
            response = _error("claude", "count_unavailable")
        else:
            decision["count_tokens_mode"] = "estimated"
            status = STATUS_PASSED
            response = JSONResponse({"input_tokens": int(tokens)})
        # la pasarela no audita las respuestas tempranas de `count_tokens`: la fila la escribe el plugin
        self._write_row(ctx, ctx.model or "unknown", status, decision, "count_tokens")
        return response

    def _subscription_foreign(self, ctx, snap, scope, face, state, permitidos):
        """FR-042: con la política encendida, una credencial de suscripción personal no sirve para un
        destino de otro proveedor (la pasarela no la reenvía ni la cambia por la del destino): 401, texto
        neutro, sin nombrar el destino. Un destino del mismo proveedor, o un modelo que ninguna regla
        redirige, sigue su camino."""
        if state != "on" or face != "claude" or not ctx.model:
            return None
        if resolver.find_published(snap.published, scope, face, ctx.model) is None:
            return None
        res = resolver.resolve(scope=scope, face=face, public_id=ctx.model,
                               request_class=(ctx.request_headers or {}).get(REQUEST_CLASS_HEADER),
                               published_rows=snap.published, rules=snap.rules,
                               destinations=snap.destinations, offers=snap.offers,
                               posture=self._posture(snap, scope, ctx.ident, redirected=True),
                               permitidos=permitidos)
        if not isinstance(res, resolver.Resolved) or res.destination.get("provider") == SUBSCRIPTION_PROVIDER_NAME:
            return None
        ctx.routing_decision = _audit_block({"face": face, "path": "subscription", "public_id": ctx.model,
                                             "rejected": "subscription_credential"})
        return _error(face, "auth")

    def _subscription_posture(self, ctx, snap, scope, face):
        posture = self._posture(snap, scope, ctx.ident, redirected=False)
        verdict = residency.evaluate(posture, SUBSCRIPTION_PROVIDER)
        decision = {"face": face, "path": "subscription", "residency_mode": verdict.mode,
                    "jurisdiction_served": verdict.jurisdiction_served,
                    "forced_masking": verdict.forced_masking}
        ctx.routing_decision = _audit_block(decision)
        if not verdict.allowed:
            return _error(face, "region")
        if verdict.forced_masking:
            ctx.governance_overrides.update(pii_masking=True, nlp_fail_mode="block", masking_scope=MASKING_SCOPE_FULL)
            decision["masking_scope"] = MASKING_SCOPE_FULL
        return None

    def _build_models_view(self, ctx, snap, scope, permitidos=None):
        face = generic_face.select_models_view(ctx.request_headers or {})
        rows = resolver.published_models(snap.published, scope, face)
        if not rows:
            return
        posture = self._posture(snap, scope, ctx.ident, redirected=True)
        usable = []
        for row in rows:
            res = resolver.resolve(scope=scope, face=face, public_id=row["public_id"],
                                   request_class="main", published_rows=snap.published,
                                   rules=snap.rules, destinations=snap.destinations,
                                   offers=snap.offers, posture=posture, permitidos=permitidos)
            if isinstance(res, resolver.Resolved):
                usable.append({**row, "destination_name": res.destination.get("name"),
                               "context_window": res.destination.get("context_window"),
                               "without_images": self._missing(face, {"images"}, res.destination,
                                                               res.fidelity) is not None})
        if face == "claude":
            view = claude_face.models_view(usable, now_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                         time.gmtime(self._clock())))
        else:
            view = generic_face.models_view(usable, created=int(self._clock()))
        ctx.state[STATE_KEY + ".models_view"] = view

    # hooks sobre el pedido
    def forward_headers_allowlist(self, ctx):
        plan = ctx.state.get(STATE_KEY)
        if plan and not plan.shadow and plan.face == "claude" and \
                resolver.fidelity("claude", plan.destination) == "native":
            return {"anthropic-beta"}
        return set()

    def pre_engine(self, ctx, body, headers):
        plan: Optional[Plan] = ctx.state.get(STATE_KEY)
        if plan is None or not isinstance(body, dict):
            return body, headers
        headers = {k: v for k, v in headers.items() if k.lower() != authz.HEADER}
        if plan.shadow:
            try:
                token = authz.issue(request_id=str(uuid.uuid4()), scope=plan.scope_label,
                                    destination_id=str(plan.decision.get("shadow_destination_id") or ""),
                                    model=str(body.get("model")), provider="shadow", credential={},
                                    decision=plan.decision)
                headers[authz.HEADER] = token
            except Exception:  # noqa: BLE001 — la sombra jamás afecta el pedido
                logger.warning("redirect: sombra sin firma (¿REDIRECT_INTERNAL_KEY ausente?)")
            return body, headers
        missing = self._select_by_capability(plan, body)
        if missing is not None:
            plan.rejected = missing
            plan.decision["rejected"] = missing
            return {"model": REJECTED_MODEL, "messages": [], "max_tokens": 1}, headers
        dest = plan.destination
        max_output = dest.get("max_output")
        if plan.face == "claude":
            headers = self._apply_betas(ctx, plan, headers)
            out, _ = credentials.strip_client_credentials(dict(body))
            if resolver.fidelity("claude", dest) == "translated":
                try:
                    out, removed = claude_face.normalize_for_translated(
                        out, dest.get("capability_profile") or {}, max_output=max_output or 0,
                        history_reasoning=thinking.history_filter(dest))
                except claude_face.CapabilityRejected as exc:
                    plan.rejected = exc.capability
                    plan.decision["rejected"] = exc.capability
                    out = {"model": REJECTED_MODEL, "messages": [], "max_tokens": 1}
                    return out, headers
                # imágenes/documentos reemplazados por una nota: quedan en la decisión (la de la
                # pasarela comparte el dict; la del motor viaja firmada abajo) — FR-033: escalar
                omitted = [r for r in removed if r in OMITTED_AUDIT]
                if omitted:
                    plan.decision["omitted"] = ",".join(omitted)
                # razonamiento de la historia que se descartó o se reconstruyó (FR-036): solo cantidades
                for label, prefix in (("thinking_dropped", claude_face.THINKING_DROPPED),
                                      ("thinking_replayed", claude_face.THINKING_REPLAYED)):
                    count = claude_face.adjustment_count(removed, prefix)
                    if count:
                        plan.decision[label] = count
                # T139 de Sentinel: campos que la herramienta mandó y el destino no conoce (p. ej.
                # `safeguards`): solo sus nombres, acotados (FR-033, FR-035)
                dropped_fields = claude_face.dropped_field_names(removed)
                if dropped_fields:
                    plan.decision["dropped_fields"] = _names_value(dropped_fields)
            out["model"] = plan.engine_model
        else:
            out, _ = generic_face.prepare_request(body, engine_model=plan.engine_model,
                                                  max_output=max_output)
        # Parámetros que la ficha del destino declara no soportados (069 enmienda): se quitan acá, en las
        # dos caras, y la lista viaja firmada para que el guard del motor haga lo mismo con lo que se cuele.
        drop = tuple(dest.get("unsupported_params") or ())
        dropped = [n for n in drop if n in out]
        for n in dropped:
            out.pop(n)
        if dropped:
            plan.decision["dropped_params"] = ",".join(dropped)       # FR-033: solo nombres, escalar
        headers[authz.HEADER] = authz.issue(
            request_id=str(uuid.uuid4()), scope=plan.scope_label, destination_id=str(dest["id"]),
            model=plan.engine_model, provider=dest["provider"], credential=plan.credential,
            api_base=dest.get("api_base"), forced_masking=plan.forced_masking,
            decision=plan.decision, price=dest.get("price_override"), drop_params=drop,
            provider_options=_signed_provider_options(dest))
        return out, headers

    def _apply_betas(self, ctx, plan: Plan, headers: dict) -> dict:
        """T094 de Sentinel (FR-040): hacia un nativo, `anthropic-beta` por lista permitida; hacia un
        traducido, ninguna. Se decide acá, con el destino final (una sustitución por capacidad puede cambiar
        la fidelidad después de que la pasarela calculó las cabeceras a reenviar)."""
        received = betas.parse((ctx.request_headers or {}).get(betas.HEADER))
        headers = {k: v for k, v in headers.items() if k.lower() != betas.HEADER}
        if not received:
            return headers
        if resolver.fidelity("claude", plan.destination) == "native":
            kept, dropped = betas.split_allowed(received, betas.allowlist())
            if kept:
                headers[betas.HEADER] = ",".join(kept)
        else:
            dropped = len(received)
        if dropped:
            plan.decision["betas_dropped"] = dropped          # FR-033: solo la cantidad
        return headers

    # ── resolución por capacidad (069 FR-008b) ────────────────────────────────
    def _missing(self, face: str, needs, dest: dict, fidelity: str) -> Optional[str]:
        """Primera capacidad que el pedido necesita y el destino no tiene. Un destino nativo de la
        cara la acepta toda; en la cara genérica solo cuenta lo declarado explícitamente falso."""
        profile = dest.get("capability_profile") or {}
        if face == "claude":
            if fidelity != "translated":
                return None
            return next((c for c in sorted(needs) if not profile.get(c, False)), None)
        return generic_face.missing_capability(needs, profile)

    def _select_by_capability(self, plan: Plan, body) -> Optional[str]:
        """Si el pedido adjunta imágenes/PDF y el destino elegido no los tiene, pasa al siguiente destino
        de la regla que sí. Devuelve la capacidad faltante si NINGUNO la tiene (⇒ rechazo)."""
        face_mod = claude_face if plan.face == "claude" else generic_face
        needs = face_mod.current_turn_needs(body)
        if not needs:
            return None
        first_missing = self._missing(plan.face, needs, plan.destination, plan.fidelity)
        if first_missing is None:
            return None
        for alt in plan.alternatives:
            if self._missing(plan.face, needs, alt.destination, alt.fidelity) is None:
                plan.destination, plan.engine_model, plan.fidelity = alt.destination, alt.engine_model, alt.fidelity
                plan.forced_masking = alt.forced_masking
                plan.credential = self.store.credential(plan.snap, alt.destination["id"])
                plan.decision.update(destination_id=alt.destination.get("id"),
                                     destination_name=alt.destination.get("name"),
                                     fidelity=alt.fidelity, residency_mode=alt.residency_mode,
                                     jurisdiction_served=alt.jurisdiction_served,
                                     substitution_reason="capability")
                # en el lugar: `ctx.routing_decision` comparte este dict y lo que se agrega después
                # (`omitted`, `dropped_fields`, `betas_dropped`) tiene que llegar a la auditoría
                plan.decision.update({k: str(v) for k, v in plan.decision.items()
                                      if v is not None and not isinstance(v, (bool, int, float, str))})
                plan.alternatives = ()
                return None
        return first_missing

    def wrap_stream(self, ctx, iterator):
        plan: Optional[Plan] = ctx.state.get(STATE_KEY)
        if plan is None or plan.shadow or plan.rejected:
            return iterator
        signer = None
        if plan.face == "claude" and resolver.fidelity("claude", plan.destination) == "translated":
            dest_id = str(plan.destination.get("id"))
            signer = lambda text: thinking.sign(dest_id, text)             # noqa: E731 — FR-036
        return stream.wrap_sse(iterator, public_model=plan.public_id,
                               face="claude" if plan.face == "claude" else "openai",
                               ping_after=self.ping_after, thinking_signer=signer)

    def map_response(self, ctx, status, content):
        plan: Optional[Plan] = ctx.state.get(STATE_KEY)
        if plan is None or plan.shadow:
            return None
        try:
            body = json.loads(content)
        except (ValueError, TypeError):
            return None
        if not isinstance(body, dict) or "model" not in body:
            return None
        body = generic_face.rewrite_response_model(body, plan.public_id)
        if plan.face == "claude" and body.get("type") == "message":
            body["usage"] = stream.complete_usage(body.get("usage"))      # FR-039: los cuatro contadores
            if resolver.fidelity("claude", plan.destination) == "translated":
                dest_id = str(plan.destination.get("id"))
                for blk in body.get("content") if isinstance(body.get("content"), list) else ():
                    if isinstance(blk, dict) and blk.get("type") == "thinking":
                        blk["signature"] = thinking.sign(dest_id, str(blk.get("thinking") or ""))   # FR-036
        return status, json.dumps(body, ensure_ascii=False).encode(), None

    def map_error(self, ctx, status, content):
        plan: Optional[Plan] = ctx.state.get(STATE_KEY)
        if plan is None or plan.shadow:
            return None
        if plan.rejected:
            self._audit_rejection(ctx, plan)
            return _error_bytes(plan.face, "capability", capability=plan.rejected)
        kind = guard_rejection_kind(content)
        if kind is not None:
            return _error_bytes(plan.face, kind)
        return _error_bytes(plan.face, claude_face.map_upstream_status(int(status)))


gateway_plugin = RedirectPlugin()
