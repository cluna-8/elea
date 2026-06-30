"""Add compliance tables and audit_logs compliance columns

Revision ID: 004
Revises: 003
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    # compliance_projects
    op.execute("""
        CREATE TABLE IF NOT EXISTS compliance_projects (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR NOT NULL,
            description TEXT,
            legal_basis VARCHAR NOT NULL,
            legal_basis_notes TEXT,
            data_category VARCHAR DEFAULT 'standard',
            ai_act_risk_level VARCHAR DEFAULT 'limited',
            is_active BOOLEAN DEFAULT false,
            eu_region_required BOOLEAN DEFAULT false,
            human_review_required BOOLEAN DEFAULT false,
            ai_disclosure_enabled BOOLEAN DEFAULT true,
            ai_disclosure_message TEXT,
            dpia_reference VARCHAR,
            dpia_version VARCHAR,
            dpia_last_reviewed DATE,
            created_at VARCHAR,
            updated_at VARCHAR
        )
    """)

    # dpa_registry
    op.execute("""
        CREATE TABLE IF NOT EXISTS dpa_registry (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            provider_name VARCHAR NOT NULL,
            dpa_type VARCHAR DEFAULT 'standard',
            signed_date DATE,
            expiration_date DATE,
            covers_special_categories BOOLEAN DEFAULT false,
            processing_region VARCHAR DEFAULT 'global',
            document_reference TEXT,
            notes TEXT,
            is_active BOOLEAN DEFAULT true,
            created_at VARCHAR
        )
    """)

    # data_subject_requests
    op.execute("""
        CREATE TABLE IF NOT EXISTS data_subject_requests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            request_type VARCHAR NOT NULL,
            subject_identifier VARCHAR NOT NULL,
            date_received DATE NOT NULL,
            date_completed DATE,
            handled_by VARCHAR,
            status VARCHAR DEFAULT 'open',
            outcome_notes TEXT,
            created_at VARCHAR
        )
    """)

    # human_reviews
    op.execute("""
        CREATE TABLE IF NOT EXISTS human_reviews (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            audit_log_id UUID,
            review_token UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
            reviewer_id VARCHAR,
            action VARCHAR,
            notes TEXT,
            reviewed_at VARCHAR,
            created_at VARCHAR
        )
    """)

    # retention_policies
    op.execute("""
        CREATE TABLE IF NOT EXISTS retention_policies (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            log_type VARCHAR UNIQUE NOT NULL,
            retention_days INTEGER NOT NULL,
            justification TEXT,
            last_updated VARCHAR,
            updated_by VARCHAR,
            purge_log JSONB DEFAULT '[]'
        )
    """)

    # Seed default retention policies
    op.execute("""
        INSERT INTO retention_policies (id, log_type, retention_days, justification)
        VALUES
            (gen_random_uuid(), 'prompt_content', 90, 'Contenido de prompts y respuestas. Período mínimo para soporte técnico y auditoría de incidencias. Revisable por el DPO según DPIA del centro.'),
            (gen_random_uuid(), 'usage_metadata', 365, 'Metadatos de uso (tokens, coste, modelo, timestamps). Necesario para auditoría de costes y análisis de rendimiento durante 12 meses.'),
            (gen_random_uuid(), 'security_events', 365, 'Eventos de guardianes y alertas de seguridad. Necesario para detectar patrones de ataque y cumplir requisitos ENS.'),
            (gen_random_uuid(), 'config_audit', 730, 'Cambios de configuración del sistema. Mínimo 24 meses para trazabilidad de decisiones administrativas. No reducible por debajo de 365 días.')
        ON CONFLICT (log_type) DO NOTHING
    """)

    # Add columns to audit_logs
    op.execute("""
        ALTER TABLE audit_logs
            ADD COLUMN IF NOT EXISTS review_token UUID,
            ADD COLUMN IF NOT EXISTS ai_disclosure_delivered BOOLEAN DEFAULT false
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS human_reviews")
    op.execute("DROP TABLE IF EXISTS data_subject_requests")
    op.execute("DROP TABLE IF EXISTS dpa_registry")
    op.execute("DROP TABLE IF EXISTS compliance_projects")
    op.execute("DROP TABLE IF EXISTS retention_policies")
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS review_token")
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS ai_disclosure_delivered")
