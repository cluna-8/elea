"""S14 — imágenes bajo el enmascarado forzado: ajuste `MASKING_IMAGES=pass|filter` (057 R43; contracts/costuras-base.md §S14).

Una imagen no se puede analizar (no hay motor de reconocimiento de texto). Hasta R43 bajo el forzado la imagen que adjunta la
persona bloqueaba el pedido y la que devuelve una herramienta se reemplazaba por una nota (R39). La instalación elige:

* `pass` (DEFAULT de Eleia): las imágenes —adjuntas y dentro de un `tool_result`— salen tal cual al destino. No cuentan como no
  analizables, no bloquean y no se reemplazan; se auditan como `images_unmasked` (conteo y tipo, jamás contenido). El TEXTO sigue
  enmascarándose completo y el resto de los binarios (audio, documentos no extraíbles) sigue como antes.
* `filter`: el comportamiento de R39 (la adjunta bloquea, la de la herramienta se cambia por una nota).

Un valor desconocido se trata como `filter` (ante la duda, el piso más alto). El pedido no puede cambiar el ajuste.
"""
import json

import pytest

import s14_helpers as h
from s14_helpers import DNI, policy  # noqa: E402
from extensions import sentinel_guardrail  # noqa: E402

VAR = "MASKING_IMAGES"
DATO = "QUJDREVGRw=="


def png():
    """Una instancia nueva por uso: el recorrido puede mutar el bloque EN EL LUGAR."""
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": DATO}}


def imagen_openai():
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{DATO}"}}


@pytest.fixture(autouse=True)
def _entorno(monkeypatch):
    monkeypatch.delenv(VAR, raising=False)
    policy.clear_forced_masking_resolvers()

    async def _nada(*_a, **_k):
        return None

    monkeypatch.setattr(sentinel_guardrail, "_auditar_bloqueo", _nada)
    monkeypatch.setattr(sentinel_guardrail, "_marcar_nlp_degradado", _nada)
    monkeypatch.setattr(sentinel_guardrail, "_PRESIDIO_URL", None)
    yield
    policy.clear_forced_masking_resolvers()


async def _enmascarar(body, *, fmt="anthropic", **kw):
    tally = policy.MaskingTally()
    cuerpo, mapa = await policy.mask_body(
        body, h.analizador("latam_ar"), policy.PlaceholderMap(), scope="full", fmt=fmt, tally=tally, **kw)
    return cuerpo, mapa, tally


def _con_tool_result(*contenido, resto=()):
    return {"model": "m", "messages": [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "screenshot", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": list(contenido)}, *resto]},
    ]}


def _resultado(cuerpo):
    return cuerpo["messages"][1]["content"][0]["content"]


# ── 1. El ajuste: default pass, filter, valor desconocido ⇒ filter ────────────────────────

def test_sin_variable_el_default_es_pass():
    assert policy.images_mode() == "pass"


@pytest.mark.parametrize("valor,esperado", [
    ("pass", "pass"), ("PASS", "pass"), (" pass ", "pass"), ("", "pass"),
    ("filter", "filter"), ("Filter", "filter"),
    ("block", "filter"), ("0", "filter"), ("true", "filter"), ("passs", "filter"),
])
def test_valores_de_la_variable(monkeypatch, valor, esperado):
    monkeypatch.setenv(VAR, valor)
    assert policy.images_mode() == esperado


# ── 2. pass: la imagen sale tal cual, no bloquea, no se reemplaza, se cuenta ──────────────

@pytest.mark.asyncio
async def test_pass_la_imagen_adjunta_sale_tal_cual_y_no_es_no_analizable():
    cuerpo, _, tally = await _enmascarar({"model": "m", "messages": [{"role": "user", "content": [png()]}]})
    assert cuerpo["messages"][0]["content"] == [png()], "el bloque no se toca"
    assert tally.unanalyzable == 0 and tally.kinds == []
    assert tally.unanalyzable_replaced == 0
    assert tally.images_unmasked == 1 and tally.unmasked_image_kinds == ["image"]


@pytest.mark.asyncio
async def test_pass_la_imagen_de_un_tool_result_no_se_reemplaza():
    cuerpo, _, tally = await _enmascarar(_con_tool_result(png()))
    assert _resultado(cuerpo) == [png()], "ni nota ni bloque vacío: la captura viaja"
    assert tally.unanalyzable == 0 and tally.unanalyzable_replaced == 0
    assert tally.images_unmasked == 1 and tally.unmasked_image_kinds == ["image"]


@pytest.mark.asyncio
async def test_pass_cuenta_cada_imagen_adjunta_y_de_herramienta():
    cuerpo, _, tally = await _enmascarar(_con_tool_result(png(), png(), resto=[png()]))
    assert tally.images_unmasked == 3 and tally.unanalyzable == 0


@pytest.mark.asyncio
async def test_pass_la_marca_de_cache_se_conserva_porque_el_bloque_no_cambia():
    imagen = {**png(), "cache_control": {"type": "ephemeral"}}
    cuerpo, _, _ = await _enmascarar(_con_tool_result(imagen))
    assert _resultado(cuerpo) == [{**png(), "cache_control": {"type": "ephemeral"}}]


@pytest.mark.asyncio
async def test_pass_el_texto_vecino_se_sigue_enmascarando_completo():
    cuerpo, mapa, tally = await _enmascarar(_con_tool_result(
        {"type": "text", "text": f"DNI {DNI}"}, png(), resto=[{"type": "text", "text": f"y también {DNI}"}]))
    assert DNI not in json.dumps(cuerpo, ensure_ascii=False) and DNI in mapa.values()
    assert tally.masked == tally.detected >= 1 and tally.unanalyzable == 0
    assert _resultado(cuerpo)[1] == png()


@pytest.mark.asyncio
async def test_pass_openai_image_url_del_usuario_y_de_una_herramienta():
    cuerpo = {"model": "m", "messages": [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "shot", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": [imagen_openai()]},
        {"role": "user", "content": [imagen_openai()]},
    ]}
    cuerpo, _, tally = await _enmascarar(cuerpo, fmt="openai")
    assert cuerpo["messages"][1]["content"] == [imagen_openai()]
    assert cuerpo["messages"][2]["content"] == [imagen_openai()]
    assert tally.unanalyzable == 0 and tally.unanalyzable_replaced == 0 and tally.images_unmasked == 2


@pytest.mark.asyncio
async def test_pass_el_resto_de_los_binarios_sigue_como_hoy():
    """Audio y documentos no extraíbles: la adjunta bloquea y la de la herramienta se reemplaza, como en R39."""
    url = {"type": "document", "source": {"type": "url", "url": "https://x.example/a.pdf"}}
    cuerpo, _, tally = await _enmascarar(_con_tool_result(url, resto=[
        {"type": "document", "source": {"type": "url", "url": "https://x.example/b.pdf"}}]))
    assert tally.unanalyzable == 1 and tally.kinds == ["document_url"]
    assert tally.unanalyzable_replaced == 1 and tally.replaced_kinds == ["document_url"]
    assert tally.images_unmasked == 0

    audio = {"model": "m", "messages": [{"role": "user", "content": [
        {"type": "input_audio", "input_audio": {"data": DATO, "format": "wav"}}]}]}
    _, _, tally = await _enmascarar(audio, fmt="openai")
    assert tally.unanalyzable == 1 and tally.kinds == ["audio"] and tally.images_unmasked == 0


@pytest.mark.asyncio
async def test_pass_no_aflojar_lo_demas_que_bloquea():
    desconocido = {"type": "tipo_que_no_existe", "payload": "x"}
    _, _, tally = await _enmascarar(_con_tool_result(desconocido, png()))
    assert tally.unanalyzable == 1 and tally.kinds == ["unknown_block"] and tally.images_unmasked == 1


# ── 3. filter: el comportamiento de R39 ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_filter_la_adjunta_bloquea_y_la_de_la_herramienta_se_reemplaza(monkeypatch):
    monkeypatch.setenv(VAR, "filter")
    cuerpo, _, tally = await _enmascarar(_con_tool_result(png(), resto=[png()]))
    assert _resultado(cuerpo) == [{"type": "text", "text": policy.UNANALYZABLE_REPLACED_NOTE}]
    assert tally.unanalyzable == 1 and tally.kinds == ["image"]
    assert tally.unanalyzable_replaced == 1 and tally.images_unmasked == 0
    assert DATO not in json.dumps(_resultado(cuerpo))


@pytest.mark.asyncio
async def test_un_valor_desconocido_se_trata_como_filter(monkeypatch):
    monkeypatch.setenv(VAR, "quizas")
    _, _, tally = await _enmascarar({"model": "m", "messages": [{"role": "user", "content": [png()]}]})
    assert tally.unanalyzable == 1 and tally.images_unmasked == 0


@pytest.mark.asyncio
async def test_el_parametro_explicito_gana_sobre_el_entorno(monkeypatch):
    monkeypatch.setenv(VAR, "filter")
    _, _, tally = await _enmascarar(_con_tool_result(png()), images="pass")
    assert tally.unanalyzable == 0 and tally.images_unmasked == 1


# ── 4. Informe del guardrail ──────────────────────────────────────────────────────────────

class _Identidad:
    def __init__(self, **sentinel):
        self.metadata = {"sentinel": {"region": "latam_ar", **sentinel}}


async def _hook(data, *, senal=True, call_type="anthropic_messages"):
    home = sentinel_guardrail._metadata_home(data, call_type)
    if senal:
        policy.mark_forced_masking(home)
    return await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(
        _Identidad(), None, data, call_type)


@pytest.mark.asyncio
async def test_el_informe_cuenta_las_imagenes_sin_enmascarar_y_no_lleva_contenido():
    data = _con_tool_result({"type": "text", "text": f"DNI {DNI}"}, png(), resto=[png()])
    await _hook(data)
    informe = data["litellm_metadata"]["masking_report"]
    assert informe["unanalyzable"] == 0 and informe["unanalyzable_kinds"] == []
    assert informe["images_unmasked"] == 2 and informe["images_unmasked_kinds"] == ["image"]
    assert "unanalyzable_replaced" not in informe
    assert informe["completed"] is True and informe["detected"] == informe["masked"] == 1
    assert DNI not in json.dumps(informe) and DATO not in json.dumps(informe)


@pytest.mark.asyncio
async def test_sin_imagenes_el_informe_es_el_de_siempre():
    data = {"model": "m", "messages": [{"role": "user", "content": "hola"}]}
    await _hook(data)
    informe = data["litellm_metadata"]["masking_report"]
    assert "images_unmasked" not in informe and "images_unmasked_kinds" not in informe


@pytest.mark.asyncio
async def test_con_filter_el_informe_no_lleva_images_unmasked_y_la_adjunta_cuenta_como_no_analizable(monkeypatch):
    monkeypatch.setenv(VAR, "filter")
    data = _con_tool_result(png(), resto=[png()])
    await _hook(data)
    informe = data["litellm_metadata"]["masking_report"]
    assert "images_unmasked" not in informe
    assert informe["unanalyzable"] == 1 and informe["unanalyzable_kinds"] == ["image"]
    assert informe["unanalyzable_replaced"] == 1


@pytest.mark.asyncio
async def test_el_pedido_no_puede_cambiar_el_ajuste(monkeypatch):
    monkeypatch.setenv(VAR, "filter")
    data = _con_tool_result(png(), resto=[png()])
    data["metadata"] = {"masking_images": "pass"}
    data["masking_images"] = "pass"
    await _hook(data)
    informe = data["litellm_metadata"]["masking_report"]
    assert informe["unanalyzable"] == 1 and "images_unmasked" not in informe


@pytest.mark.asyncio
async def test_sin_la_senal_de_forzado_no_se_cuenta_nada_y_la_imagen_no_se_toca():
    data = _con_tool_result(png())
    await _hook(data, senal=False)
    assert _resultado(data) == [png()]
    assert "images_unmasked" not in data["litellm_metadata"]["masking_report"]
