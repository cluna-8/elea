from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel

from ..database import get_db
from ..models.guardian import Guardian
from ..models.tenant import DEFAULT_TENANT_ID
from ..services.guardian_service import GuardianService
from ..services import ai_engine_client
from ..services import entity_catalog_service
from ..services.encryption_service import encrypt, decrypt
from ..auth.rbac import require_role

router = APIRouter(
    prefix="/guardians",
    tags=["Security Guardians"],
    dependencies=[Depends(require_role("admin"))],
)


class GuardianSchema(BaseModel):
    name: str
    guardian_type: str
    is_active: bool
    config: Dict[str, Any]
    fail_mode: Optional[str] = "log"
    apply_on: Optional[str] = "pre_call"
    service_api_key: Optional[str] = None  # plaintext — encrypted before storage, never returned


class GuardianResponseSchema(BaseModel):
    id: UUID
    name: str
    guardian_type: str
    is_active: bool
    config: Dict[str, Any]
    engine_guardrail_name: Optional[str] = None
    fail_mode: Optional[str] = None
    apply_on: Optional[str] = None
    has_service_key: bool = False  # true if a service API key is stored (never return the key itself)

    class Config:
        from_attributes = True


class GuardianTestRequest(BaseModel):
    text: str


def _to_response(guardian: Guardian) -> GuardianResponseSchema:
    return GuardianResponseSchema(
        id=guardian.id,
        name=guardian.name,
        guardian_type=guardian.guardian_type,
        is_active=guardian.is_active,
        config=guardian.config,
        engine_guardrail_name=None,  # never expose internal engine name to clients
        fail_mode=guardian.fail_mode,
        apply_on=guardian.apply_on,
        has_service_key=bool(guardian.service_api_key_encrypted),
    )


@router.get("", response_model=List[GuardianResponseSchema])
def list_guardians(db: Session = Depends(get_db)):
    guardians = GuardianService.get_or_create_default_guardians(db)
    return [_to_response(g) for g in guardians]


@router.post("", response_model=GuardianResponseSchema, status_code=status.HTTP_201_CREATED)
def create_guardian(payload: GuardianSchema, db: Session = Depends(get_db)):
    guardian = Guardian(
        name=payload.name,
        guardian_type=payload.guardian_type,
        is_active=payload.is_active,
        config=payload.config,
        fail_mode=payload.fail_mode,
        apply_on=payload.apply_on,
        service_api_key_encrypted=encrypt(payload.service_api_key) if payload.service_api_key else None,
    )
    db.add(guardian)
    db.commit()
    db.refresh(guardian)
    return _to_response(guardian)


# ── Catálogo de entidades custom (extensión post-016) ──────────────────────────
# IMPORTANTE: estas rutas van ANTES de `/{guardian_id}` — si no, FastAPI intenta
# parsear "custom-entities" como UUID de guardian_id y devuelve 422.

class CustomEntityDraftRequest(BaseModel):
    description: str


class CustomEntityCreateRequest(BaseModel):
    name: str
    entity_type: str
    regex: str
    score: float = 0.5
    context: Optional[List[str]] = None
    region: str = "eu"
    ai_generated: bool = False


@router.post("/custom-entities/draft", response_model=Dict[str, Any])
async def draft_custom_entity(payload: CustomEntityDraftRequest):
    """Le pide al motor de IA un borrador de patrón a partir de una descripción en
    lenguaje natural. NO persiste nada — el resultado incluye el resultado de
    correrlo contra sus propios casos de prueba, para que un humano decida si
    guardarlo (POST /custom-entities) tal cual o editado."""
    try:
        return await entity_catalog_service.draft_entity(payload.description)
    except entity_catalog_service.UnsafePatternError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/custom-entities", response_model=List[Dict[str, Any]])
def list_custom_entities(db: Session = Depends(get_db)):
    try:
        return entity_catalog_service.list_custom_entities(db, DEFAULT_TENANT_ID)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/custom-entities", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
def create_custom_entity(payload: CustomEntityCreateRequest, db: Session = Depends(get_db)):
    """Persiste un patrón ya revisado (aceptado o editado a mano tras el draft) —
    único punto donde algo se activa en el firewall real. Revalida seguridad
    siempre, sin importar si vino de un draft de IA o se tipeó a mano."""
    try:
        return entity_catalog_service.create_custom_entity(
            db, DEFAULT_TENANT_ID,
            name=payload.name, entity_type=payload.entity_type, regex=payload.regex,
            score=payload.score, context=payload.context, region=payload.region,
            ai_generated=payload.ai_generated,
        )
    except entity_catalog_service.UnsafePatternError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/custom-entities/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_custom_entity(entity_id: str, db: Session = Depends(get_db)):
    try:
        entity_catalog_service.delete_custom_entity(db, DEFAULT_TENANT_ID, entity_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return None


@router.put("/{guardian_id}", response_model=GuardianResponseSchema)
def update_guardian(guardian_id: UUID, payload: GuardianSchema, db: Session = Depends(get_db)):
    guardian = db.query(Guardian).filter(Guardian.id == guardian_id).first()
    if not guardian:
        raise HTTPException(status_code=404, detail="Guardian no encontrado.")

    guardian.name = payload.name
    guardian.guardian_type = payload.guardian_type
    guardian.is_active = payload.is_active
    guardian.config = payload.config
    guardian.fail_mode = payload.fail_mode
    guardian.apply_on = payload.apply_on

    if payload.service_api_key is not None:
        guardian.service_api_key_encrypted = encrypt(payload.service_api_key) if payload.service_api_key else None

    db.commit()
    db.refresh(guardian)
    return _to_response(guardian)


@router.post("/{guardian_id}/test", response_model=Dict[str, Any])
async def test_guardian(guardian_id: UUID, payload: GuardianTestRequest, db: Session = Depends(get_db)):
    guardian = db.query(Guardian).filter(Guardian.id == guardian_id).first()
    if not guardian:
        raise HTTPException(status_code=404, detail="Guardian no encontrado.")

    if not guardian.engine_guardrail_name:
        raise HTTPException(
            status_code=400,
            detail="Este guardián se ejecuta localmente. El test de motor no está disponible para guardianes locales."
        )

    try:
        result = await ai_engine_client.test_guardrail(guardian.engine_guardrail_name, payload.text)
        return result
    except ai_engine_client.AIEngineClientError as e:
        raise HTTPException(status_code=503, detail="El motor de seguridad no está disponible en este momento.")


@router.delete("/{guardian_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_guardian(guardian_id: UUID, db: Session = Depends(get_db)):
    guardian = db.query(Guardian).filter(Guardian.id == guardian_id).first()
    if not guardian:
        raise HTTPException(status_code=404, detail="Guardian no encontrado.")
    db.delete(guardian)
    db.commit()
    return None
