from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from ..database import get_db
from ..models.policy import SecurityPolicy
from ..auth.rbac import require_role
from pydantic import BaseModel
from typing import Dict, List, Optional

router = APIRouter(
    prefix="/security",
    tags=["Security & Optimization"],
    dependencies=[Depends(require_role("admin", "compliance_officer"))],
)

class PolicyCreateSchema(BaseModel):
    name: str
    is_active: bool
    entity_configs: Dict[str, str]
    gdpr_mode: bool
    ai_act_mode: bool
    headroom_mode: bool

class PolicyUpdateSchema(BaseModel):
    name: str
    is_active: bool
    entity_configs: Dict[str, str]
    gdpr_mode: bool
    ai_act_mode: bool
    headroom_mode: bool

def get_or_create_default_policy(db: Session) -> SecurityPolicy:
    policy = db.query(SecurityPolicy).first()
    if not policy:
        policy = SecurityPolicy(
            name="Política de Seguridad BASA",
            is_active=True,
            entity_configs={
                "PERSON": "MASK",
                "PHONE_NUMBER": "MASK",
                "EMAIL_ADDRESS": "MASK",
                "US_SSN": "BLOCK",
                "MEDICAL_LICENSE": "BLOCK",
                "DNI": "MASK",
                "CUIL": "MASK"
            },
            gdpr_mode=True,
            ai_act_mode=True,
            headroom_mode=False
        )
        db.add(policy)
        db.commit()
        db.refresh(policy)
    return policy

@router.get("/policy")
def get_active_policy(db: Session = Depends(get_db)):
    policy = db.query(SecurityPolicy).filter(SecurityPolicy.is_active == True).first()
    if not policy:
        policy = get_or_create_default_policy(db)
    return policy

@router.put("/policy")
def update_active_policy(policy_in: PolicyUpdateSchema, db: Session = Depends(get_db)):
    policy = db.query(SecurityPolicy).filter(SecurityPolicy.is_active == True).first()
    if not policy:
        policy = get_or_create_default_policy(db)
        
    policy.name = policy_in.name
    policy.is_active = policy_in.is_active
    policy.entity_configs = policy_in.entity_configs
    policy.gdpr_mode = policy_in.gdpr_mode
    policy.ai_act_mode = policy_in.ai_act_mode
    policy.headroom_mode = policy_in.headroom_mode
    
    db.commit()
    db.refresh(policy)
    return policy

@router.get("/policies")
def list_policies(db: Session = Depends(get_db)):
    get_or_create_default_policy(db)
    return db.query(SecurityPolicy).order_by(SecurityPolicy.created_at.asc()).all()

@router.post("/policies")
def create_policy(policy_in: PolicyCreateSchema, db: Session = Depends(get_db)):
    if policy_in.is_active:
        db.query(SecurityPolicy).update({SecurityPolicy.is_active: False})
        db.commit()
        
    policy = SecurityPolicy(
        name=policy_in.name,
        is_active=policy_in.is_active,
        entity_configs=policy_in.entity_configs,
        gdpr_mode=policy_in.gdpr_mode,
        ai_act_mode=policy_in.ai_act_mode,
        headroom_mode=policy_in.headroom_mode
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy

@router.put("/policies/{policy_id}")
def update_policy_by_id(policy_id: UUID, policy_in: PolicyUpdateSchema, db: Session = Depends(get_db)):
    policy = db.query(SecurityPolicy).filter(SecurityPolicy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
        
    if policy_in.is_active and not policy.is_active:
        db.query(SecurityPolicy).filter(SecurityPolicy.id != policy_id).update({SecurityPolicy.is_active: False})
        db.commit()
        
    policy.name = policy_in.name
    policy.is_active = policy_in.is_active
    policy.entity_configs = policy_in.entity_configs
    policy.gdpr_mode = policy_in.gdpr_mode
    policy.ai_act_mode = policy_in.ai_act_mode
    policy.headroom_mode = policy_in.headroom_mode
    
    db.commit()
    db.refresh(policy)
    return policy

@router.delete("/policies/{policy_id}")
def delete_policy(policy_id: UUID, db: Session = Depends(get_db)):
    policy = db.query(SecurityPolicy).filter(SecurityPolicy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
        
    total_count = db.query(SecurityPolicy).count()
    if total_count <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the only remaining policy")
        
    was_active = policy.is_active
    db.delete(policy)
    db.commit()
    
    if was_active:
        next_policy = db.query(SecurityPolicy).first()
        if next_policy:
            next_policy.is_active = True
            db.commit()
            
    return {"status": "success", "message": "Policy deleted successfully"}
