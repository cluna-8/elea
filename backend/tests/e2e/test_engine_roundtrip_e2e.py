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
import warnings

import pytest

from src.database import SessionLocal
from src.models.budget import APIKey
from src.models.tenant import DEFAULT_TENANT_ID
from src.models.user import User
from src.services.key_material import hash_key, key_preview

# Modelo puenteado por el motor (no-Claude). Override por env si el stack usa otro.
BRIDGED_MODEL = os.getenv("SENTINEL_E2E_BRIDGED_MODEL", "ollama-qwen3-4b")

# Forma de placeholder tal como la ve el usuario: ``[TIPO_idx_nonce]``. El token que el
# motor emite de verdad lleva ``nonce = uuid4().hex[:4]`` (``PlaceholderMap``, en
# sentinel_guardian_policy) — SIEMPRE 4 hex y con el índice que le tocó al valor en ESTE
# request. El regex es a propósito más laxo que esa forma: detecta también los tokens que
# el modelo reproduce mal, porque distinguirlos por forma no alcanza (ver
# ``_verifica_round_trip``).
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


def _verifica_round_trip(txt: str, mail: str) -> None:
    """Assert DURO de lo que este test verifica de verdad: **un placeholder que el modelo
    devolvió BIEN se restaura**, o sea, el valor original vuelve al cliente.

    Se mide por PRESENCIA del valor y no por ausencia de placeholders, y eso es un cambio
    con evidencia. El assert viejo (``not RAW_PH_RE.search``) fallaba ~1 de cada 3 porque
    tomaba "tiene forma de placeholder" por "es el placeholder del request", y no lo es: el
    modelo local es chico y verboso, razona en voz alta SOBRE el token que vio y lo tipea
    mal. Medido en 28 corridas contra el stack vivo: 4 dejaron un token a mano —nonces de
    2, 3 y 4 hex, e incluso un índice inventado (``_2_`` con un solo email en el prompt, o
    sea imposible)— y en las 28 el valor volvió, entre 7 y 15 veces por respuesta.

    Que un token con forma perfecta (4 hex, índice 0) tampoco pruebe nada NO es una
    concesión: 3 de esas 4 corridas fueron **sin streaming**, donde el unmask es un
    ``str.replace`` global por bloque (``unmask_response_payload`` → ``unmask_text``). Si
    el mapa del request estaba activo —y que el valor haya vuelto lo PRUEBA— ninguna
    ocurrencia del token real pudo sobrevivir a ese replace. Un token que sobrevive ahí es,
    necesariamente, uno que el motor nunca emitió.

    Un token inventado por el modelo tampoco es fuga: no lleva PII y es irrestaurable por
    definición (no está en el mapa). Lo que SÍ es fallo —y ahora falla siempre, cosa que
    antes no pasaba— es que el valor no vuelva: el skip viejo ("el modelo lo reprodujo
    mal") tapaba justo el caso grave, un unmask que no restaura NADA con el modelo encima
    tipeando mal el token se saltaba en vez de fallar."""
    crudos = RAW_PH_RE.findall(txt)
    assert mail in txt, (f"el valor original NO volvió al cliente — round-trip roto "
                         f"(placeholders crudos={crudos}): {txt[:300]}")
    if crudos:
        warnings.warn(f"el modelo reprodujo mal el token {crudos} (irrestaurable por "
                      f"diseño); el valor sí volvió {txt.count(mail)} vez/veces")


def _falla_si_placeholder_partido(fragmentos: list) -> None:
    """Detector de la regresión 024 en streaming, que es donde el argumento del replace
    global NO aplica: ahí el unmask corre POR DELTA con carry-split, así que un token real
    podría escaparse justo en un borde de chunk.

    El discriminador no depende del modelo. Si el carry retuvo bien el fragmento, el token
    llega ENTERO dentro de un delta (``safe_split`` lo sostiene hasta completarlo) — y que
    llegue entero y sin restaurar prueba que no estaba en el mapa, o sea que lo inventó el
    modelo. Si en cambio el cliente solo lo ve al CONCATENAR deltas, es que el carry lo
    soltó partido y lo emitió sin des-enmascarar: esa es la firma exacta del bug del spike
    019 que la 024 arregló (root cause: ``safe_split`` soltaba el ``[`` pelado)."""
    txt = "".join(fragmentos)
    cortes, pos = [], 0
    for frag in fragmentos:
        pos += len(frag)
        cortes.append(pos)
    partidos = [m.group(0) for m in RAW_PH_RE.finditer(txt)
                if any(m.start() < corte < m.end() for corte in cortes)]
    assert not partidos, (f"placeholder PARTIDO entre deltas y emitido sin des-enmascarar "
                          f"{partidos} — regresión del carry-split (024): {txt[:300]}")


def _texto(content_blocks) -> str:
    return "".join((b.get("text") or "") + (b.get("thinking") or "") for b in content_blocks)


@pytest.fixture
def seeded_byok_key_con_user(borrado_sin_carrera):
    """Connection byok CON User (a diferencia del fixture compartido, que usa
    ``user_id=NULL``): el contrato #8 exige ``client`` no-nulo en el evento, y eso
    requiere una Connection con persona detrás. Teardown siempre (finally), y por el
    MISMO camino resistente a la carrera con el motor que el fixture compartido (#41):
    acá la exposición es doble, porque la fila de auditoría del pedido referencia tanto
    la Connection (``api_key_id``) como la persona (``user_id``)."""
    rand = uuid.uuid4().hex[:8]
    plain = f"sk-sentinel-e2e24-{rand}"
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
        borrado_sin_carrera(db, api_key_id=key_id, user_id=user_id)
        db.close()


def test_roundtrip_no_streaming_restaura_pii(gw, seeded_byok_key):
    """US2/FR-001: la respuesta JSON vuelve con el valor original, no el placeholder."""
    mail, body = _pii_body()
    resp = gw.post("/v1/messages", headers={"x-api-key": seeded_byok_key}, json=body)
    _skip_solo_si_runtime_caido(resp.status_code, resp.text)

    data = resp.json()
    _verifica_round_trip(_texto(data.get("content", [])), mail)


def test_roundtrip_streaming_restaura_pii(gw, seeded_byok_key):
    """US1/FR-001/FR-004: los deltas del stream vuelven restaurados, incluso con el
    placeholder partido en fragmentos chicos (el caso del bridge). Dos asserts, no uno:
    que el valor vuelva (round-trip) y que ningún token haya salido PARTIDO entre deltas
    (carry-split) — lo segundo es lo que el camino streaming agrega de riesgo propio."""
    mail, body = _pii_body(stream=True)
    with gw.stream("POST", "/v1/messages",
                   headers={"x-api-key": seeded_byok_key}, json=body) as resp:
        if resp.status_code != 200:
            resp.read()
            _skip_solo_si_runtime_caido(resp.status_code, resp.text)
        # Fragmentos SIN concatenar: el borde entre deltas es la evidencia que necesita
        # ``_falla_si_placeholder_partido`` y se pierde al pegar el texto.
        fragmentos = []
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            try:
                d = json.loads(line[6:])
            except ValueError:
                continue
            delta = d.get("delta") or {}
            fragmentos.append((delta.get("text") or "") + (delta.get("thinking") or ""))

    _verifica_round_trip("".join(fragmentos), mail)
    _falla_si_placeholder_partido(fragmentos)


def test_evento_byok_lleva_identidad_y_es_metadata_only(gw, seeded_byok_key_con_user,
                                                       monitor_headers):
    """US3/FR-006 + contrato #8/#9: el evento NUEVO que produce ESTE request lleva
    tenant + tool + client (Connection con User) y conteo de entidades — y el feed
    jamás contiene el valor real (metadata-only). La correlación es por DELTA del
    feed (antes/después), no por 'primer evento que matchee' (review 024)."""
    key, username = seeded_byok_key_con_user
    # El feed exige sesión desde la 027 (hallazgo A1): la virtual key que va al gateway
    # no resuelve a un usuario de sesión, así que la lectura del feed usa la suya.
    antes = gw.get("/events?limit=100", headers=monitor_headers)
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
        feed = gw.get("/events?limit=100", headers=monitor_headers)
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
