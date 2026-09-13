"""Validación de SQL antes de ejecutar (spec 050 FR-023).

Regla: lo que no pasa se RECHAZA, nunca se "sanea". Una sola sentencia `SELECT`/`WITH`
(incluye UNION/INTERSECT/EXCEPT), sin funciones de archivo ni de sistema, sin tablas que
sean rutas, y con `LIMIT` acotado. Es la primera capa; la segunda es la conexión DuckDB de
solo lectura con `enable_external_access=false` (store.py).
"""
import re

import sqlglot
from sqlglot import exp

# Funciones que leen/escriben fuera de la base o tocan el entorno. DuckDB las bloquea
# igual con `enable_external_access=false`, pero rechazarlas acá da un error claro y
# evita depender de una sola capa.
_DENIED_FUNCTIONS = {
    "read_csv", "read_csv_auto", "read_parquet", "read_json", "read_json_auto",
    "read_json_objects", "read_text", "read_blob", "read_ndjson", "read_ndjson_auto",
    "sniff_csv", "glob", "parquet_scan", "csv_scan", "json_scan",
    "getenv", "current_setting", "duckdb_settings", "duckdb_secrets",
    "load", "install", "copy", "export", "import", "attach", "detach",
    "st_read", "iceberg_scan", "delta_scan", "sqlite_scan", "postgres_scan", "mysql_scan",
    "httpfs", "http_get", "http_post",
}

_DENIED_KEYWORDS = re.compile(
    r"\b(COPY|ATTACH|DETACH|INSTALL|LOAD|PRAGMA|EXPORT|IMPORT|CALL|CREATE|INSERT|UPDATE|"
    r"DELETE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|SET|RESET|VACUUM|CHECKPOINT|BEGIN|COMMIT|"
    r"ROLLBACK|EXECUTE|PREPARE)\b",
    re.IGNORECASE,
)

_FENCE = re.compile(r"^\s*```(?:sql)?\s*|\s*```\s*$", re.IGNORECASE)


class UnsafeSQL(ValueError):
    """La consulta no cumple la política de solo lectura; NO se ejecutó."""


class UnparsableSQL(UnsafeSQL):
    """sqlglot no pudo interpretar la consulta (visto 13-sep con un UNION ALL de 87 líneas sobre
    5 hojas). No es necesariamente insegura: el llamador puede aplicar `validate_fallback`, que
    exige forma de SELECT, sin palabras ni funciones prohibidas, y deja que DuckDB (conexión de
    solo lectura, sin acceso externo) la interprete y la acote con LIMIT."""


_DENIED_FN_RE = re.compile(r"\b(" + "|".join(sorted(_DENIED_FUNCTIONS)) + r")\s*\(", re.IGNORECASE)
_FILE_REF_RE = re.compile(r"'[^']*(\.(csv|parquet|json|xlsx|xls|txt|db|duckdb)|/|https?:|s3:)[^']*'", re.IGNORECASE)


def validate_fallback(sql: str, *, max_rows: int) -> str:
    """Validación conservadora sin AST. Devuelve `SELECT * FROM (<sql>) AS _q LIMIT n`."""
    raw = strip_fences(sql)
    if not raw or ";" in raw:
        raise UnsafeSQL("solo se acepta una sentencia")
    if not re.match(r"^\s*(SELECT|WITH)\b", raw, re.IGNORECASE):
        raise UnsafeSQL("solo se aceptan consultas de lectura (SELECT)")
    if _DENIED_KEYWORDS.search(raw):
        raise UnsafeSQL("la consulta contiene una operación no permitida")
    if _DENIED_FN_RE.search(raw):
        raise UnsafeSQL("la consulta usa una función no permitida")
    if _FILE_REF_RE.search(raw):
        raise UnsafeSQL("no se permite leer archivos ni recursos externos")
    if "--" in raw or "/*" in raw:
        raise UnsafeSQL("sin comentarios en la consulta")
    if raw.count("'") % 2 == 1:
        raise UnsafeSQL("comilla sin cerrar (consulta truncada)")
    return f"SELECT * FROM ({raw}) AS _q LIMIT {int(max_rows)}"


def strip_fences(sql: str) -> str:
    """Quita ```sql ... ``` si el modelo lo agregó igual, y el `;` final."""
    s = _FENCE.sub("", sql or "").strip()
    return s.rstrip(";").strip()


def validate(sql: str, *, max_rows: int, allowed_tables: set[str] | None = None) -> str:
    """Devuelve la sentencia normalizada (dialecto DuckDB) con LIMIT acotado, o lanza UnsafeSQL."""
    raw = strip_fences(sql)
    if not raw:
        raise UnsafeSQL("consulta vacía")
    if ";" in raw:
        raise UnsafeSQL("solo se acepta una sentencia")

    try:
        statements = sqlglot.parse(raw, read="duckdb")
    except sqlglot.errors.SqlglotError as e:  # ParseError, TokenError (comilla sin cerrar), etc.
        raise UnparsableSQL(f"no se pudo interpretar la consulta: {str(e).splitlines()[0]}") from e

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise UnsafeSQL("solo se acepta una sentencia")
    stmt = statements[0]

    if not isinstance(stmt, (exp.Select, exp.SetOperation)):
        raise UnsafeSQL(f"solo se aceptan consultas de lectura (SELECT), no {type(stmt).__name__}")

    for node in stmt.walk():
        # Cualquier sentencia no-SELECT anidada (ej. INSERT dentro de un CTE) o comando crudo.
        if isinstance(node, (exp.DDL, exp.DML, exp.Command, exp.Set, exp.Pragma, exp.Attach,
                             exp.Detach, exp.Copy, exp.Transaction, exp.Commit, exp.Rollback)):
            raise UnsafeSQL(f"no se permite {type(node).__name__} dentro de una consulta")
        if isinstance(node, exp.Func):
            name = (node.sql_name() or node.name or "").lower()
            if isinstance(node, exp.Anonymous):
                name = (node.name or "").lower()
            if name in _DENIED_FUNCTIONS:
                raise UnsafeSQL(f"la función {name}() no está permitida")
        if isinstance(node, exp.Table):
            tname = node.name or ""
            if "/" in tname or "\\" in tname or re.search(r"\.(csv|parquet|json|xlsx|xls|txt|db|duckdb)$", tname, re.I):
                raise UnsafeSQL("no se permite leer archivos directamente")
            if tname.lower().startswith(("http://", "https://", "s3://", "gs://", "az://")):
                raise UnsafeSQL("no se permite leer recursos externos")
            if allowed_tables is not None and tname and tname not in allowed_tables and not node.args.get("db"):
                # Tablas que no existen en el espacio: puede ser un CTE (se resuelve abajo).
                pass

    # CTEs válidos son nombres que el propio statement define.
    if allowed_tables is not None:
        cte_names = {c.alias_or_name for c in stmt.find_all(exp.CTE)}
        for t in stmt.find_all(exp.Table):
            if t.name and t.name not in allowed_tables and t.name not in cte_names:
                raise UnsafeSQL(f"la tabla {t.name} no existe en este espacio")

    # Palabras clave peligrosas que sqlglot pudo haber tolerado como identificadores.
    if _DENIED_KEYWORDS.search(stmt.sql(dialect="duckdb")) and _has_denied_top_level(stmt):
        raise UnsafeSQL("la consulta contiene una operación no permitida")

    # LIMIT forzado y acotado (FR-023).
    stmt = _cap_limit(stmt, max_rows)
    return stmt.sql(dialect="duckdb")


def _has_denied_top_level(stmt: exp.Expression) -> bool:
    """Evita falsos positivos: `set` como nombre de columna es válido; el keyword real no."""
    for node in stmt.walk():
        if isinstance(node, (exp.DDL, exp.DML, exp.Command, exp.Set, exp.Pragma)):
            return True
    return False


def _cap_limit(stmt: exp.Expression, max_rows: int) -> exp.Expression:
    limit = stmt.args.get("limit")
    if limit is None:
        if isinstance(stmt, exp.SetOperation):
            return exp.select("*").from_(stmt.subquery("q")).limit(max_rows)
        return stmt.limit(max_rows)
    try:
        current = int(limit.expression.name)
    except (AttributeError, ValueError):
        raise UnsafeSQL("LIMIT debe ser un número")
    if current > max_rows:
        limit.set("expression", exp.Literal.number(max_rows))
    return stmt
