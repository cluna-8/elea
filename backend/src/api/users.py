from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
import hashlib

from ..database import get_db
from ..models.user import User, Group
from ..schemas.user import UserCreate, UserResponse, GroupCreate, GroupResponse, UserBase

router = APIRouter(prefix="/users", tags=["Users"])

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# --- Group Endpoints ---

@router.post("/groups", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
def create_group(group_in: GroupCreate, db: Session = Depends(get_db)):
    db_group = db.query(Group).filter(Group.name == group_in.name).first()
    if db_group:
        raise HTTPException(status_code=400, detail="Group with this name already exists")
    
    group = Group(
        name=group_in.name,
        description=group_in.description
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group

@router.get("/groups", response_model=List[GroupResponse])
def list_groups(db: Session = Depends(get_db)):
    return db.query(Group).all()

# --- User Endpoints ---

@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user_in: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user_in.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    if user_in.group_id:
        group = db.query(Group).filter(Group.id == user_in.group_id).first()
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")

    # Use robust SHA-256 hashing to avoid Python 3.12 passlib/bcrypt bugs
    raw_password = user_in.password if user_in.password else "basa123"
    hashed_password = hash_password(raw_password)
    user = User(
        username=user_in.username,
        email=user_in.email,
        password_hash=hashed_password,
        role=user_in.role,
        group_id=user_in.group_id,
        is_active=user_in.is_active
    )
    db.add(user)
    db.commit()
    db.refresh(user)
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
    
    # Update fields
    for field, value in user_in.dict(exclude_unset=True).items():
        setattr(user, field, value)
        
    db.commit()
    db.refresh(user)
    return user
