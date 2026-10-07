"""Esfuerzo de razonamiento por destino (057): lo que el pedido pide se ajusta a lo que el destino admite.

Azure `gpt-5.1-chat` solo acepta `reasoning_effort: "medium"` y responde 400 con `low`. El conjunto que admite cada
destino es un dato de su perfil de capacidades (`features.reasoning_efforts`, editable en el catálogo); `KNOWN` trae
el único valor conocido de fábrica para las entradas que no lo declaran. Si el pedido trae un esfuerzo que el destino
no admite se mapea al más cercano que sí, y el ajuste se registra en `adjusted_params` (solo el nombre del campo,
nunca el valor): el usuario no ve un 400 por esto. Sin conjunto declarado ni conocido, el pedido pasa tal cual.

Pura y sin dependencias del motor: la usa la pasarela (`plugin.pre_engine`) para las dos caras.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

# De menos a más. `none`/`minimal` son los extremos bajos de OpenAI; `xhigh` el alto.
SCALE = ("none", "minimal", "low", "medium", "high", "xhigh")
PROFILE_KEY = "reasoning_efforts"
ADJUSTED_NAME = "reasoning_effort"

# Valores conocidos por modelo (nombre del despliegue en minúsculas) cuando la ficha no declara el conjunto.
KNOWN = {"gpt-5.1-chat": ("medium",)}


def _valid(values: Any) -> tuple:
    if not isinstance(values, (list, tuple)):
        return ()
    out: list = []
    for v in values:
        v = v.strip().lower() if isinstance(v, str) else None
        if v in SCALE and v not in out:
            out.append(v)
    return tuple(out)


def supported_efforts(dest: Mapping[str, Any]) -> Optional[tuple]:
    """Esfuerzos que admite el destino: lo declarado en su perfil; si no, el valor conocido del modelo; si no, `None`
    (sin restricción conocida)."""
    declared = _valid((dest.get("capability_profile") or {}).get(PROFILE_KEY))
    if declared:
        return declared
    real = str(dest.get("real_model") or "").rsplit("/", 1)[-1].lower()
    return KNOWN.get(real)


def nearest(value: Any, supported) -> Any:
    """El esfuerzo admitido más cercano a `value` (en el empate, el más bajo). Un valor que no está en la escala, o
    un conjunto vacío, deja el valor como vino."""
    wanted = value.strip().lower() if isinstance(value, str) else None
    allowed = _valid(supported)
    if wanted not in SCALE or not allowed:
        return value
    if wanted in allowed:
        return wanted
    pos = SCALE.index(wanted)
    return min(allowed, key=lambda a: (abs(SCALE.index(a) - pos), SCALE.index(a)))


def adjust(body: dict, dest: Mapping[str, Any]) -> list:
    """Ajusta in situ `reasoning_effort` (chat) y `reasoning.effort` (Responses) al conjunto del destino. Devuelve
    `["reasoning_effort"]` si cambió algo (solo el nombre se audita), `[]` si no."""
    supported = supported_efforts(dest)
    if not supported:
        return []
    changed = False
    current = body.get("reasoning_effort")
    if isinstance(current, str) and nearest(current, supported) != current.strip().lower():
        body["reasoning_effort"] = nearest(current, supported)
        changed = True
    reasoning = body.get("reasoning")
    if isinstance(reasoning, dict) and isinstance(reasoning.get("effort"), str):
        new = nearest(reasoning["effort"], supported)
        if new != reasoning["effort"].strip().lower():
            body["reasoning"] = {**reasoning, "effort": new}
            changed = True
    return [ADJUSTED_NAME] if changed else []
