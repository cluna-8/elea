"""Enmascarado determinista por documento (spec 043 US3, T035-T037/T041) — el bug real
reportado por Tomás Mc Nally (03-sep-2026): "el nombre Julián se enmascara de forma
diferente [en filas separadas del mismo CSV]". Causa raíz confirmada en diagnostico.md §2:
cada chunk crea su PROPIA `PlaceholderMap` (nonce aleatorio + contador que arranca en 0).
Mismo patrón de test que `test_policy_unit.py` (detector fake, librería PURA, sin red/DB).
"""
import re

import pytest

from extensions import sentinel_guardian_policy as policy

_NAME = "Julián"


async def fake_analyze_person(text: str) -> list:
    """Detector fake: encuentra TODAS las apariciones exactas de `_NAME`."""
    entities = []
    start = text.find(_NAME)
    while start != -1:
        entities.append({"start": start, "end": start + len(_NAME), "entity_type": "PERSON"})
        start = text.find(_NAME, start + 1)
    return entities


def _extraer_placeholder(masked_text: str) -> str:
    m = policy.PLACEHOLDER_TOKEN_RE.search(masked_text)
    assert m, f"ningún placeholder en: {masked_text!r}"
    return m.group(0)


# ── T035: mismo document_id, mismo valor en chunks distintos → mismo placeholder ────────

@pytest.mark.asyncio
async def test_mismo_document_id_mismo_valor_en_dos_chunks_da_el_mismo_placeholder():
    """El caso EXACTO reportado: un CSV con 'Julián' en dos filas separadas por más de un
    chunk de 4000 caracteres — dos llamadas HTTP separadas, cada una con su propio
    PlaceholderMap, pero el MISMO document_id."""
    doc_id = "documento-real-de-prueba-1"

    pmap_chunk1 = policy.PlaceholderMap(document_id=doc_id)
    masked1 = await policy.mask_text(f"nombre,edad\n{_NAME},40", fake_analyze_person, pmap_chunk1)

    pmap_chunk2 = policy.PlaceholderMap(document_id=doc_id)  # instancia DISTINTA
    masked2 = await policy.mask_text(f"nombre,edad\n{_NAME},52", fake_analyze_person, pmap_chunk2)

    ph1 = _extraer_placeholder(masked1)
    ph2 = _extraer_placeholder(masked2)
    assert ph1 == ph2, f"mismo documento, mismo valor, placeholders distintos: {ph1} != {ph2}"


@pytest.mark.asyncio
async def test_tres_chunks_del_mismo_documento_coinciden_todos():
    doc_id = "documento-real-de-prueba-2"
    placeholders = []
    for i in range(3):
        pmap = policy.PlaceholderMap(document_id=doc_id)
        masked = await policy.mask_text(f"fila {i}: {_NAME} tiene una consulta",
                                        fake_analyze_person, pmap)
        placeholders.append(_extraer_placeholder(masked))
    assert len(set(placeholders)) == 1, placeholders


# ── T036: sin document_id → comportamiento actual, sin regresión ────────────────────────

@pytest.mark.asyncio
async def test_sin_document_id_el_nonce_sigue_siendo_aleatorio_por_instancia():
    """Sin document_id, dos PlaceholderMap distintas para el MISMO valor deben (con
    altísima probabilidad) dar placeholders DISTINTOS — es el comportamiento actual, y
    tiene que seguir siendo así para no romper a otros clientes del despliegue
    compartido (la extensión de navegador, que nunca manda document_id)."""
    diferentes = 0
    for _ in range(20):
        pmap_a = policy.PlaceholderMap()
        masked_a = await policy.mask_text(_NAME, fake_analyze_person, pmap_a)
        pmap_b = policy.PlaceholderMap()
        masked_b = await policy.mask_text(_NAME, fake_analyze_person, pmap_b)
        if _extraer_placeholder(masked_a) != _extraer_placeholder(masked_b):
            diferentes += 1
    # Nonce de 4 hex (65536 valores): con 20 corridas, la probabilidad de que TODAS
    # coincidan por azar es despreciable — si el fix rompió el default, esto lo detecta.
    assert diferentes > 15, f"solo {diferentes}/20 distintos — ¿el default dejó de ser aleatorio?"


@pytest.mark.asyncio
async def test_document_id_none_explicito_es_identico_a_no_pasarlo():
    pmap1 = policy.PlaceholderMap(document_id=None)
    pmap2 = policy.PlaceholderMap()
    assert pmap1.document_id is None and pmap2.document_id is None


# ── T037: document_id distinto para el mismo valor → placeholder distinto ───────────────

@pytest.mark.asyncio
async def test_document_id_distinto_da_placeholder_distinto_para_el_mismo_valor():
    """No se crea un seudónimo estable ENTRE documentos — decisión sellada del dueño del
    producto (08-sep): eso sería una enmienda constitucional (C1), no continuación técnica
    de este bug."""
    pmap_doc_a = policy.PlaceholderMap(document_id="documento-a")
    masked_a = await policy.mask_text(_NAME, fake_analyze_person, pmap_doc_a)

    pmap_doc_b = policy.PlaceholderMap(document_id="documento-b")
    masked_b = await policy.mask_text(_NAME, fake_analyze_person, pmap_doc_b)

    assert _extraer_placeholder(masked_a) != _extraer_placeholder(masked_b)


@pytest.mark.asyncio
async def test_reenviar_el_mismo_documento_de_cero_da_otro_placeholder():
    """Subir el MISMO CSV dos veces (dos uploads distintos, dos document_id nuevos) no
    correlaciona — cada subida es un documento nuevo a todos los efectos."""
    import uuid
    pmap1 = policy.PlaceholderMap(document_id=str(uuid.uuid4()))
    masked1 = await policy.mask_text(_NAME, fake_analyze_person, pmap1)
    pmap2 = policy.PlaceholderMap(document_id=str(uuid.uuid4()))
    masked2 = await policy.mask_text(_NAME, fake_analyze_person, pmap2)
    assert _extraer_placeholder(masked1) != _extraer_placeholder(masked2)


# ── T041: gramática del placeholder y compatibilidad con el desenmascarado ──────────────

@pytest.mark.asyncio
async def test_placeholder_determinista_respeta_la_gramatica_ph_type_re():
    pmap = policy.PlaceholderMap(document_id="doc-gramatica")
    masked = await policy.mask_text(_NAME, fake_analyze_person, pmap)
    ph = _extraer_placeholder(masked)
    assert policy.PH_TYPE_RE.search(ph), f"no matchea PH_TYPE_RE: {ph}"
    assert policy.PLACEHOLDER_TOKEN_RE.fullmatch(ph), f"no matchea PLACEHOLDER_TOKEN_RE: {ph}"
    assert len(ph) < policy.MAX_CARRY, f"placeholder demasiado largo para MAX_CARRY: {ph}"


@pytest.mark.asyncio
async def test_round_trip_completo_con_document_id():
    """El desenmascarado (unmask_text) no sabe ni le importa si el placeholder es
    determinista o aleatorio — mismo mapa ph_to_orig, mismo mecanismo."""
    doc_id = "doc-roundtrip"
    pmap = policy.PlaceholderMap(document_id=doc_id)
    text = f"Consultar con {_NAME} sobre el caso"
    masked = await policy.mask_text(text, fake_analyze_person, pmap)
    assert _NAME not in masked
    restored = policy.unmask_text(masked, pmap.ph_to_orig)
    assert restored == text


@pytest.mark.asyncio
async def test_dos_valores_distintos_mismo_documento_no_colisionan():
    """Julián y María en el mismo documento deben recibir placeholders DISTINTOS entre
    sí (el HMAC deriva del valor, no solo del documento)."""
    doc_id = "doc-dos-valores"

    async def analyze_dos_nombres(text: str) -> list:
        out = []
        for nombre in ("Julián", "María"):
            idx = text.find(nombre)
            if idx != -1:
                out.append({"start": idx, "end": idx + len(nombre), "entity_type": "PERSON"})
        return out

    pmap = policy.PlaceholderMap(document_id=doc_id)
    masked = await policy.mask_text("Julián y María", analyze_dos_nombres, pmap)
    placeholders = policy.PLACEHOLDER_TOKEN_RE.findall(masked)
    assert len(placeholders) == 2
    assert placeholders[0] != placeholders[1]
