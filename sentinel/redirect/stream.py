"""Envoltorio SSE para respuestas redirigidas (research D4, R13 corrección 3; FR-020/024).

- Reenvía tramas completas en el mismo orden en que llegan (nunca reordena ni fusiona eventos).
- Si el upstream calla más de `ping_after` segundos, emite un keep-alive **entre tramas**
  (cara Claude: `event: ping`; OpenAI: comentario `: keep-alive`). Las tramas partidas entre
  chunks se re-ensamblan antes de emitirse, así un ping nunca cae dentro de una trama.
- Reescribe el modelo al id público: `message.model` de `message_start` (Claude), `model` de los
  chunks OpenAI y `response.model` de los eventos de Responses.
- Cara Claude (T091 de Sentinel, FR-038/FR-039): `usage` con los cuatro contadores en `message_start`
  (0 si el destino no informa) y `message_delta` válido sin pisar lo que informó el inicio; una falla del
  destino, o un `event: error` suyo, sale como `event: error` neutro y el stream se cierra: nunca hay un
  `message_stop` después de una falla.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import AsyncIterator, Optional

from .faces import claude as claude_face

logger = logging.getLogger("sentinel.redirect.stream")

CLAUDE_PING = b'event: ping\ndata: {"type": "ping"}\n\n'
OPENAI_KEEPALIVE = b": keep-alive\n\n"
DEFAULT_PING_AFTER = 15.0
_SEP = re.compile(rb"\r\n\r\n|\n\n|\r\r")
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
# `error.type` que emite el destino → categoría neutra de la cara (el texto nunca es el del destino)
_UPSTREAM_ERROR_KIND = {"overloaded_error": "overloaded", "rate_limit_error": "rate_limit",
                        "invalid_request_error": "invalid_request"}


def complete_usage(usage) -> dict:
    """`usage` con los cuatro contadores: lo que el destino informó y 0 para lo demás (o nulo)."""
    usage = dict(usage) if isinstance(usage, dict) else {}
    for key in USAGE_KEYS:
        value = usage.get(key)
        usage[key] = value if isinstance(value, int) and not isinstance(value, bool) else 0
    return usage


def _rewrite_obj(obj, public_model: str, face: str) -> bool:
    if not isinstance(obj, dict):
        return False
    changed = False
    if face == "claude":
        if obj.get("type") == "message_start" and isinstance(obj.get("message"), dict):
            if "model" in obj["message"]:
                obj["message"]["model"] = public_model
            obj["message"]["usage"] = complete_usage(obj["message"].get("usage"))
            changed = True
        elif obj.get("type") == "message_delta":
            # el SDK de la herramienta acumula lo que llega: no se agregan ceros que pisarían lo que
            # informó `message_start`; solo `output_tokens` es obligatorio y los nulos se quitan
            usage = {k: v for k, v in (obj.get("usage") or {}).items() if v is not None} \
                if isinstance(obj.get("usage"), dict) else {}
            if not isinstance(usage.get("output_tokens"), int):
                usage["output_tokens"] = 0
            if usage != obj.get("usage"):
                obj["usage"] = usage
                changed = True
    else:
        if "model" in obj and isinstance(obj["model"], str):
            obj["model"] = public_model
            changed = True
        resp = obj.get("response")
        if isinstance(resp, dict) and isinstance(resp.get("model"), str):
            resp["model"] = public_model
            changed = True
    return changed


def rewrite_frame(frame: bytes, public_model: str, face: str) -> bytes:
    """`frame` sin separador final. Devuelve la trama (reescrita solo si cambió)."""
    lines = re.split(rb"\r\n|\n|\r", frame)
    data_idx = [i for i, ln in enumerate(lines) if ln.startswith(b"data:")]
    if not data_idx:
        return frame
    payload = b"\n".join(lines[i][5:].lstrip(b" ") for i in data_idx)
    if payload.strip() == b"[DONE]":
        return frame
    try:
        obj = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return frame
    if not _rewrite_obj(obj, public_model, face):
        return frame
    new_data = b"data: " + json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
    out, placed = [], False
    for i, ln in enumerate(lines):
        if i in data_idx:
            if not placed:
                out.append(new_data)
                placed = True
            continue
        out.append(ln)
    return b"\n".join(out)


def _frame_object(frame: bytes):
    lines = re.split(rb"\r\n|\n|\r", frame)
    payload = b"\n".join(ln[5:].lstrip(b" ") for ln in lines if ln.startswith(b"data:"))
    try:
        return json.loads(payload) if payload.strip() else None
    except (ValueError, UnicodeDecodeError):
        return None


def upstream_error_kind(frame: bytes) -> Optional[str]:
    """Categoría neutra si la trama es un error del destino (`event: error` o `{"type": "error"}`)."""
    obj = _frame_object(frame)
    is_error_event = any(ln.strip() == b"event: error" for ln in re.split(rb"\r\n|\n|\r", frame))
    if not is_error_event and not (isinstance(obj, dict) and obj.get("type") == "error"):
        return None
    err = obj.get("error") if isinstance(obj, dict) else None
    return _UPSTREAM_ERROR_KIND.get(err.get("type") if isinstance(err, dict) else None, "upstream_failed")


async def wrap_sse(source: AsyncIterator[bytes], *, public_model: str, face: str,
                   ping_after: Optional[float] = DEFAULT_PING_AFTER) -> AsyncIterator[bytes]:
    """`face`: `claude` | `openai` (chat/completions y Responses)."""
    keepalive = CLAUDE_PING if face == "claude" else OPENAI_KEEPALIVE
    it = source.__aiter__()
    buf = b""
    pending: Optional[asyncio.Task] = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(it.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=ping_after)
            if not done:
                yield keepalive            # siempre en borde de trama: solo emitimos tramas completas
                continue
            task, pending = pending, None
            try:
                chunk = task.result()
            except StopAsyncIteration:
                break
            except Exception:  # noqa: BLE001 — la falla del destino a mitad del stream
                if face != "claude":
                    raise
                logger.warning("redirect: el destino falló a mitad del stream", exc_info=True)
                yield claude_face.error_event("overloaded")      # sin `message_stop`: cierra acá
                return
            if not chunk:
                continue
            buf += chunk if isinstance(chunk, (bytes, bytearray)) else str(chunk).encode()
            out = []
            while True:
                m = _SEP.search(buf)
                if not m:
                    break
                frame, buf = buf[:m.start()], buf[m.end():]
                kind = upstream_error_kind(frame) if face == "claude" else None
                if kind is not None:
                    out.append(claude_face.error_event(kind))
                    yield b"".join(out)
                    return                                       # nada después de un error
                out.append(rewrite_frame(frame, public_model, face) + b"\n\n")
            if out:
                yield b"".join(out)
        if buf:
            yield rewrite_frame(buf, public_model, face)
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
