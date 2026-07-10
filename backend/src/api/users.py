from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
import hashlib
from pydantic import BaseModel

from ..database import get_db
from ..models.user import User, Group, normalize_legacy_role
from ..schemas.user import UserCreate, UserResponse, GroupCreate, GroupResponse, UserBase
from ..services import ai_engine_client
from ..services.ai_engine_client import AIEngineClientError
from ..auth.session import create_session_token
from ..auth.rbac import require_role

router = APIRouter(prefix="/users", tags=["Users"])


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()

    # Bootstrap: create admin on first login if it doesn't exist yet
    if not user and body.username == "admin":
        user = User(
            username="admin",
            email="admin@basa.com.ar",  # .local es TLD reservado: EmailStr del response lo rechaza (bug heredado)
            password_hash=hash_password(body.password),
            role="tenant_admin",  # canónico post-013 (equivale al legacy 'admin' vía shim RBAC)
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    if not user or not user.is_active or user.password_hash != hash_password(body.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")

    token = create_session_token(str(user.id), user.role, user.username)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "username": user.username,
            "role": user.role,
            "display_label": user.display_label,
            "email": user.email,
        },
    }


# --- Group Endpoints ---

@router.post("/groups", response_model=GroupResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_role("admin"))])
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


@router.get("/groups", response_model=List[GroupResponse], dependencies=[Depends(require_role("admin"))])
def list_groups(db: Session = Depends(get_db)):
    return db.query(Group).all()


# --- User Endpoints ---

@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_role("admin"))])
async def create_user(user_in: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == user_in.username).first():
        raise HTTPException(status_code=400, detail="Username already registered")

    if user_in.group_id:
        if not db.query(Group).filter(Group.id == user_in.group_id).first():
            raise HTTPException(status_code=404, detail="Group not found")

    raw_password = user_in.password if user_in.password else "basa123"
    # Acepta nombres legacy del frontend heredado (admin/clinician/developer) y los
    # normaliza al enum canonico post-013 (ck_users_role) conservando la etiqueta.
    try:
        role, display_label = normalize_legacy_role(user_in.role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    user = User(
        username=user_in.username,
        email=user_in.email,
        password_hash=hash_password(raw_password),
        role=role,
        display_label=display_label,
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


@router.get("", response_model=List[UserResponse], dependencies=[Depends(require_role("admin"))])
def list_users(db: Session = Depends(get_db)):
    return db.query(User).all()


@router.get("/{user_id}", response_model=UserResponse, dependencies=[Depends(require_role("admin"))])
def get_user(user_id: UUID, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/{user_id}", response_model=UserResponse, dependencies=[Depends(require_role("admin"))])
def update_user(user_id: UUID, user_in: UserBase, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    data = user_in.dict(exclude_unset=True)
    # Mismo puente que create_user: acepta roles legacy sin violar ck_users_role
    if "role" in data:
        try:
            data["role"], label = normalize_legacy_role(data["role"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if label:
            data.setdefault("display_label", label)
    for field, value in data.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


# --- Spend Endpoints ---

@router.get("/{user_id}/spend", dependencies=[Depends(require_role("admin"))])
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


@router.get("/groups/{group_id}/spend", dependencies=[Depends(require_role("admin"))])
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
