"""API del motor tabular (spec 050, contrato 03-motores.md §3.2).

Auth: `Authorization: Bearer <TABULAR_INTERNAL_TOKEN>` + `X-Hub-User-Id` (se reenvía a
Guardian como `X-Guardian-Acting-User`). El Hub verifica la membresía contra Guardian ANTES
de llamar acá; tabular confía en el Hub por red interna + token (FR-011/FR-020).
"""
from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import settings
from .llm import EngineClient, EngineError, answer_messages, sql_messages
from .sqlguard import UnparsableSQL, UnsafeSQL, validate, validate_fallback
from .store import (EmptyTable, QueryTimeout, SpaceExists, SpaceNotFound, SpaceStore,
                    UnsupportedFormat)

log = logging.getLogger("tabular")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Eleia tabular", version="0.1.0", docs_url=None, redoc_url=None)
store = SpaceStore(settings.data_dir, memory_limit=settings.memory_limit,
                   threads=settings.threads, sample_rows=settings.sample_rows)
engine = EngineClient(settings.engine_url, settings.engine_key, settings.model,
                      timeout_s=settings.engine_timeout_s)


# ── auth ─────────────────────────────────────────────────────────────────────
def require_hub(authorization: str | None = Header(default=None),
                x_hub_user_id: str | None = Header(default=None)) -> str:
    if not settings.internal_token:
        # Fail-closed: sin token configurado nadie entra (FR-020).
        raise HTTPException(503, {"code": "not_configured", "detail": "TABULAR_INTERNAL_TOKEN no configurado"})
    if authorization != f"Bearer {settings.internal_token}":
        raise HTTPException(401, {"code": "unauthorized"})
    if not x_hub_user_id or len(x_hub_user_id) > 64:
        raise HTTPException(400, {"code": "missing_user", "detail": "falta X-Hub-User-Id"})
    return x_hub_user_id


def _space(ws: str) -> str:
    if not store.exists(ws):
        raise HTTPException(404, {"code": "space_not_found"})
    return ws


# ── modelos ──────────────────────────────────────────────────────────────────
class SpaceIn(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=64)


class HistoryItem(BaseModel):
    question: str = ""
    answer: str = ""


class QueryIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    history: list[HistoryItem] = Field(default_factory=list, max_length=5)


# ── rutas ────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "configured": bool(settings.internal_token and settings.engine_key)}


@app.post("/v1/spaces", status_code=201)
def create_space(body: SpaceIn, _user: str = Depends(require_hub)):
    if not SpaceStore.valid_id(body.workspace_id):
        raise HTTPException(422, {"code": "invalid_workspace_id"})
    try:
        store.create_space(body.workspace_id)
    except SpaceExists:
        raise HTTPException(409, {"code": "space_exists"})
    return {"workspace_id": body.workspace_id}


@app.get("/v1/spaces/{ws}/files")
def list_files(ws: str, _user: str = Depends(require_hub)):
    _space(ws)
    return {"files": store.list_files(ws)}


@app.post("/v1/spaces/{ws}/files", status_code=201)
async def upload_file(ws: str, file: UploadFile = File(...), _user: str = Depends(require_hub)):
    _space(ws)
    name = file.filename or "archivo"
    ext = (name.rsplit(".", 1)[-1] if "." in name else "").lower()
    if ext not in ("csv", "xlsx"):
        raise HTTPException(415, {"code": "unsupported_format", "detail": "solo .csv y .xlsx"})
    content = await file.read()
    if len(content) > settings.max_file_mb * 1024 * 1024:
        raise HTTPException(413, {"code": "file_too_large", "max_mb": settings.max_file_mb})
    try:
        entry = store.load_file(ws, name, content)
    except UnsupportedFormat as e:
        raise HTTPException(415, {"code": "unsupported_format", "detail": str(e)})
    except EmptyTable as e:
        raise HTTPException(422, {"code": "empty_file", "detail": str(e)})
    except Exception as e:  # archivo corrupto, hoja rara, etc.
        log.warning("carga falló en %s: %s", ws, e)
        raise HTTPException(422, {"code": "unreadable_file", "detail": "no se pudo leer el archivo"})
    return entry


@app.delete("/v1/spaces/{ws}/files/{file_id}")
def delete_file(ws: str, file_id: str, _user: str = Depends(require_hub)):
    _space(ws)
    if not store.delete_file(ws, file_id):
        raise HTTPException(404, {"code": "file_not_found"})
    return {"status": "ok"}


@app.post("/v1/spaces/{ws}/query")
def query(ws: str, body: QueryIn, user_id: str = Depends(require_hub)):
    _space(ws)
    store.ensure_aliases(ws)
    tables = store.table_names(ws)
    if not tables:
        raise HTTPException(422, {"code": "no_files", "detail": "el espacio no tiene archivos"})
    schema = store.schema_text(ws)
    common = store.common_keys(ws)
    history = [h.model_dump() for h in body.history]

    # 1) SQL desde Guardian, con UN reintento si no valida o falla al ejecutar (FR-023).
    feedback = None
    sql = ""
    columns: list[str] = []
    rows: list[dict] = []
    model_used = settings.model
    for attempt in (1, 2):
        try:
            raw, model_used = engine.chat(sql_messages(schema, body.question, history, feedback, common),
                                          acting_user_id=user_id, max_tokens=1500)
        except EngineError as e:
            raise _engine_http(e)
        if raw.strip().upper().startswith("NO_SQL"):
            raise HTTPException(422, {"code": "not_answerable",
                                      "detail": "la pregunta no se puede responder con estos archivos"})
        try:
            sql = validate(raw, max_rows=settings.max_rows, allowed_tables=tables)
        except UnparsableSQL as e:
            # Consulta que sqlglot no interpreta pero puede ser válida en DuckDB: pasa por la
            # validación conservadora y la ejecuta la conexión de solo lectura (capa 2).
            try:
                sql = validate_fallback(raw, max_rows=settings.max_rows)
                log.info("SQL sin AST, validación conservadora en %s: %s", ws, sql[:200])
            except UnsafeSQL as e2:
                log.warning("SQL rechazado (intento %d) en %s: %s | SQL completo:\n%s", attempt, ws, e2, raw[:4000])
                if attempt == 2:
                    raise HTTPException(422, {"code": "unsafe_sql", "detail": str(e2)})
                feedback = f"consulta rechazada ({e2}). Escribí una consulta más simple, en una sola sentencia."
                continue
        except UnsafeSQL as e:
            log.warning("SQL rechazado (intento %d) en %s: %s | SQL completo:\n%s", attempt, ws, e, raw[:4000])
            if attempt == 2:
                raise HTTPException(422, {"code": "unsafe_sql", "detail": str(e)})
            feedback = f"consulta rechazada por la política de solo lectura: {e}"
            continue
        try:
            columns, rows = store.query(ws, sql, timeout_s=settings.query_timeout_s)
            break
        except QueryTimeout:
            raise HTTPException(504, {"code": "timeout"})
        except Exception as e:  # error de SQL (columna inexistente, tipo, etc.)
            msg = str(e).splitlines()[0][:300]
            log.info("SQL falló (intento %d) en %s: %s | SQL: %s", attempt, ws, msg, sql[:400])
            if attempt == 2:
                raise HTTPException(422, {"code": "sql_error", "detail": msg})
            feedback = msg

    # 2) Redacción con a lo sumo `answer_rows` filas (FR-024).
    try:
        answer, model_used = engine.chat(
            answer_messages(body.question, sql, columns, rows[:settings.answer_rows], len(rows),
                            store.table_labels(ws)),
            acting_user_id=user_id, max_tokens=500, temperature=0.0)
    except EngineError as e:
        raise _engine_http(e)

    return {"sql": sql, "columns": columns, "rows": rows, "answer": answer, "model_used": model_used}


def _engine_http(e: EngineError) -> HTTPException:
    log.warning("engine %s: %s", e.status, e.detail)
    return HTTPException(502, {"code": "engine_error", "status": e.status})


@app.exception_handler(SpaceNotFound)
def _nf(_req, _exc):
    return JSONResponse(404, {"detail": {"code": "space_not_found"}})
