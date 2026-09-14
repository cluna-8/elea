"""Historial de conversaciones por espacio (spec 051).

Un archivo `history.sqlite` por espacio, AL LADO del `db.duckdb`: DuckDB no admite una conexión
de escritura mientras las consultas usan una de solo lectura (medido en RESULTADOS.md §1), y
SQLite viene con Python. Hilos y turnos pertenecen a UNA persona (`user_id` = `X-Hub-User-Id`);
Guardian registra el hilo y su dueño por fuera (el Hub verifica ahí antes de llamar acá).

Resumen de conversaciones largas: cada `summary_every` turnos se pide a Guardian un resumen de
los turnos anteriores y se guarda; al preguntar, el modelo ve ese resumen más los últimos
`window` turnos. Así una charla de 40 preguntas no cuesta 40 turnos de tokens y "resumime lo que
hablamos" funciona sobre toda la conversación.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path

_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


class ThreadNotFound(KeyError):
    pass


class ThreadForbidden(PermissionError):
    pass


class History:
    def __init__(self, space_dir_of, *, window: int = 5, summary_every: int = 10, max_rows: int = 50):
        self._dir = space_dir_of            # callable ws -> Path
        self.window = window
        self.summary_every = summary_every
        self.max_rows = max_rows
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    @staticmethod
    def valid_key(key: str) -> bool:
        return bool(_KEY_RE.match(key or ""))

    def _lock(self, ws: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(ws, threading.Lock())

    def _con(self, ws: str) -> sqlite3.Connection:
        p = Path(self._dir(ws)) / "history.sqlite"
        con = sqlite3.connect(str(p), timeout=5)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(
            "CREATE TABLE IF NOT EXISTS threads(key TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT,"
            " created_at REAL NOT NULL, updated_at REAL NOT NULL);"
            "CREATE TABLE IF NOT EXISTS turns(id INTEGER PRIMARY KEY AUTOINCREMENT, thread_key TEXT NOT NULL,"
            " user_id TEXT NOT NULL, ts REAL NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL, sql TEXT,"
            " columns_json TEXT, rows_json TEXT, total_rows INTEGER, model_used TEXT, stale INTEGER DEFAULT 0);"
            "CREATE INDEX IF NOT EXISTS turns_thread ON turns(thread_key, id);"
            "CREATE TABLE IF NOT EXISTS summaries(thread_key TEXT PRIMARY KEY, summary TEXT NOT NULL,"
            " upto_turn_id INTEGER NOT NULL, updated_at REAL NOT NULL);")
        return con

    # ── hilos ────────────────────────────────────────────────────────────────
    def list_threads(self, ws: str, user_id: str) -> list[dict]:
        with self._con(ws) as con:
            rows = con.execute(
                "SELECT t.key, t.title, t.created_at, t.updated_at,"
                " (SELECT count(*) FROM turns u WHERE u.thread_key = t.key) AS turns"
                " FROM threads t WHERE t.user_id = ? ORDER BY t.updated_at DESC", (user_id,)).fetchall()
        return [dict(r) for r in rows]

    def create_thread(self, ws: str, user_id: str, key: str, title: str | None = None) -> dict:
        if not self.valid_key(key):
            raise ValueError("thread key inválida")
        now = time.time()
        with self._lock(ws), self._con(ws) as con:
            existing = con.execute("SELECT user_id FROM threads WHERE key = ?", (key,)).fetchone()
            if existing:
                if existing["user_id"] != user_id:
                    raise ThreadForbidden(key)
                return self._thread(con, key)
            con.execute("INSERT INTO threads(key, user_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
                        (key, user_id, (title or "").strip()[:120] or None, now, now))
            return self._thread(con, key)

    def _thread(self, con: sqlite3.Connection, key: str) -> dict:
        r = con.execute("SELECT key, title, created_at, updated_at,"
                        " (SELECT count(*) FROM turns u WHERE u.thread_key = threads.key) AS turns"
                        " FROM threads WHERE key = ?", (key,)).fetchone()
        return dict(r)

    def _owned(self, con: sqlite3.Connection, key: str, user_id: str) -> None:
        r = con.execute("SELECT user_id FROM threads WHERE key = ?", (key,)).fetchone()
        if not r:
            raise ThreadNotFound(key)
        if r["user_id"] != user_id:
            raise ThreadForbidden(key)

    def rename_thread(self, ws: str, user_id: str, key: str, title: str) -> dict:
        with self._lock(ws), self._con(ws) as con:
            self._owned(con, key, user_id)
            con.execute("UPDATE threads SET title = ?, updated_at = ? WHERE key = ?",
                        ((title or "").strip()[:120] or None, time.time(), key))
            return self._thread(con, key)

    def delete_thread(self, ws: str, user_id: str, key: str) -> None:
        with self._lock(ws), self._con(ws) as con:
            self._owned(con, key, user_id)
            con.execute("DELETE FROM turns WHERE thread_key = ?", (key,))
            con.execute("DELETE FROM summaries WHERE thread_key = ?", (key,))
            con.execute("DELETE FROM threads WHERE key = ?", (key,))

    # ── turnos ───────────────────────────────────────────────────────────────
    def turns(self, ws: str, user_id: str, key: str, *, limit: int = 50, before: int | None = None,
              with_rows: bool = True) -> list[dict]:
        with self._con(ws) as con:
            self._owned(con, key, user_id)
            q = "SELECT * FROM turns WHERE thread_key = ?" + (" AND id < ?" if before else "") + \
                " ORDER BY id DESC LIMIT ?"
            args = (key, before, limit) if before else (key, limit)
            rows = [self._turn(dict(r), with_rows) for r in con.execute(q, args).fetchall()]
        rows.reverse()
        return rows

    def turn(self, ws: str, user_id: str, key: str, turn_id: int) -> dict | None:
        with self._con(ws) as con:
            self._owned(con, key, user_id)
            r = con.execute("SELECT * FROM turns WHERE thread_key = ? AND id = ?", (key, turn_id)).fetchone()
        return self._turn(dict(r), True) if r else None

    @staticmethod
    def _turn(r: dict, with_rows: bool) -> dict:
        out = {"id": r["id"], "ts": r["ts"], "question": r["question"], "answer": r["answer"],
               "sql": r["sql"], "columns": json.loads(r["columns_json"] or "[]"),
               "total_rows": r["total_rows"], "model_used": r["model_used"], "stale": bool(r["stale"])}
        if with_rows:
            out["rows"] = json.loads(r["rows_json"] or "[]")
        return out

    def add_turn(self, ws: str, user_id: str, key: str, *, question: str, answer: str, sql: str | None,
                 columns: list[str], rows: list[dict], model_used: str | None) -> int:
        with self._lock(ws), self._con(ws) as con:
            self._owned(con, key, user_id)
            cur = con.execute(
                "INSERT INTO turns(thread_key, user_id, ts, question, answer, sql, columns_json, rows_json,"
                " total_rows, model_used) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (key, user_id, time.time(), question, answer, sql, json.dumps(columns, ensure_ascii=False),
                 json.dumps(rows[:self.max_rows], ensure_ascii=False, default=str), len(rows), model_used))
            con.execute("UPDATE threads SET updated_at = ? WHERE key = ?", (time.time(), key))
            return int(cur.lastrowid)

    # ── contexto para el modelo ──────────────────────────────────────────────
    def context(self, ws: str, user_id: str, key: str) -> tuple[str | None, list[dict]]:
        """(resumen de lo viejo o None, últimos `window` turnos como {question, answer})."""
        with self._con(ws) as con:
            self._owned(con, key, user_id)
            s = con.execute("SELECT summary FROM summaries WHERE thread_key = ?", (key,)).fetchone()
            rows = con.execute("SELECT question, answer FROM turns WHERE thread_key = ? ORDER BY id DESC LIMIT ?",
                               (key, self.window)).fetchall()
        hist = [{"question": r["question"], "answer": r["answer"]} for r in reversed(rows)]
        return (s["summary"] if s else None), hist

    def needs_summary(self, ws: str, user_id: str, key: str) -> list[dict] | None:
        """Turnos viejos que todavía no están resumidos, si ya hay `summary_every` de ellos."""
        with self._con(ws) as con:
            self._owned(con, key, user_id)
            s = con.execute("SELECT upto_turn_id, summary FROM summaries WHERE thread_key = ?", (key,)).fetchone()
            upto = s["upto_turn_id"] if s else 0
            old = con.execute(
                "SELECT id, question, answer FROM turns WHERE thread_key = ? AND id > ?"
                " ORDER BY id LIMIT ?", (key, upto, self.summary_every + self.window)).fetchall()
        # Dejar siempre los últimos `window` fuera del resumen.
        candidates = [dict(r) for r in old][:-self.window] if len(old) > self.window else []
        if len(candidates) < self.summary_every:
            return None
        return [{"id": c["id"], "question": c["question"], "answer": c["answer"],
                 "previous_summary": (s["summary"] if s else None)} for c in candidates]

    def set_summary(self, ws: str, user_id: str, key: str, summary: str, upto_turn_id: int) -> None:
        with self._lock(ws), self._con(ws) as con:
            self._owned(con, key, user_id)
            con.execute("INSERT INTO summaries(thread_key, summary, upto_turn_id, updated_at) VALUES (?,?,?,?)"
                        " ON CONFLICT(thread_key) DO UPDATE SET summary = excluded.summary,"
                        " upto_turn_id = excluded.upto_turn_id, updated_at = excluded.updated_at",
                        (key, summary[:4000], upto_turn_id, time.time()))

    # ── mantenimiento ────────────────────────────────────────────────────────
    def mark_stale(self, ws: str, table_names: list[str]) -> int:
        """Marca los turnos cuya consulta usó una tabla que se borró (spec 051 §10)."""
        if not table_names or not (Path(self._dir(ws)) / "history.sqlite").exists():
            return 0
        n = 0
        with self._lock(ws), self._con(ws) as con:
            for t in table_names:
                pat = re.compile(r'(?<![A-Za-z0-9_])' + re.escape(t) + r'(?![A-Za-z0-9_])', re.I)
                ids = [r["id"] for r in con.execute("SELECT id, sql FROM turns WHERE stale = 0 AND sql IS NOT NULL")
                       if pat.search(r["sql"] or "")]
                if ids:
                    con.executemany("UPDATE turns SET stale = 1 WHERE id = ?", [(i,) for i in ids])
                    n += len(ids)
        return n
