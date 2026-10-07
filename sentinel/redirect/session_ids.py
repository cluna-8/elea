"""Identificadores derivados de la sesión de la herramienta (057 T073/T074; FR-043, FR-045; research R18).

La herramienta manda un identificador de sesión (`x-claude-code-session-id`, y `x-claude-code-agent-id` en un subagente;
sin cabecera, el `user_id` de `metadata` lleva `…_session_<id>`). Nada de eso sale hacia el destino ni hacia el motor: con la
clave del servidor (`MASKING_NONCE_KEY`, ≥ 32 caracteres) se derivan, con separación de dominio, dos identificadores que no
llevan datos de la persona y no se pueden reproducir sin la clave:

· `conversation_ref` = HMAC(clave, "conv" | empresa | sesión): la referencia que el guardrail del motor usa para el sufijo de
  los marcadores (S13). La misma entre subagentes: es la misma conversación;
· `affinity_id` = HMAC(clave, "affinity" | empresa | sesión | agente): lo que se manda a un destino que agrupa por sesión.

Sin la clave, sin sesión o con la clave corta, nada (el comportamiento de antes). Genérico: sin cadenas de ningún cliente."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from typing import Any, Mapping, Optional

SESSION_HEADER = "x-claude-code-session-id"
AGENT_HEADER = "x-claude-code-agent-id"
CONVERSATION_REF_KEY = "sentinel_conversation_ref"      # el mismo nombre que lee el guardrail del motor (S13)
KEY_ENV = "MASKING_NONCE_KEY"
MIN_KEY_CHARS = 32
_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_USER_ID_SESSION = re.compile(r"_session_([A-Za-z0-9._:-]{1,128})$")


def _clean(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and _ID.match(value) else None


def _header(headers: Optional[Mapping[str, Any]], name: str) -> Optional[str]:
    for k, v in (headers or {}).items():
        if str(k).lower() == name:
            return _clean(v)
    return None


def session_id(headers: Optional[Mapping[str, Any]], body: Any = None) -> Optional[str]:
    """El identificador de sesión que mandó la herramienta: la cabecera o, sin ella, el `user_id` de `metadata`."""
    found = _header(headers, SESSION_HEADER)
    if found or not isinstance(body, Mapping):
        return found
    meta = body.get("metadata")
    uid = meta.get("user_id") if isinstance(meta, Mapping) else None
    if not isinstance(uid, str):
        return None
    m = _USER_ID_SESSION.search(uid)
    if m:
        return m.group(1)
    try:                                                    # versiones que mandan el user_id como JSON
        parsed = json.loads(uid)
    except ValueError:
        return None
    return _clean(parsed.get("session_id")) if isinstance(parsed, dict) else None


def agent_id(headers: Optional[Mapping[str, Any]]) -> Optional[str]:
    return _header(headers, AGENT_HEADER)


def _derive(domain: str, tenant: str, *parts: str) -> Optional[str]:
    key = os.environ.get(KEY_ENV, "")
    if len(key) < MIN_KEY_CHARS:
        return None
    msg = b"\x00".join(p.encode("utf-8") for p in (domain, str(tenant), *parts))
    return hmac.new(key.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:32]


def conversation_ref(tenant: str, session: Optional[str]) -> Optional[str]:
    return _derive("conv", tenant, session) if session else None


def affinity_id(tenant: str, session: Optional[str], agent: Optional[str] = None) -> Optional[str]:
    return _derive("affinity", tenant, session, agent or "") if session else None
