"""Schemas de espacios de trabajo (spec 043 US1 — T011). Proyecciones de `Workspace`/
`WorkspaceMembership`/`WorkspaceThread` hacia la API — ver contrato 1 de la 043
(`specs/043-aislamiento-atribucion-motor/contracts/01-workspaces-membership.md`)."""
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional, Literal


class WorkspaceCreate(BaseModel):
    display_name: str
    # engine_slug es opcional en la creación: si no viene, el llamador (Hub) lo completa una
    # vez que el espacio real existe en el motor de documentos — el backend no orquesta esa
    # creación (queda del lado de la 044, mismo criterio que "solo se comparte la identidad").
    engine_slug: Optional[str] = None


class WorkspaceOut(BaseModel):
    id: UUID
    engine_slug: str
    display_name: str
    role: Literal["owner", "member"]
    status: Literal["active", "unassigned"]

    class Config:
        from_attributes = True


class WorkspaceUnassignedOut(BaseModel):
    """Proyección para admins — espacios sin dueño tras el backfill de instalaciones
    existentes (FR-006/FR-010). Sin `role`: nadie es miembro todavía."""
    id: UUID
    engine_slug: str
    display_name: str
    status: Literal["unassigned"]

    class Config:
        from_attributes = True


class WorkspaceMemberIn(BaseModel):
    username: str


class WorkspaceMemberOut(BaseModel):
    user_id: UUID
    username: str
    role: Literal["owner", "member"]


class WorkspaceTransferOwnerIn(BaseModel):
    new_owner_user_id: UUID


class WorkspaceThreadCreate(BaseModel):
    engine_thread_slug: Optional[str] = None  # None => hilo principal del usuario


class WorkspaceThreadOut(BaseModel):
    id: UUID
    workspace_id: UUID
    engine_thread_slug: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
