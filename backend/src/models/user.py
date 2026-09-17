import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base
from .tenant import DEFAULT_TENANT_ID

VALID_ROLES = {"super_admin", "tenant_admin", "compliance_officer", "client", "lectura"}

# Mapeo de roles legacy → (rol canónico, display_label), espejo del backfill de la
# migración 010 (spec 013 US2, [D9]). Lo usan los bordes de la API para aceptar
# payloads legacy sin violar el CHECK ck_users_role.
LEGACY_ROLE_MAP = {
    "admin": ("tenant_admin", None),
    "clinician": ("client", "clinician"),
    "developer": ("client", "developer"),
}


def normalize_legacy_role(role: str, display_label=None):
    """Devuelve (role_canónico, display_label) aceptando nombres legacy.

    Roles fuera del enum y del mapeo legacy levantan ValueError (el CHECK de DB los
    rechazaría igual; acá damos un error de validación legible).
    """
    if role in VALID_ROLES:
        return role, display_label
    if role in LEGACY_ROLE_MAP:
        canonical, label = LEGACY_ROLE_MAP[role]
        return canonical, display_label or label
    raise ValueError(
        f"Rol '{role}' inválido. Válidos: {sorted(VALID_ROLES)} (o legacy: {sorted(LEGACY_ROLE_MAP)})"
    )


class Group(Base):
    __tablename__ = "groups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # default Python-side al tenant …0001: los code paths heredados (on-prem) no setean
    # tenant_id; en cloud la identidad lo setea explícito y RLS WITH CHECK rechaza cruces.
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False,
                       default=DEFAULT_TENANT_ID, index=True)
    name = Column(String, nullable=False, index=True)  # UNIQUE compuesto (tenant_id, name)
    description = Column(String, nullable=True)
    engine_team_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Spec 054 (17-sep): hasta acá un equipo se podía crear pero nunca dar de baja — "es
    # un error grave" (el dueño, tras probar en vivo). Mismo criterio que `User.is_active`/
    # `deactivated_at`: NO es baja física, la auditoría histórica del grupo sigue visible
    # bajo su nombre (`audit_logs.user_group_id`, `budgets.group_id` no se tocan).
    is_active = Column(Boolean, nullable=False, default=True)
    deactivated_at = Column(DateTime, nullable=True)

    # Compliance profile fields (Feature 006)
    default_legal_basis = Column(String, nullable=True)       # e.g. art_9_2_h
    default_risk_level = Column(String, nullable=True)        # e.g. high_risk_annex3
    compliance_project_id = Column(UUID(as_uuid=True), ForeignKey("compliance_projects.id"), nullable=True)

    # Compresión de contexto por grupo (spec 012 US4) — override del flag global
    compression_mode = Column(String, default="off")              # off | deterministic | headroom
    compression_strategy = Column(String, default="deterministic")  # deterministic | headroom
    compression_threshold_tokens = Column(Integer, nullable=True)   # None -> default del servicio
    compression_aggressiveness = Column(String, default="medium")   # low | medium | high
    compression_cache_enabled = Column(Boolean, default=False)

    # Relationships
    users = relationship("User", back_populates="group")
    api_keys = relationship("APIKey", back_populates="group")
    budgets = relationship("Budget", back_populates="group")
    compliance_project = relationship("ComplianceProject", foreign_keys=[compliance_project_id])

    __table_args__ = (
        # Index(unique=True): mismo objeto que crea la migración 010 (CREATE UNIQUE
        # INDEX), para que ORM y esquema real no diverjan.
        Index("uq_groups_tenant_name", "tenant_id", "name", unique=True),
    )

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False,
                       default=DEFAULT_TENANT_ID, index=True)
    username = Column(String, nullable=False, index=True)  # UNIQUE compuesto (tenant_id, username)
    email = Column(String, nullable=False)                 # UNIQUE compuesto (tenant_id, email)
    password_hash = Column(String, nullable=False)
    # Enum reconciliado (spec 013 US2, Constitución [D9]); CHECK en DB.
    # super_admin NO se autogenera por migración: se siembra aparte, solo cloud.
    role = Column(String, nullable=False)  # super_admin | tenant_admin | compliance_officer | client | lectura
    # Labels sectoriales legacy (clinician/developer) degradados a etiqueta de display
    display_label = Column(String, nullable=True)
    # El "client" (Constitución IV) es User role='client' + client_type: describe CÓMO
    # consume la persona; la herramienta concreta (tool_type) vive en la Connection.
    client_type = Column(String, nullable=True)  # base_url | desktop | chat_ui — solo role='client'
    group_id = Column(UUID(as_uuid=True), ForeignKey("groups.id"), nullable=True)
    engine_user_id = Column(String, nullable=True, index=True)
    is_active = Column(Boolean, default=True)

    # Spec 043 US4/US5 (T008): distingue personas de cuentas de servicio (las que crea el
    # instalador — `svc.anythingllm-provider`, `svc.rag-masking` — que hoy se listaban como
    # usuarios humanos, ver diagnostico.md §4). `deactivated_at` es la BAJA definitiva
    # (revoca llaves/sesiones, libera asiento) — distinta de `is_active` (suspensión
    # reversible ya existente). Ninguna de las dos reescribe la otra.
    account_type = Column(String, nullable=False, default="person")  # person | service
    deactivated_at = Column(DateTime, nullable=True)
    deactivated_reason = Column(String, nullable=True)

    # Individual compliance override (takes precedence over group defaults)
    legal_basis = Column(String, nullable=True)
    risk_level = Column(String, nullable=True)
    compliance_project_id = Column(UUID(as_uuid=True), ForeignKey("compliance_projects.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    group = relationship("Group", back_populates="users")
    api_keys = relationship("APIKey", back_populates="user")
    budgets = relationship("Budget", back_populates="user")
    # foreign_keys explícito (spec 043 T009): AuditLog ganó un segundo FK a users
    # (acted_for_user_id), así que SQLAlchemy ya no puede inferir solo cuál de los dos usa
    # esta relación — sin esto, `AmbiguousForeignKeysError` en cualquier query sobre User.
    audit_logs = relationship("AuditLog", back_populates="user",
                              foreign_keys="AuditLog.user_id")
    consent_records = relationship("ConsentRecord", back_populates="user")
    compliance_project = relationship("ComplianceProject", foreign_keys=[compliance_project_id])

    __table_args__ = (
        Index("uq_users_tenant_username", "tenant_id", "username", unique=True),
        Index("uq_users_tenant_email", "tenant_id", "email", unique=True),
        CheckConstraint(
            "role IN ('super_admin', 'tenant_admin', 'compliance_officer', 'client', 'lectura')",
            name="ck_users_role",
        ),
        CheckConstraint(
            "client_type IS NULL OR client_type IN ('base_url', 'desktop', 'chat_ui')",
            name="ck_users_client_type",
        ),
        CheckConstraint(
            "client_type IS NULL OR role = 'client'",
            name="ck_users_client_type_role",
        ),
        CheckConstraint(
            "account_type IN ('person', 'service')",
            name="ck_users_account_type",
        ),
    )
