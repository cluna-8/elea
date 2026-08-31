"""Superficie browser-DLP (spec 019 US3): endpoints que consume la extensión MV3.

La extensión ``Sentinel Guard`` (portada de ``sentinel-browser-dlp/``) hookea ``window.fetch``
en ChatGPT/Claude web y, por cada prompt, llama a estos endpoints del gateway:

- ``GET  /gw/whoami``  → valida la virtual key → identidad (login del popup). **Fail-closed**.
- ``POST /gw/inspect`` → aplica la política Sentinel al texto plano del usuario y devuelve los
  ``replacements`` (token→original) para que la extensión reescriba el body (el modelo
  ve placeholders) y des-enmascare en el DOM. Empuja al MISMO monitor (``surface="browser"``)
  y audita **metadata-only** (Constraint C1).

**Reuso (Principio VI):** identidad, monitor y audit se reusan del ``gateway`` (014);
el masking reusa la **misma** ``sentinel_guardian_policy`` que el resto (regex hoy; Presidio
real llega en 016). Así la extensión y las rutas base_url comparten una sola política.

**Fix P4 (spec 027 T028): esta superficie corría MEDIO piso.** Hasta la 027, ``gw_inspect``
enmascaraba pero **no** evaluaba AI-Act ni bloqueaba secretos: era el contraejemplo del
piso no negociable dentro del propio producto —una API key pegada en ChatGPT salía en
claro, y una práctica prohibida pasaba sin evaluar, mientras la misma organización tenía
las dos capas activas en las coding tools—. Ahora el endpoint pasa por el **mismo
``Profile``** y la **misma** ``evaluate_request_policy`` que el passthrough: mismo orden
(AI-Act → secretos → detección PII → enmascarado si el perfil lo tiene on), misma
atribución (``applied_layers``/``blocked_by_layer``).

**Consecuencia de contrato**: la extensión **empieza a recibir bloqueos**, y el bloqueo
responde ``ok: false`` (más ``blocked``/``blocked_by_layer``/``motivo``). El ``ok:false``
es **load-bearing, no cosmética**: la MV3 ya desplegada solo tiene fail-closed sobre
``!res.ok`` (el fail-closed del hook de ``window.fetch`` en ``extension/guardia-main.js``); un bloqueo con ``ok:true`` y
``replacements: []`` haría que una extensión vieja mandara el texto ORIGINAL en claro al
proveedor — fail-open por skew de versiones, exactamente lo que un firewall no puede
permitirse. Con ``ok:false`` las extensiones viejas bloquean por su propio fail-closed
(mostrando su error genérico) y las nuevas podrán distinguir ``blocked`` y mostrar
``motivo``.
"""
import time
from typing import Optional

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse

from . import gateway  # reuse: _resolve_attribution (fail-closed check), _audit, _publish_monitor, policy
from ..licensing.degraded import require_not_hard_blocked
from ..services.governance_catalog import (
    GOVERNANCE_LAYERS,
    LAYER_KEYS,
    ROUTE_GATEWAY_PASSTHROUGH,
    SURFACES,
)
from ..services.governance_status import _PISO_SIGUE

# Bloqueo total de licencia (spec 021 US4, FR-020): whoami/inspect SON el
# servicio DLP de la extensión — bajo hard block se cortan como el resto de /gw.
router = APIRouter(prefix="/gw", tags=["Browser-DLP (extensión MV3)"],
                   dependencies=[Depends(require_not_hard_blocked)])

# ── Catálogo CERRADO de motivos de bloqueo (contrato api-gobernanza, garantía (f)) ──
#
# El `motivo` que ve el usuario en el navegador sale SOLO de acá: nunca del `block_reason`
# de la política —que enumera los tipos de secreto detectados— ni del texto inspeccionado
# (C1), ni con nombres de proveedor externo (Constitución VII). Un catálogo cerrado hace
# que ese texto no tenga por dónde llegar a la pantalla del usuario ni al DOM de un sitio
# de terceros, que es donde termina cualquier string que devolvamos acá.
_MOTIVO_POR_CAPA = {
    "ai_act_evaluation": (
        "El contenido corresponde a una práctica prohibida por la normativa de IA "
        "aplicable, así que no se envía al modelo."
    ),
    "secret_detection": (
        "Se detectó material secreto (credenciales) en el contenido. Las credenciales "
        "nunca deben enviarse a un modelo, así que el envío se bloqueó."
    ),
}
_MOTIVO_GENERICO = ("El envío fue bloqueado por una capa de gobernanza de la organización "
                    "y no se envió al modelo.")


def _motivo(blocked_by_layer: Optional[str]) -> str:
    """Copy del catálogo cerrado. Una capa sin copy propio cae al genérico — jamás se
    fabrica un texto con datos del pedido para "explicar mejor"."""
    return _MOTIVO_POR_CAPA.get(blocked_by_layer or "", _MOTIVO_GENERICO)


def _fail_closed():
    return JSONResponse(status_code=401,
                        content={"ok": False, "error": "API key requerida o inválida"})


# ── Superficie del pedido: vocabulario CERRADO, nunca el texto libre del cliente ──────
#
# **Hallazgo (verificación adversarial US2, MEDIA): `tool` es texto libre del cliente y
# contaminaba la auditoría.** El `tool` del body lo manda la extensión —es decir, la
# página— y viajaba CRUDO hasta el argumento `model` de ``gateway._audit``, o sea hasta la
# columna ``audit_logs.model``, y hasta el evento del monitor. Dos consecuencias, las dos
# malas:
#
#   1. **Reporte falsificable**: el agregado de cobertura de analytics excluye
#      ``model <> 'license'`` (los eslabones de hash-chain de la 021 no son tráfico, spec
#      021). Un usuario que mandara ``{"text": "…", "tool": "license"}`` quedaba auditado
#      pero DESAPARECÍA del panel: podía esconderse del reporte eligiendo la etiqueta de su
#      propio tráfico. Un firewall cuyo reporte de cobertura lo escribe el inspeccionado no
#      es un reporte.
#   2. **C1**: texto libre del cliente dentro de una estructura auditada — la misma regla
#      que prohíbe el `detail` en ``applied_layers`` (contrato del evento §2).
#
# La superficie se resuelve entonces contra un vocabulario cerrado, en el mismo orden de
# confianza que usa el resolutor (D5): primero el ``tool_type`` de la Connection —dato del
# admin, la señal que da ``surface_trusted=True``—; después el valor del body **solo si
# coincide exactamente con el enum canónico**; y si no, un centinela explícito.
#
# El centinela dice "no lo sabemos", que es la verdad. Lo que ya no puede pasar es que el
# cliente elija cómo se llama su tráfico en una columna que alimenta reportes: el codominio
# de esta función es finito y todos sus valores se cuentan.
#
# La señal de User-Agent (``policy.detect_tool``) queda FUERA a propósito: además de ser
# spoofeable por el cliente (D5, la razón por la que nunca relaja nada), devuelve etiquetas
# de display ("Claude Code", "Desconocido") que no pertenecen al enum canónico — mezclarlas
# en la columna auditada es una tercera taxonomía de superficie conviviendo, justo lo que
# D5 documenta como origen del problema.
_SUPERFICIE_DESCONOCIDA = "desconocido"
_SURFACES_POR_TOKEN = {s.casefold(): s for s in SURFACES}


def _superficie(ident: dict, tool_declarado) -> str:
    """Superficie canónica del pedido para auditoría y monitor. Devuelve SIEMPRE un valor
    del enum ``SURFACES`` o el centinela — nunca lo que mandó el cliente."""
    de_la_connection = ident.get("tool_type")
    if isinstance(de_la_connection, str):
        canonico = _SURFACES_POR_TOKEN.get(de_la_connection.strip().casefold())
        if canonico:
            return canonico
    if isinstance(tool_declarado, str):
        # Señal no confiable: se acepta solo por pertenencia al enum, y lo que se propaga es
        # el token canónico del registry, no el string recibido.
        canonico = _SURFACES_POR_TOKEN.get(tool_declarado.strip().casefold())
        if canonico:
            return canonico
    return _SUPERFICIE_DESCONOCIDA


# ── Bloque `proteccion` de whoami (US4 — chip de honestidad) ──────────────────────
#
# La extensión lo consume para pintar un chip ámbar "cobertura parcial"; NO lo hardcodea
# (fuente única de copy, contrato whoami-proteccion). Todo el vocabulario es CERRADO y sin
# un solo nombre de motor/tecnología (C1 / Constitución VII): "patrones"/"linguistico",
# jamás "regex"/"presidio"/nombre de proveedor.

# `deteccion`: regla del contrato — plano gateway + `pii_detection` sin servicio propio
# (`requires_service is None`) ⇒ "patrones". Hoy NINGUNA capa del catálogo declara
# `requires_service` (governance_status.confirmed_services está vacío), así que esta
# superficie siempre detecta por patrones. No se computa dinámico a propósito: el día que la
# 016 declare el sidecar NLP y esta capa pase a "linguistico", HAY QUE sumar el `detalle`
# correspondiente (hoy sólo existe el de patrones) — un flip silencioso dejaría `deteccion`
# y `detalle` contándose historias distintas.
_PROTECCION_DETECCION = "patrones"
_PROTECCION_TITULO = "Detección por patrones"

# `detalle`: prosa llana + el literal `_PISO_SIGUE` (importado de governance_status, no
# copiado). El contract test verifica `detalle.endswith(_PISO_SIGUE)`.
_PROTECCION_DETALLE = (
    "En esta superficie la detección de datos personales funciona por patrones conocidos "
    "—correo, teléfono, documentos de identidad, credenciales—. No usa análisis lingüístico: "
    "puede no reconocer nombres de persona o direcciones escritos en texto libre. "
    + _PISO_SIGUE)

# `capas_delegadas`: las capas que en modo suscripción aporta el extremo upstream (FR-013).
# Se DERIVA del registry (única fuente de verdad), no se lista a mano: una capa es delegable
# en suscripción exactamente cuando `delegable_to_upstream` es True —la MISMA condición que
# usa ``compute_layer_state`` para reportar ``ESTADO_DELEGADA``—. Hoy: content_moderation,
# prompt_injection. Sumar una capa delegable nueva actualiza el chip sin tocar este router.
_PROTECCION_CAPAS_DELEGADAS = tuple(
    k for k in LAYER_KEYS if GOVERNANCE_LAYERS[k].delegable_to_upstream)


@router.get("/whoami")
def gw_whoami(x_sentinel_key: Optional[str] = Header(None, alias="X-Sentinel-Key")):
    """Valida la key → identidad para el login del popup. Fail-closed (SC-005).

    Devuelve además el bloque `proteccion` (US4): copy server-side para el chip de
    honestidad de la extensión (vocabulario cerrado, sin nombres de motor)."""
    ident = gateway._resolve_attribution(x_sentinel_key)
    if ident["api_key_id"] is None:
        return _fail_closed()
    return {
        "ok": True,
        "user": ident.get("client_username") or "—",
        "team": ident.get("group_name") or "—",
        "key_label": ident.get("key_label") or "—",
        "proteccion": {
            "deteccion": _PROTECCION_DETECCION,
            "titulo": _PROTECCION_TITULO,
            "detalle": _PROTECCION_DETALLE,
            "capas_delegadas": list(_PROTECCION_CAPAS_DELEGADAS),
        },
    }


@router.post("/inspect")
async def gw_inspect(body: dict,
                     x_sentinel_key: Optional[str] = Header(None, alias="X-Sentinel-Key")):
    """Aplica la política Sentinel a un prompt de la superficie browser (piso COMPLETO desde
    la 027) y devuelve el texto enmascarado + los ``replacements`` para la extensión.
    Fail-closed sin key válida → 401. Empuja al monitor (surface=browser) + audita."""
    start = time.time()
    ident = gateway._resolve_attribution(x_sentinel_key)
    if ident["api_key_id"] is None:
        return _fail_closed()

    # F7: coerción segura — un `text` no-string (int/list/None) NO debe crashear el
    # endpoint; se trata como vacío (200 con replacements=[]), nunca un 500.
    # F3: se enmascara el texto COMPLETO (sin cap). Truncar acá dejaba salir la PII del
    # tail SIN placeholder; el cap sólo aplica al preview del monitor (display), abajo.
    raw = body.get("text")
    text = raw if isinstance(raw, str) else ""
    # Superficie canónica (ver ``_superficie``): jamás el `tool` crudo del body — es texto
    # libre del cliente y terminaba en `audit_logs.model`, la columna que agrega analytics.
    superficie = _superficie(ident, body.get("tool"))

    # Postura de gobernanza (027): la superficie es el `tool_type` de la Connection —dato
    # del admin, confiable—, NUNCA el `tool` del body, que lo elige la página. El modo es
    # `subscription`: este tráfico va contra la suscripción propia del cliente en el
    # producto web del proveedor, el mismo régimen que el passthrough de coding tools (y
    # por eso las capas delegables se reportan `delegated`, no "desprotegido", FR-013).
    # `X-Sentinel-Redact` no participa: la extensión no lo manda y, desde la 027, un header
    # por-request no puede relajar de todos modos.
    profile = gateway._resolve_governance_profile(ident, None, None,
                                                  route=ROUTE_GATEWAY_PASSTHROUGH)

    # Un body Anthropic sintético de un solo turno user: así el texto plano del navegador
    # entra por la MISMA función que el passthrough (`evaluate_request_policy`) en vez de
    # tener su propia media-política. Es lo que hace estructuralmente imposible que esta
    # superficie vuelva a divergir del piso (fix P4).
    synthetic = {"model": superficie, "messages": [{"role": "user", "content": text}]}
    # `ident["nlp"]` (issue #63): el contexto de detección del tenant se threadea igual que en
    # `/gw/v1/messages`. Es la misma razón por la que este endpoint reusa
    # `evaluate_request_policy` — si esta superficie eligiera detector por su cuenta,
    # volvería a divergir del piso, que es justo lo que el fix P4 vino a cerrar.
    nlp_ctx = ident.get("nlp") or {}
    block_reason, status, ph_to_orig, entities, attribution = \
        await gateway.evaluate_request_policy(synthetic, profile, nlp_ctx)

    latency = int((time.time() - start) * 1000)
    # Preview del monitor: SIEMPRE display-masked sobre mapa desechable + scrub de secretos
    # (contrato evento §10). Vale también —sobre todo— para el evento de BLOQUEO, donde el
    # bloqueo ocurre antes del enmascarado y el texto sigue crudo: sin este pase propio, la
    # vitrina se convertiría en el canal de fuga del contenido que acabamos de bloquear.
    preview = await gateway._safe_preview(synthetic, nlp_ctx)
    gateway._audit(ident, superficie, 0, 0, status, entities, latency, attribution)
    gateway._publish_monitor(ident, superficie, superficie, status, entities, preview,
                             surface="browser", attribution=attribution)

    if block_reason:
        # `ok: false` para que el fail-closed de CUALQUIER versión de la extensión dispare
        # (ver docstring del módulo). HTTP 200: el pedido se procesó y su veredicto es
        # "bloquear" — un 4xx haría que algunos clientes traten la respuesta como error de
        # red y ni miraran el cuerpo, perdiendo `blocked`/`motivo`. La decisión viaja en el
        # cuerpo, que es donde la extensión la lee.
        return JSONResponse(status_code=200, content={
            "ok": False,
            "blocked": True,
            "blocked_by_layer": attribution.blocked_by_layer,
            "motivo": _motivo(attribution.blocked_by_layer),
        })

    masked = gateway._last_user_text(synthetic) if text else text
    replacements = [{"token": ph, "original": orig} for ph, orig in ph_to_orig.items()]

    return {
        "ok": True,
        "blocked": False,
        "masked": masked,
        "replacements": replacements,
        "entities": entities,
        "user": ident.get("client_username") or "default",
        "team": ident.get("group_name") or "—",
    }
