"""Bug real encontrado en revisión (09-sep): `document_id` es "opcional, efímero,
generado por el cliente" (docstring de `PlaceholderMap`) — no se garantiza que sea un
UUID. Antes, un `document_id` no-UUID hacía que `gateway._audit()` lanzara `ValueError`
DENTRO del `try` que escribe la fila entera, y el `except Exception` genérico tumbaba TODA
la fila de auditoría (no solo el campo) — un evento con PII de por medio quedaba sin
auditar, en silencio. Ahora se parsea ANTES, fuera del try grande, y se degrada solo ese
campo a NULL si no es un UUID válido — la fila se sigue escribiendo."""
import uuid

import pytest

from migration_harness import fresh_db, owner_engine, require_postgres, run_alembic

require_postgres()

DB = "sentinel_test_gateway_audit_document_id_degrade"


@pytest.fixture(scope="module")
def factory():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    from sqlalchemy.orm import sessionmaker
    engine = owner_engine(DB)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    engine.dispose()


def _ident():
    return {
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "api_key_id": None, "user_id": None, "group_id": None,
    }


def test_document_id_no_uuid_no_pierde_la_fila_entera(factory, monkeypatch):
    from src.api import gateway

    monkeypatch.setattr(gateway, "SessionLocal", factory)

    escrita = gateway._audit(
        _ident(), "servicio", 0, 0, "passed", [], 10,
        document_group_id="no-es-un-uuid-real",
    )
    assert escrita is True, "la fila entera no debe perderse por un document_id inválido"

    db = factory()
    try:
        from src.models.audit import AuditLog
        fila = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).first()
        assert fila is not None
        assert fila.document_group_id is None, \
            "solo el campo document_group_id debe degradar a NULL, no perderse la fila"
        assert fila.compliance_status == "passed"
    finally:
        db.close()


def test_document_id_uuid_valido_se_guarda(factory, monkeypatch):
    from src.api import gateway

    monkeypatch.setattr(gateway, "SessionLocal", factory)
    doc_id = str(uuid.uuid4())

    escrita = gateway._audit(
        _ident(), "servicio", 0, 0, "passed", [], 10,
        document_group_id=doc_id,
    )
    assert escrita is True

    db = factory()
    try:
        from src.models.audit import AuditLog
        fila = db.query(AuditLog).filter(AuditLog.document_group_id == uuid.UUID(doc_id)).first()
        assert fila is not None
    finally:
        db.close()
