"""e2e del round-trip mask→unmask por el MOTOR VIVO (spec 024, FR-007 / SC-006).

El assert que faltaba cuando el gap de unmask llegó a la matriz sin detectarse
(spike 019 batch 1): el contract test cubre el round-trip DEL GATEWAY (passthrough,
upstream mockeado) y los checks del motor invocan hooks a mano — nadie verificaba el
camino real ``gateway → motor → modelo bridged → unmask → cliente``. Esta suite lo
hace contra el stack vivo (mismas reglas que el vecino: skip sin stack, jamás verde
por simulación). Requiere además el modelo local del stack dev (Ollama en el host);
si el modelo no responde, skip explícito con el motivo.

Gotcha de cache (research 024, apéndice T002): el cache del motor se keyea sobre el
prompt SIN enmascarar → prompts repetidos devuelven la respuesta de OTRO mapping.
Por eso cada corrida usa un email ÚNICO (uuid) — así el hit de cache es imposible.
"""
import json
import os
import re
import uuid

import pytest

# Modelo puenteado por el motor (no-Claude). Override por env si el stack usa otro.
BRIDGED_MODEL = os.getenv("BASA_E2E_BRIDGED_MODEL", "ollama-qwen3-4b")

# Placeholder VÁLIDO sin restaurar (formato real de la lib). Un typo del modelo al
# reproducir el token (p.ej. ``[EMAIL_ADDRESS_0_6.2bf]``) NO matchea — irrestaurable
# por diseño y sin PII, no es fallo del round-trip.
RAW_PH_RE = re.compile(r"\[EMAIL_ADDRESS_\d+_[0-9a-f]+\]")


def _pii_body(stream: bool = False):
    mail = f"e2e.{uuid.uuid4().hex[:6]}@hospital-e2e.es"
    body = {
        "model": BRIDGED_MODEL,
        "max_tokens": 700,
        "messages": [{
            "role": "user",
            "content": f"La paciente con email {mail} llamó ayer. Repite la frase tal cual. /no_think",
        }],
    }
    if stream:
        body["stream"] = True
    return mail, body


def _skip_si_modelo_caido(status_code: int, text: str):
    if status_code != 200:
        pytest.skip(f"modelo bridged '{BRIDGED_MODEL}' no disponible "
                    f"({status_code}): {text[:200]} — e2e 024 requiere el runtime local")


def _texto(content_blocks) -> str:
    return "".join((b.get("text") or "") + (b.get("thinking") or "") for b in content_blocks)


def test_roundtrip_no_streaming_restaura_pii(gw, seeded_byok_key):
    """US2/FR-001: la respuesta JSON vuelve con el valor original, no el placeholder."""
    mail, body = _pii_body()
    resp = gw.post("/v1/messages", headers={"x-api-key": seeded_byok_key}, json=body)
    _skip_si_modelo_caido(resp.status_code, resp.text)

    data = resp.json()
    txt = _texto(data.get("content", []))
    assert mail in txt, f"el valor original no volvió: {txt[:300]}"
    assert not RAW_PH_RE.search(txt), f"placeholder válido sin restaurar: {txt[:300]}"


def test_roundtrip_streaming_restaura_pii(gw, seeded_byok_key):
    """US1/FR-001/FR-004: los deltas del stream vuelven restaurados, incluso con el
    placeholder partido en fragmentos chicos (el caso del bridge)."""
    mail, body = _pii_body(stream=True)
    with gw.stream("POST", "/v1/messages",
                   headers={"x-api-key": seeded_byok_key}, json=body) as resp:
        if resp.status_code != 200:
            resp.read()
            _skip_si_modelo_caido(resp.status_code, resp.text)
        txt = ""
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            try:
                d = json.loads(line[6:])
            except ValueError:
                continue
            delta = d.get("delta") or {}
            txt += (delta.get("text") or "") + (delta.get("thinking") or "")

    assert mail in txt, f"el stream no restauró el valor original: {txt[:300]}"
    assert not RAW_PH_RE.search(txt), f"placeholder válido sin restaurar en stream: {txt[:300]}"


def test_evento_byok_lleva_identidad_y_entidades(gw, seeded_byok_key):
    """US3/FR-006: el evento del feed lleva tenant + herramienta y registra el conteo
    de entidades enmascaradas (que además prueba que el mask de IDA corrió — SC-003)."""
    mail, body = _pii_body()
    resp = gw.post("/v1/messages", headers={"x-api-key": seeded_byok_key}, json=body)
    _skip_si_modelo_caido(resp.status_code, resp.text)

    feed = gw.get("/events?limit=10", headers={"x-api-key": seeded_byok_key})
    assert feed.status_code == 200, feed.text
    events = feed.json().get("events", [])
    con_mask = [e for e in events
                if any((m or {}).get("type") == "EMAIL_ADDRESS"
                       for m in (e.get("masked_entities") or []))]
    assert con_mask, f"ningún evento con entidades enmascaradas en el feed: {events[:3]}"
    ev = con_mask[0]
    # Identidad (024 D3 — antes: null). ``client`` puede ser None para una Connection
    # sin user (como la seedeada acá); tenant y tool son el contrato mínimo.
    assert ev.get("tenant"), f"tenant nulo en el evento: {ev}"
    assert ev.get("tool"), f"tool nulo en el evento: {ev}"
