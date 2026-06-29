import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
import httpx

from ..database import get_db

router = APIRouter(prefix="/analytics", tags=["Analytics"])
logger = logging.getLogger("basa-secure-gateway.analytics")

_ENGINE_URL = os.getenv("LITELLM_API_BASE", "http://litellm:4000")
_ENGINE_KEY = os.getenv("LITELLM_MASTER_KEY", "")


def _range_dates(range_param: str) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    if range_param == "day":
        from_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif range_param == "month":
        from_dt = now - timedelta(days=30)
    else:  # default: week
        from_dt = now - timedelta(days=7)
    return from_dt, now


@router.get("/summary")
def get_analytics_summary(
    range: str = Query("week", pattern="^(day|week|month)$"),
    db: Session = Depends(get_db),
):
    from_dt, to_dt = _range_dates(range)

    # Core aggregation query
    core_sql = text("""
        SELECT
            COUNT(*)                                              AS total_requests,
            COALESCE(SUM(cost_usd), 0)                          AS total_cost_usd,
            COALESCE(SUM(prompt_tokens), 0)                     AS total_prompt_tokens,
            COALESCE(SUM(completion_tokens), 0)                 AS total_completion_tokens,
            COALESCE(SUM(tokens_saved_by_optimization), 0)      AS tokens_saved,
            COALESCE(ROUND(AVG(latency_ms)), 0)                 AS avg_latency_ms,
            COUNT(*) FILTER (WHERE pii_detected = TRUE)         AS pii_incidents,
            COUNT(*) FILTER (WHERE compliance_status = 'allowed' OR compliance_status = 'passed') AS compliance_passed,
            COUNT(*) FILTER (WHERE compliance_status = 'blocked_prohibited' OR compliance_status = 'blocked_by_policy') AS compliance_blocked
        FROM audit_logs
        WHERE timestamp >= :from_dt AND timestamp <= :to_dt
    """)
    core_row = db.execute(core_sql, {"from_dt": from_dt, "to_dt": to_dt}).fetchone()

    # Per-model breakdown
    models_sql = text("""
        SELECT
            model,
            COUNT(*)           AS requests,
            COALESCE(SUM(cost_usd), 0) AS cost_usd
        FROM audit_logs
        WHERE timestamp >= :from_dt AND timestamp <= :to_dt
        GROUP BY model
        ORDER BY requests DESC
        LIMIT 10
    """)
    model_rows = db.execute(models_sql, {"from_dt": from_dt, "to_dt": to_dt}).fetchall()

    # Guardian events aggregation
    # Extracts each event object from the guardian_events JSONB array
    # Joins with guardians table to get white-label display name
    guardian_sql = text("""
        SELECT
            COALESCE(g.name, 'Guardián de seguridad') AS display_name,
            COUNT(*) AS activations
        FROM audit_logs al
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE
                WHEN al.guardian_events IS NULL OR al.guardian_events = 'null'::jsonb THEN '[]'::jsonb
                ELSE al.guardian_events
            END
        ) AS ev
        LEFT JOIN guardians g
            ON g.engine_guardrail_name = ev->>'guardrail_name'
        WHERE al.timestamp >= :from_dt AND al.timestamp <= :to_dt
          AND jsonb_typeof(
              CASE
                  WHEN al.guardian_events IS NULL OR al.guardian_events = 'null'::jsonb THEN '[]'::jsonb
                  ELSE al.guardian_events
              END
          ) = 'array'
          AND jsonb_array_length(
              CASE
                  WHEN al.guardian_events IS NULL OR al.guardian_events = 'null'::jsonb THEN '[]'::jsonb
                  ELSE al.guardian_events
              END
          ) > 0
        GROUP BY display_name
        ORDER BY activations DESC
    """)
    try:
        guardian_rows = db.execute(guardian_sql, {"from_dt": from_dt, "to_dt": to_dt}).fetchall()
        by_guardian = {row.display_name: row.activations for row in guardian_rows}
        total_activations = sum(by_guardian.values())
    except Exception as e:
        logger.warning("Guardian events aggregation failed: %s", e)
        by_guardian = {}
        total_activations = 0

    return {
        "range": range,
        "from_date": from_dt.isoformat(),
        "to_date": to_dt.isoformat(),
        "total_requests": core_row.total_requests or 0,
        "total_cost_usd": float(core_row.total_cost_usd or 0),
        "total_prompt_tokens": core_row.total_prompt_tokens or 0,
        "total_completion_tokens": core_row.total_completion_tokens or 0,
        "tokens_saved_by_optimization": core_row.tokens_saved or 0,
        "avg_latency_ms": int(core_row.avg_latency_ms or 0),
        "pii_incidents": core_row.pii_incidents or 0,
        "compliance_passed": core_row.compliance_passed or 0,
        "compliance_blocked": core_row.compliance_blocked or 0,
        "models": [
            {"model": r.model, "requests": r.requests, "cost_usd": float(r.cost_usd)}
            for r in model_rows
        ],
        "guardian_activations": {
            "total": total_activations,
            "by_guardian": by_guardian,
        },
    }


@router.get("/engine-status")
async def get_engine_status():
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(
                f"{_ENGINE_URL}/health/readiness",
                headers={"Authorization": f"Bearer {_ENGINE_KEY}"},
            )
            if r.status_code < 400:
                return {"status": "online", "checked_at": checked_at}
    except Exception:
        pass
    return {"status": "offline", "checked_at": checked_at}
