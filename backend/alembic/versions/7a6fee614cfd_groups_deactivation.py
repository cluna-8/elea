"""groups_deactivation

Spec 054 (17-sep-2026, mail del dueño tras probar la atribución de costos en vivo):
"es un error grave el no poder desactivar un grupo". Hasta esta migración, `groups` no
tenía ningún campo de ciclo de vida — un equipo se podía crear pero nunca dar de baja,
a diferencia de `users` (`is_active`/`deactivated_at`, migración base). Mismo criterio
que la baja de usuario: NO es baja física — la auditoría histórica del grupo
(`audit_logs.user_group_id`, `budgets.group_id`) sigue intacta y visible bajo su nombre.

Idempotente (`ADD COLUMN IF NOT EXISTS`, mismo patrón que la 015): los tests de
idempotencia re-corren el cuerpo de las migraciones posteriores sobre un esquema ya
migrado, y una base con la versión adelantada no debe abortar el arranque. Mismo id y
mismo `down_revision`; en bases ya migradas es un no-op.

Revision ID: 7a6fee614cfd
Revises: 020
Create Date: 2026-09-17 10:40:10.117091

"""
from typing import Sequence, Union

from alembic import op


revision: str = '7a6fee614cfd'
down_revision: Union[str, None] = '020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS is_active "
               "BOOLEAN NOT NULL DEFAULT true")
    op.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMP")


def downgrade() -> None:
    op.execute("ALTER TABLE groups DROP COLUMN IF EXISTS deactivated_at")
    op.execute("ALTER TABLE groups DROP COLUMN IF EXISTS is_active")
