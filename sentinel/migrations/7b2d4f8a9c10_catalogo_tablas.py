"""069 — catálogo único de modelos: entradas, ofertas, fichas de cumplimiento y credenciales.

Misma rama propia que la 068 (`sentinel_redirect`): `down_revision` = la cabeza de la 068. RLS con el
patrón de la 010 (ENABLE + FORCE, `tenant_isolation` estricta por `app.current_tenant` o
`app.bypass_rls`, más la `tenant_isolation_bootstrap` permisiva de la ventana de deploy). Tres
excepciones, todas por el mismo principio (FR-001a: una organización nunca ve la credencial de una
entrada de instalación ni las entradas que no le ofrecieron):

- `ext_catalog_entry`: las filas de **instalación** (`tenant_id` NULL) solo las ve una organización
  con oferta vigente (`ext_catalog_offer` para ella o para todas) y solo las escribe el bypass.
- `ext_credential`: las de instalación (`tenant_id` NULL) NUNCA las ve una organización (solo el
  bypass); las de organización, solo esa organización.
- `ext_compliance_sheet`: sigue a su entrada (visible si la entrada lo es; escribible solo si la
  entrada es de la organización o hay bypass).

La migración de datos (modelos de consola y destinos de la 068 → entradas, FR-040) NO vive aquí:
necesita descifrar credenciales y es idempotente; ver `sentinel/catalog/migrate.py`.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "7b2d4f8a9c10"
down_revision = "0615e56e8251"
branch_labels = None
depends_on = None

STRICT = ("tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid "
          "OR current_setting('app.bypass_rls', true) = 'on'")
BOOTSTRAP = "NULLIF(current_setting('app.current_tenant', true), '') IS NULL"
BYPASS = "current_setting('app.bypass_rls', true) = 'on'"
CURRENT = "NULLIF(current_setting('app.current_tenant', true), '')::uuid"
ZERO = "'00000000-0000-0000-0000-000000000000'::uuid"

ALL_TABLES = ("ext_credential", "ext_catalog_entry", "ext_catalog_offer", "ext_compliance_sheet")


def _uuid(name, *args, **kw):
    return sa.Column(name, pg.UUID(as_uuid=True), *args, **kw)


def _ts(name, **kw):
    return sa.Column(name, sa.DateTime(timezone=True), **kw)


def _now(name):
    return _ts(name, server_default=sa.text("now()"), nullable=False)


def _tenant_fk(nullable=False):
    return _uuid("tenant_id", sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=nullable)


def _rls(table, using, check):
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({using}) WITH CHECK ({check})")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_bootstrap ON {table}")
    op.execute(f"CREATE POLICY tenant_isolation_bootstrap ON {table} "
               f"USING ({BOOTSTRAP}) WITH CHECK ({BOOTSTRAP})")


def upgrade():
    op.create_table(
        "ext_credential",
        _uuid("id", primary_key=True),
        sa.Column("level", sa.String(16), nullable=False), _tenant_fk(nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="secret"),
        sa.Column("ciphertext", sa.Text), sa.Column("env_name", sa.String(128)),
        sa.Column("fingerprint", sa.String(16), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        _uuid("created_by"), _now("created_at"), _now("updated_at"),
        sa.CheckConstraint("level IN ('installation','tenant')", name="ck_ext_credential_level"),
        sa.CheckConstraint("(level = 'tenant') = (tenant_id IS NOT NULL)",
                           name="ck_ext_credential_level_tenant"),
        sa.CheckConstraint("kind IN ('secret','env_ref')", name="ck_ext_credential_kind"),
        sa.CheckConstraint("status IN ('active','revoked')", name="ck_ext_credential_status"),
        # revocar destruye el secreto (`ciphertext` NULL): la fila queda solo como evidencia
        sa.CheckConstraint("status = 'revoked' OR (kind = 'secret' AND ciphertext IS NOT NULL) OR "
                           "(kind = 'env_ref' AND env_name IS NOT NULL)",
                           name="ck_ext_credential_material"),
        # `env_ref` solo en nivel instalación (solo el operador, FR-005)
        sa.CheckConstraint("kind <> 'env_ref' OR level = 'installation'",
                           name="ck_ext_credential_env_ref_level"),
    )
    op.execute(f"CREATE UNIQUE INDEX uq_ext_credential_name ON ext_credential "
               f"(COALESCE(tenant_id, {ZERO}), name) WHERE status = 'active'")

    op.create_table(
        "ext_catalog_entry",
        _uuid("id", primary_key=True),
        sa.Column("level", sa.String(16), nullable=False), _tenant_fk(nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("public_id", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("real_model", sa.String(256), nullable=False),
        sa.Column("protocol_family", sa.String(24), nullable=False),
        sa.Column("api_base", sa.String(512)),
        _uuid("credential_id", sa.ForeignKey("ext_credential.id")),
        sa.Column("is_aggregator", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("role", sa.String(16), nullable=False, server_default="text"),
        sa.Column("capability", sa.String(16), nullable=False, server_default="standard"),
        sa.Column("features", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("provider_options", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("context_window", sa.Integer), sa.Column("max_output", sa.Integer),
        sa.Column("price_input", sa.Numeric(20, 12)), sa.Column("price_output", sa.Numeric(20, 12)),
        sa.Column("price_source", sa.String(256)), sa.Column("price_at", sa.Date),
        sa.Column("blocked_by_default", sa.Boolean, nullable=False, server_default=sa.false()),
        _ts("enabled_at"), _uuid("enabled_by"), sa.Column("enable_reason", sa.Text),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("source", sa.String(16), nullable=False, server_default="console"),
        sa.Column("archived_reason", sa.Text),
        _uuid("created_by"), _uuid("updated_by"), _now("created_at"), _now("updated_at"),
        sa.CheckConstraint("public_id <> '' AND public_id !~ '\\s' AND public_id !~ '^rdx-'",
                           name="ck_ext_entry_public_id"),
        sa.CheckConstraint("level IN ('installation','tenant')", name="ck_ext_entry_level"),
        sa.CheckConstraint("(level = 'tenant') = (tenant_id IS NOT NULL)",
                           name="ck_ext_entry_level_tenant"),
        sa.CheckConstraint(
            "provider IN ('anthropic','azure','azure_ai','bedrock','vertex_ai','deepseek',"
            "'openrouter','ollama','openai_compatible','openai','gemini','groq','zai',"
            "'nvidia_nim','mistral','hosted_vllm')", name="ck_ext_entry_provider"),
        sa.CheckConstraint("protocol_family IN ('anthropic_messages','openai_responses','openai_chat')",
                           name="ck_ext_entry_protocol"),
        sa.CheckConstraint("role IN ('text','embeddings')", name="ck_ext_entry_role"),
        sa.CheckConstraint("capability IN ('small','standard','frontier')",
                           name="ck_ext_entry_capability"),
        sa.CheckConstraint("status IN ('active','inactive','archived')", name="ck_ext_entry_status"),
        sa.CheckConstraint("source IN ('console','seed','migrated_yaml','migrated_068')",
                           name="ck_ext_entry_source"),
        sa.CheckConstraint("NOT blocked_by_default OR enabled_at IS NULL OR enable_reason IS NOT NULL",
                           name="ck_ext_entry_enable_reason"),
        sa.CheckConstraint("status <> 'archived' OR archived_reason IS NOT NULL",
                           name="ck_ext_entry_archived_reason"),
    )
    # el nombre se reutiliza una vez archivada la entrada (queda como evidencia, FR-001)
    op.execute(f"CREATE UNIQUE INDEX uq_ext_entry_name ON ext_catalog_entry "
               f"(COALESCE(tenant_id, {ZERO}), name) WHERE status <> 'archived'")

    op.execute(f"CREATE UNIQUE INDEX uq_ext_entry_public_id ON ext_catalog_entry "
               f"(COALESCE(tenant_id, {ZERO}), public_id) WHERE status <> 'archived'")

    op.create_table(
        "ext_catalog_offer",
        _uuid("id", primary_key=True),
        _uuid("entry_id", sa.ForeignKey("ext_catalog_entry.id", ondelete="CASCADE"), nullable=False),
        _tenant_fk(nullable=True),
        _ts("enabled_at"), _uuid("enabled_by"), sa.Column("enable_reason", sa.Text),
        _uuid("created_by"), _now("created_at"),
    )
    op.execute(f"CREATE UNIQUE INDEX uq_ext_offer ON ext_catalog_offer "
               f"(entry_id, COALESCE(tenant_id, {ZERO}))")

    op.create_table(
        "ext_compliance_sheet",
        _uuid("entry_id", sa.ForeignKey("ext_catalog_entry.id", ondelete="CASCADE"),
              primary_key=True),
        sa.Column("provider_legal_entity", sa.String(256)),
        sa.Column("entity_jurisdiction", sa.String(8)),
        sa.Column("inference_jurisdiction", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("logs_jurisdiction", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("zero_data_retention", sa.Boolean), sa.Column("trains_on_data", sa.Boolean),
        sa.Column("transfer_mechanism", sa.String(16), nullable=False, server_default="unknown"),
        _uuid("dpa_registry_id"), sa.Column("eu_region_contracted", sa.Boolean),
        sa.Column("notes", sa.Text),
        sa.Column("classification_version", sa.String(64), nullable=False, server_default="console:0"),
        _uuid("classified_by"), _ts("classified_at"),
        sa.CheckConstraint("transfer_mechanism IN ('n/a','dpf','scc','none','unknown')",
                           name="ck_ext_sheet_transfer"),
    )

    _rls("ext_credential", STRICT, STRICT)
    offered = (f"tenant_id IS NULL AND level = 'installation' AND EXISTS ("
               f"SELECT 1 FROM ext_catalog_offer o WHERE o.entry_id = ext_catalog_entry.id "
               f"AND (o.tenant_id IS NULL OR o.tenant_id = {CURRENT}))")
    _rls("ext_catalog_entry",
         f"({STRICT}) OR ({offered})",
         f"(tenant_id IS NOT NULL AND tenant_id = {CURRENT}) OR {BYPASS}")
    _rls("ext_catalog_offer", f"({STRICT}) OR tenant_id IS NULL", BYPASS)
    _rls("ext_compliance_sheet",
         "EXISTS (SELECT 1 FROM ext_catalog_entry e WHERE e.id = ext_compliance_sheet.entry_id)",
         f"EXISTS (SELECT 1 FROM ext_catalog_entry e WHERE e.id = ext_compliance_sheet.entry_id "
         f"AND (e.tenant_id = {CURRENT} OR {BYPASS}))")


def downgrade():
    for table in ("ext_compliance_sheet", "ext_catalog_offer", "ext_catalog_entry", "ext_credential"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
