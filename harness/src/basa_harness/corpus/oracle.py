"""Oráculo del corpus — los reconocedores REALES del producto, replicados aquí.

Fuente canónica de verdad: ``litellm/extensions/basa_guardian_policy.py`` (config
baseline región ``eu``, SIN ``custom_names``/``custom_entities``). Este módulo NO
importa esa extensión (arrastra ``httpx`` y no está en el path del paquete): replica
el patrón de teléfono verbatim y los algoritmos de checksum que Presidio aplica para
``es``. El test ``test_corpus.py`` verifica que el patrón replicado siga presente en
el archivo fuente (detección de deriva), así el corpus nunca genera valores que el
detector real no vería.

Regla de oro (research.md R6): «un corpus que el NLP no detectaría produciría falsos
0 fugas». Por eso cada valor estructurado (NIF/NIE/IBAN/tarjeta) lleva checksum válido
y cada teléfono matchea el patrón nacional español.
"""
from __future__ import annotations

import re

# Enum CERRADO del baseline (corpus-format.md regla 1). Tipo desconocido = ERROR.
ENTITY_TYPES: frozenset[str] = frozenset({
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE", "CREDIT_CARD",
    "ES_NIF", "ES_NIE", "PASSPORT", "LOCATION", "DATE_TIME",
})

# ── Patrones replicados de basa_guardian_policy.py ────────────────────────────────

# STRUCTURED_ID_PATTERNS_BY_REGION["eu"]["PHONE_NUMBER"] (basa_guardian_policy.py:89):
# 9 dígitos empezando en 6-9, prefijo +34/0034 opcional. Replicado VERBATIM — el test
# de deriva comprueba que esta cadena exacta siga en el archivo fuente.
PHONE_PATTERN = r"\b(?:(?:\+|00)\s?34[\s.-]?)?[6-9](?:[\s.-]?\d){8}\b"
PHONE_RE = re.compile(PHONE_PATTERN)

# STRUCTURED_ID_PATTERNS_BY_REGION["eu"]["PASSPORT"] (basa_guardian_policy.py:85):
# alfanumérico 6-9 con palabra de contexto ("pasaporte"/"passport") cerca.
PASSPORT_PATTERN = r"\b[A-Z0-9]{6,9}\b"
PASSPORT_RE = re.compile(PASSPORT_PATTERN)

# PII_PATTERNS["EMAIL_ADDRESS"] (dev-fallback, basa_guardian_policy.py:58). El
# built-in de Presidio también cubre email; usamos este para el test estructural.
EMAIL_PATTERN = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
EMAIL_RE = re.compile(EMAIL_PATTERN)

# ── Checksums (built-in de Presidio para "es"; los replicamos para generar válidos) ──

# Letra de control DNI/NIF: índice = número mod 23 sobre este alfabeto (sin I,O,U,Ñ).
_NIF_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
# NIE: la letra inicial se sustituye por dígito para el checksum (X→0, Y→1, Z→2).
_NIE_PREFIX_DIGIT = {"X": "0", "Y": "1", "Z": "2"}
# Pesos del dígito de control nacional del IBAN español (BBAN mod 11).
_ES_DC_WEIGHTS = (1, 2, 4, 8, 5, 10, 9, 7, 3, 6)


def nif_control_letter(numero: str) -> str:
    """Letra de control de un NIF de 8 dígitos (algoritmo mod 23)."""
    return _NIF_LETTERS[int(numero) % 23]


def is_valid_nif(value: str) -> bool:
    """True si ``value`` es un NIF con letra de control correcta (8 dígitos + letra)."""
    m = re.fullmatch(r"(\d{8})([A-Z])", value)
    return bool(m) and m.group(2) == nif_control_letter(m.group(1))


def nie_control_letter(prefijo: str, siete_digitos: str) -> str:
    """Letra de control de un NIE (prefijo X/Y/Z + 7 dígitos)."""
    numero = _NIE_PREFIX_DIGIT[prefijo] + siete_digitos
    return _NIF_LETTERS[int(numero) % 23]


def is_valid_nie(value: str) -> bool:
    """True si ``value`` es un NIE con letra de control correcta."""
    m = re.fullmatch(r"([XYZ])(\d{7})([A-Z])", value)
    return bool(m) and m.group(3) == nie_control_letter(m.group(1), m.group(2))


def _es_bban_dc(ten_digits: str) -> int:
    """Un dígito de control nacional español sobre 10 dígitos (mod 11)."""
    s = sum(int(d) * w for d, w in zip(ten_digits, _ES_DC_WEIGHTS))
    r = 11 - (s % 11)
    return {10: 1, 11: 0}.get(r, r)


def es_national_control(bank: str, branch: str, account: str) -> str:
    """Los 2 dígitos de control nacionales (DC) de una cuenta española."""
    dc1 = _es_bban_dc("00" + bank + branch)
    dc2 = _es_bban_dc(account)
    return f"{dc1}{dc2}"


def _iban_check_digits(bban: str) -> str:
    """Dígitos de control ISO 13616 (mod 97) de un IBAN español (país ES)."""
    # Reordenar: BBAN + "ES" + "00"; E=14, S=28 → BBAN + "142800".
    rearranged = bban + "142800"
    return "%02d" % (98 - (int(rearranged) % 97))


def build_iban_es(bank: str, branch: str, account: str) -> str:
    """IBAN español compacto y válido (ES + control + BBAN de 20 dígitos)."""
    control = es_national_control(bank, branch, account)
    bban = bank + branch + control + account
    return "ES" + _iban_check_digits(bban) + bban


def is_valid_iban_es(value: str) -> bool:
    """True si ``value`` (con o sin espacios) es un IBAN ES con control mod 97 correcto."""
    compact = value.replace(" ", "")
    if not re.fullmatch(r"ES\d{22}", compact):
        return False
    # ISO 13616: mover "ES" + 2 dígitos de control al final; E=14, S=28.
    rearranged = compact[4:] + "1428" + compact[2:4]
    return int(rearranged) % 97 == 1


def luhn_check_digit(number_without_check: str) -> int:
    """Dígito verificador de Luhn a apendar al final del número."""
    total = 0
    for i, ch in enumerate(reversed(number_without_check)):
        d = int(ch)
        if i % 2 == 0:  # posición que quedará par (doblada) al apendar el verificador
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - (total % 10)) % 10


def is_valid_luhn(number: str) -> bool:
    """True si ``number`` (solo dígitos, sin separadores) satisface Luhn."""
    if not number.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0
