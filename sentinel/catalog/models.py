"""Modelos del catálogo único (069 data-model §1; T024; capa 2).

Metadata PROPIA (`CatalogBase`), como la 068: ninguna herramienta de la base se entera de estas
tablas. Las llaves foráneas a `tenants` y la RLS viven en la migración.

Generaliza `sentinel_redirect_destination` (068): una entrada del catálogo ES un modelo servible,
con ficha de cumplimiento 1:1 y credencial reutilizable. Nada guarda contenido de pedidos; las
credenciales se guardan **cifradas** (`ciphertext`, MultiFernet vía `encryption_service`) y nunca
se devuelven.
"""
from __future__ import annotations

import uuid

from sqlalchemy import (JSON, Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String,
                        Text, Uuid, func)
from sqlalchemy.dialects.postgresql import JSONB as _PG_JSONB
from sqlalchemy.orm import declarative_base

JSONB = JSON().with_variant(_PG_JSONB(), "postgresql")


def UUID(as_uuid=True):  # noqa: N802 — mismo nombre que el tipo de Postgres
    return Uuid(as_uuid=as_uuid)


CatalogBase = declarative_base()

LEVELS = ("installation", "tenant")
# Familias de proveedor soportadas (FR-004): las de la 068 + las que el spike S1 validó.
PROVIDERS = ("anthropic", "azure", "azure_ai", "bedrock", "vertex_ai", "deepseek", "openrouter",
             "ollama", "openai_compatible", "openai", "gemini", "groq", "zai", "nvidia_nim",
             "mistral", "hosted_vllm")
PROTOCOL_FAMILIES = ("anthropic_messages", "openai_responses", "openai_chat")
ROLES = ("text", "embeddings", "image", "audio", "rerank")   # FR-060
CAPABILITIES = ("small", "standard", "frontier")
ENTRY_STATUS = ("active", "inactive", "archived")
SOURCES = ("console", "seed", "migrated_yaml", "migrated_068")
CREDENTIAL_KINDS = ("secret", "env_ref")
CREDENTIAL_STATUS = ("active", "revoked")
TRANSFER_MECHANISMS = ("n/a", "dpf", "scc", "none", "unknown")
# Reglas de habilitación explícita (057 FR-029, research R14): qué hace que una entrada nazca bloqueada.
RULE_KINDS = ("provider", "api_host", "jurisdiction")
# Capacidades funcionales por entrada (FR-008a); la clave ausente = no declarada = sin la capacidad.
FEATURES = ("images", "documents_pdf", "tools", "thinking", "cache_control", "mid_system_messages")


def slugify(name: str) -> str:
    """Id público por defecto de una entrada: minúsculas, sin espacios ni acentos ni símbolos raros."""
    import re
    import unicodedata
    base = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9._:/-]+", "-", base).strip("-")
    return re.sub(r"-{2,}", "-", base)[:128]


def _pk():
    return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _stamps():
    return (Column(DateTime(timezone=True), server_default=func.now(), nullable=False),
            Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
                   nullable=False))


class Credential(CatalogBase):
    """`ext_credential`: secreto reutilizable entre entradas. Solo escritura."""
    __tablename__ = "ext_credential"
    id = _pk()
    level = Column(String(16), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), index=True)           # NULL ⇔ level=installation
    name = Column(String(128), nullable=False)
    kind = Column(String(16), nullable=False, default="secret")
    # JSON del dict de la forma del proveedor (credentials.SHAPES), cifrado; NULL si `env_ref`.
    ciphertext = Column(Text)
    env_name = Column(String(128))                               # `REDIRECT_CRED_*` si `env_ref`
    fingerprint = Column(String(16), nullable=False, default="")
    status = Column(String(16), nullable=False, default="active")
    created_by = Column(UUID(as_uuid=True))
    created_at, updated_at = _stamps()


class CatalogEntry(CatalogBase):
    __tablename__ = "ext_catalog_entry"
    id = _pk()
    level = Column(String(16), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), index=True)           # NULL ⇔ level=installation
    name = Column(String(128), nullable=False)
    # Id con el que los clientes que hablan directo al motor (Hub, tabular, presentaciones) piden el
    # modelo: estable, sin espacios y sin el prefijo interno `rdx-`. Por defecto, el slug del nombre.
    public_id = Column(String(128), nullable=False)
    provider = Column(String(32), nullable=False)
    real_model = Column(String(256), nullable=False)
    protocol_family = Column(String(24), nullable=False)
    api_base = Column(String(512))
    credential_id = Column(UUID(as_uuid=True), ForeignKey("ext_credential.id"))
    is_aggregator = Column(Boolean, nullable=False, default=False)          # FR-002a
    role = Column(String(16), nullable=False, default="text")
    capability = Column(String(16), nullable=False, default="standard")
    features = Column(JSONB, nullable=False, default=dict)                   # FR-008a / T104
    provider_options = Column(JSONB, nullable=False, default=dict)
    context_window = Column(Integer)
    max_output = Column(Integer)
    # Precio por token fijado por el guard en cada pedido (D23 / T101).
    price_input = Column(Numeric(20, 12))
    price_output = Column(Numeric(20, 12))
    price_source = Column(String(256))
    price_at = Column(Date)
    price_cache_read = Column(Numeric(20, 12))                   # USD por token (enmienda pantalla única)
    price_cache_write = Column(Numeric(20, 12))
    price_tiers = Column(JSONB)                                  # tramos por tamaño de contexto
    # Límites (`validation.LIMIT_KEYS`): timeout y num_retries los aplica el guard; el resto es informativo.
    limits = Column(JSONB, nullable=False, default=dict)
    base_model = Column(Text)                                    # modelo base para costos
    # Parámetros del pedido que el modelo NO acepta (p. ej. `temperature`): lista de nombres que fija el
    # administrador en la ficha (`validation.check_unsupported_params`); el guard los quita antes del proveedor.
    unsupported_params = Column(JSONB, nullable=False, default=list)
    # Parámetros libres validados contra `validation.ADVANCED_KEYS`; nunca credenciales.
    advanced = Column(JSONB, nullable=False, default=dict)
    # Compatibilidad 068: un destino «bloqueado por defecto» (p. ej. DeepSeek API) exige habilitación.
    blocked_by_default = Column(Boolean, nullable=False, default=False)
    enabled_at = Column(DateTime(timezone=True))
    enabled_by = Column(UUID(as_uuid=True))
    enable_reason = Column(Text)
    status = Column(String(16), nullable=False, default="active")
    source = Column(String(16), nullable=False, default="console")
    archived_reason = Column(Text)
    created_by = Column(UUID(as_uuid=True))
    updated_by = Column(UUID(as_uuid=True))
    created_at, updated_at = _stamps()


class CatalogOffer(CatalogBase):
    """Oferta de una entrada de instalación a una organización (elegida por nombre, FR-020)."""
    __tablename__ = "ext_catalog_offer"
    id = _pk()
    entry_id = Column(UUID(as_uuid=True), ForeignKey("ext_catalog_entry.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), index=True)           # NULL = a todas (`*`, compat. 068)
    enabled_at = Column(DateTime(timezone=True))                  # habilitación por organización
    enabled_by = Column(UUID(as_uuid=True))
    enable_reason = Column(Text)
    created_by = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ComplianceSheet(CatalogBase):
    """`ext_compliance_sheet`: ficha 1:1 con la entrada. El semáforo NO se guarda (se deriva)."""
    __tablename__ = "ext_compliance_sheet"
    entry_id = Column(UUID(as_uuid=True), ForeignKey("ext_catalog_entry.id", ondelete="CASCADE"),
                      primary_key=True)
    provider_legal_entity = Column(String(256))
    entity_jurisdiction = Column(String(8))                       # compat. 068 (FR-018)
    # Jurisdicción de quien posee el 50 % o más de la entidad o la controla (057 FR-028a, D12); NULL = sin cargar
    # (no cuenta como «en región»).
    control_jurisdiction = Column(String(8))
    inference_jurisdiction = Column(String(16), nullable=False, default="unknown")
    logs_jurisdiction = Column(String(16), nullable=False, default="unknown")
    zero_data_retention = Column(Boolean)                         # NULL = desconocido
    trains_on_data = Column(Boolean)                              # NULL = desconocido
    transfer_mechanism = Column(String(16), nullable=False, default="unknown")
    dpa_registry_id = Column(UUID(as_uuid=True))                  # FK lógica a `dpa_registry`
    eu_region_contracted = Column(Boolean)                        # solo agregadores
    notes = Column(Text)
    classification_version = Column(String(64), nullable=False, default="console:0")
    classified_by = Column(UUID(as_uuid=True))
    classified_at = Column(DateTime(timezone=True))


class EnablementRule(CatalogBase):
    """`ext_catalog_enablement_rule` (057 data-model §2): una entrada nace `blocked_by_default` si alguna regla
    aplicable coincide con su proveedor, el host de su `api_base` o una jurisdicción de su ficha. Nivel instalación
    (`tenant_id` NULL, la ven y aplican a todas las empresas) o empresa (solo esa empresa, y solo endurece)."""
    __tablename__ = "ext_catalog_enablement_rule"
    id = _pk()
    level = Column(String(16), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), index=True)           # NULL ⇔ level=installation
    kind = Column(String(16), nullable=False)
    value = Column(String(256), nullable=False)
    reason = Column(Text, nullable=False)
    created_by = Column(UUID(as_uuid=True))
    created_by_role = Column(String(32), nullable=False)
    created_at, updated_at = _stamps()


TABLES = tuple(m.__tablename__ for m in (Credential, CatalogEntry, CatalogOffer, ComplianceSheet,
                                         EnablementRule))
