"""057 — región del perfil con postura por defecto, reglas de habilitación explícita, relajaciones del
enmascarado forzado por destino y jurisdicción de control en la ficha (data-model §1–§4; research R13, R14, R24, R25).

Octava revisión de la rama propia `sentinel_redirect`: sigue a `f7a3c1d9e508` (la cabeza que trae de Sentinel) y es la
cabeza de la extensión en Eleia. Id por hash (`alembic revision`). Nada toca tablas `LiteLLM_*` ni `_prisma_migrations`;
las FKs apuntan solo a `tenants`, `ext_catalog_entry` y tablas propias (research R5).

- `sentinel_redirect_region`: la región de un perfil de país como dato, con `default_posture` (de fábrica
  `reject_offregion`, la paridad con Sentinel; en Eleia el seed carga `masked_all`).
- `ext_catalog_enablement_rule`: reemplaza el `provider == 'deepseek'` fijo; sin filas nada nace bloqueado.
- `sentinel_redirect_masking_relaxation`: relajación explícita del enmascarado forzado por destino; la baja no borra la
  fila (historial) y solo hay una vigente por (nivel, empresa, entrada).
- `ext_compliance_sheet.control_jurisdiction`: quién controla a la entidad responsable (NULL = sin cargar).

RLS con el patrón de la 010 (ENABLE + FORCE, `tenant_isolation` estricta más la `tenant_isolation_bootstrap` permisiva
de la ventana de deploy). Las tres tablas nuevas tienen filas de **instalación** (`tenant_id` NULL): las ve toda
empresa (la región, las reglas y las relajaciones de instalación rigen para todas) y solo las escribe una sesión con
bypass; las filas de empresa solo las ve y escribe esa empresa.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "89a92524eef6"
down_revision = "f7a3c1d9e508"
branch_labels = None
depends_on = None

STRICT = ("tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid "
          "OR current_setting('app.bypass_rls', true) = 'on'")
BOOTSTRAP = "NULLIF(current_setting('app.current_tenant', true), '') IS NULL"
BYPASS = "current_setting('app.bypass_rls', true) = 'on'"
CURRENT = "NULLIF(current_setting('app.current_tenant', true), '')::uuid"
ZERO = "'00000000-0000-0000-0000-000000000000'::uuid"

REGION, RULE, RELAXATION = ("sentinel_redirect_region", "ext_catalog_enablement_rule",
                            "sentinel_redirect_masking_relaxation")
NEW_TABLES = (REGION, RULE, RELAXATION)


def _uuid(name, *args, **kw):
    return sa.Column(name, pg.UUID(as_uuid=True), *args, **kw)


def _ts(name, **kw):
    return sa.Column(name, sa.DateTime(timezone=True), **kw)


def _now(name):
    return _ts(name, server_default=sa.text("now()"), nullable=False)


def _tenant_fk():
    return _uuid("tenant_id", sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)


def _rls(table, using, check):
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({using}) WITH CHECK ({check})")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_bootstrap ON {table}")
    op.execute(f"CREATE POLICY tenant_isolation_bootstrap ON {table} "
               f"USING ({BOOTSTRAP}) WITH CHECK ({BOOTSTRAP})")


def _level_checks(prefix):
    return (sa.CheckConstraint("level IN ('installation','tenant')", name=f"ck_{prefix}_level"),
            sa.CheckConstraint("(level = 'tenant') = (tenant_id IS NOT NULL)", name=f"ck_{prefix}_level_tenant"))


def upgrade():
    # ── §1 región del perfil ─────────────────────────────────────────────────────────────────────
    op.create_table(
        REGION,
        _uuid("id", primary_key=True),
        sa.Column("level", sa.String(16), nullable=False), _tenant_fk(),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("jurisdictions", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("region_profiles", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("default_posture", sa.String(24), nullable=False, server_default="reject_offregion"),
        sa.Column("is_zone", sa.Boolean, nullable=False, server_default=sa.false()),
        _uuid("created_by"), _uuid("updated_by"), _now("created_at"), _now("updated_at"),
        *_level_checks("redirect_region"),
        sa.CheckConstraint(
            "default_posture IN ('reject_offregion','masked_offregion','masked_all','allow')",
            name="ck_redirect_region_default_posture"),
        sa.CheckConstraint("jsonb_typeof(jurisdictions) = 'array' AND jsonb_array_length(jurisdictions) > 0",
                           name="ck_redirect_region_jurisdictions"),
        sa.CheckConstraint("jsonb_typeof(region_profiles) = 'array'", name="ck_redirect_region_profiles"),
        sa.CheckConstraint("name <> '' AND name !~ '\\s' AND name = upper(name)", name="ck_redirect_region_name"),
    )
    op.execute(f"CREATE UNIQUE INDEX uq_redirect_region_name ON {REGION} (COALESCE(tenant_id, {ZERO}), name)")

    # ── §2 reglas de habilitación explícita ──────────────────────────────────────────────────────
    op.create_table(
        RULE,
        _uuid("id", primary_key=True),
        sa.Column("level", sa.String(16), nullable=False), _tenant_fk(),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("value", sa.String(256), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        _uuid("created_by"), sa.Column("created_by_role", sa.String(32), nullable=False),
        _now("created_at"), _now("updated_at"),
        *_level_checks("enablement_rule"),
        sa.CheckConstraint("kind IN ('provider','api_host','jurisdiction')", name="ck_enablement_rule_kind"),
        sa.CheckConstraint("value <> ''", name="ck_enablement_rule_value"),
        sa.CheckConstraint("reason <> ''", name="ck_enablement_rule_reason"),
    )
    op.execute(f"CREATE UNIQUE INDEX uq_enablement_rule ON {RULE} "
               f"(COALESCE(tenant_id, {ZERO}), kind, value)")

    # ── §3 relajaciones del enmascarado forzado por destino ──────────────────────────────────────
    op.create_table(
        RELAXATION,
        _uuid("id", primary_key=True),
        sa.Column("level", sa.String(16), nullable=False), _tenant_fk(),
        _uuid("entry_id", sa.ForeignKey("ext_catalog_entry.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        _uuid("created_by"), sa.Column("created_by_role", sa.String(32), nullable=False),
        _ts("revoked_at"), _uuid("revoked_by"), sa.Column("revoke_reason", sa.Text),
        _now("created_at"), _now("updated_at"),
        *_level_checks("masking_relaxation"),
        sa.CheckConstraint("reason <> ''", name="ck_masking_relaxation_reason"),
        sa.CheckConstraint("created_by_role IN ('compliance_officer','super_admin')",
                           name="ck_masking_relaxation_role"),
        sa.CheckConstraint("revoked_at IS NULL OR revoke_reason IS NOT NULL",
                           name="ck_masking_relaxation_revoke_reason"),
    )
    # una sola relajación vigente por (nivel, empresa, entrada); las revocadas quedan como historial
    op.execute(f"CREATE UNIQUE INDEX uq_masking_relaxation_active ON {RELAXATION} "
               f"(COALESCE(tenant_id, {ZERO}), entry_id) WHERE revoked_at IS NULL")

    # ── §4 jurisdicción de control en la ficha ───────────────────────────────────────────────────
    op.add_column("ext_compliance_sheet", sa.Column("control_jurisdiction", sa.String(8)))

    # filas de instalación (tenant_id NULL): las ve toda empresa; las escribe solo el bypass
    for table in NEW_TABLES:
        _rls(table, f"({STRICT}) OR tenant_id IS NULL",
             f"(tenant_id IS NOT NULL AND tenant_id = {CURRENT}) OR {BYPASS}")


def downgrade():
    op.drop_column("ext_compliance_sheet", "control_jurisdiction")
    for table in (RELAXATION, RULE, REGION):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
