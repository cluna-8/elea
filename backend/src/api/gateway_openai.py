"""Puerta pública para el **formato de chat estándar del sector** (spec 045, US3).

POR QUÉ EXISTE. El gateway sólo publicaba el formato de mensajes, y casi toda herramienta
de terceros habla el otro. Sin esta ruta, la frase «cualquier proyecto se enchufa a
Sentinel» era falsa: no había por dónde entrar.

LO QUE **NO** ES. No es un traductor entre formatos y no es una segunda política.

- El motor **ya** aplica la política sobre este formato: sus tipos de llamada están en el
  conjunto que evalúa el guardián. Bloqueo, secretos, enmascarado reversible, auditoría
  durable y fila en la vitrina ya corrían acá — lo que faltaba era la puerta.
- El proxy byok (`_byok_proxy`) **no parsea el cuerpo**: arma URL y cabeceras, toma el
  semáforo de admisión y hace passthrough. Lo único acoplado a un formato era la URL del
  motor y la forma del error, y ahora son parámetros.

Por eso este archivo es corto y **no** debe crecer con lógica de política: si algo hay que
decidir sobre el contenido, se decide en la librería compartida, no acá. Media política en
un segundo sitio es el modo de falla que la 027 vino a cerrar.

SÓLO BYOK, A PROPÓSITO. El passthrough de suscripción manda el cuerpo verbatim al upstream
del proveedor de mensajes, que **no habla este formato**. Intentar servirlo por ahí sería
escribir el traductor por la puerta de atrás. Sin virtual key resoluble → 401 honesto.

DÓNDE VIVE. Archivo nuevo montado desde `main.py`, con el mismo patrón que gobernanza y el
plano interno: router nuevo, sin competir por `api/__init__.py`. Así el trabajo cae en la
cubeta NUEVO y no engorda la divergencia con la base (ADR 0006).
"""
from __future__ import annotations

import json
import time
from typing import Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from . import gateway
from .gateway import (
    MODELO_CADENA_USURPADA,
    sanear_modelo_declarado,
)

router = APIRouter(prefix="/gw", tags=["gateway"])


def _openai_error(message: str, status_code: int = 400, headers: Optional[dict] = None,
                  tipo: Optional[str] = None):
    """Error con la forma que la interfaz del cliente sabe renderizar.

    Gemelo de `_anthropic_error`. Sin esto un cliente de terceros muestra «error de red» en
    vez del motivo real del bloqueo — y el motivo del bloqueo es literalmente lo que el
    producto tiene que lucir.

    El `message` lleva el motivo en lenguaje llano, **nunca** el identificador interno de la
    capa que bloqueó. La metadata legible por máquina viaja por cabecera, igual que en la
    otra ruta.
    """
    if tipo is None:
        tipo = {401: "authentication_error", 402: "insufficient_quota",
                429: "rate_limit_error", 502: "api_error", 503: "api_error"}.get(
                    status_code, "invalid_request_error")
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": message, "type": tipo, "param": None, "code": None}},
        headers=headers,
    )


@router.post("/v1/chat/completions", dependencies=gateway._HARD_BLOCK)
async def gw_chat_completions(
    request: Request,
    x_sentinel_key: Optional[str] = Header(None, alias="X-Sentinel-Key"),
    x_sentinel_upstream: Optional[str] = Header(None, alias="X-Sentinel-Upstream"),
):
    start = time.time()
    raw = await request.body()
    try:
        body = json.loads(raw)
    except Exception:  # noqa: BLE001
        return _openai_error("Cuerpo JSON inválido.")
    # Mismo trust boundary que la otra puerta: acá entra JSON crudo del cliente. Un cuerpo
    # no-objeto o un `messages` que no es lista devuelve 400 honesto, jamás un 500.
    if not isinstance(body, dict):
        return _openai_error("Cuerpo inválido: se esperaba un objeto JSON.")
    if body.get("messages") is not None and not isinstance(body.get("messages"), list):
        return _openai_error("Cuerpo inválido: 'messages' debe ser una lista.")

    # El nombre del modelo lo escribe el cliente y termina en la fila de auditoría: se sanea
    # en la puerta y ANTES del ruteo, por la misma razón que en la otra ruta — ninguna puerta
    # puede ser la trasera del literal reservado.
    model = sanear_modelo_declarado(body.get("model", "unknown"))
    is_stream = bool(body.get("stream"))

    mode, sentinel_key = gateway._detect_mode_and_key(request, x_sentinel_upstream, x_sentinel_key)
    if mode != "byok" or not sentinel_key:
        # 401 honesto en vez de intentar el passthrough de suscripción: ese upstream no habla
        # este formato. Ver la cabecera del módulo.
        return _openai_error(
            "[Sentinel Gateway] Esta ruta requiere una virtual key de Sentinel "
            "(sk-sentinel-…). Configúrala como API key en tu herramienta.", 401)

    # Corte por auditoría en la puerta (misma postura que la ruta de mensajes): más barato
    # acá que un salto de red después de haber aceptado el pedido.
    if not gateway._audit_precheck_ok(gateway._exige_registro_byok()):
        resp = gateway._audit_no_disponible()
        return _openai_error(
            "[Sentinel Gateway] El registro de auditoría no está disponible y esta "
            "instalación no sirve tráfico sin registrarlo.", resp.status_code)

    # Único retoque del cuerpo, igual que en la otra ruta: «auto» → default del router. Todo
    # lo demás va verbatim al motor, que es quien aplica la política.
    enviado = gateway._resolve_auto_model(body, raw)
    modelo_al_motor = model
    if enviado is not raw:
        try:
            modelo_al_motor = sanear_modelo_declarado(json.loads(enviado).get("model") or model)
        except Exception:  # noqa: BLE001 — jamás romper por un nombre para la auditoría
            pass
    if modelo_al_motor == MODELO_CADENA_USURPADA:
        # El saneo ya lo neutralizó; se responde honesto en vez de auditar un literal falso.
        return _openai_error("[Sentinel Gateway] Nombre de modelo no admitido.", 400)

    return await gateway._byok_proxy(
        request, enviado, sentinel_key, is_stream,
        model=modelo_al_motor, start=start,
        ruta_motor="/v1/chat/completions", error_fn=_openai_error,
    )
