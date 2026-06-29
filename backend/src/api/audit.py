import csv
import io
import logging
from datetime import datetime
from typing import List, Optional, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.audit import AuditLog

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])
logger = logging.getLogger("basa-secure-gateway.audit")


class AuditLogResponseSchema(BaseModel):
    id: UUID
    timestamp: datetime
    user_id: Optional[UUID]
    api_key_id: Optional[UUID]
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    pii_detected: bool
    masked_entities: Optional[List[Any]]
    compliance_status: str
    latency_ms: int
    tokens_saved_by_optimization: int
    guardian_events: Optional[List[Any]]

    class Config:
        from_attributes = True


class AuditLogListResponseSchema(BaseModel):
    total: int
    logs: List[AuditLogResponseSchema]


def _build_query(db, pii_detected, compliance_status, from_date, to_date):
    query = db.query(AuditLog)
    if pii_detected is not None:
        query = query.filter(AuditLog.pii_detected == pii_detected)
    if compliance_status is not None:
        query = query.filter(AuditLog.compliance_status == compliance_status)
    if from_date:
        try:
            query = query.filter(AuditLog.timestamp >= datetime.fromisoformat(from_date))
        except ValueError:
            pass
    if to_date:
        try:
            query = query.filter(AuditLog.timestamp <= datetime.fromisoformat(to_date))
        except ValueError:
            pass
    return query


@router.get("", response_model=AuditLogListResponseSchema)
def list_audit_logs(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    pii_detected: Optional[bool] = Query(None),
    compliance_status: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = _build_query(db, pii_detected, compliance_status, from_date, to_date)
    total = query.count()
    logs = query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit).all()
    return {"total": total, "logs": logs}


@router.get("/export")
def export_audit_logs_csv(
    pii_detected: Optional[bool] = Query(None),
    compliance_status: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Streams audit logs as CSV. No prompt text or PII is included."""
    query = _build_query(db, pii_detected, compliance_status, from_date, to_date)
    # Limit export to 5000 rows to avoid memory exhaustion
    logs = query.order_by(AuditLog.timestamp.desc()).limit(5000).all()

    def generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "id", "timestamp", "model",
            "prompt_tokens", "completion_tokens", "cost_usd",
            "pii_detected", "compliance_status", "latency_ms",
            "tokens_saved_by_optimization", "guardian_events_count",
        ])
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate()

        for log in logs:
            writer.writerow([
                str(log.id),
                log.timestamp.isoformat() if log.timestamp else "",
                log.model,
                log.prompt_tokens,
                log.completion_tokens,
                float(log.cost_usd),
                log.pii_detected,
                log.compliance_status,
                log.latency_ms,
                log.tokens_saved_by_optimization,
                len(log.guardian_events or []),
            ])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()

    filename = f"audit_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
