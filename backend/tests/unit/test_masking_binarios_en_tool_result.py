"""S14 — binarios no analizables DENTRO de un `tool_result` bajo enmascarado forzado (057 R39; contracts/costuras-base.md §S14).

Cowork crea archivos ejecutando código y verifica el resultado con capturas que vuelven como imágenes dentro de un
`tool_result`. Bajo el forzado una imagen no es analizable y bloqueaba el pedido (403 `masking_required`): la tarea se
cortaba. Decisión de Atlas (la más restrictiva que no rompe Cowork): lo que devolvió una HERRAMIENTA y no se puede
analizar (imagen, audio, documento que no se pudo leer) se reemplaza por una nota de texto neutra —el binario nunca sale
hacia el destino— y se cuenta aparte (`unanalyzable_replaced`). Lo que adjunta la PERSONA en su mensaje sigue siendo no
analizable y bloquea, igual que antes.
"""
import json

import pytest

import s14_helpers as h
from s14_helpers import DNI, policy  # noqa: E402
from extensions import sentinel_guardrail  # noqa: E402



def png():
    """Una instancia nueva por uso: el recorrido reemplaza el bloque EN EL LUGAR."""
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJDREVGRw=="}}


NOTA = policy.UNANALYZABLE_REPLACED_NOTE


@pytest.fixture(autouse=True)
def _imagenes_filtradas(monkeypatch):
    """Estos tests fijan el modo `filter` (R39): la imagen adjunta bloquea y la de una herramienta se reemplaza. El default de
    Eleia es `pass` (R43, `test_masking_imagenes_pass.py`)."""
    monkeypatch.setenv("MASKING_IMAGES", "filter")


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


def _anthropic(*contenido_tool_result, resto=()):
    return {"model": "m", "messages": [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "screenshot", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": list(contenido_tool_result)}, *resto]},
    ]}


def _resultado(cuerpo):
    return cuerpo["messages"][1]["content"][0]["content"]


# ── 1. La captura de la herramienta se reemplaza por una nota ─────────────────────────────

@pytest.mark.asyncio
async def test_la_imagen_de_un_tool_result_se_reemplaza_por_una_nota_y_no_bloquea():
    cuerpo, _, tally = await _enmascarar(_anthropic(png()))
    assert _resultado(cuerpo) == [{"type": "text", "text": NOTA}], "nunca queda vacío ni con el binario"
    assert tally.unanalyzable == 0 and tally.kinds == []
    assert tally.unanalyzable_replaced == 1 and tally.replaced_kinds == ["image"]
    assert "QUJDREVGRw" not in json.dumps(cuerpo), "el binario no sale hacia el destino"


@pytest.mark.asyncio
async def test_la_nota_es_neutra_y_pide_no_insistir():
    assert "imagen" in NOTA and "no vuelvas" in NOTA.lower()
    for prohibido in ("litellm", "presidio", "sentinel", "elea", "guardian"):
        assert prohibido not in NOTA.lower(), "marca neutra: nada visible nombra componentes internos"


@pytest.mark.asyncio
async def test_el_texto_vecino_se_enmascara_y_la_imagen_se_reemplaza():
    cuerpo, mapa, tally = await _enmascarar(_anthropic({"type": "text", "text": f"DNI {DNI}"}, png()))
    texto = json.dumps(cuerpo, ensure_ascii=False)
    assert DNI not in texto and DNI in mapa.values()
    assert _resultado(cuerpo)[1] == {"type": "text", "text": NOTA}
    assert tally.unanalyzable == 0 and tally.unanalyzable_replaced == 1


@pytest.mark.asyncio
async def test_las_imagenes_de_turnos_anteriores_tambien_se_reemplazan():
    """La herramienta reenvía la historia entera en cada pedido: las capturas viejas no cortan la tarea."""
    cuerpo = {"model": "m", "messages": [
        *_anthropic(png(), png())["messages"],
        {"role": "assistant", "content": [{"type": "text", "text": "listo"}]},
        {"role": "user", "content": "seguí"},
    ]}
    cuerpo, _, tally = await _enmascarar(cuerpo)
    assert tally.unanalyzable == 0 and tally.unanalyzable_replaced == 2
    assert "QUJDREVGRw" not in json.dumps(cuerpo)


@pytest.mark.asyncio
async def test_la_marca_de_cache_del_bloque_pasa_a_la_nota():
    imagen = {**png(), "cache_control": {"type": "ephemeral"}}
    cuerpo, _, tally = await _enmascarar(_anthropic(imagen))
    assert _resultado(cuerpo) == [{"type": "text", "text": NOTA, "cache_control": {"type": "ephemeral"}}]
    assert tally.unanalyzable == 0


@pytest.mark.asyncio
async def test_documento_por_url_y_pdf_ilegible_dentro_de_un_tool_result_se_reemplazan():
    url = {"type": "document", "source": {"type": "url", "url": "https://x.example/a.pdf"}}
    cuerpo, _, tally = await _enmascarar(_anthropic(url, h.bloque_pdf(h.pdf_sin_texto())))
    assert _resultado(cuerpo) == [{"type": "text", "text": NOTA_DOCUMENTO}] * 2
    assert tally.unanalyzable == 0 and tally.unanalyzable_replaced == 2
    assert tally.replaced_kinds == sorted({"document_url", h.kind_esperado("pdf_no_text")})


NOTA_DOCUMENTO = policy.UNANALYZABLE_REPLACED_NOTE_DOCUMENT


@pytest.mark.asyncio
@pytest.mark.skipif(not h.HAY_PYPDF, reason="la extracción de PDF necesita pypdf (T105 lo cubre sin él)")
async def test_un_pdf_con_texto_dentro_de_un_tool_result_sigue_saliendo_como_texto_enmascarado():
    cuerpo, mapa, tally = await _enmascarar(_anthropic(h.bloque_pdf(h.pdf_con_texto(f"DNI {DNI}"))))
    assert DNI not in json.dumps(cuerpo) and DNI in mapa.values()
    assert tally.unanalyzable == 0 and tally.unanalyzable_replaced == 0


# ── 2. Lo que adjunta la persona sigue bloqueando ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_la_imagen_suelta_de_la_persona_sigue_siendo_no_analizable_aun_junto_a_un_tool_result():
    cuerpo, _, tally = await _enmascarar(_anthropic(png(), resto=[png()]))
    assert tally.unanalyzable == 1 and tally.kinds == ["image"], "solo la suelta cuenta"
    assert tally.unanalyzable_replaced == 1
    assert cuerpo["messages"][1]["content"][1]["type"] == "image", "la de la persona no se toca: el guard bloquea"


@pytest.mark.asyncio
async def test_la_imagen_de_un_turno_de_la_persona_sin_tool_result_sigue_bloqueando():
    cuerpo = {"model": "m", "messages": [{"role": "user", "content": [png()]}]}
    _, _, tally = await _enmascarar(cuerpo)
    assert tally.unanalyzable == 1 and tally.kinds == ["image"] and tally.unanalyzable_replaced == 0


@pytest.mark.asyncio
async def test_los_no_analizables_que_no_son_binarios_siguen_bloqueando_dentro_de_un_tool_result():
    desconocido = {"type": "tipo_que_no_existe", "payload": "x"}
    _, _, tally = await _enmascarar(_anthropic(desconocido))
    assert tally.unanalyzable == 1 and tally.kinds == ["unknown_block"] and tally.unanalyzable_replaced == 0


# ── 3. Formato OpenAI ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_openai_la_imagen_de_un_mensaje_tool_se_reemplaza_y_la_del_usuario_bloquea():
    def imagen():
        return {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJDREVGRw=="}}

    cuerpo = {"model": "m", "messages": [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "shot", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": [imagen()]},
        {"role": "user", "content": [imagen()]},
    ]}
    cuerpo, _, tally = await _enmascarar(cuerpo, fmt="openai")
    assert cuerpo["messages"][1]["content"] == [{"type": "text", "text": NOTA}]
    assert tally.unanalyzable == 1 and tally.kinds == ["image"]
    assert tally.unanalyzable_replaced == 1 and tally.replaced_kinds == ["image"]


# ── 4. Informe del guardrail y recorrido sin la señal ─────────────────────────────────────

class _Identidad:
    def __init__(self, **sentinel):
        self.metadata = {"sentinel": {"region": "latam_ar", **sentinel}}


async def _hook(data, *, senal=True):
    home = sentinel_guardrail._metadata_home(data, "anthropic_messages")
    if senal:
        policy.mark_forced_masking(home)
    return await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(
        _Identidad(), None, data, "anthropic_messages")


@pytest.mark.asyncio
async def test_el_informe_cuenta_lo_reemplazado_aparte_y_no_lleva_contenido():
    data = _anthropic({"type": "text", "text": f"DNI {DNI}"}, png())
    await _hook(data)
    informe = data["litellm_metadata"]["masking_report"]
    assert informe["unanalyzable"] == 0 and informe["unanalyzable_kinds"] == []
    assert informe["unanalyzable_replaced"] == 1 and informe["unanalyzable_replaced_kinds"] == ["image"]
    assert informe["completed"] is True and informe["detected"] == informe["masked"] == 1
    assert DNI not in json.dumps(informe) and "QUJDREVGRw" not in json.dumps(informe)


@pytest.mark.asyncio
async def test_sin_reemplazos_el_informe_es_el_de_siempre():
    data = {"model": "m", "messages": [{"role": "user", "content": "hola"}]}
    await _hook(data)
    informe = data["litellm_metadata"]["masking_report"]
    assert "unanalyzable_replaced" not in informe and "unanalyzable_replaced_kinds" not in informe


@pytest.mark.asyncio
async def test_sin_la_senal_la_imagen_de_un_tool_result_no_se_toca():
    data = _anthropic(png())
    await _hook(data, senal=False)
    assert _resultado(data) == [png()], "sin forzado todo queda como hoy (scope = user)"
