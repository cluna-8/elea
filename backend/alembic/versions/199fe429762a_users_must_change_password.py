"""users_must_change_password

Pedido del dueño (21-sep-2026): cuando un admin fija la contraseña de un usuario (alta o
reseteo), el usuario debe poder/deber cambiarla en su próximo ingreso. `server_default=false`
para que ningún usuario ya existente quede forzado por este release — el flag solo se prende
desde el código, hacia adelante, en alta (`create_user`) y reseteo admin (`reset_user_password`).

Revision ID: 199fe429762a
Revises: 7a6fee614cfd
Create Date: 2026-09-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '199fe429762a'
down_revision: Union[str, None] = '7a6fee614cfd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('must_change_password', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('users', 'must_change_password')
