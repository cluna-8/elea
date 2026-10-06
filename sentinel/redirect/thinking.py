"""Continuidad de razonamiento con destinos traducidos (T084/T090 de Sentinel; FR-036, research D7).

Un destino traducido no produce la firma que el proveedor original pone en sus bloques `thinking`, y la
herramienta reenvía la historia entera en cada turno. La pasarela firma cada bloque `thinking` que sale de un
destino traducido (HMAC atado al **destino** y al texto, sin estado en el servidor) y en el turno siguiente:

- firma propia y del mismo destino, y ese destino exige el razonamiento de la historia (`needs_replay`) ⇒ el
  bloque se reconstruye sin la firma (el motor lo entrega como `reasoning_content` del destino);
- cualquier otra cosa (firma de otro proveedor, de otro destino, ausente, alterada, `redacted_thinking`) o un
  destino que no lo exige ⇒ el bloque se descarta, sin error y sin dejar rastros: nunca se le manda a un
  destino el razonamiento de otro.

La clave se deriva de `REDIRECT_INTERNAL_KEY` con otro dominio que el de la autorización interna; la firma no
contiene ni el texto, ni el destino, ni la clave.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Any, Mapping, Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from sentinel.engine.redirect_authz import KEY_ENV, MIN_KEY_LEN

PREFIX = "rdxs1."
# Proveedores cuyo modelo exige el razonamiento previo en cada turno (DeepSeek); el destino puede declararlo
# con `provider_options.reasoning_replay` (dato de la ficha, sin tocar código).
REPLAY_PROVIDERS = frozenset({"deepseek"})
_TAG_BYTES = 24


def _key() -> Optional[bytes]:
    raw = os.environ.get(KEY_ENV, "")
    if len(raw) < MIN_KEY_LEN:
        return None
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"redirect-thinking",
                info=b"signature-v1").derive(raw.encode())


def _mac(key: bytes, destination_id: str, text: str) -> bytes:
    dest = str(destination_id).encode()
    payload = len(dest).to_bytes(4, "big") + dest + text.encode("utf-8", "replace")
    return hmac.new(key, payload, hashlib.sha256).digest()[:_TAG_BYTES]


def sign(destination_id: str, text: str) -> str:
    """Firma del bloque; `""` si la clave de la instalación no está (no hay firma que dar)."""
    key = _key()
    if key is None:
        return ""
    return PREFIX + base64.urlsafe_b64encode(_mac(key, destination_id, text or "")).decode().rstrip("=")


def verify(destination_id: str, text: str, signature: Any) -> bool:
    """¿Es una firma propia, de este destino y de este texto? Nunca levanta."""
    try:
        key = _key()
        if key is None or not isinstance(signature, str) or not signature.startswith(PREFIX):
            return False
        raw = signature[len(PREFIX):]
        tag = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        return hmac.compare_digest(tag, _mac(key, destination_id, text or ""))
    except Exception:  # noqa: BLE001 — una firma malformada es una firma ajena
        return False


def needs_replay(destination: Mapping[str, Any]) -> bool:
    """¿El destino exige el razonamiento del turno previo?"""
    declared = (destination.get("provider_options") or {}).get("reasoning_replay")
    if isinstance(declared, bool):
        return declared
    return destination.get("provider") in REPLAY_PROVIDERS


def history_filter(destination: Mapping[str, Any]):
    """Función `bloque -> bloque | None` para la historia de un pedido hacia `destination` (None = descartar)."""
    dest_id = str(destination.get("id"))
    replay = needs_replay(destination)

    def rebuild(block: Mapping[str, Any]):
        if (replay and block.get("type") == "thinking" and isinstance(block.get("thinking"), str)
                and verify(dest_id, block["thinking"], block.get("signature"))):
            return {"type": "thinking", "thinking": block["thinking"]}
        return None
    return rebuild
