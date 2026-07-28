"""routing_decision en audit_logs — decisión del auto-router semántico (spec 030, data-model §3)

Esquema mínimo deliberado: **1 columna nueva**, nada más. La decisión de ruteo ya viaja
por dos superficies efímeras (``pipeline_metadata.layer_llm.auto_router`` del Debugger y
el campo ``routing`` del evento de vitrina); esta columna es la tercera y la única
DURABLE — sin ella, "por qué esta consulta fue al modelo caro" se pierde al cerrar la
pestaña y FR-006 no se puede auditar a posteriori.

Qué agrega:
* ``audit_logs.routing_decision`` (JSONB) — el objeto decisión completo de data-model §2:
  ``{requested, route, score, model_selected, degraded, reason}``. **Metadata-only**: la
  ruta es una etiqueta de config y el score un número; JAMÁS entra texto del prompt (mismo
  contrato de no-fuga que rige ``applied_layers``, audit.py:34-40).

Qué NO hace, tan importante como lo que hace:
* **Nullable, sin default y sin backfill**: las filas históricas no tuvieron ruteo y NULL
  significa exactamente eso — "esta consulta no pasó por el auto-router" (el caso normal
  hoy: sólo el camino ``model == "auto"`` escribe acá). Un default ``'{}'`` volvería
  indistinguible "no hubo ruteo" de "hubo ruteo vacío".
* **Sin índice**: en v1 la decisión se lee como DETALLE de una fila ya localizada por
  tenant+timestamp, nunca como filtro. Un índice sobre JSONB (GIN) costaría escritura en
  la tabla más caliente del sistema para una query que nadie hace.
* **No toca ``applied_layers``** (contrato C1 de la 027: sólo códigos del registry y
  contadores — la decisión de ruteo no es una capa de gobierno y meterla ahí contaminaría
  el vocabulario cerrado) **ni ``guardian_events``**, que queda congelado como legado: la
  hash-chain de licencias lo relee POSICIONALMENTE (licensing/audit_events.py:92-93).
* **La cadena de hash NO cambia**: su payload lo arma ``_append_chained`` con un dict de
  claves fijas (audit_events.py:178-187) y ``verify_chain`` lo recomputa desde
  ``guardian_events[0]`` — ninguno de los dos mira las columnas de la fila. Agregar una
  columna al lado deja los hashes de los eventos existentes bit a bit idénticos (anclado
  por los tests de licensing/hash-chain, que son el gate de esta migración).

Revision ID: 013
Revises: 012
Create Date: 2026-07-28
"""
from alembic import op

revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade():
    # IF NOT EXISTS (patrón de la 012): la migración se re-corre sobre esquemas ya migrados.
    op.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS routing_decision JSONB")


def downgrade():
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS routing_decision")
