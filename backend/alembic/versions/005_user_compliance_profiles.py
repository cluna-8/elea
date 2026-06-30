"""Add user compliance profiles: group compliance fields, consent records, rate limits, audit purpose

Revision ID: 005
Revises: 004
Create Date: 2026-06-29
"""

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    # Extend groups table with compliance profile fields
    op.execute("""
        ALTER TABLE groups
            ADD COLUMN IF NOT EXISTS default_legal_basis VARCHAR,
            ADD COLUMN IF NOT EXISTS default_risk_level VARCHAR,
            ADD COLUMN IF NOT EXISTS compliance_project_id UUID REFERENCES compliance_projects(id) ON DELETE SET NULL
    """)

    # Add rate limiting columns to api_keys
    op.execute("""
        ALTER TABLE api_keys
            ADD COLUMN IF NOT EXISTS rpm_limit INTEGER DEFAULT 60,
            ADD COLUMN IF NOT EXISTS tpm_limit INTEGER DEFAULT 100000
    """)

    # Add processing purpose and group tracking to audit_logs
    op.execute("""
        ALTER TABLE audit_logs
            ADD COLUMN IF NOT EXISTS processing_purpose VARCHAR,
            ADD COLUMN IF NOT EXISTS user_group_id UUID
    """)

    # Create consent_records table
    op.execute("""
        CREATE TABLE IF NOT EXISTS consent_records (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            consent_type VARCHAR NOT NULL,
            version VARCHAR NOT NULL,
            granted_at TIMESTAMP NOT NULL DEFAULT NOW(),
            revoked_at TIMESTAMP,
            ip_address VARCHAR,
            notes TEXT
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_consent_records_user_id ON consent_records (user_id)")

    # Seed default group compliance profiles for existing groups
    op.execute("""
        UPDATE groups SET
            default_legal_basis = CASE
                WHEN name ILIKE '%medic%' OR name ILIKE '%clinico%' OR name ILIKE '%clinic%' THEN 'art_9_2_h'
                WHEN name ILIKE '%enferm%' THEN 'art_9_2_h'
                WHEN name ILIKE '%investig%' OR name ILIKE '%research%' THEN 'art_9_2_j'
                ELSE 'art_6_1_e'
            END,
            default_risk_level = CASE
                WHEN name ILIKE '%medic%' OR name ILIKE '%clinico%' OR name ILIKE '%clinic%' THEN 'high_risk_annex3'
                WHEN name ILIKE '%enferm%' THEN 'high_risk_annex3'
                ELSE 'limited'
            END
        WHERE default_legal_basis IS NULL
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS consent_records")
    op.execute("DROP INDEX IF EXISTS ix_consent_records_user_id")
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS processing_purpose")
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS user_group_id")
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS rpm_limit")
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS tpm_limit")
    op.execute("ALTER TABLE groups DROP COLUMN IF EXISTS default_legal_basis")
    op.execute("ALTER TABLE groups DROP COLUMN IF EXISTS default_risk_level")
    op.execute("ALTER TABLE groups DROP COLUMN IF EXISTS compliance_project_id")
