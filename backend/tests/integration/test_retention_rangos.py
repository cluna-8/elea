"""Validación de rangos de retención en ``PUT /compliance/retention`` (spec 018 FR-007, T015).

Ejercita el endpoint REAL contra Postgres real (mismo patrón que los contract tests de
gobernanza: app FastAPI montada sobre una DB fresca migrada a head, `get_db` overrideado).

Cubre lo que exige el encargo:

- **por CLASE**: el mínimo de cada una de las 4 clases del clasificador.
- **por TIER**: estándar (sin fila) y estricto (con la capa `enforcement_tier_estricto` on),
  incluida la MISMA entrada que pasa en un tier y se rechaza en el otro.
- **el 422 y su detalle**: el piso/tope concreto y la clase viajan en el `detail`.
- **el tope de `prompt_content`**: los DOS bordes (mínimo 1 y tope 365/90), por privacidad el
  contenido no puede retenerse MÁS.
- **el caso feliz**: un valor válido pasa (200) y se persiste.

El tier vigente se resuelve por el camino existente (`resolve_tenant_profile`); acá se lo
gobierna sembrando la fila `tenant_default → enforcement_tier_estricto = on` del tenant por
defecto, que es el alcance que gobierna una retención global/single-tenant (el endpoint no
recibe tenant). No toca el piso del purgador (`PLAZO_MINIMO_DIAS`): T015 se apila encima.
"""
import sys
from pathlib import Path

import pytest

# Los harness de DB viven en ``tests/`` y ``tests/integration/``; desde acá se agregan al path
# igual que hacen los contract tests de gobernanza.
_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import admin_headers, build_app_client  # noqa: E402

require_postgres()

DB = "sentinel_test_retention_rangos"


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    headers = admin_headers(client)
    yield client, factory, headers
    cleanup()


@pytest.fixture(autouse=True)
def _sin_tier(harness):
    """Cada test arranca en estándar (sin fila de tier). Sin esta limpieza, la fila `on` de un
    test de estricto se filtraría al siguiente y cambiaría el piso resuelto sin que se note."""
    _, factory, _ = harness
    yield
    from src.models.governance import GovernanceProfile
    db = factory()
    try:
        db.query(GovernanceProfile).delete()
        db.commit()
    finally:
        db.close()


def set_tier_estricto(factory):
    """Siembra el tier `estricto` de la instalación: fila `tenant_default → *` de la capa
    `enforcement_tier_estricto = on` para el tenant por defecto."""
    from src.models.governance import GovernanceProfile
    db = factory()
    try:
        db.add(GovernanceProfile(
            scope_type="tenant_default", scope_value="*",
            layer_key="enforcement_tier_estricto", decision="on", updated_by="test"))
        db.commit()
    finally:
        db.close()


def put_retention(client, headers, log_type, retention_days):
    return client.put("/api/v1/compliance/retention", headers=headers,
                      json=[{"log_type": log_type, "retention_days": retention_days,
                             "justification": "test", "updated_by": "admin"}])


def get_retention_map(client, headers):
    resp = client.get("/api/v1/compliance/retention", headers=headers)
    assert resp.status_code == 200, resp.text
    return {r["log_type"]: r["retention_days"] for r in resp.json()}


# ── Estándar (default, sin fila de tier): mínimo por clase ─────────────────────────


@pytest.mark.parametrize("log_type,minimo", [
    ("config_audit", 365),      # piso legal vigente — preservado exactamente
    ("security_events", 30),
    ("usage_metadata", 30),
])
def test_estandar_minimo_por_clase(harness, log_type, minimo):
    client, _, headers = harness

    bajo = put_retention(client, headers, log_type, minimo - 1)
    assert bajo.status_code == 422, bajo.text
    detalle = bajo.json()["detail"]
    assert log_type in detalle and str(minimo) in detalle, detalle

    ok = put_retention(client, headers, log_type, minimo)
    assert ok.status_code == 200, ok.text


def test_estandar_prompt_content_minimo_1_y_tope_365(harness):
    """`prompt_content` tiene mínimo (1) Y tope (365 en estándar): ambos bordes se validan."""
    client, _, headers = harness

    assert put_retention(client, headers, "prompt_content", 0).status_code == 422
    sobre = put_retention(client, headers, "prompt_content", 366)
    assert sobre.status_code == 422, sobre.text
    assert "prompt_content" in sobre.json()["detail"] and "365" in sobre.json()["detail"]

    assert put_retention(client, headers, "prompt_content", 1).status_code == 200
    assert put_retention(client, headers, "prompt_content", 365).status_code == 200


# ── Estricto (fila `enforcement_tier_estricto = on`): los mínimos suben ────────────


@pytest.mark.parametrize("log_type,minimo", [
    ("config_audit", 730),
    ("security_events", 365),
    ("usage_metadata", 365),
])
def test_estricto_minimo_por_clase(harness, log_type, minimo):
    client, factory, headers = harness
    set_tier_estricto(factory)

    bajo = put_retention(client, headers, log_type, minimo - 1)
    assert bajo.status_code == 422, bajo.text
    detalle = bajo.json()["detail"]
    assert log_type in detalle and str(minimo) in detalle, detalle

    ok = put_retention(client, headers, log_type, minimo)
    assert ok.status_code == 200, ok.text


def test_estricto_prompt_content_tope_90(harness):
    """En estricto el tope de `prompt_content` baja a 90 días (privacidad); el mínimo sigue 1."""
    client, factory, headers = harness
    set_tier_estricto(factory)

    sobre = put_retention(client, headers, "prompt_content", 91)
    assert sobre.status_code == 422, sobre.text
    assert "prompt_content" in sobre.json()["detail"] and "90" in sobre.json()["detail"]

    assert put_retention(client, headers, "prompt_content", 0).status_code == 422
    assert put_retention(client, headers, "prompt_content", 90).status_code == 200


# ── El tier CAMBIA el veredicto sobre la MISMA entrada ────────────────────────────


def test_config_audit_365_pasa_en_estandar_y_se_rechaza_en_estricto(harness):
    """La consecuencia observable del tier (US2 Independent Test): un mismo valor que en
    estándar se acepta, en estricto se rechaza — el piso vigente lo fija el tier resuelto."""
    client, factory, headers = harness

    assert put_retention(client, headers, "config_audit", 365).status_code == 200

    set_tier_estricto(factory)
    estricto = put_retention(client, headers, "config_audit", 365)
    assert estricto.status_code == 422, estricto.text
    assert "730" in estricto.json()["detail"]


def test_prompt_content_300_pasa_en_estandar_y_se_rechaza_en_estricto(harness):
    """Contracara sobre el TOPE: 300 d de contenido es legal en estándar (≤ 365) y prohibido en
    estricto (> 90)."""
    client, factory, headers = harness

    assert put_retention(client, headers, "prompt_content", 300).status_code == 200

    set_tier_estricto(factory)
    estricto = put_retention(client, headers, "prompt_content", 300)
    assert estricto.status_code == 422, estricto.text
    assert "90" in estricto.json()["detail"]


# ── El 422 no escribe nada + caso feliz persiste ──────────────────────────────────


def test_422_no_persiste_ninguna_fila_del_lote(harness):
    """Un lote con una entrada válida seguida de una inválida se rechaza ENTERO: la validación
    corre antes de commitear, así que ni la fila válida queda escrita."""
    client, factory, headers = harness
    antes = get_retention_map(client, headers)

    resp = client.put("/api/v1/compliance/retention", headers=headers, json=[
        {"log_type": "usage_metadata", "retention_days": 999, "updated_by": "admin"},
        {"log_type": "security_events", "retention_days": 5, "updated_by": "admin"},  # < 30
    ])
    assert resp.status_code == 422, resp.text

    despues = get_retention_map(client, headers)
    assert despues == antes, "el 422 no debe dejar escrita ni la fila válida del mismo lote"


def test_caso_feliz_persiste_y_se_lee(harness):
    """Un valor válido responde 200 y queda persistido (se relee por GET)."""
    client, _, headers = harness

    resp = put_retention(client, headers, "usage_metadata", 400)
    assert resp.status_code == 200, resp.text
    devuelto = {r["log_type"]: r["retention_days"] for r in resp.json()}
    assert devuelto["usage_metadata"] == 400

    assert get_retention_map(client, headers)["usage_metadata"] == 400
