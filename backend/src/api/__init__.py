from fastapi import APIRouter
from .users import router as users_router
from .budgets import router as budgets_router
from .policy import router as policy_router
from .audit import router as audit_router
from .chat import router as chat_router
from .keys import router as keys_router
from .guardians import router as guardians_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(users_router)
api_router.include_router(budgets_router)
api_router.include_router(policy_router)
api_router.include_router(audit_router)
api_router.include_router(chat_router)
api_router.include_router(keys_router)
api_router.include_router(guardians_router)
