import logging
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.consent import ConsentRecord
from ..models.user import User
from ..auth.rbac import require_role

router = APIRouter(
    prefix="/compliance/consent",
    tags=["Consent"],
    dependencies=[Depends(require_role("admin", "compliance_officer"))],
)
logger = logging.getLogger("basa-secure-gateway.consent")

CONSENT_VERSION = "1.0"


# ── Schemas ───────────────────────────────────────────────────────────────────

class ConsentCreate(BaseModel):
    user_id: UUID
    consent_type: str   # ai_use | data_processing | special_category
    version: str = CONSENT_VERSION
    notes: Optional[str] = None

class ConsentResponse(BaseModel):
    id: UUID
    user_id: UUID
    consent_type: str
    version: str
    granted_at: str
    revoked_at: Optional[str] = None
    ip_address: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True


# ── Helpers ───────────────────────────────────────────────────────────────────

def _consent_resp(c: ConsentRecord) -> dict:
    return {
        "id": c.id,
        "user_id": c.user_id,
        "consent_type": c.consent_type,
        "version": c.version,
        "granted_at": c.granted_at.isoformat() if c.granted_at else None,
        "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None,
        "ip_address": c.ip_address,
        "notes": c.notes,
        "is_active": c.revoked_at is None,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/{user_id}", response_model=List[ConsentResponse])
def get_user_consents(user_id: UUID, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    records = db.query(ConsentRecord).filter(ConsentRecord.user_id == user_id).order_by(ConsentRecord.granted_at.desc()).all()
    return [_consent_resp(r) for r in records]


@router.get("/{user_id}/active")
def get_active_consents(user_id: UUID, db: Session = Depends(get_db)):
    records = (
        db.query(ConsentRecord)
        .filter(ConsentRecord.user_id == user_id, ConsentRecord.revoked_at == None)
        .all()
    )
    return {
        "user_id": str(user_id),
        "active_consents": [r.consent_type for r in records],
        "has_ai_use": any(r.consent_type == "ai_use" for r in records),
        "has_data_processing": any(r.consent_type == "data_processing" for r in records),
        "has_special_category": any(r.consent_type == "special_category" for r in records),
    }


@router.post("", response_model=ConsentResponse, status_code=status.HTTP_201_CREATED)
def record_consent(body: ConsentCreate, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == body.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    valid_types = {"ai_use", "data_processing", "special_category"}
    if body.consent_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Tipo de consentimiento inválido. Válidos: {valid_types}")

    # Revoke any previous active consent of the same type before creating new one
    existing = (
        db.query(ConsentRecord)
        .filter(ConsentRecord.user_id == body.user_id, ConsentRecord.consent_type == body.consent_type, ConsentRecord.revoked_at == None)
        .first()
    )
    if existing:
        existing.revoked_at = datetime.utcnow()

    record = ConsentRecord(
        user_id=body.user_id,
        consent_type=body.consent_type,
        version=body.version,
        ip_address=request.client.host if request.client else None,
        notes=body.notes,
        granted_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info(f"Consentimiento '{body.consent_type}' registrado para usuario {body.user_id}")
    return _consent_resp(record)


@router.delete("/{consent_id}")
def revoke_consent(consent_id: UUID, db: Session = Depends(get_db)):
    record = db.query(ConsentRecord).filter(ConsentRecord.id == consent_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Registro de consentimiento no encontrado")
    if record.revoked_at:
        raise HTTPException(status_code=400, detail="Este consentimiento ya fue revocado")

    record.revoked_at = datetime.utcnow()
    db.commit()
    logger.info(f"Consentimiento {consent_id} revocado")
    return {"ok": True, "revoked_at": record.revoked_at.isoformat()}


@router.get("")
def list_all_consents(db: Session = Depends(get_db)):
    records = db.query(ConsentRecord).order_by(ConsentRecord.granted_at.desc()).limit(200).all()
    return [_consent_resp(r) for r in records]
