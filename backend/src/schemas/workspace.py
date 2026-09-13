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
    # Spec 050 FR-041 (12-sep-2026): el Hub declara el tipo de espacio al crearlo. Es registro
    # de acceso (quién ve qué), no lógica de motor: `rag` = documentos, `exact_analysis` =
    # planillas (motor tabular). Antes solo el endpoint de DB-GPT (spec 048, retirado) podía
    # crear espacios `exact_analysis`.
    kind: Literal["rag", "exact_analysis"] = "rag"


class WorkspaceOut(BaseModel):
    id: UUID
    engine_slug: str
    display_name: str
    role: Literal["owner", "member"]
    status: Literal["active", "unassigned"]
    # spec 048/046: distingue un espacio de chat RAG de uno de análisis exacto (DB-GPT). Bug
    # real encontrado en vivo (11-sep): faltaba acá, así que el Hub nunca podía filtrar sus
    # propios espacios de análisis exacto desde GET /workspaces (siempre volvía `None` del
    # ORM, la UI mostraba "no tenés espacios" aunque el espacio SÍ se hubiera creado bien).
    kind: Literal["rag", "exact_analysis"] = "rag"

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
    # Solo tiene efecto cuando engine_thread_slug es None — el slug REAL del motor que
    # respalda el hilo principal de esta persona (bug real 10-sep, ver workspace.py del
    # modelo). Se ignora para hilos explícitos: esos ya traen su propio slug real en
    # engine_thread_slug.
    principal_engine_thread_slug: Optional[str] = None


class WorkspaceThreadOut(BaseModel):
    id: UUID
    workspace_id: UUID
    engine_thread_slug: Optional[str] = None
    principal_engine_thread_slug: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
