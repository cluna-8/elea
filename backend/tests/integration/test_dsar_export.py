"""DSAR export (GDPR Art. 15/20) — el fix del 500 de nacimiento (#193 / #62).

`GET /api/v1/reports/dsar/{subject_identifier}` respondía **500 a CUALQUIER rol**, admin
incluido: `reports.py` pasaba el `str` de Python a `.cast()` donde SQLAlchemy espera un
`TypeEngine`, así que la query ni compilaba — fallaba antes de mirar datos o rol. El fix es
`cast(User.id, String)`.

Este archivo lo fija de punta a punta contra Postgres real, que es lo que pedía #62: un
sujeto real (por username Y por su UUID —la rama del cast, el corazón del bug— con su fila de
auditoría en el CSV) y uno inexistente (CSV vacío). Antes del fix, los tres eran 500.
"""
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import admin_headers, build_app_client  # noqa: E402

require_postgres()

DB = "sentinel_test_dsar_export"
DSAR = "/api/v1/reports/dsar"


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    client.headers.update(admin_headers(client))
    sujeto = _sembrar_sujeto_con_log(factory)
    yield client, sujeto
    cleanup()


def _sembrar_sujeto_con_log(factory):
    """Un sujeto (User) con UNA fila de auditoría suya, por base directa.

    Devuelve `(username, id_str, marca_modelo)`: la marca del modelo es un literal único que
    los asserts buscan en el CSV para probar que la fila del sujeto viajó — y no otra."""
    from src.models.audit import AuditLog
    from src.models.tenant import DEFAULT_TENANT_ID
    from src.models.user import User

    username = f"sujeto-dsar-{uuid.uuid4().hex[:8]}"
    marca_modelo = f"modelo-dsar-{uuid.uuid4().hex[:8]}"
    uid = uuid.uuid4()
    db = factory()
    try:
        db.add(User(
            id=uid, tenant_id=DEFAULT_TENANT_ID, username=username,
            email=f"{username}@sentinel.com.ar", password_hash="x", role="compliance_officer",
        ))
        db.add(AuditLog(
            id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, timestamp=datetime.utcnow(),
            user_id=uid, model=marca_modelo, prompt_tokens=1, completion_tokens=1, cost_usd=0,
            pii_detected=False, compliance_status="passed", latency_ms=7, guardian_events=[],
        ))
        db.commit()
        return username, str(uid), marca_modelo
    finally:
        db.close()


def test_export_por_username_es_200_con_la_fila_del_sujeto(harness):
    """Sujeto real por username: 200 + CSV con su fila (antes del fix: 500)."""
    client, (username, _id, marca) = harness
    r = client.get(f"{DSAR}/{username}")
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers["content-type"]
    assert marca in r.text, "la fila del sujeto tiene que viajar en su propio export"


def test_export_por_id_es_200_ejercita_el_cast(harness):
    """Sujeto real por su UUID: 200 + su fila. Es la rama `cast(User.id, String)` que hacía
    reventar la query — el corazón del bug #193; que dé 200 acá es lo que lo prueba."""
    client, (_username, id_str, marca) = harness
    r = client.get(f"{DSAR}/{id_str}")
    assert r.status_code == 200, r.text
    assert marca in r.text


def test_export_de_sujeto_inexistente_es_200_csv_vacio(harness):
    """Sujeto inexistente: 200 con CSV (vacío), NO 500. Antes del fix era 500 como cualquiera."""
    client, _ = harness
    r = client.get(f"{DSAR}/no-existe-{uuid.uuid4().hex}")
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers["content-type"]
