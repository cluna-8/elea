from pydantic import BaseModel, EmailStr
from uuid import UUID
from datetime import datetime
from typing import Optional, List

class GroupBase(BaseModel):
    name: str
    description: Optional[str] = None

class GroupCreate(GroupBase):
    pass

class GroupResponse(GroupBase):
    id: UUID
    engine_team_id: Optional[str] = None
    created_at: datetime
    # Spec 054: ciclo de vida del equipo, mismo criterio que User.is_active/deactivated_at.
    is_active: bool = True
    deactivated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class UserBase(BaseModel):
    username: str
    email: EmailStr
    role: str # admin, compliance_officer, clinician, developer
    group_id: Optional[UUID] = None
    is_active: Optional[bool] = True
    legal_basis: Optional[str] = None
    risk_level: Optional[str] = None
    compliance_project_id: Optional[UUID] = None

class UserPatch(BaseModel):
    """Spec 043 (US5, T051): actualización PARCIAL — todos los campos opcionales, a
    diferencia de `UserBase` (que `PUT /{user_id}` sigue usando, reemplazo completo, se
    mantiene por compatibilidad). Solo lo que el caller manda se toca (`exclude_unset`)."""
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    display_label: Optional[str] = None
    group_id: Optional[UUID] = None
    is_active: Optional[bool] = None
    legal_basis: Optional[str] = None
    risk_level: Optional[str] = None
    compliance_project_id: Optional[UUID] = None


class UserCreate(UserBase):
    # Sin default y sin Optional a propósito: el endpoint tenía un `or "sentinel123"` que le
    # daba la MISMA contraseña conocida a todo usuario creado sin una. La longitud mínima
    # la valida el endpoint (no un Field) para responder el 422 en español.
    password: str

class PasswordChangeRequest(BaseModel):
    """Cambio de la contraseña propia: exige la actual porque el token de sesión sigue
    siendo válido en un equipo ajeno y no alcanza como prueba de identidad."""
    current_password: str
    new_password: str

class PasswordResetRequest(BaseModel):
    """Reseteo por un admin: NO pide la actual (no la conoce, es justo el caso de uso)."""
    new_password: str

class UserResponse(UserBase):
    id: UUID
    engine_user_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
