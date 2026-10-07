"""069 US10 — routing por costo v1: estrategia de elección por regla de redirección.

Sigue a `a7d2f9c4b816` en la rama propia `sentinel_redirect`. Agrega `strategy` a
`sentinel_redirect_rule` (`order` = el orden de la regla, como hasta ahora; `cheapest` = el destino
elegible más barato primero). Las filas existentes quedan en `order`; la RLS no cambia.
"""
import sqlalchemy as sa
from alembic import op

revision = "d5b8e3a1c742"
down_revision = "a7d2f9c4b816"
branch_labels = None
depends_on = None

TABLE = "sentinel_redirect_rule"
CK = "ck_redirect_rule_strategy"


def upgrade():
    op.add_column(TABLE, sa.Column("strategy", sa.String(16), nullable=False, server_default="order"))
    op.create_check_constraint(CK, TABLE, "strategy IN ('order','cheapest')")


def downgrade():
    op.drop_constraint(CK, TABLE, type_="check")
    op.drop_column(TABLE, "strategy")
