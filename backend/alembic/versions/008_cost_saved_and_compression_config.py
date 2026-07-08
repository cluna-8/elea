"""Add cost_saved_usd to audit_logs and compression_* config to groups/security_policies

Spec 012 — Ahorro de Costes IA (US3 + US4).

* audit_logs.cost_saved_usd  — ahorro USD real por request comprimida (US3).
* groups.compression_*        — config de compresión por grupo (US4).
* security_policies.compression_mode — flag global renombrado de headroom_mode (US4);
  se migra el valor viejo y se mantiene headroom_mode por compatibilidad (deprecado).

Revision ID: 008
Revises: 007
Create Date: 2026-07-07
"""
from alembic import op

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade():
    # US3 — ahorro USD real persistido por request
    op.execute("""
        ALTER TABLE audit_logs
        ADD COLUMN IF NOT EXISTS cost_saved_usd NUMERIC(10,6) DEFAULT 0
    """)

    # US4 — config de compresión por grupo
    op.execute("""
        ALTER TABLE groups
        ADD COLUMN IF NOT EXISTS compression_mode VARCHAR DEFAULT 'off'
    """)
    op.execute("""
        ALTER TABLE groups
        ADD COLUMN IF NOT EXISTS compression_strategy VARCHAR DEFAULT 'deterministic'
    """)
    op.execute("""
        ALTER TABLE groups
        ADD COLUMN IF NOT EXISTS compression_threshold_tokens INTEGER
    """)
    op.execute("""
        ALTER TABLE groups
        ADD COLUMN IF NOT EXISTS compression_aggressiveness VARCHAR DEFAULT 'medium'
    """)
    op.execute("""
        ALTER TABLE groups
        ADD COLUMN IF NOT EXISTS compression_cache_enabled BOOLEAN DEFAULT false
    """)

    # US4 — flag global renombrado (headroom_mode -> compression_mode)
    op.execute("""
        ALTER TABLE security_policies
        ADD COLUMN IF NOT EXISTS compression_mode BOOLEAN DEFAULT false
    """)
    # Migrar el valor viejo de headroom_mode al nuevo flag (una sola vez)
    op.execute("""
        UPDATE security_policies
        SET compression_mode = headroom_mode
        WHERE compression_mode IS NULL AND headroom_mode IS NOT NULL
    """)
    # Migrar grupos: si tenían headroom activo vía policy global, respetar 'off' por defecto
    # (la activación por grupo se hace explícita desde la UI de Costos — US4).


def downgrade():
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS cost_saved_usd")
    op.execute("ALTER TABLE groups DROP COLUMN IF EXISTS compression_mode")
    op.execute("ALTER TABLE groups DROP COLUMN IF EXISTS compression_strategy")
    op.execute("ALTER TABLE groups DROP COLUMN IF EXISTS compression_threshold_tokens")
    op.execute("ALTER TABLE groups DROP COLUMN IF EXISTS compression_aggressiveness")
    op.execute("ALTER TABLE groups DROP COLUMN IF EXISTS compression_cache_enabled")
    op.execute("ALTER TABLE security_policies DROP COLUMN IF EXISTS compression_mode")