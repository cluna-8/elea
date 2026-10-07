"""Siembra de regiones y reglas de habilitación al arrancar (057 QA B2, QA v2 N1, M3; research R28, R33) [BASE].

La costura S16 de la base llama a `on_startup()` del paquete `sentinel.redirect.api` desde el `lifespan`, antes de
servir el primer pedido. Con `REDIRECT_SEED_FILES` (rutas separadas por coma o salto de línea) carga cada archivo
con el cargador que le corresponde, por su contenido:

- `regions:` → `regions_seed` (regiones del perfil con su postura por defecto);
- `providers` / `api_hosts` / `jurisdictions` → `sentinel.catalog.habilitacion` (reglas de habilitación explícita).

Reglas:
- Sin `REDIRECT_SEED_FILES` no hace nada.
- **Idempotente y seguro ante dos workers** (`WEB_CONCURRENCY` > 1: el enganche corre una vez por proceso, a la vez):
  la siembra toma un cerrojo consultivo de Postgres (`pg_advisory_xact_lock`, se suelta al confirmar) y las altas
  de los cargadores no duplican; dentro del proceso, un cerrojo de hilo.
- **Un archivo inválido o ilegible se registra y no frena a los demás**; sin la fila de región rige el respaldo en
  código (`GET /api/v1/redirect/health` da 503 `region_row_missing`). El registro lleva el nombre del archivo y el
  motivo de validación, nunca su contenido.
- Las tablas ya existen: las migraciones de la base y de la extensión corrieron al importar `main.py`.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, List, Optional

logger = logging.getLogger("sentinel.redirect.seed")

ENV = "REDIRECT_SEED_FILES"
ADVISORY_KEY = 0x5345454452474E  # «SEEDRGN»: un entero fijo de la extensión para el cerrojo consultivo
HABILITACION_KEYS = {"providers", "api_hosts", "jurisdictions"}

# Inyectable para tests: `() -> Session`. Sin él, `src.database.SessionLocal` con bypass de RLS (es dato de instalación).
SESSION_FACTORY = None
_LOCAL = threading.Lock()


def seed_files(environ: Optional[dict] = None) -> List[str]:
    raw = (os.environ if environ is None else environ).get(ENV, "") or ""
    return [p.strip() for chunk in raw.splitlines() for p in chunk.split(",") if p.strip()]


def _take_lock(db) -> None:
    """Cerrojo consultivo de Postgres por transacción (se suelta al confirmar). Otros motores: nada."""
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy import text
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": ADVISORY_KEY})


def _seed_one(db, path: str) -> str:
    """Carga un archivo. Devuelve qué hizo; levanta con el motivo si es inválido."""
    from . import regions_seed
    data = regions_seed.load_seed_file(path)
    if isinstance(data, dict) and "regions" in data:
        if set(data) - {"regions"}:
            raise ValueError("un seed de regiones solo lleva la clave `regions`")
        r = regions_seed.seed_regions(db, data, reason=f"seed al arrancar: {os.path.basename(path)}")
        return f"regiones: {r['created']} sembradas, {r['skipped']} ya existían"
    if isinstance(data, dict) and data and set(data) <= HABILITACION_KEYS:
        from sentinel.catalog import habilitacion
        r = habilitacion.seed_rules(db, data, reason=f"seed al arrancar: {os.path.basename(path)}")
        changed = habilitacion.reevaluate(db)
        return f"habilitación: {r['created']} reglas sembradas, {r['skipped']} ya existían, {len(changed)} re-evaluadas"
    if data in ({}, None):
        return "vacío"
    raise ValueError("no es un seed de regiones (`regions`) ni de habilitación (`providers`, `api_hosts`, `jurisdictions`)")


def _open():
    if SESSION_FACTORY is not None:
        return SESSION_FACTORY(), None
    from src.database import SessionLocal, tenant_context
    ctx = tenant_context(None, bypass=True)
    ctx.__enter__()
    return SessionLocal(), ctx


def run(files: List[str]) -> dict:
    results: dict = {}
    with _LOCAL:
        db, ctx = _open()
        try:
            _take_lock(db)
            for path in files:
                name = os.path.basename(path) or path
                try:
                    results[path] = _seed_one(db, path)
                    logger.info("seed %s: %s", name, results[path])
                except Exception as exc:  # noqa: BLE001 — un archivo malo no frena a los demás; rige el respaldo
                    db.rollback()
                    _take_lock(db)
                    results[path] = "error"
                    logger.error("seed %s no se cargó (%s): %s", name, type(exc).__name__, _reason(exc))
            db.commit()
        finally:
            db.close()
            if ctx is not None:
                ctx.__exit__(None, None, None)
    return results


def _reason(exc: Exception) -> str:
    """Motivo de validación del cargador (`ValueError`, sin contenido del archivo más allá del campo) o el tipo."""
    return str(exc)[:300] if isinstance(exc, (ValueError, OSError)) else "error al leer o escribir"


def on_startup() -> Optional[dict]:
    """Enganche de la costura S16 (`sentinel.redirect.api.on_startup`)."""
    files = seed_files()
    if not files:
        return None
    return run(files)
