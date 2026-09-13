from fastapi import APIRouter, Depends
from .users import router as users_router
from .budgets import router as budgets_router
from .policy import router as policy_router
from .audit import router as audit_router
from .chat import router as chat_router
from .router_config import router as router_config_router
from .keys import router as keys_router
from .guardians import router as guardians_router
from .analytics import router as analytics_router
from .compliance import router as compliance_router
from .groups import router as groups_router
from .consent import router as consent_router
from .reports import router as reports_router
from .costs import router as costs_router
from .monitor import router as monitor_router
from .gateway import router as gateway_router
from .inspect import router as inspect_router
from .health import router as health_router
from .content_policies import router as content_policies_router
from .workspaces import router as workspaces_router
from ..sso.api import router as sso_router, require_sso_enabled
from ..sso.admin_api import router as sso_admin_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(users_router)
api_router.include_router(budgets_router)
api_router.include_router(policy_router)
api_router.include_router(audit_router)
api_router.include_router(chat_router)
# Auto-router semántico (spec 030): vive en su propio módulo pero con el MISMO prefijo
# /chat, así que el panel lo consume en /api/v1/chat/router-config junto al catálogo.
api_router.include_router(router_config_router)
api_router.include_router(keys_router)
api_router.include_router(guardians_router)
api_router.include_router(analytics_router)
api_router.include_router(compliance_router)
api_router.include_router(groups_router)
api_router.include_router(consent_router)
api_router.include_router(reports_router)
api_router.include_router(costs_router)
api_router.include_router(monitor_router)
api_router.include_router(gateway_router)
api_router.include_router(inspect_router)
api_router.include_router(health_router)
api_router.include_router(content_policies_router)
api_router.include_router(workspaces_router)
# SSO (spec 017 US2): el gate de licencia se aplica ACÁ, al montar el router — no
# dentro de cada handler. Como dependency corre ANTES de la validación de request,
# así que con el flag apagado la respuesta es 403 (veredicto de licencia) y nunca un
# 422 de query params que lo tape. Inline correría después y filtraría la forma de la
# superficie antes de decidir si existe.
api_router.include_router(sso_router, dependencies=[Depends(require_sso_enabled)])
# La config del SSO va detrás del MISMO gate de licencia que el flujo: configurar una
# feature que la licencia no habilita sólo puede terminar en una pantalla que promete
# algo que después fail-closea. El rol lo gatea cada endpoint (lectura al auditor,
# escritura al admin).
api_router.include_router(sso_admin_router, dependencies=[Depends(require_sso_enabled)])
