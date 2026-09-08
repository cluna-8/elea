"""`X-Guardian-Acting-User` (spec 043 US2, contrato 2) — verificación real end-to-end contra
una DB migrada a head: la cabecera solo se obedece con `can_act_on_behalf=true` en la key Y
el usuario del mismo tenant; en cualquier otro caso el pedido se audita como si no hubiera
llegado. También verifica que `_audit` persiste `acted_for_user_id`/`surface`/
`document_group_id` de verdad en la fila (no solo que los acepta sin romper)."""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from migration_harness import fresh_db, owner_engine, require_postgres, run_alembic

require_postgres()

DB = "sentinel_test_acting_user_header_043"


@pytest.fixture(scope="module")
def factory():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    engine = owner_engine(DB)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    engine.dispose()


def _seed_tenant_user_key(factory, *, can_act_on_behalf, same_tenant_user=True):
    from src.models.tenant import Tenant
    from src.models.user import User
    from src.models.budget import APIKey
    from src.services.key_material import hash_key, key_preview

    db = factory()
    try:
        tenant = Tenant(id=uuid.uuid4(), name="T", slug=f"t-{uuid.uuid4().hex[:6]}")
        other_tenant = Tenant(id=uuid.uuid4(), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}")
        db.add_all([tenant, other_tenant])
        db.flush()

        acting_user = User(
            id=uuid.uuid4(),
            tenant_id=tenant.id if same_tenant_user else other_tenant.id,
            username=f"ana-{uuid.uuid4().hex[:6]}", email=f"{uuid.uuid4().hex[:6]}@x.test",
            password_hash="!", role="client",
        )
        db.add(acting_user)

        plain = f"sk-{uuid.uuid4().hex}"
        key = APIKey(
            id=uuid.uuid4(), tenant_id=tenant.id, key_hash=hash_key(plain),
            key_preview=key_preview(plain), name="svc-key", tool_type="servicio",
            can_act_on_behalf=can_act_on_behalf,
        )
        db.add(key)
        db.commit()
        return plain, str(acting_user.id)
    finally:
        db.close()


@pytest.fixture
def harness(factory, monkeypatch):
    from src.api import gateway
    monkeypatch.setattr(gateway, "SessionLocal", factory)
    import src.api.inspect as inspect_mod
    monkeypatch.setattr(inspect_mod, "SessionLocal", factory)
    return gateway, inspect_mod


def test_header_honrada_cuando_key_autoriza_y_usuario_es_del_tenant(harness, factory):
    gateway, inspect_mod = harness
    plain, user_id = _seed_tenant_user_key(factory, can_act_on_behalf=True)
    ident = gateway._resolve_attribution(plain)
    assert ident["can_act_on_behalf"] is True
    resolved = inspect_mod._resolve_acting_user(ident, user_id)
    assert resolved == user_id


def test_header_ignorada_si_la_key_no_tiene_el_privilegio(harness, factory):
    gateway, inspect_mod = harness
    plain, user_id = _seed_tenant_user_key(factory, can_act_on_behalf=False)
    ident = gateway._resolve_attribution(plain)
    assert ident["can_act_on_behalf"] is False
    assert inspect_mod._resolve_acting_user(ident, user_id) is None


def test_header_ignorada_si_el_usuario_es_de_otro_tenant(harness, factory):
    gateway, inspect_mod = harness
    plain, user_id = _seed_tenant_user_key(factory, can_act_on_behalf=True,
                                            same_tenant_user=False)
    ident = gateway._resolve_attribution(plain)
    assert inspect_mod._resolve_acting_user(ident, user_id) is None


def test_header_con_uuid_invalido_no_rompe(harness, factory):
    gateway, inspect_mod = harness
    plain, _ = _seed_tenant_user_key(factory, can_act_on_behalf=True)
    ident = gateway._resolve_attribution(plain)
    assert inspect_mod._resolve_acting_user(ident, "no-es-un-uuid") is None
    assert inspect_mod._resolve_acting_user(ident, None) is None


def test_audit_persiste_acted_for_user_surface_y_document_group(harness, factory):
    gateway, _ = harness
    plain, user_id = _seed_tenant_user_key(factory, can_act_on_behalf=True)
    ident = gateway._resolve_attribution(plain)
    doc_id = str(uuid.uuid4())

    ok = gateway._audit(ident, "servicio", 0, 0, "passed", [], 10, None,
                        acted_for_user_id=user_id, surface="servicio",
                        document_group_id=doc_id)
    assert ok is True

    db = factory()
    try:
        row = db.execute(text(
            "SELECT acted_for_user_id, surface, event_type, document_group_id, model "
            "FROM audit_logs ORDER BY timestamp DESC LIMIT 1"
        )).fetchone()
        assert str(row.acted_for_user_id) == user_id
        assert row.surface == "servicio"
        assert row.event_type == "traffic"
        assert str(row.document_group_id) == doc_id
        assert row.model == "servicio"
    finally:
        db.close()


def test_audit_sin_los_kwargs_nuevos_no_cambia_de_comportamiento(harness, factory):
    """Los 8 call-sites del passthrough (gateway.py) no pasan estos kwargs — deben seguir
    escribiendo la fila igual que antes de la 043."""
    gateway, _ = harness
    plain, _ = _seed_tenant_user_key(factory, can_act_on_behalf=True)
    ident = gateway._resolve_attribution(plain)
    ok = gateway._audit(ident, "gpt-4o-mini", 10, 20, "passed", [], 5, None)
    assert ok is True

    db = factory()
    try:
        row = db.execute(text(
            "SELECT acted_for_user_id, surface, event_type, document_group_id, model "
            "FROM audit_logs ORDER BY timestamp DESC LIMIT 1"
        )).fetchone()
        assert row.acted_for_user_id is None
        assert row.surface is None
        assert row.event_type == "traffic"
        assert row.document_group_id is None
        assert row.model == "gpt-4o-mini"
    finally:
        db.close()
