"""`GET /api/v1/catalog/usage` — consumo de la organización por modelo o destino (069 T131; FR-054,
FR-055; research D29).

Agrega `audit_logs` (la fuente de verdad) de la organización de la SESIÓN y del rango pedido, solo
`event_type='traffic'`. Devuelve únicamente contadores: ningún contenido de pedidos ni de respuestas.

- **Destino real**: sale de `routing_decision.extensions.redirect.destination_id` (D29, mientras no
  existan columnas propias); sin esa atribución cae al `model` de la fila.
- **Suscripción (tarifa plana)**: el passthrough del gateway registra `cost_usd=0` y
  `processing_purpose='coding-assistant'` (`gateway.py`, «suscripción = tarifa plana»); esas filas
  se separan en grupos `billing='flat'` y no suman al costo medido.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.auth.rbac import require_role

from . import admin as _admin

router = APIRouter(prefix="/catalog", tags=["catalog"])

READERS = _admin.READERS
GROUPS = ("model", "destination")
DEFAULT_DAYS = 30
FLAT_PURPOSE = "coding-assistant"

# Inyectables para tests: lector de filas (la tabla es de la base, con tipos de Postgres) y reloj.
FETCH = None
NOW = None


def _now() -> datetime:
    return NOW() if NOW is not None else datetime.now(timezone.utc)


def p95(values: list) -> int:
    """Percentil 95 por rango más cercano (nearest-rank); 0 si no hay valores."""
    if not values:
        return 0
    vs = sorted(values)
    return int(vs[max(math.ceil(0.95 * len(vs)) - 1, 0)])


def _redirect(row: dict) -> dict:
    ext = (row.get("routing_decision") or {}).get("extensions") if isinstance(
        row.get("routing_decision"), dict) else None
    red = ext.get("redirect") if isinstance(ext, dict) else None
    return red if isinstance(red, dict) else {}


def _is_flat(row: dict) -> bool:
    return row.get("processing_purpose") == FLAT_PURPOSE and not float(row.get("cost_usd") or 0)


def _key(row: dict, group: str):
    if group == "destination":
        red = _redirect(row)
        if red.get("destination_id"):
            return str(red["destination_id"]), red.get("destination_name") or str(red["destination_id"])
    return row["model"], row["model"]


def _bucket(rows: list, key: str, name: str, billing: str) -> dict:
    lats = [int(r.get("latency_ms") or 0) for r in rows]
    return {"key": key, "name": name, "requests": len(rows),
            "prompt_tokens": sum(int(r.get("prompt_tokens") or 0) for r in rows),
            "completion_tokens": sum(int(r.get("completion_tokens") or 0) for r in rows),
            "cost_usd": 0.0 if billing == "flat" else round(sum(float(r.get("cost_usd") or 0) for r in rows), 6),
            "latency_avg_ms": round(sum(lats) / len(lats)) if lats else 0,
            "latency_p95_ms": p95(lats), "billing": billing}


def aggregate(rows: list, group: str) -> dict:
    """Filas mínimas (`model`, tokens, `cost_usd`, `latency_ms`, `routing_decision`,
    `processing_purpose`) → `{data, totals}`. Pura; nunca lee ni devuelve otros campos."""
    groups: dict = {}
    for r in rows:
        k, name = _key(r, group)
        groups.setdefault((k, "flat" if _is_flat(r) else "measured"), (name, []))[1].append(r)
    data = [_bucket(rs, k, name, billing) for (k, billing), (name, rs) in groups.items()]
    data.sort(key=lambda g: (-g["requests"], g["key"], g["billing"]))
    flat = [g for g in data if g["billing"] == "flat"]
    totals = {"requests": sum(g["requests"] for g in data),
              "prompt_tokens": sum(g["prompt_tokens"] for g in data),
              "completion_tokens": sum(g["completion_tokens"] for g in data),
              "cost_usd": round(sum(g["cost_usd"] for g in data), 6),
              "flat_requests": sum(g["requests"] for g in flat)}
    return {"data": data, "totals": totals}


def _default_query(tenant_id, start: datetime, end: datetime):
    from sqlalchemy import select
    from src.models.audit import AuditLog as A
    return select(A.model, A.prompt_tokens, A.completion_tokens, A.cost_usd, A.latency_ms,
                  A.routing_decision, A.processing_purpose).where(
        A.tenant_id == tenant_id, A.event_type == "traffic",
        A.timestamp >= start, A.timestamp <= end)


def _default_fetch(db, tenant_id, start, end) -> list:
    return [dict(r._mapping) for r in db.execute(_default_query(tenant_id, start, end))]


def _parse(value: Optional[str], default: datetime, what: str, *, end_of_day=False) -> datetime:
    if not value:
        return default
    try:
        d = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, f"«{what}» debe ser una fecha ISO") from None
    if len(value) <= 10 and end_of_day:
        d += timedelta(days=1) - timedelta(microseconds=1)
    return d.replace(tzinfo=None) if d.tzinfo is None else d.astimezone(timezone.utc).replace(tzinfo=None)


@router.get("/usage")
def get_usage(group: str = "model", from_: Optional[str] = Query(default=None, alias="from"),
              to: Optional[str] = None, user=Depends(require_role(*READERS))):
    if group not in GROUPS:
        raise HTTPException(422, "group debe ser model o destination")
    end = _parse(to, _now().astimezone(timezone.utc).replace(tzinfo=None), "to", end_of_day=True)
    start = _parse(from_, end - timedelta(days=DEFAULT_DAYS), "from")
    if start > end:
        raise HTTPException(422, "«from» no puede ser posterior a «to»")
    with _admin._db(user) as db:                 # tenant_context (RLS) de la sesión
        rows = (FETCH or _default_fetch)(db, user.tenant_id, start, end)
    out = aggregate(rows, group)
    return {"from": start.isoformat(), "to": end.isoformat(), "group": group, **out}
