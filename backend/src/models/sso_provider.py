import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime
from ..database import Base
from .tenant import DEFAULT_TENANT_ID


class SSOProvider(Base):
    """Proveedor SSO por tenant (spec 017 US2). **Una fila por (tenant, provider_type).**

    Guarda la config del IdP (``config`` JSONB: directory/tenant ID, client_id, metadata de
    discovery) y la REFERENCIA Fernet al client secret (``client_secret_encrypted``), NUNCA el
    secreto en claro — el encrypt/decrypt lo hace ``services/encryption_service`` en la ruta
    SSO (L/M), no este modelo. v1: ``provider_type='entra'`` (Microsoft Entra ID).

    **RLS obligatoria** (mismo patrón que ``GovernanceProfile``): la tabla está bajo ``ENABLE``
    + ``FORCE ROW LEVEL SECURITY`` con las dos policies de la 010 (017_sso_providers.py). Es un
    backstop de base, no la validación primaria: sin ella un UPSERT/DELETE por PK del CRUD admin
    con un id ajeno pisaría el proveedor SSO de OTRO tenant. Toda query de este modelo debe igual
    filtrar por tenant — la RLS es la red, no el filtro.
    """
    __tablename__ = "sso_providers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False,
                       default=DEFAULT_TENANT_ID, index=True)
    # Clave del registro (v1 = 'entra'). El único UNIQUE es (tenant_id, provider_type).
    provider_type = Column(String, nullable=False)
    # Config del IdP: directory/tenant ID, client_id, metadata de discovery. Sin secretos en claro.
    config = Column(JSONB, nullable=True)
    # REFERENCIA Fernet al client secret (services/encryption_service), jamás el secreto en claro
    # (mismo contrato que APIKey.oauth_credential_ref). El modelo sólo lleva la columna VARCHAR.
    client_secret_encrypted = Column(String, nullable=True)
    enabled = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # ≤1 proveedor por (tenant, tipo). Expresado como índice único para reflejar la migración
        # (CREATE UNIQUE INDEX IF NOT EXISTS uq_sso_providers_tenant_type), que usa esa forma por
        # idempotencia sobre esquemas ya migrados.
        Index("uq_sso_providers_tenant_type", "tenant_id", "provider_type", unique=True),
    )
