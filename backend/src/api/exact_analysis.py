"""`/exact-analysis` — motor de análisis exacto de datos Excel/CSV (spec 048, DB-GPT).

Contrato 1 de la spec 048: lo único que `client/` (Eleia Hub, spec 046) necesita conocer —
nunca habla con DB-GPT directamente (FR-002, DB-GPT no tiene ninguna ruta de red hacia fuera
del backend). Este router es el ÚNICO proxy de autenticación/atribución/presupuesto hacia el
motor — reusa el modelo de pertenencia de `Workspace`/`WorkspaceMembership` (spec 043) con
`kind="exact_analysis"` (migración 020), nunca una entidad paralela.
"""
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.session import get_current_user
from ..database import get_db
from ..models.user import User
from ..services import exact_analysis_service as engine
from ..services import workspace_service as svc
from ..services.budget_service import BudgetService

logger = logging.getLogger("sentinel-secure-gateway")

router = APIRouter(prefix="/exact-analysis", tags=["ExactAnalysis"])

# Modelos permitidos (FR-010/"solo puede elegir entre los del catálogo") — el mismo catálogo
# real de Eleia, no lo que DB-GPT quiera ofrecer. Decisión de implementación simple: por ahora
# el default fijo de docker-compose.yml (DBGPT_ENGINE_MODEL_NAME); si el catálogo crece, esto
# pasa a leerse de GET /chat/models (mismo endpoint que ya usa el Hub) — T082 dejó esto anotado.
_DEFAULT_MODEL = "azure-gpt-4o-mini"

MENSAJE_PRESUPUESTO_AGOTADO = "Alcanzaste tu presupuesto. Contactá a tu administrador."
MENSAJE_MOTOR_NO_DISPONIBLE = (
    "El servicio de análisis de datos no está disponible. Intentá de nuevo en unos minutos."
)


def _require_user(user: Optional[User]) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida: sesión JWT válida no proporcionada o expirada.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def _is_admin(user: User) -> bool:
    return user.role in ("super_admin", "tenant_admin")


class ExactAnalysisWorkspaceCreate(BaseModel):
    display_name: str


class ExactAnalysisQuery(BaseModel):
    question: str


@router.post("/workspaces")
def create_exact_analysis_workspace(
    body: ExactAnalysisWorkspaceCreate,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    user = _require_user(user)
    ws = svc.create_workspace(
        db, user.tenant_id, user.id, display_name=body.display_name, kind="exact_analysis",
    )
    return {
        "id": ws.id, "engine_slug": ws.engine_slug, "display_name": ws.display_name,
        "kind": ws.kind, "role": "owner",
    }


@router.post("/workspaces/{workspace_id}/files")
async def upload_exact_analysis_file(
    workspace_id: uuid.UUID,
    doc_file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    user = _require_user(user)
    try:
        ws = svc.get_with_access_check(db, user.tenant_id, workspace_id, user.id,
                                       is_admin=_is_admin(user))
    except svc.WorkspaceAccessDenied:
        raise HTTPException(status_code=403, detail="No tenés acceso a este espacio.")
    if ws.kind != "exact_analysis":
        raise HTTPException(status_code=409, detail="Este espacio no es de análisis exacto.")
    if not doc_file.filename.lower().endswith((".csv", ".xlsx", ".xls")):
        raise HTTPException(
            status_code=422,
            detail="Solo se aceptan archivos tabulares (.csv, .xlsx, .xls) en este modo.",
        )

    # TODO (T090, US3 — no cerrado en esta ronda): enmascarar el contenido ANTES de que
    # llegue acá, reusando el mismo pipeline de /gw/inspect que ya protege la subida al chat
    # RAG (client/server.js). Documentado honestamente en vez de fingir que ya está: subir un
    # archivo con datos personales reales HOY no lo enmascara para este modo — ver
    # research.md/spec.md de la 048, US3.
    content = await doc_file.read()

    conv_uid = engine.new_conv_uid()
    try:
        upload_data = await engine.upload_file(
            conv_uid=conv_uid, filename=doc_file.filename, content=content,
            content_type=doc_file.content_type or "text/csv",
        )
    except engine.ExactAnalysisEngineError:
        logger.exception("exact-analysis upload falló para workspace=%s", workspace_id)
        raise HTTPException(status_code=502, detail=MENSAJE_MOTOR_NO_DISPONIBLE)

    return {
        "conv_uid": conv_uid,
        "file_name": upload_data.get("file_name"),
        "select_param": upload_data,  # el Hub lo guarda tal cual y lo reenvía en /query
    }


@router.post("/workspaces/{workspace_id}/query")
async def query_exact_analysis(
    workspace_id: uuid.UUID,
    body: dict,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    """`body` espera `{"question": str, "conv_uid": str, "select_param": dict}` — `conv_uid` y
    `select_param` son los que devolvió `POST .../files` (FR-010: preguntas que cruzan varios
    archivos del mismo espacio son responsabilidad del Hub, que puede resubir/reusar el mismo
    `conv_uid` para más de un archivo — DB-GPT acumula contexto por conversación)."""
    user = _require_user(user)
    try:
        ws = svc.get_with_access_check(db, user.tenant_id, workspace_id, user.id,
                                       is_admin=_is_admin(user))
    except svc.WorkspaceAccessDenied:
        raise HTTPException(status_code=403, detail="No tenés acceso a este espacio.")
    if ws.kind != "exact_analysis":
        raise HTTPException(status_code=409, detail="Este espacio no es de análisis exacto.")

    question = (body or {}).get("question")
    conv_uid = (body or {}).get("conv_uid")
    select_param = (body or {}).get("select_param")
    if not question or not conv_uid or not select_param:
        raise HTTPException(status_code=422, detail="Faltan question/conv_uid/select_param.")

    # FR-008: presupuesto ANTES de reenviar nada al motor — mismo criterio que el chat RAG
    # (spec 044 US2 FR-006).
    if not BudgetService.has_sufficient_budget(db, user_id=str(user.id)):
        raise HTTPException(status_code=402, detail=MENSAJE_PRESUPUESTO_AGOTADO)

    try:
        answer = await engine.ask_question(
            conv_uid=conv_uid, question=question, model_name=_DEFAULT_MODEL,
            select_param=select_param,
        )
    except engine.ExactAnalysisEngineError:
        logger.exception("exact-analysis query falló para workspace=%s", workspace_id)
        raise HTTPException(status_code=502, detail=MENSAJE_MOTOR_NO_DISPONIBLE)

    # Trazabilidad del lado de Eleia (ver docstring de exact_analysis_service.py sobre la
    # limitación real de atribución en el motor): al menos queda registrado en logs de
    # aplicación quién preguntó qué, en qué espacio, aunque el AuditLog del motor por ahora
    # atribuya el costo a la llave de servicio — mismo estado que AnythingLLM hoy.
    logger.info(
        "exact-analysis query user=%s workspace=%s conv_uid=%s sql=%r",
        user.id, workspace_id, conv_uid, answer.sql_executed,
    )

    return {
        "answer": answer.content,
        "sql_executed": answer.sql_executed,
        "model_used": answer.model_used,
    }
