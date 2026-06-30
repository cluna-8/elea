"""Add individual compliance fields to users and api_keys

Revision ID: 006
Revises: 005
Create Date: 2026-06-30
"""

from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    # Individual compliance override on users
    op.execute("""
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS legal_basis VARCHAR,
            ADD COLUMN IF NOT EXISTS risk_level VARCHAR,
            ADD COLUMN IF NOT EXISTS compliance_project_id UUID REFERENCES compliance_projects(id) ON DELETE SET NULL
    """)

    # Compliance project assignment on api_keys
    op.execute("""
        ALTER TABLE api_keys
            ADD COLUMN IF NOT EXISTS compliance_project_id UUID REFERENCES compliance_projects(id) ON DELETE SET NULL
    """)


def downgrade():
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS legal_basis")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS risk_level")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS compliance_project_id")
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS compliance_project_id")
