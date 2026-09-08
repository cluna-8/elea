"""Autoridad de pertenencia de espacios de trabajo (spec 043 US1 — T015/T016).

Ver diagnostico.md §1 de la 043: Eleia Hub nunca supo qué espacio o hilo pertenece a quién —
listaba y proxyaba todo con una única credencial de servicio hacia el motor de documentos.
Este módulo es la fuente de verdad, resuelta en el backend Guardian (decisión R1 de
research.md — no delegar en el multiusuario nativo del motor de documentos, single-user y sin
versión fijada).

Principio: toda verificación de acceso pasa por acá, nunca por el cliente que llama (FR-004).
"""
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from ..models.workspace import Workspace, WorkspaceMembership, WorkspaceThread
from ..models.user import User


class WorkspaceAccessDenied(Exception):
    """El usuario no tiene membresía sobre el workspace (o el workspace no existe — mismo
    404-que-no-lo-es: no se distingue "no existe" de "no tenés acceso", contrato 1)."""


class WorkspaceConflict(Exception):
    """Operación rechazada por una regla de negocio (p. ej. quitar al último owner sin
    transferir antes) — mapea a 409 en el router."""


def list_for_user(db: Session, tenant_id, user_id) -> list[dict]:
    """Espacios donde el usuario es owner o member — nunca devuelve nada más."""
    rows = (
        db.query(Workspace, WorkspaceMembership.role)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .filter(
            Workspace.tenant_id == tenant_id,
            WorkspaceMembership.user_id == user_id,
        )
        .all()
    )
    return [
        {"id": ws.id, "engine_slug": ws.engine_slug, "display_name": ws.display_name,
         "role": role, "status": ws.status}
        for ws, role in rows
    ]


def list_unassigned(db: Session, tenant_id) -> list[Workspace]:
    """Espacios sin dueño (backfill de instalaciones existentes, FR-006/FR-010) — solo para
    admins, el caller es responsable de verificar el rol antes de llamar."""
    return (
        db.query(Workspace)
        .filter(Workspace.tenant_id == tenant_id, Workspace.status == "unassigned")
        .all()
    )


def _membership(db: Session, workspace_id, user_id) -> Optional[WorkspaceMembership]:
    return (
        db.query(WorkspaceMembership)
        .filter(WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user_id)
        .first()
    )


def get_with_access_check(db: Session, tenant_id, workspace_id, user_id,
                          *, is_admin: bool = False) -> Workspace:
    """Devuelve el Workspace si el usuario tiene membresía (o es admin); si no, o si el
    workspace no existe, levanta ``WorkspaceAccessDenied`` — el router lo mapea a 403
    SIEMPRE, nunca 404 (no confirmar existencia a quien no tiene acceso, contrato 1)."""
    ws = db.query(Workspace).filter(Workspace.id == workspace_id,
                                    Workspace.tenant_id == tenant_id).first()
    if ws is None:
        raise WorkspaceAccessDenied()
    if is_admin:
        return ws
    if _membership(db, workspace_id, user_id) is None:
        raise WorkspaceAccessDenied()
    return ws


def create_workspace(db: Session, tenant_id, owner_user_id, *, display_name: str,
                     engine_slug: Optional[str] = None) -> Workspace:
    """Crea el espacio en el backend y a su dueño como primer miembro. NO crea nada en el
    motor de documentos — esa orquestación vive del lado de Eleia Hub (spec 044), que llama
    acá con el `engine_slug` real una vez que el espacio ya existe ahí, o deja el campo
    vacío para completarlo después (decisión: "solo se comparte la identidad" con el back)."""
    ws = Workspace(
        id=uuid.uuid4(), tenant_id=tenant_id,
        engine_slug=engine_slug or f"pendiente-{uuid.uuid4().hex[:12]}",
        display_name=display_name, owner_user_id=owner_user_id, status="active",
    )
    db.add(ws)
    db.flush()
    db.add(WorkspaceMembership(id=uuid.uuid4(), tenant_id=tenant_id, workspace_id=ws.id,
                               user_id=owner_user_id, role="owner"))
    db.commit()
    return ws


def add_member(db: Session, tenant_id, workspace_id, *, actor_user_id, username: str,
               is_admin: bool = False) -> WorkspaceMembership:
    """Solo el owner del espacio o un admin pueden agregar miembros (FR-002)."""
    ws = get_with_access_check(db, tenant_id, workspace_id, actor_user_id, is_admin=is_admin)
    if not is_admin:
        actor_membership = _membership(db, workspace_id, actor_user_id)
        if actor_membership is None or actor_membership.role != "owner":
            raise WorkspaceAccessDenied()
    target = db.query(User).filter(User.username == username,
                                   User.tenant_id == tenant_id).first()
    if target is None:
        raise WorkspaceConflict(f"Usuario '{username}' no existe en este tenant.")
    existing = _membership(db, workspace_id, target.id)
    if existing is not None:
        return existing
    row = WorkspaceMembership(id=uuid.uuid4(), tenant_id=tenant_id, workspace_id=ws.id,
                              user_id=target.id, role="member")
    db.add(row)
    db.commit()
    return row


def remove_member(db: Session, tenant_id, workspace_id, *, actor_user_id, target_user_id,
                  is_admin: bool = False) -> None:
    ws = get_with_access_check(db, tenant_id, workspace_id, actor_user_id, is_admin=is_admin)
    if not is_admin:
        actor_membership = _membership(db, workspace_id, actor_user_id)
        if actor_membership is None or actor_membership.role != "owner":
            raise WorkspaceAccessDenied()
    if ws.owner_user_id == target_user_id:
        raise WorkspaceConflict("Transferí la propiedad antes de quitar al dueño.")
    row = _membership(db, workspace_id, target_user_id)
    if row is not None:
        db.delete(row)
        db.commit()


def transfer_owner(db: Session, tenant_id, workspace_id, *, actor_user_id, new_owner_user_id,
                   is_admin: bool = False) -> Workspace:
    ws = get_with_access_check(db, tenant_id, workspace_id, actor_user_id, is_admin=is_admin)
    if not is_admin:
        actor_membership = _membership(db, workspace_id, actor_user_id)
        if actor_membership is None or actor_membership.role != "owner":
            raise WorkspaceAccessDenied()
    new_owner_membership = _membership(db, workspace_id, new_owner_user_id)
    if new_owner_membership is None:
        raise WorkspaceConflict("El nuevo dueño debe ser miembro del espacio primero.")
    old_owner_membership = _membership(db, workspace_id, ws.owner_user_id) if ws.owner_user_id else None
    if old_owner_membership is not None:
        old_owner_membership.role = "member"
    new_owner_membership.role = "owner"
    ws.owner_user_id = new_owner_user_id
    ws.status = "active"
    db.commit()
    return ws


def orphan_owned_workspaces(db: Session, tenant_id, user_id) -> int:
    """Efecto en cascada de dar de baja a un usuario (US5, FR-042): sus espacios propios
    pasan a `unassigned`, nunca se borran. Devuelve cuántos se afectaron."""
    rows = db.query(Workspace).filter(Workspace.tenant_id == tenant_id,
                                      Workspace.owner_user_id == user_id).all()
    for ws in rows:
        ws.owner_user_id = None
        ws.status = "unassigned"
    db.commit()
    return len(rows)


def sync_existing_workspaces(db: Session, tenant_id, engine_slugs: list[str]) -> int:
    """Backfill de instalaciones existentes (FR-006): todo `engine_slug` que el motor de
    documentos ya tenga y el backend no conozca se importa como espacio `unassigned`.
    Idempotente — se puede correr más de una vez sin duplicar filas."""
    known = {
        row[0] for row in db.query(Workspace.engine_slug)
        .filter(Workspace.tenant_id == tenant_id).all()
    }
    created = 0
    for slug in engine_slugs:
        if slug in known:
            continue
        db.add(Workspace(id=uuid.uuid4(), tenant_id=tenant_id, engine_slug=slug,
                         display_name=slug, owner_user_id=None, status="unassigned"))
        created += 1
    if created:
        db.commit()
    return created


# ── Hilos ──────────────────────────────────────────────────────────────────────────────

def list_threads_for_user(db: Session, tenant_id, workspace_id, user_id) -> list[WorkspaceThread]:
    """Solo los hilos del propio usuario dentro del espacio — FR-003, incluso para otros
    miembros del mismo espacio."""
    return (
        db.query(WorkspaceThread)
        .filter(WorkspaceThread.tenant_id == tenant_id,
                WorkspaceThread.workspace_id == workspace_id,
                WorkspaceThread.owner_user_id == user_id)
        .all()
    )


def create_or_get_thread(db: Session, tenant_id, workspace_id, user_id,
                         engine_thread_slug: Optional[str] = None) -> WorkspaceThread:
    existing = (
        db.query(WorkspaceThread)
        .filter(WorkspaceThread.tenant_id == tenant_id,
                WorkspaceThread.workspace_id == workspace_id,
                WorkspaceThread.owner_user_id == user_id,
                WorkspaceThread.engine_thread_slug == engine_thread_slug)
        .first()
    )
    if existing is not None:
        return existing
    row = WorkspaceThread(id=uuid.uuid4(), tenant_id=tenant_id, workspace_id=workspace_id,
                          owner_user_id=user_id, engine_thread_slug=engine_thread_slug)
    db.add(row)
    db.commit()
    return row


def delete_thread(db: Session, tenant_id, workspace_id, user_id, thread_id) -> bool:
    row = (
        db.query(WorkspaceThread)
        .filter(WorkspaceThread.id == thread_id, WorkspaceThread.tenant_id == tenant_id,
                WorkspaceThread.workspace_id == workspace_id,
                WorkspaceThread.owner_user_id == user_id)
        .first()
    )
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True
