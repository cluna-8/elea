"""Add engine guardrail fields to guardians table

Revision ID: 002
Revises: 001
Create Date: 2026-06-29
"""
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TABLE ... ADD COLUMN IF NOT EXISTS is idempotent — safe on both
    # fresh and already-migrated databases.
    op.execute("""
        ALTER TABLE guardians
            ADD COLUMN IF NOT EXISTS engine_guardrail_name VARCHAR,
            ADD COLUMN IF NOT EXISTS fail_mode VARCHAR DEFAULT 'log',
            ADD COLUMN IF NOT EXISTS apply_on VARCHAR DEFAULT 'pre_call',
            ADD COLUMN IF NOT EXISTS service_api_key_encrypted TEXT
    """)

    # Seed engine_guardrail_name for the guardian types that map to the AI engine
    op.execute("""
        UPDATE guardians
        SET engine_guardrail_name = 'litellm_content_filter',
            fail_mode = 'block',
            apply_on = 'both'
        WHERE guardian_type = 'openai_moderation'
          AND engine_guardrail_name IS NULL
    """)
    op.execute("""
        UPDATE guardians
        SET engine_guardrail_name = 'promptguard',
            fail_mode = 'block',
            apply_on = 'pre_call'
        WHERE guardian_type = 'lakera_prompt_injection'
          AND engine_guardrail_name IS NULL
    """)
    op.execute("""
        UPDATE guardians
        SET engine_guardrail_name = 'azure/text_moderations',
            fail_mode = 'block',
            apply_on = 'both'
        WHERE guardian_type = 'azure_content_safety'
          AND engine_guardrail_name IS NULL
    """)
    op.execute("""
        UPDATE guardians
        SET engine_guardrail_name = 'azure/prompt_shield',
            fail_mode = 'block',
            apply_on = 'pre_call'
        WHERE guardian_type = 'llamaguard_moderations'
          AND engine_guardrail_name IS NULL
    """)
    op.execute("""
        UPDATE guardians
        SET engine_guardrail_name = 'bedrock_guardrails',
            fail_mode = 'block',
            apply_on = 'pre_call'
        WHERE guardian_type = 'bedrock_guardrails'
          AND engine_guardrail_name IS NULL
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE guardians
            DROP COLUMN IF EXISTS engine_guardrail_name,
            DROP COLUMN IF EXISTS fail_mode,
            DROP COLUMN IF EXISTS apply_on,
            DROP COLUMN IF EXISTS service_api_key_encrypted
    """)
