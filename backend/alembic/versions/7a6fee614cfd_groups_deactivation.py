"""groups_deactivation

Spec 054 (17-sep-2026, mail del dueño tras probar la atribución de costos en vivo):
"es un error grave el no poder desactivar un grupo". Hasta esta migración, `groups` no
tenía ningún campo de ciclo de vida — un equipo se podía crear pero nunca dar de baja,
a diferencia de `users` (`is_active`/`deactivated_at`, migración base). Mismo criterio
que la baja de usuario: NO es baja física — la auditoría histórica del grupo
(`audit_logs.user_group_id`, `budgets.group_id`) sigue intacta y visible bajo su nombre.

Revision ID: 7a6fee614cfd
Revises: 020
Create Date: 2026-09-17 10:40:10.117091

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7a6fee614cfd'
down_revision: Union[str, None] = '020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('groups', sa.Column('is_active', sa.Boolean(), nullable=False,
                                       server_default=sa.true()))
    op.add_column('groups', sa.Column('deactivated_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('groups', 'deactivated_at')
    op.drop_column('groups', 'is_active')
