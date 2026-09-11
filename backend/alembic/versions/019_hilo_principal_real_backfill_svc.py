"""Hilo principal respaldado por un hilo REAL del motor + red de seguridad para cuentas
`svc.*` que quedaron sin migrar (spec 043/044 — verificación en vivo 10-sep).

Dos piezas independientes, agrupadas por ser ambas correcciones chicas encontradas en la
misma corrida de pruebas manuales contra la UI real:

1. **Columna nueva** ``workspace_threads.principal_engine_thread_slug`` (nullable). Bug real
   encontrado: la fila con ``engine_thread_slug IS NULL`` ("hilo principal") solo probaba
   que la persona lo había reclamado en el backend — Eleia Hub (``client/server.js``) nunca
   creaba un hilo real en el motor de documentos para respaldarla, y en su lugar hablaba
   directo con el chat/historial A NIVEL DE ESPACIO de AnythingLLM, que es compartido por
   TODO el mundo sin dueño. Resultado (confirmado en vivo, sesión limpia, sin caché): un
   usuario nuevo agregado a un espacio veía la conversación completa de otro. Es
   textualmente el reclamo original de Tomás ("la memoria de chats es compartida"). Esta
   columna guarda el slug real del motor que respalda al hilo principal de cada persona —
   se crea la primera vez que lo usa (lazy), se reutiliza después. Nullable y sin default:
   no rompe nada para las filas ya existentes ni para instalaciones que todavía no migraron
   el código del Hub.

2. **Backfill de red de seguridad**: repite el backfill de ``account_type`` de la 018
   (``username LIKE 'svc.%' AND account_type = 'person'`` → ``'service'``). Por qué de
   nuevo: la 018 backfillea UNA vez, al migrar — cualquier instalación que haya creado sus
   cuentas de servicio con el código VIEJO de ``POST /users`` (antes del fix de esa misma
   fecha que hace que el alta nueva detecte el prefijo `svc.` sola) se queda con esas
   cuentas mal marcadas para siempre, sin otra forma de corregirlas. Confirmado en la
   verificación en vivo del 10-sep contra datos de una sesión anterior a ese fix. Idempotente
   — no hace nada si ya no queda ninguna fila así.

Idempotente (``IF NOT EXISTS``, backfill acotado por WHERE) y reversible.

Revision ID: 019
Revises: 018
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa

revision = '019'
down_revision = '018'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE workspace_threads "
        "ADD COLUMN IF NOT EXISTS principal_engine_thread_slug VARCHAR"
    )

    # Mismo criterio que la 018: username es la fuente de verdad del prefijo 'svc.' (ver
    # elea-installer/install.sh, create_service_key) — acotado a account_type='person' para
    # no tocar filas que ya estén bien.
    op.execute(
        "UPDATE users SET account_type = 'service' "
        "WHERE username LIKE 'svc.%' AND account_type = 'person'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE workspace_threads DROP COLUMN IF EXISTS principal_engine_thread_slug"
    )
    # El backfill de account_type no se revierte — mismo criterio que la 018 (downgrade no
    # deshace backfills de datos, solo estructura).
