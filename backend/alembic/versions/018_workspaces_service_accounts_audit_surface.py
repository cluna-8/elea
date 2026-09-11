"""Aislamiento de espacios (workspaces) + cuentas de servicio + separación modelo/superficie
en auditoría (spec 043 US1/US2/US4 — T001/T004/T005/T006).

Tres piezas independientes, en una sola migración porque las tres son prerrequisito compartido
de varias historias de la 043 (Foundational, bloquea US1/US2/US4/US5):

1. **Tablas nuevas** ``workspaces``, ``workspace_memberships``, ``workspace_threads`` — la
   autoridad de pertenencia que hoy no existe en ningún lado (Eleia Hub nunca supo qué espacio
   pertenece a quién; ver diagnostico.md de la 043 §1). Tenant-scoped, mismo tratamiento RLS
   EXACTO que las tablas de la 010/012/017 (``ENABLE`` + ``FORCE`` + las dos policies con el
   predicado literal) — es el mismo backstop de base, y estas tablas nuevas nacen con el mismo
   riesgo de cruce entre tenants que ya se cerró para el resto del esquema.

2. **Columnas nuevas** en ``users`` (``account_type``, ``deactivated_at``, ``deactivated_reason``),
   ``audit_logs`` (``acted_for_user_id``, ``surface``, ``event_type``, ``document_group_id``) y
   ``api_keys`` (``can_act_on_behalf``) — todas nullable o con default, sin downtime (mismo
   criterio que la 042 al actualizar `eleavdmia` en caliente). El CHECK de ``api_keys.tool_type``
   (``ck_api_keys_tool_type``) se amplía con el valor ``'servicio'`` — sin esto, marcar las dos
   llaves del instalador (`svc.anythingllm-provider`, `svc.rag-masking`) con ese tool_type
   reventaría el constraint existente (mismo patrón DROP+ADD que la 016 para `ck_users_role`).

3. **Backfill de una sola pasada**: usuarios ``username LIKE 'svc.%'`` → ``account_type='service'``
   (criterio confirmado contra ``elea-installer/install.sh``: las dos cuentas de servicio del
   instalador se llaman literalmente así); filas de ``audit_logs`` con ``model='license'`` →
   ``event_type='license_evidence'``; filas con ``model`` en el vocabulario de superficies ya
   existente (``SURFACES`` de ``litellm/extensions/sentinel_governance.py`` + ``'servicio'``
   nuevo) → ``surface=model``. Se deja ``model`` SIN tocar en el backfill (decisión de
   research.md R5: relajar el NOT NULL de ``audit_logs.model`` es un cambio de esquema mayor que
   no hace falta para que las vistas de costos filtren correctamente por ``event_type``/
   ``surface`` — filtran ``event_type='traffic' AND surface IS NULL`` en vez de exigir
   ``model IS NULL``; ver T047 de tasks.md).

Idempotente (``IF NOT EXISTS`` / ``DROP … IF EXISTS``) y reversible.

Revision ID: 018
Revises: 017
Create Date: 2026-09-08
"""
from alembic import op

revision = '018'
down_revision = '017'
branch_labels = None
depends_on = None

# Copia LITERAL de los predicados de la 010/012/017 (mismo criterio de esos módulos: no son
# importables por nombre porque empiezan con dígito, y alembic no expone las revisiones como
# paquete — la duplicación queda anclada por el test de RLS existente, que compara el
# predicado real de pg_policies contra el de las tablas de la 010).
RLS_POLICY_PREDICATE = (
    "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)
BOOTSTRAP_PREDICATE = "NULLIF(current_setting('app.current_tenant', true), '') IS NULL"

# Tablas nuevas con RLS tenant-scoped (mismo tratamiento que sso_providers en la 017).
_RLS_TABLES = ("workspaces", "workspace_memberships", "workspace_threads")

# Vocabulario de superficies ya existente (litellm/extensions/sentinel_governance.py:94) +
# 'servicio' (spec 043 FR-014) — usado SOLO para el backfill de esta migración, no como CHECK
# de DB (la columna audit_logs.surface no lleva CHECK a propósito: R5 de research.md prefiere
# validación de aplicación, mismo criterio que evita duplicar el enum en dos sistemas — ya
# documentado como riesgo en el propio comentario de la 017).
_SURFACES_BACKFILL = (
    "claude-code", "copilot", "cursor", "claude-desktop", "chatgpt", "chat-ui", "servicio",
)


def _apply_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
        USING ({RLS_POLICY_PREDICATE})
        WITH CHECK ({RLS_POLICY_PREDICATE})
    """)
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_bootstrap ON {table}")
    op.execute(f"""
        CREATE POLICY tenant_isolation_bootstrap ON {table}
        USING ({BOOTSTRAP_PREDICATE})
        WITH CHECK ({BOOTSTRAP_PREDICATE})
    """)


def _drop_rls(table: str) -> None:
    op.execute(f"""
        DO $$
        BEGIN
            IF to_regclass('{table}') IS NOT NULL THEN
                DROP POLICY IF EXISTS tenant_isolation_bootstrap ON {table};
                DROP POLICY IF EXISTS tenant_isolation ON {table};
                ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;
                ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
            END IF;
        END $$
    """)


def upgrade() -> None:
    # ── 1. Tablas nuevas ────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS workspaces (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL
                CONSTRAINT fk_workspaces_tenant REFERENCES tenants(id),
            engine_slug VARCHAR NOT NULL,
            display_name VARCHAR NOT NULL,
            owner_user_id UUID
                CONSTRAINT fk_workspaces_owner REFERENCES users(id),
            status VARCHAR NOT NULL DEFAULT 'active',
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            CONSTRAINT ck_workspaces_status CHECK (status IN ('active', 'unassigned'))
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_workspaces_tenant_id ON workspaces (tenant_id)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_workspaces_tenant_slug
            ON workspaces (tenant_id, engine_slug)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS workspace_memberships (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL
                CONSTRAINT fk_workspace_memberships_tenant REFERENCES tenants(id),
            workspace_id UUID NOT NULL
                CONSTRAINT fk_workspace_memberships_workspace REFERENCES workspaces(id),
            user_id UUID NOT NULL
                CONSTRAINT fk_workspace_memberships_user REFERENCES users(id),
            role VARCHAR NOT NULL,
            created_at TIMESTAMP,
            CONSTRAINT ck_workspace_memberships_role CHECK (role IN ('owner', 'member'))
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_workspace_memberships_tenant_id
            ON workspace_memberships (tenant_id)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_memberships_workspace_user
            ON workspace_memberships (workspace_id, user_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_workspace_memberships_user_id
            ON workspace_memberships (user_id)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS workspace_threads (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL
                CONSTRAINT fk_workspace_threads_tenant REFERENCES tenants(id),
            workspace_id UUID NOT NULL
                CONSTRAINT fk_workspace_threads_workspace REFERENCES workspaces(id),
            owner_user_id UUID NOT NULL
                CONSTRAINT fk_workspace_threads_owner REFERENCES users(id),
            engine_thread_slug VARCHAR,
            created_at TIMESTAMP
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_workspace_threads_tenant_id
            ON workspace_threads (tenant_id)
    """)
    # NULLS NOT DISTINCT no existe antes de PG15; el compose usa postgres:16-alpine (OK), pero
    # por si algún despliegue corre en 13/14 se usa un índice único parcial equivalente en vez
    # de depender de la sintaxis nueva — más portable, mismo efecto (a lo sumo 1 hilo principal
    # por (workspace, usuario) cuando engine_thread_slug es NULL, y unicidad normal si no lo es).
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_threads_slug
            ON workspace_threads (workspace_id, owner_user_id, engine_thread_slug)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_threads_principal
            ON workspace_threads (workspace_id, owner_user_id)
            WHERE engine_thread_slug IS NULL
    """)

    for t in _RLS_TABLES:
        _apply_rls(t)

    # ── 2. Columnas nuevas ──────────────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS account_type VARCHAR NOT NULL DEFAULT 'person',
            ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS deactivated_reason VARCHAR
    """)
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_account_type")
    op.execute("""
        ALTER TABLE users ADD CONSTRAINT ck_users_account_type
        CHECK (account_type IN ('person', 'service'))
    """)

    op.execute("""
        ALTER TABLE audit_logs
            ADD COLUMN IF NOT EXISTS acted_for_user_id UUID
                CONSTRAINT fk_audit_logs_acted_for REFERENCES users(id),
            ADD COLUMN IF NOT EXISTS surface VARCHAR,
            ADD COLUMN IF NOT EXISTS event_type VARCHAR NOT NULL DEFAULT 'traffic',
            ADD COLUMN IF NOT EXISTS document_group_id UUID
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_audit_logs_acted_for_user_id
            ON audit_logs (acted_for_user_id)
            WHERE acted_for_user_id IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_audit_logs_document_group_id
            ON audit_logs (document_group_id)
            WHERE document_group_id IS NOT NULL
    """)

    op.execute("""
        ALTER TABLE api_keys
            ADD COLUMN IF NOT EXISTS can_act_on_behalf BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS ck_api_keys_tool_type")
    op.execute("""
        ALTER TABLE api_keys ADD CONSTRAINT ck_api_keys_tool_type
        CHECK (tool_type IN ('claude-code', 'copilot', 'cursor', 'claude-desktop', 'chatgpt',
                              'chat-ui', 'servicio'))
    """)

    # ── 3. Backfill (una sola pasada, idempotente) ─────────────────────────────────────
    # Cuentas de servicio del instalador: username 'svc.anythingllm-provider' / 'svc.rag-masking'
    # (elea-installer/install.sh, create_service_key). El prefijo 'svc.' es la convención real
    # del instalador, no una suposición — confirmado leyendo el script antes de escribir esto.
    op.execute("""
        UPDATE users SET account_type = 'service'
        WHERE username LIKE 'svc.%' AND account_type = 'person'
    """)

    op.execute("""
        UPDATE audit_logs SET event_type = 'license_evidence'
        WHERE model = 'license' AND event_type = 'traffic'
    """)

    # Mismo criterio para las filas de auth_events.py (backend/src/services/
    # auth_events.py, model='auth') — tampoco es tráfico, y sin este backfill las filas
    # YA EXISTENTES (anteriores a esta migración) seguían colándose en "top modelos"
    # aunque el escritor ya las marque bien desde acá en adelante.
    op.execute("""
        UPDATE audit_logs SET event_type = 'auth_evidence'
        WHERE model = 'auth' AND event_type = 'traffic'
    """)

    surfaces_sql_list = ", ".join(f"'{s}'" for s in _SURFACES_BACKFILL)
    op.execute(f"""
        UPDATE audit_logs SET surface = model
        WHERE model IN ({surfaces_sql_list}) AND surface IS NULL
    """)

    # Spec 043 (US6, T061): instalaciones existentes ya tienen la fila sembrada con el
    # nombre viejo — se renombra acá, no solo en el seed de instalaciones nuevas.
    op.execute("""
        UPDATE guardians SET name = 'Detección lingüística de datos personales'
        WHERE guardian_type = 'presidio' AND name = 'Detección NLP de PII/PHI (Presidio)'
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS ck_api_keys_tool_type")
    op.execute("""
        ALTER TABLE api_keys ADD CONSTRAINT ck_api_keys_tool_type
        CHECK (tool_type IN ('claude-code', 'copilot', 'cursor', 'claude-desktop', 'chatgpt',
                              'chat-ui'))
    """)
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS can_act_on_behalf")

    op.execute("DROP INDEX IF EXISTS ix_audit_logs_document_group_id")
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_acted_for_user_id")
    op.execute("""
        ALTER TABLE audit_logs
            DROP COLUMN IF EXISTS document_group_id,
            DROP COLUMN IF EXISTS event_type,
            DROP COLUMN IF EXISTS surface,
            DROP COLUMN IF EXISTS acted_for_user_id
    """)

    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_account_type")
    op.execute("""
        ALTER TABLE users
            DROP COLUMN IF EXISTS deactivated_reason,
            DROP COLUMN IF EXISTS deactivated_at,
            DROP COLUMN IF EXISTS account_type
    """)

    for t in reversed(_RLS_TABLES):
        _drop_rls(t)

    op.execute("DROP INDEX IF EXISTS uq_workspace_threads_principal")
    op.execute("DROP INDEX IF EXISTS uq_workspace_threads_slug")
    op.execute("DROP INDEX IF EXISTS ix_workspace_threads_tenant_id")
    op.execute("DROP TABLE IF EXISTS workspace_threads")

    op.execute("DROP INDEX IF EXISTS ix_workspace_memberships_user_id")
    op.execute("DROP INDEX IF EXISTS uq_workspace_memberships_workspace_user")
    op.execute("DROP INDEX IF EXISTS ix_workspace_memberships_tenant_id")
    op.execute("DROP TABLE IF EXISTS workspace_memberships")

    op.execute("DROP INDEX IF EXISTS uq_workspaces_tenant_slug")
    op.execute("DROP INDEX IF EXISTS ix_workspaces_tenant_id")
    op.execute("DROP TABLE IF EXISTS workspaces")
