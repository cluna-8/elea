"""069 enmienda — «parámetros no soportados» en la ficha de la entrada del catálogo (data-model §7).

Cuarta revisión de la rama propia `sentinel_redirect` (sigue a `d5b8e3a1c742`). Agrega a
`ext_catalog_entry` la columna `unsupported_params` (lista JSON de nombres de parámetros del pedido que el
modelo no acepta, p. ej. `["temperature"]`). Las filas existentes quedan con `[]`: sin valores precargados
por modelo, lo marca el administrador en la ficha. La RLS de la tabla no cambia.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "f7a3c1d9e508"
down_revision = "d5b8e3a1c742"
branch_labels = None
depends_on = None

TABLE = "ext_catalog_entry"


def upgrade():
    op.add_column(TABLE, sa.Column("unsupported_params", pg.JSONB, nullable=False,
                                   server_default=sa.text("'[]'::jsonb")))


def downgrade():
    op.drop_column(TABLE, "unsupported_params")
