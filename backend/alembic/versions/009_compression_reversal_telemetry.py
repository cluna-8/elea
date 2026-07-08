"""Add compression telemetry + reversal columns to audit_logs (spec 012 — US5/US6 close)

* audit_logs.compression_strategy VARCHAR  — estrategia de compresión aplicada
  ('deterministic' | 'headroom' | 'none'); permite telemetría por estrategia y
  detectar reversiones repetidas por estrategia (US6.3).
* audit_logs.compression_reversed BOOLEAN — True cuando la guardia de calidad (US6)
  detectó una respuesta anómala tras compresión y reintentó con el prompt original.

El flag ``llm`` (US5) queda **descartado** por la restricción verbatim
"no gastar tokens para ahorrar tokens": la compresión LLM-asistida es circular
(gasta tokens para ahorrar tokens). Se mantiene la caché Redis por hash (sin tokens)
y la guardia de reversión (US6).

Revision ID: 009
Revises: 008
Create Date: 2026-07-08
"""
from alembic import op

revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE audit_logs
        ADD COLUMN IF NOT EXISTS compression_strategy VARCHAR DEFAULT 'none'
    """)
    op.execute("""
        ALTER TABLE audit_logs
        ADD COLUMN IF NOT EXISTS compression_reversed BOOLEAN DEFAULT false
    """)


def downgrade():
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS compression_reversed")
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS compression_strategy")