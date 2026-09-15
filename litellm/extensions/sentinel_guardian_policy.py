"""sentinel_guardian_policy — librería PURA de la política Sentinel (spec 014, FR-022).

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
ni se delega a un tercero POR DEFECTO (Constitución I, Constraint C1). Esa es la
postura para todo despliegue de Sentinel/GuardIAn que NO fije la env var de abajo.

**Excepción explícita, opt-in, decisión de producto de Elea (02-sep)**: para RAG
documental, el enmascarado ocurre en la subida del documento — un request aparte,
mucho antes de cualquier chat que lo consulte — así que sin persistir el mapa en
ningún lado es IMPOSIBLE restaurar el dato real en una respuesta RAG (a diferencia
del chat directo, mask+unmask en el mismo request). Confirmado en vivo (02-sep):
con el mapa solo en memoria, un documento enmascarado correctamente jamás se
desenmascaraba en el chat — ni para DNI/CBU ni para el resto —, contra la
expectativa del producto ("el mismo comportamiento que el chat directo").

``SENTINEL_PII_VAULT_ENABLED=true`` activa una bóveda Redis (``pii_vault_redis``,
abajo) que persiste ``ph_to_orig`` con TTL (``SENTINEL_PII_VAULT_TTL_SECONDS``,
default 90 días) y la consulta en el post-call hook para desenmascarar placeholders
que NO nacieron en el request actual. Default: **OFF** — ningún despliegue existente
cambia de comportamiento sin fijar la env var explícitamente. Best-effort en los dos
sentidos (falla silenciosa con log si Redis no está, nunca rompe el masking ni deja
un placeholder sin resolver como error 500).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import sys
import time
import uuid
from typing import Awaitable, Callable, Optional, Tuple

import httpx

logger = logging.getLogger("sentinel-guardian-policy")

sys.path.insert(0, os.path.dirname(__file__))
try:
    import sentinel_engine_redis  # noqa: E402 — construcción única de clientes Redis con timeouts (#8)
except ImportError:  # pragma: no cover — no debería faltar (mismo directorio), defensivo igual
    sentinel_engine_redis = None

# Un placeholder es [TYPE_idx_nonce]; TYPE puede contener '_' (EMAIL_ADDRESS).
PH_TYPE_RE = re.compile(r"\[(.+)_\d+_[0-9a-f]+\]$")
# Igual que PH_TYPE_RE pero SIN anclar a fin de string — para encontrar TODOS los
# placeholders sueltos dentro de un texto largo (bóveda persistente, más abajo).
PLACEHOLDER_TOKEN_RE = re.compile(r"\[[A-Z][A-Za-z0-9_]*_\d+_[0-9a-f]+\]")
# Fragmento colgante que todavía podría crecer hasta ser un placeholder. Los
# placeholders empiezan SIEMPRE con tipo en MAYÚSCULAS ([PERSON_…), así que un '['
# seguido de minúscula/dígito (arr[i, nums[0) NO se retiene. Un '[' PELADO al final
# del delta SÍ se retiene (un solo delta de espera): los bridges con deltas de 1-3
# chars parten el placeholder justo tras el '[' — root cause del spike 024 (T002).
PH_TAIL_RE = re.compile(r"\[$|\[[A-Z][A-Za-z0-9_]*$")
# Máximo largo de un fragmento retenible (un placeholder real nunca supera esto).
MAX_CARRY = 48
NLP_TIMEOUT_S = float(os.getenv("SENTINEL_NLP_TIMEOUT_S", "15"))

# Tipo de delta Anthropic → campo JSON que lleva su texto.
DELTA_FIELDS = {"text_delta": "text", "thinking_delta": "thinking", "input_json_delta": "partial_json"}
FIELD_DELTA = {v: k for k, v in DELTA_FIELDS.items()}

# Firma del detector inyectado: async (text) -> [{"start", "end", "entity_type"}, …]
AnalyzeFn = Callable[[str], Awaitable[list]]

# ── Detección (portada de los servicios heredados; PURA, sin DB) ──────────────────

# PII por regex — SOLO fallback de dev/demo (ver `default_analyze` más abajo). El
# camino de producción usa `presidio_analyze` (NLP real, spec 016, Constraint SC-2).
# NO sustituye al NLP: los nombres SIN tratamiento siguen necesitando NER real. El fix
# del #64 (piloto Cámara) es que el paracaídas de emergencia no MIENTA mientras actúa.
# Antes tenía un `PHONE_NUMBER` genérico (`\b\+?[0-9][0-9\-. ]{7,14}[0-9]\b`) que
# troceaba un IBAN en DOS falsos `[PHONE_NUMBER]` dejando el prefijo (`ES91`) EN CLARO, y
# etiquetaba facturas (`FAC-2026-001587`) como teléfonos inexistentes → conteos de
# auditoría inflados. Ahora: (a) el teléfono nacional exige estructura real (patrón de
# STRUCTURED_ID_PATTERNS_BY_REGION, primer dígito 6-9 → no engulle IBANs ni importes) y el
# internacional exige prefijo `+`/`00` (empieza por dígito de país, no se pisa con IBANs
# que empiezan por letras — restaura la cobertura intl que perdía el genérico, review R2),
# (b) IBAN/tarjeta se CONFIRMAN con checksum y NIF/NIE por formato, y (c) lo que NO se
# reconoce con confianza se deja SIN TOCAR: mejor un hueco honesto que una etiqueta falsa
# (el NLP real cubre el resto). Etiquetas = tipos canónicos del producto (IBAN_CODE,
# CREDIT_CARD, ES_NIF, ES_NIE; ver el seed EU de guardianes).
#
# EMAIL: local ≤64 y dominio ≤255 chars (topes RFC 5321) + grupo atómico en el local.
# Sin el TOPE, el `+` sobre `[A-Za-z0-9._%+-]` (que incluye `-`) es O(n²) por reintento de
# arranque cuando NO hay `@` (medido: 80KB de `9-` → 17 s). El tope lo vuelve LINEAL (mismo
# input → 28 ms); el grupo atómico mata además el backtracking interno (review R2, #64).
PII_PATTERNS = {
    "EMAIL_ADDRESS": r"\b(?>[A-Za-z0-9._%+-]{1,64})@[A-Za-z0-9.-]{1,255}\.[A-Za-z]{2,}\b",
    "PERSON": r"\b(?:sr|sra|dr|dra|mr|mrs|ms)\.?\s+([A-Z][a-záéíóúñ]+(?:\s+[A-Z][a-záéíóúñ]+)+)\b",
}

# Patrones estructurados por REGIÓN (spec 016 §3, corrección post-review: el
# despliegue objetivo es Europa primero, LATAM/otros después — nunca hardcodear un
# solo país). Se inyectan como `ad_hoc_recognizers` SOLO para lo que Presidio no
# cubre ya con un reconocedor propio validado (checksum) para ese idioma/región:
#   - España: ES_NIF/ES_NIE ya son built-in de Presidio (con checksum) para
#     supported_language="es" — NO se reimplementan acá.
#   - IBAN, tarjetas de crédito, email, PERSON (NER): built-in, multi-región —
#     tampoco se reimplementan.
#   - Pasaporte: sin formato único a nivel UE (varía por país emisor). Se usa un
#     patrón genérico + palabras de contexto ("pasaporte"/"passport") que suben el
#     score en vez de fijar un formato de un solo país — precisión limitada y
#     documentada, mejor que no detectarlo. Ampliar por país es agregar una entrada
#     acá, no reescribir el pipeline.
#   - Teléfono: el built-in de Presidio SÍ es multi-región, pero sólo reconoce el
#     número cuando lleva prefijo internacional. Verificado contra el sidecar real
#     (2026-07-27): "+34 912 345 678" se detecta, "612 345 678" NO. Como el motor usa
#     el NLP en lugar del regex —no además— (`sentinel_guardrail.py` y
#     `guardian_service.py` son if/else), activar el sidecar sin esta entrada DEJA
#     LOS MÓVILES ESPAÑOLES EN CLARO. De ahí el patrón nacional acá abajo: mismo
#     criterio que el pasaporte, se agrega por país sin tocar el pipeline.
STRUCTURED_ID_PATTERNS_BY_REGION = {
    "eu": {
        "PASSPORT": (r"\b[A-Z0-9]{6,9}\b", 0.4, ["pasaporte", "passport", "reisepass", "passeport"]),
        # Numeración española (9 dígitos, primer dígito 6-9: móvil 6/7, fijo 8/9),
        # con prefijo +34/0034 opcional y separadores habituales. Los 9 dígitos que
        # NO empiezan en 6-9 (referencias, importes, expedientes) quedan fuera.
        "PHONE_NUMBER": (r"\b(?:(?:\+|00)\s?34[\s.-]?)?[6-9](?:[\s.-]?\d){8}\b", 0.6,
                         ["teléfono", "telefono", "tel", "móvil", "movil", "llamar",
                          "contacto", "whatsapp"]),
    },
    # LATAM (a habilitar cuando haya despliegues en la región — no activo por default).
    "latam_ar": {
        "DNI": (r"\b\d{2}\.?\d{3}\.?\d{3}\b", 0.85, ["dni", "documento"]),
        "CUIL": (r"\b\d{2}-\d{8}-\d\b", 0.9, ["cuil", "cuit"]),
        "PASSPORT": (r"\b[A-Z]{3}\d{6}\b", 0.75, ["pasaporte"]),
        # CBU (Clave Bancaria Uniforme): 22 dígitos corridos, sin separador estándar.
        # Solo formato (como DNI/CUIL acá arriba, sin checksum mod-10 de las dos
        # secciones) — confirmado como gap real el 31-ago (spec 040): un CBU real
        # quedaba en texto plano en una respuesta del RAG porque este patrón no
        # existía. Palabras de contexto bajan falsos positivos sobre otras corridas
        # largas de dígitos (ids internos, códigos de barra).
        "CBU": (r"\b\d{22}\b", 0.85, ["cbu", "clave bancaria", "cuenta bancaria"]),
    },
}
DEFAULT_REGION = "eu"

# ── Fallback estructurado de detección (dev/demo, #64) ────────────────────────────────
#
# Sólo lo usa `default_analyze` (el paracaídas regex). Va aparte de `PII_PATTERNS` porque
# NO es "match directo": IBAN y tarjeta se CONFIRMAN con checksum (mod-97 / Luhn) — sin
# eso, cualquier corrida de dígitos o token `AA00…` saldría etiquetado como tarjeta/IBAN,
# la mentira exacta que el #64 prohíbe. DNI/NIE y el teléfono nacional son por-país
# (región-aware); IBAN y tarjeta son INTERNACIONALES (no dependen de región).

# Estructurados por-país del fallback. El teléfono NACIONAL REUTILIZA el patrón validado del
# camino NLP (primer dígito 6-9: NO trocea IBANs/importes/expedientes). DNI/NIE por FORMATO
# (8 díg + letra / [XYZ]+7 díg + letra); el checksum de la letra es un extra que sólo el NLP
# real aporta — acá basta el formato para no dejar el documento en claro sin mentir de tipo.
#
# `PHONE_INTL` restaura la cobertura de números NO españoles que el genérico borrado del #64
# cubría (`+44 20 7946 0958`, `+33 1 42 68 53 00`, `+1 202 555 0173`) SIN reintroducir el
# sobre-matcheo: EXIGE prefijo `+`/`00` + dígito de país 1-9. Como arranca por `+`/`00` y los
# IBANs por letras y las facturas sin prefijo, no se pisan (review R2). La etiqueta que emite
# es `PHONE_NUMBER` (ver `default_analyze`): `PHONE_INTL` es sólo la clave del patrón.
# INVARIANTE (FR-015): este diccionario tiene que cubrir las MISMAS regiones que
# `STRUCTURED_ID_PATTERNS_BY_REGION`. La resolución de abajo es
# `FALLBACK_STRUCTURED_BY_REGION.get(region, {})`: una región que falte acá NO hereda `eu`,
# se queda con `{}` — o sea, el paracaídas pierde TODA la detección estructurada justo
# cuando ya falló algo. Se encontró así el 15-sep-2026: `latam_ar` existía en la tabla de
# arriba y faltaba acá, y una instalación argentina en modo degradado no detectaba ni DNI,
# ni CUIL, ni CBU (ni los europeos). `test_paracaidas_espeja_regiones` falla si alguien
# agrega una región arriba y se olvida acá.
#
# Ojo con qué se copia: acá NO hay palabras de contexto ni score — es regex puro sobre el
# texto. Por eso `eu` deja PASSPORT afuera a propósito (su patrón es `[A-Z0-9]{6,9}`, que
# sin contexto matchea casi cualquier token) y `latam_ar` sí lo incluye (`[A-Z]{3}\d{6}` es
# lo bastante específico para ir solo). Los patrones se toman de la tabla de arriba con
# `[0]` para que no puedan divergir.
# Entidades que una región tiene en la tabla principal y NO van al paracaídas, con el
# motivo. La simetría del espejo es de REGIONES, no de ENTIDADES: acá no hay palabras de
# contexto ni score, es regex puro sobre el texto, así que un patrón laxo que arriba se
# sostiene con contexto abajo se vuelve una máquina de falsos positivos.
_FUERA_DEL_PARACAIDAS = {
    # `[A-Z0-9]{6,9}` sin contexto matchea casi cualquier token en mayúsculas.
    "eu": {"PASSPORT"},
}


def _desde_principal(region: str, *entidades: str) -> dict:
    """Patrones de `STRUCTURED_ID_PATTERNS_BY_REGION[region]`, salteando los que falten.

    DEFENSIVO A PROPÓSITO, y el motivo es concreto (15-sep-2026): este archivo es de la
    BASE y lo comparten localizaciones con perfiles DESIGUALES — Eleia tiene `CBU` en
    `latam_ar` y Sentinel no. Con acceso directo (`[...]["CBU"][0]`) este diccionario, que
    es un literal a nivel de módulo, levanta `KeyError` EN EL IMPORT: no es "falta una
    entidad", es el módulo de enmascarado sin cargar, o sea el firewall caído al arranque.
    Lo detectó la sesión de Sentinel al intentar traer este arreglo.

    Saltear lo ausente también desacopla: el arreglo del paracaídas deja de depender de que
    haya bajado antes el commit que agregó la entidad.
    """
    principal = STRUCTURED_ID_PATTERNS_BY_REGION.get(region, {})
    return {e: principal[e][0] for e in entidades if e in principal}


_TELEFONO_INTL = r"(?<![\w+])(?:\+|00)[1-9]\d{0,2}(?:[\s.\-]?\d){6,14}\b"

FALLBACK_STRUCTURED_BY_REGION = {
    "eu": {
        **_desde_principal("eu", "PHONE_NUMBER"),
        "PHONE_INTL": _TELEFONO_INTL,
        "ES_NIF": r"\b\d{8}[A-Za-z]\b",
        "ES_NIE": r"\b[XYZxyz]\d{7}[A-Za-z]\b",
    },
    "latam_ar": {
        **_desde_principal("latam_ar", "DNI", "CUIL", "CBU", "PASSPORT"),
        # El teléfono argentino no está en la tabla de arriba (Presidio lo cubre con
        # prefijo internacional), así que acá va sólo el internacional, igual que en `eu`.
        "PHONE_INTL": _TELEFONO_INTL,
    },
}
# Clave del patrón fallback → etiqueta canónica emitida (cuando difieren). El teléfono
# internacional se detecta con un patrón propio pero cuenta como PHONE_NUMBER en auditoría.
_FALLBACK_LABEL = {"PHONE_INTL": "PHONE_NUMBER"}

# Corridas estructuradas del fallback fail-safe (decisión JF, opción A — ver
# `_structured_id_spans`). NO se busca dónde empieza/termina el identificador dentro de la
# corrida (eso, con checksum + fronteras, fue el origen de TRES variantes de fuga: R1 sufijo,
# R2/R3 partición de grupos, R3 dígito pegado al primer grupo). Se enmascara la corrida
# ENTERA. Patrones LINEALES (cada iteración consume ≥1 char, clases disjuntas → sin ReDoS).
# El separador interno es CUALQUIER carácter no alfanumérico (`[^0-9A-Za-z]`), no sólo
# espacio/guión: cualquier otro separador (punto, barra, coma, NBSP U+00A0, narrow-NBSP
# U+202F, salto de línea, mixtos) fracturaba la corrida en trozos bajo el umbral y fugaba el
# número ENTERO en claro (4ª clase de fuga, hallada por el gate adversarial). Con el separador
# genérico ningún carácter puede fracturar la corrida — cierre del family POR CONSTRUCCIÓN.
#   - Tarjeta: cualquier corrida de dígitos separados por ≤1 no-alfanumérico.
#   - IBAN: corrida que arranca por país (2 letras) + 2 dígitos de control. El ancla admite
#     un no-alfanumérico antes de cada dígito de control (`(?:[^0-9A-Za-z]?\d){2}`) para NO
#     fugar IBANs en grupos no estándar (`MT 84 …`, `MT8 4…`) que parten el par de control;
#     NO relaja las 2 letras iniciales, así una palabra en mayúsculas delante (`IBAN ES91…`)
#     no se traga el identificador (el ancla arranca en `ES91`, no en `IB`).
# Residual ACEPTADO (JF, «ruidoso pero seguro»): un separador de ≥2 code-points (doble
# espacio, ` - `, ` . `, `\r\n`, un emoji multi-codepoint —bandera/ZWJ/keycap—, o una LETRA
# ASCII intercalada entre dígitos) todavía fractura la corrida, porque `[^0-9A-Za-z]?` consume
# UN solo carácter. Sólo cruza el umbral de fuga (≥6 díg en claro) con un PAN SIN agrupar
# (8+8): el formato realista —grupos de 4 con cualquier separador simple— nunca deja ≥6 en
# claro. NO se ensancha a multi-char a propósito: bridgearía números distantes en prosa
# (`1234 y 5678 y …`) y sobre-enmascararía texto legítimo, peor trade que un leak no realista.
# Aceptable para un paracaídas de degrade/dev — el NLP real es el detector de producción. El
# conteo de unidades usa `c.isalnum()` (el separador ya no es un set fijo, no se puede contar
# por exclusión de un `_SEP_CHARS`).
_CARD_RUN_RE = re.compile(r"\d(?:[^0-9A-Za-z]?\d)*")
_IBAN_RUN_RE = re.compile(r"\b[A-Z]{2}(?:[^0-9A-Za-z]?\d){2}(?:[^0-9A-Za-z]?[A-Z0-9])*")
_CARD_MIN_DIGITS = 13   # longitud mínima de una tarjeta (≥13 cubre también corridas largas)
_IBAN_MIN_ALNUM = 15    # IBAN más corto (Noruega); sin tope superior a propósito (fail-safe)


# `_luhn_ok` / `_iban_ok`: los checksums YA NO gobiernan la detección del fallback (opción A:
# el paracaídas nunca deja pasar algo que PODRÍA ser tarjeta/IBAN, aunque no valide). Se
# conservan como utilidades puras — las usan los scripts de verificación del gate para
# construir/validar tarjetas de test — pero `default_analyze` no las llama.
def _luhn_ok(candidate: str) -> bool:
    """Checksum Luhn (utilidad de test; la detección fail-safe ya no depende de él)."""
    if any(not (c.isdigit() or c in " -") for c in candidate):
        return False
    digits = [int(c) for c in candidate if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _iban_ok(candidate: str) -> bool:
    """Checksum mod-97 ISO 13616 (utilidad de test; la detección fail-safe ya no lo llama)."""
    s = re.sub(r"\s", "", candidate).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s):
        return False
    rearranged = s[4:] + s[:4]
    try:
        numeric = "".join(str(int(ch, 36)) for ch in rearranged)  # A→10 … Z→35, dígitos igual
    except ValueError:
        return False
    return int(numeric) % 97 == 1


def _merge_spans(spans: list) -> list:
    """Une los (start, end) que se solapan en tramos disjuntos (unión de intervalos)."""
    if not spans:
        return []
    spans = sorted(spans)
    merged = [spans[0]]
    for s, e in spans[1:]:
        ls, le = merged[-1]
        if s <= le:
            merged[-1] = (ls, max(le, e))
        else:
            merged.append((s, e))
    return merged


def _structured_id_spans(text: str, run_re, min_units: int) -> list:
    """`[(start, end)]` a enmascarar: cada CORRIDA de `run_re` cuyo nº de unidades (chars no
    separador: dígitos para tarjeta, alnum para IBAN) alcance `min_units` se enmascara ENTERA.

    FAIL-SAFE (decisión JF, opción A). No hay checksum ni sub-escaneo de fronteras: buscar
    dónde empieza/termina el identificador DENTRO de la corrida fue el origen de las tres
    variantes de fuga (R1 sufijo colgando; R2/R3 partición entre grupos; R3 dígito pegado al
    primer grupo). Al tapar la corrida completa es IMPOSIBLE, por construcción, dejar un tramo
    del PAN/IBAN en claro. Umbral por longitud (≥13 díg / ≥15 alnum) SIN tope superior: una
    corrida larga (dos tarjetas pegadas, un ID de 40 dígitos) se enmascara igual, entera.

    Precio ACEPTADO (JF, «ruidoso pero seguro»): un número legítimo largo (un nº de pedido de
    16 dígitos) cae como CREDIT_CARD en el camino de degrade/dev. Sobre-enmascara, nunca fuga.
    El NLP real (camino de producción) es quien distingue con precisión; esto es el paracaídas.

    Coste O(len) por corrida (contar unidades + un span) ⇒ lineal, sin sub-escaneo ni ReDoS."""
    spans = []
    for m in run_re.finditer(text):
        run = m.group()
        if sum(1 for c in run if c.isalnum()) >= min_units:
            spans.append((m.start(), m.end()))
    return _merge_spans(spans)


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


async def default_analyze(text: str, region: str = DEFAULT_REGION) -> list:
    """Analyzer PII por regex — SOLO fallback explícito de dev/demo cuando no hay
    `NLP_ANALYZER_URL` configurada. NUNCA es el detector del camino de producción
    (spec 016, Constraint SC-2): no distingue nombres sin tratamiento y es lossy por
    diseño. Ante coincidencias solapadas pasa igual por `resolve_overlaps`.

    `region` (opcional, retrocompatible) elige los estructurados por-país; IBAN y tarjeta
    son internacionales y se detectan siempre. IBAN y tarjeta van por FAIL-SAFE (opción A,
    decisión JF): se enmascara la corrida entera que PODRÍA ser una tarjeta/IBAN, sin
    checksum — ruidoso pero imposible de fugar (ver `_structured_id_spans`). NIF/NIE por
    formato. `resolve_overlaps` desempata solapes (gana el más largo → el IBAN, que contiene
    a la corrida de dígitos de su cuerpo, tapa el falso CREDIT_CARD sobre esos mismos dígitos).

    TODO(región): no se threadea `SENTINEL_ENTITY_REGION` desde los call-sites (misma postura
    YAGNI que `sentinel_guardrail`): hoy el único despliegue es eu y el default lo cubre.
    Cuando haya otra región activa, pasar `region` desde `_build_analyze`/el guardrail."""
    entities = []
    patterns = dict(PII_PATTERNS)
    patterns.update(FALLBACK_STRUCTURED_BY_REGION.get(region, {}))
    for entity_type, pattern in patterns.items():
        flags = 0 if entity_type == "PERSON" else re.IGNORECASE
        label = _FALLBACK_LABEL.get(entity_type, entity_type)   # PHONE_INTL → PHONE_NUMBER
        for m in re.finditer(pattern, text, flags):
            start, end = (m.start(1), m.end(1)) if entity_type == "PERSON" else (m.start(), m.end())
            entities.append({"start": start, "end": end,
                             "entity_type": label, "score": 0.95})
    # IBAN y tarjeta: fail-safe (opción A) — cualquier corrida que PODRÍA serlo se enmascara
    # ENTERA (`_structured_id_spans`), sin checksum. IBAN primero: al ser más largo (incluye
    # las 2 letras de país) gana en `resolve_overlaps` sobre el CREDIT_CARD que la regla de
    # tarjeta pondría sobre los dígitos del cuerpo del IBAN.
    for etype, run_re, min_units in (("IBAN_CODE", _IBAN_RUN_RE, _IBAN_MIN_ALNUM),
                                     ("CREDIT_CARD", _CARD_RUN_RE, _CARD_MIN_DIGITS)):
        for start, end in _structured_id_spans(text, run_re, min_units):
            entities.append({"start": start, "end": end, "entity_type": etype, "score": 0.95})
    return resolve_overlaps(entities)


class NlpUnavailableError(Exception):
    """El motor de detección NLP real no respondió (timeout/error/formato inesperado).

    Contrato fail-closed (spec 016 FR-004, decisión del usuario): el caller (el
    guardrail) DEBE traducir esto en un bloqueo de la request — jamás en `[]`
    silencioso. Reemplaza el `except: return []` fail-open heredado de
    `PresidioService.analyze_text_http`.

    Desde el issue #63 el "bloqueo" deja de ser la ÚNICA salida: sigue siendo el
    default, pero la instalación puede elegir degradar a regex de forma RUIDOSA
    (ver `resolve_nlp_fail_mode`). Lo que queda prohibido para siempre es lo que el
    issue denuncia: degradar en silencio.
    """


# ── Política ante analyzer NLP caído (issue #63) ─────────────────────────────────────
#
# Vocabulario COMPARTIDO por los dos planos (motor `sentinel_guardrail` y backend `/gw`), y por
# eso vive acá y no en cada uno: el bug del #63 era justamente que cada plano decidía por su
# cuenta qué hacer sin el NLP (el motor bloqueaba, el backend ni siquiera lo usaba). Con una
# sola fuente, "qué pasa si el detector real no está" es UNA respuesta para todo el producto.
NLP_FAIL_BLOCK = "block"
NLP_FAIL_DEGRADE = "degrade"
NLP_FAIL_MODES = (NLP_FAIL_BLOCK, NLP_FAIL_DEGRADE)
# Clave dentro de `Guardian.config` del guardián `pii_masking`. NO es la columna
# `Guardian.fail_mode` (ésa tiene otra semántica: los guardrails delegados al motor).
NLP_FAIL_MODE_KEY = "nlp_fail_mode"

# Estados de compliance del pedido. Cerrados y compartidos para que la fila durable, el
# evento de la vitrina y el mensaje al cliente digan la MISMA palabra en los dos planos.
STATUS_NLP_BLOCKED = "blocked_nlp_unavailable"
STATUS_NLP_DEGRADED = "degraded_nlp_regex"

# Mensaje único del rechazo fail-closed (lo emiten el motor y el gateway, verbatim).
NLP_BLOCK_MESSAGE = ("Petición bloqueada: el motor de detección de datos personales "
                     "no está disponible. No se procesa sin garantía de protección de PII/PHI.")


def resolve_nlp_fail_mode(config: Optional[dict]) -> str:
    """`block` | `degrade` — qué hacer cuando el analyzer NLP no responde (issue #63).

    Lee `config["nlp_fail_mode"]`; `config` puede ser el `Guardian.config` del guardián
    `pii_masking` o el dict de identidad que lo transporta (ambos llevan la misma clave).

    **Default `block` ante clave ausente, valor vacío o valor no reconocido** — mismo patrón
    defensivo que `resolve_entity_action`, y por la misma razón: una configuración incompleta
    o mal tipeada NUNCA puede convertirse en menos protección. Es además lo que exige la
    Constitución (Principio I, regla (d): «nunca solo regex en producción con PHI») y lo que
    el motor viene haciendo desde la spec 016. Degradar es legítimo, pero tiene que ser una
    decisión ESCRITA del administrador, no el resultado de que falte una clave.

    Consecuencia deliberada para instalaciones ya existentes: su guardián `pii_masking` no
    tiene la clave, así que resuelven `block` sin migración-on-read ni pisar su config.
    """
    raw = (config or {}).get(NLP_FAIL_MODE_KEY)
    if isinstance(raw, str):
        raw = raw.strip().lower()
    return raw if raw in NLP_FAIL_MODES else NLP_FAIL_BLOCK


# ── Región de patrones estructurados por tenant (extensión de spec 016) ─────────────
#
# Hasta acá `region` se leía SOLO de `SENTINEL_ENTITY_REGION` (env var fija por contenedor,
# ver git blame de sentinel_guardrail.py): correcto mientras el único despliegue era Europa
# (YAGNI declarado en el propio comentario). Con países/clientes reales entrando por
# perfil de configuración (ADR-0001, `deploy/clients/`), la región deja de ser una
# propiedad de LA INSTALACIÓN y pasa a ser una propiedad de CADA TENANT dentro de ella
# (un partner puede alojar clientes de más de un país). Mismo mecanismo que
# `nlp_fail_mode`: clave en `Guardian.config` del guardián `pii_masking`, viaja por el
# mismo `identity` que ya carga `entity_configs`/`custom_names`/`custom_entities`.
REGION_KEY = "region"


def resolve_region(config: Optional[dict], default: str = DEFAULT_REGION) -> str:
    """Región de `STRUCTURED_ID_PATTERNS_BY_REGION` activa para este tenant.

    Lee `config["region"]`; `config` es el mismo dict de identidad que ya transporta
    `nlp_fail_mode` (Guardian.config del guardián `pii_masking`, o el dict de identidad
    que lo espeja). Ausente, vacía o no reconocida ⇒ `default` — mismo patrón defensivo
    que `resolve_nlp_fail_mode`: una config incompleta o mal tipeada NUNCA puede
    resolver una región arbitraria (un typo no puede activar/desactivar reconocedores
    de otro país por accidente).

    `default` es de responsabilidad del CALLER, no de esta función: el motor lo arma
    como `SENTINEL_ENTITY_REGION` (la región de LA INSTALACIÓN, retrocompatible con
    despliegues existentes que no configuraron `region` en ningún tenant) o
    `DEFAULT_REGION` si esa env var tampoco está. Así una instalación ya en producción
    con `SENTINEL_ENTITY_REGION=latam_ar` no cambia de comportamiento el día que este campo
    se agrega: sigue resolviendo `latam_ar` para todo tenant que no fije su propio valor.
    """
    raw = (config or {}).get(REGION_KEY)
    if isinstance(raw, str):
        raw = raw.strip().lower()
    return raw if raw in STRUCTURED_ID_PATTERNS_BY_REGION else default


def resolve_overlaps(entities: list) -> list:
    """Resuelve entidades detectadas cuyos rangos [start, end) se solapan (FR-009).

    Algoritmo (merge de intervalos, invariante garantizada incluso con 3+ entidades
    solapadas en cadena, no solo pares): se agrupan en clusters transitivos por
    barrido ordenado (si A solapa B y B solapa C, los tres van al mismo cluster
    aunque A y C no se toquen directamente) y de cada cluster sobrevive UNA sola
    entidad: la de mayor `(end - start)` — gana la más larga/específica, evita que
    un match genérico gane sobre uno más preciso que lo contiene —, a igual largo
    gana mayor `score`, a empate total gana la que apareció primero (estable).
    Como los clusters son componentes conexas maximales del grafo de solapamiento,
    los sobrevivientes de clusters distintos NUNCA se solapan entre sí.

    Sin esto, dos o más coincidencias solapadas (p.ej. un teléfono y un DNI sobre el
    mismo tramo de dígitos) pueden corromper el texto enmascarado, porque el
    reemplazo por offsets asume rangos disjuntos.
    """
    if not entities:
        return []
    indexed = list(enumerate(entities))
    ordered = sorted(indexed, key=lambda pair: pair[1]["start"])

    clusters: list = []
    cluster_end = None
    for orig_idx, ent in ordered:
        if clusters and ent["start"] < cluster_end:
            clusters[-1].append((orig_idx, ent))
            cluster_end = max(cluster_end, ent["end"])
        else:
            clusters.append([(orig_idx, ent)])
            cluster_end = ent["end"]

    survivors = [
        max(cluster, key=lambda pair: (pair[1]["end"] - pair[1]["start"], pair[1].get("score", 0.0), -pair[0]))
        for cluster in clusters
    ]
    survivors.sort(key=lambda pair: pair[0])
    return [ent for _, ent in survivors]


def resolve_entity_action(entity_type: str, entity_configs: Optional[dict]) -> str:
    """Acción configurada para un tipo de entidad en la SecurityPolicy activa
    (FR-005/FR-008). Default `MASK` para tipos ausentes o con valor no reconocido —
    nunca deja pasar una entidad detectada en crudo por omisión de configuración."""
    action = (entity_configs or {}).get(entity_type)
    return action if action in ("MASK", "BLOCK") else "MASK"


def build_ad_hoc_recognizers(custom_names: Optional[list] = None, region: str = DEFAULT_REGION,
                             custom_entities: Optional[list] = None) -> list:
    """Única fuente de los reconocedores que viajan en cada `/analyze` (spec 016 §3):
    SOLO lo que Presidio no cubre ya con un reconocedor propio validado para el
    idioma/región (ver comentario de `STRUCTURED_ID_PATTERNS_BY_REGION`) + deny-list
    de nombres personalizados (`Guardian.config.custom_names`) si hay alguno +
    entidades custom del catálogo (`Guardian.config.custom_entities`, agregadas vía
    panel/asistente de IA — `backend/src/services/entity_catalog_service.py`; solo
    `status == "active"`, nunca borradores sin revisar). `region` selecciona el set
    de patrones estructurados (default: Europa)."""
    patterns_for_region = STRUCTURED_ID_PATTERNS_BY_REGION.get(region, {})
    recognizers = [
        {
            "name": f"SENTINEL_{entity_type}",
            "supported_language": "es",
            "supported_entity": entity_type,
            "patterns": [{"name": f"{entity_type.lower()}_pattern", "regex": pattern, "score": score}],
            "context": context,
        }
        for entity_type, (pattern, score, context) in patterns_for_region.items()
    ]
    names = [n.strip() for n in (custom_names or []) if n and n.strip()]
    if names:
        recognizers.append({
            "name": "SENTINEL_CUSTOM_NAMES",
            "supported_language": "es",
            "supported_entity": "PERSON",
            "deny_list": names,
        })
    for entity in (custom_entities or []):
        if entity.get("status") != "active" or not entity.get("regex"):
            continue
        recognizers.append({
            "name": f"SENTINEL_CUSTOM_{entity.get('entity_type', 'CUSTOM')}",
            "supported_language": "es",
            "supported_entity": entity.get("entity_type", "CUSTOM"),
            "patterns": [{"name": "custom_pattern", "regex": entity["regex"],
                         "score": entity.get("score", 0.5)}],
            "context": entity.get("context") or [],
        })
    return recognizers


_http_client: Optional[httpx.AsyncClient] = None


def _get_http_client() -> httpx.AsyncClient:
    """Cliente httpx módulo-level, reusado entre llamadas a `presidio_analyze` (#167):
    instanciar un `AsyncClient` nuevo por request agotaba sockets en TIME_WAIT (46
    medidos en el issue). Lazy-init en el PRIMER uso — nunca en import-time, donde no
    hay loop corriendo (o es el equivocado) — así el cliente queda ligado al loop del
    motor ya vivo. Sin `timeout` fijo acá: el timeout es SIEMPRE por-request (ver
    `presidio_analyze`), dos llamadas pueden pedir valores distintos.

    Sin `aclose()` en el camino normal, a propósito: es un singleton de proceso, vive
    tanto como el motor. Los tests lo resetean a `None` entre corridas (fixture
    `_reset_presidio_http_client_singleton` en conftest.py) para no dejarlo atado al
    event loop de un test ya terminado."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient()
    return _http_client


async def presidio_analyze(text: str, analyzer_url: str, custom_names: Optional[list] = None,
                           region: str = DEFAULT_REGION, timeout: Optional[float] = None,
                           custom_entities: Optional[list] = None) -> list:
    # timeout subido de 2.0 -> 15.0 (31-ago, cliente RAG): medido en vivo, el spaCy
    # es_core_news_md real procesa ~330 caracteres/segundo por CPU (1 core al 100%) —
    # un texto de 6KB, nada exótico, ya tardaba 18s y el fail-closed lo bloqueaba
    # como si el analyzer estuviera caído. 15s no es "más rápido", es dejar de
    # confundir "lento pero real" con "no disponible". Documentos grandes se
    # troceean del lado del cliente (spec 040) — cada trozo individual sigue
    # entrando en este margen con un cómputo real, no forzado.
    """`AnalyzeFn` real (spec 016): llama al sidecar de detección NLP. Fail-closed
    estricto — cualquier falla de red/formato levanta `NlpUnavailableError`, NUNCA
    devuelve `[]` (contracts/presidio-analyzer-http.md). `entities=None` en el
    payload: se piden TODOS los tipos que el Analyzer soporte para el idioma (built-in
    + ad-hoc) — cobertura amplia de "todo lo que no cumpla GDPR", no una lista fija."""
    if not text:
        return []
    # Spec 050 (14-sep): configurable por env. Presenton manda prompts largos (HTML de una
    # diapositiva) y a ~330 chars/s el analyzer supera los 15 s → fail-closed "no disponible".
    # Default 15 (sin cambios); en las instalaciones con motores de generación se sube a 60.
    if timeout is None:
        timeout = NLP_TIMEOUT_S
    payload = {
        "text": text,
        "language": "es",
        "entities": None,
        "ad_hoc_recognizers": build_ad_hoc_recognizers(custom_names, region, custom_entities),
    }
    t0 = time.monotonic()
    try:
        client = _get_http_client()
        r = await client.post(f"{analyzer_url.rstrip('/')}/analyze", json=payload,
                              timeout=timeout)
        r.raise_for_status()
        raw = r.json()
    except Exception as e:
        # `str(e)` puede salir VACÍO (p.ej. un httpx.ReadTimeout sin argumentos): el
        # mensaje no puede depender de eso o el fallo queda mudo (ni causa ni cuánto
        # tardó). El tipo + el elapsed SIEMPRE están, pase lo que pase con str(e).
        elapsed = time.monotonic() - t0
        msg = (f"{type(e).__name__} tras {elapsed:.3f}s contra {analyzer_url} "
               f"(timeout={timeout}s)")
        detalle = str(e)
        if detalle:
            msg = f"{msg}: {detalle}"
        logger.warning("Presidio Analyzer no disponible: %s", msg)
        raise NlpUnavailableError(msg) from e

    if not isinstance(raw, list):
        raise NlpUnavailableError(f"respuesta inesperada del Analyzer: {type(raw)!r}")

    entities = [
        {"start": e["start"], "end": e["end"], "entity_type": e["entity_type"], "score": e.get("score", 0.0)}
        for e in raw
    ]
    return resolve_overlaps(entities)


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

    Spec 043 (US3, T038/T039): ``document_id`` opcional resuelve el bug reportado por el
    cliente Elea — "el mismo nombre se enmascara distinto en filas separadas del mismo
    CSV" (diagnostico.md §2 de la 043). Causa raíz: el cliente trocea documentos grandes en
    varias llamadas HTTP, y cada una crea su PROPIA ``PlaceholderMap`` (nonce aleatorio +
    contador que arranca en 0) — dos chunks del mismo documento nunca compartían nonce ni
    índice. Con ``document_id``, tanto el nonce como el índice se DERIVAN por HMAC del
    documento (nunca del valor solo, y nunca con I/O — sigue siendo PURA): dos chunks del
    MISMO documento con el MISMO valor detectado producen el MISMO placeholder sin
    necesitar estado compartido entre instancias; dos documentos distintos (incluso con
    idéntico contenido) producen placeholders distintos porque el HMAC usa ``document_id``
    como clave — no se crea un seudónimo estable ENTRE documentos (decisión sellada por el
    dueño del producto el 08-sep: eso sería una enmienda constitucional aparte, C1, no una
    continuación técnica de este bug). Sin ``document_id`` (el caso de la extensión de
    navegador y de cualquier otro cliente del despliegue compartido), el comportamiento es
    EXACTAMENTE el de antes — nonce aleatorio, contador secuencial — sin regresión (FR-021).
    """

    def __init__(self, nonce: Optional[str] = None, document_id: Optional[str] = None):
        self.document_id = document_id
        if document_id:
            # Determinista por documento: mismo document_id → mismo nonce siempre.
            self.nonce = nonce or hmac.new(
                document_id.encode(), b"sentinel-placeholder-nonce", hashlib.sha256
            ).hexdigest()[:4]
        else:
            self.nonce = nonce or uuid.uuid4().hex[:4]
        self.orig_to_ph: dict = {}
        self.ph_to_orig: dict = {}
        self._type_counts: dict = {}

    def _deterministic_index(self, value: str, entity_type: str, probe: int = 0) -> int:
        """Índice derivado por HMAC(document_id, tipo|valor|probe) — no un contador
        secuencial, porque distintos chunks del mismo documento son instancias DISTINTAS
        de PlaceholderMap y no comparten memoria. `probe` (default 0) es el eslabón de
        `placeholder_for` para resolver una colisión sin romper el determinismo: mismo
        valor, mismo `probe` → mismo índice, siempre.

        Bug real encontrado en revisión (09-sep): acotado antes a 4 dígitos (mod 10.000)
        — con la paradoja del cumpleaños, la probabilidad de colisión entre dos valores
        DISTINTOS del mismo tipo ya ronda el 50% a partir de ~118 valores en un mismo
        chunk (hasta 4000 caracteres, gramática `[TIPO_n_hex]` sin cambios). Ensanchado a
        8 dígitos (mod 100.000.000): la misma probabilidad recién se acerca al 50% con
        ~11.700 valores distintos del mismo tipo — físicamente imposible en un chunk de
        4000 caracteres. `placeholder_for` además prueba (`probe`) hasta encontrar un
        índice libre como respaldo, así que la colisión queda cerrada en los dos niveles:
        astronómicamente improbable, y si ocurriera, resuelta sin pisar el placeholder de
        otro valor."""
        digest = hmac.new(
            self.document_id.encode(),
            f"{entity_type}|{value}|{probe}".encode(),
            hashlib.sha256,
        ).digest()
        return int.from_bytes(digest[:5], "big") % 100_000_000

    def placeholder_for(self, value: str, entity_type: str) -> str:
        if value in self.orig_to_ph:
            return self.orig_to_ph[value]
        if self.document_id:
            probe = 0
            idx = self._deterministic_index(value, entity_type, probe)
            ph = f"[{entity_type}_{idx}_{self.nonce}]"
            # Colisión real (índice ya usado por OTRO valor en esta misma instancia):
            # reintentar con el siguiente probe — determinista, nunca aleatorio, así que
            # el mismo valor sigue resolviendo al mismo placeholder en cualquier chunk
            # que no haya visto la misma colisión previa.
            while ph in self.ph_to_orig and self.ph_to_orig[ph] != value:
                probe += 1
                idx = self._deterministic_index(value, entity_type, probe)
                ph = f"[{entity_type}_{idx}_{self.nonce}]"
        else:
            idx = self._type_counts.get(entity_type, 0)
            self._type_counts[entity_type] = idx + 1
            ph = f"[{entity_type}_{idx}_{self.nonce}]"
        self.orig_to_ph[value] = ph
        self.ph_to_orig[ph] = value
        return ph


async def mask_text(text: str, analyze: AnalyzeFn, pmap: PlaceholderMap) -> str:
    """Enmascara un segmento de texto reemplazando cada entidad detectada por su
    placeholder (reemplazo de atrás hacia adelante para no invalidar offsets).

    `resolve_overlaps` se llama ACÁ TAMBIÉN (T031, defensa en profundidad) — antes
    se confiaba en que el `analyze` inyectado (`default_analyze`/`presidio_analyze`)
    ya lo hubiera resuelto, pero `mask_text` no lo garantizaba por sí mismo: un
    `AnalyzeFn` que no llame a `resolve_overlaps` (encontrado escribiendo un test de
    stress con un analyzer de prueba deliberadamente "ingenuo") corrompía igual el
    texto. Llamarlo de nuevo sobre una lista ya disjunta es no-op barato — más
    seguro que confiar en un contrato implícito entre funciones."""
    if not text:
        return text
    entities = resolve_overlaps(await analyze(text))
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
    if PII_VAULT_ENABLED:
        await persist_placeholder_map(pmap.ph_to_orig)
    return body, pmap.ph_to_orig


# ── Bóveda persistente opt-in (ver docstring del módulo) ──────────────────────────────
PII_VAULT_ENABLED = os.environ.get("SENTINEL_PII_VAULT_ENABLED", "false").strip().lower() in (
    "1", "true", "yes", "on")
PII_VAULT_PREFIX = "sentinel:pii_vault:"
PII_VAULT_TTL_SECONDS = int(os.environ.get("SENTINEL_PII_VAULT_TTL_SECONDS", str(90 * 24 * 3600)))
_REDIS_HOST_DEFAULT = "eu-redis"


def _pii_vault_redis_endpoint() -> Tuple[str, int]:
    return os.getenv("REDIS_HOST", _REDIS_HOST_DEFAULT), int(os.getenv("REDIS_PORT", "6379"))


async def persist_placeholder_map(ph_to_orig: dict) -> None:
    """Guarda ``ph_to_orig`` en la bóveda Redis con TTL — SOLO si ``PII_VAULT_ENABLED``.
    Best-effort total: si Redis no está disponible el masking de este request YA pasó
    bien (el placeholder ya está en el texto); lo único que se pierde es la chance de
    desenmascarar más tarde, nunca se rompe ni se reintenta la request de masking."""
    if not ph_to_orig or sentinel_engine_redis is None:
        return
    try:
        import redis.asyncio as redis_lib
    except ImportError:
        logger.warning("pii_vault: redis no está en la imagen — el mapa de este masking "
                       "no persiste, RAG no podrá desenmascararlo después.")
        return
    client = None
    try:
        client = sentinel_engine_redis.async_redis_con_timeouts(redis_lib, *_pii_vault_redis_endpoint())
        pipe = client.pipeline()
        for ph, orig in ph_to_orig.items():
            pipe.set(PII_VAULT_PREFIX + ph, orig, ex=PII_VAULT_TTL_SECONDS)
        await pipe.execute()
    except Exception:  # noqa: BLE001 — best-effort, jamás propaga (ver docstring)
        logger.warning("pii_vault: no se pudo persistir el mapa reversible (Redis no "
                       "disponible) — el masking sigue OK, solo no se podrá "
                       "desenmascarar más tarde.", exc_info=True)
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001
                pass


async def resolve_placeholders_from_vault(text: str) -> dict:
    """Busca placeholders en ``text`` que no vinieron del request actual (p.ej. texto
    RAG masked en la subida de un documento, requests atrás) y los resuelve contra la
    bóveda persistente. Devuelve ``{}`` si ``PII_VAULT_ENABLED`` está apagado, no hay
    matches, o Redis no responde — nunca lanza."""
    if not PII_VAULT_ENABLED or sentinel_engine_redis is None:
        return {}
    tokens = sorted(set(PLACEHOLDER_TOKEN_RE.findall(text or "")))
    if not tokens:
        return {}
    try:
        import redis.asyncio as redis_lib
    except ImportError:
        return {}
    client = None
    try:
        client = sentinel_engine_redis.async_redis_con_timeouts(redis_lib, *_pii_vault_redis_endpoint())
        keys = [PII_VAULT_PREFIX + t for t in tokens]
        values = await client.mget(keys)
        return {
            tok: (val.decode("utf-8") if isinstance(val, (bytes, bytearray)) else val)
            for tok, val in zip(tokens, values) if val
        }
    except Exception:  # noqa: BLE001 — best-effort, jamás propaga
        logger.warning("pii_vault: no se pudo consultar la bóveda (Redis no disponible) "
                       "— la respuesta se muestra con los placeholders sin resolver.",
                       exc_info=True)
        return {}
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001
                pass


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


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _set(obj, key, value) -> None:
    if isinstance(obj, dict):
        obj[key] = value
    else:
        setattr(obj, key, value)


def json_string_map(ph_to_orig: dict) -> dict:
    """Mapa placeholder → original escapado como CONTENIDO de cadena JSON (sin comillas
    externas). Para respuestas pedidas en JSON (`response_format`) o tool calls: un original con
    salto de línea o comillas restituido crudo rompe el JSON del cliente (visto 13-sep con
    Presenton: "Invalid control character at: line 1 column 67")."""
    return {ph: json.dumps(orig, ensure_ascii=False)[1:-1] for ph, orig in ph_to_orig.items()}


def request_wants_json(request_data: dict) -> bool:
    """True si el cliente pidió la respuesta como JSON (`response_format` json_object/json_schema)."""
    rf = (request_data or {}).get("response_format")
    if isinstance(rf, dict):
        return rf.get("type") in ("json_object", "json_schema")
    return bool(rf)


def unmask_openai_chunk(chunk, carries: dict, ph_to_orig: dict, *, final: bool = False,
                        json_content: bool = False):
    """Restituye placeholders en UN chunk de streaming de la API OpenAI (chat/completions).

    Hueco real (spec 050, 12/13-sep-2026): el hook de streaming solo reescribía frames SSE
    crudos (ruta Anthropic); los chunks de ``/v1/chat/completions`` llegan como objetos
    ``ModelResponseStream`` (o dicts) y pasaban tal cual → Presenton (streaming) recibía
    ``[PERSON_0_66a5]`` en vez de "OTC". Verificado con texto, JSON y tool calls.

    ``carries`` es el estado entre chunks: ``{clave: fragmento_retenido}`` con clave
    ``("c", i)`` para ``delta.content`` de la choice ``i`` y ``("t", i, j)`` para los
    ``arguments`` del tool call ``j`` — un placeholder puede venir partido en dos deltas y
    ``safe_split`` retiene la cola hasta que llega el ``]``. Con ``final=True`` (chunk con
    ``finish_reason`` o último del stream) el carry pendiente se vuelca al chunk: 0 texto
    perdido. Muta el chunk y lo devuelve.
    """
    choices = _get(chunk, "choices") or []
    content_map = json_string_map(ph_to_orig) if json_content else ph_to_orig
    args_map = json_string_map(ph_to_orig)  # los `arguments` de un tool call SIEMPRE son JSON
    for i, choice in enumerate(choices):
        delta = _get(choice, "delta")
        if delta is None:
            continue
        fin = final or bool(_get(choice, "finish_reason"))
        key = ("c", i)
        content = _get(delta, "content")
        if isinstance(content, str) or (fin and carries.get(key)):
            combined = carries.pop(key, "") + (content or "")
            if fin:
                safe, carry = combined, ""
            else:
                safe, carry = safe_split(combined)
            if carry:
                carries[key] = carry
            if safe or content is not None:
                _set(delta, "content", unmask_text(safe, content_map))
        for j, tc in enumerate(_get(delta, "tool_calls") or []):
            fn = _get(tc, "function")
            if fn is None:
                continue
            tkey = ("t", i, _get(tc, "index", j) if _get(tc, "index", None) is not None else j)
            args = _get(fn, "arguments")
            if isinstance(args, str) or (fin and carries.get(tkey)):
                combined = carries.pop(tkey, "") + (args or "")
                if fin:
                    safe, carry = combined, ""
                else:
                    safe, carry = safe_split(combined)
                if carry:
                    carries[tkey] = carry
                _set(fn, "arguments", unmask_text(safe, args_map))
    return chunk


def flush_openai_carries(last_chunk, carries: dict, ph_to_orig: dict, *, json_content: bool = False):
    """Stream truncado sin ``finish_reason``: vuelca los carries pendientes en una copia del
    último chunk (solo ``delta.content`` / ``arguments``), para no perder texto."""
    if not carries or last_chunk is None:
        return None
    import copy as _copy
    chunk = _copy.deepcopy(last_chunk)
    content_map = json_string_map(ph_to_orig) if json_content else ph_to_orig
    args_map = json_string_map(ph_to_orig)
    for i, choice in enumerate(_get(chunk, "choices") or []):
        delta = _get(choice, "delta")
        if delta is None:
            continue
        _set(delta, "content", unmask_text(carries.pop(("c", i), ""), content_map) or None)
        for j, tc in enumerate(_get(delta, "tool_calls") or []):
            fn = _get(tc, "function")
            if fn is not None:
                idx = _get(tc, "index", None)
                _set(fn, "arguments", unmask_text(carries.pop(("t", i, idx if idx is not None else j), ""), args_map))
        if isinstance(choice, dict):
            choice["finish_reason"] = None
        else:
            try:
                setattr(choice, "finish_reason", None)
            except Exception:  # pragma: no cover - objetos inmutables
                pass
    carries.clear()
    return chunk


def flush_carry_sse_block(carry: str, carry_field: Optional[str],
                          ph_to_orig: dict, index: int = 0) -> str:
    """Delta sintético SSE **framed** para flushear el carry de un stream truncado
    (review 024: el flush crudo sin ``data:``/terminador lo descartaba el parser SSE
    del cliente → texto perdido justo en el camino que promete «0 texto perdido»)."""
    field = carry_field or "text"
    ev = {"type": "content_block_delta", "index": index,
          "delta": {"type": FIELD_DELTA[field], field: unmask_text(carry, ph_to_orig)}}
    return "event: content_block_delta\ndata: " + json.dumps(ev, ensure_ascii=False) + "\n\n"


def proxy_identity_from(data: dict) -> dict:
    """Identidad Sentinel propagada por el proxy (``custom_auth`` →
    ``user_api_key_metadata.sentinel``), buscada en AMBOS metadata-homes:
    ``litellm_metadata`` (ruta anthropic) y ``metadata`` (el resto) — 024 D3."""
    for key in ("litellm_metadata", "metadata"):
        home = (data or {}).get(key)
        if isinstance(home, dict):
            sentinel = (home.get("user_api_key_metadata") or {}).get("sentinel")
            if sentinel:
                return sentinel
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
            cset = choice.__setitem__ if isinstance(choice, dict) else (
                lambda k, v, _c=choice: setattr(_c, k, v))
            # /v1/completions: el texto vive directo en el choice.
            if isinstance(cget("text"), str):
                cset("text", unmask_text(cget("text"), ph_to_orig))
            message = cget("message")
            if message is None:
                continue
            mget = message.get if isinstance(message, dict) else (
                lambda k, d=None, _m=message: getattr(_m, k, d))
            mset = message.__setitem__ if isinstance(message, dict) else (
                lambda k, v, _m=message: setattr(_m, k, v))
            if isinstance(mget("content"), str):
                mset("content", unmask_text(mget("content"), ph_to_orig))
            # tool_calls (review 024): los argumentos JSON de las tools también vuelven
            # al cliente — sin esto, un agente ejecutaría su tool con el placeholder.
            tool_calls = mget("tool_calls")
            if isinstance(tool_calls, list):
                for tc in tool_calls:
                    tget = tc.get if isinstance(tc, dict) else (
                        lambda k, d=None, _t=tc: getattr(_t, k, d))
                    fn = tget("function")
                    if fn is None:
                        continue
                    fget = fn.get if isinstance(fn, dict) else (
                        lambda k, d=None, _f=fn: getattr(_f, k, d))
                    fset = fn.__setitem__ if isinstance(fn, dict) else (
                        lambda k, v, _f=fn: setattr(_f, k, v))
                    if isinstance(fget("arguments"), str):
                        fset("arguments", unmask_text(fget("arguments"), ph_to_orig))


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


# ── Identidad del módulo ──────────────────────────────────────────────────────────
# Este archivo entra por DOS caminos: el nombre PLANO (`import sentinel_guardian_policy`, que es
# lo que hacen los cuatro consumidores de PRODUCCIÓN —`gateway.py`, `presidio_service.py`,
# `sentinel_guardrail.py`, `sentinel_audit_logger.py`, cada uno agregándose la carpeta `extensions` a
# `sys.path`) y el nombre PAQUETE (`from extensions import sentinel_guardian_policy`, que es lo
# que usan los tests de policy y `contract_checks.py`, el check de RELEASE). Sin alias son
# DOS objetos-módulo con globals INDEPENDIENTES: mismo `__file__` —o sea que no pueden
# divergir en lógica— pero estado partido, que es lo que ya obligó al autouse
# `_reset_presidio_http_client_singleton` de `backend/tests/conftest.py` (el `_http_client`
# vivía duplicado y resetear una copia no alcanzaba).
#
# Importa ahora más que antes: la matriz D2 de la 038 vive acá para que el backend y el motor
# evalúen EL MISMO objeto en vez de dos copias «igualitas» (`specs/038/tasks.md`: si un plano
# la re-implementa, es NO_APTO). Con `setdefault` en ambos sentidos hay un solo objeto gane
# quien gane la carrera de imports.
#
# Las TRES piezas, con la razón MEDIDA de cada una (módulo sintético de 2 piezas vs 3, tres
# órdenes de import, en 3.9/3.12/3.14):
#   1-2. los dos `setdefault` cubren `from extensions import X`, `from extensions.X import …`
#        e `import extensions.X as x`, en los tres órdenes.
#   3.   el `setattr` sobre el paquete cubre el ACCESO POR ATRIBUTO (`extensions.X`), que es
#        la única forma que sin él tira `AttributeError`. Y de paso deja de apoyar el
#        invariante en el fallback a `sys.modules` de `IMPORT_FROM` (CPython ≥3.7), que
#        existe para soportar imports circulares y no para esto: nadie acá lo pinea.
# Mismo bloque que `sentinel_governance.py`, que llegó primero por la vía de dos `Profile`
# distintas y un `isinstance` que fallaba al cruzar planos.
_THIS_MODULE = sys.modules[__name__]
sys.modules.setdefault("sentinel_guardian_policy", _THIS_MODULE)
sys.modules.setdefault("extensions.sentinel_guardian_policy", _THIS_MODULE)
_EXT_PKG = sys.modules.get("extensions")
if _EXT_PKG is not None and not hasattr(_EXT_PKG, "sentinel_guardian_policy"):
    setattr(_EXT_PKG, "sentinel_guardian_policy", _THIS_MODULE)
