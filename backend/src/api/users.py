from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
import hashlib

from ..database import get_db
from ..models.user import User, Group
from ..schemas.user import UserCreate, UserResponse, GroupCreate, GroupResponse, UserBase
from ..services import ai_engine_client
from ..services.ai_engine_client import AIEngineClientError

router = APIRouter(prefix="/users", tags=["Users"])


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# --- Group Endpoints ---

@router.post("/groups", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(group_in: GroupCreate, db: Session = Depends(get_db)):
    if db.query(Group).filter(Group.name == group_in.name).first():
        raise HTTPException(status_code=400, detail="Group with this name already exists")

    group = Group(name=group_in.name, description=group_in.description)
    db.add(group)
    db.commit()
    db.refresh(group)

    try:
        engine_team_id = await ai_engine_client.create_team(name=group_in.name)
        group.engine_team_id = engine_team_id
        db.commit()
        db.refresh(group)
    except AIEngineClientError:
        db.delete(group)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The AI engine is unavailable. The team was not created. Please try again.",
        )

    return group


@router.get("/groups", response_model=List[GroupResponse])
def list_groups(db: Session = Depends(get_db)):
    return db.query(Group).all()


# --- User Endpoints ---

@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(user_in: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == user_in.username).first():
        raise HTTPException(status_code=400, detail="Username already registered")

    if user_in.group_id:
        if not db.query(Group).filter(Group.id == user_in.group_id).first():
            raise HTTPException(status_code=404, detail="Group not found")

    raw_password = user_in.password if user_in.password else "basa123"
    user = User(
        username=user_in.username,
        email=user_in.email,
        password_hash=hash_password(raw_password),
        role=user_in.role,
        group_id=user_in.group_id,
        is_active=user_in.is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    try:
        engine_user_id = await ai_engine_client.create_user(user_id=user_in.email)
        user.engine_user_id = engine_user_id
        db.commit()
        db.refresh(user)
    except AIEngineClientError:
        db.delete(user)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The AI engine is unavailable. The user was not created. Please try again.",
        )

    return user


@router.get("", response_model=List[UserResponse])
def list_users(db: Session = Depends(get_db)):
    return db.query(User).all()


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: UUID, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/{user_id}", response_model=UserResponse)
def update_user(user_id: UUID, user_in: UserBase, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    for field, value in user_in.dict(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


# --- Spend Endpoints ---

@router.get("/{user_id}/spend")
async def get_user_spend(user_id: UUID, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.engine_user_id:
        return {"spend_usd": None, "max_budget": None, "remaining": None}
    try:
        return await ai_engine_client.get_user_spend(user.engine_user_id)
    except AIEngineClientError:
        return {"spend_usd": None, "max_budget": None, "remaining": None}


@router.get("/groups/{group_id}/spend")
async def get_group_spend(group_id: UUID, db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if not group.engine_team_id:
        return {"spend_usd": None, "max_budget": None, "remaining": None}
    try:
        return await ai_engine_client.get_team_spend(group.engine_team_id)
    except AIEngineClientError:
        return {"spend_usd": None, "max_budget": None, "remaining": None}
