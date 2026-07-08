from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from ..database import get_db
from ..models.budget import Budget
from ..schemas.budget import BudgetCreate, BudgetResponse
from ..auth.rbac import require_role

router = APIRouter(
    prefix="/budgets",
    tags=["Budgets"],
    dependencies=[Depends(require_role("admin"))],
)

@router.post("", response_model=BudgetResponse, status_code=status.HTTP_201_CREATED)
def create_budget(budget_in: BudgetCreate, db: Session = Depends(get_db)):
    # Validate user or group is provided
    if not budget_in.user_id and not budget_in.group_id:
        raise HTTPException(status_code=400, detail="Either user_id or group_id must be provided")
        
    if budget_in.user_id and budget_in.group_id:
        raise HTTPException(status_code=400, detail="Cannot assign a budget to both a user and a group simultaneously")

    # Check if budget already exists
    if budget_in.user_id:
        existing = db.query(Budget).filter(Budget.user_id == budget_in.user_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Budget already exists for this user")
    else:
        existing = db.query(Budget).filter(Budget.group_id == budget_in.group_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Budget already exists for this group")

    budget = Budget(
        user_id=budget_in.user_id,
        group_id=budget_in.group_id,
        max_spend_usd=budget_in.max_spend_usd,
        max_tokens=budget_in.max_tokens,
        reset_period=budget_in.reset_period
    )
    db.add(budget)
    db.commit()
    db.refresh(budget)
    return budget

@router.get("", response_model=List[BudgetResponse])
def list_budgets(db: Session = Depends(get_db)):
    return db.query(Budget).all()

@router.get("/{budget_id}", response_model=BudgetResponse)
def get_budget(budget_id: UUID, db: Session = Depends(get_db)):
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    return budget

@router.put("/{budget_id}", response_model=BudgetResponse)
def update_budget(budget_id: UUID, budget_in: BudgetCreate, db: Session = Depends(get_db)):
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    for field, value in budget_in.dict(exclude_unset=True).items():
        setattr(budget, field, value)

    db.commit()
    db.refresh(budget)
    return budget


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(budget_id: UUID, db: Session = Depends(get_db)):
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    db.delete(budget)
    db.commit()
