"""Guard de destinos redirigidos para el motor (LiteLLM 1.92.0; research D15/D16/D18, R13).

Declarado en el fragmento de perfil como `pre_call`, `default_on`, **después** del guardrail de
la base (así ve su `masking_report`). Para modelos `rdx-*`:

1. exige la autorización interna (`x-redirect-authz`) válida y para ese mismo modelo — rige
   aunque la política esté apagada (FR-006a);
2. anti-desvío: borra todo campo de credencial/destino del cliente y fija los del destino
   (resolviendo `env:` desde el entorno del motor);
3. si la autorización pide enmascarado forzado, exige `masking_report` completo, no degradado y
   con detectadas == enmascaradas; si no, bloquea (FR-016);
4. escribe la decisión con `mark_routing_decision` de la librería de política del motor
   (costura S7: `EngineRoutingDecision`, la única forma que el logger de auditoría acepta como
   confiable) bajo `extensions.redirect`, solo claves y valores escalares cortos; lo que el
   cliente haya sembrado bajo la misma clave se descarta;
5. fija el control de caché de respuestas del motor (FR-034, research D11): la clave de LiteLLM no
   incluye credencial, base ni alcance, así que el guard le suma un `namespace` que liga alcance +
   destino; y si el pedido llevó mapa de enmascarado (o no hay garantía de que no lo llevó) la caché se
   salta en lectura y escritura — la respuesta traería marcadores de OTRO pedido;
6. quita la cabecera interna de lo que el motor registra o reenvía.

Modelos no `rdx-*`: no se tocan, salvo que traigan una autorización válida **para ese mismo
modelo** (modo sombra: la pasarela firma la decisión hipotética sin cambiar el destino); en ese
caso solo se registra la decisión. Una autorización inválida en un modelo no `rdx-*` se ignora.

El metadata-home es el mismo que usa el guardrail de la base (`litellm_metadata` en las rutas
donde `metadata` es un campo que recibe el proveedor): ahí lee `masking_report` (S5b) y ahí
escribe la decisión — nunca en un campo que viaje al destino.

Importa sus hermanos tanto desde el paquete (`sentinel.engine.*`) como copiado plano al
directorio de extensiones del motor (`extensions.redirect_guard`, S9).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Mapping, Optional

try:  # paquete (pasarela, tests)
    from sentinel.engine import redirect_authz as authz
    from sentinel.engine import redirect_credentials as credentials
except ImportError:  # copiado plano junto a sus hermanos
    try:
        from . import redirect_authz as authz  # type: ignore[no-redef]
        from . import redirect_credentials as credentials  # type: ignore[no-redef]
    except ImportError:
        import redirect_authz as authz  # type: ignore[no-redef]
        import redirect_credentials as credentials  # type: ignore[no-redef]

try:  # librería de política del motor (S7); en el motor: `extensions.sentinel_guardian_policy`
    from extensions import sentinel_guardian_policy as _gpolicy  # type: ignore
except ImportError:
    try:
        import sentinel_guardian_policy as _gpolicy  # type: ignore[no-redef]
    except ImportError:  # fuera del motor: la decisión se escribe sin marca de confianza
        _gpolicy = None

try:
    from litellm.integrations.custom_guardrail import CustomGuardrail
except ImportError:  # fuera del motor (tests de lógica pura sin litellm)
    class CustomGuardrail:  # type: ignore[no-redef]
        def __init__(self, **kwargs):
            self.guardrail_name = kwargs.get("guardrail_name")

RDX_PREFIX = "rdx-"
DECISION_KEY = "_internal_routing_decision"
MASKING_REPORT_KEY = "masking_report"
_METADATA_KEYS = ("metadata", "litellm_metadata")
DECISION_NAMESPACE = "redirect"
CACHE_FIELD = "cache"                    # control de caché por pedido de LiteLLM (`DynamicCacheControl`)
CACHE_NAMESPACE_PREFIX = "rdx:"
CACHE_BYPASS = {"no-cache": True, "no-store": True}
# rutas donde `metadata` es un campo del body que recibe el proveedor (mismo criterio que
# `_metadata_home` del guardrail de la base)
_LITELLM_METADATA_CALL_TYPES = frozenset({"anthropic_messages", "aresponses", "responses"})
_SCALAR_KEY = re.compile(r"^[a-z0-9_]{1,32}$")
_MAX_STR = 128


class GuardRejection(Exception):
    """Rechazo con texto neutro apto para devolver al cliente."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(code)
        self.status, self.code, self.message = status, code, message


def _is_rejection(exc: BaseException) -> bool:
    """¿Es un rechazo del guard, aunque venga de otra instancia del módulo? (`status`, `code`, `message`)."""
    if isinstance(exc, GuardRejection):
        return True
    return (type(exc).__name__ == "GuardRejection" and isinstance(getattr(exc, "status", None), int)
            and isinstance(getattr(exc, "code", None), str) and isinstance(getattr(exc, "message", None), str))


def is_redirect_model(model: Any) -> bool:
    return isinstance(model, str) and model.startswith(RDX_PREFIX)


def _headers_of(data: Mapping[str, Any]) -> dict:
    psr = data.get("proxy_server_request") or {}
    hdrs = psr.get("headers") or {}
    return {str(k).lower(): v for k, v in hdrs.items()} if isinstance(hdrs, Mapping) else {}


def _scrub_internal_header(data: dict) -> None:
    """La autorización interna no debe quedar en logs ni reenviarse al destino."""
    containers = [(data.get("proxy_server_request") or {}).get("headers")]
    containers += [(data.get(k) or {}).get("headers") for k in _METADATA_KEYS if isinstance(data.get(k), dict)]
    for hdrs in containers:
        if isinstance(hdrs, dict):
            for k in [k for k in hdrs if str(k).lower() == authz.HEADER]:
                hdrs.pop(k)


FULL_SCOPE = "full"


def masking_ok(report: Any, *, forced: bool = False) -> bool:
    """¿El informe del guardrail de la base (S5b) garantiza el enmascarado? Completo, no degradado y con todo lo
    detectado enmascarado. Con el forzado vigente (`forced`, 057 S14; QA B3) además exige **alcance completo**
    (`scope == "full"`) y nada no analizable (`unanalyzable == 0`): un informe sin esos campos (un guardrail
    anterior a S14) no prueba que se hayan enmascarado `system`, herramientas ni adjuntos, así que bloquea."""
    if not isinstance(report, Mapping):
        return False
    try:
        ok = (report.get("completed") is True and report.get("degraded") is False
              and int(report.get("detected")) == int(report.get("masked")))
        if ok and forced:
            unanalyzable = report.get("unanalyzable")
            ok = (report.get("scope") == FULL_SCOPE and not isinstance(unanalyzable, bool)
                  and int(unanalyzable) == 0)
        return ok
    except (TypeError, ValueError):
        return False


def _no_masking_map(report: Any) -> bool:
    """¿Hay garantía de que el pedido NO lleva mapa de enmascarado? Solo con un informe completo, no
    degradado, sin entidades detectadas ni enmascaradas. Todo lo demás (informe ausente, ilegible, con
    conteos que no cierran) se trata como «con mapa»: ante la duda no se cachea."""
    if not masking_ok(report):
        return False
    try:
        return int(report.get("masked")) == 0
    except (TypeError, ValueError):
        return False


def cache_control(grant: authz.Grant, report: Any) -> dict:
    """Control de caché del motor para un pedido redirigido (FR-034). Sin mapa de enmascarado, la
    respuesta solo se comparte entre pedidos del mismo alcance y destino: el `namespace` es un hash
    (sin ids ni secretos) de alcance, destino, modelo, proveedor y base — los dos últimos para que un
    destino editado en sitio no herede respuestas de su versión anterior."""
    if not _no_masking_map(report):
        return dict(CACHE_BYPASS)
    material = json.dumps([grant.scope, grant.destination_id, grant.model, grant.provider, grant.api_base],
                          separators=(",", ":"), ensure_ascii=True)
    return {"namespace": CACHE_NAMESPACE_PREFIX + hashlib.sha256(material.encode()).hexdigest()[:32]}


def _home_key(data: Mapping[str, Any], call_type: Optional[str]) -> str:
    if call_type in _LITELLM_METADATA_CALL_TYPES or "litellm_metadata" in data:
        return "litellm_metadata"
    return "metadata"


def _home(data: dict, call_type: Optional[str]) -> dict:
    key = _home_key(data, call_type)
    home = data.get(key)
    if not isinstance(home, dict):
        home = {}
        data[key] = home
    return home


def _masking_report(data: Mapping[str, Any], call_type: Optional[str] = None):
    """Solo del home que escribe el guardrail de la base: un `masking_report` sembrado por el
    cliente en el otro campo no cuenta."""
    md = data.get(_home_key(data, call_type))
    return md.get(MASKING_REPORT_KEY) if isinstance(md, Mapping) else None


def _scalars(decision: Mapping[str, Any]) -> dict:
    """Forma que acepta `extensions` en el plano interno: claves `[a-z0-9_]{1,32}`, valores
    str ≤128, int, float, bool o null."""
    out = {}
    for k, v in decision.items():
        if not (isinstance(k, str) and _SCALAR_KEY.match(k)):
            continue
        if isinstance(v, str):
            out[k] = v[:_MAX_STR]
        elif v is None or isinstance(v, (bool, int, float)):
            out[k] = v
    return out


# Entrada de `applied_layers` que suma la redirección. `model_redirect` no es una capa del registry
# de gobernanza (no se enciende por perfil): el plano interno la acepta por
# `sentinel_governance.ATTRIBUTION_EXTRA_LAYERS`. `allow`: el guard dejó pasar el pedido, ya
# resuelto y con su protección verificada (el enmascarado forzado se audita en la decisión).
REDIRECT_LAYER = {"layer_code": "model_redirect", "status": "applied", "decision": "allow"}


def _write_decision(data: dict, call_type: Optional[str], decision: Mapping[str, Any]) -> dict:
    """Marca la decisión en el home (sobrescribe la del cliente, en ambos campos) conservando
    una decisión confiable previa del motor (p. ej. del auto-router) y sumando la nuestra bajo
    `extensions.redirect`."""
    for k in _METADATA_KEYS:
        md = data.get(k)
        if isinstance(md, dict) and DECISION_KEY in md and not (
                _gpolicy is not None and isinstance(md[DECISION_KEY], _gpolicy.EngineRoutingDecision)):
            md.pop(DECISION_KEY)
    home = _home(data, call_type)
    previous = None
    if _gpolicy is not None:
        previous = _gpolicy.trusted_routing_decision(home)
    merged = dict(previous or {})
    ext = dict(merged.get("extensions") or {})
    ext[DECISION_NAMESPACE] = _scalars(decision)
    merged["extensions"] = ext
    if _gpolicy is not None:
        _gpolicy.mark_routing_decision(home, merged)
        # La redirección es una capa que se aplicó a ESTE pedido (069 T070): se suma a la
        # atribución confiable sin pisar lo que marcó el guardrail. Una decisión en sombra no
        # cambió el destino, así que no cuenta como aplicada.
        if not decision.get("shadow") and hasattr(_gpolicy, "mark_attribution"):
            _gpolicy.mark_attribution(home, extra_layers=[dict(REDIRECT_LAYER)])
    else:
        home[DECISION_KEY] = merged
    return merged


def _shadow_decision(data: dict, token: Any, call_type: Optional[str], key, now) -> None:
    """Modelo no `rdx-*` con autorización: solo vale si es para ESTE modelo (sombra)."""
    try:
        grant = authz.verify(token, expected_model=data.get("model"), key=key, now=now)
    except authz.AuthzError:
        return
    decision = dict(grant.decision)
    decision.update({"request_id": grant.request_id, "shadow": True})
    _write_decision(data, call_type, decision)


OPENROUTER = "openrouter"
OPENROUTER_ZDR_KEY = "openrouter_zdr"
# Claves del cuerpo que un cliente usaría para enrutar a otros proveedores o modelos de OpenRouter
_OPENROUTER_CLIENT_ROUTING = ("provider", "route", "models")


def apply_openrouter_prefs(data: dict, grant: authz.Grant) -> None:
    """FR-032 (research R19): todo pedido a OpenRouter sale con cero retención, sin recolección de datos y solo a la
    lista de proveedores permitidos de la entrada (`only`), sea lo que sea que mande el cliente. Sin lista, el pedido
    no se sirve. Nombres de campo según la referencia de «Provider Routing» de OpenRouter (`zdr`, `data_collection`,
    `only`); LiteLLM los pasa por `extra_body`."""
    allow = [str(p).strip() for p in (grant.provider_options or {}).get("providers_allowlist") or ()
             if isinstance(p, str) and p.strip()]
    if not allow:
        raise GuardRejection(503, "destination_misconfigured", "Modelo no disponible temporalmente.")
    for k in _OPENROUTER_CLIENT_ROUTING:
        data.pop(k, None)
    extra = data.get("extra_body")
    extra = {k: v for k, v in extra.items() if k not in _OPENROUTER_CLIENT_ROUTING} if isinstance(extra, dict) else {}
    extra["provider"] = {"only": allow, "data_collection": "deny", "zdr": True}
    data["extra_body"] = extra


DROPPED_KEY = "dropped_params"


def strip_unsupported(data: dict, names) -> list:
    """Quita de la raíz del pedido los parámetros que la ficha del destino declara no soportados (069
    enmienda). Devuelve los nombres que el pedido SÍ traía, en el orden de la ficha: solo eso se audita
    (nunca el valor). Funciona igual para todos los tipos de llamada: el campo está en la raíz del cuerpo
    en chat, Responses y `anthropic_messages`, y `additional_drop_params` del motor no alcanza a la ruta
    nativa de Anthropic (litellm 1.92.0, `messages/utils.py`), así que no se depende de él."""
    dropped = []
    for name in names or ():
        if name in data:
            data.pop(name)
            dropped.append(name)
    return dropped


def _merge_dropped(decision: dict, dropped: list) -> None:
    """Suma lo quitado ahora a lo que la pasarela ya había quitado (misma clave, sin repetir)."""
    prev = [n for n in str(decision.get(DROPPED_KEY) or "").split(",") if n]
    merged = prev + [n for n in dropped if n not in prev]
    if merged:
        decision[DROPPED_KEY] = ",".join(merged)


ADJUSTED_KEY = "adjusted_params"
# Piso de tokens de salida por proveedor (069 T183). OpenAI y Azure OpenAI atienden por Responses, que rechaza
# `max_output_tokens < 16` con 400; Claude Desktop sondea con `max_tokens: 1`. Constante por proveedor, no campo
# de la ficha: un campo `min_output_tokens` exigiría migración, API y firma de la autorización (deuda en T183).
MIN_OUTPUT_TOKENS = {"openai": 16, "azure": 16}
COMPLETION_TOKENS_PROVIDERS = ("openai", "azure")
# Caras donde `max_tokens` es el campo propio del protocolo (Anthropic Messages) y el motor lo traduce solo: no se renombra.
KEEP_MAX_TOKENS_CALL_TYPES = ("anthropic_messages", "responses", "aresponses")
OUTPUT_TOKEN_PARAMS = ("max_tokens", "max_completion_tokens", "max_output_tokens")


def raise_min_output_tokens(data: dict, provider: Any, call_type: Optional[str] = None) -> list:
    """Sube al piso del proveedor los límites de salida que el pedido trae POR DEBAJO de él (no los quita ni
    agrega los ausentes). Devuelve los nombres ajustados (solo eso se audita, nunca el valor). Único punto de
    paso: lo usan la redirección (`apply_redirect`) y la ruta directa del catálogo (`redirect_catalog`)."""
    floor = MIN_OUTPUT_TOKENS.get(provider)
    adjusted = []
    if provider in COMPLETION_TOKENS_PROVIDERS and call_type not in KEEP_MAX_TOKENS_CALL_TYPES and "max_tokens" in data:
        # T192: los modelos nuevos de OpenAI por /chat/completions solo aceptan `max_completion_tokens` (400 si llega
        # `max_tokens`). Con los dos manda el que ya es válido; se quita el viejo.
        if data.get("max_completion_tokens") is None:
            data["max_completion_tokens"] = data.pop("max_tokens")
            adjusted.append("max_tokens->max_completion_tokens")
        else:
            data.pop("max_tokens")
            adjusted.append("max_tokens")
    for name in OUTPUT_TOKEN_PARAMS if floor else ():
        v = data.get(name)
        if isinstance(v, int) and not isinstance(v, bool) and v < floor:
            data[name] = floor
            adjusted.append(name)
    return adjusted


def _engine_cost_map() -> Mapping[str, Any]:
    try:
        import litellm
        return litellm.model_cost or {}
    except Exception:  # noqa: BLE001 — sin mapa, el pedido sigue sin precio (queda marcado)
        return {}


def apply_redirect(data: dict, *, environ: Optional[Mapping[str, str]] = None,
                   key: Optional[str] = None, now: Optional[float] = None,
                   call_type: Optional[str] = None,
                   cost_map: Optional[Mapping[str, Any]] = None) -> dict:
    """Lógica pura del guard. Muta y devuelve `data`; lanza `GuardRejection`."""
    model = data.get("model")
    token = _headers_of(data).get(authz.HEADER)
    if not is_redirect_model(model):
        if token:
            _scrub_internal_header(data)
            _shadow_decision(data, token, call_type, key, now)
        return data
    environ = os.environ if environ is None else environ
    _scrub_internal_header(data)
    if not token:
        raise GuardRejection(403, "authz_missing", authz.AuthzError.public_message)
    try:
        grant = authz.verify(token, expected_model=model, key=key, now=now)
    except authz.AuthzKeyMissing:
        raise GuardRejection(503, "authz_key_missing", authz.AuthzKeyMissing.public_message) from None
    except authz.AuthzError as e:
        raise GuardRejection(403, e.code, authz.AuthzError.public_message) from None
    parts = credentials.split_family_model(model)
    if parts is None or credentials.PROVIDER_FAMILY.get(grant.provider) != parts[0]:
        raise GuardRejection(403, "family_mismatch", authz.AuthzError.public_message)

    if grant.forced_masking and not masking_ok(_masking_report(data, call_type), forced=True):
        raise GuardRejection(403, "masking_required",
                             "El pedido no pudo protegerse para este destino y fue bloqueado.")

    for k in credentials.CLIENT_CREDENTIAL_FIELDS:
        data.pop(k, None)
    if "headers" in data:
        fwd = credentials.filter_forward_headers(data.get("headers"))
        if fwd:
            data["headers"] = fwd
        else:
            data.pop("headers")
    # Lo marcado «no soportado» se quita PRIMERO, del pedido del cliente: lo que el guard escribe después
    # (credencial, costo) no puede ser alcanzado por la lista (H1 del QA del PR #78).
    dropped = strip_unsupported(data, grant.drop_params)
    adjusted = raise_min_output_tokens(data, grant.provider, call_type)
    try:
        cred = credentials.resolve_env_refs(grant.credential, environ)
        data.update(credentials.to_litellm_params(grant.provider, cred, grant.api_base))
    except credentials.CredentialError:
        raise GuardRejection(503, "destination_misconfigured",
                             "Modelo no disponible temporalmente.") from None
    # La caché se decide con el informe del guardrail de la base; lo que mande el cliente en `cache`
    # (namespace, ttl, s-maxage, use-cache…) se reemplaza entero.
    if grant.provider == OPENROUTER:
        apply_openrouter_prefs(data, grant)
    data[CACHE_FIELD] = cache_control(grant, _masking_report(data, call_type))
    pricing, pricing_source = credentials.cost_params(
        grant.price, grant.provider, parts[1], _engine_cost_map() if cost_map is None else cost_map)
    data.update(pricing)

    decision = dict(grant.decision)
    _merge_dropped(decision, dropped)
    if adjusted:
        decision[ADJUSTED_KEY] = ",".join(adjusted)
    if grant.provider == OPENROUTER:
        decision[OPENROUTER_ZDR_KEY] = True
    decision.update({"destination_id": grant.destination_id, "request_id": grant.request_id,
                     "scope": grant.scope, "forced_masking": grant.forced_masking,
                     "masking_verified": bool(grant.forced_masking), "pricing": pricing_source})
    if grant.forced_masking:
        decision["masking_scope"] = FULL_SCOPE            # verificado arriba: el informe lo dice y el guard lo exigió
    _write_decision(data, call_type, decision)
    return data


def strip_client_decision(data: dict) -> None:
    """Un valor de `_internal_routing_decision` que no escribió código del motor no vale nada
    (una `EngineRoutingDecision` del auto-router, sí: se conserva)."""
    for k in _METADATA_KEYS:
        md = data.get(k)
        if isinstance(md, dict) and DECISION_KEY in md and not (
                _gpolicy is not None and isinstance(md[DECISION_KEY], _gpolicy.EngineRoutingDecision)):
            md.pop(DECISION_KEY)


class RedirectGuard(CustomGuardrail):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._catalog = None

    def _catalog_direct(self):
        """Resolución por catálogo para clientes directos (069 T033). Perezoso: el módulo hermano
        solo se importa si hay con qué hablar (URL del plano interno)."""
        if self._catalog is None:
            try:
                from sentinel.engine import redirect_catalog as mod
            except ImportError:
                try:
                    from . import redirect_catalog as mod  # type: ignore[no-redef]
                except ImportError:
                    import redirect_catalog as mod  # type: ignore[no-redef]
            self._catalog = mod.CatalogDirect()
        return self._catalog

    def should_run_guardrail(self, data, event_type) -> bool:
        # No es opcional: ni la metadata de la llave/equipo (`disable_global_guardrails`,
        # `opted_out_global_guardrails`) puede apagarlo en pre_call — sin él, un `rdx-*` saldría
        # con las credenciales de entorno del motor.
        if getattr(event_type, "value", event_type) == "pre_call":
            return True
        return super().should_run_guardrail(data, event_type)

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        strip_client_decision(data)
        try:
            if not is_redirect_model(data.get("model")) and \
                    await self._catalog_direct().apply(data, user_api_key_dict, call_type=call_type):
                return data
            return apply_redirect(data, call_type=call_type)
        except Exception as e:  # noqa: BLE001
            # Dentro del motor, `redirect_catalog` y `redirect_guard` pueden cargarse como módulos DISTINTOS
            # (nombre plano vs `extensions.`), y la `GuardRejection` del catálogo no es entonces la clase de
            # este módulo: `except GuardRejection` no la atrapaba y el pedido salía 500 (reintentable) en vez
            # de 403/400/503 (hallazgo en nix, 2-oct). Se reconoce por forma, no por identidad de clase.
            if not _is_rejection(e):
                raise
            from fastapi import HTTPException
            raise HTTPException(status_code=e.status, detail={"error": e.message, "code": e.code}) from None
