import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Numeric, BigInteger, Integer, CheckConstraint, Index, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base
from .tenant import DEFAULT_TENANT_ID

class Budget(Base):
    __tablename__ = "budgets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False,
                       default=DEFAULT_TENANT_ID, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    group_id = Column(UUID(as_uuid=True), ForeignKey("groups.id"), nullable=True)
    # El TECHO lo escribe un humano en dólares con centavos: (10,4) le sobra.
    max_spend_usd = Column(Numeric(10, 4), nullable=False)
    # El CONTADOR acumula pedidos reales, y con (10,4) una llamada barata de verdad
    # (~$0.000012 con gpt-4o-mini) redondeaba a 0.0000: el gasto quedaba congelado y el
    # enforcement que lo lee nunca llegaba al techo. 8 decimales = migración 014 (#76).
    current_spend_usd = Column(Numeric(14, 8), default=0)
    max_tokens = Column(BigInteger, nullable=False)
    current_tokens = Column(BigInteger, default=0)
    reset_period = Column(String, nullable=False) # daily, weekly, monthly, never
    last_reset_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="budgets")
    group = relationship("Group", back_populates="budgets")

class APIKey(Base):
    """Virtual key por herramienta. Naming público/UI: **Connection** (white-label, VII).

    Spec 013 US5 la extiende como la Connection de la jerarquía
    Tenant → Group → Client(User) → Connection: identidad por ``key_hash`` (UNIQUE
    **global**: material secreto, una colisión debe ser global), ≤1 Connection activa
    por herramienta por client (UNIQUE ``(tenant_id, user_id, tool_type)``).
    La gobernanza legal vive en el User (FR-016); acá viven los toggles operativos
    por-key con semántica **NULL = heredar** del group/tenant (nunca NULL = off).
    """
    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False,
                       default=DEFAULT_TENANT_ID, index=True)
    key_hash = Column(String, unique=True, nullable=False, index=True)
    key_preview = Column(String, nullable=False)
    engine_key_token = Column(String, nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    group_id = Column(UUID(as_uuid=True), ForeignKey("groups.id"), nullable=True)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True)
    rpm_limit = Column(Integer, default=60)
    tpm_limit = Column(Integer, default=100000)
    # Legacy pre-013. FR-016: la gobernanza legal (compliance_project/legal_basis) se
    # resuelve desde el User (cascada de contexto), NUNCA desde la Connection; este
    # campo queda por compatibilidad y no participa de la resolución.
    compliance_project_id = Column(UUID(as_uuid=True), ForeignKey("compliance_projects.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Connection (spec 013 US5): herramienta concreta que consume esta key.
    # default 'claude-code' mantiene vivos los code paths heredados que no lo setean.
    tool_type = Column(String, nullable=False, default="claude-code")
    # byok: la key del proveedor la pone el cliente; subscription-passthrough: OAuth de
    # suscripción reenviado por el backend (única excepción de proxy propio, Constitución VI).
    upstream_mode = Column(String, nullable=False, default="byok")
    # REFERENCIA a un secreto cifrado Fernet (encryption_service) o gestor de secretos.
    # NUNCA el token OAuth en claro (SC-5). Obligatoria si upstream_mode='subscription-passthrough'.
    oauth_credential_ref = Column(String, nullable=True)

    # Toggles por-key (FR-014): NULL = heredar del group/tenant; valor = override.
    redact_enabled = Column(Boolean, nullable=True)
    compression_mode = Column(String, nullable=True)   # off | deterministic | headroom
    allowed_models = Column(JSONB, nullable=True)      # lista de model-ids permitidos
    allowed_tools = Column(JSONB, nullable=True)       # lista de tools/features permitidas

    # Spec 043 US2 (T010, contrato 2 — X-Guardian-Acting-User): allowlist EXPLÍCITA para que
    # una Connection pueda afirmar "actúo en nombre del usuario X" y que el motor/backend lo
    # acepte. Default False: ninguna key existente gana esta capacidad por accidente al
    # migrar. Solo las llaves de servicio del instalador (tool_type='servicio') la necesitan.
    can_act_on_behalf = Column(Boolean, nullable=False, default=False)

    # Relationships
    user = relationship("User", back_populates="api_keys")
    group = relationship("Group", back_populates="api_keys")
    audit_logs = relationship("AuditLog", back_populates="api_key")
    compliance_project = relationship("ComplianceProject", foreign_keys=[compliance_project_id])

    __table_args__ = (
        # PARCIAL sobre keys activas (≤1 Connection ACTIVA por herramienta por client):
        # las filas históricas/desactivadas no colisionan; re-emitir tras revocar es válido.
        Index("uq_api_keys_tenant_user_tool", "tenant_id", "user_id", "tool_type",
              unique=True, postgresql_where=text("is_active IS TRUE")),
        CheckConstraint(
            "tool_type IN ('claude-code', 'copilot', 'cursor', 'claude-desktop', 'chatgpt', 'chat-ui', 'servicio')",
            name="ck_api_keys_tool_type",
        ),
        CheckConstraint(
            "upstream_mode IN ('subscription-passthrough', 'byok')",
            name="ck_api_keys_upstream_mode",
        ),
        CheckConstraint(
            "upstream_mode != 'subscription-passthrough' OR oauth_credential_ref IS NOT NULL",
            name="ck_api_keys_subscription_oauth",
        ),
    )
