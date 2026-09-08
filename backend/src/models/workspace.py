"""Espacios de trabajo del Hub (spec 043 US1 — T007): la autoridad de pertenencia que hoy no
existe en ningún lado. Ver diagnostico.md de la 043 §1: Eleia Hub nunca supo qué espacio o hilo
pertenece a quién — listaba y proxyaba todo con una única credencial de servicio hacia el motor
de documentos. Estas tres tablas son la fuente de verdad de pertenencia, resuelta en el backend
Guardian (decisión R1 de research.md: no delegar en el multiusuario nativo del motor de
documentos, que corre single-user y cuya API admin no está versionada de forma estable).

Tenant-scoped con RLS forzado, mismo tratamiento que el resto del esquema desde la 010/012/017
(migración 018). Un `Workspace` refleja el `slug` real del motor de documentos; un
`WorkspaceMembership` es la relación usuario↔espacio (dueño o miembro); un `WorkspaceThread`
refleja el hilo real del motor de documentos con dueño explícito — el "hilo principal" de una
persona en un espacio es la fila con `engine_thread_slug IS NULL`.
"""
import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, CheckConstraint, Index, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base
from .tenant import DEFAULT_TENANT_ID

VALID_WORKSPACE_STATUSES = {"active", "unassigned"}
VALID_MEMBERSHIP_ROLES = {"owner", "member"}


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False,
                       default=DEFAULT_TENANT_ID, index=True)
    # slug real en el motor de documentos — único por tenant (UNIQUE compuesto).
    engine_slug = Column(String, nullable=False)
    display_name = Column(String, nullable=False)
    # NULL = "sin asignar" (backfill de instalaciones existentes, FR-006 de la 043; también el
    # estado transitorio cuando se da de baja al dueño, FR-042).
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status = Column(String, nullable=False, default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", foreign_keys=[owner_user_id])
    memberships = relationship("WorkspaceMembership", back_populates="workspace",
                               cascade="all, delete-orphan")
    threads = relationship("WorkspaceThread", back_populates="workspace",
                           cascade="all, delete-orphan")

    __table_args__ = (
        Index("uq_workspaces_tenant_slug", "tenant_id", "engine_slug", unique=True),
        CheckConstraint(
            "status IN ('active', 'unassigned')",
            name="ck_workspaces_status",
        ),
    )


class WorkspaceMembership(Base):
    __tablename__ = "workspace_memberships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False,
                       default=DEFAULT_TENANT_ID, index=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String, nullable=False)  # owner | member
    created_at = Column(DateTime, default=datetime.utcnow)

    workspace = relationship("Workspace", back_populates="memberships")
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("uq_workspace_memberships_workspace_user", "workspace_id", "user_id", unique=True),
        CheckConstraint(
            "role IN ('owner', 'member')",
            name="ck_workspace_memberships_role",
        ),
    )


class WorkspaceThread(Base):
    __tablename__ = "workspace_threads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False,
                       default=DEFAULT_TENANT_ID, index=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    # NULL = hilo principal de esa persona en ese espacio (uno por (workspace, usuario)).
    engine_thread_slug = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    workspace = relationship("Workspace", back_populates="threads")
    owner = relationship("User", foreign_keys=[owner_user_id])

    __table_args__ = (
        Index("uq_workspace_threads_slug", "workspace_id", "owner_user_id",
              "engine_thread_slug", unique=True),
        # Índice parcial (mismo criterio que audit.py:63-64 y tenant.py:33): a lo sumo un hilo
        # principal por (workspace, usuario). Portable a PG13/14 (no depende de NULLS NOT
        # DISTINCT, que es de PG15+) — mismo motivo documentado en la migración 018.
        Index("uq_workspace_threads_principal", "workspace_id", "owner_user_id", unique=True,
              postgresql_where=text("engine_thread_slug IS NULL")),
    )
