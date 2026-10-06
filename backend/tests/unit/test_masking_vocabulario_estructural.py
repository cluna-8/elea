"""S14 — posiciones estructurales con el NER REAL: vocabulario cerrado y tipos semánticos en identificadores (057 T083; decisión del
owner del 2026-10-06 que enmienda N8; contracts/costuras-base.md §S14 «Vocabulario cerrado y tipos semánticos»).

Con el analizador real (spaCy es + reconocedores de patrón), el recorrido de alcance completo bloqueaba TODO pedido con un mensaje
`assistant` o con herramientas: `assistant`, `tool_use`, `Read`, `file_path` o un id `toolu_…` salían como PERSON/LOCATION en una
posición estructural (que no se reescribe) y contaban como `structural_entity`. Esta suite imita al NER con un analizador que, además
de los patrones de la base, marca esas cadenas con tipos semánticos, y fija la regla nueva:

  (A) valores de VOCABULARIO CERRADO del protocolo (rol, tipo de bloque, `tool_choice.type`, …): no se analizan; un valor fuera del
      vocabulario se sigue analizando como antes;
  (B) posiciones estructurales de vocabulario ABIERTO (nombres de herramienta, ids, claves de esquema): se ignoran SOLO los tipos de NER
      semántico (PERSON, LOCATION, ORGANIZATION, NRP, URL, DATE_TIME); los de patrón (DNI, CUIT, CBU, email, teléfono, tarjeta, IBAN…)
      y los propios de la empresa siguen bloqueando.

El texto de los mensajes, `tool_result`, `thinking`, `system` y los subárboles libres no cambian.
"""
import copy
import json
import re

import pytest

import s14_helpers as h
from s14_helpers import CBU, CUIT, DNI, policy  # noqa: E402

# Lo que el NER real marcó en el pedido sintético de Claude Code (medido en el motor con el analizador real, 2026-10-06).
SEMANTICAS = {"assistant": "PERSON", "tool_use": "PERSON", "tool_result": "PERSON", "Read": "PERSON", "file_path": "PERSON",
              "toolu_01A09q90qw90lq91780001": "LOCATION", "Herramienta3": "LOCATION", "0.py": "URL",
              "get_customer": "ORGANIZATION", "Juan Pérez": "PERSON", "x-juan": "PERSON", "tool": "PERSON",
              "function": "PERSON", "user": "PERSON", "custom": "ORGANIZATION"}


async def _ner(texto, tipos=None):
    """Analizador de patrones de la base + marcas semánticas sobre la cadena completa (como las que hace el NER)."""
    salida = await policy.default_analyze(texto, region="latam_ar")
    tipo = (tipos or SEMANTICAS).get(texto)
    if tipo is None and (texto.startswith("toolu_") or re.fullmatch(r"Herramienta\d+", texto)):
        tipo = "LOCATION"
    if tipo:
        salida.append({"start": 0, "end": len(texto), "entity_type": tipo, "score": 0.85})
    return salida


async def _enmascarar(body, *, fmt="anthropic", analizar=_ner):
    tally = policy.MaskingTally()
    cuerpo, mapa = await policy.mask_body(body, analizar, policy.PlaceholderMap(), scope="full", fmt=fmt, tally=tally)
    return cuerpo, mapa, tally


def _plano(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ── (A) vocabulario cerrado ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_el_rol_assistant_no_bloquea_un_chat_de_varios_turnos():
    cuerpo = {"model": "m", "max_tokens": 32, "messages": [
        {"role": "user", "content": "Hola"}, {"role": "assistant", "content": "Hola, ¿en qué te ayudo?"},
        {"role": "user", "content": "Respondé solo: ok"}]}
    original = copy.deepcopy(cuerpo)
    cuerpo, _, tally = await _enmascarar(cuerpo)
    assert tally.unanalyzable == 0 and tally.kinds == [] and tally.detected == tally.masked
    assert [m["role"] for m in cuerpo["messages"]] == ["user", "assistant", "user"]
    assert cuerpo == original


@pytest.mark.asyncio
async def test_a_los_valores_cerrados_del_protocolo_no_se_analizan():
    llamadas = []

    async def _contar(texto):
        llamadas.append(texto)
        return await _ner(texto)

    cuerpo = {
        "model": "m", "thinking": {"type": "enabled", "budget_tokens": 100},
        "tool_choice": {"type": "tool", "name": "buscar"},
        "messages": [
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "buscar", "input": {}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "listo"}]},
                {"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": "texto"}}]}],
        "tools": [{"name": "buscar", "type": "custom", "description": "d", "input_schema": {
            "type": "object", "required": ["q"], "properties": {"q": {"type": "string", "format": "date"}}}}]}
    _, _, tally = await _enmascarar(cuerpo, analizar=_contar)
    assert tally.unanalyzable == 0
    for cerrado in ("assistant", "user", "tool_use", "tool_result", "custom", "enabled", "tool", "text/plain",
                    "object", "string", "date", "properties", "required", "type", "format"):
        assert cerrado not in llamadas, f"{cerrado!r} es vocabulario cerrado del protocolo: no se manda al analizador"


@pytest.mark.asyncio
async def test_a_un_valor_fuera_del_vocabulario_se_sigue_analizando():
    # un rol que no es del protocolo (el cliente lo inventó con un nombre propio) es una posición estructural normal
    cuerpo = {"model": "m", "messages": [{"role": "Juan Pérez", "content": "hola"}]}
    cuerpo, _, tally = await _enmascarar(cuerpo)
    assert cuerpo["messages"][0]["role"] == "Juan Pérez" and tally.kinds == ["structural_entity"]

    con_dni = {"model": "m", "messages": [{"role": DNI, "content": "hola"}]}
    _, _, tally = await _enmascarar(con_dni)
    assert tally.kinds == ["structural_entity"]

    tipo_raro = {"model": "m", "messages": [{"role": "user", "content": [{"type": "text", "text": "x"}]}],
                 "tools": [{"name": "t", "type": "Juan Pérez", "input_schema": {"type": "object"}}]}
    _, _, tally = await _enmascarar(tipo_raro)
    assert tally.kinds == ["structural_entity"]


@pytest.mark.asyncio
async def test_a_vocabulario_cerrado_openai():
    cuerpo = {"model": "gpt", "stream": True, "tool_choice": "auto",
              "response_format": {"type": "json_schema", "json_schema": {"name": "salida", "schema": {"type": "object"}}},
              "messages": [
                  {"role": "system", "content": "sos un asistente"},
                  {"role": "user", "content": "hola"},
                  {"role": "assistant", "content": None, "tool_calls": [
                      {"id": "call_1", "type": "function", "function": {"name": "buscar", "arguments": "{}"}}]},
                  {"role": "tool", "tool_call_id": "call_1", "content": "listo"},
                  {"role": "assistant", "content": "ok"}],
              "tools": [{"type": "function", "function": {"name": "buscar", "parameters": {"type": "object"}}}]}
    original = copy.deepcopy(cuerpo)
    cuerpo, _, tally = await _enmascarar(cuerpo, fmt="openai")
    assert tally.unanalyzable == 0 and cuerpo == original


# ── (B) vocabulario abierto: tipos semánticos ignorados, tipos de patrón bloquean ────────────────

@pytest.mark.asyncio
async def test_b_nombres_ids_y_claves_de_esquema_con_ner_semantico_no_bloquean():
    cuerpo = {"model": "m", "messages": [
        {"role": "assistant", "content": [
            {"type": "text", "text": "leo el archivo"},
            {"type": "tool_use", "id": "toolu_01A09q90qw90lq91780001", "name": "Read", "input": {"file_path": "/x"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_01A09q90qw90lq91780001",
                                      "content": "contenido"}]}],
        "tools": [{"name": "Read", "description": "lee", "input_schema": {
            "type": "object", "required": ["file_path"],
            "properties": {"file_path": {"type": "string", "description": "ruta"}}}}],
        "tool_choice": {"type": "tool", "name": "Read"}}
    cuerpo, _, tally = await _enmascarar(cuerpo)
    assert tally.unanalyzable == 0 and tally.kinds == []
    assert cuerpo["tools"][0]["name"] == "Read" and "file_path" in cuerpo["tools"][0]["input_schema"]["properties"]
    assert cuerpo["messages"][0]["content"][1]["id"] == "toolu_01A09q90qw90lq91780001", "no se reescribe: rompería el pedido"


@pytest.mark.asyncio
async def test_b_openai_nombres_e_ids_con_ner_semantico_no_bloquean():
    cuerpo = {"model": "m", "tool_choice": {"type": "function", "function": {"name": "Read"}},
              "messages": [
                  {"role": "assistant", "content": None, "tool_calls": [
                      {"id": "toolu_01A09q90qw90lq91780001", "type": "function",
                       "function": {"name": "Read", "arguments": "{}"}}]},
                  {"role": "tool", "tool_call_id": "toolu_01A09q90qw90lq91780001", "content": "ok"}],
              "tools": [{"type": "function", "function": {"name": "Read", "parameters": {
                  "type": "object", "required": ["file_path"], "properties": {"file_path": {"type": "string"}}}}}]}
    original = copy.deepcopy(cuerpo)
    cuerpo, _, tally = await _enmascarar(cuerpo, fmt="openai")
    assert tally.unanalyzable == 0 and cuerpo == original


@pytest.mark.asyncio
@pytest.mark.parametrize("dato", [DNI, CUIT, CBU, "juan@ejemplo.com"], ids=["dni", "cuit", "cbu", "email"])
async def test_b_los_tipos_de_patron_siguen_bloqueando_en_cada_posicion_abierta(dato):
    esquema = {"type": "object", "required": [dato], "properties": {dato: {"type": "string"}}}
    anthropic = {
        "id_tool_use": {"model": "m", "messages": [{"role": "assistant", "content": [
            {"type": "tool_use", "id": dato, "name": "buscar", "input": {}}]}]},
        "nombre_tool_use": {"model": "m", "messages": [{"role": "assistant", "content": [
            {"type": "tool_use", "id": "t", "name": dato, "input": {}}]}]},
        "tool_use_id_del_result": {"model": "m", "messages": [{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": dato, "content": "x"}]}]},
        "nombre_de_herramienta": {"model": "m", "messages": [], "tools": [
            {"name": dato, "input_schema": {"type": "object"}}]},
        "tool_choice_name": {"model": "m", "messages": [], "tool_choice": {"type": "tool", "name": dato}},
        "clave_de_properties": {"model": "m", "messages": [], "tools": [{"name": "t", "input_schema": esquema}]},
        "item_de_required": {"model": "m", "messages": [], "tools": [{"name": "t", "input_schema": {
            "type": "object", "required": [dato]}}]},
        "ref": {"model": "m", "messages": [], "tools": [{"name": "t", "input_schema": {
            "type": "object", "properties": {"a": {"$ref": f"#/$defs/{dato}"}}}}]},
    }
    for donde, cuerpo in anthropic.items():
        _, _, tally = await _enmascarar(cuerpo)
        assert tally.kinds == ["structural_entity"], f"anthropic/{donde}: {dato!r} en un identificador debe seguir bloqueando"
    openai = {
        "tool_call_id": {"model": "m", "messages": [{"role": "tool", "tool_call_id": dato, "content": "x"}]},
        "id_de_tool_call": {"model": "m", "messages": [{"role": "assistant", "content": None, "tool_calls": [
            {"id": dato, "type": "function", "function": {"name": "t", "arguments": "{}"}}]}]},
        "function_name": {"model": "m", "messages": [{"role": "assistant", "content": None, "tool_calls": [
            {"id": "c", "type": "function", "function": {"name": dato, "arguments": "{}"}}]}]},
        "tool_choice_function": {"model": "m", "messages": [], "tool_choice": {
            "type": "function", "function": {"name": dato}}},
        "tools_function_name": {"model": "m", "messages": [], "tools": [
            {"type": "function", "function": {"name": dato, "parameters": {"type": "object"}}}]},
        "parameters": {"model": "m", "messages": [], "tools": [
            {"type": "function", "function": {"name": "t", "parameters": esquema}}]},
        "json_schema_name": {"model": "m", "messages": [], "response_format": {
            "type": "json_schema", "json_schema": {"name": dato, "schema": {"type": "object"}}}},
    }
    for donde, cuerpo in openai.items():
        _, _, tally = await _enmascarar(cuerpo, fmt="openai")
        assert tally.kinds == ["structural_entity"], f"openai/{donde}: {dato!r} en un identificador debe seguir bloqueando"


@pytest.mark.asyncio
@pytest.mark.parametrize("dato", ["4111111111111111", "ES9121000418450200051332", "+54 9 11 2345-6789"],
                         ids=["tarjeta", "iban", "telefono"])
async def test_b_tarjeta_iban_y_telefono_en_nombres_y_claves_siguen_bloqueando(dato):
    # los demás tipos de patrón de la decisión del owner (el DNI, el CUIT, el CBU y el email están arriba). Los secretos
    # (`SECRET_PATTERNS`) no son un tipo del analizador sino un detector aparte que no pasa por esta regla: no cambia.
    casos = {
        "anthropic/nombre_de_herramienta": ({"model": "m", "messages": [], "tools": [
            {"name": dato, "input_schema": {"type": "object"}}]}, "anthropic"),
        "anthropic/clave_de_schema": ({"model": "m", "messages": [], "tools": [
            {"name": "t", "input_schema": {"type": "object", "properties": {dato: {"type": "string"}}}}]}, "anthropic"),
        "anthropic/nombre_de_tool_use": ({"model": "m", "messages": [{"role": "assistant", "content": [
            {"type": "tool_use", "id": "t", "name": dato, "input": {}}]}]}, "anthropic"),
        "openai/nombre_de_funcion": ({"model": "m", "messages": [], "tools": [
            {"type": "function", "function": {"name": dato, "parameters": {"type": "object"}}}]}, "openai"),
    }
    for donde, (cuerpo, fmt) in casos.items():
        _, _, tally = await _enmascarar(cuerpo, fmt=fmt)
        assert tally.kinds == ["structural_entity"], f"{donde}: {dato!r} debe seguir bloqueando"


@pytest.mark.asyncio
async def test_b_un_dato_personal_en_un_identificador_con_semantica_tambien_bloquea():
    # el NER marca la cadena entera como PERSON (ignorado) pero el patrón de DNI la marca también: manda el patrón
    async def _ambos(texto):
        salida = await policy.default_analyze(texto, region="latam_ar")
        return salida + [{"start": 0, "end": len(texto), "entity_type": "PERSON", "score": 0.85}]

    cuerpo = {"model": "m", "messages": [], "tools": [{"name": f"leer {DNI}", "input_schema": {"type": "object"}}]}
    _, _, tally = await _enmascarar(cuerpo, analizar=_ambos)
    assert tally.kinds == ["structural_entity"]


@pytest.mark.asyncio
async def test_b_un_tipo_propio_de_la_empresa_o_desconocido_sigue_bloqueando_en_un_identificador():
    # solo los tipos semánticos de una lista CERRADA se ignoran; todo lo demás (incluidos los de la empresa) bloquea
    async def _propio(texto):
        return [{"start": 0, "end": len(texto), "entity_type": "CODIGO_INTERNO", "score": 0.9}] if texto == "Read" else []

    cuerpo = {"model": "m", "messages": [], "tools": [{"name": "Read", "input_schema": {"type": "object"}}]}
    _, _, tally = await _enmascarar(cuerpo, analizar=_propio)
    assert tally.kinds == ["structural_entity"]


@pytest.mark.asyncio
async def test_b_los_tipos_semanticos_solo_se_ignoran_en_identificadores_no_en_otras_posiciones_estructurales():
    # una clave de esquema que NO es palabra clave conocida ni nombre de propiedad (`x-juan`) y un campo desconocido siguen estrictos
    cuerpo = {"model": "m", "messages": [], "tools": [{"name": "t", "input_schema": {"type": "object", "x-juan": 1}}]}
    cuerpo, _, tally = await _enmascarar(cuerpo)
    assert tally.kinds == ["structural_entity"], "una palabra clave de esquema fuera del vocabulario se analiza estricta"

    campo = {"model": "m", "messages": [{"role": "user", "content": "hola"}], "Juan Pérez": 1}
    _, _, tally = await _enmascarar(campo)
    assert tally.kinds == ["structural_entity"], "un campo desconocido de primer nivel: su clave se analiza estricta"


@pytest.mark.asyncio
async def test_b_el_texto_libre_sigue_enmascarando_los_tipos_semanticos():
    cuerpo = {"model": "m", "messages": [
        {"role": "user", "content": "Juan Pérez"},
        {"role": "assistant", "content": [{"type": "text", "text": "Juan Pérez"},
                                          {"type": "tool_use", "id": "t", "name": "buscar", "input": {"q": "Juan Pérez"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "Juan Pérez"}]}],
        "system": "Juan Pérez"}
    cuerpo, mapa, tally = await _enmascarar(cuerpo)
    assert "Juan Pérez" not in _plano(cuerpo), "el texto de mensajes, tool_use.input, tool_result y system se enmascara igual"
    assert tally.unanalyzable == 0 and tally.detected == tally.masked == 5 and mapa


# ── el pedido sintético de Claude Code (60 herramientas, 24 turnos) ──────────────────────────────

def _pedido_tipico_de_claude_code(turnos=24, herramientas=60):
    """El mismo pedido sintético de `sentinel/tests/perf` (60 herramientas, 24 turnos de herramienta, `system` grande)."""
    esquema = {"type": "object", "required": ["file_path"], "properties": {
        "file_path": {"type": "string", "description": "Ruta absoluta del archivo a leer."},
        "offset": {"type": "integer", "description": "Línea desde la que empezar a leer."},
        "limit": {"type": "integer", "description": "Cantidad de líneas a leer."}}}
    mensajes = [{"role": "user", "content": f"Revisá el cliente con DNI {DNI} y arreglá el error de login."}]
    for i in range(turnos):
        mensajes.append({"role": "assistant", "content": [
            {"type": "text", "text": f"Voy a leer el archivo {i}."},
            {"type": "tool_use", "id": f"toolu_{i:04d}", "name": "Read",
             "input": {"file_path": f"/repo/src/modulo_{i}.py", "limit": 200}}]})
        mensajes.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"toolu_{i:04d}", "content": f"# archivo {i}\ndef funcion():\n    return 42\n"}]})
    return {"model": "claude-sonnet-4-5", "max_tokens": 8192, "stream": True,
            "system": [{"type": "text", "text": "Sos Claude Code, la CLI oficial. " * 30, "cache_control": {"type": "ephemeral"}}],
            "messages": mensajes,
            "tools": [{"name": f"Herramienta{i}", "description": f"Herramienta {i}.",
                       "input_schema": {**esquema, "properties": {**esquema["properties"],
                                                                  "file_path": {"type": "string", "description": f"Ruta {i}."}}}}
                      for i in range(herramientas)]}


@pytest.mark.asyncio
async def test_pedido_tipico_de_claude_code_con_ner_real_ya_no_se_bloquea():
    cuerpo = _pedido_tipico_de_claude_code()
    cuerpo, _, tally = await _enmascarar(cuerpo)
    assert tally.unanalyzable == 0 and tally.kinds == [], tally.kinds
    assert tally.detected == tally.masked >= 1
    assert DNI not in _plano(cuerpo), "el DNI del primer mensaje sale enmascarado"


# ── instantánea del contrato (contracts/costuras-base.md §S14 «Vocabulario cerrado y tipos semánticos») ──────────

VOCABULARIO_DEL_CONTRATO = {
    "anthropic": {
        "messages.*.role": ["assistant", "user"],
        "….type": ["document", "image", "redacted_thinking", "search_result", "server_tool_use", "text", "thinking",
                   "tool_result", "tool_use", "web_search_result", "web_search_tool_result"],
        "….source.type": ["base64", "content", "file", "text", "url"],
        "….source.media_type": "re:[a-z]+/[a-z0-9][a-z0-9.+-]{0,99}",
        "thinking.type": ["adaptive", "disabled", "enabled"],
        "tool_choice.type": ["any", "auto", "none", "tool"],
        "tools.*.type": "re:(custom|[a-z][a-z0-9_]*_\\d{8})",
    },
    "openai": {
        "messages.*.role": ["assistant", "developer", "function", "system", "tool", "user"],
        "messages.*.tool_calls.*.type": ["function"],
        "….type": ["file", "image_url", "input_audio", "refusal", "text"],
        "response_format.type": ["json_object", "json_schema", "text"],
        "tool_choice": ["auto", "none", "required"],
        "tool_choice.type": ["allowed_tools", "custom", "function"],
        "tools.*.type": ["custom", "function"],
    },
}
IDENTIFICADORES_DEL_CONTRATO = {
    "anthropic": ["tool_choice.name", "….id@tool_use", "….name@tool_use", "….tool_use_id@tool_result", "tools.*.name"],
    "openai": ["messages.*.tool_call_id", "messages.*.tool_calls.*.id", "messages.*.tool_calls.*.function.name",
               "tool_choice.function.name", "tools.*.function.name", "response_format.json_schema.name"],
}
TIPOS_SEMANTICOS_DEL_CONTRATO = ["DATE_TIME", "LOCATION", "NRP", "ORGANIZATION", "PERSON", "URL"]


def _normal(vocab):
    return sorted(vocab) if isinstance(vocab, frozenset) else "re:" + vocab.pattern


def test_g_las_tablas_de_vocabulario_son_las_del_contrato():
    assert {f: {r: _normal(v) for r, v in t.items()} for f, t in policy.S14_CLOSED_VOCABULARY.items()} \
        == VOCABULARIO_DEL_CONTRATO, "agregar o quitar un valor cerrado es un cambio de contrato (§S14) con test"
    assert {f: sorted(v) for f, v in policy.S14_OPEN_IDENTIFIERS.items()} \
        == {f: sorted(v) for f, v in IDENTIFICADORES_DEL_CONTRATO.items()}
    assert sorted(policy.STRUCTURAL_IGNORED_ENTITY_TYPES) == TIPOS_SEMANTICOS_DEL_CONTRATO


def test_g_cada_posicion_de_vocabulario_es_una_posicion_estructural_de_la_tabla():
    """Una posición con vocabulario cerrado o de identificador tiene que existir como `structural` en la tabla S14: si no,
    la regla nueva no se aplicaría nunca (y un cambio de nombre en una de las dos tablas lo dejaría mudo)."""
    for fmt in ("anthropic", "openai"):
        estructurales = {r.partition("@")[0] for r in policy.S14_EXEMPT_POSITIONS[fmt]["structural"]}
        propuestas = set(policy.S14_CLOSED_VOCABULARY[fmt]) | {r.partition("@")[0] for r in policy.S14_OPEN_IDENTIFIERS[fmt]}
        assert propuestas <= estructurales, sorted(propuestas - estructurales)


@pytest.mark.asyncio
async def test_h_el_prefetch_no_pide_al_analizador_lo_que_el_recorrido_no_analiza():
    cuerpo = {"model": "m", "messages": [{"role": "user", "content": "hola"}, {"role": "assistant", "content": "ok"}]}
    textos = policy._collect_texts(cuerpo, "anthropic", with_scans=True)
    assert "assistant" not in textos and "user" not in textos and "hola" in textos
    rol_raro = {"model": "m", "messages": [{"role": "Juan Pérez", "content": "hola"}]}
    assert "Juan Pérez" in policy._collect_texts(rol_raro, "anthropic", with_scans=True)
