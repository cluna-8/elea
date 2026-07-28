"""Tests de la migración 014 — precisión del contador de gasto (issue #76).

El bug que paga esta migración se midió en el ensayo del piloto: los tokens del
presupuesto subían y **el dinero no**. La causa no estaba en el servicio sino en la escala
de la columna: con `numeric(10,4)`, una llamada barata de verdad (~$0.000012 con
`gpt-4o-mini`) redondea a `0.0000` al guardarse. El contador sumaba cero para siempre y el
enforcement que lo lee —el 402 del motor, la otra mitad de #76— nunca llegaba al techo.

Por eso el test que importa no es el del `information_schema`: es el de la ACUMULACIÓN
contra Postgres de verdad (dos pedidos de $0.00001 tienen que valer $0.00002). El redondeo
lo hace la base, así que un test con un doble de sesión habría pasado en verde con la
columna vieja y el bug seguiría vivo.

Mismo harness que la 012/013: Postgres del Docker Compose, conectado como `rls_owner`
(NOSUPERUSER dueño de las tablas). Self-skip si Postgres no está.
"""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from migration_harness import (
    DEFAULT_TENANT, fresh_db, owner_engine, require_postgres, run_alembic,
)

require_postgres()

DB = "basa_test_migration_014"

# Coste de UNA llamada corta a un modelo económico, redondeado hacia arriba. Con la escala
# vieja (4 decimales) esto es exactamente 0.0000 — el bug entero en un número.
COSTE_BARATO = Decimal("0.00001")


@pytest.fixture(scope="module")
def engine():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    eng = owner_engine(DB)
    yield eng
    eng.dispose()


def _escala(cx, columna: str):
    return cx.execute(text("""
        SELECT numeric_precision, numeric_scale
        FROM information_schema.columns
        WHERE table_name = 'budgets' AND column_name = :col
    """), {"col": columna}).one_or_none()


# ── Esquema ────────────────────────────────────────────────────────────────────────────

def test_current_spend_usd_tiene_8_decimales(engine):
    with engine.connect() as cx:
        assert tuple(_escala(cx, "current_spend_usd")) == (14, 8)


def test_max_spend_usd_no_cambia(engine):
    """El TECHO lo escribe un humano en dólares con centavos: (10,4) le sobra y ampliarlo
    cambiaría el shape de un campo de formulario sin arreglar nada."""
    with engine.connect() as cx:
        assert tuple(_escala(cx, "max_spend_usd")) == (10, 4)


def test_la_base_ya_no_redondea_el_pedido_barato(engine):
    """Control directo del bug, sin ORM de por medio: el valor que antes se guardaba como
    0.0000 ahora sobrevive al INSERT."""
    fila = uuid.uuid4()
    with engine.begin() as cx:
        cx.execute(text("""
            INSERT INTO budgets (id, tenant_id, max_spend_usd, current_spend_usd,
                                 max_tokens, current_tokens, reset_period)
            VALUES (:id, :tenant, 10, :gasto, 1000000, 0, 'monthly')
        """), {"id": fila, "tenant": DEFAULT_TENANT, "gasto": COSTE_BARATO})
        guardado = cx.execute(text(
            "SELECT current_spend_usd FROM budgets WHERE id = :id"
        ), {"id": fila}).scalar()

    assert guardado == COSTE_BARATO, "la columna volvió a redondear el gasto a cero"


# ── Lo que el officer/admin ve: el contador se mueve ───────────────────────────────────

def test_dos_llamadas_baratas_acumulan_y_no_se_pierden(engine):
    """El anclaje de #76: 0.00001 + 0.00001 = 0.00002 pasando por el servicio REAL
    (`BudgetService.update_budget`), que es el único camino de carga de los dos planos
    —Playground y motor vía `/internal/audit`—. Con la escala vieja daba 0.0000 y el
    presupuesto no se agotaba nunca."""
    from src.models.budget import Budget
    from src.services.budget_service import BudgetService

    grupo = uuid.uuid4()
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = factory()
    try:
        db.execute(text(
            "INSERT INTO groups (id, tenant_id, name) VALUES (:id, :tenant, :nombre)"
        ), {"id": grupo, "tenant": DEFAULT_TENANT, "nombre": f"grupo-{grupo.hex[:8]}"})
        presupuesto = Budget(tenant_id=DEFAULT_TENANT, group_id=grupo,
                             max_spend_usd=Decimal("10"), current_spend_usd=Decimal("0"),
                             max_tokens=1_000_000, current_tokens=0, reset_period="monthly")
        db.add(presupuesto)
        db.commit()

        for _ in range(2):
            BudgetService.update_budget(db, group_id=str(grupo), prompt_tokens=100,
                                        completion_tokens=50, model="gpt-4o-mini",
                                        override_cost=COSTE_BARATO)

        db.refresh(presupuesto)
        gastado = presupuesto.current_spend_usd
        tokens = presupuesto.current_tokens
    finally:
        db.close()

    assert gastado == Decimal("0.00002"), f"el gasto no acumuló: {gastado}"
    assert tokens == 300, "los tokens ya acumulaban antes del fix; no se rompieron"


def test_el_coste_calculado_por_el_tarifario_tampoco_se_trunca(engine):
    """`calculate_cost` cuantiza a la MISMA escala de la columna: si truncara a 4 decimales
    antes de guardar, la migración no serviría de nada."""
    from src.services.budget_service import BudgetService

    # 100 tokens de entrada de gpt-4o-mini = 100/1e6 * $0.15 = $0.000015
    coste = BudgetService.calculate_cost("gpt-4o-mini", 100, 0)
    assert coste == Decimal("0.00001500"), coste
    assert coste.as_tuple().exponent == -8, "la escala del coste no es la de la columna"


# ── Convivencia con la cadena de licencias (SC-003 de la 031, FR-010) ──────────────────

def test_la_migracion_no_toca_la_hash_chain_de_licencias(engine):
    """`budgets` no participa del payload encadenado (`_append_chained` arma su dict desde
    `guardian_events`), así que cambiar la escala de una de sus columnas tiene que dejar la
    cadena válida y el head quieto. Si alguien mueve el gasto DENTRO de la cadena, se pone
    rojo acá."""
    from src.licensing.audit_events import EVENT_SEAT_LIMIT, emit_license_event, verify_chain
    from src.models.license_state import LicenseRuntimeState

    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = factory()
    try:
        for i in range(3):
            emit_license_event(db, EVENT_SEAT_LIMIT, license_id="lic_mig_014",
                               seats_used=10 + i, max_seats=10, reason=f"mig-014-{i}")
        head_antes = db.query(LicenseRuntimeState).filter_by(id=1).one().hash_head
        assert verify_chain(db)["ok"], "la cadena ya venía rota antes de tocar nada"
    finally:
        db.close()

    # Re-corre el cuerpo de la 014 sobre el esquema ya migrado (también prueba idempotencia)
    run_alembic(DB, "stamp", "013")
    run_alembic(DB, "upgrade", "head")

    db = factory()
    try:
        reporte = verify_chain(db)
        head_despues = db.query(LicenseRuntimeState).filter_by(id=1).one().hash_head
    finally:
        db.close()

    assert reporte["ok"], reporte
    assert reporte["checked"] >= 3
    assert head_despues == head_antes, "el head se movió: la migración entró a la cadena"

    with engine.connect() as cx:
        assert tuple(_escala(cx, "current_spend_usd")) == (14, 8), "re-correrla la deshizo"


# ── Ida y vuelta ───────────────────────────────────────────────────────────────────────

def test_downgrade_vuelve_a_la_escala_vieja_y_reupgrade_es_limpio(engine):
    """El downgrade REDONDEA (es la naturaleza de bajar la escala, y es exactamente el bug
    que la 014 arregla): se documenta acá para que nadie lo descubra en producción."""
    run_alembic(DB, "downgrade", "013")

    with engine.connect() as cx:
        assert tuple(_escala(cx, "current_spend_usd")) == (10, 4)
        # …y el gasto fino que había se perdió en el redondeo
        assert cx.execute(text(
            "SELECT COUNT(*) FROM budgets WHERE current_spend_usd = 0"
        )).scalar() >= 1

    run_alembic(DB, "upgrade", "head")
    with engine.connect() as cx:
        assert tuple(_escala(cx, "current_spend_usd")) == (14, 8)
