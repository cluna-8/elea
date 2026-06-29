"""Add response_text to human_reviews

Revision ID: 007
Revises: 006
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE human_reviews
        ADD COLUMN IF NOT EXISTS response_text TEXT
    """)


def downgrade():
    op.execute("ALTER TABLE human_reviews DROP COLUMN IF EXISTS response_text")
