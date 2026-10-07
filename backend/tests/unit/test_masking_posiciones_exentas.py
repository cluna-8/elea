"""S14 — exenciones por POSICIÓN estructural, nunca por nombre de clave (057 T106; QA v2 N8; research R29;
contracts/costuras-base.md §S14 «Posiciones exentas»).

Un campo llamado `id`, `name`, `type` o `role` en un subárbol libre (`tool_use.input`, `metadata`,
`function.arguments`, `default`/`examples` del esquema…) NO está exento: se enmascara como cualquier valor.
Las claves de objeto con datos se enmascaran (la respuesta las restaura); los escalares numéricos se
analizan como su texto decimal y, si hay detección, salen como marcador (cadena). Las posiciones
estructurales se analizan pero no se reescriben: una detección ahí es «no analizable»
(`structural_entity`) y el guard bloquea.
"""
import copy
import json

import pytest

import s14_helpers as h
from s14_helpers import CBU, CUIT, DNI, DNI_PUNTOS, policy  # noqa: E402
from extensions import sentinel_guardrail  # noqa: E402

TEL = 5491112345678


async def _enmascarar(body, *, fmt="anthropic"):
    tally = policy.MaskingTally()
    mapa_ph = policy.PlaceholderMap()
    cuerpo, mapa = await policy.mask_body(
        body, h.analizador(), mapa_ph, scope="full", fmt=fmt, tally=tally)
    return cuerpo, mapa, tally


def _plano(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _mensaje_con_input(entrada):
    return {"model": "m", "messages": [{"role": "assistant", "content": [
        {"type": "tool_use", "id": "toolu_01", "name": "buscar", "input": entrada}]}]}


# ── (a) colisión de nombres en subárboles libres ────────────────────────────────────

COLISION = {"name": "Juan Pérez", "id": DNI, "type": f"DNI {DNI_PUNTOS}", "role": CUIT}


@pytest.mark.asyncio
async def test_a_colision_de_nombres_en_tool_use_input():
    cuerpo, _, tally = await _enmascarar(_mensaje_con_input(copy.deepcopy(COLISION)))
    entrada = cuerpo["messages"][0]["content"][0]["input"]
    _sin_datos(entrada)
    assert set(entrada) == {"name", "id", "type", "role"}, "las claves de protocolo-con-nombre-común no cambian"
    assert tally.unanalyzable == 0


def _sin_datos(obj):
    plano = _plano(obj)
    for valor in (DNI, DNI_PUNTOS, CUIT):
        assert valor not in plano, f"{valor!r} salió en claro"


@pytest.mark.asyncio
async def test_a_colision_en_metadata():
    cuerpo = {"model": "m", "metadata": copy.deepcopy(COLISION),
              "messages": [{"role": "user", "content": "hola"}]}
    cuerpo, _, tally = await _enmascarar(cuerpo)
    _sin_datos(cuerpo["metadata"])
    assert tally.unanalyzable == 0


@pytest.mark.asyncio
async def test_a_colision_en_arguments_de_openai():
    cuerpo = {"model": "m", "messages": [{"role": "assistant", "content": None, "tool_calls": [
        {"id": "call_1", "type": "function",
         "function": {"name": "buscar", "arguments": json.dumps(COLISION)}}]}]}
    cuerpo, _, tally = await _enmascarar(cuerpo, fmt="openai")
    argumentos = json.loads(cuerpo["messages"][0]["tool_calls"][0]["function"]["arguments"])
    _sin_datos(argumentos)
    assert tally.unanalyzable == 0


@pytest.mark.asyncio
async def test_a_colision_en_default_y_examples_del_esquema():
    esquema = {"type": "object", "properties": {"x": {
        "type": "object", "default": copy.deepcopy(COLISION), "examples": [copy.deepcopy(COLISION)]}}}
    cuerpo = {"model": "m", "messages": [], "tools": [{"name": "t", "input_schema": esquema}]}
    cuerpo, _, tally = await _enmascarar(cuerpo)
    x = cuerpo["tools"][0]["input_schema"]["properties"]["x"]
    _sin_datos(x)
    assert x["type"] == "object", "la palabra clave `type` del esquema queda"
    assert tally.unanalyzable == 0


# ── (b) claves con datos ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_b_claves_con_datos_se_enmascaran_y_la_respuesta_las_restaura():
    cuerpo = _mensaje_con_input({DNI: "x", "juan@ejemplo.com": 1, "normal": {DNI_PUNTOS: [1, 2]}})
    cuerpo, mapa, tally = await _enmascarar(cuerpo)
    entrada = cuerpo["messages"][0]["content"][0]["input"]
    assert DNI not in _plano(entrada) and "juan@ejemplo.com" not in _plano(entrada)
    assert DNI_PUNTOS not in _plano(entrada) and "normal" in entrada
    assert tally.unanalyzable == 0
    # El modelo repite las claves enmascaradas en su tool_use: la respuesta las restaura.
    respuesta = {"content": [{"type": "tool_use", "id": "t", "name": "n",
                              "input": copy.deepcopy(entrada)}]}
    policy.unmask_response_payload(respuesta, mapa)
    assert respuesta["content"][0]["input"] == {DNI: "x", "juan@ejemplo.com": 1,
                                                 "normal": {DNI_PUNTOS: [1, 2]}}


# ── (c) escalares numéricos ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_c_escalares_numericos_salen_como_marcador_y_vuelven_restaurados():
    entrada = {"dni": int(DNI), "cbu": int(CBU), "tel": TEL, "activo": True, "nada": None, "n": 3}
    cuerpo, mapa, tally = await _enmascarar(_mensaje_con_input(copy.deepcopy(entrada)))
    salida = cuerpo["messages"][0]["content"][0]["input"]
    for clave in ("dni", "cbu", "tel"):
        assert isinstance(salida[clave], str) and salida[clave].startswith("["), (clave, salida[clave])
    assert salida["activo"] is True and salida["nada"] is None and salida["n"] == 3
    assert tally.unanalyzable == 0
    respuesta = {"content": [{"type": "tool_use", "id": "t", "name": "n", "input": dict(salida)}]}
    policy.unmask_response_payload(respuesta, mapa)
    restaurado = respuesta["content"][0]["input"]
    assert restaurado["dni"] == DNI and restaurado["cbu"] == CBU and restaurado["tel"] == str(TEL)


@pytest.mark.asyncio
async def test_c_numeros_en_arguments_de_openai():
    cuerpo = {"model": "m", "messages": [{"role": "assistant", "content": None, "tool_calls": [
        {"id": "c", "type": "function",
         "function": {"name": "f", "arguments": json.dumps({"dni": int(DNI), "ok": False})}}]}]}
    cuerpo, _, _ = await _enmascarar(cuerpo, fmt="openai")
    argumentos = json.loads(cuerpo["messages"][0]["tool_calls"][0]["function"]["arguments"])
    assert isinstance(argumentos["dni"], str) and argumentos["ok"] is False


# ── (d) posiciones estructurales intactas ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_d_posiciones_estructurales_intactas_anthropic():
    cuerpo = {
        "model": "claude-sonnet-4-5-20250929", "stream": False, "max_tokens": 4096, "top_k": 40,
        "thinking": {"type": "enabled", "budget_tokens": 4000},
        "tool_choice": {"type": "tool", "name": "buscar", "disable_parallel_tool_use": True},
        "messages": [
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "pienso", "signature": "EqQBCkYIBRgC=="},
                {"type": "tool_use", "id": "toolu_01ABCdef", "name": "buscar", "input": {}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_01ABCdef",
                 "content": [{"type": "text", "text": "listo"}]},
                {"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": "texto"}}]},
        ],
        "tools": [{"name": "buscar", "type": "custom", "description": "d", "input_schema": {
            "type": "object", "required": ["q", "otro"],
            "properties": {"q": {"type": "string", "format": "date"}, "otro": {"$ref": "#/$defs/a"}},
            "$defs": {"a": {"type": "integer", "minimum": 1}}}}],
    }
    original = copy.deepcopy(cuerpo)
    cuerpo, _, tally = await _enmascarar(cuerpo)
    assert cuerpo == original
    assert tally.unanalyzable == 0 and tally.detected == 0


@pytest.mark.asyncio
async def test_d_posiciones_estructurales_intactas_openai():
    cuerpo = {
        "model": "gpt-4o-2024-08-06", "stream": True, "stream_options": {"include_usage": True},
        "max_tokens": 100, "n": 1, "temperature": 0.5, "parallel_tool_calls": False,
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "salida", "schema": {"type": "object", "properties": {"a": {"type": "string"}}}}},
        "tool_choice": {"type": "function", "function": {"name": "buscar"}},
        "messages": [
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_abc", "type": "function", "function": {"name": "buscar", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call_abc", "content": "listo"},
        ],
        "tools": [{"type": "function", "function": {
            "name": "buscar", "strict": True,
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}}}],
    }
    original = copy.deepcopy(cuerpo)
    cuerpo, _, tally = await _enmascarar(cuerpo, fmt="openai")
    assert cuerpo == original
    assert tally.unanalyzable == 0


@pytest.mark.asyncio
async def test_d_bloques_anidados_en_tool_result_siguen_las_posiciones_de_bloque():
    cuerpo = {"model": "m", "messages": [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_01", "content": [
            {"type": "text", "text": f"DNI {DNI}", "cache_control": {"type": "ephemeral"}},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}]}]}]}
    cuerpo, _, tally = await _enmascarar(cuerpo)
    anidados = cuerpo["messages"][0]["content"][0]["content"]
    assert DNI not in _plano(cuerpo) and anidados[0]["type"] == "text"
    assert anidados[0]["cache_control"] == {"type": "ephemeral"}
    assert tally.kinds == ["image"], "la imagen anidada también es no analizable (j)"


# ── (e) contrabando en una posición estructural ───────────────────────────────────────

@pytest.mark.asyncio
async def test_e_dni_como_id_de_tool_use_no_se_reescribe_y_es_no_analizable():
    cuerpo = {"model": "m", "messages": [{"role": "assistant", "content": [
        {"type": "tool_use", "id": DNI_PUNTOS, "name": "buscar", "input": {}}]}]}
    cuerpo, _, tally = await _enmascarar(cuerpo)
    assert cuerpo["messages"][0]["content"][0]["id"] == DNI_PUNTOS, "reescribirlo rompería el pedido"
    assert tally.kinds == ["structural_entity"] and tally.unanalyzable == 1


@pytest.mark.asyncio
async def test_e_dni_como_nombre_de_herramienta_es_no_analizable():
    cuerpo = {"model": "m", "messages": [], "tools": [
        {"name": DNI, "description": "d", "input_schema": {"type": "object"}}]}
    cuerpo, _, tally = await _enmascarar(cuerpo)
    assert cuerpo["tools"][0]["name"] == DNI and tally.kinds == ["structural_entity"]


@pytest.mark.asyncio
async def test_e_contrabando_en_clave_de_properties_y_en_openai_function_name():
    esquema = {"type": "object", "properties": {DNI: {"type": "string"}}}
    cuerpo = {"model": "m", "messages": [], "tools": [{"name": "t", "input_schema": esquema}]}
    cuerpo, _, tally = await _enmascarar(cuerpo)
    assert list(cuerpo["tools"][0]["input_schema"]["properties"]) == [DNI]
    assert tally.kinds == ["structural_entity"]

    openai = {"model": "m", "messages": [{"role": "assistant", "content": None, "tool_calls": [
        {"id": "c", "type": "function", "function": {"name": DNI, "arguments": "{}"}}]}]}
    openai, _, tally = await _enmascarar(openai, fmt="openai")
    assert openai["messages"][0]["tool_calls"][0]["function"]["name"] == DNI
    assert tally.kinds == ["structural_entity"]


@pytest.mark.asyncio
async def test_e_el_guardrail_informa_el_contrabando_para_que_el_guard_bloquee(monkeypatch):
    async def _nada(*_a, **_k):
        return None

    monkeypatch.setattr(sentinel_guardrail, "_auditar_bloqueo", _nada)
    monkeypatch.setattr(sentinel_guardrail, "_PRESIDIO_URL", None)

    class _Id:
        metadata = {"sentinel": {"region": "latam_ar"}}

    data = {"model": "m", "messages": [{"role": "assistant", "content": [
        {"type": "tool_use", "id": DNI, "name": "buscar", "input": {}}]}]}
    home = sentinel_guardrail._metadata_home(data, "anthropic_messages")
    policy.mark_forced_masking(home)
    await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(_Id(), None, data, "anthropic_messages")
    informe = data["litellm_metadata"]["masking_report"]
    assert informe["unanalyzable"] == 1 and informe["unanalyzable_kinds"] == ["structural_entity"]
    assert informe["detected"] > informe["masked"], "detectado y no enmascarado: el guard no puede pasarlo"


# ── (f) cache_control fuera del protocolo ─────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("forma", [
    {"type": "ephemeral", "extra": f"dni {DNI}"},
    {"type": "algo_raro"},
    {"type": "ephemeral", "ttl": "una semana"},
    "no-es-un-objeto",
])
async def test_f_cache_control_con_forma_fuera_del_protocolo_es_no_analizable(forma):
    cuerpo = {"model": "m", "messages": [{"role": "user", "content": [
        {"type": "text", "text": "hola", "cache_control": copy.deepcopy(forma)}]}]}
    _, _, tally = await _enmascarar(cuerpo)
    assert tally.kinds == ["cache_control"]


@pytest.mark.asyncio
async def test_f_cache_control_valido_pasa_intacto_en_system_y_tools():
    cuerpo = {"model": "m",
              "system": [{"type": "text", "text": "s", "cache_control": {"type": "ephemeral", "ttl": "5m"}}],
              "messages": [],
              "tools": [{"name": "t", "cache_control": {"type": "ephemeral"}, "input_schema": {"type": "object"}}]}
    original = copy.deepcopy(cuerpo)
    cuerpo, _, tally = await _enmascarar(cuerpo)
    assert cuerpo == original and tally.unanalyzable == 0


# ── (h) `seed` de OpenAI que cumple el patrón de DNI ──────────────────────────────────

@pytest.mark.asyncio
async def test_h_seed_de_8_digitos_cumple_el_patron_de_dni_y_se_bloquea():
    cuerpo = {"model": "m", "seed": 12345678, "messages": [{"role": "user", "content": "hola"}]}
    cuerpo, _, tally = await _enmascarar(cuerpo, fmt="openai")
    assert cuerpo["seed"] == 12345678, "no se reescribe"
    assert tally.kinds == ["structural_entity"], "falso positivo aceptado, fail-closed"


# ── (i) function.arguments que no es JSON válido ──────────────────────────────────────

@pytest.mark.asyncio
async def test_i_arguments_que_no_es_json_se_analiza_como_texto():
    cuerpo = {"model": "m", "messages": [{"role": "assistant", "content": None, "tool_calls": [
        {"id": "c", "type": "function",
         "function": {"name": "f", "arguments": f"{{esto no es json, dni {DNI}"}}]}]}
    cuerpo, _, tally = await _enmascarar(cuerpo, fmt="openai")
    argumentos = cuerpo["messages"][0]["tool_calls"][0]["function"]["arguments"]
    assert DNI not in argumentos and "esto no es json" in argumentos
    assert tally.unanalyzable == 0


# ── (g) la tabla de posiciones es igual a la del contrato ─────────────────────────────

POSICIONES_DEL_CONTRATO = {
    "anthropic": {
        "opaque": [
            "model",
            "….signature",
            "….source.data",
            "….cache_control",
            "tools.*.cache_control",
        ],
        "structural": [
            "stream", "max_tokens", "temperature", "top_p", "top_k",
            "thinking.type", "thinking.budget_tokens", "reasoning_effort",
            "tool_choice.type", "tool_choice.name", "tool_choice.disable_parallel_tool_use",
            "messages.*.role",
            "….type", "….id@tool_use", "….name@tool_use", "….tool_use_id@tool_result", "….is_error@tool_result",
            "….source.type", "….source.media_type",
            "tools.*.name", "tools.*.type",
            "tools.*.input_schema#schema",
        ],
    },
    "openai": {
        "opaque": [
            "model",
            "….file.file_data",
            "….image_url.url",
        ],
        "structural": [
            "stream", "stream_options.*", "max_tokens", "max_completion_tokens", "temperature", "top_p", "n",
            "seed", "presence_penalty", "frequency_penalty", "logprobs", "top_logprobs", "reasoning_effort",
            "parallel_tool_calls", "response_format.type", "response_format.json_schema.name",
            "tool_choice", "tool_choice.type", "tool_choice.function.name",
            "messages.*.role", "messages.*.tool_call_id",
            "messages.*.tool_calls.*.id", "messages.*.tool_calls.*.type",
            "messages.*.tool_calls.*.function.name",
            "….type",
            "tools.*.type", "tools.*.function.name", "tools.*.function.strict",
            "tools.*.function.parameters#schema", "response_format.json_schema.schema#schema",
        ],
    },
}


def test_g_la_tabla_de_posiciones_del_guardrail_es_igual_a_la_del_contrato():
    tabla = policy.S14_EXEMPT_POSITIONS
    assert {f: {c: sorted(v) for c, v in clases.items()} for f, clases in tabla.items()} == {
        f: {c: sorted(v) for c, v in clases.items()} for f, clases in POSICIONES_DEL_CONTRATO.items()
    }, ("agregar o quitar una posición exenta es un cambio de contrato "
        "(contracts/costuras-base.md §S14) con test")
