"""Desenmascarado TOLERANTE acotado a las etiquetas activas del pedido (segunda pasada de ``unmask_text``).

Hueco real (verificación de clientes, 21-oct-2026): los modelos chicos alteran la etiqueta ``[TIPO_idx_nonce]`` al copiarla
dentro de argumentos de herramienta —sin corchetes (``DNI_0_b1c0``) o con un entero de más (``[PERSON_4_0_0a81]``)— y la
coincidencia EXACTA no la restituye: el cliente ejecuta la herramienta con el marcador en vez del dato.

Contrato:

- La segunda pasada corre SOLO si la exacta dejó algo (el nonce de una etiqueta activa sigue en el texto) y SOLO con las
  claves de ``ph_to_orig`` ACTIVAS: exige tipo, índice y nonce EXACTOS. Tolera corchetes ausentes o ``<>``, un entero extra
  tras el índice y mayúsculas/minúsculas.
- JAMÁS distancia de edición: todas las etiquetas de un pedido comparten nonce y ``[PERSON_1_0a81]`` / ``[PERSON_4_0a81]``
  quedan a distancia 1 — cruzaría datos de dos personas.
- Lo que no se altera sale idéntico, byte a byte, a como salía antes.
"""
import json
import random
import time

import pytest

import s14_helpers as h  # noqa: F401  (doble de litellm)
from extensions import sentinel_guardian_policy as policy  # noqa: E402

NONCE = "0a81"
MAPA = {
    f"[PERSON_4_{NONCE}]": "Juan Ejemplo Prueba",
    f"[PERSON_1_{NONCE}]": "Ana Sintética",
    f"[DNI_0_{NONCE}]": "12345678",
    f"[EMAIL_ADDRESS_0_{NONCE}]": "prueba.sintetica@example.com",
}


def antes(text: str, ph_to_orig: dict) -> str:
    """El desenmascarado de siempre (exacto), para afirmar que lo no alterado no cambia."""
    for ph, orig in ph_to_orig.items():
        if ph in text:
            text = text.replace(ph, orig)
    return text


# ── Los fallos reales de 31-cierre-real.md §3.2 (sintéticos) ───────────────────────────────────────

REALES = [
    # (etiqueta activa, lo que el modelo escribió, dato original)
    ("[DNI_0_b1c0]", 'DNI_0_b1c0', "12345678"),                      # 25 §6.2 (genérica, curl)
    ("[DNI_0_14dc]", 'DNI_0_14dc', "12345678"),                      # 25 §6.2
    ("[DNI_0_2311]", 'DNI_0_2311', "12345678"),                      # 25 §6.2
    ("[DNI_0_de39]", 'DNI_0_de39', "12345678"),                      # 25 §6.2 (cara Claude)
    ("[EMAIL_ADDRESS_0_8f1c]", 'EMAIL_ADDRESS_0_8f1c', "prueba.sintetica@example.com"),
    ("[PERSON_4_0a81]", '[PERSON_4_0_0a81]', "Juan Ejemplo Prueba"),  # 27 §3.4 (dsh, streaming): índice espurio
]


@pytest.mark.parametrize("ph,alterado,original", REALES)
def test_los_fallos_reales_recuperan_el_dato_original(ph, alterado, original):
    mapa = {ph: original}
    assert policy.unmask_text(alterado, mapa) == original
    args = json.dumps({"dni": alterado, "otro": "x"})
    assert json.loads(policy.unmask_text(args, mapa)) == {"dni": original, "otro": "x"}
    sql = f"SELECT * FROM clientes WHERE dato = '{alterado}' LIMIT 1"
    assert policy.unmask_text(sql, mapa) == f"SELECT * FROM clientes WHERE dato = '{original}' LIMIT 1"


# ── Variantes que se toleran ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("alterado", [
    "DNI_0_0a81", "dni_0_0a81", "Dni_0_0A81", "[dni_0_0a81]", "[DNI_0_0A81]", "<DNI_0_0a81>", "<DNI_0_0a81]",
    "[DNI_0_0a81>", "[DNI_0_7_0a81]", "DNI_0_12_0a81", "[dni_0_0_0A81]",
])
def test_variantes_toleradas(alterado):
    assert policy.unmask_text(f"dni={alterado};", MAPA) == "dni=12345678;"


@pytest.mark.parametrize("alterado", [
    "[DNI_0_0a81", "DNI_0_0a81]", "<DNI_0_0a81", "DNI_0_0a81>", "[DNI_0_0a81, PERSON_4_0a81]", "[PERSON_1_0a81",
])
def test_un_corchete_suelto_no_se_interpreta_y_la_etiqueta_queda_como_llego(alterado):
    # Un stream truncado (`Hola [PERSON_1_66a5`) o el `[...]` de una lista de código: sin pareja, no se toca.
    assert policy.unmask_text(alterado, MAPA) == alterado


def test_tipo_con_guion_bajo_y_mayusculas():
    assert policy.unmask_text("correo: email_address_0_0A81.", MAPA) == "correo: prueba.sintetica@example.com."
    assert policy.unmask_text("<EMAIL_ADDRESS_0_0a81>", MAPA) == "prueba.sintetica@example.com"


def test_dos_entidades_del_mismo_tipo_cada_una_con_su_dato():
    texto = "de PERSON_1_0a81 para [PERSON_4_0_0a81], y otra vez <person_1_0a81>"
    assert policy.unmask_text(texto, MAPA) == "de Ana Sintética para Juan Ejemplo Prueba, y otra vez Ana Sintética"


def test_mezcla_de_exactas_y_alteradas():
    texto = "[PERSON_4_0a81] tiene DNI_0_0a81 y mail [EMAIL_ADDRESS_0_0a81]; ver [DNI_0_0a81]"
    assert policy.unmask_text(texto, MAPA) == (
        "Juan Ejemplo Prueba tiene 12345678 y mail prueba.sintetica@example.com; ver 12345678")


# ── Negativos: jamás cruzar datos ni restituir etiquetas ajenas ──────────────────────────────────

SOLO_P4 = {f"[PERSON_4_{NONCE}]": "Juan Ejemplo Prueba"}


@pytest.mark.parametrize("texto", [
    f"[PERSON_1_{NONCE}]", f"PERSON_1_{NONCE}", f"[PERSON_1_0_{NONCE}]",         # otro ÍNDICE (distancia 1 con el activo)
    "[PERSON_4_ffff]", "PERSON_4_ffff", "[PERSON_4_0_ffff]",                       # otro NONCE (otro pedido)
    f"[DNI_4_{NONCE}]", f"DNI_4_{NONCE}",                                            # otro TIPO
    f"[PERSON_40_{NONCE}]", f"PERSON_40_{NONCE}", f"[PERSON_14_{NONCE}]",          # índice que contiene al activo
    f"PERSON_4_{NONCE}x", f"xPERSON_4_{NONCE}", f"_PERSON_4_{NONCE}", f"PERSON_4_{NONCE}_",   # pegada a otra palabra
    f"MYPERSON_4_{NONCE}", f"PERSON_4_{NONCE}a", f"PERSON_4_{NONCE}1",
    f"PERSON_4__{NONCE}", f"PERSON_4_x_{NONCE}", f"PERSON_4{NONCE}", f"PERSON4_{NONCE}",   # gramática rota
])
def test_negativos_no_se_restituye_lo_que_no_es_la_etiqueta_activa(texto):
    assert policy.unmask_text(f"a {texto} b", SOLO_P4) == f"a {texto} b"


def test_negativo_explicito_persona_1_frente_a_persona_4_no_se_cruzan():
    # El mapa tiene SOLO la persona 4; el modelo escribió la 1 (otro dato) sin corchetes: queda tal cual (y se detecta).
    assert policy.unmask_text("PERSON_1_0a81 y PERSON_4_0a81", SOLO_P4) == "PERSON_1_0a81 y Juan Ejemplo Prueba"


def test_negativo_nonce_de_otro_pedido():
    otro_pedido = "[DNI_0_beef]"
    assert policy.unmask_text(f"dni DNI_0_beef y {otro_pedido}", MAPA) == f"dni DNI_0_beef y {otro_pedido}"


def test_mapa_vacio_o_sin_etiquetas_activas_no_cambia_nada():
    assert policy.unmask_text("DNI_0_0a81 [PERSON_4_0a81]", {}) == "DNI_0_0a81 [PERSON_4_0a81]"


# ── Valor original con caracteres especiales (el reemplazo NO interpreta \1, \g<0>, $1, \u…) ──────────

ESPECIALES = ["a\\1b", "$1 y ${x}", "\\g<0>", "\\u00e9\\n\\\\", "c:\\Users\\yo", "(.*)\\0", "%s {0} {nombre}"]


@pytest.mark.parametrize("orig", ESPECIALES)
def test_valor_original_con_caracteres_especiales_se_inserta_literal(orig):
    mapa = {f"[DNI_0_{NONCE}]": orig}
    assert policy.unmask_text("x DNI_0_0a81 y [DNI_0_7_0A81] z", mapa) == f"x {orig} y {orig} z"
    assert policy.unmask_text("[DNI_0_0a81]", mapa) == orig                      # la exacta, igual que antes


# ── Estructuras anidadas: valores, claves y tool_use.input ────────────────────────────────────────

def test_unmask_deep_json_anidado_y_claves():
    entrada = {
        "cliente": {"dni": "DNI_0_0a81", "nombres": ["PERSON_4_0a81", "[PERSON_1_0_0a81]"]},
        "PERSON_4_0a81": {"nota": "ver <EMAIL_ADDRESS_0_0a81>"},
        "[DNI_0_0a81]": 1,
        "n": 3, "ok": True, "vacio": None,
    }
    salida = policy.unmask_deep(entrada, MAPA)
    assert salida == {
        "cliente": {"dni": "12345678", "nombres": ["Juan Ejemplo Prueba", "Ana Sintética"]},
        "Juan Ejemplo Prueba": {"nota": "ver prueba.sintetica@example.com"},
        "12345678": 1,
        "n": 3, "ok": True, "vacio": None,
    }


def test_respuesta_anthropic_tool_use_input_alterado():
    resp = {"content": [
        {"type": "text", "text": "Busco a PERSON_4_0a81."},
        {"type": "tool_use", "id": "t1", "name": "buscar", "input": {"dni": "DNI_0_0a81", "q": "x [PERSON_4_0_0a81]"}},
    ]}
    policy.unmask_response_payload(resp, MAPA)
    assert resp["content"][0]["text"] == "Busco a Juan Ejemplo Prueba."
    assert resp["content"][1]["input"] == {"dni": "12345678", "q": "x Juan Ejemplo Prueba"}


def test_respuesta_openai_no_streaming_tool_calls_y_texto():
    resp = {"choices": [{"message": {
        "content": "ficha de [person_1_0a81]",
        "tool_calls": [{"id": "c1", "type": "function",
                        "function": {"name": "guardar_ficha",
                                     "arguments": '{"dni": "DNI_0_0a81", "email": "EMAIL_ADDRESS_0_0a81"}'}}]}}]}
    policy.unmask_response_payload(resp, MAPA)
    msg = resp["choices"][0]["message"]
    assert msg["content"] == "ficha de Ana Sintética"
    assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {
        "dni": "12345678", "email": "prueba.sintetica@example.com"}


# ── Lo NO alterado no cambia (byte a byte) ────────────────────────────────────────────────────────

FRAGMENTOS = [
    "Hola, ", "esto es prosa normal. ", "x = arr[i] + nums[0]; ", "def f_0_abcd(): pass\n", "cliente_id_0_1234 ", "DNI_0_ffff ",
    "[PERSON_1_beef] ", "PERSON_9_0a82 ", "[DNI_0_0a81] ", "[PERSON_4_0a81], ", "[EMAIL_ADDRESS_0_0a81]\n", "\\n \\u00e9 $1 ",
    "http://x.y/z_1_0b2c ", "[1, 2, 3] ", "{\"k\": \"v\"} ", "TIPO_n_xxxx ", "[PERSON_0_a1b2] ",
]


def test_lo_no_alterado_sale_identico_a_como_salia():
    rnd = random.Random(2610)
    for _ in range(400):
        texto = "".join(rnd.choice(FRAGMENTOS) for _ in range(rnd.randint(0, 25)))
        assert policy.unmask_text(texto, MAPA) == antes(texto, MAPA), texto


def test_sin_etiquetas_ni_nonce_no_se_corre_la_segunda_pasada(monkeypatch):
    llamadas = []
    original = policy._tolerant_pattern
    monkeypatch.setattr(policy, "_tolerant_pattern", lambda *a, **k: (llamadas.append(a), original(*a, **k))[1])
    policy.unmask_text("Hola mundo, sin nada raro. DNI_0_ffff", MAPA)
    policy.unmask_text("[PERSON_4_0a81] y [DNI_0_0a81], todo exacto", MAPA)
    assert llamadas == []
    policy.unmask_text("DNI_0_0a81", MAPA)
    assert llamadas != []


def test_texto_vacio_y_no_cadena():
    assert policy.unmask_text("", MAPA) == ""
    assert policy.unmask_deep(None, MAPA) is None and policy.unmask_deep(5, MAPA) == 5


# ── Streaming: la etiqueta partida entre deltas, con y sin corchete ───────────────────────────────

def _cortes(texto: str, partes: int):
    """Todas las formas de partir ``texto`` en ``partes`` deltas no vacías (exhaustivo para 2; por muestreo para más)."""
    n = len(texto)
    if partes == 2:
        for i in range(1, n):
            yield [texto[:i], texto[i:]]
    elif partes == 3:
        rnd = random.Random(7)
        for _ in range(250):
            i, j = sorted(rnd.sample(range(1, n), 2))
            yield [texto[:i], texto[i:j], texto[j:]]
    else:
        yield [c for c in texto]


def _chunk(content=None, args=None, finish=None):
    tc = None if args is None else [{"index": 0, "id": "c1", "type": "function",
                                     "function": {"name": "guardar_ficha", "arguments": args}}]
    return {"choices": [{"index": 0, "finish_reason": finish, "delta": {"content": content, "tool_calls": tc}}]}


def _emitido(deltas, mapa, campo="content"):
    carries, salida, ultimo = {}, "", None
    for i, d in enumerate(deltas):
        ultimo = _chunk(content=d) if campo == "content" else _chunk(args=d)
        out = policy.unmask_openai_chunk(ultimo, carries, mapa)
        salida += _extraer(out, campo)
    fin = _chunk(None, finish="stop")
    salida += _extraer(policy.unmask_openai_chunk(fin, carries, mapa), campo)
    volcado = policy.flush_openai_carries(ultimo, carries, mapa)
    if volcado is not None:
        salida += _extraer(volcado, campo)
    assert carries == {}
    return salida


def _extraer(chunk, campo):
    delta = chunk["choices"][0]["delta"]
    if campo == "content":
        return delta.get("content") or ""
    return "".join((tc["function"].get("arguments") or "") for tc in delta.get("tool_calls") or [])


TEXTOS_STREAM = [
    ("Ficha de PERSON_4_0a81 con DNI_0_0a81 listo.", "Ficha de Juan Ejemplo Prueba con 12345678 listo."),
    ("Ficha de [PERSON_4_0_0a81], mail <EMAIL_ADDRESS_0_0a81>.", "Ficha de Juan Ejemplo Prueba, mail prueba.sintetica@example.com."),
    ("dni=dni_0_0A81!", "dni=12345678!"),
    ("DNI_0_0a81", "12345678"),                                       # la etiqueta es TODO el texto
    ("[DNI_0_0a81] y DNI_0_0a81", "12345678 y 12345678"),
    ("Sin nada protegido: person_9_0a81 queda.", "Sin nada protegido: person_9_0a81 queda."),
]


@pytest.mark.parametrize("partes", [2, 3, 0])
@pytest.mark.parametrize("texto,esperado", TEXTOS_STREAM)
def test_streaming_texto_con_la_etiqueta_partida_en_cualquier_lado(texto, esperado, partes):
    for deltas in _cortes(texto, partes):
        assert _emitido(deltas, MAPA) == esperado, deltas


def test_streaming_argumentos_json_con_valor_escapado():
    # Los `arguments` de un tool call son JSON: el original se restituye ESCAPADO como contenido de cadena.
    mapa = {f"[PERSON_4_{NONCE}]": 'Juan "El Zurdo" Pérez\\n', f"[DNI_0_{NONCE}]": "12345678"}
    for alterado in ("PERSON_4_0a81", "[PERSON_4_0_0a81]", "<person_4_0A81>"):
        args = json.dumps({"nombre": "@@", "dni": "DNI_0_0a81"}, ensure_ascii=False).replace("@@", alterado)
        for partes in (2, 3, 0):
            for deltas in _cortes(args, partes):
                bruto = _emitido(deltas, mapa, campo="args")
                assert json.loads(bruto) == {"nombre": 'Juan "El Zurdo" Pérez\\n', "dni": "12345678"}, deltas


def test_streaming_argumentos_el_dato_con_caracteres_especiales_va_literal():
    mapa = {f"[DNI_0_{NONCE}]": "a\\1 $1 \\g<0>"}
    args = '{"dni": "DNI_0_0a81"}'
    for deltas in _cortes(args, 2):
        assert json.loads(_emitido(deltas, mapa, campo="args")) == {"dni": "a\\1 $1 \\g<0>"}


def test_streaming_anthropic_input_json_delta_con_la_etiqueta_partida():
    parcial = '{"dni": "DNI_0_0a81", "q": "x [PERSON_4_0_0a81]"}'
    for deltas in list(_cortes(parcial, 2)) + list(_cortes(parcial, 0)):
        carry, campo, salida = "", None, ""
        eventos = [{"type": "content_block_delta", "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": d}} for d in deltas]
        eventos.append({"type": "content_block_stop", "index": 0})
        for ev in eventos:
            out, carry, campo = policy.unmask_delta_event(ev, carry, campo, MAPA)
            for e in out:
                salida += (e.get("delta") or {}).get("partial_json", "")
        assert salida == '{"dni": "12345678", "q": "x Juan Ejemplo Prueba"}', deltas


def test_streaming_anthropic_texto_via_bloques_sse():
    texto = "Ficha: PERSON_4_0a81 / DNI_0_0a81 / [EMAIL_ADDRESS_0_0_0a81]."
    for deltas in list(_cortes(texto, 2)) + list(_cortes(texto, 0)):
        carry, campo, salida = "", None, ""
        bloques = [f'event: content_block_delta\ndata: {json.dumps({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": d}})}'
                   for d in deltas]
        bloques.append('event: content_block_stop\ndata: {"type": "content_block_stop", "index": 0}')
        for b in bloques:
            out, carry, campo, _, _ = policy.rewrite_sse_block(b, carry, campo, MAPA)
            for ob in out:
                for linea in ob.split("\n"):
                    if linea.startswith("data:"):
                        salida += json.loads(linea[5:]).get("delta", {}).get("text", "")
        assert salida == "Ficha: Juan Ejemplo Prueba / 12345678 / prueba.sintetica@example.com.", deltas


# ── safe_split: retiene también la cola SIN corchete que todavía puede ser una etiqueta activa ──────

def test_safe_split_sin_mapa_es_el_de_siempre():
    assert policy.safe_split("hola [PERSON_0_ab") == ("hola ", "[PERSON_0_ab")
    assert policy.safe_split("hola DNI_0_0a") == ("hola DNI_0_0a", "")        # sin mapa no hay cola sin corchete
    assert policy.safe_split("arr[i, [1,2") == ("arr[i, [1,2", "")
    assert policy.safe_split("x [") == ("x ", "[")


@pytest.mark.parametrize("cola", [
    "P", "PER", "PERSON", "PERSON_", "PERSON_4", "PERSON_4_", "PERSON_4_0", "PERSON_4_0a", "PERSON_4_0a8",   # prefijos
    "PERSON_4_0_", "PERSON_4_0_0", "PERSON_4_12_0a",                                                          # entero extra
    "person_4_0A8", "<PERSON_4_0a8", "<", "<DN", "[person_4_0a", "D", "DNI_0_", "EMAIL_ADDRESS_0_0a81",
])
def test_safe_split_retiene_el_prefijo_viable_de_una_etiqueta_activa(cola):
    assert policy.safe_split("el dato es " + cola, MAPA) == ("el dato es ", cola)


@pytest.mark.parametrize("texto", [
    "Hola mundo cómo estás", "persona nueva", "el cliente", "valor DNI_9_", "x PERSON_4_ffff", "y PERSON_5_0a81 ",
    "z DNI_0_0a81 ", "a PERSON_4_0a81x", "listo.", "arr[i, [1,2", "fin ", "", "texto con_guion_bajo_pero_largo_que_no_es_una_etiqueta_activa_ni_cerca",
    "x" * 60,
])
def test_safe_split_no_frena_la_prosa_normal(texto):
    assert policy.safe_split(texto, MAPA) == (texto, "")


def test_safe_split_la_cola_sin_corchete_nunca_supera_max_carry():
    for n in range(1, 120):
        seguro, cola = policy.safe_split("ok " + "PERSON_4_0a8"[:12] * 1 + "_" * n, MAPA)
        assert len(cola) <= policy.MAX_CARRY and seguro + cola == "ok " + "PERSON_4_0a8" + "_" * n


# ── Costo: textos de 300.000 caracteres ──────────────────────────────────────────────────────────

def _texto_grande(n=300_000):
    base = ("El cliente_id_0_1234 pidió revisar la función get_user_by_id_9_beef con sus parámetros "
            "[uno, dos] y {\"k\": \"v\"}; ver PERSON_9_0a82 y TIPO_n_xxxx. ")
    return (base * (n // len(base) + 1))[:n]


def test_costo_300k_sin_marcadores_activos():
    mapa = {f"[PERSON_{i}_{NONCE}]": f"Persona {i}" for i in range(120)}
    texto = _texto_grande()
    t0 = time.perf_counter()
    igual = policy.unmask_text(texto, mapa) == texto
    dt = time.perf_counter() - t0
    assert igual and dt < 1.5, dt


def test_costo_300k_con_marcadores_alterados_y_120_claves():
    mapa = {f"[PERSON_{i}_{NONCE}]": f"Persona {i}" for i in range(120)}
    texto = _texto_grande()
    trozos = [texto[i:i + 5000] + f" PERSON_{i // 5000 % 120}_0a81 y [PERSON_7_0_0a81] " for i in range(0, len(texto), 5000)]
    texto = "".join(trozos)
    t0 = time.perf_counter()
    salida = policy.unmask_text(texto, mapa)
    dt = time.perf_counter() - t0
    restos = "_0a81" in salida.replace("PERSON_9_0a82", "")      # (variables booleanas: un fallo no imprime 300 k caracteres)
    restituido = "Persona 7" in salida
    assert dt < 1.5, dt
    assert not restos and restituido


def test_costo_300k_patologico_sin_backtracking_catastrofico():
    mapa = {f"[PERSON_4_{NONCE}]": "X", f"[EMAIL_ADDRESS_0_{NONCE}]": "Y"}
    for patologico in ("a_" * 150_000, "A" * 300_000, "PERSON_" * 43_000, "_" * 300_000, "PERSON_4_" * 33_000,
                       "EMAIL_ADDRESS_0_" * 18_000 + NONCE, ("PERSON_4_0" + "_0" * 40) * 5_000, "[" * 300_000, "<" * 300_000):
        t0 = time.perf_counter()
        policy.unmask_text(patologico + " " + NONCE, mapa)
        dt = time.perf_counter() - t0
        assert dt < 2.0, (patologico[:20], dt)
