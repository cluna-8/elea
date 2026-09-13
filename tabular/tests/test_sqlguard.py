"""FR-023: lo que no es un SELECT de solo lectura se rechaza sin ejecutar (SC-004)."""
import pytest

from app.sqlguard import UnsafeSQL, validate

T = {"f1_ventas", "f2_vendedores"}


def test_select_simple_agrega_limit():
    sql = validate("SELECT depto, SUM(monto) AS total FROM f1_ventas GROUP BY depto", max_rows=500, allowed_tables=T)
    assert sql.upper().startswith("SELECT")
    assert "LIMIT 500" in sql


def test_limit_mayor_se_acota():
    sql = validate("SELECT * FROM f1_ventas LIMIT 99999", max_rows=500, allowed_tables=T)
    assert "LIMIT 500" in sql and "99999" not in sql


def test_limit_menor_se_respeta():
    sql = validate("SELECT * FROM f1_ventas LIMIT 10", max_rows=500, allowed_tables=T)
    assert "LIMIT 10" in sql


def test_with_y_join_aceptados():
    sql = validate(
        "WITH v AS (SELECT vendedor, SUM(monto) m FROM f1_ventas GROUP BY vendedor) "
        "SELECT d.depto, SUM(v.m) FROM v JOIN f2_vendedores d ON d.vendedor = v.vendedor GROUP BY d.depto",
        max_rows=500, allowed_tables=T)
    assert "JOIN" in sql.upper()


def test_union_aceptado_con_limit():
    sql = validate("SELECT depto FROM f1_ventas UNION SELECT depto FROM f2_vendedores", max_rows=100, allowed_tables=T)
    assert "LIMIT 100" in sql


def test_fences_markdown_se_quitan():
    sql = validate("```sql\nSELECT * FROM f1_ventas;\n```", max_rows=5, allowed_tables=T)
    assert sql.upper().startswith("SELECT")


@pytest.mark.parametrize("bad", [
    "DROP TABLE f1_ventas",
    "DELETE FROM f1_ventas",
    "UPDATE f1_ventas SET monto = 0",
    "INSERT INTO f1_ventas VALUES (1)",
    "CREATE TABLE x AS SELECT 1",
    "ALTER TABLE f1_ventas ADD COLUMN y INT",
    "SELECT 1; DROP TABLE f1_ventas",
    "SELECT * FROM f1_ventas; SELECT 1",
    "COPY f1_ventas TO '/tmp/x.csv'",
    "ATTACH '/data/otro.duckdb' AS o",
    "PRAGMA database_list",
    "SET memory_limit='10GB'",
    "INSTALL httpfs",
    "LOAD httpfs",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM read_csv_auto('/etc/passwd')",
    "SELECT * FROM read_parquet('x.parquet')",
    "SELECT * FROM '/etc/passwd'",
    "SELECT * FROM 'datos.csv'",
    "SELECT * FROM 'https://x/y.csv'",
    "SELECT getenv('HOME')",
    "SELECT * FROM tabla_inexistente",
    "",
    "esto no es sql",
])
def test_rechazados(bad):
    with pytest.raises(UnsafeSQL):
        validate(bad, max_rows=500, allowed_tables=T)


def test_cte_no_se_confunde_con_tabla_inexistente():
    sql = validate("WITH t AS (SELECT 1 AS x FROM f1_ventas) SELECT x FROM t", max_rows=5, allowed_tables=T)
    assert "WITH" in sql.upper()


from app.sqlguard import UnparsableSQL, validate_fallback


def test_no_parseable_lanza_unparsable_y_fallback_acepta_select():
    with pytest.raises(UnparsableSQL):
        validate("SELECT 't5' AS tabla, NULL::INTEGER AS ano, FROM t5 WHERE (", max_rows=5, allowed_tables=T)
    sql = validate_fallback("SELECT 't1' AS tabla, nombre FROM t1 UNION ALL SELECT 't2', nombre FROM t2", max_rows=50)
    assert sql.startswith("SELECT * FROM (") and sql.endswith("LIMIT 50")


@pytest.mark.parametrize("bad", [
    "DROP TABLE t1", "SELECT 1; SELECT 2", "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM 'datos.csv'", "SELECT * FROM 'https://x/y'", "SELECT 1 -- comentario",
    "WITH x AS (SELECT 1) INSERT INTO t1 SELECT * FROM x", "SELECT getenv('HOME')",
])
def test_fallback_rechaza(bad):
    with pytest.raises(UnsafeSQL):
        validate_fallback(bad, max_rows=5)


def test_comilla_sin_cerrar_no_explota():
    with pytest.raises(UnparsableSQL):
        validate("SELECT * FROM t1 WHERE nombre ILIKE '%iot", max_rows=5, allowed_tables=T)
    with pytest.raises(UnsafeSQL):
        validate_fallback("SELECT * FROM t1 WHERE nombre ILIKE '%iot", max_rows=5)


def test_union_all_by_name_aceptado():
    sql = validate("SELECT 'Ventas' AS hoja, * FROM f1_ventas UNION ALL BY NAME SELECT 'Vendedores' AS hoja, * FROM f2_vendedores",
                   max_rows=100, allowed_tables=T)
    assert "BY NAME" in sql.upper() and "LIMIT 100" in sql
