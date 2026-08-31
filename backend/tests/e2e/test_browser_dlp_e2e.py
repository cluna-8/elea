"""e2e superficie browser-DLP (spec 019 US3) — HTTP vivo, masking real + monitor.

La extensión MV3 llama ``GET /gw/whoami`` (login del popup, fail-closed) y ``POST
/gw/inspect`` (enmascara el prompt, devuelve ``replacements`` para reescribir el body y
des-enmascarar el DOM). Cada inspect empuja al MISMO feed del monitor con
``surface="browser"`` y audita metadata-only (Constraint C1: la vitrina jamás muestra
PII cruda). Nada mockeado: la key se seedea en la base y el masking corre sobre la
librería ``sentinel_guardian_policy`` real. Ver COORDINATION-019 (asserts T5–T7).
"""
import json

import pytest

EMAIL = "juan.perez@hospital.es"
DNI = "12345678Z"   # DNI español (formato NIF): se reconoce como ES_NIF por formato (#64)


def test_t5_whoami_fail_closed(gw, seeded_byok_key):
    """T5 (whoami fail-closed, SC-005): sin key → 401; key inválida → 401; key seedeada
    → 200 con ``ok=True``. La resolución es real contra la base compartida."""
    assert gw.get("/whoami").status_code == 401
    assert gw.get("/whoami", headers={"X-Sentinel-Key": "sk-sentinel-bad"}).status_code == 401

    ok = gw.get("/whoami", headers={"X-Sentinel-Key": seeded_byok_key})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["ok"] is True, body


def test_t6_inspect_masking_round_trip(gw, seeded_byok_key):
    """T6 (inspect masking round-trip): con la key seedeada, el endpoint enmascara la
    PII (el modelo verá placeholders) y devuelve ``replacements`` token→original con los
    que la extensión reconstruye el texto. Masking real vía la política compartida."""
    resp = gw.post(
        "/inspect",
        headers={"X-Sentinel-Key": seeded_byok_key},
        json={"text": f"Contactá a {EMAIL}, DNI {DNI}"},
    )
    assert resp.status_code == 200, resp.text
    j = resp.json()

    # El upstream (ChatGPT/Claude web) verá placeholders, NUNCA la PII cruda. Nota (#64):
    # el fallback dev `default_analyze` reconoce el DNI español como ES_NIF por formato —
    # ya no lo trocea/mal-etiqueta como PHONE_NUMBER genérico (ver test_route_parity.py).
    assert EMAIL not in j["masked"] and DNI not in j["masked"], j["masked"]
    assert "[EMAIL_ADDRESS_" in j["masked"], j["masked"]

    # replacements = token→original (para des-enmascarar el DOM):
    tokens = {r_["token"]: r_["original"] for r_ in j["replacements"]}
    assert EMAIL in tokens.values() and DNI in tokens.values(), j["replacements"]

    # Reconstrucción real (lo que hace la extensión): masked + replacements → original.
    restored = j["masked"]
    for tok, orig in sorted(tokens.items(), key=lambda kv: -len(kv[1])):
        restored = restored.replace(tok, orig)
    assert EMAIL in restored and DNI in restored, restored

    # entities lleva los tipos detectados (para la vitrina/reportes):
    types = {e["type"] for e in j["entities"]}
    assert "EMAIL_ADDRESS" in types, j["entities"]


def test_t6_inspect_fail_closed(gw):
    """T6-fail-closed: ``POST /inspect`` sin key válida → 401 (nunca enmascara ni audita
    tráfico anónimo). Guard de T6: el 200 de T6 dependía de la key seedeada."""
    resp = gw.post("/inspect", json={"text": f"mi email es {EMAIL}"})
    assert resp.status_code == 401, resp.text


def test_t7_monitor_surface_browser_no_raw_pii(gw, seeded_byok_key, monitor_headers):
    """T7 (monitor C1, surface=browser sin PII cruda): un inspect real publica un evento
    ``surface="browser"`` en el feed; ``GET /events`` lo devuelve. Se afirma (a) hay ≥1
    evento browser y (b) NINGÚN evento expone el email/DNI crudo en su ``masked_preview``
    (C1: la vitrina jamás muestra PII cruda, ni siquiera efímera en Redis).

    El feed es efímero: si Redis está caído y ``/events`` viene vacío, se skipea con
    motivo (no se falla)."""
    # Generar tráfico browser determinístico (no depender del orden de otros tests):
    ins = gw.post(
        "/inspect",
        headers={"X-Sentinel-Key": seeded_byok_key},
        json={"text": f"Contactá a {EMAIL}, DNI {DNI}"},
    )
    assert ins.status_code == 200, ins.text

    # El feed exige sesión desde la 027 (hallazgo A1): una virtual key no alcanza.
    resp = gw.get("/events", params={"limit": 20}, headers=monitor_headers)
    assert resp.status_code == 200, resp.text
    events = resp.json().get("events", [])
    if not events:
        pytest.skip("feed del monitor vacío (Redis no disponible / efímero) — T7 opcional sin feed")

    browser = [e for e in events if e.get("surface") == "browser"]
    assert browser, f"no hay evento surface=browser en el feed: {events}"

    # C1: PII cruda JAMÁS en el preview de ningún evento (browser o motor).
    for e in events:
        preview = e.get("masked_preview") or ""
        assert EMAIL not in preview, f"email crudo en masked_preview: {e}"
        assert DNI not in preview, f"DNI crudo en masked_preview: {e}"
        # Y por las dudas, tampoco en ninguna otra parte del evento serializado:
        blob = json.dumps(e, ensure_ascii=False)
        assert EMAIL not in blob and DNI not in blob, f"PII cruda en el evento: {e}"
