"""Almacén por espacio: archivos crudos + una base DuckDB por espacio (spec 050 FR-021/023/025).

Layout en `TABULAR_DATA_DIR`:
    spaces/<workspace_id>/db.duckdb      base con una tabla por hoja/archivo
    spaces/<workspace_id>/meta.json      índice de archivos y tablas
    spaces/<workspace_id>/files/<id>.<ext>   el archivo original (vive acá, nunca sale)

Carga (escritura) y consulta (lectura) usan conexiones distintas, serializadas por un lock
por espacio: DuckDB no deja abrir el mismo archivo con configuraciones distintas a la vez.
"""
from __future__ import annotations

import csv
import datetime as dt
import decimal
import io
import json
import math
import re
import threading
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

_WS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_IDENT_RE = re.compile(r"[^a-z0-9_]+")
SUPPORTED = {"csv", "xlsx"}


class SpaceNotFound(KeyError):
    pass


class SpaceExists(KeyError):
    pass


class UnsupportedFormat(ValueError):
    pass


class EmptyTable(ValueError):
    pass


class QueryTimeout(TimeoutError):
    pass


def _slug(s: str, fallback: str = "t") -> str:
    # Acentos fuera, no reemplazados por "_": "Almacén" → "almacen" (bug real con planillas de
    # Elea: quedaba "almac_n" y el modelo no reconocía la columna).
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = _IDENT_RE.sub("_", s.strip().lower()).strip("_")
    if not s:
        s = fallback
    if s[0].isdigit():
        s = f"c_{s}"
    return s[:48]


def _json_safe(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        # Ruido de coma flotante de Excel (5554422.999999899, 115910370208.62003): dos
        # decimales alcanzan para cifras de negocio y evitan que el modelo los copie tal cual.
        return round(v, 2)
    if isinstance(v, (int, str, bool)):
        return v
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", "replace")
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _json_safe(x) for k, x in v.items()}
    if hasattr(v, "item"):  # numpy scalar
        return _json_safe(v.item())
    return str(v)


@dataclass
class TableInfo:
    name: str
    columns: list[dict]           # [{name, type, label}]
    rows: int
    sample: list[dict] = field(default_factory=list)
    alias: str = ""               # vista corta `tN` que usa el modelo en el SQL
    sheet: str | None = None      # nombre original de la hoja en el Excel (None para csv)

    def as_dict(self) -> dict:
        return {"name": self.name, "alias": self.alias, "sheet": self.sheet, "columns": self.columns,
                "rows": self.rows, "sample": self.sample}


class SpaceStore:
    def __init__(self, data_dir: str, *, memory_limit: str = "1GB", threads: int = 2,
                 sample_rows: int = 5):
        self.root = Path(data_dir) / "spaces"
        self.root.mkdir(parents=True, exist_ok=True)
        self.memory_limit = memory_limit
        self.threads = threads
        self.sample_rows = sample_rows
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ── rutas ────────────────────────────────────────────────────────────────
    @staticmethod
    def valid_id(ws: str) -> bool:
        return bool(_WS_RE.match(ws or ""))

    def _dir(self, ws: str) -> Path:
        if not self.valid_id(ws):
            raise SpaceNotFound(ws)
        return self.root / ws

    def _db(self, ws: str) -> Path:
        return self._dir(ws) / "db.duckdb"

    def _meta_path(self, ws: str) -> Path:
        return self._dir(ws) / "meta.json"

    def _lock(self, ws: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(ws, threading.Lock())

    def exists(self, ws: str) -> bool:
        return self.valid_id(ws) and self._db(ws).exists()

    def _require(self, ws: str) -> None:
        if not self.exists(ws):
            raise SpaceNotFound(ws)

    def _read_meta(self, ws: str) -> dict:
        p = self._meta_path(ws)
        if not p.exists():
            return {"files": []}
        return json.loads(p.read_text("utf-8"))

    def _write_meta(self, ws: str, meta: dict) -> None:
        tmp = self._meta_path(ws).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self._meta_path(ws))

    # ── conexiones ───────────────────────────────────────────────────────────
    def _rw(self, ws: str) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(str(self._db(ws)), config={
            "memory_limit": self.memory_limit, "threads": self.threads,
            "enable_external_access": "false",
        })
        return con

    def _ro(self, ws: str) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(str(self._db(ws)), read_only=True, config={
            "memory_limit": self.memory_limit, "threads": self.threads,
            "enable_external_access": "false",
        })
        con.execute("SET lock_configuration = true")
        return con

    # ── espacios ─────────────────────────────────────────────────────────────
    def create_space(self, ws: str) -> None:
        if not self.valid_id(ws):
            raise ValueError("workspace_id inválido")
        d = self._dir(ws)
        if self._db(ws).exists():
            raise SpaceExists(ws)
        (d / "files").mkdir(parents=True, exist_ok=True)
        with self._lock(ws):
            con = self._rw(ws)
            con.close()
            self._write_meta(ws, {"files": []})

    def list_files(self, ws: str) -> list[dict]:
        self._require(ws)
        return self._read_meta(ws)["files"]

    def table_names(self, ws: str) -> set[str]:
        """Nombres válidos en SQL: alias `tN` y nombre largo (compatibilidad)."""
        out = set()
        for f in self.list_files(ws):
            for t in f["tables"]:
                out.add(t["name"])
                if t.get("alias"):
                    out.add(t["alias"])
        return out

    @staticmethod
    def _next_alias(con: duckdb.DuckDBPyConnection) -> str:
        existing = {r[0] for r in con.execute(
            "SELECT view_name FROM duckdb_views() WHERE NOT internal").fetchall()}
        k = 1
        while f"t{k}" in existing:
            k += 1
        return f"t{k}"

    def ensure_aliases(self, ws: str) -> None:
        """Espacios cargados antes de los alias: crea la vista `tN` que falte (una vez)."""
        meta = self._read_meta(ws)
        pending = [t for f in meta["files"] for t in f["tables"] if not t.get("alias")]
        if not pending:
            return
        with self._lock(ws):
            con = self._rw(ws)
            try:
                # Vistas `tN` huérfanas (sin alias en meta) se descartan antes de asignar.
                usados = {t.get("alias") for f in meta["files"] for t in f["tables"] if t.get("alias")}
                for (v,) in con.execute("SELECT view_name FROM duckdb_views() WHERE NOT internal").fetchall():
                    if re.fullmatch(r"t\d+", v) and v not in usados:
                        con.execute(f'DROP VIEW IF EXISTS "{v}"')
                for t in pending:
                    t["alias"] = self._next_alias(con)
                    con.execute(f'CREATE VIEW IF NOT EXISTS "{t["alias"]}" AS SELECT * FROM "{t["name"]}"')
            finally:
                con.close()
            self._write_meta(ws, meta)

    # ── carga ────────────────────────────────────────────────────────────────
    def load_file(self, ws: str, filename: str, content: bytes) -> dict:
        self._require(ws)
        ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
        if ext not in SUPPORTED:
            raise UnsupportedFormat(ext or "sin extensión")

        frames = self._read_frames(ext, filename, content)
        file_id = uuid.uuid4().hex[:12]
        meta = self._read_meta(ws)
        n = len(meta["files"]) + 1
        base = _slug(Path(filename).stem, "archivo")

        with self._lock(ws):
            (self._dir(ws) / "files" / f"{file_id}.{ext}").write_bytes(content)
            con = self._rw(ws)
            tables: list[TableInfo] = []
            try:
                existing = self.table_names(ws)
                for sheet, df in frames:
                    if df.empty or df.shape[1] == 0:
                        continue
                    df, labels = self._normalize_columns(df)
                    tname = f"f{n}_{base}" if sheet is None else f"f{n}_{base}_{_slug(sheet, 'hoja')}"
                    tname = self._unique(tname, existing)
                    existing.add(tname)
                    con.register("_df", df)
                    con.execute(f'CREATE TABLE "{tname}" AS SELECT * FROM _df')
                    con.unregister("_df")
                    info = self._describe(con, tname, labels)
                    # Alias corto `tN` como VISTA: es el nombre que ve el modelo y que usa en el
                    # SQL. Motivo real (planilla CDCV, 12-sep): el firewall de Guardian tomó el
                    # nombre largo `f1_tabla_datos_recogida_de_datos` por un nombre de persona y
                    # lo enmascaró; el SQL volvió con el placeholder y no ejecutó. `t3` no se
                    # confunde con nada.
                    info.alias = self._next_alias(con)
                    info.sheet = sheet
                    con.execute(f'CREATE VIEW "{info.alias}" AS SELECT * FROM "{tname}"')
                    tables.append(info)
            finally:
                con.close()
            if not tables:
                (self._dir(ws) / "files" / f"{file_id}.{ext}").unlink(missing_ok=True)
                raise EmptyTable("el archivo no tiene datos")
            entry = {
                "file_id": file_id, "name": filename, "ext": ext,
                "uploaded_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "tables": [t.as_dict() for t in tables],
            }
            meta["files"].append(entry)
            self._write_meta(ws, meta)
        return entry

    def delete_file(self, ws: str, file_id: str) -> bool:
        self._require(ws)
        meta = self._read_meta(ws)
        entry = next((f for f in meta["files"] if f["file_id"] == file_id), None)
        if not entry:
            return False
        with self._lock(ws):
            con = self._rw(ws)
            try:
                for t in entry["tables"]:
                    if t.get("alias"):
                        con.execute(f'DROP VIEW IF EXISTS "{t["alias"]}"')
                    con.execute(f'DROP TABLE IF EXISTS "{t["name"]}"')
            finally:
                con.close()
            (self._dir(ws) / "files" / f"{file_id}.{entry['ext']}").unlink(missing_ok=True)
            meta["files"] = [f for f in meta["files"] if f["file_id"] != file_id]
            self._write_meta(ws, meta)
        return True

    @staticmethod
    def _detect_header(raw: pd.DataFrame) -> pd.DataFrame:
        """Planillas armadas a mano (caso real CDCV): título y notas arriba, encabezado real
        varias filas más abajo, columnas vacías a los lados. Se elige como encabezado la
        primera fila (entre las 25 primeras) cuyas celdas no vacías son todas texto, son al
        menos 2 y cubren ≥ 60 % del ancho útil. Si ninguna califica, se usa la primera fila."""
        df = raw.dropna(how="all").dropna(axis=1, how="all")
        if df.empty:
            return df
        width = df.shape[1]
        header_idx = None
        for i in range(min(25, len(df))):
            vals = [v for v in df.iloc[i].tolist() if pd.notna(v) and str(v).strip() != ""]
            if len(vals) >= 2 and len(vals) >= 0.6 * width and all(isinstance(v, str) for v in vals):
                header_idx = i
                break
        if header_idx is None:
            header_idx = 0
        header = df.iloc[header_idx].tolist()
        body = df.iloc[header_idx + 1:].reset_index(drop=True)
        names = [str(h).strip() if pd.notna(h) and str(h).strip() else f"col_{j + 1}"
                 for j, h in enumerate(header)]
        body.columns = names
        body = body.dropna(how="all")
        # Columnas sin encabezado y sin datos (solo tenían una nota arriba del encabezado): fuera.
        sin_nombre = {n for n, h in zip(names, header) if pd.isna(h) or not str(h).strip()}
        vacias = [c for c in body.columns if c in sin_nombre and body[c].isna().all()]
        return body.drop(columns=vacias)

    @staticmethod
    def _read_frames(ext: str, filename: str, content: bytes) -> list[tuple[str | None, pd.DataFrame]]:
        if ext == "csv":
            if not content.strip():
                raise EmptyTable("el archivo no tiene datos")
            for enc in ("utf-8-sig", "latin-1"):
                try:
                    try:
                        df = pd.read_csv(io.BytesIO(content), sep=None, engine="python", encoding=enc)
                    except csv.Error:  # una sola columna: el detector de separador no decide
                        df = pd.read_csv(io.BytesIO(content), encoding=enc)
                    return [(None, df)]
                except UnicodeDecodeError:
                    continue
                except pd.errors.EmptyDataError:
                    raise EmptyTable("el archivo no tiene datos")
            raise UnsupportedFormat("codificación no reconocida")
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, engine="openpyxl", header=None)
        return [(name, SpaceStore._detect_header(df)) for name, df in sheets.items()]

    @staticmethod
    def _normalize_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
        """Devuelve el DataFrame con columnas normalizadas y el mapa nombre → rótulo original."""
        seen: dict[str, int] = {}
        cols = []
        labels: dict[str, str] = {}
        for i, c in enumerate(df.columns):
            name = _slug(str(c), f"col_{i + 1}")
            if name.startswith("unnamed_"):
                name = f"col_{i + 1}"
            if name in seen:
                seen[name] += 1
                name = f"{name}_{seen[name]}"
            else:
                seen[name] = 1
            cols.append(name)
            labels[name] = str(c)
        df = df.copy()
        df.columns = cols
        return df.dropna(how="all"), labels

    @staticmethod
    def _unique(name: str, existing: set[str]) -> str:
        if name not in existing:
            return name
        i = 2
        while f"{name}_{i}" in existing:
            i += 1
        return f"{name}_{i}"

    def _describe(self, con: duckdb.DuckDBPyConnection, tname: str,
                  labels: dict[str, str] | None = None) -> TableInfo:
        labels = labels or {}
        cols = [{"name": r[0], "type": r[1], "label": labels.get(r[0], r[0])}
                for r in con.execute(f'DESCRIBE "{tname}"').fetchall()]
        rows = con.execute(f'SELECT COUNT(*) FROM "{tname}"').fetchone()[0]
        cur = con.execute(f'SELECT * FROM "{tname}" LIMIT {self.sample_rows}')
        names = [d[0] for d in cur.description]
        sample = [{k: _json_safe(v) for k, v in zip(names, row)} for row in cur.fetchall()]
        return TableInfo(tname, cols, rows, sample)

    # ── esquema para el prompt ───────────────────────────────────────────────
    def schema_text(self, ws: str) -> str:
        """Tablas, columnas (con su rótulo original) y muestra, en texto para el modelo.

        Formato deliberadamente NO-SQL: con `CREATE TABLE (col TIPO)` un modelo chico copiaba
        el tipo dentro del WHERE (`idproducto BIGINT = 1411`, visto con datos reales de Elea).
        """
        parts = []
        for f in self.list_files(ws):
            for t in f["tables"]:
                sql_name = t.get("alias") or t["name"]
                legible = self.table_labels(ws).get(sql_name, f["name"])
                parts.append(f'Tabla {sql_name}  — nombre legible para mostrar: "{legible}" — {t["rows"]} filas')
                for c in t["columns"]:
                    label = c.get("label") or c["name"]
                    extra = f' — en la planilla se llama "{label}"' if label != c["name"] else ""
                    parts.append(f'  - {c["name"]}: {c["type"]}{extra}')
                if t["sample"]:
                    parts.append("  Filas de ejemplo (JSON):")
                    parts.extend("    " + json.dumps(r, ensure_ascii=False) for r in t["sample"])
                parts.append("")
        return "\n".join(parts).rstrip()

    def table_labels(self, ws: str) -> dict[str, str]:
        """alias/nombre técnico → nombre legible ("archivo, hoja") para las respuestas."""
        out: dict[str, str] = {}
        for f in self.list_files(ws):
            for t in f["tables"]:
                hoja = t.get("sheet") or t["name"]
                legible = f'{f["name"]}' if len(f["tables"]) == 1 else f'{f["name"]}, hoja "{hoja}"'
                out[t.get("alias") or t["name"]] = legible
                out[t["name"]] = legible
        return out

    def common_keys(self, ws: str) -> dict[str, list[str]]:
        """Columnas presentes en más de una tabla del espacio → candidatas a JOIN."""
        seen: dict[str, list[str]] = {}
        for f in self.list_files(ws):
            for t in f["tables"]:
                for c in t["columns"]:
                    seen.setdefault(c["name"], []).append(t.get("alias") or t["name"])
        return {col: tabs for col, tabs in seen.items() if len(tabs) > 1}

    # ── consulta ─────────────────────────────────────────────────────────────
    def query(self, ws: str, sql: str, *, timeout_s: int) -> tuple[list[str], list[dict]]:
        """Ejecuta un SQL YA VALIDADO en conexión de solo lectura, con timeout por interrupción."""
        self._require(ws)
        with self._lock(ws):
            con = self._ro(ws)
            timer = threading.Timer(timeout_s, con.interrupt)
            timer.start()
            try:
                cur = con.execute(sql)
                names = [d[0] for d in cur.description]
                rows = [{k: _json_safe(v) for k, v in zip(names, r)} for r in cur.fetchall()]
            except duckdb.InterruptException as e:
                raise QueryTimeout(str(e)) from e
            finally:
                timer.cancel()
                con.close()
        return names, rows
