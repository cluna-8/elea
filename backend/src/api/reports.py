import csv
import io
import json
from datetime import datetime, date
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional

from ..database import get_db
from ..models.audit import AuditLog
from ..models.compliance import ComplianceProject, HumanReview
from ..models.user import User
from ..auth.rbac import require_role

router = APIRouter(prefix="/reports", tags=["Compliance Reports"])

LEGAL_BASIS_LABELS = {
    "art_9_2_h": "Art. 9(2)(h) GDPR — Prestación sanitaria / farmacovigilancia",
    "art_9_2_j": "Art. 9(2)(j) GDPR — Interés público / investigación",
    "art_9_2_a": "Art. 9(2)(a) GDPR — Consentimiento explícito",
    "art_9_2_b": "Art. 9(2)(b) GDPR — Empleo / RRHH",
    "art_9_2_f": "Art. 9(2)(f) GDPR — Reivindicación de derechos",
    "art_6_1_c": "Art. 6(1)(c) GDPR — Obligación legal",
    "art_6_1_e": "Art. 6(1)(e) GDPR — Misión de interés público",
    "art_6_1_b": "Art. 6(1)(b) GDPR — Ejecución de contrato",
    "art_6_1_f": "Art. 6(1)(f) GDPR — Interés legítimo",
}

RISK_LABELS = {
    "minimal": "Riesgo Mínimo",
    "limited": "Riesgo Limitado",
    "high_risk_annex3": "Alto Riesgo — Anexo III EU AI Act",
    "high_risk_annex1": "Alto Riesgo — Anexo I EU AI Act (MDR)",
}


def _csv_response(rows: list[dict], filename: str) -> StreamingResponse:
    if not rows:
        rows = [{}]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/rat", dependencies=[Depends(require_role("admin", "compliance_officer"))])
def export_rat(db: Session = Depends(get_db)):
    """
    Registro de Actividades de Tratamiento — GDPR Art. 30.
    One row per active compliance project.
    """
    projects = db.query(ComplianceProject).filter(ComplianceProject.is_active == True).all()
    today = date.today().isoformat()
    rows = []
    for p in projects:
        rows.append({
            "nombre_actividad": p.name,
            "descripcion": p.description or "",
            "finalidad": p.processing_purpose if hasattr(p, "processing_purpose") else "Asistencia IA para actividades de pharma, marketing y gastos",
            "base_juridica": LEGAL_BASIS_LABELS.get(p.legal_basis, p.legal_basis or ""),
            "categoria_datos": "Datos de categoría especial — Art. 9 GDPR (datos de salud)" if p.data_category == "health_data" else ("Datos de categoría especial — Art. 9 GDPR (datos de empleados)" if p.data_category == "employee_data" else p.data_category or ""),
            "nivel_riesgo_ai_act": RISK_LABELS.get(p.ai_act_risk_level, p.ai_act_risk_level or ""),
            "region_procesamiento": "Unión Europea" if p.eu_region_required else "Sin restricción de región",
            "revision_humana": "Sí" if p.human_review_required else "No",
            "disclosure_ia": "Sí — Art. 50 EU AI Act" if p.ai_disclosure_enabled else "No",
            "referencia_dpia": p.dpia_reference or "Pendiente",
            "version_dpia": p.dpia_version or "",
            "ultima_revision_dpia": p.dpia_last_reviewed or "",
            "fecha_exportacion": today,
        })
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return _csv_response(rows, f"RAT_Art30_GDPR_{ts}.csv")


@router.get("/dsar/{subject_identifier}", dependencies=[Depends(require_role("admin", "compliance_officer"))])
def export_dsar(subject_identifier: str, db: Session = Depends(get_db)):
    """
    DSAR export — GDPR Art. 15 / 20. All audit log entries for the subject.
    Subject identifier is pseudonymized (username or user ID).
    """
    user = db.query(User).filter(
        (User.username == subject_identifier) | (User.id.cast(str) == subject_identifier)
    ).first()

    rows = []
    if user:
        logs = db.query(AuditLog).filter(AuditLog.user_id == user.id).order_by(AuditLog.timestamp.desc()).limit(1000).all()
        for log in logs:
            rows.append({
                "fecha_hora": log.timestamp.isoformat() if log.timestamp else "",
                "modelo_ia": log.model,
                "tokens_prompt": log.prompt_tokens,
                "tokens_respuesta": log.completion_tokens,
                "coste_usd": float(log.cost_usd),
                "datos_personales_detectados": "Sí" if log.pii_detected else "No",
                "entidades_enmascaradas": json.dumps(log.masked_entities or []),
                "estado_compliance": log.compliance_status,
                "disclosure_ia_entregado": "Sí" if log.ai_disclosure_delivered else "No",
                "revision_humana_token": str(log.review_token) if log.review_token else "",
                "proposito_procesamiento": log.processing_purpose or "",
                "latencia_ms": log.latency_ms,
            })

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_id = "".join(c for c in subject_identifier if c.isalnum() or c in "-_")[:32]
    return _csv_response(rows, f"DSAR_{safe_id}_{ts}.csv")


@router.get("/human-review-log", dependencies=[Depends(require_role("admin", "compliance_officer"))])
def export_human_review_log(db: Session = Depends(get_db)):
    """Export all completed human review decisions."""
    reviews = db.query(HumanReview).filter(HumanReview.reviewed_at != None).order_by(HumanReview.reviewed_at.desc()).all()
    rows = []
    for r in reviews:
        rows.append({
            "token_revision": str(r.review_token),
            "audit_log_id": str(r.audit_log_id) if r.audit_log_id else "",
            "accion": r.action or "",
            "revisor": r.reviewer_id or "",
            "notas": r.notes or "",
            "fecha_revision": r.reviewed_at or "",
            "fecha_creacion": r.created_at or "",
        })
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return _csv_response(rows, f"Revisiones_Humanas_{ts}.csv")


@router.get("/executive", dependencies=[Depends(require_role("admin", "compliance_officer"))])
def executive_summary(db: Session = Depends(get_db)):
    """JSON executive summary for the DPO — totals, rates, alerts."""
    # spec 021: los eventos de licencia (model='license') no son transacciones.
    total_logs = db.query(AuditLog).filter(AuditLog.model != "license").count()
    pii_logs = db.query(AuditLog).filter(AuditLog.pii_detected == True).count()
    disclosure_logs = db.query(AuditLog).filter(AuditLog.ai_disclosure_delivered == True).count()
    pending_reviews = db.query(HumanReview).filter(HumanReview.reviewed_at == None).count()
    completed_reviews = db.query(HumanReview).filter(HumanReview.reviewed_at != None).count()
    active_projects = db.query(ComplianceProject).filter(ComplianceProject.is_active == True).count()
    missing_dpia = db.query(ComplianceProject).filter(
        ComplianceProject.is_active == True,
        ComplianceProject.ai_act_risk_level.in_(["high_risk_annex3", "high_risk_annex1"]),
        ComplianceProject.dpia_reference == None,
    ).count()

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "audit": {
            "total_transactions": total_logs,
            "pii_masking_rate_pct": round(pii_logs / total_logs * 100, 1) if total_logs else 0,
            "ai_disclosure_rate_pct": round(disclosure_logs / total_logs * 100, 1) if total_logs else 0,
        },
        "human_review": {
            "pending": pending_reviews,
            "completed": completed_reviews,
            "completion_rate_pct": round(completed_reviews / (pending_reviews + completed_reviews) * 100, 1) if (pending_reviews + completed_reviews) else 100,
        },
        "compliance_projects": {
            "active": active_projects,
            "missing_dpia": missing_dpia,
        },
        "alerts": [
            f"{missing_dpia} proyecto(s) de alto riesgo sin DPIA registrada" if missing_dpia else None,
            f"{pending_reviews} revisiones humanas pendientes" if pending_reviews > 0 else None,
        ],
    }
