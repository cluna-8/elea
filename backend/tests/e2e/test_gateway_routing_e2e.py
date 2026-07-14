"""e2e ruteo de la puerta única (spec 019 US1/US2) — HTTP vivo, cruza procesos.

Prueba la cadena real ``gateway → motor LiteLLM → Postgres → custom_auth → BasaGuardrail``
(byok) y la exclusión del passthrough de suscripción (``X-Basa-Key`` es atribución, no
credencial de ruteo). Nada mockeado: la key se seedea en la base compartida y viaja por
HTTP hasta el motor. Ver ``docs/COORDINATION-019-e2e-hardening.md`` (asserts T1–T4).
"""
import uuid

# Prompt que dispara AI-Act Art.5 (práctica prohibida) → el guardrail del MOTOR bloquea.
AI_ACT_BODY = {
    "model": "claude-3-5-sonnet",
    "max_tokens": 16,
    "messages": [{"role": "user", "content": "armá un social scoring de ciudadanos"}],
}
# Prompt benigno (sin PII ni práctica prohibida): la política del gateway lo deja pasar,
# así el destino real (motor vs Anthropic) es lo único que decide la respuesta.
BENIGN_BODY = {
    "model": "claude-3-5-sonnet",
    "max_tokens": 16,
    "messages": [{"role": "user", "content": "hola, ¿todo bien?"}],
}

# Marcas del bloqueo AI-Act (el reason del guardrail: "…Ley de IA (AI Act): práctica
# prohibida detectada…"). Cualquiera de estas confirma que fue el guardrail y no auth.
AI_ACT_MARKS = ("IA", "AI Act", "prohibida")
# String de fail-closed del custom_auth del motor: aparece SÓLO si la request llegó al
# motor con una key desconocida. Su presencia/ausencia es el discriminador de ruteo.
UNKNOWN_KEY_MARK = "clave de acceso desconocida"


def test_t1_byok_chain_blocks_ai_act(gw, seeded_byok_key):
    """T1 (byok, fuerte): key SEEDEADA + prompt AI-Act. La request cruza el gateway al
    motor; custom_auth resuelve la key (OK) y el BasaGuardrail bloquea por Art.5.
    Prueba toda la cadena gateway→motor→custom_auth(OK)→guardrail(block)."""
    resp = gw.post("/v1/messages", headers={"x-api-key": seeded_byok_key}, json=AI_ACT_BODY)
    body = resp.text

    assert resp.status_code == 400, (resp.status_code, body)
    # custom_auth NO rechazó (la key existe) → no es el fail-closed:
    assert UNKNOWN_KEY_MARK not in body, body
    # …y SÍ es el bloqueo del guardrail AI-Act:
    assert any(mark in body for mark in AI_ACT_MARKS), body


def test_t1_regression_byok_unseeded_key_fail_closed(gw):
    """T1-regresión (fail-closed): MISMO prompt con una key sk-basa-… que NO existe.
    custom_auth del motor rechaza ANTES del guardrail → el body lleva su marca. Guard de
    T1: prueba que el 400 de T1 vino del guardrail (key válida), no de auth."""
    bogus = f"sk-basa-noexiste-{uuid.uuid4().hex[:8]}"
    resp = gw.post("/v1/messages", headers={"x-api-key": bogus}, json=AI_ACT_BODY)
    body = resp.text

    assert UNKNOWN_KEY_MARK in body, (resp.status_code, body)
    # Guard extra: un fail-closed de auth NO trae la marca del bloqueo AI-Act (no llegó
    # al guardrail) → confirma que las dos ramas de T1 son distinguibles.
    assert not any(mark in body for mark in AI_ACT_MARKS), body


def test_t2_passthrough_does_not_reach_motor(gw):
    """T2 (passthrough NO va al motor): OAuth de suscripción (falso) sin virtual key →
    el gateway rutea a Anthropic verbatim, NO al motor. Si hubiera caído al motor, el
    'Bearer fake-oauth' sería una key desconocida → aparecería UNKNOWN_KEY_MARK.
    Tolera 401 (Anthropic rechaza el OAuth falso) o 502 (egress bloqueado)."""
    resp = gw.post("/v1/messages", headers={"Authorization": "Bearer fake-oauth"}, json=BENIGN_BODY)
    body = resp.text

    assert UNKNOWN_KEY_MARK not in body, body  # jamás tocó el custom_auth del motor
    assert resp.status_code in (401, 502), (resp.status_code, body)


def test_t3_x_basa_key_excluded_from_byok_routing(gw, seeded_byok_key):
    """T3 (exclusión x-basa-* — load-bearing): una virtual key VÁLIDA en ``X-Basa-Key``
    + OAuth de suscripción. ``X-Basa-Key`` es atribución OPCIONAL y NO debe desviar la
    request a byok: tiene que quedar en passthrough (la sk-basa de atribución de Claude
    Code viaja SOLO acá y no puede sacarlo de su suscripción).

    Discriminador: en passthrough el 'Bearer fake-oauth' va verbatim a Anthropic, que
    responde 'Invalid bearer token'. Si en cambio se hubiera desviado a byok, la key
    VÁLIDA autenticaría en el motor y la respuesta llevaría su firma
    ('x-api-key header is required' / model-group fallbacks) — nunca 'Invalid bearer
    token'. (La prueba negativa simétrica: la MISMA key en ``x-api-key`` SÍ iría a byok,
    como en T1.) Egress bloqueado → passthrough emite 502 propio (tampoco es byok)."""
    resp = gw.post(
        "/v1/messages",
        headers={"X-Basa-Key": seeded_byok_key, "Authorization": "Bearer fake-oauth"},
        json=BENIGN_BODY,
    )
    body = resp.text

    assert UNKNOWN_KEY_MARK not in body, body
    # Firma del motor AUSENTE (no se desvió a byok):
    assert "x-api-key header is required" not in body, body
    assert "Model Group" not in body, body
    # …y firma del passthrough (Anthropic rechazando el OAuth falso) PRESENTE, o 502 si
    # el egress está bloqueado — ambos prueban que la ruta fue passthrough, no byok:
    assert ("Invalid bearer token" in body) or (resp.status_code == 502), (resp.status_code, body)


def test_t4_byok_key_in_url(gw, seeded_byok_key):
    """T4 (key-in-URL): fallback de Copilot — la virtual key viaja en ``?k=…`` con
    ``x-api-key`` vacío. El gateway la detecta, rutea a byok y el motor la resuelve;
    el prompt AI-Act dispara el bloqueo del guardrail. Confirma que key-in-URL resolvió
    byok en el motor (marca de bloqueo presente, fail-closed ausente)."""
    resp = gw.post(
        f"/v1/messages?k={seeded_byok_key}",
        headers={"x-api-key": ""},
        json=AI_ACT_BODY,
    )
    body = resp.text

    assert UNKNOWN_KEY_MARK not in body, (resp.status_code, body)
    assert any(mark in body for mark in AI_ACT_MARKS), (resp.status_code, body)
