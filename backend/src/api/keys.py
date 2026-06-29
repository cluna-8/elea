import secrets
import hashlib
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel

from ..database import get_db
from ..models.budget import APIKey
from ..models.user import User, Group

router = APIRouter(prefix="/keys", tags=["Virtual Keys"])

class KeyCreateSchema(BaseModel):
    name: str
    user_id: Optional[UUID] = None
    group_id: Optional[UUID] = None
    expires_at: Optional[datetime] = None

class KeyResponseSchema(BaseModel):
    id: UUID
    name: str
    key_preview: str
    user_id: Optional[UUID]
    group_id: Optional[UUID]
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class KeyGeneratedResponse(BaseModel):
    id: UUID
    name: str
    key_preview: str
    plain_key: str
    user_id: Optional[UUID]
    group_id: Optional[UUID]
    created_at: datetime

@router.get("", response_model=List[KeyResponseSchema])
def list_keys(db: Session = Depends(get_db)):
    return db.query(APIKey).all()

@router.post("", response_model=KeyGeneratedResponse, status_code=status.HTTP_201_CREATED)
def generate_key(key_in: KeyCreateSchema, db: Session = Depends(get_db)):
    if key_in.user_id:
        user = db.query(User).filter(User.id == key_in.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
    if key_in.group_id:
        group = db.query(Group).filter(Group.id == key_in.group_id).first()
        if not group:
            raise HTTPException(status_code=404, detail="Team/Group not found")

    token = secrets.token_urlsafe(32)
    plain_key = f"basa_sk_{token}"
    
    key_hash = hashlib.sha256(plain_key.encode()).hexdigest()
    key_preview = f"basa_sk_...{plain_key[-6:]}"

    db_key = APIKey(
        name=key_in.name,
        key_hash=key_hash,
        key_preview=key_preview,
        user_id=key_in.user_id,
        group_id=key_in.group_id,
        expires_at=key_in.expires_at
    )
    db.add(db_key)
    db.commit()
    db.refresh(db_key)

    return KeyGeneratedResponse(
        id=db_key.id,
        name=db_key.name,
        key_preview=db_key.key_preview,
        plain_key=plain_key,
        user_id=db_key.user_id,
        group_id=db_key.group_id,
        created_at=db_key.created_at
    )

@router.delete("/{key_id}")
def revoke_key(key_id: UUID, db: Session = Depends(get_db)):
    db_key = db.query(APIKey).filter(APIKey.id == key_id).first()
    if not db_key:
        raise HTTPException(status_code=404, detail="Key not found")
    
    db.delete(db_key)
    db.commit()
    return {"status": "success", "message": "API Key revoked and deleted successfully"}
