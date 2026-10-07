"""057 R40 — el default de la etiqueta de un id publicado pasa a `requested`.

Novena revisión de la rama propia `sentinel_redirect`: sigue a `89a92524eef6` (la cabeza anterior en Eleia). Id por hash
(`alembic revision`). Solo cambia el DEFAULT de la columna `sentinel_redirect_published_model.label_mode`: de `destination`
(el cliente veía «Sonnet · servido por <destino>») a `requested` (el cliente ve el id Claude que pidió y nunca el destino).
Las filas existentes NO se tocan: lo que un administrador dejó en `destination` o `custom` sigue igual (la etiqueta es dato
suyo, no se cambia en silencio). La restricción CHECK de los tres valores no cambia; la RLS tampoco.
"""
from alembic import op

revision = "0529902015ad"
down_revision = "89a92524eef6"
branch_labels = None
depends_on = None

TABLE, COLUMN = "sentinel_redirect_published_model", "label_mode"


def upgrade():
    op.alter_column(TABLE, COLUMN, server_default="requested")


def downgrade():
    op.alter_column(TABLE, COLUMN, server_default="destination")
