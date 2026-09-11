"""Espacios de trabajo de Eleia Hub (spec 043 US1 — T017/T018/T020, contrato 1).

Autoridad de pertenencia real: ningún endpoint de este router confía en lo que el cliente
afirma sobre a qué espacio pertenece — todo pasa por `workspace_service`, que consulta
`workspace_memberships` en cada operación (FR-004). Ver diagnostico.md §1 de la 043.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.session import get_current_user
from ..database import get_db
from ..models.user import User
from ..services import workspace_service as svc
from ..services.audit_service import AuditService
from ..schemas.workspace import (
    WorkspaceCreate, WorkspaceMemberIn, WorkspaceThreadCreate,
    WorkspaceTransferOwnerIn,
)

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])

_ADMIN_ROLES = {"super_admin", "tenant_admin"}


def _require_user(user: Optional[User]) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida: sesión JWT válida no proporcionada o expirada.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def _denied(db: Optional[Session] = None, actor: Optional[User] = None,
            workspace_id: Optional[uuid.UUID] = None):
    # Uniforme para "sin membresía" y "no existe" (contrato 1: nunca 404 que confirme
    # existencia a quien no tiene acceso).
    # FR-005 (T020): fila de auditoría metadata-only del intento — identidad del
    # solicitante y recurso, JAMÁS contenido. Mismo patrón que guardians.py:488 (eventos
    # administrativos sin tráfico de modelo: model lleva el código, cost/tokens en 0).
    # Best-effort: un fallo al auditar NUNCA debe impedir que el 403 se devuelva.
    if db is not None and actor is not None:
        try:
            AuditService.log_transaction(
                db=db, model="workspace_access_denied",
                prompt_tokens=0, completion_tokens=0, cost_usd=0.0,
                pii_detected=False, masked_entities=[],
                compliance_status="blocked_by_policy", latency_ms=0,
                processing_purpose="administrative",
                user_id=actor.id, tenant_id=actor.tenant_id,
                event_type="access_denied",
                document_group_id=workspace_id,
            )
        except Exception:  # noqa: BLE001 — nunca bloquea la respuesta 403 real
            pass
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                        detail="sin acceso a este espacio")


def _is_admin(user: User) -> bool:
    return user.role in _ADMIN_ROLES


@router.get("")
def list_workspaces(all: bool = False, status_filter: Optional[str] = None,
                    db: Session = Depends(get_db),
                    user: Optional[User] = Depends(get_current_user)):
    user = _require_user(user)
    if all or status_filter == "unassigned":
        if not _is_admin(user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="solo admins pueden ver espacios sin asignar")
        rows = svc.list_unassigned(db, user.tenant_id)
        return {"workspaces": [
            {"id": w.id, "engine_slug": w.engine_slug, "display_name": w.display_name,
             "status": w.status} for w in rows
        ]}
    return {"workspaces": svc.list_for_user(db, user.tenant_id, user.id)}


@router.post("")
def create_workspace(body: WorkspaceCreate, db: Session = Depends(get_db),
                     user: Optional[User] = Depends(get_current_user)):
    user = _require_user(user)
    ws = svc.create_workspace(db, user.tenant_id, user.id, display_name=body.display_name,
                              engine_slug=body.engine_slug)
    return {"id": ws.id, "engine_slug": ws.engine_slug, "display_name": ws.display_name,
            "role": "owner", "status": ws.status}


@router.get("/{workspace_id}")
def get_workspace(workspace_id: uuid.UUID, db: Session = Depends(get_db),
                  user: Optional[User] = Depends(get_current_user)):
    user = _require_user(user)
    try:
        ws = svc.get_with_access_check(db, user.tenant_id, workspace_id, user.id,
                                       is_admin=_is_admin(user))
    except svc.WorkspaceAccessDenied:
        _denied(db, user, workspace_id)
    membership = svc._membership(db, workspace_id, user.id)
    role = membership.role if membership else ("owner" if _is_admin(user) else "member")
    return {"id": ws.id, "engine_slug": ws.engine_slug, "display_name": ws.display_name,
            "role": role, "status": ws.status}


@router.get("/{workspace_id}/members")
def list_members(workspace_id: uuid.UUID, db: Session = Depends(get_db),
                 user: Optional[User] = Depends(get_current_user)):
    user = _require_user(user)
    try:
        svc.get_with_access_check(db, user.tenant_id, workspace_id, user.id,
                                  is_admin=_is_admin(user))
    except svc.WorkspaceAccessDenied:
        _denied(db, user, workspace_id)
    from ..models.workspace import WorkspaceMembership
    rows = (
        db.query(WorkspaceMembership, User.username)
        .join(User, User.id == WorkspaceMembership.user_id)
        .filter(WorkspaceMembership.workspace_id == workspace_id)
        .all()
    )
    return {"members": [
        {"user_id": m.user_id, "username": uname, "role": m.role} for m, uname in rows
    ]}


@router.post("/{workspace_id}/members")
def add_member(workspace_id: uuid.UUID, body: WorkspaceMemberIn, db: Session = Depends(get_db),
               user: Optional[User] = Depends(get_current_user)):
    user = _require_user(user)
    try:
        row = svc.add_member(db, user.tenant_id, workspace_id, actor_user_id=user.id,
                             username=body.username, is_admin=_is_admin(user))
    except svc.WorkspaceAccessDenied:
        _denied(db, user, workspace_id)
    except svc.WorkspaceConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return {"user_id": row.user_id, "role": row.role}


@router.delete("/{workspace_id}/members/{target_user_id}")
def remove_member(workspace_id: uuid.UUID, target_user_id: uuid.UUID,
                  db: Session = Depends(get_db),
                  user: Optional[User] = Depends(get_current_user)):
    user = _require_user(user)
    try:
        svc.remove_member(db, user.tenant_id, workspace_id, actor_user_id=user.id,
                          target_user_id=target_user_id, is_admin=_is_admin(user))
    except svc.WorkspaceAccessDenied:
        _denied(db, user, workspace_id)
    except svc.WorkspaceConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return {"status": "ok"}


@router.patch("/{workspace_id}/transfer-owner")
def transfer_owner(workspace_id: uuid.UUID, body: WorkspaceTransferOwnerIn,
                   db: Session = Depends(get_db),
                   user: Optional[User] = Depends(get_current_user)):
    user = _require_user(user)
    try:
        ws = svc.transfer_owner(db, user.tenant_id, workspace_id, actor_user_id=user.id,
                                new_owner_user_id=body.new_owner_user_id,
                                is_admin=_is_admin(user))
    except svc.WorkspaceAccessDenied:
        _denied(db, user, workspace_id)
    except svc.WorkspaceConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return {"id": ws.id, "owner_user_id": ws.owner_user_id}


# ── Hilos (FR-003) ────────────────────────────────────────────────────────────────────

@router.get("/{workspace_id}/threads")
def list_threads(workspace_id: uuid.UUID, db: Session = Depends(get_db),
                 user: Optional[User] = Depends(get_current_user)):
    user = _require_user(user)
    try:
        svc.get_with_access_check(db, user.tenant_id, workspace_id, user.id,
                                  is_admin=_is_admin(user))
    except svc.WorkspaceAccessDenied:
        _denied(db, user, workspace_id)
    rows = svc.list_threads_for_user(db, user.tenant_id, workspace_id, user.id)
    return {"threads": [
        {"id": t.id, "workspace_id": t.workspace_id,
         "engine_thread_slug": t.engine_thread_slug,
         "principal_engine_thread_slug": t.principal_engine_thread_slug,
         "created_at": t.created_at}
        for t in rows
    ]}


@router.post("/{workspace_id}/threads")
def create_thread(workspace_id: uuid.UUID, body: WorkspaceThreadCreate,
                  db: Session = Depends(get_db),
                  user: Optional[User] = Depends(get_current_user)):
    user = _require_user(user)
    try:
        svc.get_with_access_check(db, user.tenant_id, workspace_id, user.id,
                                  is_admin=_is_admin(user))
    except svc.WorkspaceAccessDenied:
        _denied(db, user, workspace_id)
    row = svc.create_or_get_thread(db, user.tenant_id, workspace_id, user.id,
                                   engine_thread_slug=body.engine_thread_slug,
                                   principal_engine_thread_slug=body.principal_engine_thread_slug)
    return {"id": row.id, "workspace_id": row.workspace_id,
            "engine_thread_slug": row.engine_thread_slug,
            "principal_engine_thread_slug": row.principal_engine_thread_slug,
            "created_at": row.created_at}


@router.delete("/{workspace_id}/threads/{thread_id}")
def delete_thread(workspace_id: uuid.UUID, thread_id: uuid.UUID, db: Session = Depends(get_db),
                  user: Optional[User] = Depends(get_current_user)):
    user = _require_user(user)
    try:
        svc.get_with_access_check(db, user.tenant_id, workspace_id, user.id,
                                  is_admin=_is_admin(user))
    except svc.WorkspaceAccessDenied:
        _denied(db, user, workspace_id)
    ok = svc.delete_thread(db, user.tenant_id, workspace_id, user.id, thread_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="hilo no encontrado")
    return {"status": "ok"}
