"""Propiedad del espejo: la vitrina JAMÁS muestra un string que el masker no tocó (#63).

Por qué un test de propiedad y no más casos sueltos. El fix del hallazgo ALTO del review
adversarial consiste en que `gateway._textos_enmascarables` sea el espejo exacto de
`policy._mask_content`: cada string que el preview del monitor puede mostrar tiene que ser un
string que `mask_body` reescribe. Pero son DOS funciones, en DOS módulos, mantenidas por
separado — y el bug original fue exactamente eso: una recogía `text` de cualquier bloque y la
otra sólo enmascaraba `type` en ("text", "tool_result"), así que
`{"type": "image", "text": "<PII>"}` salía LITERAL a la vitrina y a Redis.

Un test por forma conocida no protege de la forma que nadie previó. Este recorre un corpus de
formas variadas —tipos distintos, `text` vs `content`, anidados, basura— y afirma el
invariante DIRECCIONAL:

    {strings que el preview expone}  ⊆  {strings que mask_text analizó}

La dirección importa. Que el masker toque MÁS de lo que la vitrina muestra es seguro (mirar de
más es conservador). Que la vitrina muestre algo que el masker no tocó es la fuga. El test
sólo prohíbe la segunda.

El "conjunto de strings que mask_text analizó" no se declara a mano: se INSTRUMENTA el
analizador inyectado, que es el único punto por el que pasa todo lo que se enmascara. Así el
test mide el comportamiento real de la librería compartida, no una copia de sus reglas.
"""
import copy

import pytest

from src.api import gateway

policy = gateway.policy

# PII de relleno, distinta en cada campo, para que un assert que falle diga QUÉ campo se fugó.
PII = {
    "texto": "Sr. Juan Perez vive en Valencia",
    "imagen": "IMG-LEAK maria.lopez@clinica.es",
    "tool_str": "resultado: paciente ana@hospital.es",
    "tool_sub": "sub-bloque de Dr. Carlos Ruiz",
    "tool_sub_img": "TOOLIMG-LEAK pedro@clinica.es",
    "pensamiento": "THINK-LEAK dni 12345678Z",
    "tool_use": "TOOLUSE-LEAK +34 612 345 678",
    "sin_tipo": "NOTYPE-LEAK laura@clinica.es",
    "doc": "DOC-LEAK IBAN ES9121000418450200051332",
}

# Corpus de bloques de `content`. Cada entrada: (bloque, strings que el preview PUEDE mostrar).
# Los que esperan `[]` son los peligrosos: llevan texto que el masker no transforma.
CORPUS = [
    # — Lo que el masker SÍ reescribe —
    ({"type": "text", "text": PII["texto"]}, [PII["texto"]]),
    ({"type": "tool_result", "content": PII["tool_str"]}, [PII["tool_str"]]),
    ({"type": "tool_result", "content": [{"type": "text", "text": PII["tool_sub"]}]},
     [PII["tool_sub"]]),

    # — Lo que el masker NO toca: nada de esto puede llegar a la vitrina —
    # El caso que reprodujo el reviewer: `type` no enmascarable con un `text` al lado.
    ({"type": "image", "text": PII["imagen"]}, []),
    # Variante realista: bloque de imagen bien formado + `text` colado.
    ({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAA"},
      "text": PII["imagen"]}, []),
    # `thinking` se enmascara en la RESPUESTA (unmask), no en el pedido del user.
    ({"type": "thinking", "thinking": PII["pensamiento"], "text": PII["pensamiento"]}, []),
    # Los `input` de tool_use no los toca `_mask_content`.
    ({"type": "tool_use", "name": "buscar", "input": {"text": PII["tool_use"]},
      "text": PII["tool_use"]}, []),
    # Documentos: mismo criterio que imagen.
    ({"type": "document", "text": PII["doc"]}, []),
    # Sin `type`: no hay forma de saber si se enmascara ⇒ no se muestra.
    ({"text": PII["sin_tipo"]}, []),
    # `tool_result` anidado con un sub-bloque NO enmascarable: sólo sobrevive el de texto.
    ({"type": "tool_result", "content": [
        {"type": "text", "text": PII["tool_sub"]},
        {"type": "image", "text": PII["tool_sub_img"]},
    ]}, [PII["tool_sub"]]),

    # — Formas degeneradas: no pueden romper ni colar nada —
    ({"type": "text"}, []),                                  # sin `text`
    ({"type": "text", "text": None}, []),                    # `text` no-string
    ({"type": "text", "text": 12345}, []),
    ({"type": "tool_result", "content": None}, []),
    ({"type": "tool_result", "content": [{"type": "text"}]}, []),
    ({"type": "tool_result", "content": [{"no": "es un bloque"}]}, []),
    ({}, []),
]


def _cuerpo(bloques) -> dict:
    return {"model": "claude-3-5-sonnet-20241022",
            "messages": [{"role": "user", "content": list(bloques)}]}


async def _analizador_registrador(registro: list):
    """`AnalyzeFn` que no detecta nada pero ANOTA cada string que le pasaron.

    Es el instrumento del test: `mask_text` llama al analizador con exactamente el segmento
    que va a enmascarar, así que el registro ES el conjunto "lo que el masker tocó",
    observado del código real en vez de declarado a mano."""
    async def _analyze(text: str) -> list:
        registro.append(text)
        return []
    return _analyze


async def _strings_que_el_masker_toca(body: dict) -> set:
    registro: list = []
    analyze = await _analizador_registrador(registro)
    # Sobre una COPIA: `mask_body` muta, y el preview se mide contra el cuerpo original.
    await policy.mask_body(copy.deepcopy(body), analyze)
    return set(registro)


# ── La propiedad ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("bloque, esperado", CORPUS,
                         ids=[f"{b.get('type') or 'sin-type'}-{i}"
                              for i, (b, _e) in enumerate(CORPUS)])
async def test_el_preview_nunca_muestra_lo_que_el_masker_no_toca(bloque, esperado):
    """Invariante direccional, bloque por bloque."""
    body = _cuerpo([bloque])
    tocados = await _strings_que_el_masker_toca(body)

    preview = gateway._last_user_text(body)
    expuestos = [p for p in preview.split("\n") if p]

    fugados = [s for s in expuestos if s not in tocados]
    assert not fugados, (
        f"el preview expone strings que `mask_body` NUNCA analizó: {fugados!r} — "
        f"el masker sólo tocó {sorted(tocados)!r}")
    # Y la contracara: el helper no puede "aprobar" el test devolviendo siempre vacío.
    assert expuestos == esperado


@pytest.mark.asyncio
async def test_la_propiedad_vale_sobre_el_corpus_entero_mezclado():
    """El mismo invariante con TODOS los bloques en un solo turno: así se cubre también la
    interacción entre formas (el orden del aplanado, un bloque peligroso entre dos seguros)."""
    bloques = [b for b, _e in CORPUS]
    body = _cuerpo(bloques)
    tocados = await _strings_que_el_masker_toca(body)

    expuestos = [p for p in gateway._last_user_text(body).split("\n") if p]

    assert set(expuestos) <= tocados, (
        f"fuga en el corpus mezclado: {sorted(set(expuestos) - tocados)!r}")
    # Ninguna de las PII de los bloques NO enmascarables aparece, con nombre y apellido.
    for clave in ("imagen", "pensamiento", "tool_use", "sin_tipo", "doc", "tool_sub_img"):
        assert PII[clave] not in "\n".join(expuestos), f"se fugó el campo {clave!r}"
    # …y las de los enmascarables sí, o el test estaría pasando por vacío.
    for clave in ("texto", "tool_str", "tool_sub"):
        assert PII[clave] in "\n".join(expuestos)


@pytest.mark.asyncio
async def test_el_content_string_del_mensaje_tambien_cumple():
    """`content` como str suelto (la forma más común) es el caso trivial, pero tiene que
    entrar por la misma propiedad: `_mask_content` lo enmascara entero."""
    body = {"model": "m", "messages": [{"role": "user", "content": PII["texto"]}]}
    tocados = await _strings_que_el_masker_toca(body)

    assert gateway._last_user_text(body) == PII["texto"]
    assert PII["texto"] in tocados


@pytest.mark.asyncio
async def test_el_preview_real_no_deja_pasar_el_bloque_no_enmascarable():
    """Cierre extremo a extremo del invariante: no sobre el helper, sino sobre
    `_safe_preview` con el atajo `ya_enmascarado` activo — que es el camino por el que el
    bug llegaba de verdad a Redis y al monitor."""
    body = _cuerpo([
        {"type": "text", "text": PII["texto"]},
        {"type": "image", "text": PII["imagen"]},
    ])
    # Se enmascara el body como lo haría la política, con el detector regex de dev.
    await policy.mask_body(body, policy.default_analyze)

    preview = await gateway._safe_preview(body, None, ya_enmascarado=True)

    assert PII["imagen"] not in preview, "PII cruda en la vitrina (C1)"
    assert "maria.lopez@clinica.es" not in preview
