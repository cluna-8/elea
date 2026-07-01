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
    def get_personal_budget(db: Session, user_id: str) -> Budget:
        if not user_id:
            return None
        return db.query(Budget).filter(Budget.user_id == user_id).first()

    @staticmethod
    def get_group_budget(db: Session, group_id: str) -> Budget:
        if not group_id:
            return None
        return db.query(Budget).filter(Budget.group_id == group_id).first()

    @staticmethod
    def get_applicable_budgets(db: Session, user_id: str = None, group_id: str = None) -> list:
        """
        Returns all budgets that apply to this request (personal and/or group).
        Both layers apply simultaneously — the request is blocked if ANY is exhausted.
        When the user has a personal budget, the group budget is ALSO checked (dual-layer).
        When the user has no personal budget, only the group budget applies.
        """
        budgets = []
        resolved_group_id = group_id

        if user_id:
            personal = BudgetService.get_personal_budget(db, user_id)
            if personal:
                budgets.append(personal)

            # Resolve group_id from the user record if not passed explicitly
            if not resolved_group_id:
                user_obj = db.query(User).filter(User.id == user_id).first()
                if user_obj and user_obj.group_id:
                    resolved_group_id = str(user_obj.group_id)

        if resolved_group_id:
            group_b = BudgetService.get_group_budget(db, resolved_group_id)
            if group_b and group_b not in budgets:
                budgets.append(group_b)

        return budgets

    @staticmethod
    def get_budget_by_owner(db: Session, user_id: str = None, group_id: str = None) -> Budget:
        """Legacy single-budget lookup — kept for backward compatibility."""
        budgets = BudgetService.get_applicable_budgets(db, user_id=user_id, group_id=group_id)
        return budgets[0] if budgets else None

    @staticmethod
    def get_user_budget(db: Session, user_id: str) -> Budget:
        return BudgetService.get_personal_budget(db, user_id)

    @staticmethod
    def _budget_has_credit(budget: "Budget") -> bool:
        return (
            budget.current_spend_usd < budget.max_spend_usd
            and budget.current_tokens < budget.max_tokens
        )

    @staticmethod
    def has_sufficient_budget(db: Session, user_id: str = None, group_id: str = None) -> bool:
        """
        Fallback model: allow if AT LEAST ONE applicable budget has remaining credit.
        Personal is the primary allocation; group is the departmental fallback.
        If no budget is configured, the request is allowed.
        """
        budgets = BudgetService.get_applicable_budgets(db, user_id=user_id, group_id=group_id)
        if not budgets:
            return True
        return any(BudgetService._budget_has_credit(b) for b in budgets)

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
    def update_budget(db: Session, user_id: str = None, group_id: str = None, prompt_tokens: int = 0, completion_tokens: int = 0, model: str = "", override_cost: Decimal = None) -> None:
        """
        Parallel deduction: each budget tracks its own spend independently.
        - Personal budget deducts from personal (only while it has credit).
        - Group budget deducts from group (only while it has credit).
        """
        budgets = BudgetService.get_applicable_budgets(db, user_id=user_id, group_id=group_id)
        if not budgets:
            return
        cost = override_cost if override_cost is not None else BudgetService.calculate_cost(model, prompt_tokens, completion_tokens)
        total_tokens = prompt_tokens + completion_tokens
        for budget in budgets:
            if BudgetService._budget_has_credit(budget):
                budget.current_spend_usd += cost
                budget.current_tokens += total_tokens
        db.commit()
