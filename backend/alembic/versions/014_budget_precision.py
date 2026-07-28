"""budgets.current_spend_usd: numeric(10,4) → numeric(14,8) (issue #76, precisión del contador)

El bug, medido en el ensayo del piloto (28-jul): el contador de gasto se quedaba
**congelado en $0.0000** mientras los tokens sí subían. No era el servicio: era la escala
de la columna. Con `numeric(10,4)` Postgres redondea al guardar, y una llamada barata de
verdad —el caso NORMAL con `gpt-4o-mini` ($0.165/$0.66 por millón)— cuesta del orden de
$0.000012: menos de medio último dígito, o sea **0.0000**. El presupuesto sumaba cero una y
otra vez, y el enforcement que se apoya en ese número (el 402 de `custom_auth`, mitad
"cortar" de #76) no cortaba nunca porque el gasto jamás llegaba al techo.

Qué agrega:
* `budgets.current_spend_usd` pasa a `NUMERIC(14,8)`: 8 decimales resuelven ~1e-8 USD, tres
  órdenes de magnitud por debajo del pedido más barato que se factura hoy. Los 6 dígitos
  enteros (14-8) se conservan exactos: el techo sigue siendo $999.999,99999999, el mismo
  rango que ya tenía con (10,4).

Qué NO hace, tan importante como lo que hace:
* **No toca `max_spend_usd`.** El TECHO lo escribe un humano en la UI en dólares con
  centavos; (10,4) le sobra. Ampliarlo no arregla nada y cambiaría el shape de un campo de
  formulario. Postgres compara `numeric` de escalas distintas sin perder precisión, así que
  `current_spend_usd < max_spend_usd` sigue siendo exacto.
* **No hay backfill ni conversión de datos.** El `ALTER TYPE` de numeric a una escala MAYOR
  es una ampliación: los valores existentes se preservan bit a bit (0.0012 → 0.00120000).
  Lo que ya se perdió por redondeo es irrecuperable —esos centavos nunca se guardaron— y
  esta migración no inventa historia.
* **No toca `audit_logs.cost_usd`.** Esa columna ya es `NUMERIC(10,6)` (001): resuelve al
  microdólar, que le alcanza al coste de UN pedido (~$0.000012 es 0.000012, no 0). Quien
  no llegaba era el ACUMULADOR, con dos decimales menos y sumando pedido tras pedido.
  Deuda declarada, no disimulada: por debajo de 1e-6 la fila de auditoría sigue
  redondeando, y cuando eso importe se corrige con su propia migración.
* **La cadena de hash NO cambia**: `_append_chained` arma su payload con un dict de claves
  fijas de `guardian_events` (licensing/audit_events.py:178-187) y `verify_chain` lo
  recomputa desde ahí — ninguno de los dos mira `budgets`. El gate de esta migración son
  los tests de licensing/hash-chain, que siguen verdes sin tocarlos.

Revision ID: 014
Revises: 013
Create Date: 2026-07-28
"""
from alembic import op

revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None


def upgrade():
    # Idempotente por CONDICIÓN y no por `IF NOT EXISTS` (que ALTER TYPE no tiene): la
    # migración se re-corre sobre esquemas ya migrados (mismo requisito que la 012/013) y
    # un ALTER TYPE repetido reescribiría la tabla entera para nada.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'budgets' AND column_name = 'current_spend_usd'
                  AND (numeric_precision, numeric_scale) IS DISTINCT FROM (14, 8)
            ) THEN
                ALTER TABLE budgets
                    ALTER COLUMN current_spend_usd TYPE NUMERIC(14, 8);
            END IF;
        END $$;
    """)


def downgrade():
    # Vuelta a (10,4). OJO: acá SÍ se pierde dato (Postgres redondea al reducir la escala) —
    # es la naturaleza del downgrade, y es exactamente el bug que la 014 arregla.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'budgets' AND column_name = 'current_spend_usd'
                  AND (numeric_precision, numeric_scale) IS DISTINCT FROM (10, 4)
            ) THEN
                ALTER TABLE budgets
                    ALTER COLUMN current_spend_usd TYPE NUMERIC(10, 4);
            END IF;
        END $$;
    """)
