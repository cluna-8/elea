import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
from ..database import Base

# UUID fijo del default tenant (spec 013, FR-002): pivote determinista del backfill
# on-premise. Seeds, migraciones y tests lo referencian; NO cambiar.
DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class Tenant(Base):
    """Raíz de la jerarquía Tenant → Group → Client(User) → Connection(APIKey).

    Un tenant es la empresa compradora (Elea, Cámara…). En on-premise hay exactamente
    uno (el default ``…0001``); en cloud SaaS conviven varios aislados por RLS.
    ``slug`` habilita despliegues por cliente como config+seed (Constitución VII).
    """
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    deployment_mode = Column(String, nullable=False, default="on_premise")  # on_premise | cloud

    # Defaults de cascada de contexto (spec 013 US4): raíz de la resolución
    # User > Group > Tenant. La cascada de SecurityPolicy/entity_configs es spec 015.
    default_legal_basis = Column(String, nullable=True)
    default_risk_level = Column(String, nullable=True)
    # FKs circulares suaves (tenants ↔ compliance_projects/security_policies):
    # use_alter + los MISMOS nombres que la migración 010 (que las añade tras poblar),
    # así create_all y autogenerate ven el mismo esquema que produce la 010.
    default_compliance_project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("compliance_projects.id", use_alter=True,
                   name="fk_tenants_default_compliance_project"),
        nullable=True)
    default_security_policy_id = Column(
        UUID(as_uuid=True),
        ForeignKey("security_policies.id", use_alter=True,
                   name="fk_tenants_default_security_policy"),
        nullable=True)

    # Espejo de compresión (mismos knobs que Group, spec 012) como default de tenant
    compression_mode = Column(String, default="off")                 # off | deterministic | headroom
    compression_strategy = Column(String, default="deterministic")   # deterministic | headroom
    compression_threshold_tokens = Column(Integer, nullable=True)
    compression_aggressiveness = Column(String, default="medium")    # low | medium | high
    compression_cache_enabled = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "deployment_mode IN ('on_premise', 'cloud')",
            name="ck_tenants_deployment_mode",
        ),
    )
