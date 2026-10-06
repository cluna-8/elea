"""068 US5 — informes de la prueba de fidelidad (data-model §8).

Segunda revisión de la rama propia `sentinel_redirect` (sigue a `7b2d4f8a9c10`, la del catálogo de la 069): una tabla con el
resultado por capacidad de cada corrida, para comparar versiones de una herramienta y ver las
regresiones antes de que lleguen a los usuarios (US5, escenario 4). RLS con el patrón de la
rama: ENABLE + FORCE, `tenant_isolation` estricta y la `tenant_isolation_bootstrap` permisiva de
la ventana de deploy. No guarda contenido de pedidos ni respuestas.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "c3f1a7d9e204"
down_revision = "7b2d4f8a9c10"
branch_labels = None
depends_on = None

TABLE = "sentinel_redirect_fidelity_report"
STRICT = ("tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid "
          "OR current_setting('app.bypass_rls', true) = 'on'")
BOOTSTRAP = "NULLIF(current_setting('app.current_tenant', true), '') IS NULL"


def upgrade():
    op.create_table(
        TABLE,
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("destination_id", pg.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("face", sa.String(16), nullable=False),
        sa.Column("tool", sa.String(24), nullable=False),
        sa.Column("tool_version", sa.String(64)),
        sa.Column("corpus_version", sa.String(32), nullable=False),
        sa.Column("results", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("verdict", sa.String(12), nullable=False),
        sa.Column("complete", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("pass_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("cost", sa.Numeric(12, 8), nullable=False, server_default="0"),
        sa.Column("run_by", pg.UUID(as_uuid=True)),
        sa.Column("run_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("face IN ('claude','codex','openai_generic')",
                           name="ck_sentinel_redirect_fidelity_face"),
        sa.CheckConstraint("verdict IN ('apto','no_apto','incompleto')",
                           name="ck_sentinel_redirect_fidelity_verdict"),
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.execute(f"CREATE POLICY tenant_isolation ON {TABLE} USING ({STRICT}) WITH CHECK ({STRICT})")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_bootstrap ON {TABLE}")
    op.execute(f"CREATE POLICY tenant_isolation_bootstrap ON {TABLE} "
               f"USING ({BOOTSTRAP}) WITH CHECK ({BOOTSTRAP})")


def downgrade():
    op.execute(f"DROP TABLE IF EXISTS {TABLE} CASCADE")
