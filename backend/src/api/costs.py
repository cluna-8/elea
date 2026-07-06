"""Sección de Costos — Ahorro de Costes IA.

Endpoints:
* ``GET  /costs/summary``   — gasto agregado + tokens ahorrados + top modelos.
* ``POST /costs/calculator`` — calculadora de decisión: tokens actuales → tras
  compresión → ahorro USD + veredicto (conviene / no_conviene / usd_no_disponible).

La calculadora usa el compresor determinista (US1) para estimar el ahorro y el
rate de input del modelo (vía el motor IA) para traducirlo a USD. No persiste
nada: es una herramienta de decisión previa a la activación.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.optimization_service import OptimizationService

logger = logging.getLogger("basa-secure-gateway.costs")

router = APIRouter(prefix="/costs", tags=["Costs"])

_ENGINE_URL = os.getenv("LITELLM_API_BASE", "http://litellm:4000")
_ENGINE_KEY = os.getenv("LITELLM_MASTER_KEY", "")

# Ratio mínimo de ahorro para que el veredicto sea "conviene".
_MIN_SAVINGS_RATIO = 0.10


def _range_dates(range_param: str) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    if range_param == "day":
        from_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif range_param == "month":
        from_dt = now - timedelta(days=30)
    else:  # week
        from_dt = now - timedelta(days=7)
    return from_dt, now


def _get_input_cost_per_token(model_name: str | None) -> float | None:
    """Return the model's input cost per token from the AI engine, or None."""
    if not model_name:
        return None
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(
                f"{_ENGINE_URL}/model/info",
                headers={"Authorization": f"Bearer {_ENGINE_KEY}"},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.warning(f"Could not fetch model info for pricing ({e})")
        return None
    for m in data.get("data", []):
        if m.get("model_name") == model_name:
            info = m.get("model_info", {})
            ipt = info.get("input_cost_per_token", 0) or 0
            return float(ipt)
    return None


def _avg_input_cost_per_token() -> float | None:
    """Average input cost per token across configured models (for the summary estimate)."""
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(
                f"{_ENGINE_URL}/model/info",
                headers={"Authorization": f"Bearer {_ENGINE_KEY}"},
            )
            r.raise_for_status()
            data = r.json()
    except Exception:
        return None
    rates = []
    for m in data.get("data", []):
        info = m.get("model_info", {})
        ipt = info.get("input_cost_per_token", 0) or 0
        if float(ipt) > 0:
            rates.append(float(ipt))
    return (sum(rates) / len(rates)) if rates else None


# ---------------------------------------------------------------------- #
# Summary
# ---------------------------------------------------------------------- #
@router.get("/summary")
def get_costs_summary(
    range: str = Query("week", pattern="^(day|week|month)$"),
    db: Session = Depends(get_db),
):
    from_dt, to_dt = _range_dates(range)

    row = db.execute(
        text(
            """
            SELECT
                COALESCE(SUM(cost_usd), 0)                       AS total_cost_usd,
                COALESCE(SUM(prompt_tokens), 0)                  AS total_prompt_tokens,
                COALESCE(SUM(completion_tokens), 0)              AS total_completion_tokens,
                COALESCE(SUM(tokens_saved_by_optimization), 0)   AS tokens_saved,
                COUNT(*)                                         AS total_requests
            FROM audit_logs
            WHERE timestamp >= :from_dt AND timestamp <= :to_dt
            """
        ),
        {"from_dt": from_dt, "to_dt": to_dt},
    ).first()

    tokens_saved = int(row.tokens_saved or 0)
    avg_rate = _avg_input_cost_per_token()
    cost_saved_estimate = round(tokens_saved * avg_rate, 6) if avg_rate else None

    models = db.execute(
        text(
            """
            SELECT model,
                   COALESCE(SUM(cost_usd), 0)                     AS cost_usd,
                   COUNT(*)                                       AS requests,
                   COALESCE(SUM(tokens_saved_by_optimization), 0) AS tokens_saved
            FROM audit_logs
            WHERE timestamp >= :from_dt AND timestamp <= :to_dt
            GROUP BY model
            ORDER BY cost_usd DESC
            LIMIT 10
            """
        ),
        {"from_dt": from_dt, "to_dt": to_dt},
    ).all()

    # Desglose por usuario (top 10 por gasto)
    by_user = db.execute(
        text(
            """
            SELECT u.username                                AS name,
                   COALESCE(SUM(a.cost_usd), 0)              AS cost_usd,
                   COUNT(*)                                   AS requests,
                   COALESCE(SUM(a.tokens_saved_by_optimization), 0) AS tokens_saved
            FROM audit_logs a
            LEFT JOIN users u ON u.id = a.user_id
            WHERE a.timestamp >= :from_dt AND a.timestamp <= :to_dt
            GROUP BY u.username
            ORDER BY cost_usd DESC
            LIMIT 10
            """
        ),
        {"from_dt": from_dt, "to_dt": to_dt},
    ).all()

    # Desglose por grupo (top 10 por gasto) — usa el grupo registrado en la request
    by_group = db.execute(
        text(
            """
            SELECT COALESCE(g.name, '— sin grupo —')        AS name,
                   COALESCE(SUM(a.cost_usd), 0)              AS cost_usd,
                   COUNT(*)                                   AS requests,
                   COALESCE(SUM(a.tokens_saved_by_optimization), 0) AS tokens_saved
            FROM audit_logs a
            LEFT JOIN groups g ON g.id = a.user_group_id
            WHERE a.timestamp >= :from_dt AND a.timestamp <= :to_dt
            GROUP BY g.name
            ORDER BY cost_usd DESC
            LIMIT 10
            """
        ),
        {"from_dt": from_dt, "to_dt": to_dt},
    ).all()

    return {
        "range": range,
        "total_cost_usd": float(row.total_cost_usd or 0),
        "total_prompt_tokens": int(row.total_prompt_tokens or 0),
        "total_completion_tokens": int(row.total_completion_tokens or 0),
        "tokens_saved": tokens_saved,
        "total_requests": int(row.total_requests or 0),
        "cost_saved_estimate_usd": cost_saved_estimate,
        "top_models": [
            {
                "model": m.model,
                "cost_usd": float(m.cost_usd or 0),
                "requests": int(m.requests or 0),
                "tokens_saved": int(m.tokens_saved or 0),
            }
            for m in models
        ],
        "by_user": [
            {
                "name": b.name or "— sin usuario —",
                "cost_usd": float(b.cost_usd or 0),
                "requests": int(b.requests or 0),
                "tokens_saved": int(b.tokens_saved or 0),
            }
            for b in by_user
        ],
        "by_group": [
            {
                "name": b.name,
                "cost_usd": float(b.cost_usd or 0),
                "requests": int(b.requests or 0),
                "tokens_saved": int(b.tokens_saved or 0),
            }
            for b in by_group
        ],
    }


# ---------------------------------------------------------------------- #
# Calculator (decisión de activación)
# ---------------------------------------------------------------------- #
class CalculatorRequest(BaseModel):
    prompt: str = Field(..., description="Prompt de ejemplo a evaluar")
    model: str | None = Field(None, description="Modelo destino para calcular el ahorro en USD")
    threshold: int | None = Field(None, description="Umbral mínimo de tokens; default del servicio")
    aggressiveness: str = Field("medium", pattern="^(low|medium|high)$")
    strategy: str = Field("deterministic", pattern="^(deterministic|headroom)$",
                          description="deterministic (prosa, local) o headroom (módulo local SmartCrusher para contenido estructurado)")


@router.post("/calculator")
def calculate_compression(req: CalculatorRequest):
    threshold = (
        req.threshold if req.threshold is not None else OptimizationService.DEFAULT_THRESHOLD
    )
    analysis = OptimizationService.analyze(
        req.prompt,
        model=req.model,
        threshold=threshold,
        aggressiveness=req.aggressiveness,
        strategy=req.strategy,
    )

    rate = _get_input_cost_per_token(req.model)
    below_threshold = analysis["tokens_original"] < threshold
    good_ratio = analysis["ratio"] >= _MIN_SAVINGS_RATIO

    if rate is not None:
        analysis["cost_saved_usd"] = round(analysis["tokens_saved"] * rate, 6)
        analysis["veredicto"] = "no_conviene" if (below_threshold or not good_ratio) else "conviene"
    else:
        analysis["cost_saved_usd"] = None
        if below_threshold or not good_ratio:
            analysis["veredicto"] = "no_conviene"
        else:
            analysis["veredicto"] = "usd_no_disponible"

    analysis["threshold"] = threshold
    analysis["model"] = req.model
    analysis["aggressiveness"] = req.aggressiveness
    analysis["strategy"] = req.strategy
    return analysis