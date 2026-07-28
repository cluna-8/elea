import csv
import enum
import io
import logging
from datetime import datetime
from typing import List, Optional, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.audit import AuditLog
from ..auth.rbac import require_role

router = APIRouter(
    prefix="/audit-logs",
    tags=["Audit Logs"],
    dependencies=[Depends(require_role("admin", "compliance_officer"))],
)
logger = logging.getLogger("basa-secure-gateway.audit")


# ── Filtro de estado (spec 031, FR-006 + contrato §UI) ───────────────────────────────
#
# Hasta la 031 el officer tenía que INFERIR el bloqueo: filtrar por un
# `compliance_status` exacto exigía conocer de memoria los valores (`blocked_prohibited`,
# `blocked_secret`, `blocked_guardian`…) o adivinar por «0/0 tokens». Ahora hay un filtro
# explícito sobre la convención D1: prefijo `blocked_`, filtro canónico `LIKE 'blocked%'`.
#
# Es un Enum y no un string libre A PROPÓSITO: un valor mal escrito devuelve 422 en vez de
# ignorarse en silencio. En una pantalla de cumplimiento, un filtro que se ignora es peor
# que un error — el officer cree estar viendo SÓLO los bloqueos y está viendo todo.
BLOQUEADO_LIKE = "blocked%"

# `model='license'` son los eslabones de la hash-chain de licencias (021): transiciones del
# ciclo de vida del deployment, NO intentos de tráfico. Y varias de ellas escriben
# `compliance_status='blocked_by_policy'` (licensing/audit_events.py:195), o sea que caen de
# lleno en `LIKE 'blocked%'`. Sin esta exclusión, «Bloqueados» mezclaría «se venció la
# licencia» con «un empleado intentó pegar el padrón de socios», que es exactamente la
# confusión que la pantalla tiene que eliminar. Mismo criterio que ya aplica el agregado de
# cobertura de analytics (`model <> 'license'`, protegido tras el hallazgo de la 028) — la
# hash-chain no se toca: sólo se la deja fuera de un filtro de tráfico (FR-010).
MODELO_LICENCIA = "license"


class EstadoFiltro(str, enum.Enum):
    BLOQUEADOS = "bloqueados"
    PERMITIDOS = "permitidos"


class AuditLogResponseSchema(BaseModel):
    id: UUID
    timestamp: datetime
    user_id: Optional[UUID]
    api_key_id: Optional[UUID]
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    pii_detected: bool
    masked_entities: Optional[List[Any]]
    compliance_status: str
    latency_ms: int
    tokens_saved_by_optimization: int
    guardian_events: Optional[List[Any]]
    # Capa que bloqueó (spec 027, `layer_key` del registry; NULL en filas anteriores y en
    # las permitidas). Va en el listado porque SC-005 pide que el officer vea «qué capa» sin
    # abrir otra vista: con el badge de bloqueo a secas tendría el "qué" pero no el "por
    # dónde". Campo opcional ⇒ los consumidores previos a la 031 no se enteran.
    blocked_by_layer: Optional[str] = None

    class Config:
        from_attributes = True


class AuditLogListResponseSchema(BaseModel):
    total: int
    logs: List[AuditLogResponseSchema]


def _build_query(db, pii_detected, compliance_status, from_date, to_date, estado=None):
    query = db.query(AuditLog)
    if pii_detected is not None:
        query = query.filter(AuditLog.pii_detected == pii_detected)
    if compliance_status is not None:
        query = query.filter(AuditLog.compliance_status == compliance_status)
    if estado is not None:
        # Los dos valores son complementarios sobre el MISMO universo (tráfico, sin los
        # eslabones de licencia): `bloqueados` + `permitidos` = todo lo que el filtro
        # considera, sin filas que se caigan entre ambos ni que aparezcan en los dos.
        query = query.filter(AuditLog.model != MODELO_LICENCIA)
        if estado == EstadoFiltro.BLOQUEADOS:
            query = query.filter(AuditLog.compliance_status.like(BLOQUEADO_LIKE))
        else:
            query = query.filter(~AuditLog.compliance_status.like(BLOQUEADO_LIKE))
    if from_date:
        try:
            query = query.filter(AuditLog.timestamp >= datetime.fromisoformat(from_date))
        except ValueError:
            pass
    if to_date:
        try:
            query = query.filter(AuditLog.timestamp <= datetime.fromisoformat(to_date))
        except ValueError:
            pass
    return query


_ESTADO_DESC = ("Aísla el resultado del pedido: `bloqueados` = intentos impedidos "
                "(compliance_status con prefijo `blocked_`), `permitidos` = el resto. "
                "Excluye los eslabones de licencia (model='license'), que no son tráfico.")


@router.get("", response_model=AuditLogListResponseSchema)
def list_audit_logs(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    pii_detected: Optional[bool] = Query(None),
    compliance_status: Optional[str] = Query(None),
    estado: Optional[EstadoFiltro] = Query(None, description=_ESTADO_DESC),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = _build_query(db, pii_detected, compliance_status, from_date, to_date, estado)
    total = query.count()
    logs = query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit).all()
    return {"total": total, "logs": logs}


@router.get("/export")
def export_audit_logs_csv(
    pii_detected: Optional[bool] = Query(None),
    compliance_status: Optional[str] = Query(None),
    estado: Optional[EstadoFiltro] = Query(None, description=_ESTADO_DESC),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Streams audit logs as CSV. No prompt text or PII is included.

    Acepta los MISMOS filtros que el listado (incluido `estado`, spec 031): el officer que
    filtró «Bloqueados» en pantalla y exporta tiene que llevarse esas filas y no la tabla
    entera — un export que ignora el filtro visible es una trampa silenciosa.
    """
    query = _build_query(db, pii_detected, compliance_status, from_date, to_date, estado)
    # Limit export to 5000 rows to avoid memory exhaustion
    logs = query.order_by(AuditLog.timestamp.desc()).limit(5000).all()

    def generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "id", "timestamp", "model",
            "prompt_tokens", "completion_tokens", "cost_usd",
            "pii_detected", "compliance_status", "latency_ms",
            "tokens_saved_by_optimization", "guardian_events_count",
        ])
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate()

        for log in logs:
            writer.writerow([
                str(log.id),
                log.timestamp.isoformat() if log.timestamp else "",
                log.model,
                log.prompt_tokens,
                log.completion_tokens,
                float(log.cost_usd),
                log.pii_detected,
                log.compliance_status,
                log.latency_ms,
                log.tokens_saved_by_optimization,
                len(log.guardian_events or []),
            ])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()

    filename = f"audit_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
