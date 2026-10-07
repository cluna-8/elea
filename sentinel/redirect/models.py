"""Modelos SQLAlchemy de la política de redireccionamiento (data-model §1–§6b; capa 2).

Metadata PROPIA (`RedirectBase`), no la `Base` del backend: así ninguna herramienta de la base
(`create_all` de tests, autogenerate) se entera de estas tablas. Las llaves foráneas a
`tenants` viven en la migración (`sentinel/migrations/`), no en el ORM, por la misma razón:
el ORM no puede resolver una tabla de otra metadata.

Nada guarda contenido de pedidos. La credencial de destino se guarda **cifrada**
(`credential_encrypted`, Fernet vía `encryption_service` del backend) y nunca se devuelve.
"""
from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, Numeric, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB as _PG_JSONB
from sqlalchemy.orm import declarative_base

# Tipos portables: en Postgres son UUID/JSONB (lo que crea la migración); en SQLite (tests de la
# API sin base real) degradan a sus equivalentes.
JSONB = JSON().with_variant(_PG_JSONB(), "postgresql")


def UUID(as_uuid=True):  # noqa: N802 — mismo nombre que el tipo de Postgres
    return Uuid(as_uuid=as_uuid)

RedirectBase = declarative_base()

SCOPE_TYPES = ("connection", "user", "group", "tenant")
POLICY_STATES = ("off", "shadow", "on")
POSTURE_MODES = ("off", "allowlist", "offregion_masked")
LEVELS = ("installation", "tenant")
PROVIDERS = ("anthropic", "azure", "azure_ai", "bedrock", "vertex_ai", "deepseek", "openrouter",
             "ollama", "openai_compatible", "openai", "gemini", "groq", "zai", "nvidia_nim",
             "mistral", "hosted_vllm")
PROTOCOL_FAMILIES = ("anthropic_messages", "openai_responses", "openai_chat")
DESTINATION_STATUS = ("active", "inactive", "revoked")
FACES = ("claude", "codex", "openai_generic")
FAMILY_TIERS = ("opus", "sonnet", "haiku", "fable", "mythos")
LABEL_MODES = ("destination", "requested", "custom")
REQUEST_CLASSES = ("main", "subagent", "workflow", "compaction", "auxiliary")
AUDIT_ENTITIES = ("policy", "posture", "destination", "offer", "published_model", "rule",
                  "label", "kit_key", "region", "masking_relaxation")
# Postura por defecto de una región para el tráfico redirigido sin fila de postura (057 FR-031; research R23).
DEFAULT_POSTURES = ("reject_offregion", "masked_offregion", "masked_all", "allow")
RELAXATION_ROLES = ("compliance_officer", "super_admin")


def _pk():
    return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _stamps():
    return (Column(DateTime(timezone=True), server_default=func.now(), nullable=False),
            Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
                   nullable=False))


class RedirectPolicy(RedirectBase):
    __tablename__ = "sentinel_redirect_policy"
    id = _pk()
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    scope_type = Column(String(16), nullable=False)
    scope_value = Column(String(64), nullable=False)
    state = Column(String(8), nullable=False, default="off")
    reason = Column(Text)
    changed_by = Column(UUID(as_uuid=True))
    changed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RedirectPosture(RedirectBase):
    __tablename__ = "sentinel_redirect_posture"
    id = _pk()
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    scope_type = Column(String(16), nullable=False)
    scope_value = Column(String(64), nullable=False)
    mode = Column(String(24), nullable=False)
    jurisdictions = Column(JSONB, nullable=False, default=list)
    accept_foreign_entity = Column(Boolean, nullable=False, default=False)
    reason = Column(Text, nullable=False)
    created_by = Column(UUID(as_uuid=True))
    created_by_role = Column(String(32), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RedirectDestination(RedirectBase):
    __tablename__ = "sentinel_redirect_destination"
    id = _pk()
    level = Column(String(16), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), index=True)           # NULL ⇔ level=installation
    name = Column(String(128), nullable=False)
    provider = Column(String(32), nullable=False)
    real_model = Column(String(256), nullable=False)
    protocol_family = Column(String(24), nullable=False)
    inference_jurisdiction = Column(String(8))
    entity_jurisdiction = Column(String(8))
    blocked_by_default = Column(Boolean, nullable=False, default=False)
    enabled_at = Column(DateTime(timezone=True))
    enabled_by = Column(UUID(as_uuid=True))
    enable_reason = Column(Text)
    # dict con la forma del proveedor (credentials.SHAPES), JSON cifrado con Fernet. Los valores
    # pueden ser `env:REDIRECT_CRED_*` SOLO en nivel instalación (credentials.validate_credential)
    credential_encrypted = Column(Text)
    api_base = Column(String(512))
    provider_options = Column(JSONB, nullable=False, default=dict)
    capability_profile = Column(JSONB, nullable=False, default=dict)
    context_window = Column(Integer)
    max_output = Column(Integer)
    price_override = Column(JSONB)
    status = Column(String(16), nullable=False, default="active")
    created_by = Column(UUID(as_uuid=True))
    updated_by = Column(UUID(as_uuid=True))
    created_at, updated_at = _stamps()


class RedirectOffer(RedirectBase):
    """Oferta de un destino de instalación a un tenant (`tenant_id` NULL = a todos, `*`)."""
    __tablename__ = "sentinel_redirect_offer"
    id = _pk()
    destination_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), index=True)
    enabled_at = Column(DateTime(timezone=True))                  # habilitación por tenant (FR-017)
    enabled_by = Column(UUID(as_uuid=True))
    enable_reason = Column(Text)
    created_by = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RedirectPublishedModel(RedirectBase):
    __tablename__ = "sentinel_redirect_published_model"
    id = _pk()
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    face = Column(String(16), nullable=False)
    public_id = Column(String(128), nullable=False)
    family_tier = Column(String(16))
    is_family_default = Column(Boolean, nullable=False, default=False)
    label = Column(String(256))
    label_mode = Column(String(16), nullable=False, default="requested", server_default="requested")
    scope_type = Column(String(16), nullable=False, default="tenant")
    scope_value = Column(String(64), nullable=False, default="*")
    reference_model = Column(String(256))
    created_by = Column(UUID(as_uuid=True))
    updated_by = Column(UUID(as_uuid=True))
    created_at, updated_at = _stamps()


class RedirectRule(RedirectBase):
    __tablename__ = "sentinel_redirect_rule"
    id = _pk()
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    published_model_id = Column(UUID(as_uuid=True))
    family_tier = Column(String(16))
    request_class = Column(String(16))
    scope_type = Column(String(16), nullable=False, default="tenant")
    scope_value = Column(String(64), nullable=False, default="*")
    targets = Column(JSONB, nullable=False, default=list)         # [destination_id, ...]
    strategy = Column(String(16), nullable=False, default="order", server_default="order")  # order | cheapest
    created_by = Column(UUID(as_uuid=True))
    updated_by = Column(UUID(as_uuid=True))
    created_at, updated_at = _stamps()


class RedirectConfigAudit(RedirectBase):
    __tablename__ = "sentinel_redirect_config_audit"
    id = _pk()
    tenant_id = Column(UUID(as_uuid=True), index=True)            # NULL = nivel instalación
    entity = Column(String(24), nullable=False)
    entity_id = Column(String(64))
    action = Column(String(24), nullable=False)
    before = Column(JSONB)
    after = Column(JSONB)
    actor_id = Column(UUID(as_uuid=True))
    actor_role = Column(String(32))
    reason = Column(Text)
    at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RedirectRegion(RedirectBase):
    """Región del perfil como dato (057 FR-021, FR-030, FR-031; data-model §1): jurisdicciones, los perfiles de
    país que resuelven a ella y la postura por defecto del tráfico redirigido. Nivel instalación (`tenant_id`
    NULL) o empresa (gana la de la empresa). Nada de contenido de pedidos."""
    __tablename__ = "sentinel_redirect_region"
    id = _pk()
    level = Column(String(16), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), index=True)           # NULL ⇔ level=installation
    name = Column(String(64), nullable=False)                    # mayúsculas, sin espacios (p. ej. AMERICAS)
    jurisdictions = Column(JSONB, nullable=False, default=list)  # zonas o países ISO-3166 alfa-2; no vacía
    region_profiles = Column(JSONB, nullable=False, default=list)  # perfiles de país que resuelven a esta fila
    default_posture = Column(String(24), nullable=False, default="reject_offregion",
                             server_default="reject_offregion")
    is_zone = Column(Boolean, nullable=False, default=False)
    created_by = Column(UUID(as_uuid=True))
    updated_by = Column(UUID(as_uuid=True))
    created_at, updated_at = _stamps()


class RedirectMaskingRelaxation(RedirectBase):
    """Relajación del enmascarado forzado por destino (057 FR-031a; data-model §3): solo cumplimiento o
    super-admin, con motivo, y solo si la ficha del destino cumple las precondiciones. La baja no borra la fila.
    La llave foránea a `ext_catalog_entry` vive en la migración (otra metadata)."""
    __tablename__ = "sentinel_redirect_masking_relaxation"
    id = _pk()
    level = Column(String(16), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), index=True)           # NULL ⇔ level=installation
    entry_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    reason = Column(Text, nullable=False)
    created_by = Column(UUID(as_uuid=True))
    created_by_role = Column(String(32), nullable=False)
    revoked_at = Column(DateTime(timezone=True))
    revoked_by = Column(UUID(as_uuid=True))
    revoke_reason = Column(Text)
    created_at, updated_at = _stamps()


class RedirectFidelityReport(RedirectBase):
    """Informe de una prueba de fidelidad (data-model §8; FR-031). Solo metadatos y resultados por
    capacidad: el corpus es sintético y nunca se guarda contenido de respuestas."""
    __tablename__ = "sentinel_redirect_fidelity_report"
    id = _pk()
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    destination_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    face = Column(String(16), nullable=False)
    tool = Column(String(24), nullable=False)
    tool_version = Column(String(64))
    corpus_version = Column(String(32), nullable=False)
    results = Column(JSONB, nullable=False, default=list)
    verdict = Column(String(12), nullable=False)
    complete = Column(Boolean, nullable=False, default=True)
    pass_rate = Column(Numeric(5, 4), nullable=False)
    cost = Column(Numeric(12, 8), nullable=False, default=0)
    run_by = Column(UUID(as_uuid=True))
    run_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


TABLES = tuple(m.__tablename__ for m in (
    RedirectPolicy, RedirectPosture, RedirectDestination, RedirectOffer, RedirectPublishedModel,
    RedirectRule, RedirectConfigAudit, RedirectFidelityReport, RedirectRegion, RedirectMaskingRelaxation))
