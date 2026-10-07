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
from typing import AsyncIterator, Callable, Optional

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


def _count(value) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def cache_tokens(usage) -> dict:
    """Tokens de caché que informó el destino en su `usage` (057 FR-046): `cache_read_tokens` y `cache_write_tokens`, solo los
    que vienen como entero ≥ 0 (un cero informado cuenta: el destino dijo que no hubo aciertos). Cara Claude:
    `cache_read_input_tokens` / `cache_creation_input_tokens`; chat OpenAI/OpenRouter: `prompt_tokens_details.cached_tokens` y
    `cache_write_tokens`; Responses: `input_tokens_details`. Nunca contenido."""
    if not isinstance(usage, dict):
        return {}
    out = {}
    for name, direct, detail in (("cache_read_tokens", "cache_read_input_tokens", "cached_tokens"),
                                 ("cache_write_tokens", "cache_creation_input_tokens", "cache_write_tokens")):
        value = _count(usage.get(direct))
        for details in ("prompt_tokens_details", "input_tokens_details"):
            if value is None and isinstance(usage.get(details), dict):
                value = _count(usage[details].get(detail))
        if value is not None:
            out[name] = value
    return out


def frame_usage(obj) -> list:
    """Los `usage` que lleva un objeto de trama SSE: `message_start`/`message_delta` (cara Claude), el chunk final de chat y
    `response.completed` (Responses)."""
    if not isinstance(obj, dict):
        return []
    found = [obj.get("usage")]
    if isinstance(obj.get("message"), dict):
        found.append(obj["message"].get("usage"))
    if isinstance(obj.get("response"), dict):
        found.append(obj["response"].get("usage"))
    return [u for u in found if isinstance(u, dict)]


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


class ThinkingSigner:
    """Firma los bloques `thinking` de un destino traducido (T090 de Sentinel; FR-036): al cerrarse el bloque
    agrega un `signature_delta` con la firma de la pasarela sobre el texto acumulado, y descarta la firma que
    haya mandado el destino (es ajena). Trabaja sobre tramas completas; el resto pasa tal cual."""

    def __init__(self, sign: Callable[[str], str]):
        self._sign = sign
        self._text: dict = {}

    def process(self, frame: bytes) -> list:
        obj = _frame_object(frame)
        if not isinstance(obj, dict):
            return [frame]
        kind, index = obj.get("type"), obj.get("index")
        if kind == "content_block_start" and isinstance(obj.get("content_block"), dict) \
                and obj["content_block"].get("type") == "thinking":
            self._text[index] = []
            if obj["content_block"].get("signature"):
                obj["content_block"]["signature"] = ""
                return [_reframe(frame, obj)]
        elif kind == "content_block_delta" and index in self._text and isinstance(obj.get("delta"), dict):
            delta = obj["delta"]
            if delta.get("type") == "thinking_delta":
                self._text[index].append(str(delta.get("thinking") or ""))
            elif delta.get("type") == "signature_delta":
                return []                                    # la del destino: ajena
        elif kind == "content_block_stop" and index in self._text:
            signature = self._sign("".join(self._text.pop(index)))
            sig = {"type": "content_block_delta", "index": index,
                   "delta": {"type": "signature_delta", "signature": signature}}
            return [b"event: content_block_delta\ndata: " + json.dumps(sig, separators=(",", ":")).encode(), frame]
        return [frame]


def _reframe(frame: bytes, obj: dict) -> bytes:
    """La trama con su `data:` reemplazado por `obj` (conserva `event:` y comentarios)."""
    lines = re.split(rb"\r\n|\n|\r", frame)
    out, placed = [], False
    for ln in lines:
        if ln.startswith(b"data:"):
            if not placed:
                out.append(b"data: " + json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode())
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
                   ping_after: Optional[float] = DEFAULT_PING_AFTER,
                   thinking_signer: Optional[Callable[[str], str]] = None,
                   usage_sink: Optional[Callable[[dict], None]] = None) -> AsyncIterator[bytes]:
    """`face`: `claude` | `openai` (chat/completions y Responses). `thinking_signer`: solo cara Claude hacia
    un destino traducido (ver `ThinkingSigner`). `usage_sink`: recibe cada `usage` que pasa por el stream (tokens de caché para
    la auditoría, 057 FR-046); no cambia ni reordena nada de lo que llega al cliente y una falla suya no corta el stream."""
    def _tap(piece: bytes) -> None:
        if usage_sink is None:
            return
        try:
            for usage in frame_usage(_frame_object(piece)):
                usage_sink(usage)
        except Exception:  # noqa: BLE001 — la auditoría jamás afecta al stream
            logger.warning("redirect: no se pudo leer el usage del stream", exc_info=True)

    keepalive = CLAUDE_PING if face == "claude" else OPENAI_KEEPALIVE
    signer = ThinkingSigner(thinking_signer) if thinking_signer is not None and face == "claude" else None
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
                for piece in (signer.process(frame) if signer is not None else [frame]):
                    _tap(piece)
                    out.append(rewrite_frame(piece, public_model, face) + b"\n\n")
            if out:
                yield b"".join(out)
        if buf:
            _tap(buf)
            yield rewrite_frame(buf, public_model, face)
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
