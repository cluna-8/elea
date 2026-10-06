"""S14 — alcance completo del enmascarado forzado (057 T096; QA B3; research R29; contracts/costuras-base.md §S14).

La señal `sentinel_forced_masking` (solo la escribe la pasarela, con marca de procedencia por tipo, igual que
la decisión de ruteo) lleva al guardrail del motor a enmascarar TODO lo que sale hacia el destino:
`system`, todos los turnos, `tool_use`, `tool_result`, `thinking`, descripciones de herramientas y, como
regla general fail-closed, todo valor de texto del cuerpo salvo las posiciones estructurales del protocolo.
Lo que no se puede analizar (imagen, PDF sin texto, tipos desconocidos…) queda contado en el informe con su
nombre de tipo, para que el guard de la extensión bloquee.

Sin la señal, nada cambia: `scope = "user"` y solo los turnos `user` (los 26 casos de
`tests/contract/test_gw_no_regresion_057.py` y los tests de `masking_report` lo siguen fijando).

Las colisiones de nombres, claves y números las fija `test_masking_posiciones_exentas.py` (T106); el PDF
hostil, `test_masking_pdf_hostil.py` (T105).
"""
import copy
import json

import pytest

import s14_helpers as h
from s14_helpers import CBU, CUIT, DNI, DNI_PUNTOS, policy  # noqa: E402
from extensions import sentinel_guardrail  # noqa: E402

PROSA = "Hola, que tal"


class _Identidad:
    def __init__(self, **sentinel):
        self.metadata = {"sentinel": {"region": "latam_ar", **sentinel}}


@pytest.fixture(autouse=True)
def _sin_resolutores():
    policy.clear_forced_masking_resolvers()
    yield
    policy.clear_forced_masking_resolvers()


@pytest.fixture(autouse=True)
def _sin_efectos_laterales(monkeypatch):
    async def _nada(*_a, **_k):
        return None

    monkeypatch.setattr(sentinel_guardrail, "_auditar_bloqueo", _nada)
    monkeypatch.setattr(sentinel_guardrail, "_marcar_nlp_degradado", _nada)
    monkeypatch.setattr(sentinel_guardrail, "_PRESIDIO_URL", None)


async def _enmascarar(body, *, fmt="anthropic", region="latam_ar"):
    tally = policy.MaskingTally()
    cuerpo, mapa = await policy.mask_body(
        body, h.analizador(region), policy.PlaceholderMap(), scope="full", fmt=fmt, tally=tally)
    return cuerpo, mapa, tally


def _texto(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _cliente(data: dict) -> dict:
    """Lo que sale hacia el destino: sin la metadata interna (ahí vive el mapa reversible, que es del motor)."""
    return {k: v for k, v in data.items() if k not in ("litellm_metadata", "metadata")}


def _sin_pii(obj, *valores):
    plano = _texto(obj)
    for valor in valores or (DNI, DNI_PUNTOS, CUIT, CBU):
        assert valor not in plano, f"{valor!r} salió en claro"


# ── 1. Sin la señal: igual que hoy ───────────────────────────────────────────────────

def _pedido_anthropic():
    return {
        "model": "claude-sonnet-4-5",
        "max_tokens": 1024,
        "system": f"Atendés a un cliente con DNI {DNI}.",
        "messages": [
            {"role": "user", "content": f"Mi DNI es {DNI_PUNTOS}"},
            {"role": "assistant", "content": [{"type": "text", "text": f"Anoto el DNI {DNI}"}]},
        ],
        "tools": [{"name": "buscar", "description": f"Busca por DNI {DNI}",
                   "input_schema": {"type": "object", "properties": {}}}],
    }


@pytest.mark.asyncio
async def test_sin_senal_solo_el_turno_user_y_scope_user():
    original = _pedido_anthropic()
    data = copy.deepcopy(original)
    salida = await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(
        _Identidad(), None, data, "anthropic_messages")
    informe = data["litellm_metadata"]["masking_report"]
    assert informe["scope"] == "user"
    assert informe["unanalyzable"] == 0 and informe["unanalyzable_kinds"] == []
    assert DNI_PUNTOS not in _texto(salida["messages"][0]), "el turno user sí se enmascara"
    # Lo demás, byte a byte como antes: system, turno assistant y herramientas siguen en claro.
    assert salida["system"] == original["system"]
    assert salida["messages"][1] == original["messages"][1]
    assert salida["tools"] == original["tools"]


@pytest.mark.asyncio
async def test_sin_senal_mask_body_sin_scope_no_cambia_de_alcance():
    cuerpo = _pedido_anthropic()
    await policy.mask_body(cuerpo, h.analizador(), policy.PlaceholderMap())
    assert DNI in cuerpo["system"] and DNI in _texto(cuerpo["tools"])


# ── 2. Con la señal: alcance completo (formato Anthropic) ─────────────────────────────

@pytest.mark.asyncio
async def test_alcance_completo_anthropic_system_turnos_herramientas_y_thinking():
    cuerpo = {
        "model": "claude-sonnet-4-5",
        "max_tokens": 4096,
        "system": [{"type": "text", "text": f"Cliente CUIT {CUIT}", "cache_control": {"type": "ephemeral"}}],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": f"DNI {DNI_PUNTOS}"}]},
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": f"El DNI {DNI} es del cliente", "signature": "firma-opaca=="},
                {"type": "text", "text": f"Tengo su CBU {CBU}"},
                {"type": "tool_use", "id": "toolu_01A", "name": "buscar",
                 "input": {"consulta": f"documento {DNI}", "anidado": {"lista": [f"cuit {CUIT}"]}}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_01A",
                 "content": f"Resultado para el DNI {DNI}"},
                {"type": "tool_result", "tool_use_id": "toolu_01B",
                 "content": [{"type": "text", "text": f"CBU {CBU}"}]},
            ]},
        ],
        "tools": [{"name": "buscar", "description": f"Busca a quien tenga el DNI {DNI}",
                   "input_schema": {"type": "object", "properties": {
                       "q": {"type": "string", "description": f"ej. {CUIT}"}}}}],
    }
    cuerpo, mapa, tally = await _enmascarar(cuerpo)
    _sin_pii(cuerpo)
    assert tally.unanalyzable == 0 and tally.kinds == []
    assert tally.masked == tally.detected > 0
    assert len(mapa) >= 4
    # Estructura intacta (posiciones del protocolo): roles, tipos, ids, nombres, firma, modelo.
    assert cuerpo["model"] == "claude-sonnet-4-5" and cuerpo["max_tokens"] == 4096
    assert [m["role"] for m in cuerpo["messages"]] == ["user", "assistant", "user"]
    asistente = cuerpo["messages"][1]["content"]
    assert asistente[0]["signature"] == "firma-opaca==" and asistente[2]["id"] == "toolu_01A"
    assert asistente[2]["name"] == "buscar" and cuerpo["tools"][0]["name"] == "buscar"
    assert cuerpo["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert cuerpo["messages"][2]["content"][0]["tool_use_id"] == "toolu_01A"


@pytest.mark.asyncio
async def test_thinking_firmado_con_detecciones_se_enmascara_y_se_informa():
    cuerpo = {"model": "m", "messages": [{"role": "assistant", "content": [
        {"type": "thinking", "thinking": f"DNI {DNI}", "signature": "firma=="}]}]}
    cuerpo, _, tally = await _enmascarar(cuerpo)
    assert DNI not in _texto(cuerpo)
    assert cuerpo["messages"][0]["content"][0]["signature"] == "firma=="
    assert tally.signed_thinking_masked == 1, "el guard decide si el destino es nativo (invalida la firma)"


# ── 3. Regla general fail-closed: todo valor de texto ───────────────────────────────

@pytest.mark.asyncio
async def test_regla_general_metadata_stop_sequences_esquema_y_campos_desconocidos():
    cuerpo = {
        "model": "m", "max_tokens": 10,
        "metadata": {"user_id": f"dni-{DNI}"},
        "stop_sequences": [f"FIN {DNI_PUNTOS}"],
        "campo_nuevo_del_proveedor": {"nota": f"cuit {CUIT}"},
        "messages": [{"role": "user", "content": "hola"}],
        "tools": [{"name": "t", "input_schema": {"type": "object", "properties": {
            "tipo": {"type": "string", "enum": [f"cod {DNI}", "B"], "default": f"{DNI}",
                     "examples": [f"cbu {CBU}"], "title": f"T {CUIT}"}}}}],
    }
    cuerpo, _, tally = await _enmascarar(cuerpo)
    _sin_pii(cuerpo)
    assert tally.unanalyzable == 0
    # Las claves de `properties` y las palabras clave del esquema siguen siendo las mismas.
    assert list(cuerpo["tools"][0]["input_schema"]["properties"]) == ["tipo"]
    assert cuerpo["tools"][0]["input_schema"]["properties"]["tipo"]["type"] == "string"


@pytest.mark.asyncio
async def test_posiciones_estructurales_de_r29_salen_intactas():
    cuerpo = {
        "model": "claude-sonnet-4-5-20250929", "stream": True, "max_tokens": 8000, "temperature": 0.2,
        "thinking": {"type": "enabled", "budget_tokens": 2048},
        "tool_choice": {"type": "tool", "name": "buscar"},
        "system": "Sos un asistente",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "hola", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]}],
        "tools": [{"name": "buscar", "type": "custom", "description": "d",
                   "cache_control": {"type": "ephemeral"},
                   "input_schema": {"type": "object", "required": ["q"],
                                    "properties": {"q": {"type": "string", "format": "uri"}}}}],
    }
    original = copy.deepcopy(cuerpo)
    cuerpo, _, tally = await _enmascarar(cuerpo)
    assert cuerpo == original
    assert tally.unanalyzable == 0 and tally.detected == 0


# ── 4. Formato OpenAI ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_alcance_completo_openai_system_developer_tool_calls_y_nombres():
    cuerpo = {
        "model": "gpt-x", "user": f"cliente-{DNI}",
        "messages": [
            {"role": "system", "content": f"Cliente CUIT {CUIT}"},
            {"role": "developer", "content": [{"type": "text", "text": f"CBU {CBU}"}]},
            {"role": "user", "name": f"Ana-{DNI}", "content": f"DNI {DNI_PUNTOS}"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "buscar", "arguments": json.dumps({"q": f"dni {DNI}"})}}]},
            {"role": "tool", "tool_call_id": "call_1", "content": f"Resultado {DNI}"},
        ],
        "tools": [{"type": "function", "function": {
            "name": "buscar", "description": f"por DNI {DNI}",
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}}],
    }
    cuerpo, _, tally = await _enmascarar(cuerpo, fmt="openai")
    _sin_pii(cuerpo)
    assert tally.unanalyzable == 0
    llamada = cuerpo["messages"][3]["tool_calls"][0]
    assert llamada["id"] == "call_1" and llamada["function"]["name"] == "buscar"
    assert json.loads(llamada["function"]["arguments"])["q"].startswith("dni [")
    assert cuerpo["messages"][4]["tool_call_id"] == "call_1"


# ── 5. PDF ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pdf_con_texto_viaja_como_bloque_de_texto_enmascarado():
    pdf = h.pdf_con_texto(f"Ficha del cliente DNI {DNI}", "Segunda pagina sin datos")
    cuerpo = {"model": "m", "messages": [{"role": "user", "content": [
        {"type": "text", "text": "resumí"}, h.bloque_pdf(pdf)]}]}
    cuerpo, mapa, tally = await _enmascarar(cuerpo)
    bloque = cuerpo["messages"][0]["content"][1]
    if h.HAY_PYPDF:
        assert bloque["type"] == "text" and "Ficha del cliente DNI [DNI_" in bloque["text"]
        assert DNI not in _texto(cuerpo) and "Segunda pagina" in bloque["text"]
        assert tally.unanalyzable == 0 and DNI in mapa.values()
    else:
        assert tally.kinds == ["pdf_unavailable"], "sin pypdf, todo PDF es no analizable (falla cerrado)"


@pytest.mark.asyncio
async def test_pdf_sin_pypdf_es_no_analizable_siempre(monkeypatch):
    monkeypatch.setattr(policy, "_pypdf_disponible", lambda: False)
    cuerpo = {"model": "m", "messages": [{"role": "user", "content": [h.bloque_pdf(h.pdf_con_texto("x"))]}]}
    _, _, tally = await _enmascarar(cuerpo)
    assert tally.unanalyzable == 1 and tally.kinds == ["pdf_unavailable"]


@pytest.mark.asyncio
async def test_pdf_openai_parte_file_con_texto():
    pdf = h.pdf_con_texto(f"DNI {DNI}")
    cuerpo = {"model": "m", "messages": [{"role": "user", "content": [
        {"type": "text", "text": "mirá"}, h.parte_pdf_openai(pdf)]}]}
    cuerpo, _, tally = await _enmascarar(cuerpo, fmt="openai")
    if h.HAY_PYPDF:
        assert cuerpo["messages"][0]["content"][1]["type"] == "text"
        assert DNI not in _texto(cuerpo) and tally.unanalyzable == 0
    else:
        assert tally.kinds == ["pdf_unavailable"]


@pytest.mark.asyncio
@pytest.mark.parametrize("nombre,pdf,esperado", [
    ("escaneado", lambda: h.pdf_sin_texto(2), "pdf_no_text"),
    ("protegido", lambda: h.pdf_protegido(), "pdf_error"),
    ("corrupto", lambda: b"%PDF-1.4\nesto no es un pdf\n", "pdf_error"),
])
async def test_pdf_no_extraible_es_no_analizable_con_su_nombre(nombre, pdf, esperado):
    cuerpo = {"model": "m", "messages": [{"role": "user", "content": [h.bloque_pdf(pdf())]}]}
    _, _, tally = await _enmascarar(cuerpo)
    assert tally.unanalyzable == 1
    assert tally.kinds == [h.kind_esperado(esperado)]


@pytest.mark.asyncio
async def test_pdf_sobre_topes_de_paginas_y_de_bytes(monkeypatch):
    monkeypatch.setenv("MASKING_PDF_MAX_PAGES", "2")
    cuerpo = {"model": "m", "messages": [{"role": "user", "content": [
        h.bloque_pdf(h.pdf_con_texto("a", "b", "c"))]}]}
    _, _, tally = await _enmascarar(cuerpo)
    assert tally.kinds == [h.kind_esperado("pdf_resource_limit")]

    monkeypatch.setenv("MASKING_PDF_MAX_PAGES", "200")
    monkeypatch.setenv("MASKING_PDF_MAX_BYTES", "500")
    cuerpo = {"model": "m", "messages": [{"role": "user", "content": [
        h.bloque_pdf(h.pdf_con_texto("a" * 800))]}]}
    _, _, tally = await _enmascarar(cuerpo)
    assert tally.kinds == [h.kind_esperado("pdf_resource_limit")]


@pytest.mark.asyncio
async def test_no_analizables_con_sus_nombres_de_tipo():
    cuerpo = {"model": "m", "messages": [
        {"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}},
            {"type": "document", "source": {"type": "url", "url": "https://x.example/a.pdf"}},
            {"type": "audio", "source": {"type": "base64", "media_type": "audio/wav", "data": "AAAA"}},
            {"type": "tipo_que_no_existe", "payload": "x"},
        ]},
        {"role": "assistant", "content": [{"type": "redacted_thinking", "data": "opaco"}]},
    ]}
    _, _, tally = await _enmascarar(cuerpo)
    assert tally.unanalyzable == 5, "Anthropic no tiene bloque de audio: es un tipo desconocido"
    assert tally.kinds == sorted(["image", "document_url", "unknown_block", "redacted_thinking"])


@pytest.mark.asyncio
async def test_no_analizables_openai_imagen_audio_y_archivo_por_id():
    cuerpo = {"model": "m", "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "https://x.example/a.png"}},
        {"type": "input_audio", "input_audio": {"data": "AAAA", "format": "wav"}},
        {"type": "file", "file": {"file_id": "file-abc"}},
    ]}]}
    _, _, tally = await _enmascarar(cuerpo, fmt="openai")
    assert tally.unanalyzable == 3
    assert tally.kinds == sorted(["image", "audio", "document_url"])


# ── 6. Guardrail: la señal, el informe y la política ──────────────────────────────

async def _hook(data, *, call_type="anthropic_messages", senal=True, **identidad):
    home = sentinel_guardrail._metadata_home(data, call_type)
    if senal:
        policy.mark_forced_masking(home)
    return await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(
        _Identidad(**identidad), None, data, call_type)


@pytest.mark.asyncio
async def test_guardrail_con_senal_enmascara_todo_e_informa_scope_full():
    data = _pedido_anthropic()
    salida = await _hook(data)
    _sin_pii(_cliente(salida))
    informe = data["litellm_metadata"]["masking_report"]
    assert informe == {"completed": True, "degraded": False, "detected": informe["detected"],
                       "masked": informe["masked"], "scope": "full", "unanalyzable": 0,
                       "unanalyzable_kinds": []}
    assert informe["detected"] == informe["masked"] >= 4


@pytest.mark.asyncio
async def test_la_senal_que_manda_el_cliente_se_descarta():
    data = _pedido_anthropic()
    data["metadata"] = {"sentinel_forced_masking": {"scope": "full"}, "otra": "x"}
    data["litellm_metadata"] = {"sentinel_forced_masking": {"scope": "full"}}
    data["sentinel_forced_masking"] = {"scope": "full"}
    salida = await _hook(data, senal=False)
    informe = data["litellm_metadata"]["masking_report"]
    assert informe["scope"] == "user", "una señal sembrada por el cliente no amplía ni cambia nada"
    assert DNI in salida["system"], "alcance de hoy: el system no se toca"
    for home in (data["metadata"], data["litellm_metadata"], data):
        assert not isinstance(home.get("sentinel_forced_masking"), policy.ForcedMaskingSignal)
    assert "sentinel_forced_masking" not in data and "sentinel_forced_masking" not in data["metadata"]


@pytest.mark.asyncio
async def test_senal_valida_en_el_home_de_la_pasarela_pero_no_la_del_cliente_en_metadata():
    data = _pedido_anthropic()
    data["metadata"] = {"sentinel_forced_masking": {"scope": "user"}}
    salida = await _hook(data)           # la pasarela escribe en `litellm_metadata`
    assert data["litellm_metadata"]["masking_report"]["scope"] == "full"
    _sin_pii(_cliente(salida))


@pytest.mark.asyncio
async def test_forzado_enciende_el_enmascarado_aunque_la_empresa_lo_apague():
    data = _pedido_anthropic()
    salida = await _hook(data, redact_enabled=False)
    _sin_pii(_cliente(salida))
    assert data["litellm_metadata"]["masking_report"]["masked"] > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("modo", ["degrade", "block", None])
async def test_forzado_con_analizador_caido_bloquea_aunque_diga_degrade(monkeypatch, modo):
    async def _caido(*_a, **_k):
        raise policy.NlpUnavailableError("down")

    monkeypatch.setattr(sentinel_guardrail, "_PRESIDIO_URL", "http://nlp")
    monkeypatch.setattr(policy, "presidio_analyze", _caido)
    data = _pedido_anthropic()
    extra = {} if modo is None else {"nlp_fail_mode": modo}
    salida = await _hook(data, **extra)
    assert isinstance(salida, str), "el rechazo del hook es una cadena (HTTP 400)"
    assert data["litellm_metadata"]["masking_report"]["degraded"] is False
    assert data["litellm_metadata"]["masking_report"]["completed"] is False


@pytest.mark.asyncio
async def test_un_tipo_que_la_empresa_no_enmascara_se_enmascara_igual_bajo_forzado():
    data = {"model": "m", "messages": [{"role": "user", "content": f"DNI {DNI}"}]}
    salida = await _hook(data, entity_configs={"DNI": "ALLOW"})
    assert DNI not in _texto(_cliente(salida))
    informe = data["litellm_metadata"]["masking_report"]
    assert informe["detected"] == informe["masked"] == 1


@pytest.mark.asyncio
async def test_informe_con_no_analizables_no_lleva_contenido():
    data = {"model": "m", "messages": [{"role": "user", "content": [
        {"type": "text", "text": f"DNI {DNI}"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}]}]}
    await _hook(data)
    informe = data["litellm_metadata"]["masking_report"]
    assert informe["unanalyzable"] == 1 and informe["unanalyzable_kinds"] == ["image"]
    assert informe["completed"] is True, "el guardrail informa; el guard de la extensión bloquea"
    for valor in (DNI, "AAAA"):
        assert valor not in json.dumps(informe)


@pytest.mark.asyncio
async def test_conversacion_de_varios_turnos_vuelve_a_enmascarar_la_respuesta_restaurada():
    # La herramienta reenvía la respuesta del asistente YA restaurada (con el DNI original):
    # sale enmascarada de nuevo, y el mapa del pedido lo restaura en la respuesta.
    data = {
        "model": "m", "system": f"Cliente CUIT {CUIT}",
        "messages": [
            {"role": "user", "content": f"Mi DNI es {DNI}"},
            {"role": "assistant", "content": [{"type": "text", "text": f"Confirmo su DNI {DNI}"}]},
            {"role": "user", "content": "¿y mi CBU?"},
        ]}
    salida = await _hook(data)
    _sin_pii(_cliente(salida))
    mapa = data["litellm_metadata"]["pii_tokens"]
    asistente = salida["messages"][1]["content"][0]["text"]
    assert policy.unmask_text(asistente, mapa) == f"Confirmo su DNI {DNI}"


# ── 7. Patrón de CUIT/CUIL sin guiones del perfil latam_ar (QA M7) ─────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("valor", [CUIT, h.CUIT_SIN_GUIONES, DNI, DNI_PUNTOS, CBU])
async def test_bateria_de_formatos_del_perfil_latam_ar(valor):
    entidades = await policy.default_analyze(f"dato {valor} fin", region="latam_ar")
    assert entidades, f"{valor} no se detecta"
    assert any(valor in f"dato {valor} fin"[e["start"]:e["end"]] for e in entidades)


def test_patron_cuil_sin_guiones_en_la_tabla_principal():
    import re
    patron = policy.STRUCTURED_ID_PATTERNS_BY_REGION["latam_ar"]["CUIL"][0]
    assert re.search(patron, f"cuit {CUIT}") and re.search(patron, f"cuit {h.CUIT_SIN_GUIONES}")
    assert not re.search(patron, "cuit 2030123456"), "10 dígitos no es un CUIT"


# ── 8. Resolutor registrado por una extensión (el grant firmado no lo ve el guardrail base) ──────

@pytest.mark.asyncio
async def test_un_resolutor_registrado_que_dice_si_activa_el_alcance_completo():
    vistos = []

    def _resolutor(data, user_api_key_dict, call_type):
        vistos.append(call_type)
        return True

    policy.register_forced_masking_resolver(_resolutor)
    policy.register_forced_masking_resolver(_resolutor)       # idempotente
    data = _pedido_anthropic()
    salida = await _hook(data, senal=False)
    assert vistos == ["anthropic_messages"], "se consulta una vez por pedido"
    assert data["litellm_metadata"]["masking_report"]["scope"] == "full"
    _sin_pii(_cliente(salida))
    # la marca la puso el guardrail, dentro del motor (no se puede forjar desde el cuerpo)
    assert isinstance(data["litellm_metadata"][policy.FORCED_MASKING_KEY], policy.ForcedMaskingSignal)


@pytest.mark.asyncio
async def test_un_resolutor_que_dice_no_deja_el_alcance_de_hoy():
    policy.register_forced_masking_resolver(lambda *_: False)
    data = _pedido_anthropic()
    salida = await _hook(data, senal=False)
    assert data["litellm_metadata"]["masking_report"]["scope"] == "user"
    assert DNI in salida["system"]


@pytest.mark.asyncio
async def test_un_resolutor_que_falla_cuenta_como_forzado_falla_cerrado():
    def _roto(*_a):
        raise RuntimeError("firma ilegible")

    policy.register_forced_masking_resolver(_roto)
    data = _pedido_anthropic()
    salida = await _hook(data, senal=False)
    assert data["litellm_metadata"]["masking_report"]["scope"] == "full"
    _sin_pii(_cliente(salida))


@pytest.mark.asyncio
async def test_la_senal_del_cliente_no_activa_nada_aunque_haya_resolutores_que_dicen_no():
    policy.register_forced_masking_resolver(lambda *_: False)
    data = _pedido_anthropic()
    data["metadata"] = {"sentinel_forced_masking": {"scope": "full"}}
    await _hook(data, senal=False)
    assert data["litellm_metadata"]["masking_report"]["scope"] == "user"


# ── 9. `thinking` firmado: campo opcional, no suma a no analizables ──────────────────────

@pytest.mark.asyncio
async def test_el_informe_lleva_signed_thinking_solo_cuando_hubo_y_no_suma_a_unanalyzable():
    data = {"model": "m", "messages": [{"role": "assistant", "content": [
        {"type": "thinking", "thinking": f"DNI {DNI}", "signature": "firma=="}]}]}
    await _hook(data)
    informe = data["litellm_metadata"]["masking_report"]
    assert informe["signed_thinking"] == 1
    assert informe["unanalyzable"] == 0 and informe["unanalyzable_kinds"] == []

    limpio = {"model": "m", "messages": [{"role": "assistant", "content": [
        {"type": "thinking", "thinking": "sin datos", "signature": "firma=="}]}]}
    await _hook(limpio)
    assert "signed_thinking" not in limpio["litellm_metadata"]["masking_report"]


# ── 10. Lo interno del motor no se recorre; lo del cliente sí ─────────────────────────

@pytest.mark.asyncio
async def test_la_metadata_del_cliente_se_enmascara_y_la_interna_del_motor_no_se_toca():
    data = _pedido_anthropic()
    data["metadata"] = {"user_id": f"dni-{DNI}"}
    data["litellm_metadata"] = {"user_api_key_user_email": "operadora@ejemplo.es", "requester_ip": "10.0.0.7"}
    data["proxy_server_request"] = {"headers": {"x-forwarded-for": "190.1.2.3"},
                                    "body": {"raw": f"DNI {DNI}"}}
    interna = copy.deepcopy(data["litellm_metadata"])
    copia_de_registro = copy.deepcopy(data["proxy_server_request"])
    salida = await _hook(data)
    assert DNI not in _texto(salida["metadata"]), "metadata.user_id es del cliente: sale enmascarada"
    for clave, valor in interna.items():
        assert data["litellm_metadata"][clave] == valor, f"{clave}: la metadata interna no se enmascara"
    assert data["proxy_server_request"] == copia_de_registro, "la copia de registro de la pasarela no se toca"


@pytest.mark.asyncio
async def test_en_las_rutas_openai_metadata_es_el_home_interno_y_no_se_recorre():
    data = {"model": "m", "messages": [{"role": "user", "content": f"DNI {DNI}"}],
            "metadata": {"user_api_key_user_email": "operadora@ejemplo.es"}}
    salida = await _hook(data, call_type="acompletion")
    assert DNI not in _texto(salida["messages"])
    assert salida["metadata"]["user_api_key_user_email"] == "operadora@ejemplo.es"
    assert salida["metadata"]["masking_report"]["scope"] == "full"
