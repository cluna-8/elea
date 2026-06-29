from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel

from ..database import get_db
from ..models.guardian import Guardian
from ..services.guardian_service import GuardianService

router = APIRouter(prefix="/guardians", tags=["Security Guardians"])

class GuardianSchema(BaseModel):
    name: str
    guardian_type: str
    is_active: bool
    config: Dict[str, Any]

class GuardianResponseSchema(BaseModel):
    id: UUID
    name: str
    guardian_type: str
    is_active: bool
    config: Dict[str, Any]

    class Config:
        from_attributes = True

@router.get("", response_model=List[GuardianResponseSchema])
def list_guardians(db: Session = Depends(get_db)):
    return GuardianService.get_or_create_default_guardians(db)

@router.post("", response_model=GuardianResponseSchema, status_code=status.HTTP_201_CREATED)
def create_guardian(payload: GuardianSchema, db: Session = Depends(get_db)):
    guardian = Guardian(
        name=payload.name,
        guardian_type=payload.guardian_type,
        is_active=payload.is_active,
        config=payload.config
    )
    db.add(guardian)
    db.commit()
    db.refresh(guardian)
    return guardian

@router.put("/{guardian_id}", response_model=GuardianResponseSchema)
def update_guardian(guardian_id: UUID, payload: GuardianSchema, db: Session = Depends(get_db)):
    guardian = db.query(Guardian).filter(Guardian.id == guardian_id).first()
    if not guardian:
        raise HTTPException(status_code=404, detail="Guardian no encontrado.")
    
    guardian.name = payload.name
    guardian.guardian_type = payload.guardian_type
    guardian.is_active = payload.is_active
    guardian.config = payload.config
    
    db.commit()
    db.refresh(guardian)
    return guardian

@router.delete("/{guardian_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_guardian(guardian_id: UUID, db: Session = Depends(get_db)):
    guardian = db.query(Guardian).filter(Guardian.id == guardian_id).first()
    if not guardian:
        raise HTTPException(status_code=404, detail="Guardian no encontrado.")
    db.delete(guardian)
    db.commit()
    return None
