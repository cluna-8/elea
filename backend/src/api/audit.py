from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from ..database import get_db
from ..models.audit import AuditLog
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])

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
    masked_entities: Optional[List[dict]]
    compliance_status: str
    latency_ms: int
    tokens_saved_by_optimization: int

    class Config:
        from_attributes = True

class AuditLogListResponseSchema(BaseModel):
    total: int
    logs: List[AuditLogResponseSchema]

@router.get("", response_model=AuditLogListResponseSchema)
def list_audit_logs(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    pii_detected: Optional[bool] = Query(None),
    compliance_status: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(AuditLog)
    
    if pii_detected is not None:
        query = query.filter(AuditLog.pii_detected == pii_detected)
        
    if compliance_status is not None:
        query = query.filter(AuditLog.compliance_status == compliance_status)
        
    total = query.count()
    logs = query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit).all()
    
    return {
        "total": total,
        "logs": logs
    }
