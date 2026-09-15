"""Unit tests de sentinel_guardian_policy (spec 014 T006, FR-022).

Librería PURA: la detección se inyecta como callable — acá un detector fake por
patrones fijos, sin Presidio ni DB. Cubre: mask reversible con nonce, colisión de
placeholder con literal del usuario, carry-split (placeholder partido vs '[' suelto
de código), round-trip text/thinking/tool_use y stream truncado.
"""
import json
import re

import pytest

from extensions import sentinel_guardian_policy as policy

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

    async def post(self, url, json=None, timeout=None):
        if self._raise_exc:
            raise self._raise_exc
        return self._response


# Reset del singleton de `presidio_analyze` entre tests: fixture GLOBAL autouse en
# `conftest.py` (`_reset_presidio_http_client_singleton`) — necesita resetear DOS
# entradas de sys.modules (import bare vs `extensions.`-prefixed), no sólo la que ve
# este archivo, así que vive ahí y no acá.


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
    deny = next(r for r in recognizers if r["name"] == "SENTINEL_CUSTOM_NAMES")
    assert deny["deny_list"] == ["Pedro", "Cristian"]
    assert deny["supported_entity"] == "PERSON"


def test_build_ad_hoc_recognizers_latam_region_adds_dni_cuil():
    recognizers = policy.build_ad_hoc_recognizers([], region="latam_ar")
    entities = {r["supported_entity"] for r in recognizers}
    assert entities == {"DNI", "CUIL", "PASSPORT"}


def test_build_ad_hoc_recognizers_unknown_region_is_empty():
    assert policy.build_ad_hoc_recognizers([], region="mars") == []


# ── resolve_region (extensión de spec 016, mismo patrón que resolve_nlp_fail_mode) ──

def test_resolve_region_ausente_usa_el_default_del_caller():
    assert policy.resolve_region(None) == policy.DEFAULT_REGION
    assert policy.resolve_region({}) == policy.DEFAULT_REGION
    assert policy.resolve_region({}, default="latam_ar") == "latam_ar"


def test_resolve_region_tenant_propio_pisa_el_default():
    assert policy.resolve_region({"region": "latam_ar"}, default="eu") == "latam_ar"


def test_resolve_region_valor_no_reconocido_no_pisa_el_default():
    # Un typo/región inexistente NUNCA activa/desactiva reconocedores de otro país por
    # accidente — cae al default del caller, igual que resolve_nlp_fail_mode con `block`.
    assert policy.resolve_region({"region": "mars"}, default="eu") == "eu"
    assert policy.resolve_region({"region": ""}, default="latam_ar") == "latam_ar"


def test_resolve_region_es_case_insensitive_y_recorta_espacios():
    assert policy.resolve_region({"region": " LATAM_AR "}, default="eu") == "latam_ar"


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


@pytest.mark.asyncio
async def test_presidio_analyze_reusa_el_mismo_cliente_entre_llamadas(monkeypatch):
    """#167: crear un `AsyncClient` nuevo por request agotaba sockets en TIME_WAIT (46
    medidos en el issue). Dos llamadas seguidas tienen que construir el `AsyncClient`
    UNA sola vez y reusar la misma instancia — no una por request."""
    construcciones = []

    def _construir(**kw):
        cliente = _FakeAsyncClient(response=_FakeResponse(200, []))
        construcciones.append(cliente)
        return cliente

    monkeypatch.setattr("httpx.AsyncClient", _construir)

    await policy.presidio_analyze("Juan Pérez fue", "http://presidio:3000", [])
    await policy.presidio_analyze("otra vez Juan Pérez", "http://presidio:3000", [])

    assert len(construcciones) == 1, (
        f"AsyncClient se construyó {len(construcciones)} veces — se esperaba 1 (reuso)")


@pytest.mark.asyncio
async def test_presidio_analyze_pasa_el_timeout_por_llamada(monkeypatch):
    """El timeout ya no es config del cliente (que ahora se reusa) — tiene que viajar
    por-llamada en el `.post()`, así dos requests con timeouts distintos no chocan."""
    vistos = []

    class _ClienteQueRegistraTimeout(_FakeAsyncClient):
        async def post(self, url, json=None, timeout=None):
            vistos.append(timeout)
            return await super().post(url, json=json, timeout=timeout)

    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda **kw: _ClienteQueRegistraTimeout(response=_FakeResponse(200, [])),
    )

    await policy.presidio_analyze("hola", "http://presidio:3000", [], timeout=7.5)

    assert vistos == [7.5]


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
async def test_fallback_numero_largo_sin_luhn_se_enmascara_fail_safe():
    """CAMBIO DE COMPORTAMIENTO (opción A, decisión JF): el fallback ya NO usa Luhn. Una
    corrida de ≥13 dígitos (un nº de pedido) se enmascara como CREDIT_CARD aunque NO sea una
    tarjeta — over-mask deliberado, «ruidoso pero seguro». Antes (R1-R3, con checksum) quedaba
    intacta; el checksum + búsqueda de fronteras era justo el origen de las 3 fugas."""
    text = "El pedido 1234567890123 sigue en curso"       # 13 dígitos, no Luhn
    masked, types, _ = await _fallback_mask(text)
    assert types == ["CREDIT_CARD"]
    assert "1234567890123" not in masked


@pytest.mark.asyncio
async def test_fallback_iban_shape_sin_checksum_se_enmascara_fail_safe():
    """CAMBIO DE COMPORTAMIENTO (opción A): sin mod-97, cualquier corrida con forma de IBAN
    (país + 2 dígitos de control + ≥15 alnum) se enmascara como IBAN_CODE aunque el checksum
    no cuadre. Antes quedaba intacta. Over-mask deliberado para no fugar (JF)."""
    text = "El codigo interno ES00 1111 1111 1111 1111 1111 no es una cuenta"
    masked, types, _ = await _fallback_mask(text)
    assert types == ["IBAN_CODE"]
    assert "ES00" not in masked


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


async def _best_time(coro_factory, reps=3):
    """Mejor de `reps` corridas (resta ruido de scheduling/GC) del tiempo de un callable."""
    import time
    best = float("inf")
    for _ in range(reps):
        t0 = time.perf_counter()
        await coro_factory()
        best = min(best, time.perf_counter() - t0)
    return best


@pytest.mark.asyncio
async def test_fallback_escala_lineal_no_redos():
    """Regresión ReDoS como PROPIEDAD DE ESCALADO, no como wall-clock absoluto. Un umbral de
    segundos (`< 3s`) era el fallo de CI: pasaba en local y fallaba en el runner de 2 cores
    (medía el hardware, no el algoritmo). Aquí se mide t(N), t(2N), t(4N) sobre el peor caso
    (`9-`*N: EMAIL sin `@` + corridas densas para tarjeta) y se exige que el tiempo NO
    EXPLOTE: t(kN)/t(N) ≈ k (lineal). Un patrón O(n²) daría ~4x al duplicar y ~16x al
    cuadruplicar, reventando estos umbrales — en CUALQUIER máquina, rápida o lenta."""
    base = 20000
    t1 = await _best_time(lambda: policy.default_analyze("9-" * base))
    t2 = await _best_time(lambda: policy.default_analyze("9-" * (2 * base)))
    t4 = await _best_time(lambda: policy.default_analyze("9-" * (4 * base)))
    # Lineal: al 2x y 4x el tiempo crece ~2x y ~4x. Umbrales holgados (≤3x/≤6x) para no ser
    # flaky; un O(n²) daría ~4x/~16x y NO pasaría. El criterio es el ESCALADO, no los segundos.
    assert t2 / t1 < 3.0, f"escalado no lineal al 2x: t1={t1:.4f}s t2={t2:.4f}s (ratio {t2/t1:.2f})"
    assert t4 / t1 < 6.0, f"escalado no lineal al 4x: t1={t1:.4f}s t4={t4:.4f}s (ratio {t4/t1:.2f})"
    # Techo de sanidad MUY holgado y secundario (independiente del hardware razonable).
    assert t4 < 30.0, f"tiempo absurdo aun siendo lineal: t4={t4:.2f}s"


@pytest.mark.asyncio
async def test_email_pattern_local_acotado_escala_lineal():
    """El tope RFC del local (`{1,64}`) es lo que garantiza tiempo lineal del EMAIL: sin él,
    `"a-"*N` sin `@` es O(n²) (review R2). Se mide sobre el patrón aislado y se exige escalado
    lineal (ratio ~2 al duplicar), no un wall-clock absoluto."""
    import time
    rx = re.compile(policy.PII_PATTERNS["EMAIL_ADDRESS"], re.IGNORECASE)

    def t(n):
        best = float("inf")
        for _ in range(3):
            t0 = time.perf_counter()
            assert rx.findall("a-" * n) == []          # sin '@' → 0 matches
            best = min(best, time.perf_counter() - t0)
        return best

    assert t(2 * 40000) / t(40000) < 3.0                # O(n²) daría ~4x
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
    """Caso puntual del reviewer: `250 <tarjeta>` dejaba `11` en claro. Ahora la CORRIDA
    entera (`250 4111…`, un solo run de dígitos) se enmascara — cero PAN en claro. Nota
    (opción A): `250` cae DENTRO del placeholder (over-mask del importe pegado), no queda
    fuera como en R2/R3; es el precio aceptado del fail-safe («ruidoso pero seguro»)."""
    masked, types, _ = await _fallback_mask("Importe 250 4111111111111111 gracias")
    assert types == ["CREDIT_CARD"]
    assert "4111111111111111" not in masked and "11 gracias" not in masked
    # `250 4111…` es UN run → UN placeholder; sólo las PALABRAS (no dígitos) quedan fuera.
    assert masked.startswith("Importe [CREDIT_CARD_0_") and masked.endswith("] gracias")


# ── Fuga PARCIAL en tarjeta AGRUPADA precedida de un importe (review R3, hallazgo ALTO) ──
#
# El round-2 permitía que un match terminara en una frontera de token INTERNA (los espacios
# entre los grupos de 4 de una tarjeta escrita en formato humano). Cuando `importe + primeros
# grupos` daba Luhn válido pero `importe + tarjeta completa` no, enmascaraba `importe+prefijo`
# y dejaba los últimos grupos (dígitos del PAN) colgando en claro. Ningún test anterior lo
# cazaba porque TODOS usaban tarjetas sin espacios (`4111111111111111`). Estos usan el formato
# agrupado real. FALLAN sobre el código round-2 (dejan 4-12 dígitos del PAN en claro).

# Tarjetas de test reales (Luhn válidas) en grupos de 4 (formato humano).
_GROUPED_CARDS = ["4111 1111 1111 1111", "4398 2597 9190 7482", "5555 5555 5555 4444",
                  "4526 0181 5908 3012", "4000 0012 3456 7899"]


def _clear_text(masked: str, pmap) -> str:
    """El texto que sobrevive EN CLARO: `masked` con los placeholders quitados. Hace falta
    porque el nonce del placeholder (`[CREDIT_CARD_0_<hex>]`) puede contener por azar 4
    dígitos que coincidan con un grupo del PAN — eso NO es fuga (el PAN sí está enmascarado)."""
    clear = masked
    for ph in pmap.ph_to_orig:
        clear = clear.replace(ph, " ")
    return clear


def _pan_groups_in_clear(masked: str, card: str, pmap) -> list:
    """Grupos de 4 dígitos del PAN que sobreviven en el texto EN CLARO. Con importes de
    ≤3 dígitos NO hay coincidencia posible de un grupo de 4 → cualquier hit es fuga real."""
    clear = _clear_text(masked, pmap)
    pan = card.replace(" ", "").replace("-", "")
    return [pan[k:k + 4] for k in range(0, len(pan), 4) if pan[k:k + 4] in clear]


@pytest.mark.asyncio
@pytest.mark.parametrize("card", _GROUPED_CARDS)
@pytest.mark.parametrize("amount", ["0", "7", "16", "42", "250", "999", "016", "007"])
@pytest.mark.parametrize("layout", ["{a} {c}", "{a}-{c}", "{c} {a}", "importe {a}, tarjeta {c}."])
async def test_fallback_tarjeta_agrupada_con_importe_cero_pan_en_claro(card, amount, layout):
    """Ni un dígito del PAN de una tarjeta AGRUPADA queda en claro por llevar un importe
    pegado delante/detrás (review R3). Importes ≤3 díg ⇒ un grupo de 4 del PAN en claro es
    fuga inequívoca."""
    text = layout.format(a=amount, c=card)
    masked, _types, pmap = await _fallback_mask(text)
    assert _pan_groups_in_clear(masked, card, pmap) == [], f"fuga parcial del PAN: {masked!r}"
    assert card not in _clear_text(masked, pmap)
    assert policy.unmask_text(masked, pmap.ph_to_orig) == text


@pytest.mark.asyncio
@pytest.mark.parametrize("text,card", [
    ("016 4398 2597 9190 7482", "4398 2597 9190 7482"),               # evidencia R3 (4 díg. fugaban)
    ("100000007 4111 1111 1111 1111", "4111 1111 1111 1111"),         # evidencia R3 (12 díg.)
    ("94875749118625 4526 0181 5908 3012", "4526 0181 5908 3012"),    # evidencia R3 (12 díg.)
])
async def test_fallback_evidencia_r3_cero_pan_en_claro(text, card):
    """Las 3 cadenas de evidencia del reviewer: el PAN queda ÍNTEGRAMENTE enmascarado (cero
    dígitos en claro), y el masking es reversible."""
    masked, _types, pmap = await _fallback_mask(text)
    pan = card.replace(" ", "")
    # ningún tramo de ≥4 dígitos consecutivos del PAN sobrevive en una corrida EN CLARO
    # (placeholders quitados: su nonce hex podría coincidir por azar con dígitos del PAN)
    clear_runs = re.findall(r"\d+", _clear_text(masked, pmap))
    for run in clear_runs:
        for L in range(4, len(pan) + 1):
            for s in range(len(pan) - L + 1):
                assert pan[s:s + L] not in run, f"{L} díg. del PAN en claro: {masked!r}"
    assert policy.unmask_text(masked, pmap.ph_to_orig) == text


@pytest.mark.asyncio
async def test_fallback_iban_agrupado_con_basura_delante_cero_fuga():
    """Análogo del R3 para IBAN agrupado (grupos de 4). Un token corto delante no deja el
    IBAN colgando en una frontera de grupo interna."""
    for junk in ["XX", "12", "ES", "REF"]:
        text = f"{junk} ES91 2100 0418 4502 0005 1332"
        masked, _types, pmap = await _fallback_mask(text)
        clear = _clear_text(masked, pmap)
        # ni el IBAN completo ni ningún grupo final del cuerpo en claro
        assert "ES9121000418450200051332" not in clear.replace(" ", "")
        assert "0005 1332" not in clear and "4502 0005 1332" not in clear
        assert policy.unmask_text(masked, pmap.ph_to_orig) == text


@pytest.mark.asyncio
async def test_fallback_fuzz_tarjeta_agrupada_importe_cero_fugas():
    """Fuzz acotado (regresión R3): tarjetas Luhn-válidas en 3 formatos × importes ≤3 díg ×
    posiciones/separadores. Ni un dígito del PAN en claro (importe corto ⇒ sin coincidencia).
    Cubre el espacio que el reviewer midió con fuga en ~9% de importes sobre el código viejo."""
    import random
    rnd = random.Random(64)

    def make_card():
        while True:
            base = "4" + "".join(rnd.choice("0123456789") for _ in range(14))
            for last in "0123456789":
                if _luhn(base + last):
                    return base + last

    def _luhn(num):
        d = [int(c) for c in num]
        tot = 0
        for i, x in enumerate(reversed(d)):
            if i % 2 == 1:
                x *= 2
                if x > 9:
                    x -= 9
            tot += x
        return tot % 10 == 0

    checked = leaks = 0
    for _ in range(400):
        pan = make_card()
        forms = [pan, " ".join(pan[k:k + 4] for k in range(0, 16, 4)),
                 "-".join(pan[k:k + 4] for k in range(0, 16, 4))]
        for f in forms:
            for amount in (str(rnd.randint(0, 999)), str(rnd.randint(0, 9))):
                for sep in (" ", "-"):
                    for text in (f"{amount}{sep}{f}", f"{f}{sep}{amount}"):
                        masked, _t, pmap = await _fallback_mask(text)
                        checked += 1
                        # importe ≤3 díg: un grupo de 4 del PAN en claro es fuga inequívoca
                        # (placeholders quitados: el nonce hex podría coincidir por azar)
                        clear = _clear_text(masked, pmap)
                        if any(pan[k:k + 4] in clear for k in range(0, 16, 4)):
                            leaks += 1
    assert leaks == 0, f"{leaks}/{checked} inputs con dígitos del PAN en claro"


# ── Fail-safe over-mask sin checksum (opción A, decisión JF) — 3ª variante de fuga (R3) ──
#
# El re-review encontró que checksum+fronteras NO puede ser leak-free: un dígito pegado al
# PRIMER grupo (la tarjeta ya no arranca en un inicio de token) fugaba el PAN entero. JF
# eligió la opción A: enmascarar la CORRIDA entera que PODRÍA ser tarjeta/IBAN, sin checksum.
# Ruidoso pero imposible de fugar por construcción.


@pytest.mark.asyncio
@pytest.mark.parametrize("text,pan", [
    ("44787 7893 2879 2170", "44787789328792170"),                 # cadena nueva del coordinador
    ("Pague 5004917 4845 8989 7107 ayer", "5004917484589897107"),  # idem
    ("94011 5244 9390 9269", "94011524493909269"),                 # idem
    ("94398 2597 9190 7482", "94398259791907482"),                 # dígito pegado al 1er grupo (3ª variante)
    ("2 4398 2597 9190 7482", "24398259791907482"),                # idem, 1 díg + espacio
    ("2504398259791907482", "2504398259791907482"),                # importe pegado sin separador ({a}{c})
    ("43 9825 979190 7482", "4398259791907482"),                   # grupos irregulares
])
async def test_fallback_corrida_larga_se_enmascara_entera_cero_fuga(text, pan):
    """Cualquier corrida de dígitos ≥13 se tapa ENTERA: ni un dígito consecutivo del PAN
    sobrevive en claro, sea cual sea el troceo o la basura pegada (3ª variante R3)."""
    masked, types, pmap = await _fallback_mask(text)
    assert types == ["CREDIT_CARD"]
    clear = _clear_text(masked, pmap)
    # ningún tramo de ≥4 dígitos consecutivos del PAN en una corrida en claro
    for run in re.findall(r"\d+", clear):
        for L in range(4, len(pan) + 1):
            for s in range(len(pan) - L + 1):
                assert pan[s:s + L] not in run, f"fuga de {pan[s:s+L]!r} en {masked!r}"
    assert policy.unmask_text(masked, pmap.ph_to_orig) == text


@pytest.mark.asyncio
async def test_fallback_dos_tarjetas_pegadas_se_enmascaran_juntas():
    """Dos tarjetas agrupadas en una misma corrida (`4111… 5555…`) → un solo run ≥13 díg →
    todo enmascarado. Antes (checksum) el boundary-finding podía dejar una en claro."""
    text = "4111 1111 1111 1111 5555 5555 5555 4444"
    masked, types, pmap = await _fallback_mask(text)
    assert types == ["CREDIT_CARD"]
    assert "4444" not in _clear_text(masked, pmap) and "4111" not in _clear_text(masked, pmap)
    assert policy.unmask_text(masked, pmap.ph_to_orig) == text


@pytest.mark.asyncio
@pytest.mark.parametrize("grouped", [
    "ES91 2100 0418 4502 0005 1332",          # estándar grupos de 4
    "ES9121000418450200051332",               # contiguo
    "ES 91 2100 0418 4502 0005 1332",         # espacio tras el país (parte al control)
    "MT 84 MA LT 01 10 00 01 23 45 MT LC AS T0 01 S",   # grupos de 2 (parten control)
])
async def test_fallback_iban_grouping_no_estandar_se_enmascara(grouped):
    """El ancla admite un espacio antes de cada dígito de control, así que agrupaciones no
    estándar (`ES 91…`, `MT 84…`) que parten el par de control NO fugan el IBAN (opción A).
    LÍMITE DOCUMENTADO: un IBAN con espacio entre CADA carácter (incluido el país, `M T 8 4…`)
    no se detecta — formato no humano; catcharlo obligaría a sobre-enmascarar prosa en
    mayúsculas. Ese caso lo cubre sólo el NLP real."""
    masked, types, pmap = await _fallback_mask(grouped)
    assert types == ["IBAN_CODE"]
    assert grouped.replace(" ", "") not in _clear_text(masked, pmap).replace(" ", "")
    assert policy.unmask_text(masked, pmap.ph_to_orig) == grouped


@pytest.mark.asyncio
async def test_fallback_over_mask_numero_legitimo_es_aceptado():
    """Precio ACEPTADO del fail-safe (JF «ruidoso pero seguro»): un número largo legítimo
    de ≥13 dígitos cae como CREDIT_CARD en degrade/dev. Se documenta como comportamiento
    esperado, NO como bug. (Los cortos <13 —factura, expediente, DNI— siguen intactos.)"""
    masked, types, _ = await _fallback_mask("El pedido 1234567890123456 se envió")   # 16 díg
    assert types == ["CREDIT_CARD"]
    # contraparte: lo corto NO se toca
    m2, t2, _ = await _fallback_mask("expediente 202600145 y factura FAC-2026-001587")
    assert t2 == [] and m2 == "expediente 202600145 y factura FAC-2026-001587"


@pytest.mark.asyncio
async def test_fallback_fuzz_failsafe_todos_los_layouts_cero_fuga():
    """Fuzz grande (opción A): tarjeta en 3 formatos × importes (incl. LARGOS) × TODOS los
    layouts, INCLUYENDO pegado sin separador (`{a}{c}`) — el que abrió la 3ª fuga. Ni un
    tramo ≥6 del PAN en claro. Con el fail-safe la corrida entera se tapa, así que 0 fugas."""
    import random
    rnd = random.Random(64)

    def _luhn(num):
        d = [int(c) for c in num]
        tot = 0
        for i, x in enumerate(reversed(d)):
            if i % 2 == 1:
                x *= 2
                if x > 9:
                    x -= 9
            tot += x
        return tot % 10 == 0

    def make_card():
        while True:
            base = "4" + "".join(rnd.choice("0123456789") for _ in range(14))
            for last in "0123456789":
                if _luhn(base + last):
                    return base + last

    checked = leaks = 0
    for _ in range(1500):
        pan = make_card()
        forms = [pan, " ".join(pan[k:k + 4] for k in range(0, 16, 4)),
                 "-".join(pan[k:k + 4] for k in range(0, 16, 4))]
        amounts = [str(rnd.randint(0, 999)), str(rnd.randint(0, 9)),
                   "".join(rnd.choice("0123456789") for _ in range(rnd.randint(1, 6)))]
        for f in forms:
            for a in amounts:
                for layout in (f"{a} {f}", f"{a}-{f}", f"{f} {a}", f"{a}{f}", f"{f}{a}"):
                    masked, _t, pmap = await _fallback_mask(layout)
                    checked += 1
                    clear = _clear_text(masked, pmap)
                    # cualquier tramo de ≥6 dígitos del PAN en una corrida en claro = fuga
                    for run in re.findall(r"\d+", clear):
                        if any(pan[s:s + 6] in run for s in range(len(pan) - 5)):
                            leaks += 1
                            break
    assert leaks == 0, f"{leaks}/{checked} inputs con ≥6 dígitos del PAN en claro"


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


# ── 4ª clase de fuga: separador interno EXÓTICO fracturaba la corrida (gate adversarial) ──
#
# Antes el separador interno de la corrida sólo toleraba espacio/guión, así que CUALQUIER otro
# separador de UN carácter (punto, barra, coma, tab, NBSP, narrow-NBSP, ZWSP, underscore, pipe,
# newline, mixtos) partía el PAN/IBAN en trozos <umbral y lo fugaba ENTERO en claro. El fix
# generalizó el separador a `[^0-9A-Za-z]?` (cualquier no-alfanumérico de 1 char): con eso
# NINGÚN separador de 1 char puede fracturar la corrida — cierre del family POR CONSTRUCCIÓN.
# Este test PARAMETRIZADO fija ese family: cada variante DEBE enmascarar la corrida entera,
# cero dígitos del secreto en claro. Residual EXPLÍCITAMENTE aceptado (JF, «ruidoso pero
# seguro»): separadores de 2+ chars/code-points (doble espacio, ` - `, emoji multi-codepoint)
# todavía fracturan — NO se cubren acá porque son el precio documentado del paracaídas de
# degrade/dev; el NLP real es el detector de producción.

_CARD_16 = "4111111111111111"          # PAN de test (Luhn válido), 16 dígitos


def _grouped(digits: str, sep: str) -> str:
    """`digits` en grupos de 4 unidos por `sep` (formato humano con separador arbitrario)."""
    return sep.join(digits[i:i + 4] for i in range(0, len(digits), 4))


def _no_secret_digits_in_clear(masked: str, secret_digits: str, pmap) -> None:
    """Afirma que NI UN tramo de dígitos del secreto sobrevive en el texto en claro
    (placeholders quitados: su nonce hex podría coincidir por azar con dígitos del PAN).
    Escanea todas las corridas de dígitos que quedan sueltas: ningún substring del secreto
    de longitud ≥4 puede aparecer, y el PAN compacto tampoco."""
    clear = _clear_text(masked, pmap)
    runs = re.findall(r"\d+", clear)
    for L in range(4, len(secret_digits) + 1):
        for s in range(len(secret_digits) - L + 1):
            frag = secret_digits[s:s + L]
            assert all(frag not in run for run in runs), \
                f"fuga de {frag!r} ({L} díg.) en claro: {masked!r}"
    assert secret_digits not in re.sub(r"\s", "", clear), f"PAN compacto en claro: {masked!r}"


@pytest.mark.asyncio
@pytest.mark.parametrize("text,secret", [
    pytest.param(f"Pago {_grouped(_CARD_16, ' ')} gracias", _CARD_16, id="espacio"),
    pytest.param(f"Pago {_grouped(_CARD_16, '-')} gracias", _CARD_16, id="guion"),
    pytest.param(f"Pago {_grouped(_CARD_16, '.')} gracias", _CARD_16, id="punto"),
    pytest.param(f"Pago {_grouped(_CARD_16, '/')} gracias", _CARD_16, id="barra"),
    pytest.param(f"Pago {_grouped(_CARD_16, ',')} gracias", _CARD_16, id="coma"),
    pytest.param(f"Pago {_grouped(_CARD_16, chr(9))} gracias", _CARD_16, id="tab"),
    pytest.param(f"Pago {_grouped(_CARD_16, chr(0x00A0))} gracias", _CARD_16, id="NBSP"),
    pytest.param(f"Pago {_grouped(_CARD_16, chr(0x202F))} gracias", _CARD_16, id="narrow-NBSP"),
    pytest.param(f"Pago {_grouped(_CARD_16, chr(0x200B))} gracias", _CARD_16, id="ZWSP"),
    pytest.param(f"Pago {_grouped(_CARD_16, '_')} gracias", _CARD_16, id="underscore"),
    pytest.param(f"Pago {_grouped(_CARD_16, '|')} gracias", _CARD_16, id="pipe"),
    pytest.param(f"Pago {_grouped(_CARD_16, chr(10))} gracias", _CARD_16, id="newline"),
    pytest.param("Pago 4111.1111 1111.1111 gracias", _CARD_16, id="mixto-punto+espacio"),
    pytest.param("Pago 4111111111111111 gracias", _CARD_16, id="contiguo"),
    pytest.param("4111 1111 1111 1111 5555 5555 5555 4444",
                 "41111111111111115555555555554444", id="dos-tarjetas-pegadas"),
    pytest.param("44787 7893 2879 2170", "44787789328792170", id="R3-fused"),
])
async def test_fallback_card_separador_family_enmascara_entero(text, secret):
    """Family de separadores de la 4ª fuga: cada corrida se enmascara ENTERA como CREDIT_CARD,
    con cero dígitos del secreto en claro y masking reversible."""
    masked, types, pmap = await _fallback_mask(text)
    assert types == ["CREDIT_CARD"], f"tipo inesperado: {types} en {masked!r}"
    _no_secret_digits_in_clear(masked, secret, pmap)
    assert policy.unmask_text(masked, pmap.ph_to_orig) == text


_IBAN_ES = "ES91 2100 0418 4502 0005 1332"
_IBAN_ES_BODY = "ES9121000418450200051332"


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [
    pytest.param("ES91.2100.0418.4502.0005.1332", id="punto"),
    pytest.param("ES91 2100 0418 4502 0005 1332", id="NBSP"),
    pytest.param("ES91/2100/0418/4502/0005/1332", id="barra"),
])
async def test_fallback_iban_separador_family_enmascara(text):
    """El IBAN con separador exótico de 1 char (punto/NBSP/barra) se enmascara ENTERO como
    IBAN_CODE: ni el prefijo `ES91` ni el cuerpo quedan en claro, y el masking es reversible."""
    masked, types, pmap = await _fallback_mask(text)
    assert types == ["IBAN_CODE"], f"tipo inesperado: {types} en {masked!r}"
    assert "ES91" not in masked
    assert _IBAN_ES_BODY not in re.sub(r"[^0-9A-Za-z]", "", _clear_text(masked, pmap))
    assert policy.unmask_text(masked, pmap.ph_to_orig) == text


@pytest.mark.asyncio
async def test_fallback_iban_con_etiqueta_no_se_traga_la_palabra():
    """`IBAN ES91 …` debe quedar `IBAN [IBAN_CODE_…]`: el ancla arranca en `ES91` (2 letras de
    país + control), NO en la palabra `IBAN` de delante — no se traga la etiqueta ni deja el
    identificador en claro."""
    text = f"IBAN {_IBAN_ES}"
    masked, types, pmap = await _fallback_mask(text)
    assert types == ["IBAN_CODE"]
    assert masked.startswith("IBAN [IBAN_CODE_0_") and masked.endswith("]")
    assert "ES91" not in masked and "1332" not in masked
    assert policy.unmask_text(masked, pmap.ph_to_orig) == text


@pytest.mark.asyncio
@pytest.mark.parametrize("text,expected_types", [
    pytest.param("pedido 12345", [], id="pedido-corto"),
    pytest.param("FAC-2026-001587", [], id="factura"),
    pytest.param("expediente 202600145", [], id="expediente"),
    pytest.param("DNI 12345678Z", ["ES_NIF"], id="dni-es_nif"),
])
async def test_fallback_goldens_no_se_sobre_enmascaran(text, expected_types):
    """Goldens que DEBEN sobrevivir: facturas/expedientes/pedidos cortos quedan INTACTOS
    (nada que ver con tarjeta/IBAN) y el DNI español sale como ES_NIF por formato — el fix del
    family de separadores no debe empezar a sobre-enmascarar identificadores legítimos."""
    masked, types, pmap = await _fallback_mask(text)
    assert types == expected_types, f"tipos inesperados {types} en {masked!r}"
    if not expected_types:
        assert masked == text
    else:
        assert policy.unmask_text(masked, pmap.ph_to_orig) == text


# ── FR-015/FR-016: el paracaídas tiene que espejar las regiones ────────────────────────
#
# Por qué existe este test: la resolución del paracaídas es
# `FALLBACK_STRUCTURED_BY_REGION.get(region, {})`. Si una región existe en la tabla
# principal y falta en la del paracaídas, NO hereda `eu` — devuelve `{}` y el modo
# degradado se queda sin ninguna detección estructurada, justo cuando ya falló algo.
# Pasó de verdad: `latam_ar` estuvo sólo en la tabla principal hasta el 15-sep-2026.

def test_paracaidas_espeja_regiones():
    """Agregar una región arriba y olvidarla en el paracaídas tiene que romper acá."""
    principales = set(policy.STRUCTURED_ID_PATTERNS_BY_REGION)
    paracaidas = set(policy.FALLBACK_STRUCTURED_BY_REGION)
    faltan = principales - paracaidas
    assert not faltan, (
        f"Regiones en STRUCTURED_ID_PATTERNS_BY_REGION sin entrada en "
        f"FALLBACK_STRUCTURED_BY_REGION: {sorted(faltan)}. En modo degradado esas regiones "
        f"pierden TODA la detección estructurada (`.get(region, {{}})` devuelve vacío, no "
        f"hereda 'eu')."
    )


def test_paracaidas_ninguna_region_queda_vacia():
    """Una región presente pero con dict vacío es el mismo agujero, disfrazado."""
    vacias = [r for r, pats in policy.FALLBACK_STRUCTURED_BY_REGION.items() if not pats]
    assert not vacias, f"Regiones del paracaídas sin ningún patrón: {vacias}"


def test_paracaidas_latam_ar_cubre_los_documentos_argentinos():
    """Regresión del hallazgo del 15-sep: DNI, CUIL y CBU en el camino degradado."""
    pats = policy.FALLBACK_STRUCTURED_BY_REGION["latam_ar"]
    for entidad in ("DNI", "CUIL", "CBU"):
        assert entidad in pats, f"falta {entidad} en el paracaídas de latam_ar"
    assert re.search(pats["DNI"], "el DNI es 28.455.910")
    assert re.search(pats["CUIL"], "CUIL 20-28455910-3")
    assert re.search(pats["CBU"], "CBU 0170099220000012345678")


def test_paracaidas_reusa_los_patrones_de_la_tabla_principal():
    """Los patrones se toman con [0] de la principal: no pueden divergir en silencio."""
    for region, pats in policy.FALLBACK_STRUCTURED_BY_REGION.items():
        principal = policy.STRUCTURED_ID_PATTERNS_BY_REGION.get(region, {})
        for entidad, patron in pats.items():
            if entidad in principal:
                assert patron == principal[entidad][0], (
                    f"{region}/{entidad}: el patrón del paracaídas se separó del de la "
                    f"tabla principal"
                )
