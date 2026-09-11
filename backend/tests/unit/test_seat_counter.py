"""Unit tests del contador de seats (spec 021, T013 — [D-021]/FR-013/FR-014).

seat = Connection ACTIVA no expirada, POR tenant. Excluye revocadas
(is_active=False) y expiradas (expires_at pasado); aislado entre tenants.
"""
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from migration_harness import DEFAULT_TENANT, fresh_db, owner_engine, require_postgres, run_alembic

require_postgres()

DB = "sentinel_test_seat_counter"

OTHER_TENANT = uuid.UUID("22222222-0000-0000-0000-000000000002")


@pytest.fixture(scope="module")
def factory():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    engine = owner_engine(DB)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    engine.dispose()


def _key(db, *, tenant_id=None, is_active=True, expires_at=None, tool="claude-code"):
    from src.models.budget import APIKey
    row = APIKey(
        name=f"k-{uuid.uuid4().hex[:8]}",
        key_hash=f"hash-{uuid.uuid4()}",
        key_preview="sk-...x",
        tool_type=tool,
        is_active=is_active,
        expires_at=expires_at,
    )
    if tenant_id is not None:
        row.tenant_id = tenant_id
    db.add(row)
    return row


def test_counts_only_active_non_expired_per_tenant(factory):
    from src.licensing.seat_counter import count_active_seats
    from src.models.tenant import Tenant
    db = factory()
    try:
        db.add(Tenant(id=OTHER_TENANT, name="Otro", slug="otro"))
        db.flush()
        now = datetime.utcnow()
        # tenant default: 2 activas + 1 revocada + 1 expirada + 1 activa con expiry futuro
        _key(db)
        _key(db, tool="cursor")
        _key(db, is_active=False)
        _key(db, expires_at=now - timedelta(days=1))
        _key(db, tool="copilot", expires_at=now + timedelta(days=30))
        # otro tenant: 1 activa (no debe contaminar el conteo del default)
        _key(db, tenant_id=OTHER_TENANT)
        db.commit()

        assert count_active_seats(db, DEFAULT_TENANT) == 3
        assert count_active_seats(db, OTHER_TENANT) == 1
        # tenant sin seats → 0 (no None)
        assert count_active_seats(db, uuid.uuid4()) == 0
    finally:
        db.close()


def test_llaves_de_cuentas_de_servicio_no_ocupan_asiento(factory):
    """Spec 043 (US4, T046): las llaves de `svc.anythingllm-provider`/`svc.rag-masking`
    (o cualquier usuario `account_type='service'`) NO cuentan como seat — sin esto, cada
    cliente de Eleia paga 2 asientos de licencia por cuentas que ningún humano usa."""
    from src.licensing.seat_counter import count_active_seats
    from src.models.user import User
    db = factory()
    try:
        persona = User(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT,
                       username=f"persona-{uuid.uuid4().hex[:6]}",
                       email=f"{uuid.uuid4().hex[:6]}@x.test", password_hash="!",
                       role="client", account_type="person")
        servicio = User(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT,
                        username=f"svc.rag-masking-{uuid.uuid4().hex[:6]}",
                        email=f"{uuid.uuid4().hex[:6]}@x.test", password_hash="!",
                        role="client", account_type="service")
        db.add_all([persona, servicio])
        db.flush()

        antes = count_active_seats(db, DEFAULT_TENANT)

        k_persona = _key(db)
        k_persona.user_id = persona.id
        k_servicio = _key(db, tool="servicio")
        k_servicio.user_id = servicio.id
        k_huerfana = _key(db)  # sin user_id — debe seguir contando igual que hoy
        db.commit()

        despues = count_active_seats(db, DEFAULT_TENANT)
        # +2: la de la persona y la huérfana. La de la cuenta de servicio NO suma.
        assert despues == antes + 2
    finally:
        db.close()
