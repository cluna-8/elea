"""069 US2 — perfiles de acceso por riesgo: perfiles, reglas, asignaciones, techos y perfil de llave.

Misma rama propia que el catálogo (`sentinel_redirect`): `down_revision` = la cabeza actual. El perfil
de la llave va en tabla propia (`ext_access_key_profile`): ninguna columna de `api_keys` cambia. RLS con
el patrón de la 010 (ENABLE + FORCE, `tenant_isolation` estricta por `app.current_tenant` o
`app.bypass_rls`, más la `tenant_isolation_bootstrap` permisiva de la ventana de deploy);
`ext_access_profile_rule` sigue a su perfil.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "a7d2f9c4b816"
down_revision = "e4a9c15b7d30"
branch_labels = None
depends_on = None

STRICT = ("tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid "
          "OR current_setting('app.bypass_rls', true) = 'on'")
BOOTSTRAP = "NULLIF(current_setting('app.current_tenant', true), '') IS NULL"

TENANT_TABLES = ("ext_access_profile", "ext_access_assignment", "ext_ai_act_ceiling",
                 "ext_access_key_profile")


def _uuid(name, *args, **kw):
    return sa.Column(name, pg.UUID(as_uuid=True), *args, **kw)


def _ts(name, **kw):
    return sa.Column(name, sa.DateTime(timezone=True), **kw)


def _now(name):
    return _ts(name, server_default=sa.text("now()"), nullable=False)


def _tenant_fk():
    return _uuid("tenant_id", sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)


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
        "ext_access_profile",
        _uuid("id", primary_key=True), _tenant_fk(),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("seeded", sa.Boolean, nullable=False, server_default=sa.false()),
        _ts("archived_at"), sa.Column("archived_reason", sa.Text),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        _uuid("created_by"), _uuid("updated_by"), _now("created_at"), _now("updated_at"),
        sa.CheckConstraint("kind IN ('company','ceiling','key')", name="ck_ext_access_profile_kind"),
        sa.CheckConstraint("archived_at IS NULL OR archived_reason IS NOT NULL",
                           name="ck_ext_access_profile_archived_reason"),
    )
    op.create_index("ix_ext_access_profile_tenant_id", "ext_access_profile", ["tenant_id"])
    # el nombre se reutiliza una vez archivado el perfil (queda como evidencia)
    op.execute("CREATE UNIQUE INDEX uq_ext_access_profile_name ON ext_access_profile "
               "(tenant_id, kind, name) WHERE archived_at IS NULL")

    op.create_table(
        "ext_access_profile_rule",
        _uuid("id", primary_key=True),
        _uuid("profile_id", sa.ForeignKey("ext_access_profile.id", ondelete="CASCADE"),
              nullable=False),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("effect", sa.String(8), nullable=False),
        sa.Column("selector", sa.String(16), nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.CheckConstraint("effect IN ('include','exclude')", name="ck_ext_access_rule_effect"),
        sa.CheckConstraint("selector IN ('semaforo','jurisdiccion','proveedor','capacidad','entrada')",
                           name="ck_ext_access_rule_selector"),
    )
    op.create_index("ix_ext_access_profile_rule_profile_id", "ext_access_profile_rule", ["profile_id"])

    op.create_table(
        "ext_access_assignment",
        _uuid("id", primary_key=True), _tenant_fk(),
        _uuid("profile_id", sa.ForeignKey("ext_access_profile.id"), nullable=False),
        sa.Column("subject_type", sa.String(8), nullable=False),
        _uuid("subject_id", nullable=False),
        sa.CheckConstraint("subject_type IN ('tenant','group','user')",
                           name="ck_ext_access_assignment_subject"),
    )
    op.create_index("ix_ext_access_assignment_tenant_id", "ext_access_assignment", ["tenant_id"])
    op.create_index("ix_ext_access_assignment_profile_id", "ext_access_assignment", ["profile_id"])
    op.execute("CREATE UNIQUE INDEX uq_ext_access_assignment ON ext_access_assignment "
               "(subject_type, subject_id, profile_id)")

    op.create_table(
        "ext_ai_act_ceiling",
        _uuid("tenant_id", sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("risk_level", sa.String(24), primary_key=True),
        _uuid("profile_id", sa.ForeignKey("ext_access_profile.id"), nullable=False),
        sa.CheckConstraint(
            "risk_level IN ('minimal','limited','high_risk_annex1','high_risk_annex3')",
            name="ck_ext_ai_act_ceiling_risk"),
    )

    op.create_table(
        "ext_access_key_profile",
        _uuid("api_key_id", primary_key=True), _tenant_fk(),
        _uuid("profile_id", sa.ForeignKey("ext_access_profile.id"), nullable=False),
        _uuid("updated_by"), _now("updated_at"),
    )
    op.create_index("ix_ext_access_key_profile_tenant_id", "ext_access_key_profile", ["tenant_id"])

    for t in TENANT_TABLES:
        _rls(t, STRICT, STRICT)
    rule_using = ("EXISTS (SELECT 1 FROM ext_access_profile p "
                  "WHERE p.id = ext_access_profile_rule.profile_id)")
    _rls("ext_access_profile_rule", rule_using, rule_using)


def downgrade():
    for table in ("ext_access_key_profile", "ext_ai_act_ceiling", "ext_access_assignment",
                  "ext_access_profile_rule", "ext_access_profile"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
