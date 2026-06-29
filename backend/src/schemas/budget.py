from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional
from decimal import Decimal

class BudgetBase(BaseModel):
    user_id: Optional[UUID] = None
    group_id: Optional[UUID] = None
    max_spend_usd: Decimal
    max_tokens: int
    reset_period: str # daily, weekly, monthly, never

class BudgetCreate(BudgetBase):
    pass

class BudgetResponse(BudgetBase):
    id: UUID
    current_spend_usd: Decimal
    current_tokens: int
    last_reset_at: datetime
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
class APIKeyCreate(BaseModel):
    name: str
    user_id: Optional[UUID] = None
    group_id: Optional[UUID] = None
    expires_at: Optional[datetime] = None

class APIKeyResponse(BaseModel):
    id: UUID
    key_preview: str
    name: str
    is_active: bool
    expires_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True
