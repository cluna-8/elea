import uuid
import logging
from datetime import date, datetime
from typing import List, Optional, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import text, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.compliance import (
    ComplianceProject, DPARegistry, DataSubjectRequest, HumanReview, RetentionPolicy
)
from ..models.audit import AuditLog
from ..auth.rbac import require_role

router = APIRouter(prefix="/compliance", tags=["Compliance"])
logger = logging.getLogger("basa-secure-gateway.compliance")

DEFAULT_DISCLOSURE_ES = (
    "Este servicio utiliza inteligencia artificial para generar respuestas. "
    "Las respuestas generadas por IA deben ser revisadas por un profesional "
    "cualificado antes de ser aplicadas. (EU AI Act Art. 50)"
)


# ── Schemas ──────────────────────────────────────────────────────────────────

class ComplianceProjectSchema(BaseModel):
    name: str
    description: Optional[str] = None
    legal_basis: str
    legal_basis_notes: Optional[str] = None
    data_category: str = "standard"
    ai_act_risk_level: str = "limited"
    is_active: bool = False
    eu_region_required: bool = False
    human_review_required: bool = False
    ai_disclosure_enabled: bool = True
    ai_disclosure_message: Optional[str] = None
    dpia_reference: Optional[str] = None
    dpia_version: Optional[str] = None
    dpia_last_reviewed: Optional[date] = None

class ComplianceProjectResponse(ComplianceProjectSchema):
    id: UUID
    created_at: Optional[str]
    updated_at: Optional[str]
    class Config:
        from_attributes = True


class DPASchema(BaseModel):
    provider_name: str
    dpa_type: str = "standard"
    signed_date: Optional[date] = None
    expiration_date: Optional[date] = None
    covers_special_categories: bool = False
    processing_region: str = "global"
    document_reference: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True

class DPAResponse(DPASchema):
    id: UUID
    created_at: Optional[str]
    dpa_status: Optional[str] = None
    class Config:
        from_attributes = True


class DSRSchema(BaseModel):
    request_type: str
    subject_identifier: str
    date_received: date
    handled_by: Optional[str] = None
    outcome_notes: Optional[str] = None

class DSRUpdateSchema(BaseModel):
    status: str
    date_completed: Optional[date] = None
    handled_by: Optional[str] = None
    outcome_notes: Optional[str] = None

class DSRResponse(DSRSchema):
    id: UUID
    date_completed: Optional[date]
    status: str
    created_at: Optional[str]
    class Config:
        from_attributes = True


class HumanReviewSubmit(BaseModel):
    reviewer_id: str
    action: str
    notes: Optional[str] = None

class RetentionPolicySchema(BaseModel):
    log_type: str
    retention_days: int
    justification: Optional[str] = None
    updated_by: Optional[str] = None

class RetentionPolicyResponse(RetentionPolicySchema):
    id: UUID
    last_updated: Optional[str]
    class Config:
        from_attributes = True


def _dpa_status(dpa: DPARegistry) -> str:
    if not dpa.expiration_date:
        return "active"
    today = date.today()
    days_left = (dpa.expiration_date - today).days
    if days_left < 0:
        return "expired"
    if days_left <= 30:
        return "expiring_soon"
    return "active"


# ── Compliance Projects ───────────────────────────────────────────────────────

@router.get("/projects", response_model=List[ComplianceProjectResponse], dependencies=[Depends(require_role("admin", "compliance_officer"))])
def list_projects(db: Session = Depends(get_db)):
    return db.query(ComplianceProject).order_by(ComplianceProject.name).all()


@router.post("/projects", response_model=ComplianceProjectResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_role("admin", "compliance_officer"))])
def create_project(payload: ComplianceProjectSchema, db: Session = Depends(get_db)):
    if payload.ai_act_risk_level in ("high_risk_annex3", "high_risk_annex1"):
        payload = payload.model_copy(update={"human_review_required": True})
    now = datetime.utcnow().isoformat()
    project = ComplianceProject(**payload.model_dump(), created_at=now, updated_at=now)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.put("/projects/{project_id}", response_model=ComplianceProjectResponse, dependencies=[Depends(require_role("admin", "compliance_officer"))])
def update_project(project_id: UUID, payload: ComplianceProjectSchema, db: Session = Depends(get_db)):
    project = db.query(ComplianceProject).filter(ComplianceProject.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
    if payload.ai_act_risk_level in ("high_risk_annex3", "high_risk_annex1"):
        payload = payload.model_copy(update={"human_review_required": True})
    for field, value in payload.model_dump().items():
        setattr(project, field, value)
    project.updated_at = datetime.utcnow().isoformat()
    db.commit()
    db.refresh(project)
    return project


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_role("admin", "compliance_officer"))])
def delete_project(project_id: UUID, db: Session = Depends(get_db)):
    project = db.query(ComplianceProject).filter(ComplianceProject.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
    db.delete(project)
    db.commit()


# ── DPA Registry ─────────────────────────────────────────────────────────────

@router.get("/dpas", response_model=List[DPAResponse], dependencies=[Depends(require_role("admin", "compliance_officer"))])
def list_dpas(db: Session = Depends(get_db)):
    dpas = db.query(DPARegistry).order_by(DPARegistry.provider_name).all()
    result = []
    for dpa in dpas:
        d = DPAResponse.model_validate(dpa)
        d.dpa_status = _dpa_status(dpa)
        result.append(d)
    return result


@router.post("/dpas", response_model=DPAResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_role("admin", "compliance_officer"))])
def create_dpa(payload: DPASchema, db: Session = Depends(get_db)):
    dpa = DPARegistry(**payload.model_dump(), created_at=datetime.utcnow().isoformat())
    db.add(dpa)
    db.commit()
    db.refresh(dpa)
    r = DPAResponse.model_validate(dpa)
    r.dpa_status = _dpa_status(dpa)
    return r


@router.put("/dpas/{dpa_id}", response_model=DPAResponse, dependencies=[Depends(require_role("admin", "compliance_officer"))])
def update_dpa(dpa_id: UUID, payload: DPASchema, db: Session = Depends(get_db)):
    dpa = db.query(DPARegistry).filter(DPARegistry.id == dpa_id).first()
    if not dpa:
        raise HTTPException(status_code=404, detail="DPA no encontrado.")
    for field, value in payload.model_dump().items():
        setattr(dpa, field, value)
    db.commit()
    db.refresh(dpa)
    r = DPAResponse.model_validate(dpa)
    r.dpa_status = _dpa_status(dpa)
    return r


@router.delete("/dpas/{dpa_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_role("admin", "compliance_officer"))])
def delete_dpa(dpa_id: UUID, db: Session = Depends(get_db)):
    dpa = db.query(DPARegistry).filter(DPARegistry.id == dpa_id).first()
    if not dpa:
        raise HTTPException(status_code=404, detail="DPA no encontrado.")
    db.delete(dpa)
    db.commit()


# ── Data Subject Requests ─────────────────────────────────────────────────────

@router.get("/dsr", response_model=List[DSRResponse], dependencies=[Depends(require_role("admin", "compliance_officer"))])
def list_dsrs(db: Session = Depends(get_db)):
    return db.query(DataSubjectRequest).order_by(DataSubjectRequest.date_received.desc()).all()


@router.post("/dsr", response_model=DSRResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_role("admin", "compliance_officer"))])
def create_dsr(payload: DSRSchema, db: Session = Depends(get_db)):
    dsr = DataSubjectRequest(**payload.model_dump(), created_at=datetime.utcnow().isoformat())
    db.add(dsr)
    db.commit()
    db.refresh(dsr)
    return dsr


@router.put("/dsr/{dsr_id}", response_model=DSRResponse, dependencies=[Depends(require_role("admin", "compliance_officer"))])
def update_dsr(dsr_id: UUID, payload: DSRUpdateSchema, db: Session = Depends(get_db)):
    dsr = db.query(DataSubjectRequest).filter(DataSubjectRequest.id == dsr_id).first()
    if not dsr:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada.")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(dsr, field, value)
    db.commit()
    db.refresh(dsr)
    return dsr


@router.get("/dsr/search", dependencies=[Depends(require_role("admin", "compliance_officer"))])
def search_dsr(subject_id: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    dsrs = db.query(DataSubjectRequest).filter(
        DataSubjectRequest.subject_identifier == subject_id
    ).all()
    logs = db.query(AuditLog).filter(
        AuditLog.user_id == subject_id
    ).order_by(AuditLog.timestamp.desc()).limit(100).all()
    return {
        "subject_identifier": subject_id,
        "dsr_requests": [{"id": str(d.id), "type": d.request_type, "status": d.status, "date_received": str(d.date_received)} for d in dsrs],
        "audit_log_count": len(logs),
        "audit_logs": [
            {
                "id": str(l.id),
                "timestamp": l.timestamp.isoformat() if l.timestamp else None,
                "model": l.model,
                "pii_detected": l.pii_detected,
                "compliance_status": l.compliance_status,
            }
            for l in logs
        ],
    }


# ── Human Review ──────────────────────────────────────────────────────────────

@router.post("/review/{review_token}", status_code=status.HTTP_200_OK, dependencies=[Depends(require_role("admin", "compliance_officer", "clinician"))])
def submit_review(review_token: UUID, payload: HumanReviewSubmit, db: Session = Depends(get_db)):
    review = db.query(HumanReview).filter(HumanReview.review_token == review_token).first()
    if not review:
        raise HTTPException(status_code=404, detail="Token de revisión no encontrado.")
    if review.reviewed_at:
        raise HTTPException(status_code=409, detail="Esta revisión ya fue completada.")
    review.reviewer_id = payload.reviewer_id
    review.action = payload.action
    review.notes = payload.notes
    review.reviewed_at = datetime.utcnow().isoformat()
    db.commit()
    return {"status": "reviewed", "action": payload.action}


@router.get("/review/pending", dependencies=[Depends(require_role("admin", "compliance_officer", "clinician"))])
def list_pending_reviews(db: Session = Depends(get_db)):
    pending = db.query(HumanReview).filter(HumanReview.reviewed_at == None).order_by(HumanReview.created_at.desc()).all()
    result = []
    for r in pending:
        log = db.query(AuditLog).filter(AuditLog.id == r.audit_log_id).first() if r.audit_log_id else None
        result.append({
            "review_token": str(r.review_token),
            "audit_log_id": str(r.audit_log_id) if r.audit_log_id else None,
            "created_at": r.created_at,
            "response_text": r.response_text,
            "context": {
                "model": log.model if log else None,
                "processing_purpose": log.processing_purpose if log else None,
                "prompt_tokens": log.prompt_tokens if log else None,
                "completion_tokens": log.completion_tokens if log else None,
                "pii_detected": log.pii_detected if log else False,
                "masked_entities": log.masked_entities if log else [],
                "compliance_status": log.compliance_status if log else None,
                "guardian_events": log.guardian_events if log else [],
                "ai_disclosure_delivered": log.ai_disclosure_delivered if log else False,
            } if log else None,
        })
    return result


# ── Retention Policies ────────────────────────────────────────────────────────

@router.get("/retention", response_model=List[RetentionPolicyResponse], dependencies=[Depends(require_role("admin", "compliance_officer"))])
def get_retention(db: Session = Depends(get_db)):
    return db.query(RetentionPolicy).order_by(RetentionPolicy.log_type).all()


@router.put("/retention", response_model=List[RetentionPolicyResponse], dependencies=[Depends(require_role("admin", "compliance_officer"))])
def update_retention(policies: List[RetentionPolicySchema], db: Session = Depends(get_db)):
    updated = []
    for p in policies:
        row = db.query(RetentionPolicy).filter(RetentionPolicy.log_type == p.log_type).first()
        if not row:
            continue
        if p.log_type == "config_audit" and p.retention_days < 365:
            raise HTTPException(status_code=422, detail="La retención de logs de configuración no puede ser inferior a 365 días.")
        row.retention_days = p.retention_days
        row.justification = p.justification
        row.updated_by = p.updated_by
        row.last_updated = datetime.utcnow().isoformat()
        updated.append(row)
    db.commit()
    return updated


# ── DPO Dashboard ─────────────────────────────────────────────────────────────

@router.get("/dashboard", dependencies=[Depends(require_role("admin", "compliance_officer"))])
def get_compliance_dashboard(db: Session = Depends(get_db)):
    today = date.today()

    projects = db.query(ComplianceProject).all()
    proj_active = sum(1 for p in projects if p.is_active)
    proj_warnings = sum(1 for p in projects if p.is_active and p.ai_act_risk_level in ("high_risk_annex3", "high_risk_annex1") and not p.dpia_reference)
    proj_blocked = sum(1 for p in projects if not p.legal_basis)

    dpas = db.query(DPARegistry).filter(DPARegistry.is_active == True).all()
    dpa_active = sum(1 for d in dpas if _dpa_status(d) == "active")
    dpa_expiring = sum(1 for d in dpas if _dpa_status(d) == "expiring_soon")
    dpa_expired = sum(1 for d in dpas if _dpa_status(d) == "expired")

    dpia_missing = sum(1 for p in projects if p.is_active and p.ai_act_risk_level in ("high_risk_annex3", "high_risk_annex1") and not p.dpia_reference)
    dpia_review_due = sum(1 for p in projects if p.dpia_last_reviewed and (today - p.dpia_last_reviewed).days > 365)

    dsrs = db.query(DataSubjectRequest).all()
    dsr_open = sum(1 for d in dsrs if d.status == "open")

    total_logs = db.query(AuditLog).count()
    pii_logs = db.query(AuditLog).filter(AuditLog.pii_detected == True).count()
    disclosure_logs = db.query(AuditLog).filter(AuditLog.ai_disclosure_delivered == True).count()

    pending_reviews = db.query(HumanReview).filter(HumanReview.reviewed_at == None).count()
    total_reviews = db.query(HumanReview).count()
    completed_reviews = total_reviews - pending_reviews

    purpose_rows = (
        db.query(AuditLog.processing_purpose, func.count(AuditLog.id))
        .group_by(AuditLog.processing_purpose)
        .all()
    )
    purpose_distribution = {(p or "sin_especificar"): c for p, c in purpose_rows}

    return {
        "projects": {
            "total": len(projects),
            "active": proj_active,
            "warnings": proj_warnings,
            "blocked": proj_blocked,
        },
        "dpas": {
            "active": dpa_active,
            "expiring_soon": dpa_expiring,
            "expired": dpa_expired,
        },
        "dpias": {
            "missing": dpia_missing,
            "review_due": dpia_review_due,
        },
        "data_subject_requests": {
            "open": dsr_open,
            "total": len(dsrs),
        },
        "audit_stats": {
            "total_logs": total_logs,
            "pii_masking_rate": round(pii_logs / total_logs * 100, 1) if total_logs else 0,
            "ai_disclosure_rate": round(disclosure_logs / total_logs * 100, 1) if total_logs else 0,
        },
        "human_review": {
            "pending": pending_reviews,
            "completed": completed_reviews,
            "completion_rate": round(completed_reviews / total_reviews * 100, 1) if total_reviews else 100,
        },
        "processing_purpose_distribution": purpose_distribution,
    }
