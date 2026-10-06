"""Migración `3d1f1bd93c73` — marcas `cache_hit` / `cost_estimated` en `audit_logs`.

Gasto en cero (specs/ANALISIS-GASTO-CERO-2026-10.md §9). Lo que importa: las filas
históricas y las que inserta un motor viejo (que no manda las marcas) quedan en `false`,
o sea que ningún cero anterior cambia de significado, y la migración se puede repetir.

Mismo harness que la 012/013/014: Postgres del Docker Compose; self-skip si no está.
"""
import pytest
from sqlalchemy import text

from migration_harness import DEFAULT_TENANT, fresh_db, owner_engine, require_postgres, run_alembic

require_postgres()

DB = "sentinel_test_migration_audit_cache_hit"
REV = "3d1f1bd93c73"


@pytest.fixture(scope="module")
def engine():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    eng = owner_engine(DB)
    yield eng
    eng.dispose()


def _columna(cx, nombre):
    return cx.execute(text("""
        SELECT data_type, is_nullable, column_default FROM information_schema.columns
        WHERE table_name = 'audit_logs' AND column_name = :c"""), {"c": nombre}).one_or_none()


@pytest.mark.parametrize("nombre", ["cache_hit", "cost_estimated"])
def test_columnas_booleanas_not_null_default_false(engine, nombre):
    with engine.connect() as cx:
        tipo, nulo, defecto = _columna(cx, nombre)
    assert tipo == "boolean" and nulo == "NO" and defecto == "false"


def test_un_insert_sin_las_marcas_queda_en_false(engine):
    """Retrocompatibilidad: el INSERT de un motor viejo no las menciona."""
    with engine.begin() as cx:
        cx.execute(text("""
            INSERT INTO audit_logs (tenant_id, model, prompt_tokens, completion_tokens,
                                    cost_usd, compliance_status, latency_ms)
            VALUES (:t, 'm-sin-marcas', 1, 1, 0, 'passed', 1)"""), {"t": DEFAULT_TENANT})
        fila = cx.execute(text("SELECT cache_hit, cost_estimated FROM audit_logs "
                               "WHERE model = 'm-sin-marcas'")).one()
    assert (fila.cache_hit, fila.cost_estimated) == (False, False)


def test_downgrade_y_upgrade_son_repetibles(engine):
    run_alembic(DB, "downgrade", "199fe429762a")
    with engine.connect() as cx:
        assert _columna(cx, "cache_hit") is None and _columna(cx, "cost_estimated") is None
    run_alembic(DB, "upgrade", "head")
    run_alembic(DB, "upgrade", "head")  # idempotente: segunda vez es no-op
    with engine.connect() as cx:
        assert _columna(cx, "cache_hit") is not None
