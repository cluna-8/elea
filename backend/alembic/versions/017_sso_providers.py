"""SSO providers por tenant (spec 017 US2 — T013): esquema + RLS.

Tabla nueva ``sso_providers``: una fila por (tenant, provider_type) con la config del IdP
(directory/tenant ID, client_id, metadata de discovery) y la REFERENCIA Fernet al client
secret —``client_secret_encrypted``, jamás el secreto en claro—. El cifrado/descifrado lo
hace el consumidor con ``services/encryption_service`` (la ruta SSO, L/M); esta migración
sólo crea la columna VARCHAR. v1 registra ``provider_type='entra'`` (Microsoft Entra ID).

RLS: tabla tenant-scoped, mismo tratamiento EXACTO que las 13 de la 010 y que
``governance_profiles`` (012) — ``ENABLE`` + ``FORCE`` + las DOS policies con el predicado
LITERAL de la 010 (010_multitenant_foundation.py:78-84). Es un BACKSTOP DE BASE: el CRUD
admin de la ruta SSO hace UPSERT/DELETE por PK (patrón habitual del repo) y sin RLS el admin
del tenant A podría pisar el proveedor SSO del tenant B pasando un id ajeno. La policy
permisiva ``tenant_isolation_bootstrap`` la elimina T020 junto con las demás tablas al cablear
la identidad fail-closed por request — NO se resuelve acá.

Idempotente (IF NOT EXISTS / DROP … IF EXISTS) y reversible (downgrade: DROP POLICY x2 +
DROP INDEX x2 + DROP TABLE).

Revision ID: 017
Revises: 016
Create Date: 2026-08-21
"""
from alembic import op

revision = '017'
down_revision = '016'
branch_labels = None
depends_on = None

# Copia LITERAL de los predicados de la 010 (010_multitenant_foundation.py:78-84), igual que la
# 012 (:51-62): el módulo de la 010 no es importable por nombre (empieza con dígito) y alembic
# no expone las revisiones como paquete. La duplicación queda anclada por el test de RLS, que
# compara el predicado real de pg_policies de esta tabla contra el de las tablas de la 010.
RLS_POLICY_PREDICATE = (
    "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)
# Ventana de deploy heredada de la 010: sin GUC seteado, la sesión ve/escribe como hasta hoy
# (on-prem). La elimina la 017/T020 para TODAS las tablas a la vez, incluida ésta.
BOOTSTRAP_PREDICATE = "NULLIF(current_setting('app.current_tenant', true), '') IS NULL"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS sso_providers (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL
                CONSTRAINT fk_sso_providers_tenant REFERENCES tenants(id),
            provider_type VARCHAR NOT NULL,
            config JSONB,
            -- REFERENCIA Fernet al client secret, NUNCA el secreto en claro (mismo contrato
            -- que api_keys.oauth_credential_ref, 010:216). El encrypt lo hace el consumidor.
            client_secret_encrypted VARCHAR,
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    # Nombre alineado con el que genera SQLAlchemy por `index=True` en tenant_id.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sso_providers_tenant_id
            ON sso_providers (tenant_id)
    """)
    # ≤1 proveedor por (tenant, tipo): índice único. Va como CREATE UNIQUE INDEX IF NOT EXISTS
    # (y no un CONSTRAINT inline) para ser idempotente sobre esquemas ya migrados — un ADD
    # CONSTRAINT no se re-agrega limpio cuando el CREATE TABLE IF NOT EXISTS es un no-op.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_sso_providers_tenant_type
            ON sso_providers (tenant_id, provider_type)
    """)

    # ── RLS: mismo tratamiento que las 13 tablas de la 010 (:274-289) y la 012 (:104-123).
    op.execute("ALTER TABLE sso_providers ENABLE ROW LEVEL SECURITY")
    # FORCE: sin esto el DUEÑO de la tabla —el rol del runtime— bypasea sus propias policies.
    op.execute("ALTER TABLE sso_providers FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON sso_providers")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON sso_providers
        USING ({RLS_POLICY_PREDICATE})
        WITH CHECK ({RLS_POLICY_PREDICATE})
    """)
    op.execute("DROP POLICY IF EXISTS tenant_isolation_bootstrap ON sso_providers")
    op.execute(f"""
        CREATE POLICY tenant_isolation_bootstrap ON sso_providers
        USING ({BOOTSTRAP_PREDICATE})
        WITH CHECK ({BOOTSTRAP_PREDICATE})
    """)


def downgrade() -> None:
    # Simétrico del upgrade. El DROP TABLE se llevaría las policies igual, pero se sueltan
    # explícitamente para que un downgrade parcial (o una tabla que sobreviva por datos) no deje
    # RLS forzada sin policies — eso sería un deny-all silencioso. Va dentro de un DO guardado
    # por to_regclass porque `DROP POLICY IF EXISTS` igual explota si la TABLA no existe (el IF
    # EXISTS es de la policy, no de la relación). Mismo cuidado que la 012.
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('sso_providers') IS NOT NULL THEN
                DROP POLICY IF EXISTS tenant_isolation_bootstrap ON sso_providers;
                DROP POLICY IF EXISTS tenant_isolation ON sso_providers;
                ALTER TABLE sso_providers NO FORCE ROW LEVEL SECURITY;
                ALTER TABLE sso_providers DISABLE ROW LEVEL SECURITY;
            END IF;
        END $$
    """)
    op.execute("DROP INDEX IF EXISTS uq_sso_providers_tenant_type")
    op.execute("DROP INDEX IF EXISTS ix_sso_providers_tenant_id")
    op.execute("DROP TABLE IF EXISTS sso_providers")
