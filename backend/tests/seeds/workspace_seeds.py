"""Helpers de seed para tests de espacios/membresías/cuentas de servicio (spec 043 — T003).

Sigue el mismo patrón que ``seed_key()`` en ``tests/unit/test_api_key_expiry.py``: recibe una
``factory`` (sessionmaker) ya apuntada a una DB de test migrada a head vía
``migration_harness.fresh_db``/``run_alembic`` — no usa ``conftest.py`` porque el patrón real
del repo es "cada módulo crea su propia DB descartable", no fixtures globales compartidas.
"""
import uuid
from datetime import datetime


def seed_user(factory, *, username=None, role="client", account_type="person",
              tenant_id=None, group_id=None, deactivated_at=None):
    from src.models.user import User
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    try:
        row = User(
            id=uuid.uuid4(),
            tenant_id=tenant_id or DEFAULT_TENANT_ID,
            username=username or f"user-{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:8]}@example.test",
            password_hash="!",  # nunca se autentica con password en estos tests
            role=role,
            account_type=account_type,
            group_id=group_id,
            deactivated_at=deactivated_at,
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def seed_workspace(factory, *, engine_slug=None, display_name="Espacio de prueba",
                   owner_user_id=None, status="active", tenant_id=None):
    from src.models.workspace import Workspace
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    try:
        row = Workspace(
            id=uuid.uuid4(),
            tenant_id=tenant_id or DEFAULT_TENANT_ID,
            engine_slug=engine_slug or f"ws-{uuid.uuid4().hex[:8]}",
            display_name=display_name,
            owner_user_id=owner_user_id,
            status=status,
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def seed_membership(factory, *, workspace_id, user_id, role="member", tenant_id=None):
    from src.models.workspace import WorkspaceMembership
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    try:
        row = WorkspaceMembership(
            id=uuid.uuid4(),
            tenant_id=tenant_id or DEFAULT_TENANT_ID,
            workspace_id=workspace_id,
            user_id=user_id,
            role=role,
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def seed_thread(factory, *, workspace_id, owner_user_id, engine_thread_slug=None,
                tenant_id=None):
    from src.models.workspace import WorkspaceThread
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    try:
        row = WorkspaceThread(
            id=uuid.uuid4(),
            tenant_id=tenant_id or DEFAULT_TENANT_ID,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            engine_thread_slug=engine_thread_slug,
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()
