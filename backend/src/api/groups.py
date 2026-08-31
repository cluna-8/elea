import logging
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import Group, User
from ..models.compliance import ComplianceProject
from ..auth.rbac import require_role

router = APIRouter(
    prefix="/groups",
    tags=["Groups"],
    # gestion_iam: el auditor (compliance_officer) LEE los grupos (R); los writes re-cierran
    # a admin por-endpoint (#247, alinea a la matriz).
    dependencies=[Depends(require_role("admin", "compliance_officer"))],
)
logger = logging.getLogger("sentinel-secure-gateway.groups")


# ── Schemas ───────────────────────────────────────────────────────────────────

class GroupComplianceUpdate(BaseModel):
    default_legal_basis: Optional[str] = None
    default_risk_level: Optional[str] = None
    compliance_project_id: Optional[UUID] = None

class GroupComplianceResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    engine_team_id: Optional[str] = None
    default_legal_basis: Optional[str] = None
    default_risk_level: Optional[str] = None
    compliance_project_id: Optional[UUID] = None
    compliance_project_name: Optional[str] = None
    user_count: int = 0
    created_at: Optional[str] = None

    class Config:
        from_attributes = True

class UserGroupAssign(BaseModel):
    group_id: Optional[UUID] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _group_response(group: Group, db: Session) -> dict:
    project_name = None
    if group.compliance_project_id:
        proj = db.query(ComplianceProject).filter(ComplianceProject.id == group.compliance_project_id).first()
        project_name = proj.name if proj else None

    user_count = db.query(User).filter(User.group_id == group.id).count()

    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "engine_team_id": group.engine_team_id,
        "default_legal_basis": group.default_legal_basis,
        "default_risk_level": group.default_risk_level,
        "compliance_project_id": group.compliance_project_id,
        "compliance_project_name": project_name,
        "user_count": user_count,
        "created_at": group.created_at.isoformat() if group.created_at else None,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=List[GroupComplianceResponse])
def list_groups(db: Session = Depends(get_db)):
    groups = db.query(Group).order_by(Group.name).all()
    return [_group_response(g, db) for g in groups]


@router.get("/{group_id}", response_model=GroupComplianceResponse)
def get_group(group_id: UUID, db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    return _group_response(group, db)


@router.put("/{group_id}/compliance", response_model=GroupComplianceResponse, dependencies=[Depends(require_role("admin"))])
def update_group_compliance(group_id: UUID, body: GroupComplianceUpdate, db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    if body.compliance_project_id:
        proj = db.query(ComplianceProject).filter(ComplianceProject.id == body.compliance_project_id).first()
        if not proj:
            raise HTTPException(status_code=404, detail="Proyecto de compliance no encontrado")

    if body.default_legal_basis is not None:
        group.default_legal_basis = body.default_legal_basis
    if body.default_risk_level is not None:
        group.default_risk_level = body.default_risk_level
    if body.compliance_project_id is not None:
        group.compliance_project_id = body.compliance_project_id

    db.commit()
    db.refresh(group)
    logger.info(f"Grupo {group.name} perfil compliance actualizado")
    return _group_response(group, db)


@router.delete("/{group_id}/compliance", dependencies=[Depends(require_role("admin"))])
def clear_group_compliance(group_id: UUID, db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    group.default_legal_basis = None
    group.default_risk_level = None
    group.compliance_project_id = None
    db.commit()
    return {"ok": True}


@router.get("/{group_id}/users")
def list_group_users(group_id: UUID, db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    users = db.query(User).filter(User.group_id == group_id).all()
    return [
        {"id": u.id, "username": u.username, "email": u.email, "role": u.role, "is_active": u.is_active}
        for u in users
    ]


@router.put("/users/{user_id}/group", dependencies=[Depends(require_role("admin"))])
def assign_user_group(user_id: UUID, body: UserGroupAssign, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if body.group_id:
        group = db.query(Group).filter(Group.id == body.group_id).first()
        if not group:
            raise HTTPException(status_code=404, detail="Grupo no encontrado")

    user.group_id = body.group_id
    db.commit()
    db.refresh(user)
    return {"ok": True, "user_id": str(user_id), "group_id": str(body.group_id) if body.group_id else None}
