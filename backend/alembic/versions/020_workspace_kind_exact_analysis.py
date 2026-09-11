"""Extiende `workspaces` con `kind` para el modo de análisis exacto de datos (spec 048, T070).

Un espacio de análisis exacto (DB-GPT, spec 046/048) es un `Workspace` MÁS con
`kind='exact_analysis'` en vez de una entidad paralela — reusa `WorkspaceMembership`, RLS y el
patrón "sin asignar" ya construidos en la 018/043 sin duplicar ninguno de los tres (Reuse over
Reinvent, Development Workflow #2 de la constitución). Default `'rag'` para no romper ninguna fila
existente: todo `Workspace` de hoy sigue siendo, sin cambios, un espacio de chat RAG.

Idempotente (`IF NOT EXISTS`, `DROP CONSTRAINT IF EXISTS` antes de recrear el CHECK) y reversible.

Revision ID: 020
Revises: 019
Create Date: 2026-09-10
"""
from alembic import op

revision = '020'
down_revision = '019'
branch_labels = None
depends_on = None

_CHECK_NAME = "ck_workspaces_kind"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS kind VARCHAR NOT NULL DEFAULT 'rag'"
    )
    op.execute(f"ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS {_CHECK_NAME}")
    op.execute(
        f"ALTER TABLE workspaces ADD CONSTRAINT {_CHECK_NAME} "
        "CHECK (kind IN ('rag', 'exact_analysis'))"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS {_CHECK_NAME}")
    op.execute("ALTER TABLE workspaces DROP COLUMN IF EXISTS kind")
