from fastapi import APIRouter
from .users import router as users_router
from .budgets import router as budgets_router
from .policy import router as policy_router
from .audit import router as audit_router
from .chat import router as chat_router
from .keys import router as keys_router
from .guardians import router as guardians_router
from .analytics import router as analytics_router
from .compliance import router as compliance_router
from .groups import router as groups_router
from .consent import router as consent_router
from .reports import router as reports_router
from .costs import router as costs_router
from .monitor import router as monitor_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(users_router)
api_router.include_router(budgets_router)
api_router.include_router(policy_router)
api_router.include_router(audit_router)
api_router.include_router(chat_router)
api_router.include_router(keys_router)
api_router.include_router(guardians_router)
api_router.include_router(analytics_router)
api_router.include_router(compliance_router)
api_router.include_router(groups_router)
api_router.include_router(consent_router)
api_router.include_router(reports_router)
api_router.include_router(costs_router)
api_router.include_router(monitor_router)
