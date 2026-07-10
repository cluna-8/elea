"""Multi-Tenant Foundation & Client Model (spec 013)

Convierte el esquema single-tenant heredado en el bedrock multi-tenant:

* Tabla ``tenants`` + default tenant de UUID fijo ``00000000-0000-0000-0000-000000000001``
  (``slug='default'``, ``on_premise``) — el pivote que mantiene vivo el on-prem.
* ``tenant_id UUID NOT NULL FK→tenants.id`` en 13 tablas (las 8 pedidas + las 5 de
  compliance por FR-007, decisión recomendada: sin ellas habría fugas cross-tenant),
  con backfill relacional donde hay identidad (``user_id → users.tenant_id``) y
  fallback al default tenant. Índices ``ix_<t>_tenant_id`` (+ ``(tenant_id, timestamp)``
  en audit_logs).
* Reconciliación de roles ([D9]): backfill ``admin→tenant_admin``,
  ``clinician``/``developer``→``client``+``display_label`` (catch-all a ``client`` para
  valores sucios) ANTES del ``CHECK (role IN (...))``. ``super_admin`` NO se autogenera.
* Client model (US5): ``users.client_type`` + Connection = ``api_keys`` extendida
  (``tool_type`` backfill ``'claude-code'``, ``upstream_mode``, ``oauth_credential_ref``,
  toggles NULL=heredar).
* Unicidad compuesta por tenant: ``(tenant_id, username/email/name)`` y
  ``(tenant_id, user_id, tool_type)``; ``api_keys.key_hash`` sigue UNIQUE global.
* Row-Level Security: ``ENABLE`` + ``FORCE`` por tabla con policy ``tenant_isolation``
  (GUC ``app.current_tenant`` + bypass ``app.bypass_rls``).

REQUISITO FORCE RLS (T002): la app y alembic se conectan como ``basa_admin``, DUEÑO de
las tablas — sin ``FORCE ROW LEVEL SECURITY`` el dueño bypasea RLS y el aislamiento
sería un falso positivo (SC-4).

⚠️ TRAMPA SUPERUSER: en el docker-compose actual ``basa_admin`` es además SUPERUSER de
Postgres (lo crea la imagen), y los superusers bypasean RLS SIEMPRE, incluso con FORCE.
Para que la RLS sea efectiva en runtime, la app debe conectarse como un rol
NOSUPERUSER (dueño o no) — cableado de identidad/rol de app en spec 017. Los tests de
013 lo prueban con un rol NOSUPERUSER dueño de las tablas.

VENTANA DE DEPLOY (FR-024, riesgo #2 del plan): además de la policy estricta
``tenant_isolation`` se crea ``tenant_isolation_bootstrap``: permite la fila cuando el
GUC ``app.current_tenant`` NO está seteado (las policies permisivas se OR-ean). Así el
on-prem sigue funcionando sin el GUC cableado (cero regresión, SC-002) y en cuanto una
sesión setea el GUC el aislamiento es efectivo. La spec 017 (identidad fail-closed)
DEBE eliminar la policy bootstrap al cablear el GUC por request.

Idempotente (IF NOT EXISTS / ON CONFLICT DO NOTHING / DROP … IF EXISTS) y reversible
(downgrade destructivo del scope multi-tenant, documentado; restaurar los UNIQUE
globales falla si ya existen duplicados cross-tenant — solo para test/rollback).

Revision ID: 010
Revises: 009
Create Date: 2026-07-10
"""
from alembic import op

revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None

DEFAULT_TENANT = '00000000-0000-0000-0000-000000000001'

# Tablas tenant-scoped y su estrategia de backfill:
#   'default'    → todo al default tenant
#   'user'       → user_id → users.tenant_id, fallback default
#   'user_group' → user_id → users.tenant_id, luego group_id → groups.tenant_id, fallback default
# El orden importa: groups/users primero (los backfills relacionales dependen de users.tenant_id).
TENANT_TABLES = [
    ("groups", "default"),
    ("users", "default"),
    ("api_keys", "user_group"),
    ("budgets", "user_group"),
    ("audit_logs", "user"),
    ("consent_records", "user"),
    ("security_policies", "default"),
    ("guardians", "default"),
    ("compliance_projects", "default"),
    ("dpa_registry", "default"),
    ("data_subject_requests", "default"),
    ("human_reviews", "default"),
    ("retention_policies", "default"),
]

RLS_POLICY_PREDICATE = (
    "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)
# Ventana de deploy: sin GUC seteado, la sesión ve/escribe como hasta hoy (on-prem).
# Se elimina en 017 al cablear la identidad fail-closed.
BOOTSTRAP_PREDICATE = "NULLIF(current_setting('app.current_tenant', true), '') IS NULL"


def _add_fk_if_not_exists(table: str, constraint: str, fk_sql: str) -> None:
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = '{constraint}' AND conrelid = '{table}'::regclass
            ) THEN
                ALTER TABLE {table} ADD CONSTRAINT {constraint} {fk_sql};
            END IF;
        END $$;
    """)


def upgrade() -> None:
    # ── Paso 1: tabla tenants (sin FKs circulares a compliance/policy; se añaden al final)
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR NOT NULL,
            slug VARCHAR NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            deployment_mode VARCHAR NOT NULL DEFAULT 'on_premise'
                CONSTRAINT ck_tenants_deployment_mode CHECK (deployment_mode IN ('on_premise', 'cloud')),
            default_legal_basis VARCHAR,
            default_risk_level VARCHAR,
            default_compliance_project_id UUID,
            default_security_policy_id UUID,
            compression_mode VARCHAR DEFAULT 'off',
            compression_strategy VARCHAR DEFAULT 'deterministic',
            compression_threshold_tokens INTEGER,
            compression_aggressiveness VARCHAR DEFAULT 'medium',
            compression_cache_enabled BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_tenants_slug ON tenants (slug)")

    # ── Paso 2: default tenant determinista (pivote on-prem, FR-002)
    op.execute(f"""
        INSERT INTO tenants (id, name, slug, deployment_mode)
        VALUES ('{DEFAULT_TENANT}', 'Default Tenant', 'default', 'on_premise')
        ON CONFLICT (id) DO NOTHING
    """)

    # ── Paso 3: tenant_id + backfill + NOT NULL + FK + índice, por tabla (orden importa)
    for table, strategy in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id UUID")

        if strategy in ("user", "user_group"):
            op.execute(f"""
                UPDATE {table} t SET tenant_id = u.tenant_id
                FROM users u
                WHERE t.tenant_id IS NULL AND t.user_id = u.id AND u.tenant_id IS NOT NULL
            """)
        if strategy == "user_group":
            op.execute(f"""
                UPDATE {table} t SET tenant_id = g.tenant_id
                FROM groups g
                WHERE t.tenant_id IS NULL AND t.group_id = g.id AND g.tenant_id IS NOT NULL
            """)
        # Fallback explícito: filas huérfanas (user_id NULL, etc.) caen al default tenant
        # para que el SET NOT NULL no falle (FR-005).
        op.execute(f"UPDATE {table} SET tenant_id = '{DEFAULT_TENANT}' WHERE tenant_id IS NULL")

        op.execute(f"ALTER TABLE {table} ALTER COLUMN tenant_id SET NOT NULL")
        _add_fk_if_not_exists(
            table, f"fk_{table}_tenant", "FOREIGN KEY (tenant_id) REFERENCES tenants (id)"
        )
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)")

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_timestamp
        ON audit_logs (tenant_id, timestamp)
    """)

    # ── Paso 4: reconciliación de roles ([D9]) — backfill ANTES del CHECK (FR-009/FR-010)
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS display_label VARCHAR")
    op.execute("""
        UPDATE users SET role = 'client', display_label = COALESCE(display_label, 'clinician')
        WHERE role = 'clinician'
    """)
    op.execute("""
        UPDATE users SET role = 'client', display_label = COALESCE(display_label, 'developer')
        WHERE role = 'developer'
    """)
    op.execute("UPDATE users SET role = 'tenant_admin' WHERE role = 'admin'")
    # Catch-all para valores legacy sucios fuera del enum: degradan a client conservando
    # la etiqueta original (el ADD CONSTRAINT no puede fallar por datos no cubiertos).
    op.execute("""
        UPDATE users SET display_label = COALESCE(display_label, role), role = 'client'
        WHERE role NOT IN ('super_admin', 'tenant_admin', 'compliance_officer', 'client')
    """)
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_role")
    op.execute("""
        ALTER TABLE users ADD CONSTRAINT ck_users_role
        CHECK (role IN ('super_admin', 'tenant_admin', 'compliance_officer', 'client'))
    """)

    # ── Paso 5: client model (US5) — users.client_type + Connection (api_keys extendida)
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS client_type VARCHAR")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_client_type")
    op.execute("""
        ALTER TABLE users ADD CONSTRAINT ck_users_client_type
        CHECK (client_type IS NULL OR client_type IN ('base_url', 'desktop', 'chat_ui'))
    """)
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_client_type_role")
    op.execute("""
        ALTER TABLE users ADD CONSTRAINT ck_users_client_type_role
        CHECK (client_type IS NULL OR role = 'client')
    """)

    op.execute("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS tool_type VARCHAR")
    op.execute("UPDATE api_keys SET tool_type = 'claude-code' WHERE tool_type IS NULL")
    op.execute("ALTER TABLE api_keys ALTER COLUMN tool_type SET NOT NULL")
    op.execute("ALTER TABLE api_keys ALTER COLUMN tool_type SET DEFAULT 'claude-code'")
    op.execute("ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS ck_api_keys_tool_type")
    op.execute("""
        ALTER TABLE api_keys ADD CONSTRAINT ck_api_keys_tool_type
        CHECK (tool_type IN ('claude-code', 'copilot', 'cursor', 'claude-desktop', 'chatgpt', 'chat-ui'))
    """)

    op.execute("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS upstream_mode VARCHAR NOT NULL DEFAULT 'byok'")
    op.execute("ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS ck_api_keys_upstream_mode")
    op.execute("""
        ALTER TABLE api_keys ADD CONSTRAINT ck_api_keys_upstream_mode
        CHECK (upstream_mode IN ('subscription-passthrough', 'byok'))
    """)
    # Referencia a secreto Fernet, NUNCA el token OAuth en claro (SC-5, FR-015)
    op.execute("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS oauth_credential_ref VARCHAR")
    op.execute("ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS ck_api_keys_subscription_oauth")
    op.execute("""
        ALTER TABLE api_keys ADD CONSTRAINT ck_api_keys_subscription_oauth
        CHECK (upstream_mode != 'subscription-passthrough' OR oauth_credential_ref IS NOT NULL)
    """)
    # Toggles por-key (FR-014): NULL = heredar del group/tenant, valor = override
    op.execute("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS redact_enabled BOOLEAN")
    op.execute("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS compression_mode VARCHAR")
    op.execute("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS allowed_models JSONB")
    op.execute("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS allowed_tools JSONB")

    # ── Paso 6: unicidad compuesta por tenant (FR-017/FR-018)
    # Los UNIQUE inline de la 001 generan nombres auto <tabla>_<columna>_key; el DROP usa
    # esos nombres exactos (verificados contra la 001) para ser idempotente.
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_username_key")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_email_key")
    op.execute("ALTER TABLE groups DROP CONSTRAINT IF EXISTS groups_name_key")
    op.execute("DROP INDEX IF EXISTS users_username_key")
    op.execute("DROP INDEX IF EXISTS users_email_key")
    op.execute("DROP INDEX IF EXISTS groups_name_key")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_users_tenant_username ON users (tenant_id, username)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_users_tenant_email ON users (tenant_id, email)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_groups_tenant_name ON groups (tenant_id, name)
    """)
    # ≤1 Connection ACTIVA por herramienta por client; api_keys.key_hash queda UNIQUE
    # global (material secreto: una colisión debe ser global, FR-006).
    # Dedupe previo (hallazgo de review): el esquema legacy permitía N keys por user y
    # el backfill las deja todas en 'claude-code' — sin dedupe, el índice único explota
    # sobre una DB real. Se conserva ACTIVA la más reciente por (tenant, user, tool) y
    # las anteriores pasan a is_active=FALSE (solo bookkeeping local: la validez
    # efectiva de la key vive en el motor, que no se toca — cero revocación real).
    op.execute("""
        UPDATE api_keys k SET is_active = FALSE
        WHERE k.is_active IS TRUE AND k.user_id IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM api_keys k2
            WHERE k2.tenant_id = k.tenant_id AND k2.user_id = k.user_id
              AND k2.tool_type = k.tool_type AND k2.is_active IS TRUE
              AND (k2.created_at > k.created_at
                   OR (k2.created_at = k.created_at AND k2.id > k.id))
          )
    """)
    # Índice PARCIAL sobre keys activas: las filas históricas/desactivadas no
    # colisionan y re-emitir una Connection tras revocarla es válido.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_tenant_user_tool
        ON api_keys (tenant_id, user_id, tool_type)
        WHERE is_active IS TRUE
    """)

    # ── Paso 7: RLS — ENABLE + FORCE + policies (FR-019/FR-020/FR-021)
    for table, _ in TENANT_TABLES:
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

    # RLS también sobre la PROPIA tabla tenants (hallazgo de review: sin esto, una
    # sesión scopeada a un tenant vería nombres/slugs de todos los demás). La policy
    # scopea por id (la fila del tenant actual), con el mismo bypass y bootstrap.
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenants")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON tenants
        USING (id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
               OR current_setting('app.bypass_rls', true) = 'on')
        WITH CHECK (id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
                    OR current_setting('app.bypass_rls', true) = 'on')
    """)
    op.execute("DROP POLICY IF EXISTS tenant_isolation_bootstrap ON tenants")
    op.execute(f"""
        CREATE POLICY tenant_isolation_bootstrap ON tenants
        USING ({BOOTSTRAP_PREDICATE})
        WITH CHECK ({BOOTSTRAP_PREDICATE})
    """)

    # ── Paso 8: FKs circulares suaves de tenants (las tablas destino ya existen desde 001/004)
    _add_fk_if_not_exists(
        "tenants", "fk_tenants_default_compliance_project",
        "FOREIGN KEY (default_compliance_project_id) REFERENCES compliance_projects (id)",
    )
    _add_fk_if_not_exists(
        "tenants", "fk_tenants_default_security_policy",
        "FOREIGN KEY (default_security_policy_id) REFERENCES security_policies (id)",
    )


def downgrade() -> None:
    # Destructivo del scope multi-tenant (documentado; solo test/rollback).
    op.execute("ALTER TABLE tenants DROP CONSTRAINT IF EXISTS fk_tenants_default_compliance_project")
    op.execute("ALTER TABLE tenants DROP CONSTRAINT IF EXISTS fk_tenants_default_security_policy")

    for table, _ in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_bootstrap ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP INDEX IF EXISTS uq_api_keys_tenant_user_tool")
    op.execute("DROP INDEX IF EXISTS uq_users_tenant_username")
    op.execute("DROP INDEX IF EXISTS uq_users_tenant_email")
    op.execute("DROP INDEX IF EXISTS uq_groups_tenant_name")
    # Restaurar los UNIQUE globales de la 001 (falla si hay duplicados cross-tenant).
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_username_key') THEN
                ALTER TABLE users ADD CONSTRAINT users_username_key UNIQUE (username);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_email_key') THEN
                ALTER TABLE users ADD CONSTRAINT users_email_key UNIQUE (email);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'groups_name_key') THEN
                ALTER TABLE groups ADD CONSTRAINT groups_name_key UNIQUE (name);
            END IF;
        END $$;
    """)

    op.execute("ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS ck_api_keys_subscription_oauth")
    op.execute("ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS ck_api_keys_upstream_mode")
    op.execute("ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS ck_api_keys_tool_type")
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS allowed_tools")
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS allowed_models")
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS compression_mode")
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS redact_enabled")
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS oauth_credential_ref")
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS upstream_mode")
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS tool_type")

    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_client_type_role")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_client_type")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_role")
    # Revertir la reconciliación de roles ANTES de perder display_label (hallazgo de
    # review: sin esto, el código legacy no reconocería tenant_admin/client). No es
    # 100% inyectivo: los roles sucios degradados por el catch-all quedan 'client'
    # (su etiqueta original sigue en display_label hasta esta línea) y un super_admin
    # sembrado a mano no tiene equivalente legacy (queda tal cual, documentado).
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'tenant_admin'")
    op.execute("""
        UPDATE users SET role = display_label
        WHERE role = 'client' AND display_label IS NOT NULL
    """)
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS client_type")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS display_label")

    op.execute("DROP INDEX IF EXISTS ix_audit_logs_tenant_timestamp")
    for table, _ in reversed(TENANT_TABLES):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS fk_{table}_tenant")
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_tenant_id")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS tenant_id")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenants")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_bootstrap ON tenants")
    op.execute("DROP TABLE IF EXISTS tenants")
