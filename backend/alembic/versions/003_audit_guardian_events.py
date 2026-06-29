"""Add guardian_events column to audit_logs

Revision ID: 003
Revises: 002
Create Date: 2026-06-29
"""
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE audit_logs
            ADD COLUMN IF NOT EXISTS guardian_events JSONB DEFAULT '[]'
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE audit_logs
            DROP COLUMN IF EXISTS guardian_events
    """)
