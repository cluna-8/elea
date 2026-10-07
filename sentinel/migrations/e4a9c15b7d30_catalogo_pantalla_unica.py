"""069 enmienda — pantalla única «Modelos»: columnas nuevas de la entrada del catálogo (data-model §7).

Tercera revisión de la rama propia `sentinel_redirect` (sigue a `c3f1a7d9e204`). Agrega a
`ext_catalog_entry`: `limits` (rpm, tpm, max_parallel_requests, timeout, num_retries), `base_model`,
precios de caché (`price_cache_read`/`price_cache_write`, USD por token) y por tramos (`price_tiers`),
y `advanced` (parámetros libres validados por la API contra una lista corta de claves). Amplía el
CHECK de `role` a texto, embeddings, imagen, audio y reranking (FR-060). Las filas existentes quedan
igual (`{}` y NULL); la RLS de la tabla no cambia.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "e4a9c15b7d30"
down_revision = "c3f1a7d9e204"
branch_labels = None
depends_on = None

TABLE = "ext_catalog_entry"
OLD_ROLES = "role IN ('text','embeddings')"
NEW_ROLES = "role IN ('text','embeddings','image','audio','rerank')"


def upgrade():
    op.add_column(TABLE, sa.Column("limits", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column(TABLE, sa.Column("base_model", sa.Text))
    op.add_column(TABLE, sa.Column("price_cache_read", sa.Numeric(20, 12)))
    op.add_column(TABLE, sa.Column("price_cache_write", sa.Numeric(20, 12)))
    op.add_column(TABLE, sa.Column("price_tiers", pg.JSONB))
    op.add_column(TABLE, sa.Column("advanced", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.drop_constraint("ck_ext_entry_role", TABLE, type_="check")
    op.create_check_constraint("ck_ext_entry_role", TABLE, NEW_ROLES)


def downgrade():
    # una entrada de imagen/audio/reranking no cabe en el vocabulario anterior: se archiva antes de volver
    op.execute(f"UPDATE {TABLE} SET status = 'archived', archived_reason = 'downgrade: tipo de modelo no soportado' "
               "WHERE role NOT IN ('text','embeddings') AND status <> 'archived'")
    op.execute(f"UPDATE {TABLE} SET role = 'text' WHERE role NOT IN ('text','embeddings')")
    op.drop_constraint("ck_ext_entry_role", TABLE, type_="check")
    op.create_check_constraint("ck_ext_entry_role", TABLE, OLD_ROLES)
    for col in ("advanced", "price_tiers", "price_cache_write", "price_cache_read", "base_model", "limits"):
        op.drop_column(TABLE, col)
