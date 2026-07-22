import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Numeric, Integer, Index, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base
from .tenant import DEFAULT_TENANT_ID

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Denormalizado (backfill relacional desde user_id → users.tenant_id en la 010);
    # índice compuesto (tenant_id, timestamp) para el dashboard bajo RLS.
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False,
                       default=DEFAULT_TENANT_ID, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    api_key_id = Column(UUID(as_uuid=True), ForeignKey("api_keys.id"), nullable=True)
    model = Column(String, nullable=False)
    prompt_tokens = Column(Integer, nullable=False)
    completion_tokens = Column(Integer, nullable=False)
    cost_usd = Column(Numeric(10, 6), nullable=False)
    cost_saved_usd = Column(Numeric(10, 6), default=0)  # Ahorro USD real por compresión (spec 012 US3)
    pii_detected = Column(Boolean, default=False)
    masked_entities = Column(JSONB, nullable=True) # e.g., [{"type": "PERSON", "count": 2}]
    compliance_status = Column(String, nullable=False) # passed, flagged_high_risk, blocked_by_policy
    latency_ms = Column(Integer, nullable=False)
    tokens_saved_by_optimization = Column(Integer, default=0)
    compression_strategy = Column(String, default="none")   # spec 012 US6: deterministic | headroom | none (llm descartado)
    compression_reversed = Column(Boolean, default=False)  # spec 012 US6: guardia de reversión activada
    guardian_events = Column(JSONB, default=list)           # guardrail events returned by the AI engine
    # Atribución por pedido (spec 027, D6). guardian_events queda CONGELADO como legado: sus
    # tres productores son incompatibles entre sí y la hash-chain de licencias lo relee
    # POSICIONALMENTE (licensing/audit_events.py:92-93), así que no se migra ni se le agregan
    # lectores; la atribución nueva vive acá. Separa los tres ejes que hoy conflan en un solo
    # campo: identidad de la capa, estado de la capa y decisión sobre el pedido.
    # C1 — metadata-only: SOLO códigos del registry y contadores. Prohibido texto libre, valor
    # detectado o fragmento de prompt (el patrón de los `detail` con el nombre propio bloqueado
    # es una fuga y no se copia). NULL en filas históricas = "anterior a la atribución 027".
    applied_layers = Column(JSONB, nullable=True)   # [{"layer_code","status","decision","count"?}]
    # layer_key del registry que produjo el bloqueo, JAMÁS el nombre de display del guardián
    # (editable y white-label: un rename rompería la atribución histórica). Escalar aparte del
    # JSONB para que la query de bloqueos sea trivial con índice parcial.
    blocked_by_layer = Column(String, nullable=True)
    review_token = Column(UUID(as_uuid=True), nullable=True)
    ai_disclosure_delivered = Column(Boolean, default=False)
    processing_purpose = Column(String, nullable=True)   # marketing | expense_processing | pharmacovigilance | research | administrative (alias legacy: clinical_decision)
    user_group_id = Column(UUID(as_uuid=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="audit_logs")
    api_key = relationship("APIKey", back_populates="audit_logs")

    __table_args__ = (
        Index("ix_audit_logs_tenant_timestamp", "tenant_id", "timestamp"),
        # PARCIAL (spec 027): los bloqueos son la excepción, no la norma — indexar la tabla
        # entera sería pagar por las filas que no interesan. Declarado en el modelo, no solo
        # en la migración, para que create_all y autogenerate vean el mismo esquema que
        # produce la 012 (misma convención que tenant.py:33).
        Index("ix_audit_logs_tenant_blocked_layer", "tenant_id", "blocked_by_layer",
              postgresql_where=text("blocked_by_layer IS NOT NULL")),
    )
