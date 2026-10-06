"""Estimación local de tokens para `count_tokens` (T093 de Sentinel; FR-041, research R12; QA M14).

Sin red, nunca: usa `tiktoken` con `cl100k_base` (la codificación de `backend/src/services/token_counter.py`)
**solo si su vocabulario ya está en el disco** (`TIKTOKEN_CACHE_DIR`, horneado en la imagen) y con el hash
esperado; si no está o no coincide, estima `caracteres/4`. La librería, ante un vocabulario ausente,
lo descargaría: por eso se verifica antes de pedírselo.

El texto estimado es el que viaja al destino y cuenta: `system`, mensajes, razonamiento, llamadas y
resultados de herramientas y la definición de las herramientas. Las firmas, los ids y las marcas de
caché no cuentan; cada imagen o documento suma un valor fijo (`MEDIA_TOKENS`).
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from typing import Any, Optional

ENCODING = "cl100k_base"
_BLOB = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
_EXPECTED_SHA256 = "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
MEDIA_TOKENS = 1500
_encoder = None


def _vocabulary_path() -> Optional[str]:
    """Donde `tiktoken` buscaría el vocabulario (mismas reglas que `read_file_cached`); `None` si el
    caché está deshabilitado o el archivo no está."""
    if "TIKTOKEN_CACHE_DIR" in os.environ:
        cache_dir = os.environ["TIKTOKEN_CACHE_DIR"]
    elif "DATA_GYM_CACHE_DIR" in os.environ:
        cache_dir = os.environ["DATA_GYM_CACHE_DIR"]
    else:
        cache_dir = os.path.join(tempfile.gettempdir(), "data-gym-cache")
    if not cache_dir:
        return None
    path = os.path.join(cache_dir, hashlib.sha1(_BLOB.encode()).hexdigest())
    return path if os.path.isfile(path) else None


def _get_encoder():
    global _encoder
    if _encoder is not None:
        return _encoder
    path = _vocabulary_path()
    if path is None:
        return None
    try:
        with open(path, "rb") as f:
            if hashlib.sha256(f.read()).hexdigest() != _EXPECTED_SHA256:
                return None                  # corrupto: la librería lo volvería a bajar de la red
        import tiktoken
        _encoder = tiktoken.get_encoding(ENCODING)
    except Exception:  # noqa: BLE001 — sin librería o sin vocabulario usable: caracteres/4
        return None
    return _encoder


def mode() -> str:
    """Con qué se estima ahora: `cl100k_base` o `chars_over_4`."""
    return ENCODING if _get_encoder() is not None else "chars_over_4"


def _tool_result_text(content: Any, out: list) -> int:
    if isinstance(content, str):
        out.append(content)
        return 0
    media = 0
    for blk in content if isinstance(content, list) else ():
        media += _block_text(blk, out)
    return media


def _block_text(blk: Any, out: list) -> int:
    """Suma el texto de un bloque a `out` y devuelve cuántos adjuntos (imagen/documento) trae."""
    if isinstance(blk, str):
        out.append(blk)
        return 0
    if not isinstance(blk, dict):
        return 0
    kind = blk.get("type")
    if kind == "text":
        out.append(str(blk.get("text") or ""))
    elif kind == "thinking":
        out.append(str(blk.get("thinking") or ""))              # la firma no cuenta
    elif kind == "tool_use":
        out.append(str(blk.get("name") or ""))
        out.append(json.dumps(blk.get("input"), ensure_ascii=False, default=str))
    elif kind == "tool_result":
        return _tool_result_text(blk.get("content"), out)
    elif kind in ("image", "document"):
        return 1
    return 0


def extract_text(body: Any) -> tuple:
    """→ (texto que cuenta, cantidad de adjuntos). Nunca falla con un cuerpo malformado."""
    if not isinstance(body, dict):
        return "", 0
    pieces, media = [], 0
    system = body.get("system")
    for blk in [system] if isinstance(system, str) else (system if isinstance(system, list) else ()):
        media += _block_text(blk, pieces)
    for msg in body.get("messages") if isinstance(body.get("messages"), list) else ():
        content = msg.get("content") if isinstance(msg, dict) else None
        for blk in [content] if isinstance(content, str) else (content if isinstance(content, list) else ()):
            media += _block_text(blk, pieces)
    for tool in body.get("tools") if isinstance(body.get("tools"), list) else ():
        if isinstance(tool, dict):
            pieces.append(str(tool.get("name") or ""))
            pieces.append(str(tool.get("description") or ""))
            if tool.get("input_schema") is not None:
                pieces.append(json.dumps(tool["input_schema"], ensure_ascii=False, default=str))
    return "\n".join(p for p in pieces if p), media


def estimate(body: Any) -> Optional[int]:
    """Tokens de entrada estimados, o `None` si el cuerpo no es un objeto (sin estimación)."""
    if not isinstance(body, dict):
        return None
    text, media = extract_text(body)
    enc = _get_encoder()
    tokens = len(enc.encode(text, disallowed_special=())) if enc is not None else len(text) // 4
    return tokens + media * MEDIA_TOKENS
