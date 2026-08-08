"""Unit tests de basa_guardian_policy (spec 014 T006, FR-022).

Librería PURA: la detección se inyecta como callable — acá un detector fake por
patrones fijos, sin Presidio ni DB. Cubre: mask reversible con nonce, colisión de
placeholder con literal del usuario, carry-split (placeholder partido vs '[' suelto
de código), round-trip text/thinking/tool_use y stream truncado.
"""
import json
import re

import pytest

from extensions import basa_guardian_policy as policy

# Detector fake: emails y el nombre "Juan Pérez" (spans exactos, estilo Presidio)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_NAME = "Juan Pérez"


async def fake_analyze(text: str) -> list:
    entities = []
    for m in _EMAIL_RE.finditer(text):
        entities.append({"start": m.start(), "end": m.end(), "entity_type": "EMAIL_ADDRESS"})
    start = text.find(_NAME)
    while start != -1:
        entities.append({"start": start, "end": start + len(_NAME), "entity_type": "PERSON"})
        start = text.find(_NAME, start + 1)
    return entities


@pytest.mark.asyncio
async def test_mask_is_reversible_and_upstream_sees_placeholders():
    body = {"messages": [
        {"role": "user", "content": f"Soy {_NAME}, mi mail es juan@acme.com"},
    ]}
    masked, ph_to_orig = await policy.mask_body(body, fake_analyze)

    text = masked["messages"][0]["content"]
    assert _NAME not in text and "juan@acme.com" not in text
    assert "[PERSON_0_" in text and "[EMAIL_ADDRESS_0_" in text
    # Round-trip completo
    assert policy.unmask_text(text, ph_to_orig) == f"Soy {_NAME}, mi mail es juan@acme.com"


@pytest.mark.asyncio
async def test_same_value_gets_same_placeholder_across_request():
    body = {"messages": [
        {"role": "user", "content": f"{_NAME} escribió"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": f"resumí lo de {_NAME}"},
    ]}
    masked, ph_to_orig = await policy.mask_body(body, fake_analyze)
    ph_first = masked["messages"][0]["content"].split(" escribió")[0]
    assert ph_first in masked["messages"][2]["content"]
    assert len([p for p in ph_to_orig if p.startswith("[PERSON_")]) == 1


@pytest.mark.asyncio
async def test_system_and_assistant_turns_are_not_masked():
    """Mismo alcance que el demo: solo turnos user (el system prompt no se toca)."""
    body = {
        "system": f"Sos el asistente de {_NAME}",
        "messages": [{"role": "assistant", "content": f"Hola {_NAME}"}],
    }
    masked, ph_to_orig = await policy.mask_body(body, fake_analyze)
    assert masked["system"] == f"Sos el asistente de {_NAME}"
    assert masked["messages"][0]["content"] == f"Hola {_NAME}"
    assert ph_to_orig == {}


@pytest.mark.asyncio
async def test_tool_result_blocks_are_masked():
    body = {"messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": f"mail: juan@acme.com"},
            {"type": "tool_result", "content": [
                {"type": "text", "text": f"cliente: {_NAME}"},
            ]},
        ],
    }]}
    masked, ph_to_orig = await policy.mask_body(body, fake_analyze)
    assert "juan@acme.com" not in json.dumps(masked)
    assert _NAME not in json.dumps(masked)
    assert len(ph_to_orig) == 2


@pytest.mark.asyncio
async def test_user_typed_placeholder_literal_does_not_collide():
    """El nonce por request evita que un literal tipeado por el usuario
    ("[PERSON_0]" o incluso un placeholder con otro nonce) colisione en el unmask."""
    literal = "[PERSON_0]"
    body = {"messages": [{"role": "user", "content": f"{literal} no es {_NAME}"}]}
    masked, ph_to_orig = await policy.mask_body(body, fake_analyze)

    text = masked["messages"][0]["content"]
    assert literal in text  # el literal del usuario queda intacto
    restored = policy.unmask_text(text, ph_to_orig)
    assert restored == f"{literal} no es {_NAME}"


def test_safe_split_holds_placeholder_fragment_but_not_code():
    # Fragmento que PUEDE ser un placeholder en curso → se retiene
    safe, carry = policy.safe_split("hola [PERSON_0_a")
    assert safe == "hola " and carry == "[PERSON_0_a"
    # '[' suelto de código/prosa → se emite ya (el streaming no se frena)
    safe, carry = policy.safe_split("arr[i")
    assert safe == "arr[i" and carry == ""
    safe, carry = policy.safe_split("nums[0")
    assert safe == "nums[0" and carry == ""
    # placeholder ya cerrado → nada que retener
    safe, carry = policy.safe_split("hola [PERSON_0_ab12] chau")
    assert carry == ""
    # fragmento absurdo de largo > MAX_CARRY no se retiene
    safe, carry = policy.safe_split("x[" + "A" * 60)
    assert carry == ""


def _stream_roundtrip(deltas, ph_to_orig, delta_type="text_delta"):
    """Alimenta deltas al StreamUnmasker y devuelve el texto reconstruido."""
    field = policy.DELTA_FIELDS[delta_type]
    um = policy.StreamUnmasker(ph_to_orig)
    out = []
    for chunk in deltas:
        events = um.feed({"type": "content_block_delta", "index": 0,
                          "delta": {"type": delta_type, field: chunk}})
        out.extend(e["delta"][field] for e in events if e.get("type") == "content_block_delta")
    events = um.feed({"type": "content_block_stop", "index": 0})
    out.extend(e["delta"][field] for e in events if e.get("type") == "content_block_delta")
    return "".join(out)


def test_stream_unmask_placeholder_split_across_chunks():
    ph_to_orig = {"[PERSON_0_ab12]": _NAME}
    # El placeholder viene partido en 3 chunks
    text = _stream_roundtrip(["Hola [PER", "SON_0_", "ab12], todo bien"], ph_to_orig)
    assert text == f"Hola {_NAME}, todo bien"


@pytest.mark.asyncio
async def test_stream_unmask_survives_overlap_resolution_with_different_length(monkeypatch):
    """T031: el placeholder que termina en el texto enmascarado depende de CUÁL
    entidad ganó `resolve_overlaps` — un tipo más largo (p.ej. ES_NIF, 6 chars) puede
    ganarle a uno más corto (p.ej. ID, 2 chars) que se solapaba, cambiando el largo
    total del placeholder respecto de lo que se vería sin resolver el solapamiento.
    El carry-split (basado en el nonce y el patrón `[A-Z][A-Za-z0-9_]*`, no en un
    largo fijo) tiene que seguir funcionando igual, partido en cualquier punto."""
    text = "El documento 12345678Z es válido"

    async def analyze_with_overlap(t: str) -> list:
        # Dos candidatos que se solapan sobre el mismo rango de dígitos+letra —
        # ES_NIF (más largo/específico) debe ganarle a un ID genérico más corto.
        start = t.index("12345678Z")
        end = start + len("12345678Z")
        return [
            {"start": start, "end": start + 8, "entity_type": "ID", "score": 0.5},
            {"start": start, "end": end, "entity_type": "ES_NIF", "score": 1.0},
        ]

    pmap = policy.PlaceholderMap()
    masked = await policy.mask_text(text, analyze_with_overlap, pmap)
    # Confirma que efectivamente ganó el más largo (ES_NIF), no "ID":
    assert "[ES_NIF_0_" in masked and "[ID_0_" not in masked

    # Parte el texto YA ENMASCARADO en todos los puntos posibles y confirma
    # reconstrucción exacta en cada uno — no solo en el punto "cómodo" de un test
    # armado a mano con un placeholder de largo fijo.
    for split_at in range(1, len(masked)):
        chunks = [masked[:split_at], masked[split_at:]]
        rebuilt = _stream_roundtrip(chunks, pmap.ph_to_orig)
        assert rebuilt == text, f"falló partiendo en {split_at}: {chunks!r} -> {rebuilt!r}"


def test_stream_unmask_roundtrip_thinking_and_tool_use():
    ph_to_orig = {"[EMAIL_ADDRESS_0_ff00]": "juan@acme.com"}
    thinking = _stream_roundtrip(
        ["analizo [EMAIL_ADD", "RESS_0_ff00] a ver"], ph_to_orig, "thinking_delta")
    assert thinking == "analizo juan@acme.com a ver"

    tool_json = _stream_roundtrip(
        ['{"to": "[EMAIL', '_ADDRESS_0_ff00]"}'], ph_to_orig, "input_json_delta")
    assert tool_json == '{"to": "juan@acme.com"}'


def test_stream_truncated_flushes_carry_without_losing_text():
    """Stream cortado a mitad de un posible placeholder: flush() emite el carry —
    0 texto perdido (aunque quede sin des-enmascarar por incompleto)."""
    ph_to_orig = {"[PERSON_0_ab12]": _NAME}
    um = policy.StreamUnmasker(ph_to_orig)
    events = um.feed({"type": "content_block_delta", "index": 0,
                      "delta": {"type": "text_delta", "text": "hola [PERSON_0"}})
    emitted = "".join(e["delta"]["text"] for e in events)
    assert emitted == "hola "
    flushed = um.flush()
    assert flushed and flushed[0]["delta"]["text"] == "[PERSON_0"


class _FakeResponse:
    def __init__(self, status_code=200, json_body=None):
        self.status_code = status_code
        self._json = json_body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class _FakeAsyncClient:
    """Doble de httpx.AsyncClient — evita red real en unit tests (spec 016)."""

    def __init__(self, response=None, raise_exc=None, **kwargs):
        self._response = response
        self._raise_exc = raise_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None):
        if self._raise_exc:
            raise self._raise_exc
        return self._response


# ── resolve_overlaps (spec 016 FR-009) ─────────────────────────────────────────

def test_resolve_overlaps_no_overlap_is_noop():
    entities = [
        {"start": 0, "end": 3, "entity_type": "DNI", "score": 0.9},
        {"start": 10, "end": 15, "entity_type": "EMAIL_ADDRESS", "score": 0.9},
    ]
    assert policy.resolve_overlaps(entities) == entities


def test_resolve_overlaps_longer_match_wins():
    # Un "DNI" completo contiene un match parcial de "PHONE_NUMBER" — gana el más largo.
    phone = {"start": 0, "end": 7, "entity_type": "PHONE_NUMBER", "score": 0.95}
    dni = {"start": 0, "end": 9, "entity_type": "DNI", "score": 0.85}
    result = policy.resolve_overlaps([phone, dni])
    assert result == [dni]


def test_resolve_overlaps_tie_break_by_score():
    a = {"start": 0, "end": 5, "entity_type": "PERSON", "score": 0.6}
    b = {"start": 0, "end": 5, "entity_type": "LOCATION", "score": 0.9}
    assert policy.resolve_overlaps([a, b]) == [b]


def test_resolve_overlaps_preserves_input_order_for_survivors():
    e1 = {"start": 20, "end": 25, "entity_type": "EMAIL_ADDRESS", "score": 0.9}
    e2 = {"start": 0, "end": 5, "entity_type": "PERSON", "score": 0.9}
    assert policy.resolve_overlaps([e1, e2]) == [e1, e2]


def test_resolve_overlaps_empty_input():
    assert policy.resolve_overlaps([]) == []


def test_resolve_overlaps_chained_three_way_never_leaves_overlap():
    # A solapa B, B solapa C, pero A y C no se tocan directamente — deben ir al
    # mismo cluster y sobrevivir solo UNA (regresión del algoritmo par-a-par).
    a = {"start": 0, "end": 6, "entity_type": "PHONE_NUMBER", "score": 0.9}
    b = {"start": 4, "end": 12, "entity_type": "DNI", "score": 0.85}
    c = {"start": 10, "end": 16, "entity_type": "CUIL", "score": 0.9}
    result = policy.resolve_overlaps([a, b, c])
    assert len(result) == 1
    for i in range(len(result) - 1):
        assert result[i]["end"] <= result[i + 1]["start"]


# ── resolve_entity_action (spec 016 FR-005/FR-008) ─────────────────────────────

def test_resolve_entity_action_respects_config():
    cfg = {"CREDIT_CARD": "BLOCK", "PERSON": "MASK"}
    assert policy.resolve_entity_action("CREDIT_CARD", cfg) == "BLOCK"
    assert policy.resolve_entity_action("PERSON", cfg) == "MASK"


def test_resolve_entity_action_defaults_to_mask():
    assert policy.resolve_entity_action("PASSPORT", {}) == "MASK"
    assert policy.resolve_entity_action("PASSPORT", None) == "MASK"
    assert policy.resolve_entity_action("PASSPORT", {"PASSPORT": "invalid-value"}) == "MASK"


# ── build_ad_hoc_recognizers (spec 016 §3, SC-006) ──────────────────────────────

def test_build_ad_hoc_recognizers_default_region_is_eu_passport_and_phone():
    # España (ES_NIF/ES_NIE) ya viene built-in en Presidio — NO se reimplementa acá.
    # El teléfono SÍ: el built-in sólo reconoce el número con prefijo internacional.
    recognizers = policy.build_ad_hoc_recognizers([])
    entities = {r["supported_entity"] for r in recognizers}
    assert entities == {"PASSPORT", "PHONE_NUMBER"}
    assert not any(r.get("deny_list") for r in recognizers)
    passport = next(r for r in recognizers if r["supported_entity"] == "PASSPORT")
    assert "passport" in passport["context"] and "pasaporte" in passport["context"]


@pytest.mark.parametrize("texto", [
    "Llamame al 612 345 678 cuando puedas.",   # móvil sin prefijo: el caso que se escapaba
    "Mi numero es 612345678.",                  # sin separadores
    "Oficina: 912 345 678.",                    # fijo
    "Contacto 612-345-678.",                    # con guiones
    "Telefono +34 912 345 678.",                # con prefijo internacional
    "Llamar al 0034 612 345 678.",              # prefijo en formato 00
])
def test_es_phone_pattern_detecta_numeracion_espaniola(texto):
    """El built-in PHONE_NUMBER de Presidio sólo reconoce el número con prefijo
    internacional (verificado contra el sidecar real, 2026-07-27). Como el motor usa
    el NLP EN LUGAR del regex, sin este patrón los móviles españoles viajaban en claro."""
    pattern = policy.STRUCTURED_ID_PATTERNS_BY_REGION["eu"]["PHONE_NUMBER"][0]
    assert re.search(pattern, texto), f"no detectó el teléfono en: {texto!r}"


@pytest.mark.parametrize("texto", [
    "La factura numero 202600145 esta pendiente.",   # 9 dígitos que no empiezan en 6-9
    "El importe asciende a 123456789 centimos.",
    "IBAN ES9121000418450200051332 para la transferencia.",
    "El NIF de la empresa es B12345678.",
    "Codigo postal 28001, Madrid.",
])
def test_es_phone_pattern_no_marca_numeros_que_no_son_telefonos(texto):
    """El precio de la cobertura no puede ser enmascarar toda cifra larga: una Cámara
    de Comercio mueve facturas, importes y expedientes en cada prompt."""
    pattern = policy.STRUCTURED_ID_PATTERNS_BY_REGION["eu"]["PHONE_NUMBER"][0]
    assert not re.search(pattern, texto), f"falso positivo en: {texto!r}"


def test_build_ad_hoc_recognizers_adds_deny_list_when_names_present():
    recognizers = policy.build_ad_hoc_recognizers(["Pedro", " Cristian ", "", "  "])
    deny = next(r for r in recognizers if r["name"] == "BASA_CUSTOM_NAMES")
    assert deny["deny_list"] == ["Pedro", "Cristian"]
    assert deny["supported_entity"] == "PERSON"


def test_build_ad_hoc_recognizers_latam_region_adds_dni_cuil():
    recognizers = policy.build_ad_hoc_recognizers([], region="latam_ar")
    entities = {r["supported_entity"] for r in recognizers}
    assert entities == {"DNI", "CUIL", "PASSPORT"}


def test_build_ad_hoc_recognizers_unknown_region_is_empty():
    assert policy.build_ad_hoc_recognizers([], region="mars") == []


def test_build_ad_hoc_recognizers_includes_active_custom_entities():
    custom_entities = [
        {"entity_type": "HISTORIA_CLINICA_ES", "regex": r"\bHC-\d{6}\b",
         "score": 0.7, "context": ["historia clínica"], "status": "active"},
        {"entity_type": "DRAFT_ONLY", "regex": r"\bXX\d{4}\b", "status": "draft"},
    ]
    recognizers = policy.build_ad_hoc_recognizers([], custom_entities=custom_entities)
    entities = {r["supported_entity"] for r in recognizers}
    # Los estructurados de la región eu (PASSPORT, PHONE_NUMBER) + la entidad custom
    # activa; la de status="draft" NUNCA llega al Analyzer real (revisión humana
    # obligatoria, ver entity_catalog_service).
    assert entities == {"PASSPORT", "PHONE_NUMBER", "HISTORIA_CLINICA_ES"}


def test_build_ad_hoc_recognizers_ignores_custom_entity_without_regex():
    custom_entities = [{"entity_type": "SIN_REGEX", "status": "active"}]
    recognizers = policy.build_ad_hoc_recognizers([], custom_entities=custom_entities)
    assert "SIN_REGEX" not in {r["supported_entity"] for r in recognizers}


# ── presidio_analyze (spec 016 FR-004, contracts/presidio-analyzer-http.md) ────

@pytest.mark.asyncio
async def test_presidio_analyze_success(monkeypatch):
    body = [{"start": 0, "end": 10, "entity_type": "PERSON", "score": 0.85}]
    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda **kw: _FakeAsyncClient(response=_FakeResponse(200, body)),
    )
    result = await policy.presidio_analyze("Juan Pérez fue", "http://presidio:3000", [])
    assert result == body


@pytest.mark.asyncio
async def test_presidio_analyze_fails_closed_on_timeout(monkeypatch):
    import httpx as httpx_mod
    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda **kw: _FakeAsyncClient(raise_exc=httpx_mod.TimeoutException("boom")),
    )
    with pytest.raises(policy.NlpUnavailableError):
        await policy.presidio_analyze("hola", "http://presidio:3000", [])


@pytest.mark.asyncio
async def test_presidio_analyze_fails_closed_on_bad_status(monkeypatch):
    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda **kw: _FakeAsyncClient(response=_FakeResponse(503, None)),
    )
    with pytest.raises(policy.NlpUnavailableError):
        await policy.presidio_analyze("hola", "http://presidio:3000", [])


@pytest.mark.asyncio
async def test_presidio_analyze_fails_closed_on_malformed_body(monkeypatch):
    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda **kw: _FakeAsyncClient(response=_FakeResponse(200, {"not": "a list"})),
    )
    with pytest.raises(policy.NlpUnavailableError):
        await policy.presidio_analyze("hola", "http://presidio:3000", [])


@pytest.mark.asyncio
async def test_presidio_analyze_empty_text_short_circuits(monkeypatch):
    # No debe llamar a la red para texto vacío.
    def _boom(**kw):
        raise AssertionError("no debería llamar a httpx con texto vacío")
    monkeypatch.setattr("httpx.AsyncClient", _boom)
    assert await policy.presidio_analyze("", "http://presidio:3000", []) == []


def test_rewrite_sse_block_full_stream():
    """Nivel SSE (Estrategia B / passthrough OAuth): reescritura de bloques crudos,
    con extracción de usage al pasar."""
    ph_to_orig = {"[PERSON_0_ab12]": _NAME}
    blocks = [
        'event: message_start\ndata: {"type": "message_start", "message": {"usage": {"input_tokens": 12}}}',
        'event: content_block_start\ndata: {"type": "content_block_start", "index": 0}',
        'event: content_block_delta\ndata: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hola [PERSON"}}',
        'event: content_block_delta\ndata: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "_0_ab12]!"}}',
        'event: content_block_stop\ndata: {"type": "content_block_stop", "index": 0}',
        'event: message_delta\ndata: {"type": "message_delta", "usage": {"output_tokens": 7}}',
    ]
    carry, field = "", None
    out_text, in_tok, out_tok = [], None, None
    for block in blocks:
        outs, carry, field, itk, otk = policy.rewrite_sse_block(block, carry, field, ph_to_orig)
        in_tok = itk if itk is not None else in_tok
        out_tok = otk if otk is not None else out_tok
        for ob in outs:
            for line in ob.split("\n"):
                if line.startswith("data:"):
                    data = json.loads(line[5:])
                    if data.get("type") == "content_block_delta":
                        out_text.append(data["delta"]["text"])
    assert "".join(out_text) == f"Hola {_NAME}!"
    assert in_tok == 12 and out_tok == 7
    assert carry == ""


# ── Fallback honesto: default_analyze (#64, golden del piloto Cámara) ───────────────
#
# El fallback regex es el camino de DEGRADE (issue #63: por default es `block`; el regex
# sólo actúa si el admin eligió `degrade`, o en dev/demo sin NLP_ANALYZER_URL). NO
# sustituye al NLP (los nombres sin tratamiento siguen necesitando NER real). Estos tests
# blindan el arreglo del #64: el paracaídas no MIENTE mientras actúa — no trocea IBANs en
# falsos teléfonos, no etiqueta facturas como PHONE_NUMBER, y lo que no reconoce con
# confianza lo deja sin tocar (hueco honesto) en vez de sobre-enmascarar con etiqueta falsa.


async def _fallback_mask(text: str):
    """Enmascara `text` con el fallback regex real (`default_analyze`) y devuelve
    (masked, tipos_detectados, pmap) para afirmar tipo + round-trip."""
    pmap = policy.PlaceholderMap()
    masked = await policy.mask_text(text, policy.default_analyze, pmap)
    types = [policy.PH_TYPE_RE.match(ph).group(1) for ph in pmap.ph_to_orig]
    return masked, types, pmap


@pytest.mark.asyncio
async def test_fallback_iban_no_se_trocea_ni_deja_prefijo_en_claro():
    """Golden #1 del piloto: `ES91 2100 0418 4502 0005 1332` entra como UN solo
    [IBAN_CODE], sin dejar el prefijo `ES91` en claro y sin partirse en dos
    [PHONE_NUMBER] (el bug exacto del #64)."""
    text = "Transfiere a ES91 2100 0418 4502 0005 1332 antes del viernes"
    masked, types, pmap = await _fallback_mask(text)
    assert types == ["IBAN_CODE"]
    assert masked.count("[IBAN_CODE_") == 1
    assert "PHONE_NUMBER" not in "|".join(types)      # CERO teléfonos falsos
    assert "ES91" not in masked and "1332" not in masked  # nada del IBAN en claro
    assert policy.unmask_text(masked, pmap.ph_to_orig) == text  # round-trip exacto


@pytest.mark.asyncio
async def test_fallback_referencias_no_son_telefonos_falsos():
    """Golden #2: números de factura/expediente NO deben salir como [PHONE_NUMBER]
    (auditoría con "teléfonos" inexistentes, conteos inflados). El fallback los deja SIN
    TOCAR — mejor un hueco honesto que una etiqueta falsa."""
    text = "Refs FAC-2026-001587 y PROP-2026-1842 pendientes de pago"
    masked, types, _ = await _fallback_mask(text)
    assert types == []
    assert masked == text                              # intacto, sin PHONE_NUMBER inventado


@pytest.mark.asyncio
async def test_fallback_dni_espaniol_es_es_nif_por_formato():
    """Golden #3: `12345678Z` (DNI español) se reconoce como ES_NIF por FORMATO."""
    text = "El titular presenta DNI 12345678Z en la solicitud"
    masked, types, pmap = await _fallback_mask(text)
    assert types == ["ES_NIF"]
    assert "12345678Z" not in masked
    assert policy.unmask_text(masked, pmap.ph_to_orig) == text


@pytest.mark.asyncio
async def test_fallback_nie_espaniol_es_es_nie_por_formato():
    """Complemento del #3: el NIE (letra inicial X/Y/Z) sale como ES_NIE por formato."""
    text = "Extranjero con NIE X1234567L verificado"
    masked, types, pmap = await _fallback_mask(text)
    assert types == ["ES_NIE"]
    assert "X1234567L" not in masked
    assert policy.unmask_text(masked, pmap.ph_to_orig) == text


@pytest.mark.asyncio
async def test_fallback_tarjeta_valida_es_credit_card_luhn():
    """Golden #4: `4111 1111 1111 1111` (Luhn válido) sale como CREDIT_CARD."""
    text = "Pago con la tarjeta 4111 1111 1111 1111 hoy"
    masked, types, pmap = await _fallback_mask(text)
    assert types == ["CREDIT_CARD"]
    assert "4111" not in masked
    assert policy.unmask_text(masked, pmap.ph_to_orig) == text


@pytest.mark.asyncio
async def test_fallback_numero_largo_no_luhn_no_es_tarjeta():
    """#64: una corrida de 13-19 dígitos que NO valida Luhn (un nº de pedido) no se
    etiqueta como CREDIT_CARD — hueco honesto, no una etiqueta falsa. El NLP real es quien
    decide los casos dudosos; el paracaídas no inventa tarjetas."""
    text = "El pedido 1234567890123 sigue en curso"       # 13 dígitos, no Luhn
    masked, types, _ = await _fallback_mask(text)
    assert "CREDIT_CARD" not in types
    assert masked == text


@pytest.mark.asyncio
async def test_fallback_iban_con_checksum_invalido_no_se_enmascara():
    """#64: un `AA00…` con checksum mod-97 inválido NO es un IBAN — no se etiqueta como
    IBAN_CODE. Evita sobre-enmascarar códigos internos que empiezan como un IBAN."""
    text = "El codigo interno ES00 1111 1111 1111 1111 1111 no es una cuenta"
    masked, types, _ = await _fallback_mask(text)
    assert "IBAN_CODE" not in types


@pytest.mark.asyncio
@pytest.mark.parametrize("text,numero", [
    ("Llamame al +34 612 345 678 cuando puedas", "612 345 678"),
    ("Mi movil es 612 345 678, gracias", "612 345 678"),
    ("Oficina 912 345 678", "912 345 678"),
])
async def test_fallback_telefono_espaniol_sigue_siendo_phone_number(text, numero):
    """Golden #5: el fix no puede romper la cobertura que SÍ funcionaba — un teléfono
    español real (con o sin prefijo +34) sigue saliendo como [PHONE_NUMBER]."""
    masked, types, _ = await _fallback_mask(text)
    assert types == ["PHONE_NUMBER"]
    assert numero not in masked


@pytest.mark.asyncio
async def test_fallback_iban_y_numero_cercano_no_corrompe_el_masked():
    """Golden #6 (regresión de overlaps): un IBAN + un número cerca pasan por
    `resolve_overlaps` sin corromper el texto por offsets solapados. El expediente (ni
    teléfono ni tarjeta) queda intacto; el round-trip es exacto."""
    text = "IBAN ES91 2100 0418 4502 0005 1332 expediente 202600145"
    masked, types, pmap = await _fallback_mask(text)
    assert types == ["IBAN_CODE"]
    assert "202600145" in masked                       # el expediente, sin tocar (honesto)
    assert "ES91" not in masked
    assert policy.unmask_text(masked, pmap.ph_to_orig) == text


@pytest.mark.asyncio
async def test_fallback_mix_completo_cada_tipo_a_su_etiqueta():
    """Escenario denso (piloto Cámara): email + IBAN + tarjeta + DNI + teléfono conviven,
    cada uno a su tipo canónico (#64) y sin trocear ni contaminar offsets. (PERSON queda
    fuera a propósito: su patrón fallback es un asunto aparte del #64.)"""
    text = ("Datos: DNI 12345678Z, IBAN ES91 2100 0418 4502 0005 1332, "
            "tarjeta 4111 1111 1111 1111, tel 612345678, mail juan@acme.com")
    masked, types, pmap = await _fallback_mask(text)
    assert set(types) == {"ES_NIF", "IBAN_CODE", "CREDIT_CARD",
                          "PHONE_NUMBER", "EMAIL_ADDRESS"}
    for crudo in ("12345678Z", "ES91", "4111 1111", "612345678", "juan@acme.com"):
        assert crudo not in masked
    assert policy.unmask_text(masked, pmap.ph_to_orig) == text


@pytest.mark.asyncio
async def test_default_analyze_region_es_retrocompatible_e_internacional():
    """La firma nueva `default_analyze(text, region=...)` es retrocompatible (los
    call-sites la pasan como AnalyzeFn de un solo argumento → default eu). IBAN y tarjeta
    son INTERNACIONALES: se detectan aunque la región no tenga estructurados por-país."""
    ents = await policy.default_analyze("DNI 12345678Z")           # sin región → eu
    assert [e["entity_type"] for e in ents] == ["ES_NIF"]
    # Región sin patrones por-país: no hay ES_NIF, pero el IBAN (internacional) sigue.
    ents_mars = await policy.default_analyze(
        "DNI 12345678Z IBAN ES91 2100 0418 4502 0005 1332", region="mars")
    assert sorted(e["entity_type"] for e in ents_mars) == ["IBAN_CODE"]


@pytest.mark.asyncio
async def test_fallback_no_redos_en_entrada_patologica():
    """Regresión ReDoS (review R2). Input PATOLÓGICO de verdad: `"9-"*N` SIN `@`. `-` está
    en la clase del local del EMAIL (`[A-Za-z0-9._%+-]`), así que sin el tope de longitud el
    `+` reintenta arranque en cada posición → O(n²) (medido: 80KB → 17 s). El tope RFC (≤64)
    lo vuelve LINEAL. Con 100KB debe terminar MUY por debajo del límite; un patrón O(n²)
    tardaría decenas de segundos y reventaría esta cota estricta."""
    import time
    hostil = "9-" * 50000            # 100.000 chars, sin '@' (el peor caso del local del EMAIL)
    t0 = time.monotonic()
    await policy.default_analyze(hostil)
    elapsed = time.monotonic() - t0
    assert elapsed < 3.0, f"posible ReDoS: {elapsed:.2f}s en 100KB (esperado <1s)"


def test_email_pattern_local_acotado_mata_el_backtracking():
    """El tope del local (`{1,64}`) es lo que garantiza el tiempo lineal: sin él, el mismo
    input crece cuadrático. Se mide directamente sobre el patrón EMAIL para que la garantía
    no dependa del resto del pipeline (review R2, hallazgo 3)."""
    import time
    rx = re.compile(policy.PII_PATTERNS["EMAIL_ADDRESS"], re.IGNORECASE)
    hostil = "a-" * 50000           # 100.000 chars sin '@'
    t0 = time.monotonic()
    assert rx.findall(hostil) == []
    assert time.monotonic() - t0 < 1.0
    # y sigue reconociendo emails normales
    assert rx.findall("escribe a juan.perez@hospital.es hoy") == ["juan.perez@hospital.es"]


# ── Fugas de PII con basura pegada delante/detrás (review R2, hallazgo ALTO) ────────
#
# El round-1 sólo recortaba PREFIJOS del candidato greedy, así que un identificador real
# pegado DETRÁS de un token corto con separador quedaba como SUFIJO y salía EN CLARO. Estos
# son los reproductores exactos del reviewer + variantes: el invariante es que NINGÚN
# IBAN/tarjeta válido presente en el texto puede quedar sin enmascarar.

_LEAK_SENSITIVE = ["ES9121000418450200051332", "DE89370400440532013000",
                   "4111111111111111", "5555555555554444"]


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [
    "999 4111111111111111",                       # tarjeta tras basura corta + espacio
    "XX99 ES9121000418450200051332",              # IBAN tras token IBAN-able corto
    "Importe 250 4111111111111111 gracias",       # fuga parcial del round-1 ([CARD]11)
    "GB12AB ES9121000418450200051332",            # fuga parcial del round-1 ([IBAN]…51332)
    "ES9121000418450200051332 DE89370400440532013000",  # dos IBANs separados (ya iba bien)
    "ES9121000418450200051332 4111111111111111",  # IBAN + tarjeta
    "4111111111111111 5555555555554444",          # dos tarjetas
    "ES9121000418450200051332ABC",                # basura pegada al final (contiguo)
    "4111111111111111999",                         # tarjeta + dígitos pegados al final
    "99 4111111111111111",                         # basura mínima + tarjeta real
])
async def test_fallback_no_fuga_identificador_con_basura_pegada(text):
    """Ningún IBAN/tarjeta válido del texto sobrevive en claro, y el masking es reversible."""
    masked, _types, pmap = await _fallback_mask(text)
    for tok in _LEAK_SENSITIVE:
        if tok in text:
            assert tok not in masked, f"FUGA de {tok!r} en {masked!r}"
    assert policy.unmask_text(masked, pmap.ph_to_orig) == text


@pytest.mark.asyncio
async def test_fallback_fuga_parcial_del_round1_ahora_enmascara_entero():
    """Caso puntual del reviewer: `250 <tarjeta>` dejaba `11` en claro. Ahora la tarjeta
    entera queda enmascarada (el `250`/`Importe`/`gracias`, que no son PII, se dejan)."""
    masked, types, _ = await _fallback_mask("Importe 250 4111111111111111 gracias")
    assert types == ["CREDIT_CARD"]
    assert "4111111111111111" not in masked and "11 gracias" not in masked
    # la tarjeta entera es UN placeholder; el `250` y las palabras no-PII quedan
    assert masked.startswith("Importe 250 [CREDIT_CARD_0_") and masked.endswith("] gracias")


# ── Teléfono internacional restaurado sin reintroducir el sobre-matcheo (R2, hallazgo 2) ──

@pytest.mark.asyncio
@pytest.mark.parametrize("text,numero", [
    ("Llama al +44 20 7946 0958 por favor", "+44 20 7946 0958"),
    ("Oficina de París +33 1 42 68 53 00 hoy", "+33 1 42 68 53 00"),
    ("US line +1 202 555 0173 disponible", "+1 202 555 0173"),
    ("Alemania +49 30 123456 extensión", "+49 30 123456"),
])
async def test_fallback_telefono_internacional_se_enmascara(text, numero):
    """El intl (prefijo `+`/`00`) que el genérico borrado del #64 cubría vuelve a salir como
    PHONE_NUMBER — sin él, números NO españoles viajaban en claro (regresión R2)."""
    masked, types, _ = await _fallback_mask(text)
    assert types == ["PHONE_NUMBER"]
    assert numero not in masked


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [
    "IBAN ES9121000418450200051332 para la transferencia",   # empieza por letras, no por +
    "La factura 202600145 sigue pendiente",                   # sin prefijo +/00
    "referencia 4567 890 123 del expediente",                 # dígitos sin prefijo intl
])
async def test_fallback_intl_no_reintroduce_sobre_matcheo(text):
    """El intl EXIGE prefijo `+`/`00`: IBANs (letras), facturas y referencias sin prefijo NO
    se marcan como teléfono — no se re-rompe el bug del #64."""
    _masked, types, _ = await _fallback_mask(text)
    assert "PHONE_NUMBER" not in types
