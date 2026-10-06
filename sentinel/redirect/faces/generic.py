"""Cara OpenAI genérica (contracts/cara-generica.md; research D3/D5).

Misma forma de error que `_openai_error` de la pasarela (`{"error":{message,type,param,code}}`)
con los códigos nuevos `model_not_found` (404) y `region_not_allowed` (403).
"""
from __future__ import annotations

import copy
from typing import Any, Iterable, Mapping, Optional

from .. import credentials
from .claude import CAPABILITY_MESSAGES, clamp_retry_after

OWNED_BY = "organization"


def select_models_view(headers: Mapping[str, Any]) -> str:
    """`anthropic-version` presente ⇒ cara Claude; si no ⇒ genérica."""
    return "claude" if any(str(k).lower() == "anthropic-version" for k in headers) else "openai_generic"


def models_view(rows: Iterable[Mapping[str, Any]], *, created: int) -> dict:
    data = [{"id": r["public_id"], "object": "model", "created": int(r.get("created") or created),
             "owned_by": OWNED_BY} for r in rows]
    return {"object": "list", "data": sorted(data, key=lambda m: m["id"])}


_ERRORS = {  # kind → (status, type, code, mensaje neutro)
    "not_available": (404, "invalid_request_error", "model_not_found", "Modelo no disponible para tu organización."),
    "region": (403, "permission_error", "region_not_allowed", "Modelo no disponible para tu región."),
    "capability": (400, "invalid_request_error", "capability_rejected", "capability_rejected: {capability}"),
    "invalid_request": (400, "invalid_request_error", None, "El pedido no es válido para este modelo."),
    "rate_limit": (429, "rate_limit_error", None, "Límite de uso alcanzado. Reintentá en unos segundos."),
    "overloaded": (503, "api_error", None, "El modelo está saturado. Reintentá en unos segundos."),
    "policy_unavailable": (503, "api_error", None, "Servicio no disponible temporalmente."),
    "model_not_allowed": (403, "permission_error", "model_not_allowed",
                          "Este modelo no está permitido para tu perfil."),
    "auth": (401, "authentication_error", None, "Credencial no válida para este modelo."),
    "upstream_auth": (502, "api_error", None, "Modelo no disponible temporalmente."),
    # Rechazos del propio Sentinel: definitivos, nunca reintentables (069 FR-008d)
    "masking_blocked": (403, "permission_error", "masking_required",
                        "El pedido no pudo protegerse para este destino y fue bloqueado. "
                        "Probá en una conversación nueva."),
    "policy_blocked": (403, "permission_error", "policy_rejected",
                       "El pedido fue rechazado por la política de la organización."),
    "destination_misconfigured": (403, "permission_error", "destination_misconfigured",
                                  "Modelo no disponible: la configuración del destino está "
                                  "incompleta. Avisá al administrador."),
}


def error_response(kind: str, *, capability: Optional[str] = None, retry_after: Any = None):
    status, etype, code, text = _ERRORS[kind]
    if kind == "capability":
        text = text.format(capability=capability or "unknown")
        human = CAPABILITY_MESSAGES.get(capability or "")
        if human:
            text = f"{text} — {human}"
    headers = {"retry-after": str(clamp_retry_after(retry_after))} if kind == "rate_limit" else {}
    return status, headers, {"error": {"message": text, "type": etype, "param": None, "code": code}}


def rewrite_response_model(body: Mapping[str, Any], public_id: str) -> dict:
    out = copy.deepcopy(dict(body))
    if "model" in out:
        out["model"] = public_id
    return out


_PART_CAPABILITY = {"image_url": "images", "input_image": "images", "file": "documents_pdf",
                    "input_file": "documents_pdf"}
_PART_MARKERS = {"images": "[imagen omitida: el modelo no acepta imágenes]",
                 "documents_pdf": "[documento omitido: el modelo no acepta documentos PDF]"}


def _turn_start(messages: list) -> int:
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], dict) and messages[i].get("role") == "user":
            return i
    return len(messages)


def current_turn_needs(body: Mapping[str, Any]) -> frozenset:
    """Imágenes/documentos en el turno ACTUAL (partes `image_url`/`file` del formato de chat estándar)."""
    msgs = body.get("messages") or []
    needs = set()
    for m in msgs[_turn_start(msgs):]:
        content = m.get("content") if isinstance(m, dict) else None
        for part in content if isinstance(content, list) else ():
            cap = _PART_CAPABILITY.get(part.get("type")) if isinstance(part, dict) else None
            if cap:
                needs.add(cap)
    return frozenset(needs)


def _declares_no(profile: Mapping[str, Any], cap: str) -> bool:
    """En la cara genérica la capacidad solo se niega si el destino la declara EXPLÍCITAMENTE falsa:
    un destino sin perfil sigue recibiendo todo, como antes de la 069 (FR-039)."""
    return profile.get(cap) is False


def strip_history_media(messages: list, profile: Mapping[str, Any]) -> list:
    out = copy.deepcopy(messages)
    for m in out[:_turn_start(out)]:
        content = m.get("content") if isinstance(m, dict) else None
        if not isinstance(content, list):
            continue
        for i, part in enumerate(content):
            cap = _PART_CAPABILITY.get(part.get("type")) if isinstance(part, dict) else None
            if cap and _declares_no(profile, cap):
                content[i] = {"type": "text", "text": _PART_MARKERS[cap]}
    return out


def missing_capability(needs: Iterable[str], profile: Mapping[str, Any]) -> Optional[str]:
    return next((c for c in sorted(needs) if _declares_no(profile, c)), None)


def prepare_request(body: Mapping[str, Any], *, engine_model: str, max_output: Optional[int],
                    profile: Optional[Mapping[str, Any]] = None):
    """Reescribe `model` al destino, quita credenciales del cliente y topea la salida."""
    out, cred_fields = credentials.strip_client_credentials(copy.deepcopy(dict(body)))
    if profile and isinstance(out.get("messages"), list):
        out["messages"] = strip_history_media(out["messages"], profile)
    removed = ["client_credentials"] if cred_fields else []
    out["model"] = engine_model
    if max_output:
        for k in ("max_tokens", "max_completion_tokens"):
            if isinstance(out.get(k), int) and out[k] > max_output:
                out[k] = int(max_output)
                removed.append(k)
    return out, removed
