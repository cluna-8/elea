from decimal import Decimal
from sqlalchemy.orm import Session
from ..models.budget import Budget
from ..models.user import User

# Model pricing per 1,000,000 tokens (Input, Output) in USD
MODEL_PRICING = {
    "gpt-4o": {"input": Decimal("5.00"), "output": Decimal("15.00")},
    "azure-gpt-4o-mini": {"input": Decimal("0.165"), "output": Decimal("0.66")},
    "gemini-2.5-flash": {"input": Decimal("0.30"), "output": Decimal("2.50")},
    "gemini-2.5-flash-lite": {"input": Decimal("0.075"), "output": Decimal("0.30")},
    "gpt-4o-mini": {"input": Decimal("0.15"), "output": Decimal("0.60")},
    "claude-3-5-sonnet": {"input": Decimal("3.00"), "output": Decimal("15.00")},
    "default": {"input": Decimal("5.00"), "output": Decimal("15.00")}
}

class BudgetService:
    @staticmethod
    def get_budget_by_owner(db: Session, user_id: str = None, group_id: str = None) -> Budget:
        """
        Retrieves the active budget for a user or group.
        """
        if user_id:
            budget = db.query(Budget).filter(Budget.user_id == user_id).first()
            if budget:
                return budget
            # Fallback to group budget if user has no direct budget
            user = db.query(User).filter(User.id == user_id).first()
            if user and user.group_id:
                return db.query(Budget).filter(Budget.group_id == user.group_id).first()
        if group_id:
            return db.query(Budget).filter(Budget.group_id == group_id).first()
        return None

    @staticmethod
    def get_user_budget(db: Session, user_id: str) -> Budget:
        return BudgetService.get_budget_by_owner(db, user_id=user_id)

    @staticmethod
    def has_sufficient_budget(db: Session, user_id: str = None, group_id: str = None) -> bool:
        """
        Checks if the user or group has remaining budget (monetary and tokens).
        """
        budget = BudgetService.get_budget_by_owner(db, user_id=user_id, group_id=group_id)
        if not budget:
            # If no budget is configured, we allow the request by default
            return True
            
        if budget.current_spend_usd >= budget.max_spend_usd:
            return False
            
        if budget.current_tokens >= budget.max_tokens:
            return False
            
        return True

    @staticmethod
    def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
        """
        Calculates the cost of a request based on the model and token counts.
        """
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])
        input_cost = (Decimal(prompt_tokens) / Decimal("1000000")) * pricing["input"]
        output_cost = (Decimal(completion_tokens) / Decimal("1000000")) * pricing["output"]
        return input_cost + output_cost

    @staticmethod
    def update_budget(db: Session, user_id: str = None, group_id: str = None, prompt_tokens: int = 0, completion_tokens: int = 0, model: str = "", override_cost: Decimal = None) -> Budget:
        """
        Updates the budget consumption for a user or their group.
        """
        budget = BudgetService.get_budget_by_owner(db, user_id=user_id, group_id=group_id)
        if not budget:
            return None
            
        cost = override_cost if override_cost is not None else BudgetService.calculate_cost(model, prompt_tokens, completion_tokens)
        total_tokens = prompt_tokens + completion_tokens
        
        budget.current_spend_usd += cost
        budget.current_tokens += total_tokens
        
        db.commit()
        db.refresh(budget)
        return budget
