"""audit_cache_hit_cost_estimated

Gasto en cero (specs/ANALISIS-GASTO-CERO-2026-10.md §9): dos marcas booleanas en `audit_logs`
para que un cero ya no sea mudo. `cache_hit` = el motor sirvió el pedido desde su caché de
respuestas (costo 0 real); `cost_estimated` = el motor no informó costo y `cost_usd` es el del
tarifario del backend. Metadata-only (booleanos). `NOT NULL DEFAULT false`: ninguna fila
histórica cambia de significado y el motor viejo, que no las manda, sigue insertando igual.

Idempotente (`ADD COLUMN IF NOT EXISTS`, mismo patrón que la 199fe429762a).

Revision ID: 3d1f1bd93c73
Revises: 199fe429762a
Create Date: 2026-10-06 12:56:32.806326

"""
from typing import Sequence, Union

from alembic import op


revision: str = '3d1f1bd93c73'
down_revision: Union[str, None] = '199fe429762a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS cache_hit "
               "BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS cost_estimated "
               "BOOLEAN NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS cost_estimated")
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS cache_hit")
