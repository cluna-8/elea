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

from src.database import SessionLocal
from src.models.budget import APIKey
from src.models.tenant import DEFAULT_TENANT_ID
from src.models.user import User
from src.services.key_material import hash_key, key_preview

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


# Señales de "el runtime local no está" (lo ÚNICO que amerita skip). Cualquier otro
# error (500 por excepción del unmask, 400 por regresión del guardrail…) DEBE fallar:
# un skip blanket dejaría la suite verde-por-skip ante una regresión real (review 024).
_UNAVAILABLE_CODES = {502, 503, 504}
_UNAVAILABLE_MARKS = ("connect", "connection", "no disponible", "timeout", "not found")


def _skip_solo_si_runtime_caido(status_code: int, text: str):
    if status_code == 200:
        return
    if status_code in _UNAVAILABLE_CODES or any(m in text.lower() for m in _UNAVAILABLE_MARKS):
        pytest.skip(f"runtime local de '{BRIDGED_MODEL}' no disponible "
                    f"({status_code}): {text[:200]} — e2e 024 requiere el modelo vivo")
    pytest.fail(f"respuesta inesperada del camino byok ({status_code}) — NO es "
                f"indisponibilidad del modelo, puede ser regresión: {text[:300]}")


def _texto_o_skip_por_typo(txt: str, mail: str) -> None:
    """Asserts del round-trip tolerantes al ÚNICO caso aceptado: el modelo reprodujo
    el placeholder con un typo (token corrupto, irrestaurable por diseño). Una
    regresión real deja un placeholder VÁLIDO → falla antes de llegar al skip."""
    assert not RAW_PH_RE.search(txt), f"placeholder válido sin restaurar: {txt[:300]}"
    if mail not in txt and "EMAIL_ADDRESS" in txt:
        pytest.skip("el modelo reprodujo el placeholder corrupto (typo del modelo, "
                    "irrestaurable por diseño) — reintentar con otra corrida")
    assert mail in txt, f"el valor original no volvió: {txt[:300]}"


def _texto(content_blocks) -> str:
    return "".join((b.get("text") or "") + (b.get("thinking") or "") for b in content_blocks)


@pytest.fixture
def seeded_byok_key_con_user():
    """Connection byok CON User (a diferencia del fixture compartido, que usa
    ``user_id=NULL``): el contrato #8 exige ``client`` no-nulo en el evento, y eso
    requiere una Connection con persona detrás. Teardown siempre (finally)."""
    rand = uuid.uuid4().hex[:8]
    plain = f"sk-basa-e2e24-{rand}"
    db = SessionLocal()
    user = User(
        tenant_id=DEFAULT_TENANT_ID,
        username=f"e2e24-{rand}",
        email=f"e2e24-{rand}@e2e.local",
        password_hash="!e2e-no-login",
        role="client",
        client_type="base_url",
    )
    db.add(user)
    db.flush()
    row = APIKey(
        key_hash=hash_key(plain),
        tenant_id=DEFAULT_TENANT_ID,
        key_preview=key_preview(plain),
        name=f"e2e24-conn-{rand}",
        tool_type="claude-code",
        upstream_mode="byok",
        is_active=True,
        user_id=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    key_id, user_id, username = row.id, user.id, user.username
    try:
        yield plain, username
    finally:
        for model, pk in ((APIKey, key_id), (User, user_id)):
            obj = db.get(model, pk)
            if obj is not None:
                db.delete(obj)
        db.commit()
        db.close()


def test_roundtrip_no_streaming_restaura_pii(gw, seeded_byok_key):
    """US2/FR-001: la respuesta JSON vuelve con el valor original, no el placeholder."""
    mail, body = _pii_body()
    resp = gw.post("/v1/messages", headers={"x-api-key": seeded_byok_key}, json=body)
    _skip_solo_si_runtime_caido(resp.status_code, resp.text)

    data = resp.json()
    _texto_o_skip_por_typo(_texto(data.get("content", [])), mail)


def test_roundtrip_streaming_restaura_pii(gw, seeded_byok_key):
    """US1/FR-001/FR-004: los deltas del stream vuelven restaurados, incluso con el
    placeholder partido en fragmentos chicos (el caso del bridge)."""
    mail, body = _pii_body(stream=True)
    with gw.stream("POST", "/v1/messages",
                   headers={"x-api-key": seeded_byok_key}, json=body) as resp:
        if resp.status_code != 200:
            resp.read()
            _skip_solo_si_runtime_caido(resp.status_code, resp.text)
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

    _texto_o_skip_por_typo(txt, mail)


def test_evento_byok_lleva_identidad_y_es_metadata_only(gw, seeded_byok_key_con_user):
    """US3/FR-006 + contrato #8/#9: el evento NUEVO que produce ESTE request lleva
    tenant + tool + client (Connection con User) y conteo de entidades — y el feed
    jamás contiene el valor real (metadata-only). La correlación es por DELTA del
    feed (antes/después), no por 'primer evento que matchee' (review 024)."""
    key, username = seeded_byok_key_con_user
    antes = gw.get("/events?limit=100", headers={"x-api-key": key})
    assert antes.status_code == 200, antes.text
    vistos = {json.dumps(e, sort_keys=True) for e in antes.json().get("events", [])}

    mail, body = _pii_body()
    resp = gw.post("/v1/messages", headers={"x-api-key": key}, json=body)
    _skip_solo_si_runtime_caido(resp.status_code, resp.text)

    # El evento lo publica un callback async del motor DESPUÉS de responder → polling
    # corto (el feed es efímero pero la publicación tarda unos instantes).
    import time as _time
    con_mask, events = [], []
    for _ in range(10):
        feed = gw.get("/events?limit=100", headers={"x-api-key": key})
        assert feed.status_code == 200, feed.text
        events = feed.json().get("events", [])
        nuevos = [e for e in events if json.dumps(e, sort_keys=True) not in vistos]
        con_mask = [e for e in nuevos
                    if any((m or {}).get("type") == "EMAIL_ADDRESS"
                           for m in (e.get("masked_entities") or []))]
        if con_mask:
            break
        _time.sleep(1)

    # Contrato #9 (metadata-only): el valor real JAMÁS aparece en el feed completo.
    assert mail not in json.dumps(events), "el feed contiene el valor real (fuga metadata-only)"
    assert con_mask, f"el request no produjo un evento nuevo con entidades: {events[:3]}"
    ev = con_mask[0]
    # Contrato #8 (024 D3 — antes: null): identidad COMPLETA.
    assert ev.get("tenant"), f"tenant nulo en el evento: {ev}"
    assert ev.get("tool"), f"tool nulo en el evento: {ev}"
    assert ev.get("client") == username, f"client esperado {username}: {ev}"
