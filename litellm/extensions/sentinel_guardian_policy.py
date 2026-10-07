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

import asyncio
import base64
import copy
import hashlib
import hmac
import importlib.util
import json
import logging
import os
import re
import signal
import sys
import time
import uuid
from collections import OrderedDict
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
        # CUIT/CUIL con o sin guiones (`20-30123456-7` y `20301234567`): el perfil argentino los escribe de las
        # dos formas y solo la primera se detectaba (057 T097, QA M7). 11 dígitos entre fronteras de palabra.
        "CUIL": (r"\b\d{2}-?\d{8}-?\d\b", 0.9, ["cuil", "cuit"]),
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
    # Límite izquierdo: sin él, `task-implementation` o `risk-assessment` (…`sk-` + 10 letras) eran «clave» y la capa
    # rechazaba pedidos sin credencial (057 R37). Una clave real no va pegada a una letra o dígito anteriores.
    # Cuerpo: las llaves actuales (`sk-proj-…`, `sk-svcacct-…`, `sk-admin-…`) llevan guiones y guiones bajos, así que la rama
    # larga acepta `[A-Za-z0-9_-]{20,}`; las viejas `sk-<alfanumérico>` (≥ 10) siguen por la rama corta. La larga va primero para
    # que la redacción cubra la llave entera (057 R38). Mismo patrón que `OPENAI_KEY_PATTERN` de GuardianService (test de paridad).
    "OpenAI API Key": r"(?<![a-zA-Z0-9])sk-(?:[A-Za-z0-9_-]{20,}|[A-Za-z0-9]{10,})",
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


# ── Decisión de ruteo con procedencia del motor (audit_logs.routing_decision) ────────
#
# El metadata-home que lee el logger de auditoría es la fusión de `litellm_metadata` y
# `metadata`, y `metadata` es un campo del BODY: lo escribe el cliente (hallazgo A3 de la
# 027). Una clave "interna" no alcanza — el cliente puede mandar la misma. La marca de
# procedencia es el TIPO: el cliente solo puede producir JSON (dict/list/str/número), jamás
# una instancia de esta clase; el código del motor, sí. Es subclase de dict para que
# sobreviva un `deepcopy` y serialice como JSON si el motor vuelca la metadata a un log.
ROUTING_DECISION_KEY = "_internal_routing_decision"


class EngineRoutingDecision(dict):
    """Decisión de ruteo escrita por código del motor (no falsificable desde el body)."""


def mark_routing_decision(home: dict, decision: dict) -> None:
    """Deja la decisión en el metadata-home del pedido, SOBRESCRIBIENDO cualquier valor
    que el cliente haya sembrado bajo la misma clave. Solo para código del motor."""
    if isinstance(home, dict) and isinstance(decision, dict):
        home[ROUTING_DECISION_KEY] = EngineRoutingDecision(decision)


def trusted_routing_decision(*homes) -> Optional[dict]:
    """La decisión del motor si alguno de los homes la trae con su marca; si no, None.

    Se mira cada home POR SEPARADO: en la fusión `metadata` (cliente) gana sobre
    `litellm_metadata`, y un valor plano del cliente taparía el del motor."""
    for home in homes:
        value = home.get(ROUTING_DECISION_KEY) if isinstance(home, dict) else None
        if isinstance(value, EngineRoutingDecision):
            return dict(value)
    return None


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

# Rechazo del enmascarado forzado de alcance completo (S14): algo del pedido no se pudo analizar. Copia
# verbatim del rechazo del guard de la extensión (cara Claude, 400): no dice qué ni dónde (sin contenido).
MASKING_REQUIRED_MESSAGE = ("El pedido no pudo protegerse para este destino y fue bloqueado. "
                            "Probá en una conversación nueva.")

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


def extract_inspect_text(body: dict, cap: int = INSPECT_CAP, *, scope: str = "user",
                         fmt: Optional[str] = None, skip_keys=()) -> str:
    """Texto de los turnos user (str o bloques text/tool_result) para los detectores.
    Mismo alcance que el masking: sin la señal de forzado, el system prompt no se inspecciona acá.

    Con `scope="full"` (S14) es el mismo alcance completo del enmascarado: todo valor de texto del cuerpo
    salvo las posiciones estructurales (el recorrido es el mismo; ver `_w_body`)."""
    if scope == MASKING_SCOPE_FULL:
        partes = _collect_texts(body, fmt or detect_body_format(body), skip=skip_keys)
        return "\n".join(partes)[:cap]
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


# S13 (057 T072; research R18): referencia de conversación que solo escribe la pasarela y clave del servidor.
CONVERSATION_REF_KEY = "sentinel_conversation_ref"
NONCE_KEY_ENV = "MASKING_NONCE_KEY"
_NONCE_KEY_MIN_CHARS = 32
NONCE_SCOPE_CONVERSATION, NONCE_SCOPE_REQUEST = "conversation", "request"


def new_placeholder_map(home: dict, identity: dict) -> Tuple["PlaceholderMap", str]:
    """El `PlaceholderMap` de un pedido y su alcance (`conversation` | `request`, solo el nombre; nunca el valor).
    Con `MASKING_NONCE_KEY` (≥ 32 caracteres) y la referencia de conversación del home, el sufijo y los índices son
    estables por conversación; sin alguna de las dos, o si la derivación falla, aleatorio como siempre (la protección
    no depende de esto, solo la eficacia de la caché del proveedor)."""
    ref = home.get(CONVERSATION_REF_KEY) if isinstance(home, dict) else None
    key = os.environ.get(NONCE_KEY_ENV, "")
    if isinstance(ref, str) and ref and key:
        try:
            return (PlaceholderMap.for_conversation(
                key, tenant=str(identity.get("tenant_id") or ""), key_id=str(identity.get("key_id") or ""), ref=ref),
                NONCE_SCOPE_CONVERSATION)
        except Exception:  # noqa: BLE001 — sin la derivación, aleatorio: la caché pierde eficacia, la protección no
            logger.warning("masking: no se pudo derivar el sufijo por conversación; se usa el aleatorio")
    return PlaceholderMap(), NONCE_SCOPE_REQUEST


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
        # Clave del índice determinista: el `document_id` (043) o, con S13, la derivada por conversación. Sin ninguna,
        # contador secuencial como siempre.
        self._index_key: Optional[bytes] = document_id.encode() if document_id else None
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

    @classmethod
    def for_conversation(cls, key: str, *, tenant: str, key_id: str, ref: str) -> "PlaceholderMap":
        """S13 (057 R18; contracts/costuras-base.md §S13): mapa con marcadores ESTABLES dentro de una conversación.

        `nonce = HMAC(key, "nonce" | tenant | llave | ref)[:4]` y el índice por valor
        `HMAC(HMAC(key, "idx" | tenant | llave | ref), tipo | valor | probe)`: el mismo valor en la misma conversación da el
        mismo marcador en todos los pedidos y sin importar el orden de aparición; otra conversación, llave, empresa o
        clave del servidor dan otro. `key` es el secreto del servidor (`MASKING_NONCE_KEY`, ≥ 32 caracteres): sin él el
        sufijo no se puede reproducir. Los componentes van separados por NUL (sin ambigüedad entre campos). Lanza
        `ValueError` ante una clave corta o una referencia vacía: el llamador cae al aleatorio."""
        if not isinstance(key, str) or len(key) < _NONCE_KEY_MIN_CHARS or not ref:
            raise ValueError("clave o referencia de conversación inválida")
        k = key.encode("utf-8")
        ctx = "\x00".join((str(tenant), str(key_id), str(ref))).encode("utf-8")
        mapa = cls(nonce=hmac.new(k, b"nonce\x00" + ctx, hashlib.sha256).hexdigest()[:4])
        mapa._index_key = hmac.new(k, b"idx\x00" + ctx, hashlib.sha256).digest()
        return mapa

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
            self._index_key,
            f"{entity_type}|{value}|{probe}".encode(),
            hashlib.sha256,
        ).digest()
        return int.from_bytes(digest[:5], "big") % 100_000_000

    def placeholder_for(self, value: str, entity_type: str) -> str:
        if value in self.orig_to_ph:
            return self.orig_to_ph[value]
        if self._index_key:
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
    return _replace_entities(text, entities, pmap)


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


# ═══════════════════════════════════════════════════════════════════════════════════
# S14 — alcance completo del enmascarado forzado (057 T097; QA B3, QA v2 N4/N8; research R29;
# contracts/costuras-base.md §S14). BASE: genérico, sin nombres de ninguna localización; retrocompatible
# (sin la señal, `mask_body` y `extract_inspect_text` hacen exactamente lo de siempre).
# ═══════════════════════════════════════════════════════════════════════════════════
#
# La señal: metadata interna `sentinel_forced_masking = {"scope": "full"}` que SOLO escribe la pasarela (en
# `pre_engine` de una extensión) con la misma marca de procedencia por TIPO que la decisión de ruteo: el
# cliente solo produce JSON, jamás una instancia de `ForcedMaskingSignal`. La que mande el cliente se descarta.
FORCED_MASKING_KEY = "sentinel_forced_masking"
MASKING_SCOPE_USER = "user"
MASKING_SCOPE_FULL = "full"


class ForcedMaskingSignal(dict):
    """Señal de enmascarado forzado escrita por código del motor (no falsificable desde el body)."""


def mark_forced_masking(home: dict, scope: str = MASKING_SCOPE_FULL) -> None:
    """Deja la señal en el metadata-home del pedido, sobrescribiendo lo que el cliente haya sembrado."""
    if isinstance(home, dict):
        home[FORCED_MASKING_KEY] = ForcedMaskingSignal({"scope": scope})


def trusted_forced_masking(*homes) -> bool:
    """True si algún home trae la señal CON su marca de procedencia y alcance completo.

    Se mira cada home por separado (en la fusión, `metadata` —campo del body— tapa a `litellm_metadata`)."""
    for home in homes:
        value = home.get(FORCED_MASKING_KEY) if isinstance(home, dict) else None
        if isinstance(value, ForcedMaskingSignal) and value.get("scope") == MASKING_SCOPE_FULL:
            return True
    return False


# Resolutores del forzado (S14, decisión del coordinador): el forzado viaja hacia el motor en un token firmado
# que verifica el guard de una EXTENSIÓN, y ese guard corre DESPUÉS del guardrail base; el base no ve el grant.
# La extensión registra acá, al importarse en el motor, una función que decide si ESTE pedido es forzado
# (p. ej. verificando la cabecera firmada) y el guardrail base marca la señal por tipo. La base no sabe nada
# de cómo se decide: solo que alguien registrado dice que sí.
_FORCED_MASKING_RESOLVERS: list = []


def register_forced_masking_resolver(resolver) -> None:
    """`resolver(data, user_api_key_dict, call_type) -> bool`. Idempotente (el mismo objeto no se duplica)."""
    if callable(resolver) and resolver not in _FORCED_MASKING_RESOLVERS:
        _FORCED_MASKING_RESOLVERS.append(resolver)


def clear_forced_masking_resolvers() -> None:
    """Solo para tests."""
    _FORCED_MASKING_RESOLVERS.clear()


def resolve_forced_masking(data: dict, user_api_key_dict, call_type) -> bool:
    """True si algún resolutor registrado dice que el pedido es forzado.

    FALLA CERRADO: un resolutor que lanza cuenta como «forzado» (se enmascara de más, nunca de menos) y se
    registra el error sin el contenido del pedido."""
    for resolver in list(_FORCED_MASKING_RESOLVERS):
        try:
            if resolver(data, user_api_key_dict, call_type):
                return True
        except Exception:  # noqa: BLE001 — sin la decisión, la postura segura es enmascarar todo
            logger.error("forced_masking: el resolutor %s falló; el pedido se trata como forzado",
                         getattr(resolver, "__name__", "?"), exc_info=True)
            return True
    return False


def discard_untrusted_forced_masking(*containers) -> None:
    """Quita la señal que NO lleva la marca de procedencia (la mandó el cliente: cuerpo, `metadata`)."""
    for container in containers:
        if isinstance(container, dict) and not isinstance(
                container.get(FORCED_MASKING_KEY), ForcedMaskingSignal):
            container.pop(FORCED_MASKING_KEY, None)


class MaskingTally:
    """Cuentas del enmascarado de alcance completo — solo conteos y NOMBRES DE TIPO, jamás contenido.

    `detected`: detecciones en todo lo analizado (incluidas las de posiciones estructurales, que no se
    reescriben); `masked`: reemplazos hechos; `unanalyzable`: bloques/posiciones que no se pudieron
    analizar (cada uno con su nombre de tipo en `kinds`)."""

    def __init__(self):
        self.detected = 0
        self.masked = 0
        self.unanalyzable = 0
        self._kinds: set = set()
        self.signed_thinking_masked = 0
        self.unanalyzable_replaced = 0
        self._replaced_kinds: set = set()

    @property
    def kinds(self) -> list:
        return sorted(self._kinds)

    @property
    def replaced_kinds(self) -> list:
        return sorted(self._replaced_kinds)

    def flag(self, kind: str) -> None:
        self.unanalyzable += 1
        self._kinds.add(kind)

    def replace(self, kind: str) -> None:
        """Un binario que devolvió una HERRAMIENTA (`tool_result`) y no se pudo analizar: se cambió por una nota
        (R39). No cuenta como no analizable —el binario ya no sale—, pero queda contado para la auditoría."""
        self.unanalyzable_replaced += 1
        self._replaced_kinds.add(kind)


# ── Tabla de posiciones exentas (QA v2 N8) ─────────────────────────────────────────────
#
# Lista CERRADA por formato; `*` = cualquier índice (o cualquier clave, al final de la ruta); `…` = un bloque de
# contenido a cualquier profundidad de `messages[*].content[*]` o `system[*]`, incluidos los bloques anidados en
# `tool_result.content[*]`; `@tipo` = solo para bloques de ese tipo; `#schema` = la posición lleva un JSON
# Schema (sus palabras clave, `type`/`format`/`$ref`, las claves de `properties` y `required[*]` son
# estructurales; los valores libres del esquema se enmascaran). FUERA de estas rutas no hay exención, aunque la
# clave se llame `id`, `name`, `type` o `role`. Agregar o quitar una posición es un cambio de contrato
# (contracts/costuras-base.md §S14) y de su test de instantánea.
#
#   opaque     — ni se analiza ni se reescribe (el valor no viaja como lo mandó el cliente o no es texto).
#   structural — se analiza, no se reescribe: una detección ahí es no analizable (`structural_entity`).
S14_EXEMPT_POSITIONS = {
    "anthropic": {
        "opaque": (
            "model",
            "….signature",
            "….source.data",
            "….cache_control",
            "tools.*.cache_control",
        ),
        "structural": (
            "stream", "max_tokens", "temperature", "top_p", "top_k",
            "thinking.type", "thinking.budget_tokens",
            "tool_choice.type", "tool_choice.name", "tool_choice.disable_parallel_tool_use",
            "messages.*.role",
            "….type", "….id@tool_use", "….name@tool_use", "….tool_use_id@tool_result", "….is_error@tool_result",
            "….source.type", "….source.media_type",
            "tools.*.name", "tools.*.type",
            "tools.*.input_schema#schema",
        ),
    },
    "openai": {
        "opaque": (
            "model",
            "….file.file_data",
            "….image_url.url",
        ),
        "structural": (
            "stream", "stream_options.*", "max_tokens", "max_completion_tokens", "temperature", "top_p", "n",
            "seed", "presence_penalty", "frequency_penalty", "logprobs", "top_logprobs",
            "parallel_tool_calls", "response_format.type", "response_format.json_schema.name",
            "tool_choice", "tool_choice.type", "tool_choice.function.name",
            "messages.*.role", "messages.*.tool_call_id",
            "messages.*.tool_calls.*.id", "messages.*.tool_calls.*.type",
            "messages.*.tool_calls.*.function.name",
            "….type",
            "tools.*.type", "tools.*.function.name", "tools.*.function.strict",
            "tools.*.function.parameters#schema", "response_format.json_schema.schema#schema",
        ),
    },
}

_CLASS_OPAQUE, _CLASS_STRUCT, _CLASS_SCHEMA, _CLASS_CACHE = "opaque", "struct", "schema", "cache"
_BLOCK = "…"
# Bloques de contenido: de `system[*]` y de `messages[*].content[*]` (y los anidados en `tool_result`).
_BLOCK_ROOTS = ("system.*", "messages.*.content.*")
_MAX_DEPTH = 100


def _build_position_index():
    index, containers = {}, {}
    for fmt, clases in S14_EXEMPT_POSITIONS.items():
        entries, prefixes = {}, set()
        for clase, rutas in clases.items():
            for ruta in rutas:
                cls = _CLASS_OPAQUE if clase == "opaque" else _CLASS_STRUCT
                if ruta.endswith("#schema"):
                    ruta, cls = ruta[:-len("#schema")], _CLASS_SCHEMA
                elif ruta.endswith("cache_control"):
                    cls = _CLASS_CACHE
                ruta, _, tipo = ruta.partition("@")
                entries[(ruta, tipo or None)] = cls
                partes = ruta.split(".")
                for i in range(1, len(partes)):
                    prefixes.add(".".join(partes[:i]))
        index[fmt] = entries
        containers[fmt] = prefixes
    return index, containers


_S14_INDEX, _S14_CONTAINERS = _build_position_index()

# ── Posiciones estructurales con el NER real: vocabulario cerrado e identificadores (057 T083) ───────────────────
#
# Decisión del owner, 2026-10-06 (enmienda de N8; contracts/costuras-base.md §S14 «Vocabulario cerrado y tipos
# semánticos»). Medido con el analizador real: `assistant`, `tool_use`, `Read`, `file_path` o un id `toolu_…` salen como
# PERSON/LOCATION y, como una posición estructural no se reescribe, TODO pedido con un mensaje `assistant` o con
# herramientas se bloqueaba. Dos reglas, solo bajo el enmascarado forzado y solo sobre las posiciones «structural» de arriba:
#   (A) VOCABULARIO CERRADO: el valor de una posición cuyo conjunto de valores lo fija el protocolo (rol, tipo de bloque,
#       `tool_choice.type`, …) y que está dentro de ese conjunto NO se analiza; uno fuera del conjunto se analiza como siempre.
#   (B) IDENTIFICADORES (vocabulario abierto: nombres de herramienta, ids, claves y nombres del esquema): se ignoran SOLO los
#       tipos de NER semántico de `STRUCTURAL_IGNORED_ENTITY_TYPES`; los de patrón (DNI, CUIT, CBU, email, teléfono, tarjeta,
#       IBAN…) y los propios de la empresa o desconocidos siguen siendo `structural_entity`.
# El texto de mensajes, `tool_result`, `thinking`, `system` y los subárbol libres no cambian. Agregar o quitar un valor o una
# posición es un cambio de contrato (§S14) y de su test de instantánea.
_MIME_RE = re.compile(r"[a-z]+/[a-z0-9][a-z0-9.+-]{0,99}")
_ANTHROPIC_TOOL_TYPE_RE = re.compile(r"(custom|[a-z][a-z0-9_]*_\d{8})")
_ANTHROPIC_BLOCK_TYPES = frozenset((
    "text", "image", "document", "tool_use", "server_tool_use", "tool_result", "thinking", "redacted_thinking",
    "search_result", "web_search_tool_result", "web_search_result"))
_OPENAI_PART_TYPES = frozenset(("text", "refusal", "image_url", "input_audio", "file"))

S14_CLOSED_VOCABULARY = {
    "anthropic": {
        "messages.*.role": frozenset(("user", "assistant")),
        "….type": _ANTHROPIC_BLOCK_TYPES,
        "….source.type": frozenset(("base64", "url", "text", "file", "content")),
        "….source.media_type": _MIME_RE,
        "thinking.type": frozenset(("enabled", "disabled", "adaptive")),
        "tool_choice.type": frozenset(("auto", "any", "tool", "none")),
        "tools.*.type": _ANTHROPIC_TOOL_TYPE_RE,
    },
    "openai": {
        "messages.*.role": frozenset(("system", "developer", "user", "assistant", "tool", "function")),
        "messages.*.tool_calls.*.type": frozenset(("function",)),
        "….type": _OPENAI_PART_TYPES,
        "response_format.type": frozenset(("text", "json_object", "json_schema")),
        "tool_choice": frozenset(("none", "auto", "required")),
        "tool_choice.type": frozenset(("function", "allowed_tools", "custom")),
        "tools.*.type": frozenset(("function", "custom")),
    },
}
S14_OPEN_IDENTIFIERS = {
    "anthropic": ("tool_choice.name", "….id@tool_use", "….name@tool_use", "….tool_use_id@tool_result", "tools.*.name"),
    "openai": ("messages.*.tool_call_id", "messages.*.tool_calls.*.id", "messages.*.tool_calls.*.function.name",
               "tool_choice.function.name", "tools.*.function.name", "response_format.json_schema.name"),
}
# Tipos de NER SEMÁNTICO (los que una cadena corta y común dispara por parecerse a un nombre, un lugar o una URL). Lista
# CERRADA: un tipo que no esté acá (patrón, propio de la empresa o desconocido) sigue bloqueando.
STRUCTURAL_IGNORED_ENTITY_TYPES = frozenset(("PERSON", "LOCATION", "ORGANIZATION", "NRP", "URL", "DATE_TIME"))
_MODE_CLOSED, _MODE_OPEN = "closed", "open"


def _build_mode_index():
    index = {}
    for fmt in S14_EXEMPT_POSITIONS:
        entradas = {}
        for ruta, vocab in S14_CLOSED_VOCABULARY.get(fmt, {}).items():
            entradas[(ruta, None)] = (_MODE_CLOSED, vocab)
        for ruta in S14_OPEN_IDENTIFIERS.get(fmt, ()):
            ruta, _, tipo = ruta.partition("@")
            entradas[(ruta, tipo or None)] = (_MODE_OPEN, None)
        index[fmt] = entradas
    return index


_S14_MODE_INDEX = _build_mode_index()


def _scan_mode(fmt: str, path: str, block_type=None):
    """Modo de análisis de una posición estructural: `("closed", vocabulario)`, `("open", None)` o `None` (estricta)."""
    index = _S14_MODE_INDEX[fmt]
    if block_type in _TOOL_USE_TYPES:
        block_type = "tool_use"
    if block_type is not None and (path, block_type) in index:
        return index[(path, block_type)]
    return index.get((path, None))


def _in_vocabulary(vocab, value) -> bool:
    if isinstance(vocab, frozenset):
        return value in vocab
    return len(value) <= 128 and vocab.fullmatch(value) is not None

# Exenciones OPCIONALES (057 T112; research R34): posiciones OPACAS que la instalación puede encender por variable de
# entorno, APAGADAS por defecto (todo se analiza). Misma semántica que las opacas de arriba: ni se analizan ni se
# reescriben. `@rol` = solo el contenido de los mensajes con ese `role`. Agregar o quitar una posición es un cambio de
# contrato (contracts/costuras-base.md §S17) y de su test de instantánea; la tabla de arriba no cambia.
S14_EXEMPT_POSITIONS_OPTIONAL = {
    "system_prompt": {
        "anthropic": ("system",),
        "openai": ("messages.*.content@system", "messages.*.content@developer"),
    },
    "tool_definitions": {
        "anthropic": ("tools",),
        "openai": ("tools", "functions"),
    },
}
_OPTIONAL_EXEMPT_ENV = {"system_prompt": "MASKING_EXEMPT_SYSTEM_PROMPT",
                        "tool_definitions": "MASKING_EXEMPT_TOOL_DEFINITIONS"}


def optional_exemptions() -> frozenset:
    """Exenciones opcionales encendidas por la instalación (variables de entorno, leídas en cada uso; solo `1`, `true`,
    `yes` u `on` encienden; cualquier otro valor ⇒ apagada). El pedido no interviene: no hay otra vía."""
    return frozenset(nombre for nombre, var in _OPTIONAL_EXEMPT_ENV.items()
                     if os.environ.get(var, "").strip().lower() in _TRUE_WORDS)


def _optionally_exempt(fmt: str, exempt, path: str, nodo: dict) -> bool:
    for opcion in exempt:
        for ruta in S14_EXEMPT_POSITIONS_OPTIONAL.get(opcion, {}).get(fmt, ()):
            ruta, _, rol = ruta.partition("@")
            if path == ruta and (not rol or nodo.get("role") == rol):
                return True
    return False
_TOOL_USE_TYPES = ("tool_use", "server_tool_use")


def _cpath(path: str, key) -> str:
    return key if path == "" else f"{path}.{key}"


def _class_of(fmt: str, path: str, block_type=None):
    """Clase exenta de una ruta (None = no exenta: subárbol libre). Por posición, nunca por nombre."""
    index = _S14_INDEX[fmt]
    if block_type in _TOOL_USE_TYPES:
        block_type = "tool_use"
    if block_type is not None and (path, block_type) in index:
        return index[(path, block_type)]
    if (path, None) in index:
        return index[(path, None)]
    padre, _, _ = path.rpartition(".")
    return index.get((padre + ".*", None)) if padre else None


def _valid_cache_control(value) -> bool:
    """Forma del protocolo: solo `type` (= ephemeral) y `ttl` (5m | 1h)."""
    if not isinstance(value, dict) or set(value) - {"type", "ttl"}:
        return False
    return value.get("type") == "ephemeral" and value.get("ttl", "5m") in ("5m", "1h")


# ── Recorrido del cuerpo: UNA fuente para enmascarar e inspeccionar ─────────────────────
#
# Los recorridos son generadores que piden operaciones al «conductor» y reciben su resultado:
#   ("text", s)  → texto libre: el conductor devuelve el texto enmascarado
#   ("num", n)   → escalar numérico libre: devuelve n, o el marcador (cadena) si hay detección
#   ("scan", v)  → posición estructural: se analiza, jamás se reescribe (detección ⇒ structural_entity)
#   ("scan_closed", (vocabulario, v)) → estructural de vocabulario cerrado: dentro del conjunto no se analiza; fuera, como "scan"
#   ("scan_open", v) → estructural de vocabulario abierto (identificador): como "scan", ignorando los tipos de NER semántico
#   ("flag", k)  → no analizable de tipo `k`
#   ("replaced", k) → binario no analizable de una herramienta (dentro de `tool_result`) ya cambiado por una nota (R39)
#   ("pdf", b64) → (texto|None, tipo_de_falla|None)
#   ("signed_thinking", None) → un `thinking` con firma cambió de texto
# El conductor de enmascarado (`_mask_body_full`) es async; el de inspección (`_collect_texts`) es síncrono.

def _w_scan(node, depth=0, mode=None):
    """Posición estructural: se analiza todo lo que hay adentro (claves incluidas), sin reescribir nada. `mode` (de
    `_scan_mode`) solo afecta a las cadenas: vocabulario cerrado (no se analiza lo que está dentro del conjunto) o
    identificador (se ignoran los tipos de NER semántico); sin `mode`, las cadenas se analizan estrictas. Los escalares
    numéricos van siempre como identificador (valor abierto)."""
    if depth > _MAX_DEPTH:
        yield ("flag", "too_deep")
    elif isinstance(node, str) and mode is not None:
        if mode[0] == _MODE_CLOSED:
            yield ("scan_closed", (mode[1], node))
        else:
            yield ("scan_open", node)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        # Escalar numérico estructural (`temperature`, `top_k`, `minLength`, `maxItems`…): su valor es abierto como el de un
        # identificador, y el NER real marca la cadena `1` como LOCATION. Como en (B): se ignoran los tipos semánticos y un
        # patrón (un DNI como valor) sigue bloqueando. El texto es el mismo con el que el prefetch lo pide al analizador.
        yield ("scan_open", repr(node) if isinstance(node, float) else str(node))
    elif isinstance(node, str):
        yield ("scan", node)
    elif isinstance(node, list):
        for item in node:
            yield from _w_scan(item, depth + 1, mode)
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _w_scan(key, depth + 1)
            yield from _w_scan(value, depth + 1)


def _w_free(node, depth=0):
    """Subárbol libre: se enmascara todo valor de texto, las CLAVES de objeto y los escalares numéricos;
    booleanos y `null` no llevan datos."""
    if depth > _MAX_DEPTH:
        yield ("flag", "too_deep")
        return node
    if isinstance(node, str):
        return (yield ("text", node))
    if isinstance(node, bool) or node is None:
        return node
    if isinstance(node, (int, float)):
        return (yield ("num", node))
    if isinstance(node, list):
        for i, item in enumerate(node):
            node[i] = yield from _w_free(item, depth + 1)
        return node
    if isinstance(node, dict):
        items = list(node.items())
        node.clear()
        for key, value in items:
            nueva = (yield ("text", key)) if isinstance(key, str) else key
            node[nueva] = yield from _w_free(value, depth + 1)
        return node
    return node


# JSON Schema (`input_schema`, `parameters`): palabras clave y nombres estructurales; valores libres.
_SCHEMA_SCALAR_KEYS = frozenset((
    "type", "format", "$ref", "$schema", "$id", "$anchor", "$dynamicRef", "$dynamicAnchor", "minimum", "maximum",
    "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minLength", "maxLength", "minItems", "maxItems",
    "uniqueItems", "minProperties", "maxProperties", "minContains", "maxContains", "nullable", "readOnly",
    "writeOnly", "deprecated"))
_SCHEMA_SUBSCHEMA_KEYS = frozenset((
    "items", "additionalProperties", "additionalItems", "not", "if", "then", "else", "contains",
    "propertyNames", "unevaluatedProperties", "unevaluatedItems", "contentSchema"))
_SCHEMA_SUBSCHEMA_LISTS = frozenset(("allOf", "anyOf", "oneOf", "prefixItems"))
_SCHEMA_NAME_MAPS = frozenset(("properties", "$defs", "definitions", "patternProperties",
                               "dependentSchemas", "dependentRequired", "dependencies"))
# Vocabulario cerrado del esquema (057 T083): sus palabras clave, los tipos de JSON y los formatos estándar. Todo lo demás
# (un nombre de propiedad, un `$ref`, una palabra clave inventada) es un identificador o se analiza estricto.
_SCHEMA_KEYWORDS = (_SCHEMA_SCALAR_KEYS | _SCHEMA_SUBSCHEMA_KEYS | _SCHEMA_SUBSCHEMA_LISTS | _SCHEMA_NAME_MAPS
                    | frozenset(("required", "description", "title", "enum", "const", "default", "examples", "pattern",
                                 "$comment", "contentMediaType", "contentEncoding")))
_SCHEMA_JSON_TYPES = frozenset(("object", "array", "string", "number", "integer", "boolean", "null"))
_SCHEMA_FORMATS = frozenset((
    "date-time", "time", "date", "duration", "email", "idn-email", "hostname", "idn-hostname", "ipv4", "ipv6", "uri",
    "uri-reference", "iri", "iri-reference", "uuid", "uri-template", "json-pointer", "relative-json-pointer", "regex",
    "binary", "byte", "int32", "int64", "float", "double", "password"))
_SCHEMA_REF_KEYS = frozenset(("$ref", "$id", "$anchor", "$dynamicRef", "$dynamicAnchor", "$schema"))
_SCHEMA_KEYWORD_MODE = (_MODE_CLOSED, _SCHEMA_KEYWORDS)
_SCHEMA_VALUE_MODE = {"type": (_MODE_CLOSED, _SCHEMA_JSON_TYPES), "format": (_MODE_CLOSED, _SCHEMA_FORMATS)}
_IDENTIFIER_MODE = (_MODE_OPEN, None)


def _w_schema(node, depth=0):
    if depth > _MAX_DEPTH:
        yield ("flag", "too_deep")
        return node
    if isinstance(node, list):             # `items` en forma de tupla (draft-07)
        for item in node:
            yield from _w_schema(item, depth + 1)
        return node
    if not isinstance(node, dict):
        yield from _w_scan(node, depth + 1)
        return node
    for key, value in node.items():
        yield from _w_scan(key, depth + 1, _SCHEMA_KEYWORD_MODE)   # la palabra clave es estructural
        if key in _SCHEMA_SCALAR_KEYS or key == "required":
            if key == "required":
                modo = _IDENTIFIER_MODE
            elif key in _SCHEMA_REF_KEYS:
                modo = _IDENTIFIER_MODE
            else:
                modo = _SCHEMA_VALUE_MODE.get(key)
            yield from _w_scan(value, depth + 1, modo)
        elif key in _SCHEMA_SUBSCHEMA_KEYS:
            yield from _w_schema(value, depth + 1)
        elif key in _SCHEMA_SUBSCHEMA_LISTS and isinstance(value, list):
            for sub in value:
                yield from _w_schema(sub, depth + 1)
        elif key in _SCHEMA_NAME_MAPS and isinstance(value, dict):
            for nombre, sub in value.items():
                yield from _w_scan(nombre, depth + 1, _IDENTIFIER_MODE)   # el nombre de la propiedad es estructural
                if isinstance(sub, (dict, list)) and key != "dependentRequired":
                    yield from _w_schema(sub, depth + 1)
                else:
                    yield from _w_scan(sub, depth + 1, _IDENTIFIER_MODE)
        else:                                                 # description, title, enum, const, default,
            node[key] = yield from _w_free(value, depth + 1)  # examples, pattern, $comment y desconocidos
    return node


def _w_cache_control(owner: dict, key: str):
    if not _valid_cache_control(owner.get(key)):
        yield ("flag", "cache_control")


# Binarios que devolvió una HERRAMIENTA dentro de un `tool_result` y no se pueden analizar (R39; la captura con la que
# Cowork revisa su resultado): bajo el forzado se reemplazan por una nota de texto neutra —el binario nunca sale hacia el
# destino— en vez de bloquear el pedido. Lo que adjunta la PERSONA en su mensaje sigue siendo no analizable (bloquea).
# Texto neutro (marca blanca): sin nombres de componentes; pide no insistir para no entrar en un bucle de capturas.
UNANALYZABLE_REPLACED_NOTE = ("[imagen omitida por la política de protección de datos: no se envía al modelo. No vuelvas "
                              "a pedir capturas ni imágenes; seguí con lo que tengas en texto.]")
UNANALYZABLE_REPLACED_NOTE_DOCUMENT = ("[documento omitido por la política de protección de datos: no se envía al modelo. "
                                       "No vuelvas a pedir el documento; pedí su contenido como texto.]")
UNANALYZABLE_REPLACED_NOTE_AUDIO = ("[audio omitido por la política de protección de datos: no se envía al modelo. "
                                    "No vuelvas a pedir audio; seguí con lo que tengas en texto.]")


def _replacement_note(kind: str) -> str:
    if kind == "image":
        return UNANALYZABLE_REPLACED_NOTE
    if kind == "audio":
        return UNANALYZABLE_REPLACED_NOTE_AUDIO
    return UNANALYZABLE_REPLACED_NOTE_DOCUMENT


def _w_unanalyzable(blk: dict, kind: str, in_tool_result: bool):
    """Binario no analizable: dentro de un `tool_result` se cambia (en el lugar) por una nota de texto y cuenta como
    reemplazado; en cualquier otro lugar es no analizable y bloquea. La marca de caché del bloque pasa a la nota."""
    if not in_tool_result:
        yield ("flag", kind)
        return
    nota = {"type": "text", "text": _replacement_note(kind)}
    keep_cache = blk.get("cache_control")
    if keep_cache is not None and _valid_cache_control(keep_cache):
        nota["cache_control"] = keep_cache
    blk.clear()
    blk.update(nota)
    yield ("replaced", kind)


def _w_blocks(fmt, content, depth, in_tool_result=False):
    """Contenido de un mensaje o de `system`/`tool_result`: cadena, o lista de bloques. `in_tool_result`: lo devolvió
    una herramienta (bloques de un `tool_result`; en OpenAI, el contenido de un mensaje `tool`)."""
    if isinstance(content, str):
        return (yield ("text", content))
    if isinstance(content, list):
        for i, blk in enumerate(content):
            if isinstance(blk, str):
                content[i] = yield ("text", blk)
            else:
                yield from _w_block(fmt, blk, depth + 1, in_tool_result)
    elif content is not None and not isinstance(content, bool):
        yield from _w_free(content, depth + 1)
    return content


def _w_pdf_block(blk: dict, b64_data, keep_cache, in_tool_result=False):
    """Bloque PDF → bloque de texto con el texto extraído (que el conductor enmascara) o no analizable (dentro de un
    `tool_result`, reemplazado por una nota)."""
    texto, falla = yield ("pdf", b64_data)
    if falla is not None:
        yield from _w_unanalyzable(blk, falla, in_tool_result)
        return
    masked = yield ("text", texto)
    nuevo = {"type": "text", "text": masked}
    if keep_cache is not None and _valid_cache_control(keep_cache):
        nuevo["cache_control"] = keep_cache
    blk.clear()
    blk.update(nuevo)


def _w_block(fmt, blk, depth=0, in_tool_result=False):
    if depth > _MAX_DEPTH:
        yield ("flag", "too_deep")
        return
    if not isinstance(blk, dict):
        yield from _w_free(blk, depth)
        return
    tipo = blk.get("type")
    if fmt == "anthropic":
        if tipo == "image":
            yield from _w_unanalyzable(blk, "image", in_tool_result)
            return
        if tipo == "redacted_thinking":
            yield ("flag", "redacted_thinking")
            return
        if tipo == "document":
            yield from _w_document_anthropic(blk, depth, in_tool_result)
            return
        if tipo not in ("text", "tool_use", "server_tool_use", "tool_result", "thinking"):
            yield ("flag", "unknown_block")
            return
    else:
        if tipo == "image_url":
            yield from _w_unanalyzable(blk, "image", in_tool_result)
            return
        if tipo == "input_audio":
            yield from _w_unanalyzable(blk, "audio", in_tool_result)
            return
        if tipo == "file":
            yield from _w_file_openai(blk, depth, in_tool_result)
            return
        if tipo not in ("text", "refusal"):
            yield ("flag", "unknown_block")
            return
    antes = blk.get("thinking") if tipo == "thinking" else None
    yield from _w_container(fmt, blk, _BLOCK, depth)
    if tipo == "thinking" and blk.get("signature") is not None and blk.get("thinking") != antes:
        yield ("signed_thinking", None)


def _w_document_anthropic(blk, depth, in_tool_result=False):
    fuente = blk.get("source")
    if not isinstance(fuente, dict):
        yield ("flag", "unknown_block")
        return
    tipo = fuente.get("type")
    if tipo == "base64" and fuente.get("media_type") == "application/pdf" and isinstance(fuente.get("data"), str):
        yield from _w_pdf_block(blk, fuente["data"], blk.get("cache_control"), in_tool_result)
        return
    if tipo in ("url", "file"):
        yield from _w_unanalyzable(blk, "document_url", in_tool_result)
        return
    if tipo == "text" and isinstance(fuente.get("data"), str):
        # Texto plano en el cuerpo: es texto, no base64 opaco. Más estricto que la tabla, no menos.
        fuente["data"] = yield ("text", fuente["data"])
        yield from _w_container("anthropic", blk, _BLOCK, depth)
        return
    if tipo == "content":
        yield from _w_blocks("anthropic", fuente.get("content"), depth, in_tool_result)
        yield from _w_container("anthropic", blk, _BLOCK, depth, skip=("source",))
        return
    yield from _w_unanalyzable(blk, "document", in_tool_result)


def _w_file_openai(blk, depth, in_tool_result=False):
    archivo = blk.get("file")
    if not isinstance(archivo, dict):
        yield ("flag", "unknown_block")
        return
    datos = archivo.get("file_data")
    if isinstance(datos, str) and datos.startswith("data:application/pdf;base64,"):
        yield from _w_pdf_block(blk, datos.split(",", 1)[1], None, in_tool_result)
    elif archivo.get("file_id") is not None or (isinstance(datos, str) and not datos.startswith("data:")):
        yield from _w_unanalyzable(blk, "document_url", in_tool_result)
    else:
        yield from _w_unanalyzable(blk, "document", in_tool_result)


def _w_arguments(owner: dict, key: str, depth):
    """`tool_calls[*].function.arguments` (OpenAI): JSON parseado (subárbol libre); si no es JSON válido,
    se analiza y se enmascara como texto."""
    valor = owner[key]
    if not isinstance(valor, str):
        owner[key] = yield from _w_free(valor, depth + 1)
        return
    try:
        parseado = json.loads(valor)
    except ValueError:
        owner[key] = yield ("text", valor)
        return
    nuevo = yield from _w_free(parseado, depth + 1)
    owner[key] = json.dumps(nuevo, ensure_ascii=False)


def _w_container(fmt, nodo, path, depth, skip=(), exempt=frozenset()):
    """Objeto de protocolo: sus claves son nombres de campo (se analizan, nunca se reescriben) y cada valor se
    trata según su POSICIÓN: opaco, estructural, esquema, contenedor conocido o subárbol libre."""
    containers = _S14_CONTAINERS[fmt]
    tipo_bloque = nodo.get("type") if path == _BLOCK else None
    for clave in list(nodo):
        if clave in skip:
            continue
        valor = nodo[clave]
        cp = _cpath(path, clave)
        if exempt and _optionally_exempt(fmt, exempt, cp, nodo):
            continue                                              # exención opcional de la instalación (opaca)
        # Rutas de contenido (no son exenciones): system, contenido de mensajes, tool_result, arguments.
        if path == "" and clave == "system":
            nodo[clave] = yield from _w_blocks(fmt, valor, depth)
            continue
        if path == "messages.*" and clave == "content":
            devuelto = fmt == "openai" and nodo.get("role") in ("tool", "function")   # lo devolvió una herramienta
            nodo[clave] = yield from _w_blocks(fmt, valor, depth, devuelto)
            continue
        if path == _BLOCK and clave == "content" and tipo_bloque == "tool_result":
            nodo[clave] = yield from _w_blocks(fmt, valor, depth, True)
            continue
        if path == "messages.*.tool_calls.*.function" and clave == "arguments":
            yield from _w_arguments(nodo, clave, depth)
            continue
        cls = _class_of(fmt, cp, tipo_bloque)
        if cls is None and cp not in containers:
            yield from _w_scan(clave, depth + 1)                 # campo desconocido: la clave se analiza
            nodo[clave] = yield from _w_free(valor, depth + 1)   # y su valor se enmascara
            continue
        if cls == _CLASS_OPAQUE:
            continue
        if cls == _CLASS_CACHE:
            yield from _w_cache_control(nodo, clave)
            continue
        if cls == _CLASS_SCHEMA:
            yield from _w_schema(valor, depth + 1)
            continue
        if cp in containers and isinstance(valor, dict):
            yield from _w_container(fmt, valor, cp, depth + 1, exempt=exempt)
            continue
        if cp in containers and isinstance(valor, list):
            for i, item in enumerate(valor):
                if isinstance(item, dict):
                    yield from _w_container(fmt, item, cp + ".*", depth + 1, exempt=exempt)
                else:
                    yield from _w_scan(item, depth + 1)
            continue
        if cls == _CLASS_STRUCT:
            yield from _w_scan(valor, depth + 1, _scan_mode(fmt, cp, tipo_bloque))
            continue
        yield from _w_scan(clave, depth + 1)
        nodo[clave] = yield from _w_free(valor, depth + 1)


def _w_body(fmt, body, skip=(), exempt=frozenset()):
    """`skip`: claves de primer nivel que NO son del cliente (la metadata interna del motor y sus copias de
    registro): no se recorren, no se enmascaran y no cuentan."""
    yield from _w_container(fmt, body, "", 0, skip=skip, exempt=exempt)


def detect_body_format(body: dict) -> str:
    """`openai` | `anthropic` según la forma del cuerpo (el guardrail pasa el formato por `call_type`)."""
    for msg in body.get("messages") if isinstance(body.get("messages"), list) else []:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") in ("system", "developer", "tool") or "tool_calls" in msg:
            return "openai"
        contenido = msg.get("content")
        for blk in contenido if isinstance(contenido, list) else []:
            if isinstance(blk, dict) and blk.get("type") in ("image_url", "input_audio", "file"):
                return "openai"
    return "anthropic"


def _drive_sync(gen, handler):
    try:
        op = next(gen)
        while True:
            op = gen.send(handler(op))
    except StopIteration as stop:
        return stop.value


async def _drive(gen, handler):
    try:
        op = next(gen)
        while True:
            op = gen.send(await handler(op))
    except StopIteration as stop:
        return stop.value


def _collect_texts(body: dict, fmt: str, *, with_scans: bool = False, skip=(), exempt=frozenset()) -> list:
    """Todo lo que el alcance completo analizaría (texto libre, claves libres, números), sin mutar `body`
    (el recorrido corre sobre una copia). `with_scans` suma también las posiciones estructurales: lo usa el
    conductor para analizar todo por adelantado; el texto de inspección (AI-Act, secretos) no las lleva."""
    partes: list = []

    def _handler(op):
        tipo, valor = op
        if tipo == "text":
            partes.append(valor)
            return valor
        if tipo == "num":
            partes.append(repr(valor) if isinstance(valor, float) else str(valor))
            return valor
        if tipo == "scan":
            if with_scans:
                partes.append(valor if isinstance(valor, str) else (
                    repr(valor) if isinstance(valor, float) else str(valor)))
            return None
        if tipo == "scan_closed":
            if with_scans and not _in_vocabulary(*valor):      # dentro del vocabulario cerrado: no se analiza
                partes.append(valor[1])
            return None
        if tipo == "scan_open":
            if with_scans:
                partes.append(valor)
            return None
        if tipo == "pdf":
            return (None, "skip")
        return None

    _drive_sync(_w_body(fmt, copy.deepcopy({k: v for k, v in body.items() if k not in skip}), (), exempt), _handler)
    return partes


# ── Extracción de PDF en un proceso hijo (QA v2 N4; research R29 3b) ───────────────────

class PdfConfig:
    """Topes del extractor, leídos del entorno en cada pedido (todas opcionales; valor inválido ⇒ default)."""

    def __init__(self):
        self.max_pages = _env_number("MASKING_PDF_MAX_PAGES", 200, int, 1)
        self.max_bytes = _env_number("MASKING_PDF_MAX_BYTES", 20 * 1024 * 1024, int, 1)
        self.max_memory_mb = _env_number("MASKING_PDF_MAX_MEMORY_MB", 512, int, 1)
        self.timeout_s = _env_number("MASKING_PDF_TIMEOUT_S", 20.0, float, 0.001)
        self.max_concurrency = _env_number("MASKING_PDF_MAX_CONCURRENCY", 2, int, 1)
        self.max_stream_bytes = _env_number("MASKING_PDF_MAX_STREAM_BYTES", 25 * 1024 * 1024, int, 1)
        self.max_text_chars = _env_number("MASKING_PDF_MAX_TEXT_CHARS", 2_000_000, int, 1)
        self.max_per_request = _env_number("MASKING_PDF_MAX_PER_REQUEST", 5, int, 1)
        self.request_deadline_s = _env_number("MASKING_PDF_REQUEST_DEADLINE_S", 30.0, float, 0.001)
        self.cache_entries = _env_number("MASKING_PDF_CACHE_ENTRIES", 32, int, 0)


def _env_number(nombre, default, cast, minimo):
    try:
        valor = cast(os.environ.get(nombre, default))
    except (TypeError, ValueError):
        return default
    return valor if valor >= minimo else default


def pdf_config() -> PdfConfig:
    return PdfConfig()


class PdfRequestBudget:
    """Presupuesto de UN pedido: cuántos PDF lleva y cuándo vence su plazo total (incluye la espera)."""

    def __init__(self):
        self.count = 0
        self.deadline = None


# SHA-256 de los bytes → ("text", texto) | ("fail", tipo). Solo en memoria del proceso, acotada; JAMÁS se
# persiste ni se registra: el historial que las herramientas reenvían en cada turno no re-extrae el mismo PDF.
_PDF_CACHE: "OrderedDict" = OrderedDict()
_PDF_SEM: dict = {}


def reset_pdf_state() -> None:
    _PDF_CACHE.clear()
    _PDF_SEM.clear()


def _pypdf_disponible() -> bool:
    return importlib.util.find_spec("pypdf") is not None


def _pdf_child_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "sentinel_pdf_extract.py")


def _pdf_child_argv(cfg: PdfConfig, timeout_s: float) -> list:
    """`python -I <hijo> <memoria_mb> <cpu_s> <páginas> <flujo> <texto>`. Se lanza por RUTA y no con `-m`: con
    `-I` (aislado) el directorio de las extensiones no está en `sys.path`, y el hijo no importa nada del motor."""
    cpu_s = int(timeout_s) + 5
    return [sys.executable or "python3", "-I", _pdf_child_path(), str(cfg.max_memory_mb), str(cpu_s),
            str(cfg.max_pages), str(cfg.max_stream_bytes), str(cfg.max_text_chars)]


def _pdf_child_env() -> dict:
    """Sin credenciales: el hijo no hereda el entorno del motor, solo lo mínimo para arrancar."""
    return {k: os.environ[k] for k in ("PATH", "LD_LIBRARY_PATH", "LANG", "LC_ALL") if k in os.environ}


async def _spawn_pdf_child(argv: list):
    return await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, env=_pdf_child_env(), close_fds=True, start_new_session=True)


def _pdf_semaphore(cfg: PdfConfig) -> asyncio.Semaphore:
    """Semáforo por proceso del motor (y por bucle de eventos: un `Semaphore` queda atado al bucle)."""
    loop = asyncio.get_running_loop()
    if _PDF_SEM.get("loop") is not loop or _PDF_SEM.get("size") != cfg.max_concurrency:
        _PDF_SEM.clear()
        _PDF_SEM.update(loop=loop, size=cfg.max_concurrency, sem=asyncio.Semaphore(cfg.max_concurrency))
    return _PDF_SEM["sem"]


# Salida del hijo (ver `sentinel_pdf_extract`): 0 ok, 3 tope, 4 protegido, 5 error, 6 sin pypdf.
_CHILD_FAILS = {3: "pdf_resource_limit", 4: "pdf_error", 5: "pdf_error", 6: "pdf_unavailable"}


def _classify_child_exit(codigo: int, salida: bytes):
    """(texto, None) | (None, tipo). Una señal de CPU es plazo; memoria/aborto/violación de segmento, tope."""
    if codigo == 0:
        texto = salida.decode("utf-8", errors="replace")
        return (texto, None) if texto.strip() else (None, "pdf_no_text")
    if codigo in _CHILD_FAILS:
        return None, _CHILD_FAILS[codigo]
    if codigo == -signal.SIGXCPU:
        return None, "pdf_timeout"
    if codigo in (-signal.SIGKILL, -signal.SIGABRT, -signal.SIGSEGV, -signal.SIGBUS):
        return None, "pdf_resource_limit"
    return None, "pdf_error"


async def _run_pdf_child(raw: bytes, cfg: PdfConfig, timeout_s: float):
    """Lanza el hijo, le pasa el PDF y espera con plazo; al vencer (o si se cancela), lo mata. Devuelve
    (código, salida) o (None, b"") si venció el plazo."""
    proc = await _spawn_pdf_child(_pdf_child_argv(cfg, timeout_s))
    try:
        try:
            salida, _ = await asyncio.wait_for(proc.communicate(raw), timeout_s)
        except asyncio.TimeoutError:
            return None, b""
        return proc.returncode, salida
    finally:
        if proc.returncode is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            await asyncio.shield(proc.wait())


def _cache_put(sha: str, valor: tuple, cfg: PdfConfig) -> None:
    if cfg.cache_entries <= 0:
        return
    _PDF_CACHE[sha] = valor
    _PDF_CACHE.move_to_end(sha)
    while len(_PDF_CACHE) > cfg.cache_entries:
        _PDF_CACHE.popitem(last=False)


async def extract_pdf_text(raw: bytes, budget: PdfRequestBudget):
    """Texto de un PDF o su nombre de tipo de no analizable: `(texto, None)` | `(None, tipo)`.

    Nunca corre en el bucle de eventos: un proceso hijo por PDF con límites del sistema operativo y plazo.
    Cualquier fallo ⇒ no analizable; sin `pypdf`, todo PDF lo es (falla cerrado)."""
    cfg = pdf_config()
    budget.count += 1
    if not _pypdf_disponible():
        return None, "pdf_unavailable"
    if len(raw) > cfg.max_bytes:
        return None, "pdf_resource_limit"
    if budget.count > cfg.max_per_request:
        return None, "pdf_request_limit"
    sha = hashlib.sha256(raw).hexdigest()
    previo = _PDF_CACHE.get(sha)
    if previo is not None:
        _PDF_CACHE.move_to_end(sha)
        return (previo[1], None) if previo[0] == "text" else (None, previo[1])
    ahora = time.monotonic()
    if budget.deadline is None:
        budget.deadline = ahora + cfg.request_deadline_s
    restante = budget.deadline - ahora
    if restante <= 0:
        return None, "pdf_request_limit"
    sem = _pdf_semaphore(cfg)
    try:
        await asyncio.wait_for(sem.acquire(), restante)
    except asyncio.TimeoutError:
        return None, "pdf_request_limit"
    try:
        restante = budget.deadline - time.monotonic()
        if restante <= 0:
            return None, "pdf_request_limit"
        plazo = min(cfg.timeout_s, restante)
        codigo, salida = await _run_pdf_child(raw, cfg, plazo)
    finally:
        sem.release()
    if codigo is None:
        # Venció el plazo del PDF (hijo matado) o el total del pedido, lo que llegara primero.
        if restante < cfg.timeout_s:
            return None, "pdf_request_limit"
        resultado = (None, "pdf_timeout")
    else:
        resultado = _classify_child_exit(codigo, salida)
    _cache_put(sha, ("text", resultado[0]) if resultado[1] is None else ("fail", resultado[1]), cfg)
    return resultado


# ═══════════════════════════════════════════════════════════════════════════════════
# S17 — caché de análisis por segmento (057 T110; research R34; contracts/costuras-base.md §S17). BASE: genérico,
# retrocompatible (apagada o ausente, el recorrido es el de siempre). Guarda SOLO detecciones (inicio, fin, tipo de
# entidad, puntaje): jamás el texto, el valor detectado ni un placeholder, que cada pedido genera con su propio mapa.
# ═══════════════════════════════════════════════════════════════════════════════════

_ANALYSIS_CACHE_DEFAULTS = {"max_entries": 20_000, "ttl_s": 3600.0}
_ANALYSIS_CACHE_MAX_DETECTIONS = 1_000        # un segmento con más detecciones no se cachea (acota la memoria por entrada)
_TRUE_WORDS, _FALSE_WORDS = ("1", "true", "yes", "on"), ("0", "false", "no", "off")


class AnalysisCacheConfig:
    """Configuración de la caché, leída del entorno en cada uso (todas opcionales; valor inválido ⇒ el de por defecto)."""

    def __init__(self):
        crudo = os.environ.get("MASKING_ANALYSIS_CACHE_ENABLED", "").strip().lower()
        self.enabled = crudo not in _FALSE_WORDS
        self.max_entries = _env_number("MASKING_ANALYSIS_CACHE_MAX_ENTRIES", _ANALYSIS_CACHE_DEFAULTS["max_entries"], int, 1)
        self.ttl_s = _env_number("MASKING_ANALYSIS_CACHE_TTL_S", _ANALYSIS_CACHE_DEFAULTS["ttl_s"], float, 0.001)
        self.salt = os.environ.get("MASKING_ANALYSIS_CACHE_SALT", "")


def analysis_cache_config() -> AnalysisCacheConfig:
    return AnalysisCacheConfig()


class AnalysisCache:
    """LRU acotada por entradas, con TTL. En proceso (no sale del motor; se pierde al reiniciar).

    Clave: hash hexadecimal de 64 caracteres (ver `analysis_key`). Valor: lista de `(inicio, fin, tipo, puntaje)`.
    `get` devuelve una copia (el llamador puede mutarla); un acceso renueva la entrada."""

    def __init__(self, max_entries: int = 20_000, ttl_s: float = 3600.0, clock=time.monotonic):
        self.max_entries, self.ttl_s, self._clock = max_entries, ttl_s, clock
        self._data: "OrderedDict[str, tuple]" = OrderedDict()      # clave → (vence, detecciones)

    def __len__(self) -> int:
        return len(self._data)

    def get(self, key: str):
        hit = self._data.get(key)
        if hit is None:
            return None
        vence, detecciones = hit
        if self._clock() >= vence:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return list(detecciones)

    def put(self, key: str, detecciones) -> None:
        if len(detecciones) > _ANALYSIS_CACHE_MAX_DETECTIONS:
            return
        self._data[key] = (self._clock() + self.ttl_s, tuple(tuple(d) for d in detecciones))
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    def dump_for_tests(self) -> dict:
        """Todo lo guardado (clave → detecciones), para que un test verifique que no hay texto ni valores."""
        return {k: [list(d) for d in v[1]] for k, v in self._data.items()}


_ANALYSIS_CACHE: Optional[AnalysisCache] = None
_ANALYSIS_CACHE_SHAPE: Optional[tuple] = None


def get_analysis_cache() -> AnalysisCache:
    """La caché del proceso; se vuelve a crear (vacía) si cambian los topes configurados."""
    global _ANALYSIS_CACHE, _ANALYSIS_CACHE_SHAPE
    cfg = analysis_cache_config()
    forma = (cfg.max_entries, cfg.ttl_s)
    if _ANALYSIS_CACHE is None or _ANALYSIS_CACHE_SHAPE != forma:
        _ANALYSIS_CACHE, _ANALYSIS_CACHE_SHAPE = AnalysisCache(cfg.max_entries, cfg.ttl_s), forma
    return _ANALYSIS_CACHE


def reset_analysis_cache() -> None:
    """Vacía la caché del proceso (tests; también sirve para invalidar a mano sin reiniciar)."""
    global _ANALYSIS_CACHE, _ANALYSIS_CACHE_SHAPE
    _ANALYSIS_CACHE, _ANALYSIS_CACHE_SHAPE = None, None


def analysis_config_version(*, region: str, custom_names=None, custom_entities=None, analyzer_url: str = "",
                            salt: Optional[str] = None, language: str = "es") -> str:
    """Huella de TODO lo que cambia el resultado del analizador para un mismo texto: los reconocedores que viajan en
    cada `/analyze` (`build_ad_hoc_recognizers`), los nombres y entidades propias, la región, el idioma, la URL del
    analizador y la sal manual (`MASKING_ANALYSIS_CACHE_SALT`: para cuando cambian los reconocedores DEL analizador sin
    cambiar nada de esto). Cualquier cambio ⇒ otra versión ⇒ otras claves (se invalida sin borrar nada)."""
    nombres = sorted(str(n) for n in (custom_names or []))
    entidades = sorted(json.dumps(e, sort_keys=True, default=str) for e in (custom_entities or []))
    ordenadas = sorted(custom_entities or [], key=lambda e: json.dumps(e, sort_keys=True, default=str))
    reconocedores = json.dumps(build_ad_hoc_recognizers(nombres, region, ordenadas), sort_keys=True, default=str)
    if salt is None:
        salt = analysis_cache_config().salt
    huella = json.dumps({"r": reconocedores, "names": nombres, "ents": entidades, "region": region, "lang": language,
                         "url": analyzer_url, "salt": salt}, sort_keys=True)
    return hashlib.sha256(huella.encode("utf-8")).hexdigest()[:16]


def analysis_key(text: str, *, version: str, scope: str = "", language: str = "es") -> str:
    """`SHA-256(versión | idioma | empresa | texto)`. El texto entra solo como hash."""
    h = hashlib.sha256()
    for parte in (version, language, scope):
        h.update(parte.encode("utf-8"))
        h.update(b"\x00")
    h.update(text.encode("utf-8", "surrogatepass"))
    return h.hexdigest()


def cached_analyze(analyze: AnalyzeFn, *, cache: Optional[AnalysisCache], version: str, scope: str = "",
                   language: str = "es") -> AnalyzeFn:
    """Envuelve el analizador REAL del pedido con la caché. Una instancia por pedido: además de la caché del proceso
    (`cache`, o ninguna si está apagada) lleva una memoria del propio pedido, así que un segmento repetido se analiza una
    vez aunque la caché esté apagada. Lo que no se cachea: una falla del analizador (`NlpUnavailableError` u otra: sube tal
    cual, sin guardar nada) y los segmentos con demasiadas detecciones. No envolver el regex de respaldo de `degrade`."""
    local: dict = {}

    async def _analyze(text: str) -> list:
        if not text:
            return await analyze(text)
        key = analysis_key(text, version=version, scope=scope, language=language)
        hit = local.get(key)
        if hit is None and cache is not None:
            hit = cache.get(key)
        if hit is None:
            raw = await analyze(text)
            hit = [(e["start"], e["end"], e["entity_type"], float(e.get("score", 0.0))) for e in raw]
            if cache is not None:
                cache.put(key, hit)
        local[key] = hit
        return [{"start": d[0], "end": d[1], "entity_type": d[2], "score": d[3]} for d in hit]

    return _analyze


# ── Conductor de enmascarado ─────────────────────────────────────────────────────────

_ANALYZE_CHUNK = 50_000       # un texto más largo se analiza por trozos (en saltos de línea cuando se puede)
_PREFETCH_CONCURRENCY = 8


def _split_for_analysis(text: str) -> list:
    if len(text) <= _ANALYZE_CHUNK:
        return [text]
    trozos, inicio = [], 0
    while inicio < len(text):
        fin = min(inicio + _ANALYZE_CHUNK, len(text))
        if fin < len(text):
            corte = max(text.rfind("\n", inicio, fin), text.rfind(" ", inicio, fin))
            fin = corte + 1 if corte > inicio else fin
        trozos.append(text[inicio:fin])
        inicio = fin
    return trozos


def _replace_entities(text: str, entities: list, pmap: "PlaceholderMap") -> str:
    out = text
    for e in sorted(entities, key=lambda x: x["start"], reverse=True):
        value = text[e["start"]:e["end"]]
        out = out[: e["start"]] + pmap.placeholder_for(value, e["entity_type"]) + out[e["end"]:]
    return out


class _FullScopeMasker:
    """Conductor async del recorrido de alcance completo: analiza (con memoria por texto dentro del
    pedido), reemplaza por marcadores y cuenta."""

    def __init__(self, analyze: AnalyzeFn, pmap: "PlaceholderMap", tally: MaskingTally):
        self.analyze, self.pmap, self.tally = analyze, pmap, tally
        self.budget = PdfRequestBudget()
        self._memo: dict = {}

    async def entities(self, text: str) -> list:
        if not text or not text.strip():
            return []
        if text not in self._memo:
            self._memo[text] = await self._analyze_text(text)
        return self._memo[text]

    async def _analyze_text(self, text: str) -> list:
        trozos = _split_for_analysis(text)
        if len(trozos) == 1:
            return resolve_overlaps(await self.analyze(text))
        out, base = [], 0
        for trozo in trozos:
            for e in resolve_overlaps(await self.analyze(trozo)):
                out.append({**e, "start": e["start"] + base, "end": e["end"] + base})
            base += len(trozo)
        return out

    async def identifier_entities(self, text: str) -> list:
        """Detecciones de un identificador (posición estructural de vocabulario abierto): las de patrón y las propias de la
        empresa. Los tipos de NER semántico se descartan ANTES de resolver solapes: una detección semántica que cubre a
        todo el identificador (`leer 30123456` como PERSON) no puede tapar al patrón que va adentro (el DNI)."""
        if not text or not text.strip():
            return []
        out, base = [], 0
        for trozo in _split_for_analysis(text):
            crudas = [e for e in await self.analyze(trozo) if e.get("entity_type") not in STRUCTURAL_IGNORED_ENTITY_TYPES]
            out.extend({**e, "start": e["start"] + base, "end": e["end"] + base} for e in resolve_overlaps(crudas))
            base += len(trozo)
        return out

    async def prefetch(self, textos: list) -> None:
        """Analiza de a varios a la vez los textos que el recorrido va a pedir (el resultado queda en la
        memoria): un Claude Code típico trae cientos de cadenas cortas y una llamada por cadena en serie suma."""
        pendientes = [t for t in dict.fromkeys(textos) if t and t.strip() and t not in self._memo]
        if len(pendientes) < 2:
            return
        sem = asyncio.Semaphore(_PREFETCH_CONCURRENCY)

        async def _uno(t):
            async with sem:
                self._memo[t] = await self._analyze_text(t)

        await asyncio.gather(*[_uno(t) for t in pendientes])

    async def mask_str(self, text: str) -> str:
        ents = await self.entities(text)
        self.tally.detected += len(ents)
        if not ents:
            return text
        self.tally.masked += len(ents)
        return _replace_entities(text, ents, self.pmap)

    async def handle(self, op):
        tipo, valor = op
        if tipo == "text":
            return await self.mask_str(valor)
        if tipo == "num":
            texto = repr(valor) if isinstance(valor, float) else str(valor)
            ents = await self.entities(texto)
            if not ents:
                return valor
            return await self.mask_str(texto)
        if tipo == "scan_closed":
            vocab, valor = valor
            if _in_vocabulary(vocab, valor):               # vocabulario cerrado del protocolo: nada que analizar
                return None
            tipo = "scan"                                  # fuera del vocabulario: posición estructural normal
        if tipo == "scan_open":
            ents = await self.identifier_entities(valor)
            if ents:
                self.tally.detected += len(ents)
                self.tally.flag("structural_entity")
            return None
        if tipo == "scan":
            ents = await self.entities(valor if isinstance(valor, str) else (
                repr(valor) if isinstance(valor, float) else str(valor)))
            if ents:
                self.tally.detected += len(ents)
                self.tally.flag("structural_entity")
            return None
        if tipo == "flag":
            self.tally.flag(valor)
            return None
        if tipo == "replaced":
            self.tally.replace(valor)
            return None
        if tipo == "pdf":
            # Tope de tamaño ANTES de decodificar: no se materializan 75 MB de un base64 de 100 MB.
            if len(valor) > (pdf_config().max_bytes * 4) // 3 + 8:
                return None, ("pdf_resource_limit" if _pypdf_disponible() else "pdf_unavailable")
            try:
                raw = base64.b64decode(valor, validate=False)
            except (ValueError, TypeError):
                return None, "pdf_error"
            return await extract_pdf_text(raw, self.budget)
        if tipo == "signed_thinking":
            self.tally.signed_thinking_masked += 1
            return None
        return None


def inspect_segments(body: dict, fmt: Optional[str] = None, *, skip_keys=(), exempt=frozenset()) -> list:
    """Los segmentos de texto que el alcance completo analiza (los mismos que `extract_inspect_text(scope="full")` une,
    salvo las exenciones opcionales), sin unirlos ni recortarlos: cada uno es una clave de la caché de análisis (S17)."""
    return _collect_texts(body, fmt or detect_body_format(body), skip=skip_keys, exempt=exempt)


async def analyze_segments(segmentos: list, analyze: AnalyzeFn) -> list:
    """Detecciones de cada segmento con el mismo troceo y la misma concurrencia que el recorrido de alcance completo
    (`_FullScopeMasker.prefetch`). Con `analyze` envuelto por `cached_analyze`, lo que analiza acá queda en la caché y
    el recorrido de enmascarado lo encuentra: el análisis previo por tipo no suma una segunda pasada (S17)."""
    masker = _FullScopeMasker(analyze, PlaceholderMap(), MaskingTally())
    unicos = list(dict.fromkeys(t for t in segmentos if t and t.strip()))
    await masker.prefetch(unicos)
    out: list = []
    for t in unicos:
        out.extend(await masker.entities(t))
    return out


async def _mask_body_full(body: dict, analyze: AnalyzeFn, pmap: "PlaceholderMap", fmt: str,
                          tally: MaskingTally, skip=(), exempt=frozenset()) -> None:
    masker = _FullScopeMasker(analyze, pmap, tally)
    await masker.prefetch(_collect_texts(body, fmt, with_scans=True, skip=skip, exempt=exempt))
    await _drive(_w_body(fmt, body, skip, exempt), masker.handle)


async def mask_body(body: dict, analyze: AnalyzeFn,
                    pmap: Optional[PlaceholderMap] = None, *, scope: str = MASKING_SCOPE_USER,
                    fmt: Optional[str] = None, tally: Optional[MaskingTally] = None,
                    skip_keys=(), exempt=frozenset()) -> Tuple[dict, dict]:
    """Enmascara la PII del request. Devuelve (body mutado, mapa placeholder→original).

    Sin `scope` (o `scope="user"`): solo los turnos USER, como siempre (no el system prompt ni las
    herramientas — mismo alcance que el demo). Con `scope="full"` (S14, enmascarado forzado): TODO valor de
    texto que sale hacia el destino —`system`, todos los turnos, `tool_use`, `tool_result`, `thinking`,
    descripciones de herramientas y todo campo desconocido—, salvo las posiciones estructurales de
    `S14_EXEMPT_POSITIONS`; los PDF con texto viajan como texto enmascarado y lo no analizable queda contado
    en `tally` (`MaskingTally`, solo conteos y nombres de tipo). `fmt` = `anthropic` | `openai`.
    `skip_keys`: claves de primer nivel internas del motor que no se recorren (metadata interna, copias de
    registro de la pasarela). `exempt`: exenciones opcionales de la instalación (`optional_exemptions()`; solo con
    `scope="full"`), por defecto ninguna."""
    pmap = pmap or PlaceholderMap()
    if scope == MASKING_SCOPE_FULL:
        await _mask_body_full(body, analyze, pmap, fmt or detect_body_format(body),
                              tally if tally is not None else MaskingTally(), skip=skip_keys, exempt=exempt)
    else:
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
        # Las CLAVES también (S14: bajo el enmascarado forzado una clave con datos sale como marcador y el
        # modelo la repite en su `tool_use`); una clave sin marcador no cambia.
        return {(unmask_text(k, ph_to_orig) if isinstance(k, str) else k): unmask_deep(v, ph_to_orig)
                for k, v in obj.items()}
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
