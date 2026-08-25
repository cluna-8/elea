import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
from ..database import Base
from .tenant import DEFAULT_TENANT_ID


class GovernanceProfile(Base):
    """Configuración de gobernanza del tenant: **una fila por decisión** (spec 027, D2).

    Cada fila dice "para este alcance, esta capa opcional está ``on``/``off``". La
    **ausencia de fila es heredar** del nivel inferior de la cascada — el mismo idioma
    ``NULL = heredar`` que ya usan los toggles por-Connection de la 013
    (``APIKey.redact_enabled``, budget.py:71-75). No existe ``decision='inherit'``:
    volver a heredar es **DELETE de la fila**. La precedencia completa la resuelve el
    resolutor puro (Connection > superficie confiable > modo de conexión >
    tenant_default > default de producto), jamás la DB.

    **Por qué no cuelga de ``SecurityPolicy``** (D2): esa tabla no es multi-tenant en la
    práctica pese a tener ``tenant_id`` —su lector real es ``db.query(SecurityPolicy).first()``
    sin filtrar tenant (``get_or_create_default_policy`` de ``api/policy.py`` y repeticiones)—, mantiene el invariante de **un solo
    activo global** apagando el resto en cada escritura (``create_policy``/``update_policy_by_id`` de ``api/policy.py``), y su eje es "qué
    entidades PII y con qué acción", no "qué capas corren para este alcance". El eje
    modo×superficie exige N filas activas a la vez. El precedente de forma que sí se copia es
    ``ComplianceProject`` (compliance.py:13-34): entidad por tenant, referenciada por clave,
    sin columnas espejo en ``Tenant``.

    ``layer_key`` va **sin FK y sin CHECK** a propósito (D1): el catálogo de capas es una
    constante de código (``GOVERNANCE_LAYERS``) para que ningún ``UPDATE`` pueda apagar el
    piso, y duplicarlo en el esquema lo volvería mutable por DB. Una FK a ``guardians.id``
    además la destruiría el seed, que borra la tabla entera y re-siembra (guardian_service.py:33-36).
    La validación es en capas: el router admin rechaza con 422 el ``layer_key`` desconocido o
    de ``tier=floor``, y el resolutor **ignora** toda fila de piso o fuera del registry — una
    fila contrabandeada por SQL directo es inerte (SC-004 estructural, no validación).

    **RLS obligatoria** (hallazgo A1): la tabla está bajo ``ENABLE`` + ``FORCE ROW LEVEL
    SECURITY`` con las mismas dos policies que las 13 tablas de la 010
    (012_governance_profiles_audit_attribution.py). Es backstop de base, no la validación
    primaria: sin ella, un UPSERT/DELETE por PK del CRUD admin con un id ajeno apagaría
    capas de seguridad de OTRO tenant. Toda query de este modelo debe igual filtrar por
    tenant — la RLS es la red, no el filtro.

    **Límite con la 015**: el enum de ``scope_type`` queda **cerrado** a los tres valores.
    ``group``/``client`` son de la cascada 015: cuando existan se insertan como dos niveles
    más en la misma lista de precedencia del resolutor y como dos valores nuevos del CHECK,
    sin cambiar el contrato de esta tabla.
    """
    __tablename__ = "governance_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False,
                       default=DEFAULT_TENANT_ID, index=True)
    # Eje del alcance. 'tenant_default' usa el centinela '*' como scope_value porque el
    # UNIQUE de Postgres no deduplica NULLs: el default de tenant necesita valor concreto.
    scope_type = Column(String, nullable=False)
    scope_value = Column(String, nullable=False)
    # Clave del registry en código (D1). Los tokens de 'connection_mode' son el codominio de
    # la función de mapeo del ruteo EFECTIVO, jamás el upstream_mode crudo de la Connection
    # (budget.py:92-95 es la intención declarada, no el ruteo real).
    # ACOTADA a 64: es una clave del registry en código, no texto libre (la más larga hoy
    # ronda los 20 chars). Sin FK ni CHECK (arriba), el largo es el único límite de esquema;
    # sin él, esta columna acepta cadenas ilimitadas en una tabla que se exporta como
    # evidencia de auditoría.
    layer_key = Column(String(64), nullable=False)
    decision = Column(String, nullable=False)
    # CONTRATO de este campo: lleva el **username o id del admin autenticado**, y NUNCA el
    # email ni ningún otro dato de contacto — la tabla se exporta como evidencia de auditoría
    # y no tiene purga por retención, así que un email acá queda en claro para siempre (C1).
    # Lo escribe SIEMPRE el router admin; las escrituras de sistema usan el centinela
    # 'system'. Acotada a 120 (el username más largo del repo entra de sobra) para que un
    # router descuidado que intente meter texto libre falle en la base, no en la exportación.
    # Precedente RetentionPolicy.updated_by (compliance.py:99), endurecido a NOT NULL porque
    # no hay camino de escritura sin identidad. No es FK a users: sobrevive al borrado del
    # usuario y es lo que exporta un informe de auditoría.
    updated_by = Column(String(120), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # Una decisión por (alcance, capa): el UPSERT del CRUD se apoya en este UNIQUE.
        UniqueConstraint("tenant_id", "scope_type", "scope_value", "layer_key",
                         name="uq_governance_profiles_scope"),
        CheckConstraint(
            "scope_type IN ('tenant_default', 'connection_mode', 'surface')",
            name="ck_governance_profiles_scope_type",
        ),
        CheckConstraint(
            "decision IN ('on', 'off')",
            name="ck_governance_profiles_decision",
        ),
        # El dominio de scope_value depende del scope_type. La rama 'surface' es espejo
        # EXACTO de ck_api_keys_tool_type (budget.py:88-91): ambos CHECKs deben evolucionar
        # en la MISMA migración cuando se agregue una superficie (p.ej. la API de Responses).
        # Mientras una superficie no esté en el enum, su tráfico resuelve por fallback a
        # connection_mode → tenant_default (riesgo asumido en D5).
        CheckConstraint(
            "(scope_type = 'tenant_default' AND scope_value = '*')"
            " OR (scope_type = 'connection_mode'"
            "     AND scope_value IN ('subscription', 'gateway-models'))"
            " OR (scope_type = 'surface'"
            "     AND scope_value IN ('claude-code', 'copilot', 'cursor',"
            "                         'claude-desktop', 'chatgpt', 'chat-ui'))",
            name="ck_governance_profiles_scope_pair",
        ),
    )
