"""guardians.created_at: desempate determinista de la postura pii_masking (issue #104)

El bug (hallazgo #6 del gate del PR #97, severidad MEDIA): con DOS guardianes `pii_masking`
activos en un tenant, los CUATRO lectores de la postura NLP (`nlp_fail_mode`) elegían la fila
con `LIMIT 1`/`.first()` SIN `ORDER BY`. La postura efectiva quedaba ARBITRARIA y podía diferir
entre el backend, el motor y lo que reporta `/health`. El propio `_IDENTITY_SQL` ya había
resuelto esto para el PRESUPUESTO (#76) con `ORDER BY created_at, id` («determinismo puro»),
pero la tabla `guardians` no tenía columna por la que ordenar: sólo `id` (un UUID aleatorio de
`gen_random_uuid()`, que da un orden estable pero sin sentido de "más antigua").

Qué agrega: una columna `created_at TIMESTAMP` para que el desempate sea el MISMO criterio
que el del presupuesto y "la fila más antigua" recupere su sentido literal.

Por qué NO un unique constraint sobre (tenant_id, guardian_type) —la otra opción del issue—:
una instalación que ya tenga dos `pii_masking` activos haría FALLAR la migración. El fix
primario y seguro es el `ORDER BY (created_at, id)` en los cuatro lectores; el constraint
parcial queda como follow-up, y sólo con un paso de dedup previo.

Por qué es segura para installs con datos existentes:
* Es ADITIVA e idempotente (mismo patrón que la 002): `ADD COLUMN IF NOT EXISTS`.
* `DEFAULT NOW()` es estable dentro de la transacción de la migración, así que TODAS las
  filas preexistentes reciben el MISMO instante. Entre ellas el desempate lo pone la PK `id`
  —determinista igual—, y las filas nuevas traen su timestamp real.
* `NOT NULL` queda satisfecho por el default en el mismo ALTER: no hay ventana con NULLs.

Revision ID: 015
Revises: 014
Create Date: 2026-08-08
"""
from alembic import op

revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE guardians
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW()
    """)


def downgrade():
    op.execute("ALTER TABLE guardians DROP COLUMN IF EXISTS created_at")
