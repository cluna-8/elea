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
from ..services import ai_engine_client
from ..services.ai_engine_client import AIEngineClientError

router = APIRouter(prefix="/keys", tags=["Virtual Keys"])


class KeyCreateSchema(BaseModel):
    name: str
    user_id: Optional[UUID] = None
    group_id: Optional[UUID] = None
    max_budget: Optional[float] = None
    budget_duration: Optional[str] = "30d"
    models: Optional[List[str]] = None
    expires_at: Optional[datetime] = None
    compliance_project_id: Optional[UUID] = None
    rpm_limit: Optional[int] = 60
    tpm_limit: Optional[int] = 100000


class KeyResponseSchema(BaseModel):
    id: UUID
    name: str
    key_preview: str
    user_id: Optional[UUID]
    group_id: Optional[UUID]
    is_active: bool
    compliance_project_id: Optional[UUID] = None
    rpm_limit: Optional[int] = 60
    tpm_limit: Optional[int] = 100000
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
    compliance_project_id: Optional[UUID] = None
    created_at: datetime


@router.get("", response_model=List[KeyResponseSchema])
def list_keys(db: Session = Depends(get_db)):
    return db.query(APIKey).all()


@router.post("", response_model=KeyGeneratedResponse, status_code=status.HTTP_201_CREATED)
async def generate_key(key_in: KeyCreateSchema, db: Session = Depends(get_db)):
    engine_team_id: Optional[str] = None
    engine_user_id: Optional[str] = None

    if key_in.group_id:
        group = db.query(Group).filter(Group.id == key_in.group_id).first()
        if not group:
            raise HTTPException(status_code=404, detail="Team/Group not found")
        if not group.engine_team_id:
            raise HTTPException(
                status_code=422,
                detail="This team was created before key management was enabled. Please recreate it to generate keys.",
            )
        engine_team_id = group.engine_team_id

    if key_in.user_id:
        user = db.query(User).filter(User.id == key_in.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if not user.engine_user_id:
            raise HTTPException(
                status_code=422,
                detail="This user was created before key management was enabled. Please recreate them to generate keys.",
            )
        engine_user_id = user.engine_user_id

    try:
        result = await ai_engine_client.generate_key(
            name=key_in.name,
            max_budget=key_in.max_budget,
            budget_duration=key_in.budget_duration or "30d",
            models=key_in.models,
            team_id=engine_team_id,
            user_id=engine_user_id,
        )
    except AIEngineClientError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The AI engine is unavailable. The key was not generated. Please try again.",
        )

    plain_key: str = result["plain_key"]
    engine_key_token: str = result["engine_key_token"]
    key_hash = hashlib.sha256(plain_key.encode()).hexdigest()
    key_preview = f"sk-...{plain_key[-6:]}"

    db_key = APIKey(
        name=key_in.name,
        key_hash=key_hash,
        key_preview=key_preview,
        engine_key_token=engine_key_token,
        user_id=key_in.user_id,
        group_id=key_in.group_id,
        expires_at=key_in.expires_at,
        compliance_project_id=key_in.compliance_project_id,
        rpm_limit=key_in.rpm_limit or 60,
        tpm_limit=key_in.tpm_limit or 100000,
    )
    db.add(db_key)

    try:
        db.commit()
        db.refresh(db_key)
    except Exception:
        db.rollback()
        # Best-effort rollback: revoke the key we just created in the engine
        try:
            await ai_engine_client.delete_key(engine_key_token)
        except AIEngineClientError:
            pass
        raise HTTPException(status_code=500, detail="Failed to save key. Please contact the administrator.")

    return KeyGeneratedResponse(
        id=db_key.id,
        name=db_key.name,
        key_preview=db_key.key_preview,
        plain_key=plain_key,
        user_id=db_key.user_id,
        group_id=db_key.group_id,
        compliance_project_id=db_key.compliance_project_id,
        created_at=db_key.created_at,
    )


@router.delete("/{key_id}")
async def revoke_key(key_id: UUID, db: Session = Depends(get_db)):
    db_key = db.query(APIKey).filter(APIKey.id == key_id).first()
    if not db_key:
        raise HTTPException(status_code=404, detail="Key not found")

    if db_key.engine_key_token:
        try:
            await ai_engine_client.delete_key(db_key.engine_key_token)
        except AIEngineClientError:
            # Engine revocation failed but we still remove it locally —
            # the key won't be accepted by our gateway layer either way.
            pass

    db.delete(db_key)
    db.commit()
    return {"status": "success", "message": "Key revoked successfully"}


@router.get("/{key_id}/spend")
async def get_key_spend(key_id: UUID, db: Session = Depends(get_db)):
    db_key = db.query(APIKey).filter(APIKey.id == key_id).first()
    if not db_key:
        raise HTTPException(status_code=404, detail="Key not found")
    if not db_key.engine_key_token:
        return {"spend_usd": None, "max_budget": None, "remaining": None}
    try:
        return await ai_engine_client.get_key_spend(db_key.engine_key_token)
    except AIEngineClientError:
        return {"spend_usd": None, "max_budget": None, "remaining": None}
