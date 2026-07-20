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
# seguido de minúscula/dígito (arr[i, nums[0) NO se retiene. Un '[' PELADO al final
# del delta SÍ se retiene (un solo delta de espera): los bridges con deltas de 1-3
# chars parten el placeholder justo tras el '[' — root cause del spike 024 (T002).
PH_TAIL_RE = re.compile(r"\[$|\[[A-Z][A-Za-z0-9_]*$")
# Máximo largo de un fragmento retenible (un placeholder real nunca supera esto).
MAX_CARRY = 48

# Tipo de delta Anthropic → campo JSON que lleva su texto.
DELTA_FIELDS = {"text_delta": "text", "thinking_delta": "thinking", "input_json_delta": "partial_json"}
FIELD_DELTA = {v: k for k, v in DELTA_FIELDS.items()}

# Firma del detector inyectado: async (text) -> [{"start", "end", "entity_type"}, …]
AnalyzeFn = Callable[[str], Awaitable[list]]

# ── Detección (portada de los servicios heredados; PURA, sin DB) ──────────────────

# PII por regex (espejo de PresidioService.PATTERNS). Tier demo/dev: el NLP real
# (Presidio) es precondición de prod con PHI (Constraint C2) y llega en la spec 016.
PII_PATTERNS = {
    "EMAIL_ADDRESS": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "PHONE_NUMBER": r"\b(?:\+?54)?[-. ]?\(?\d{2,4}\)?[-. ]?\d{3,4}[-. ]?\d{4}\b",
    "DNI": r"\b\d{2}\.?\d{3}\.?\d{3}\b",
    "CUIL": r"\b\d{2}-\d{8}-\d\b",
    "PERSON": r"\b(?:paciente|doctor|dr|dra|sr|sra|don|doña|afiliado)\s+([A-Z][a-záéíóúñ]+(?:\s+[A-Z][a-záéíóúñ]+)+)\b",
}

# Prácticas prohibidas EU AI Act Art.5 (espejo de ComplianceService.PROHIBITED_KEYWORDS)
PROHIBITED_PATTERNS = [
    r"social\s*scoring", r"score\s*social", r"clasificación\s*social",
    r"subliminal\s*manipulation", r"manipulación\s*subliminal",
    r"biometric\s*categorization", r"categorización\s*biométrica",
]
# Alto riesgo Anexo III (heurístico; solo flag, no bloquea — [D3])
HIGH_RISK_PATTERNS = [
    r"farmacovigilancia\s*automatizada", r"farmacovigilancia\s*autónoma",
    r"decisión\s*regulatoria\s*autónoma", r"decision\s*regulatoria\s*autonoma",
    r"ensayo\s*clínico\s*autónomo", r"ensayo\s*clinico\s*autonomo",
    r"evaluación\s*de\s*crédito", r"credit\s*scoring",
    r"automated\s*hiring", r"evaluación\s*de\s*cv", r"selección\s*de\s*personal\s*automática",
    r"scoring\s*de\s*empleados", r"evaluación\s*automatizada\s*de\s*representantes",
    r"evaluacion\s*automatizada\s*de\s*representantes",
    r"personalización\s*manipuladora", r"personalizacion\s*manipuladora",
]

# Secretos/keys (espejo de GuardianService)
SECRET_PATTERNS = {
    "OpenAI API Key": r"sk-[a-zA-Z0-9]{10,}",
    "Google API Key": r"AIzaSy[a-zA-Z0-9_-]{33}",
    "Generic Secret": r"Bearer\s+[a-zA-Z0-9\-_\.]{20,}",
}

INSPECT_CAP = 16000  # chars entregados a los detectores

# Mapa User-Agent → herramienta (primer match gana; portado 1:1 del demo _TOOL_UA).
# El ORDEN es semántica observable (claude antes que curl, curl antes que httpx).
# Vive acá (lib PURA) para que el passthrough del backend y custom_auth lo compartan.
TOOL_UA = [
    ("claude", "Claude Code"),
    ("copilot", "GitHub Copilot"),
    ("vscode", "VS Code"),
    ("vs code", "VS Code"),
    ("cursor", "Cursor"),
    ("continue", "Continue.dev"),
    ("aider", "aider"),
    ("cline", "Cline"),
    ("roo", "Roo Code"),
    ("codex", "Codex CLI"),
    ("gemini", "Gemini CLI"),
    ("windsurf", "Windsurf"),
    ("postman", "Postman"),
    ("curl", "curl"),
    ("httpx", "API directa"),
    ("python-requests", "API directa"),
    ("node-fetch", "API directa"),
]


def detect_tool(user_agent: Optional[str]) -> str:
    """Herramienta de codeo desde el User-Agent (primer match gana; degrada honesto)."""
    low = (user_agent or "").lower()
    for needle, name in TOOL_UA:
        if needle in low:
            return name
    return "Desconocido"


async def default_analyze(text: str) -> list:
    """Analyzer PII por regex (mismo comportamiento que el PresidioService heredado).
    Inyectable: en prod con PHI se reemplaza por Presidio NLP (spec 016, SC-2)."""
    entities = []
    for entity_type, pattern in PII_PATTERNS.items():
        flags = re.IGNORECASE if entity_type != "PERSON" else 0
        for m in re.finditer(pattern, text, flags):
            start, end = (m.start(1), m.end(1)) if entity_type == "PERSON" else (m.start(), m.end())
            entities.append({"start": start, "end": end,
                             "entity_type": entity_type, "score": 0.95})
    return entities


def evaluate_ai_act(text: str) -> dict:
    """Gate AI-Act: prohibido (Art.5) bloquea; alto riesgo (Anexo III) solo flaggea."""
    if not text:
        return {"status": "passed", "risk_level": "low", "reason": None}
    for pattern in PROHIBITED_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return {"status": "blocked_prohibited", "risk_level": "prohibited",
                    "reason": ("Petición bloqueada por la Ley de IA (AI Act): "
                               f"práctica prohibida detectada ({pattern}).")}
    for pattern in HIGH_RISK_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return {"status": "flagged_high_risk", "risk_level": "high",
                    "reason": ("Advertencia de la Ley de IA: aplicación de alto riesgo "
                               f"detectada ({pattern}). Se requiere supervisión humana.")}
    return {"status": "passed", "risk_level": "low", "reason": None}


def detect_secrets(text: str) -> list:
    """Material secreto (API keys / tokens) que JAMÁS debe salir hacia un LLM."""
    return [name for name, pattern in SECRET_PATTERNS.items()
            if re.search(pattern, text)]


def redact_secrets(text: str) -> str:
    """Reemplaza material secreto por un marcador — para previews/vitrina (Constraint
    C1): una credencial NUNCA debe llegar al monitor ni a Redis, ni siquiera efímera."""
    for pattern in SECRET_PATTERNS.values():
        text = re.sub(pattern, "[SECRET_REDACTED]", text)
    return text


def extract_inspect_text(body: dict, cap: int = INSPECT_CAP) -> str:
    """Texto de los turnos user (str o bloques text/tool_result) para los detectores.
    Mismo alcance que el masking: el system prompt no se inspecciona acá."""
    parts = []
    messages = body.get("messages")
    for msg in messages if isinstance(messages, list) else []:
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for blk in content:
                if isinstance(blk, dict) and isinstance(blk.get("text"), str):
                    parts.append(blk["text"])
    return "\n".join(parts)[:cap]


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
    messages = body.get("messages")
    for msg in messages if isinstance(messages, list) else []:
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


def proxy_identity_from(data: dict) -> dict:
    """Identidad Basa propagada por el proxy (``custom_auth`` →
    ``user_api_key_metadata.basa``), buscada en AMBOS metadata-homes:
    ``litellm_metadata`` (ruta anthropic) y ``metadata`` (el resto) — 024 D3."""
    for key in ("litellm_metadata", "metadata"):
        home = (data or {}).get(key)
        if isinstance(home, dict):
            basa = (home.get("user_api_key_metadata") or {}).get("basa")
            if basa:
                return basa
    return {}


def unmask_response_payload(response, ph_to_orig: dict) -> None:
    """Des-enmascara una respuesta NO-streaming mutándola, sea cual sea su shape:
    ``dict`` plano (rutas bridged del motor — 024 D1) u objeto con atributos
    (passthrough). Cubre ``content`` Anthropic (text/thinking/input) y ``choices``
    OpenAI. Fail-safe: shape no reconocido o sin mapping → no-op, jamás rompe."""
    if not ph_to_orig:
        return
    get = response.get if isinstance(response, dict) else (
        lambda k, d=None: getattr(response, k, d))

    content = get("content")
    if isinstance(content, list):
        for block in content:
            bget = block.get if isinstance(block, dict) else (
                lambda k, d=None, _b=block: getattr(_b, k, d))
            bset = block.__setitem__ if isinstance(block, dict) else (
                lambda k, v, _b=block: setattr(_b, k, v))
            for field in ("text", "thinking"):
                value = bget(field)
                if isinstance(value, str):
                    bset(field, unmask_text(value, ph_to_orig))
            tool_input = bget("input")
            if isinstance(tool_input, (dict, list)):
                bset("input", unmask_deep(tool_input, ph_to_orig))
        return

    choices = get("choices")
    if isinstance(choices, list):
        for choice in choices:
            cget = choice.get if isinstance(choice, dict) else (
                lambda k, d=None, _c=choice: getattr(_c, k, d))
            message = cget("message")
            if message is None:
                continue
            mget = message.get if isinstance(message, dict) else (
                lambda k, d=None, _m=message: getattr(_m, k, d))
            mset = message.__setitem__ if isinstance(message, dict) else (
                lambda k, v, _m=message: setattr(_m, k, v))
            if isinstance(mget("content"), str):
                mset("content", unmask_text(mget("content"), ph_to_orig))


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
