"""068 — tablas de la política de redireccionamiento (capa 2, data-model §1–§6b).

Rama PROPIA del árbol de Alembic (`branch_labels=("sentinel_redirect",)`, id hash): se suma
con la costura S4 (`ALEMBIC_EXTRA_VERSION_LOCATIONS=<ruta>/sentinel/migrations`) y los
arranques migran a `heads`. `depends_on="010"`: necesita `tenants` y el patrón de RLS de la
010, nada más de la base.

RLS con el patrón de `010_multitenant_foundation.py` (ENABLE + FORCE, `tenant_isolation`
estricta por `app.current_tenant` o `app.bypass_rls`, más la `tenant_isolation_bootstrap`
permisiva de la ventana de deploy, igual que las tablas de la 017/018). Dos excepciones:

- `sentinel_redirect_destination`: las filas de **instalación** (`tenant_id` NULL) solo las ve
  un tenant con oferta vigente (`sentinel_redirect_offer` para él o para todos) y solo las
  escribe una sesión con bypass (super_admin).
- `sentinel_redirect_offer`: un tenant ve las ofertas para él y las «para todos»; escribir
  exige bypass.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0615e56e8251"
down_revision = None
branch_labels = ("sentinel_redirect",)
depends_on = "010"

STRICT = ("tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid "
          "OR current_setting('app.bypass_rls', true) = 'on'")
BOOTSTRAP = "NULLIF(current_setting('app.current_tenant', true), '') IS NULL"
BYPASS = "current_setting('app.bypass_rls', true) = 'on'"
CURRENT = "NULLIF(current_setting('app.current_tenant', true), '')::uuid"

_SCOPE = "scope_type IN ('connection','user','group','tenant')"
_TENANT_TABLES = ("sentinel_redirect_policy", "sentinel_redirect_posture",
                  "sentinel_redirect_published_model", "sentinel_redirect_rule",
                  "sentinel_redirect_config_audit")
ALL_TABLES = _TENANT_TABLES + ("sentinel_redirect_destination", "sentinel_redirect_offer")


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
        "sentinel_redirect_policy",
        _uuid("id", primary_key=True), _tenant_fk(),
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("scope_value", sa.String(64), nullable=False),
        sa.Column("state", sa.String(8), nullable=False, server_default="off"),
        sa.Column("reason", sa.Text), _uuid("changed_by"), _now("changed_at"),
        sa.UniqueConstraint("tenant_id", "scope_type", "scope_value",
                            name="uq_sentinel_redirect_policy_scope"),
        sa.CheckConstraint(_SCOPE, name="ck_sentinel_redirect_policy_scope"),
        sa.CheckConstraint("state IN ('off','shadow','on')", name="ck_sentinel_redirect_policy_state"),
    )
    op.create_table(
        "sentinel_redirect_posture",
        _uuid("id", primary_key=True), _tenant_fk(),
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("scope_value", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(24), nullable=False),
        sa.Column("jurisdictions", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("accept_foreign_entity", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.Text, nullable=False),
        _uuid("created_by"), sa.Column("created_by_role", sa.String(32), nullable=False),
        _now("created_at"),
        sa.CheckConstraint(_SCOPE, name="ck_sentinel_redirect_posture_scope"),
        sa.CheckConstraint("mode IN ('off','allowlist','offregion_masked')",
                           name="ck_sentinel_redirect_posture_mode"),
        sa.CheckConstraint("mode <> 'allowlist' OR jsonb_array_length(jurisdictions) > 0",
                           name="ck_sentinel_redirect_posture_allowlist"),
    )
    op.create_table(
        "sentinel_redirect_destination",
        _uuid("id", primary_key=True),
        sa.Column("level", sa.String(16), nullable=False), _tenant_fk(nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("real_model", sa.String(256), nullable=False),
        sa.Column("protocol_family", sa.String(24), nullable=False),
        sa.Column("inference_jurisdiction", sa.String(8)),
        sa.Column("entity_jurisdiction", sa.String(8)),
        sa.Column("blocked_by_default", sa.Boolean, nullable=False, server_default=sa.false()),
        _ts("enabled_at"), _uuid("enabled_by"), sa.Column("enable_reason", sa.Text),
        sa.Column("credential_encrypted", sa.Text),
        sa.Column("api_base", sa.String(512)),
        sa.Column("provider_options", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("capability_profile", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("context_window", sa.Integer), sa.Column("max_output", sa.Integer),
        sa.Column("price_override", pg.JSONB),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        _uuid("created_by"), _uuid("updated_by"), _now("created_at"), _now("updated_at"),
        sa.CheckConstraint("level IN ('installation','tenant')", name="ck_sentinel_redirect_dest_level"),
        sa.CheckConstraint("(level = 'tenant') = (tenant_id IS NOT NULL)",
                           name="ck_sentinel_redirect_dest_level_tenant"),
        sa.CheckConstraint(
            "provider IN ('anthropic','azure','azure_ai','bedrock','vertex_ai','deepseek',"
            "'openrouter','ollama','openai_compatible','openai','gemini','groq')",
            name="ck_sentinel_redirect_dest_provider"),
        sa.CheckConstraint("protocol_family IN ('anthropic_messages','openai_responses','openai_chat')",
                           name="ck_sentinel_redirect_dest_protocol"),
        sa.CheckConstraint("status IN ('active','inactive','revoked')",
                           name="ck_sentinel_redirect_dest_status"),
        sa.CheckConstraint("NOT blocked_by_default OR enabled_at IS NULL OR enable_reason IS NOT NULL",
                           name="ck_sentinel_redirect_dest_enable_reason"),
    )
    op.execute("CREATE UNIQUE INDEX uq_sentinel_redirect_dest_name ON sentinel_redirect_destination "
               "(COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid), name)")
    op.create_table(
        "sentinel_redirect_offer",
        _uuid("id", primary_key=True),
        _uuid("destination_id", sa.ForeignKey("sentinel_redirect_destination.id", ondelete="CASCADE"),
              nullable=False),
        _tenant_fk(nullable=True),
        _ts("enabled_at"), _uuid("enabled_by"), sa.Column("enable_reason", sa.Text),
        _uuid("created_by"), _now("created_at"),
    )
    op.execute("CREATE UNIQUE INDEX uq_sentinel_redirect_offer ON sentinel_redirect_offer "
               "(destination_id, COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid))")
    op.create_table(
        "sentinel_redirect_published_model",
        _uuid("id", primary_key=True), _tenant_fk(),
        sa.Column("face", sa.String(16), nullable=False),
        sa.Column("public_id", sa.String(128), nullable=False),
        sa.Column("family_tier", sa.String(16)),
        sa.Column("is_family_default", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("label", sa.String(256)),
        sa.Column("label_mode", sa.String(16), nullable=False, server_default="destination"),
        sa.Column("scope_type", sa.String(16), nullable=False, server_default="tenant"),
        sa.Column("scope_value", sa.String(64), nullable=False, server_default="*"),
        sa.Column("reference_model", sa.String(256)),
        _uuid("created_by"), _uuid("updated_by"), _now("created_at"), _now("updated_at"),
        sa.UniqueConstraint("tenant_id", "face", "public_id", "scope_type", "scope_value",
                            name="uq_sentinel_redirect_published"),
        sa.CheckConstraint(_SCOPE, name="ck_sentinel_redirect_published_scope"),
        sa.CheckConstraint("face IN ('claude','codex','openai_generic')",
                           name="ck_sentinel_redirect_published_face"),
        sa.CheckConstraint("public_id !~ '\\s' AND public_id !~ '^rdx-'",
                           name="ck_sentinel_redirect_published_public_id"),
        sa.CheckConstraint("label_mode IN ('destination','requested','custom')",
                           name="ck_sentinel_redirect_published_label_mode"),
    )
    op.create_table(
        "sentinel_redirect_rule",
        _uuid("id", primary_key=True), _tenant_fk(),
        _uuid("published_model_id",
              sa.ForeignKey("sentinel_redirect_published_model.id", ondelete="CASCADE")),
        sa.Column("family_tier", sa.String(16)),
        sa.Column("request_class", sa.String(16)),
        sa.Column("scope_type", sa.String(16), nullable=False, server_default="tenant"),
        sa.Column("scope_value", sa.String(64), nullable=False, server_default="*"),
        sa.Column("targets", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        _uuid("created_by"), _uuid("updated_by"), _now("created_at"), _now("updated_at"),
        sa.CheckConstraint(_SCOPE, name="ck_sentinel_redirect_rule_scope"),
        sa.CheckConstraint("published_model_id IS NOT NULL OR family_tier IS NOT NULL",
                           name="ck_sentinel_redirect_rule_target"),
        sa.CheckConstraint(
            "request_class IS NULL OR request_class IN "
            "('main','subagent','workflow','compaction','auxiliary')",
            name="ck_sentinel_redirect_rule_class"),
    )
    op.create_table(
        "sentinel_redirect_config_audit",
        _uuid("id", primary_key=True), _tenant_fk(nullable=True),
        sa.Column("entity", sa.String(24), nullable=False),
        sa.Column("entity_id", sa.String(64)),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("before", pg.JSONB), sa.Column("after", pg.JSONB),
        _uuid("actor_id"), sa.Column("actor_role", sa.String(32)),
        sa.Column("reason", sa.Text), _now("at"),
    )

    for table in _TENANT_TABLES:
        _rls(table, STRICT, STRICT)
    offered = (f"tenant_id IS NULL AND level = 'installation' AND EXISTS ("
               f"SELECT 1 FROM sentinel_redirect_offer o WHERE o.destination_id = "
               f"sentinel_redirect_destination.id AND (o.tenant_id IS NULL OR o.tenant_id = {CURRENT}))")
    _rls("sentinel_redirect_destination",
         f"({STRICT}) OR ({offered})",
         f"(tenant_id IS NOT NULL AND tenant_id = {CURRENT}) OR {BYPASS}")
    _rls("sentinel_redirect_offer",
         f"({STRICT}) OR tenant_id IS NULL",
         BYPASS)


def downgrade():
    for table in reversed(("sentinel_redirect_policy", "sentinel_redirect_posture",
                           "sentinel_redirect_destination", "sentinel_redirect_offer",
                           "sentinel_redirect_published_model", "sentinel_redirect_rule",
                           "sentinel_redirect_config_audit")):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
