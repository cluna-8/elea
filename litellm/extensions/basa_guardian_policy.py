"""basa_guardian_policy — librería PURA de la política Basa (spec 014, FR-022).

Mask reversible de PII con nonce por request, unmask (texto y estructuras), y el
motor de *carry-split* para des-enmascarar streaming sin corromper placeholders
partidos entre chunks. Portada 1:1 del gateway del demo (gatelite
``backend/src/api/gateway.py``) con dos niveles de API:

- **Nivel objeto parseado** (Estrategia A, hooks del motor): ``unmask_delta_event``
  opera sobre eventos Anthropic ya parseados (dicts).
- **Nivel SSE** (Estrategia B / passthrough OAuth del backend): ``rewrite_sse_block``
  opera sobre bloques SSE crudos, construido SOBRE el nivel parseado (DRY).

PURA = sin DB, sin servicios, sin I/O: la detección de entidades se **inyecta** como
callable async (``analyze``). Importable desde el contenedor del motor Y desde el
backend (los dos hogares del plan 014) sin arrastrar dependencias.

El mapa reversible (``ph_to_orig``) vive en memoria del request y JAMÁS se persiste
ni se delega a un tercero (Constitución I, Constraint C1).
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Awaitable, Callable, Optional, Tuple

# Un placeholder es [TYPE_idx_nonce]; TYPE puede contener '_' (EMAIL_ADDRESS).
PH_TYPE_RE = re.compile(r"\[(.+)_\d+_[0-9a-f]+\]$")
# Fragmento colgante que todavía podría crecer hasta ser un placeholder. Los
# placeholders empiezan SIEMPRE con tipo en MAYÚSCULAS ([PERSON_…), así que un '['
# suelto seguido de minúscula/dígito (arr[i, nums[0) NO se retiene.
PH_TAIL_RE = re.compile(r"\[[A-Z][A-Za-z0-9_]*$")
# Máximo largo de un fragmento retenible (un placeholder real nunca supera esto).
MAX_CARRY = 48

# Tipo de delta Anthropic → campo JSON que lleva su texto.
DELTA_FIELDS = {"text_delta": "text", "thinking_delta": "thinking", "input_json_delta": "partial_json"}
FIELD_DELTA = {v: k for k, v in DELTA_FIELDS.items()}

# Firma del detector inyectado: async (text) -> [{"start", "end", "entity_type"}, …]
AnalyzeFn = Callable[[str], Awaitable[list]]


class PlaceholderMap:
    """Asignación consistente valor→placeholder para todo el request.

    El mismo valor original recibe el MISMO placeholder en todo el prompt (el modelo
    ve un texto coherente). El nonce por request evita colisiones con literales que
    el usuario haya tipeado (p.ej. "[PERSON_0]") y hace irreproducibles los tokens.
    """

    def __init__(self, nonce: Optional[str] = None):
        self.nonce = nonce or uuid.uuid4().hex[:4]
        self.orig_to_ph: dict = {}
        self.ph_to_orig: dict = {}
        self._type_counts: dict = {}

    def placeholder_for(self, value: str, entity_type: str) -> str:
        if value in self.orig_to_ph:
            return self.orig_to_ph[value]
        idx = self._type_counts.get(entity_type, 0)
        self._type_counts[entity_type] = idx + 1
        ph = f"[{entity_type}_{idx}_{self.nonce}]"
        self.orig_to_ph[value] = ph
        self.ph_to_orig[ph] = value
        return ph


async def mask_text(text: str, analyze: AnalyzeFn, pmap: PlaceholderMap) -> str:
    """Enmascara un segmento de texto reemplazando cada entidad detectada por su
    placeholder (reemplazo de atrás hacia adelante para no invalidar offsets)."""
    if not text:
        return text
    entities = await analyze(text)
    out = text
    for e in sorted(entities, key=lambda x: x["start"], reverse=True):
        value = text[e["start"]:e["end"]]
        out = out[: e["start"]] + pmap.placeholder_for(value, e["entity_type"]) + out[e["end"]:]
    return out


async def _mask_content(content, analyze: AnalyzeFn, pmap: PlaceholderMap):
    """Enmascara el content de un mensaje (str, o lista con bloques text/tool_result)."""
    if isinstance(content, str):
        return await mask_text(content, analyze, pmap)
    if isinstance(content, list):
        for blk in content:
            if not isinstance(blk, dict):
                continue
            if blk.get("type") == "text" and isinstance(blk.get("text"), str):
                blk["text"] = await mask_text(blk["text"], analyze, pmap)
            elif blk.get("type") == "tool_result":
                tr = blk.get("content")
                if isinstance(tr, str):
                    blk["content"] = await mask_text(tr, analyze, pmap)
                elif isinstance(tr, list):
                    for sub in tr:
                        if isinstance(sub, dict) and sub.get("type") == "text" \
                                and isinstance(sub.get("text"), str):
                            sub["text"] = await mask_text(sub["text"], analyze, pmap)
    return content


async def mask_body(body: dict, analyze: AnalyzeFn,
                    pmap: Optional[PlaceholderMap] = None) -> Tuple[dict, dict]:
    """Enmascara la PII de los turnos USER del request (no el system prompt/tools —
    mismo alcance que el demo). Devuelve (body mutado, mapa placeholder→original)."""
    pmap = pmap or PlaceholderMap()
    for msg in body.get("messages") or []:
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        msg["content"] = await _mask_content(msg.get("content"), analyze, pmap)
    return body, pmap.ph_to_orig


def unmask_text(text: str, ph_to_orig: dict) -> str:
    for ph, orig in ph_to_orig.items():
        if ph in text:
            text = text.replace(ph, orig)
    return text


def unmask_deep(obj, ph_to_orig):
    """Des-enmascara placeholders en cualquier punto de una estructura anidada
    (inputs de tool_use, listas de bloques, etc.)."""
    if isinstance(obj, str):
        return unmask_text(obj, ph_to_orig)
    if isinstance(obj, list):
        return [unmask_deep(x, ph_to_orig) for x in obj]
    if isinstance(obj, dict):
        return {k: unmask_deep(v, ph_to_orig) for k, v in obj.items()}
    return obj


def safe_split(combined: str) -> Tuple[str, str]:
    """Retiene un sufijo SOLO si todavía puede ser un placeholder a medio llegar
    (un [PERSON_0_ab12] real puede venir partido en dos deltas). Un '[' suelto en
    prosa/código (arr[i, [1,2, markdown) se emite ya mismo — el streaming no se
    frena. Devuelve (texto_seguro, carry)."""
    idx = combined.rfind("[")
    if idx != -1 and "]" not in combined[idx:]:
        tail = combined[idx:]
        if PH_TAIL_RE.match(tail) and len(tail) <= MAX_CARRY:
            return combined[:idx], tail
    return combined, ""


def unmask_delta_event(data: dict, carry: str, carry_field: Optional[str],
                       ph_to_orig: dict) -> Tuple[list, str, Optional[str]]:
    """Motor de carry-split sobre un evento Anthropic PARSEADO (dict).

    Devuelve (eventos_de_salida, nuevo_carry, nuevo_carry_field). Los eventos de
    salida son dicts listos para re-serializar; en ``content_block_stop`` el carry
    pendiente se flushea como un delta sintético ANTES del stop (0 texto perdido).
    """
    typ = data.get("type")
    if typ == "content_block_start":
        # Bloque nuevo → cualquier carry previo es stale (defensa; el flush real
        # ocurre en content_block_stop del bloque anterior).
        return [data], "", None
    if typ == "content_block_delta":
        field = DELTA_FIELDS.get((data.get("delta") or {}).get("type"))
        if field:
            combined = carry + (data["delta"].get(field) or "")
            safe, new_carry = safe_split(combined)
            data["delta"][field] = unmask_text(safe, ph_to_orig)
            return [data], new_carry, field
        return [data], carry, carry_field
    if typ == "content_block_stop":
        out = []
        if carry:
            field = carry_field or "text"
            out.append({
                "type": "content_block_delta",
                "index": data.get("index", 0),
                "delta": {"type": FIELD_DELTA[field], field: unmask_text(carry, ph_to_orig)},
            })
        out.append(data)
        return out, "", None
    return [data], carry, carry_field


def rewrite_sse_block(block: str, carry: str, carry_field: Optional[str],
                      ph_to_orig: dict):
    """Reescribe UN evento SSE crudo des-enmascarando los campos de texto
    (text/thinking/partial_json), delegando el carry-split en ``unmask_delta_event``.

    Devuelve (bloques_out, carry, carry_field, in_tok|None, out_tok|None) — los
    tokens de usage se extraen al pasar (los usa el passthrough del backend; en la
    ruta motor el usage lo maneja el motor).
    """
    lines = block.split("\n")
    data_idx = next((i for i, l in enumerate(lines) if l.startswith("data:")), None)
    if data_idx is None:
        return [block], carry, carry_field, None, None
    try:
        data = json.loads(lines[data_idx][5:].strip())
    except Exception:
        return [block], carry, carry_field, None, None

    typ = data.get("type")
    in_tok = out_tok = None
    if typ == "message_start":
        in_tok = ((data.get("message") or {}).get("usage") or {}).get("input_tokens")
    elif typ == "message_delta":
        out_tok = (data.get("usage") or {}).get("output_tokens")

    events, new_carry, new_field = unmask_delta_event(data, carry, carry_field, ph_to_orig)

    out_blocks = []
    for ev in events:
        if ev is data and typ not in ("content_block_delta",):
            # Evento sin cambios de texto → emitir el bloque original intacto.
            out_blocks.append(block)
        elif ev.get("type") == "content_block_delta" and ev is data:
            lines[data_idx] = "data: " + json.dumps(data, ensure_ascii=False)
            out_blocks.append("\n".join(lines))
        else:
            # Evento sintético (flush del carry) — framing SSE mínimo.
            out_blocks.append("event: content_block_delta\ndata: "
                              + json.dumps(ev, ensure_ascii=False))
    return out_blocks, new_carry, new_field, in_tok, out_tok


class StreamUnmasker:
    """Wrapper con estado del carry para consumir streams evento a evento.

    Uso (Estrategia A, objetos parseados):
        um = StreamUnmasker(ph_to_orig)
        for data in eventos_parseados:
            for out in um.feed(data): yield out
    """

    def __init__(self, ph_to_orig: dict):
        self.ph_to_orig = ph_to_orig
        self.carry = ""
        self.carry_field: Optional[str] = None

    def feed(self, data: dict) -> list:
        events, self.carry, self.carry_field = unmask_delta_event(
            data, self.carry, self.carry_field, self.ph_to_orig
        )
        return events

    def flush(self) -> list:
        """Stream truncado (sin content_block_stop): emite el carry pendiente como
        delta sintético para no perder texto."""
        if not self.carry:
            return []
        field = self.carry_field or "text"
        event = {
            "type": "content_block_delta", "index": 0,
            "delta": {"type": FIELD_DELTA[field], field: unmask_text(self.carry, self.ph_to_orig)},
        }
        self.carry, self.carry_field = "", None
        return [event]
