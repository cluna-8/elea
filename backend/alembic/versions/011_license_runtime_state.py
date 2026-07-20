"""license_runtime_state: estado runtime de licencia (spec 021 US5 — FR-023/FR-028)

Una fila singleton (id=1) por deployment con:
* hash_head + event_counter — ancla local de la cadena de hashes de los eventos
  de licencia (FR-028); avanzan con cada evento, bajo FOR UPDATE.
* genesis_license_id — ancla de la génesis de la cadena (se registra en el
  onboarding; el primer true-up se verifica contra ella).
* monotonic_ts — marca monotónica anti-rollback de reloj (FR-023): un tick con
  now < marca emite license_clock_rollback_suspected y degrada la creación.

NO es schema del dominio (013 intacta): es el "pequeño estado" que el plan de
la 021 anticipa explícitamente.

Revision ID: 011
Revises: 010
Create Date: 2026-07-20
"""
from alembic import op

revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS license_runtime_state (
            id INTEGER PRIMARY KEY,
            genesis_license_id VARCHAR,
            anchored_license_id VARCHAR,
            hash_head VARCHAR,
            event_counter BIGINT NOT NULL DEFAULT 0,
            monotonic_ts TIMESTAMP,
            updated_at TIMESTAMP,
            CONSTRAINT ck_license_runtime_state_singleton CHECK (id = 1)
        )
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS license_runtime_state")
