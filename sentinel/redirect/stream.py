"""Envoltorio SSE para respuestas redirigidas (research D4, R13 corrección 3; FR-020/024).

- Reenvía tramas completas en el mismo orden en que llegan (nunca reordena ni fusiona eventos).
- Si el upstream calla más de `ping_after` segundos, emite un keep-alive **entre tramas**
  (cara Claude: `event: ping`; OpenAI: comentario `: keep-alive`). Las tramas partidas entre
  chunks se re-ensamblan antes de emitirse, así un ping nunca cae dentro de una trama.
- Reescribe el modelo al id público: `message.model` de `message_start` (Claude), `model` de los
  chunks OpenAI y `response.model` de los eventos de Responses.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import AsyncIterator, Optional

CLAUDE_PING = b'event: ping\ndata: {"type": "ping"}\n\n'
OPENAI_KEEPALIVE = b": keep-alive\n\n"
DEFAULT_PING_AFTER = 15.0
_SEP = re.compile(rb"\r\n\r\n|\n\n|\r\r")


def _rewrite_obj(obj, public_model: str, face: str) -> bool:
    if not isinstance(obj, dict):
        return False
    changed = False
    if face == "claude":
        if obj.get("type") == "message_start" and isinstance(obj.get("message"), dict) \
                and "model" in obj["message"]:
            obj["message"]["model"] = public_model
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
            if not chunk:
                continue
            buf += chunk if isinstance(chunk, (bytes, bytearray)) else str(chunk).encode()
            out = []
            while True:
                m = _SEP.search(buf)
                if not m:
                    break
                frame, buf = buf[:m.start()], buf[m.end():]
                out.append(rewrite_frame(frame, public_model, face) + b"\n\n")
            if out:
                yield b"".join(out)
        if buf:
            yield rewrite_frame(buf, public_model, face)
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
