"""057 (hallazgo del gate): stream estilo Azure con `choices=[]` por el camino de la cara Claude redirigida.

Azure OpenAI abre el stream con un chunk de anotaciones de filtro de contenido y lo cierra con otro de `usage`, los dos con
`choices=[]`. Con `stream_options.include_usage` (lo fija el adaptador de `/v1/messages` del motor) el stream de LiteLLM los
deja pasar y el adaptador de Anthropic desreferencia `chunk.choices[0]`: `IndexError`, el cliente recibe 200 con la respuesta
cortada y no se escribe la fila de auditoría. La versión del motor la fija M1 (no se actualiza): el arreglo vive en el guard,
que filtra esos chunks ANTES de que lleguen al adaptador.

El motor no está instalado en el entorno de tests: un módulo falso con el mismo contrato que el real (`AnthropicAdapter.
translate_completion_output_params_streaming` itera el stream y lee `choices[0]`) hace de adaptador.
"""
import asyncio
import sys
import types
from types import SimpleNamespace as NS

import pytest

from sentinel.engine import redirect_guard as g

_MOD = "litellm.llms.anthropic.experimental_pass_through.adapters.transformation"


def _chunk(text=None, finish=None, choices=None, usage=None):
    if choices is None:
        choices = [NS(index=0, delta=NS(content=text), finish_reason=finish)]
    return NS(choices=choices, usage=usage)


def _azure_stream():
    """Lo que manda Azure: filtro de contenido al inicio, texto, cierre y `usage` al final (los dos de los extremos, sin choices)."""
    return [_chunk(choices=[]), _chunk("ho"), _chunk("la"), _chunk(finish="stop"), _chunk(choices=[], usage={"total_tokens": 7})]


async def _alist(stream):
    return [c async for c in stream]


class _Fuente:
    """Stream asíncrono con `__aiter__`, como el `CustomStreamWrapper`."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        async def gen():
            for c in self._chunks:
                yield c
        return gen()


@pytest.fixture
def adaptador(monkeypatch):
    """`AnthropicAdapter` falso con la misma conducta que el real: itera el stream y lee `choices[0]` de cada chunk."""
    class AnthropicAdapter:
        def translate_completion_output_params_streaming(self, completion_stream, model, tool_name_mapping=None,
                                                         polyfill_result=None, is_async=True):
            async def sse():
                async for chunk in completion_stream:
                    yield chunk.choices[0].delta.content or "" if chunk.choices[0].finish_reason is None else "<fin>"
            return sse()

    chain = _MOD.split(".")
    for i in range(1, len(chain) + 1):
        monkeypatch.setitem(sys.modules, ".".join(chain[:i]), types.ModuleType(".".join(chain[:i])))
    monkeypatch.setattr(sys.modules[_MOD], "AnthropicAdapter", AnthropicAdapter, raising=False)
    return AnthropicAdapter


def test_sin_el_filtro_el_adaptador_revienta_con_el_chunk_sin_choices(adaptador):
    """El estado de hoy (rojo de origen): el stream de Azure rompe al adaptador."""
    flujo = adaptador().translate_completion_output_params_streaming(_Fuente(_azure_stream()), model="m")
    with pytest.raises(IndexError):
        asyncio.run(_alist(flujo))


def test_con_el_filtro_el_stream_de_azure_llega_entero_al_adaptador(adaptador):
    assert g.install_empty_choices_filter() is True
    flujo = adaptador().translate_completion_output_params_streaming(_Fuente(_azure_stream()), model="m")
    assert asyncio.run(_alist(flujo)) == ["ho", "la", "<fin>"]


def test_el_filtro_es_idempotente(adaptador):
    assert g.install_empty_choices_filter() is True
    assert g.install_empty_choices_filter() is True
    flujo = adaptador().translate_completion_output_params_streaming(_Fuente(_azure_stream()), model="m")
    assert asyncio.run(_alist(flujo)) == ["ho", "la", "<fin>"]


def test_un_stream_normal_no_se_toca(adaptador):
    g.install_empty_choices_filter()
    normal = [_chunk("a"), _chunk("b"), _chunk(finish="stop")]
    flujo = adaptador().translate_completion_output_params_streaming(_Fuente(normal), model="m")
    assert asyncio.run(_alist(flujo)) == ["a", "b", "<fin>"]


def test_tambien_filtra_un_stream_sincrono(adaptador):
    """`AnthropicAdapter` también sirve el camino síncrono (`is_async=False`): el filtro lo cubre con `__iter__`."""
    capturado = {}

    def sync(self, completion_stream, model, tool_name_mapping=None, polyfill_result=None, is_async=True):
        capturado["chunks"] = [c.choices[0].delta.content for c in completion_stream if c.choices[0].finish_reason is None]
        return iter(capturado["chunks"])

    adaptador.translate_completion_output_params_streaming = sync
    g.install_empty_choices_filter()
    assert list(adaptador().translate_completion_output_params_streaming(iter(_azure_stream()), model="m")) == ["ho", "la"]


def test_sin_el_adaptador_del_motor_no_hay_nada_que_instalar(monkeypatch):
    """Fuera del motor (tests de lógica pura) o con una base sin ese adaptador: no falla, devuelve False."""
    monkeypatch.setitem(sys.modules, _MOD, None)       # `import` lanza ImportError
    assert g.install_empty_choices_filter() is False


def test_no_toca_el_contenido_de_los_chunks_con_choices(adaptador):
    g.install_empty_choices_filter()
    con_choices = _chunk("hola")
    flujo = adaptador().translate_completion_output_params_streaming(_Fuente([_chunk(choices=[]), con_choices]), model="m")
    assert asyncio.run(_alist(flujo)) == ["hola"]
    assert con_choices.choices[0].delta.content == "hola"


def test_el_guard_instala_el_filtro_al_crearse(adaptador):
    g.RedirectGuard()
    flujo = adaptador().translate_completion_output_params_streaming(_Fuente(_azure_stream()), model="m")
    assert asyncio.run(_alist(flujo)) == ["ho", "la", "<fin>"]
