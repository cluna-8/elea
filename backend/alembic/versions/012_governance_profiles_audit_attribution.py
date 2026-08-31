"""governance_profiles + atribución por pedido en audit_logs (spec 027 — data-model §1 y §3)

Esquema deliberadamente chico: **1 tabla nueva** y **2 columnas nuevas**. Todo vive en
la base del backend (``sentinel_gateway``); la base del motor NO recibe esquema — el motor
consume el perfil ya resuelto por la cascada, no leyendo estas tablas (D3).

Qué agrega:
* ``governance_profiles`` — una fila por decisión (D2): "para este alcance, esta capa
  opcional está on/off". La ausencia de fila es *heredar*. UNIQUE por
  (tenant, alcance, capa) + 3 CHECKs nombrados: enum de scope_type CERRADO (group/client
  son de la 015), enum de decision, y el CHECK compuesto que ata cada scope_type a su
  dominio de scope_value — su rama 'surface' es espejo EXACTO de ck_api_keys_tool_type
  y ambos deben evolucionar en la MISMA migración al agregar una superficie.
* ``audit_logs.applied_layers`` (JSONB) y ``audit_logs.blocked_by_layer`` (VARCHAR) +
  índice PARCIAL de bloqueos: los bloqueos son la excepción, indexar la tabla entera
  sería pagar por las filas que no interesan.
* **RLS sobre ``governance_profiles``** (hallazgo A1 de la verificación adversarial):
  es la única tabla nueva con ``tenant_id`` y, encima, la que decide QUÉ CAPAS DE
  SEGURIDAD CORREN. Sin backstop de base, el CRUD admin de US2 —que hace UPSERT/DELETE
  por PK, patrón habitual del repo— deja que el admin del tenant A apague ``pii_masking``
  del tenant B pasando un id ajeno. Se replican ENABLE + FORCE + las DOS policies con el
  MISMO predicado de la 010 (010_multitenant_foundation.py:78-84 y :274-289): un predicado
  propio sería una segunda semántica de aislamiento y el día que la 017 endurezca la
  ventana bootstrap, esta tabla quedaría afuera.

Qué NO hace, tan importante como lo que hace:
* **Cero seed de datos**: la postura por defecto emerge del ``default_decision`` del
  registry en código (D1). Sembrar filas convertiría el default de producto en dato
  borrable, y un tenant sin filas ya tiene postura completa (SC-007).
* **No toca ``guardians``**: ni columnas, ni filas, ni cardinalidad. Crítico porque el
  seed re-siembra destructivamente el catálogo si hay menos de 9 filas
  (guardian_service.py:33-36); esta migración no altera ese conteo y por eso es segura
  de correr. ``layer_key`` va sin FK por la misma razón: una FK a ``guardians.id`` se
  perdería en cascada en el próximo arranque.
* **No toca ``guardian_events``** ni hace backfill: queda congelado como legado (la
  hash-chain de licencias lo relee posicionalmente, licensing/audit_events.py:92-93).
  Las filas históricas quedan con ``applied_layers`` NULL — semántica explícita:
  "anterior a la atribución 027".

Revision ID: 012
Revises: 011
Create Date: 2026-07-22
"""
from alembic import op

revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None

# Copia LITERAL de los predicados de la 010 (010_multitenant_foundation.py:78-84). No se
# importan porque el módulo de la 010 no es importable por nombre (empieza con dígito) y
# alembic no expone las revisiones como paquete; la duplicación queda anclada por el test
# de RLS, que compara el predicado real de pg_policies contra el de las otras tablas.
RLS_POLICY_PREDICATE = (
    "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid "
    "OR current_setting('app.bypass_rls', true) = 'on'"
)
# Ventana de deploy heredada de la 010: sin GUC seteado, la sesión ve/escribe como hasta
# hoy (on-prem). Se elimina en 017 al cablear la identidad fail-closed — y debe eliminarse
# para TODAS las tablas a la vez, incluida esta.
BOOTSTRAP_PREDICATE = "NULLIF(current_setting('app.current_tenant', true), '') IS NULL"


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS governance_profiles (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL
                CONSTRAINT fk_governance_profiles_tenant REFERENCES tenants(id),
            scope_type VARCHAR NOT NULL,
            scope_value VARCHAR NOT NULL,
            -- Acotadas a propósito: esta tabla se EXPORTA como evidencia de auditoría.
            -- layer_key es una clave del registry en código (la más larga hoy ~20 chars);
            -- updated_by lleva el username/id del admin y NUNCA el email (ver el modelo).
            layer_key VARCHAR(64) NOT NULL,
            decision VARCHAR NOT NULL,
            updated_by VARCHAR(120) NOT NULL,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            CONSTRAINT uq_governance_profiles_scope
                UNIQUE (tenant_id, scope_type, scope_value, layer_key),
            CONSTRAINT ck_governance_profiles_scope_type
                CHECK (scope_type IN ('tenant_default', 'connection_mode', 'surface')),
            CONSTRAINT ck_governance_profiles_decision
                CHECK (decision IN ('on', 'off')),
            CONSTRAINT ck_governance_profiles_scope_pair
                CHECK (
                    (scope_type = 'tenant_default' AND scope_value = '*')
                    OR (scope_type = 'connection_mode'
                        AND scope_value IN ('subscription', 'gateway-models'))
                    OR (scope_type = 'surface'
                        AND scope_value IN ('claude-code', 'copilot', 'cursor',
                                            'claude-desktop', 'chatgpt', 'chat-ui'))
                )
        )
    """)
    # Nombre alineado con el que genera SQLAlchemy por `index=True` en tenant_id.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_governance_profiles_tenant_id
            ON governance_profiles (tenant_id)
    """)

    # ── RLS: mismo tratamiento que las 13 tablas tenant-scoped de la 010 (:274-289).
    # Es un BACKSTOP DE BASE, no la validación primaria: el router admin filtra por tenant,
    # pero un UPSERT/DELETE por PK con un id ajeno (patrón habitual del repo) se comería el
    # perfil de otro tenant y apagaría sus capas de seguridad. Idempotente (DROP IF EXISTS
    # antes de CREATE) porque la migración se re-corre sobre esquemas ya migrados.
    op.execute("ALTER TABLE governance_profiles ENABLE ROW LEVEL SECURITY")
    # FORCE: sin esto el DUEÑO de la tabla bypasea sus propias policies.
    op.execute("ALTER TABLE governance_profiles FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON governance_profiles")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON governance_profiles
        USING ({RLS_POLICY_PREDICATE})
        WITH CHECK ({RLS_POLICY_PREDICATE})
    """)
    op.execute("DROP POLICY IF EXISTS tenant_isolation_bootstrap ON governance_profiles")
    op.execute(f"""
        CREATE POLICY tenant_isolation_bootstrap ON governance_profiles
        USING ({BOOTSTRAP_PREDICATE})
        WITH CHECK ({BOOTSTRAP_PREDICATE})
    """)

    op.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS applied_layers JSONB")
    op.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS blocked_by_layer VARCHAR")
    # PARCIAL: los bloqueos son la excepción, no la norma.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_blocked_layer
            ON audit_logs (tenant_id, blocked_by_layer)
            WHERE blocked_by_layer IS NOT NULL
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_tenant_blocked_layer")
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS blocked_by_layer")
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS applied_layers")
    # Simétrico del upgrade. El DROP TABLE se llevaría las policies igual, pero se sueltan
    # explícitamente para que un downgrade parcial (o una tabla que sobreviva por datos)
    # no deje RLS forzada sin policies — eso sería un deny-all silencioso.
    # Va dentro de un DO guardado por to_regclass porque `DROP POLICY IF EXISTS` igual
    # explota si la TABLA no existe (el IF EXISTS es de la policy, no de la relación).
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('governance_profiles') IS NOT NULL THEN
                DROP POLICY IF EXISTS tenant_isolation_bootstrap ON governance_profiles;
                DROP POLICY IF EXISTS tenant_isolation ON governance_profiles;
                ALTER TABLE governance_profiles NO FORCE ROW LEVEL SECURITY;
                ALTER TABLE governance_profiles DISABLE ROW LEVEL SECURITY;
            END IF;
        END $$
    """)
    op.execute("DROP INDEX IF EXISTS ix_governance_profiles_tenant_id")
    op.execute("DROP TABLE IF EXISTS governance_profiles")
