"""Cara Claude (contracts/cara-claude.md; research D3/D5/D6).

- `models_view`: `/gw/v1/models` en formato Anthropic desde los ids publicados (face=claude).
- `error_response` / `error_event`: tabla de errores con `error.type` por categoría.
- `normalize_for_translated`: adapta un pedido Messages para un destino **traducido** según su
  perfil de capacidades (no se aplica a destinos nativos: FR-026).

Entradas de `models_view` (una por id publicado, ya resuelto el destino del pedido principal):
`public_id`, `family_tier`, `is_family_default`, `label_mode` (`destination`|`requested`|
`custom`), `label`, `destination_name`, `context_window`, `created_at`.
"""
from __future__ import annotations

import copy
import json
import math
import re
from typing import Any, Iterable, Mapping, Optional

from .. import credentials

ONE_MILLION = 1_000_000
DEFAULT_RETRY_AFTER = 10
MAX_RETRY_AFTER = 60

_TIER_NAMES = {"opus": "Opus", "sonnet": "Sonnet", "haiku": "Haiku", "fable": "Fable", "mythos": "Mythos"}


def display_label(row: Mapping[str, Any]) -> str:
    mode = row.get("label_mode") or "destination"
    if mode == "custom" and row.get("label"):
        return str(row["label"])
    if mode == "requested":
        return str(row.get("requested_label") or row["public_id"])
    tier = _TIER_NAMES.get(row.get("family_tier") or "", row.get("family_tier") or row["public_id"])
    dest = row.get("destination_name")
    label = f"{tier} · servido por {dest}" if dest else str(tier)
    if row.get("without_images"):         # FR-008a: que el selector avise antes de adjuntar
        label += " · sin imágenes"
    return label


def _model_entry(row: Mapping[str, Any], now_iso: str) -> dict:
    window = int(row.get("context_window") or 0)
    shows_destination = (row.get("label_mode") or "destination") == "destination"
    desc = f"Ventana: {window}." if window else "Ventana: sin declarar."
    if shows_destination and row.get("destination_name"):
        desc = f"Destino: {row['destination_name']}. {desc}"
    entry = {
        "type": "model", "id": row["public_id"], "display_name": display_label(row),
        "description": desc, "created_at": row.get("created_at") or now_iso,
        "anthropic_family_tier": row.get("family_tier"),
        "is_family_default": bool(row.get("is_family_default")),
        "max_input_tokens": window, "supports_1m": window >= ONE_MILLION,
    }
    if not window:  # sin declarar: mejor el default del cliente que una ventana 0
        del entry["max_input_tokens"]
    return entry


def models_view(rows: Iterable[Mapping[str, Any]], *, limit: int = 1000, after_id: Optional[str] = None,
                before_id: Optional[str] = None, now_iso: str) -> dict:
    entries = sorted((_model_entry(r, now_iso) for r in rows), key=lambda m: m["id"])
    ids = [m["id"] for m in entries]
    if after_id in ids:
        entries = entries[ids.index(after_id) + 1:]
    elif before_id in ids:
        entries = entries[:ids.index(before_id)]
    limit = max(1, min(int(limit or 1000), 1000))
    page, has_more = entries[:limit], len(entries) > limit
    return {"data": page, "has_more": has_more,
            "first_id": page[0]["id"] if page else None, "last_id": page[-1]["id"] if page else None}


# --- errores -------------------------------------------------------------------------

CAPABILITY_MESSAGES = {
    "images": "Este modelo no acepta imágenes. Quitá la imagen de este mensaje o elegí otro modelo.",
    "documents_pdf": "Este modelo no acepta documentos. Quitá el documento de este mensaje o elegí "
                     "otro modelo.",
}

_ERRORS = {  # kind → (status, error.type, mensaje neutro, reintentar)
    "not_available": (404, "not_found_error", "Modelo no disponible para tu organización.", False),
    "region": (403, "permission_error", "Modelo no disponible para tu región.", False),
    "capability": (400, "invalid_request_error", "capability_rejected: {capability}", False),
    "invalid_request": (400, "invalid_request_error", "El pedido no es válido para este modelo.", False),
    "overloaded": (529, "overloaded_error", "El modelo está saturado. Reintentá en unos segundos.", True),
    "rate_limit": (429, "rate_limit_error", "Límite de uso alcanzado. Reintentá en unos segundos.", False),
    "policy_unavailable": (503, "api_error", "Servicio no disponible temporalmente.", True),
    # Perfil de acceso (069 D9): 403 y no 401, que dispara reloguear; sin reintento.
    "model_not_allowed": (403, "permission_error", "Este modelo no está permitido para tu perfil.", False),
    "auth": (401, "authentication_error", "Credencial no válida para este modelo.", False),
    "upstream_auth": (502, "api_error", "Modelo no disponible temporalmente.", True),
    # Rechazos del propio Sentinel: definitivos, nunca reintentables (069 FR-008d). Van como 400
    # y no 403: Claude Desktop antepone «Failed to authenticate» a todo 403 y el usuario cree que
    # su llave está mal (demo del 28-sep).
    "masking_blocked": (400, "invalid_request_error", "El pedido no pudo protegerse para este "
                        "destino y fue bloqueado. Probá en una conversación nueva.", False),
    "policy_blocked": (400, "invalid_request_error", "El pedido fue rechazado por la política de la "
                       "organización.", False),
    "destination_misconfigured": (400, "invalid_request_error", "Modelo no disponible: la "
                                  "configuración del destino está incompleta. Avisá al "
                                  "administrador.", False),
}


def clamp_retry_after(value: Any) -> int:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return DEFAULT_RETRY_AFTER
    if math.isnan(v):
        return DEFAULT_RETRY_AFTER
    return int(min(MAX_RETRY_AFTER, max(1, math.ceil(v))))


def error_response(kind: str, *, capability: Optional[str] = None, retry_after: Any = None,
                   message: Optional[str] = None):
    """→ (status, headers, body) con el cuerpo `{"type":"error","error":{...}}`."""
    status, etype, text, retry = _ERRORS[kind]
    if kind == "capability":
        text = text.format(capability=capability or "unknown")
        # el marcador `capability_rejected: <función>` va primero: es lo que las herramientas
        # reconocen para recuperarse; después, la explicación para la persona (069 FR-008b)
        message = message or CAPABILITY_MESSAGES.get(capability or "")
        if message:
            text = f"{text} — {message}"
    headers = {}
    if retry:
        headers["x-should-retry"] = "true"
    if kind == "rate_limit":
        headers["retry-after"] = str(clamp_retry_after(retry_after))
    return status, headers, {"type": "error", "error": {"type": etype, "message": text}}


def map_upstream_status(status: int) -> str:
    if status == 429:
        return "rate_limit"
    if status >= 500:
        return "overloaded"
    if status in (401, 403):
        return "upstream_auth"          # falla de NUESTRA credencial de destino, no del usuario
    if status == 404:
        return "not_available"
    return "invalid_request"


def error_event(kind: str, **kw) -> bytes:
    """Error posterior a `message_start`: `event: error` y se cierra el stream (sin message_stop)."""
    _, _, body = error_response(kind, **kw)
    return b"event: error\ndata: " + json.dumps(body, ensure_ascii=False).encode() + b"\n\n"


# --- normalizador ----------------------------------------------------------------------

class CapabilityRejected(ValueError):
    def __init__(self, capability: str):
        super().__init__(f"capability_rejected: {capability}")
        self.capability = capability


# T139 de Sentinel (FR-035, research R10): hacia un destino traducido solo pasan los campos de primer
# nivel de esta lista (contracts/cara-claude.md §1). Una lista negra (`safeguards`) se rompe con el
# próximo campo nuevo de la herramienta; los que adapta el normalizador no cuentan como desconocidos.
FIELD_ALLOWLIST = ("model", "messages", "system", "max_tokens", "stop_sequences", "stream", "temperature",
                   "top_p", "top_k", "tools", "tool_choice", "metadata")
_ADAPTED_FIELDS = frozenset({"thinking", "output_config", "context_management"})
DROPPED_FIELD_PREFIX = "dropped_field:"
MAX_DROPPED_NAMES = 20                  # la auditoría lleva nombres, acotados: nunca valores
_SAFE_FIELD_NAME = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
_INVALID_FIELD_NAME = "campo_no_valido"

_EFFORT = {"low": "low", "medium": "medium", "high": "high", "max": "high", "xhigh": "high"}
_BLOCK_CAPABILITY = {"document": "documents_pdf", "image": "images"}


def _strip_cache_control(node):
    if isinstance(node, dict):
        node.pop("cache_control", None)
        for v in node.values():
            _strip_cache_control(v)
    elif isinstance(node, list):
        for v in node:
            _strip_cache_control(v)


def _as_blocks(content) -> list:
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return []


_OMITTED_NOTE = {"images": "[imagen omitida: el modelo de este chat no acepta imágenes]",
                 "documents_pdf": "[documento omitido: el modelo de este chat no acepta documentos]"}
# Lo que devolvió una herramienta en el turno actual (la captura con la que Cowork revisa su
# resultado): la nota le pide al agente que no insista, para que no entre en un bucle de capturas.
_TOOL_NOTE = {"images": "[imagen omitida: el modelo de este chat no acepta imágenes. No vuelvas a "
                        "pedir capturas ni imágenes; seguí con lo que tengas en texto.]",
              "documents_pdf": "[documento omitido: el modelo de este chat no acepta documentos. No "
                               "vuelvas a pedir el documento; pedí su contenido como texto.]"}
_TOOL_LABEL = {"images": "images_in_tool_result", "documents_pdf": "documents_in_tool_result"}


def _omit_unsupported(content: list, profile: Mapping[str, Any], notes: Mapping[str, str]) -> set:
    """Reemplaza, en el lugar y uno por uno, los bloques sin soporte por una nota de texto
    (recursivo en `tool_result`): un contenido que era solo la imagen queda con la nota, nunca
    vacío. Devuelve las capacidades omitidas."""
    omitted = set()
    for i, blk in enumerate(content):
        if not isinstance(blk, dict):
            continue
        cap = _BLOCK_CAPABILITY.get(blk.get("type"))
        if cap and not profile.get(cap, False):
            content[i] = {"type": "text", "text": notes[cap]}
            omitted.add(cap)
        elif isinstance(blk.get("content"), list):          # tool_result con bloques anidados
            omitted |= _omit_unsupported(blk["content"], profile, notes)
    return omitted


def current_turn_needs(body: Mapping[str, Any]) -> frozenset:
    """Capacidades que la PERSONA adjuntó en el turno actual (imagen o documento sueltos en su último
    mensaje). Lo que devuelve una herramienta dentro de un `tool_result` no cuenta: se reemplaza por una
    nota, no corta la tarea."""
    msgs = [m for m in (body.get("messages") or []) if isinstance(m, dict)]
    last = max((i for i, m in enumerate(msgs) if m.get("role") == "user"), default=-1)
    content = msgs[last].get("content") if last >= 0 else None
    return frozenset(_BLOCK_CAPABILITY[b["type"]] for b in (content if isinstance(content, list) else ())
                     if isinstance(b, dict) and b.get("type") in _BLOCK_CAPABILITY)


def _check_blocks(messages: list, profile: Mapping[str, Any]) -> list:
    """Imágenes/documentos sin soporte. Turnos anteriores: se reemplazan por una nota (la
    herramienta reenvía la historia entera; rechazar dejaba el chat inservible, 069 FR-008e).
    Turno actual (último del usuario): un bloque suelto lo adjuntó la persona y se rechaza; uno
    dentro de un `tool_result` lo devolvió una herramienta que pidió el modelo (la captura de
    Cowork, F5 del 29-sep) y se reemplaza, para no cortar la tarea. Devuelve qué se omitió."""
    last_user = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
    labels = []
    for i, m in enumerate(messages):
        content = m.get("content")
        if not isinstance(content, list):
            continue
        if i != last_user:
            if _omit_unsupported(content, profile, _OMITTED_NOTE) and "images_in_history" not in labels:
                labels.append("images_in_history")
            continue
        for blk in content:
            if not isinstance(blk, dict):
                continue
            cap = _BLOCK_CAPABILITY.get(blk.get("type"))
            if cap and not profile.get(cap, False):
                raise CapabilityRejected(cap)
        tool_omitted = set()
        for blk in content:
            if isinstance(blk, dict) and isinstance(blk.get("content"), list):
                tool_omitted |= _omit_unsupported(blk["content"], profile, _TOOL_NOTE)
        labels += [_TOOL_LABEL[c] for c in sorted(tool_omitted)]
    return labels


def _dropped_field_entries(names: Iterable[str]) -> list:
    """Nombres de campo a ajustes `dropped_field:<nombre>`: ordenados, sin duplicados y acotados
    (largo, caracteres y cantidad); un nombre que no es un identificador corto se reemplaza."""
    safe = sorted({n if _SAFE_FIELD_NAME.match(n) else _INVALID_FIELD_NAME for n in names})
    if len(safe) > MAX_DROPPED_NAMES:
        safe = safe[:MAX_DROPPED_NAMES - 1] + [f"otros_{len(safe) - MAX_DROPPED_NAMES + 1}"]
    return [DROPPED_FIELD_PREFIX + n for n in safe]


def dropped_field_names(removed: Iterable[str]) -> list:
    """Los nombres de los campos descartados que `normalize_for_translated` dejó en sus ajustes."""
    return [r[len(DROPPED_FIELD_PREFIX):] for r in removed if r.startswith(DROPPED_FIELD_PREFIX)]


def normalize_for_translated(body: Mapping[str, Any], profile: Mapping[str, Any], *, max_output: int):
    """→ (cuerpo nuevo, lista de ajustes aplicados). No muta la entrada. Los campos de primer nivel
    fuera de `FIELD_ALLOWLIST` se quitan sin error; sus nombres van como `dropped_field:<nombre>`."""
    out = copy.deepcopy(dict(body))
    removed = []

    out, cred_fields = credentials.strip_client_credentials(out)
    if cred_fields:
        removed.append("client_credentials")

    unknown = [k for k in out if isinstance(k, str) and k not in FIELD_ALLOWLIST and k not in _ADAPTED_FIELDS]
    for k in unknown:
        out.pop(k)
    removed += _dropped_field_entries(unknown)

    thinking = out.pop("thinking", None)
    oc = out.get("output_config")
    effort = None
    if isinstance(oc, dict) and "effort" in oc:
        effort = oc.pop("effort")
        if not oc:
            out.pop("output_config")
        removed.append("output_config")
    if thinking is not None:
        removed.append("thinking")
    if profile.get("thinking"):
        if isinstance(thinking, dict) and thinking.get("type") == "enabled":
            out["thinking"] = thinking
        elif (isinstance(thinking, dict) and thinking.get("type") == "adaptive") or effort is not None:
            out["reasoning_effort"] = _EFFORT.get(str(effort).lower(), "medium") if effort else "medium"

    if out.pop("context_management", None) is not None:
        removed.append("context_management")

    if not profile.get("cache_control") and "cache_control" in json.dumps(out, default=str):
        _strip_cache_control(out)
        removed.append("cache_control")

    msgs = out.get("messages") or []
    removed += _check_blocks(msgs, profile)
    if not profile.get("mid_system_messages") and any(m.get("role") == "system" for m in msgs):
        extra = [b for m in msgs if m.get("role") == "system" for b in _as_blocks(m.get("content"))]
        out["messages"] = [m for m in msgs if m.get("role") != "system"]
        out["system"] = _as_blocks(out.get("system")) + extra
        removed.append("mid_system_messages")

    if max_output and isinstance(out.get("max_tokens"), int) and out["max_tokens"] > max_output:
        out["max_tokens"] = int(max_output)
        removed.append("max_tokens")
    return out, removed
