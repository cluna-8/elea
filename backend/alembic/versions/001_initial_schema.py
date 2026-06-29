"""Initial schema baseline

Revision ID: 001
Revises:
Create Date: 2026-06-29

Creates all original tables using IF NOT EXISTS so it is safe
to run against an already-populated database.
"""
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR NOT NULL UNIQUE,
            description VARCHAR,
            engine_team_id VARCHAR,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_groups_name ON groups (name)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_groups_engine_team_id ON groups (engine_team_id)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            username VARCHAR NOT NULL UNIQUE,
            email VARCHAR NOT NULL UNIQUE,
            password_hash VARCHAR NOT NULL,
            role VARCHAR NOT NULL,
            group_id UUID REFERENCES groups(id),
            engine_user_id VARCHAR,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_users_username ON users (username)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_users_engine_user_id ON users (engine_user_id)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            key_hash VARCHAR NOT NULL UNIQUE,
            key_preview VARCHAR NOT NULL,
            engine_key_token VARCHAR,
            user_id UUID REFERENCES users(id),
            group_id UUID REFERENCES groups(id),
            name VARCHAR NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_api_keys_key_hash ON api_keys (key_hash)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_api_keys_engine_key_token ON api_keys (engine_key_token)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id),
            group_id UUID REFERENCES groups(id),
            max_spend_usd NUMERIC(10,4) NOT NULL,
            current_spend_usd NUMERIC(10,4) DEFAULT 0.0000,
            max_tokens BIGINT NOT NULL,
            current_tokens BIGINT DEFAULT 0,
            reset_period VARCHAR NOT NULL,
            last_reset_at TIMESTAMP DEFAULT NOW(),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS security_policies (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            entity_configs JSONB NOT NULL,
            gdpr_mode BOOLEAN DEFAULT TRUE,
            ai_act_mode BOOLEAN DEFAULT TRUE,
            headroom_mode BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS guardians (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR NOT NULL,
            guardian_type VARCHAR NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            config JSON DEFAULT '{}'
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timestamp TIMESTAMP DEFAULT NOW(),
            user_id UUID REFERENCES users(id),
            api_key_id UUID REFERENCES api_keys(id),
            model VARCHAR NOT NULL,
            prompt_tokens INTEGER NOT NULL,
            completion_tokens INTEGER NOT NULL,
            cost_usd NUMERIC(10,6) NOT NULL,
            pii_detected BOOLEAN DEFAULT FALSE,
            masked_entities JSONB,
            compliance_status VARCHAR NOT NULL,
            latency_ms INTEGER NOT NULL,
            tokens_saved_by_optimization INTEGER DEFAULT 0
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_audit_logs_timestamp ON audit_logs (timestamp)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_logs")
    op.execute("DROP TABLE IF EXISTS guardians")
    op.execute("DROP TABLE IF EXISTS security_policies")
    op.execute("DROP TABLE IF EXISTS budgets")
    op.execute("DROP TABLE IF EXISTS api_keys")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP TABLE IF EXISTS groups")
