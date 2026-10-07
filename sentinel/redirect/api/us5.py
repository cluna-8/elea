"""Kits, prueba de fidelidad y comparador de costos (US5; contracts/admin-api.md; T110–T112).

Mismo router base (`/redirect`) y mismos helpers que `admin.py` (sesión con `tenant_context`,
auditoría de configuración, roles de FR-014b): lo único nuevo es la lógica de cada ruta, que vive
en `kits.py`, `fidelity.py` y `costs.py` (funciones puras, con tests propios).

- `GET  /redirect/kits/{tool}?scope=&include_credential=` — tenant_admin. Con `include_credential`
  se emite una llave NUEVA del alcance (límite: los ids públicos de la herramienta) y la emisión
  queda en la auditoría de configuración (`kit_key`), sin la llave.
- `POST /redirect/fidelity-runs` · `GET /redirect/fidelity-runs[/{id}]` — tenant_admin lanza;
  tenant_admin y compliance_officer leen.
- `GET  /redirect/cost-comparison?from&to&scope` — tenant_admin y compliance_officer.

`scope` = `tenant` (default) · `user:<id>` · `group:<id>` · `connection:<id>`.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from src.auth.rbac import require_role

from .. import costs, fidelity, kits, residency
from .. import models as m
from ..scopes import RequestScope, applicable
from ..store import decrypt_credential, load_from_session
from . import admin
from .admin import READERS, TENANT_ADMIN, _audit, _db, _err, _store, _uuid

router = APIRouter()           # sin prefijo: se incluye dentro del router `/redirect` de admin

# Inyectables para tests (sin Postgres, sin motor, sin backend de llaves).
KEY_ISSUER = None        # async (db, user, *, tool, scope, models) -> (key_id, plain_key)
SENDER_FACTORY = None    # (destination, credential, *, face, tenant_id) -> fidelity.Sender
PRICE = None             # (model, prompt, completion) -> Decimal
AUDIT_SOURCE = None      # (db, tenant_id, start, end) -> list[dict]

MAX_AUDIT_ROWS = 100_000
DEFAULT_PERIOD_DAYS = 30
_RUNNING: set = set()    # (tenant, destino) con una prueba en curso


def _scope_param(value: Optional[str]) -> tuple:
    value = (value or "tenant").strip()
    if value == "tenant":
        return ("tenant", "*")
    kind, _, ident = value.partition(":")
    if kind not in ("user", "group", "connection") or not ident:
        _err(422, "scope: tenant, user:<id>, group:<id> o connection:<id>")
    try:
        uuid.UUID(ident)
    except ValueError:
        _err(422, "scope: el id del alcance debe ser un uuid")
    return (kind, ident)


def _request_scope(tenant_id, scope: tuple) -> RequestScope:
    kind, ident = scope
    return RequestScope(tenant_id=str(tenant_id), connection_id=ident if kind == "connection" else None,
                        user_id=ident if kind == "user" else None,
                        group_ids=(ident,) if kind == "group" else ())


def _price(model: str, prompt: int, completion: int) -> Decimal:
    if PRICE is not None:
        return PRICE(model, prompt, completion)
    from src.services.budget_service import BudgetService
    return BudgetService.calculate_cost(model, prompt, completion)       # la ÚNICA fuente de precios


def _gateway_url(request: Request) -> str:
    fixed = os.environ.get("REDIRECT_GATEWAY_URL", "").strip()
    if fixed:
        return fixed.rstrip("/")
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}/api/v1/gw"


# ── kits ──────────────────────────────────────────────────────────────────────────────────

def _scope_catalog(snap, tenant_id, scope: tuple) -> list:
    """Ids publicados que ve el alcance: el más específico gana por (cara, id)."""
    seen, out = set(), []
    for row in applicable(snap.published, _request_scope(tenant_id, scope)):
        key = (row.get("face"), row.get("public_id"))
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


async def _issue_key(db, user, *, tool: str, scope: tuple, models: list):
    if KEY_ISSUER is not None:
        return await KEY_ISSUER(db, user, tool=tool, scope=scope, models=models)
    from src.api import keys as keys_api
    kind, ident = scope
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    # Tope propio de la herramienta (`kits.KEY_LIMITS`); sin entrada, el default de la base. `generate_key` lo aplica
    # en la fila `api_keys` (la pasarela) y en la llave del motor.
    limits = {}
    if tool in kits.KEY_LIMITS:
        limits = dict(zip(("rpm_limit", "tpm_limit"), kits.KEY_LIMITS[tool]))
    created = await keys_api.generate_key(keys_api.KeyCreateSchema(
        name=f"Kit {tool}", user_id=ident if kind == "user" else None,
        group_id=ident if kind == "group" else None, models=models,
        tool_type=tool.replace("_", "-"), tool_label=f"kit-{tool}-{stamp}", **limits), db)
    return str(created.id), created.plain_key


@router.get("/kits/{tool}")
async def get_kit(tool: str, request: Request, scope: Optional[str] = None,
                  include_credential: bool = False, user=Depends(require_role(*TENANT_ADMIN))):
    if tool not in kits.TOOLS:
        _err(404, f"herramienta desconocida: {tool}")
    sc = _scope_param(scope)
    if include_credential and sc[0] == "connection":
        _err(422, "una conexión ya tiene su llave: pedí el kit sin credencial o por usuario/grupo/tenant")
    with _db(user) as db:
        snap = load_from_session(db, str(user.tenant_id), always=True)
    catalog = _scope_catalog(snap, user.tenant_id, sc)
    face = kits.TOOL_FACE[tool]
    mine = [p for p in catalog if p.get("face") == face]
    window = kits.min_context_window(mine, snap.rules, snap.destinations)
    brand = os.environ.get("BRAND_NAME", "Gateway")
    gateway = _gateway_url(request)

    def build(api_key=None):
        try:
            return kits.build_kit(tool, gateway_url=gateway, brand=brand, published=catalog,
                                  context_window=window, api_key=api_key)
        except kits.KitError as exc:
            _err(404 if exc.code == "no_models" else 422, exc.message)

    kit = build()                                   # valida antes de emitir ninguna llave
    key_id = None
    if include_credential:
        with _db(user) as db:
            key_id, plain = await _issue_key(db, user, tool=tool, scope=sc, models=kit["models"])
            _audit(db, user, entity="kit_key", entity_id=key_id, action="issue",
                   after={"tool": tool, "scope": f"{sc[0]}:{sc[1]}", "models": kit["models"]})
        kit = build(api_key=plain)
    version = hashlib.sha256(json.dumps([[p["face"], p["public_id"], p.get("family_tier"), p.get("label")]
                                         for p in mine] + [window], sort_keys=True).encode()).hexdigest()[:12]
    return {**kit, "scope": f"{sc[0]}:{sc[1]}", "catalog_version": version, "issued_key_id": key_id,
            "context_window": window, "generated_at": datetime.now(timezone.utc).isoformat()}


# ── prueba de fidelidad ─────────────────────────────────────────────────────────────────

class FidelityIn(BaseModel):
    destination_id: str
    tool: str
    face: Optional[str] = None
    tool_version: Optional[str] = Field(default=None, max_length=64)


_REPORT_FIELDS = ("tenant_id", "destination_id", "face", "tool", "tool_version", "corpus_version",
                  "verdict", "complete", "run_by", "run_at")


def _report_dict(r: m.RedirectFidelityReport) -> dict:
    out = admin._row(r, ("id",) + _REPORT_FIELDS)
    out.update(results=list(r.results or []), pass_rate=float(r.pass_rate), cost=float(r.cost))
    return out


def _previous(db, tenant_id, destination_id, tool, before_id) -> Optional[m.RedirectFidelityReport]:
    q = (db.query(m.RedirectFidelityReport)
         .filter(m.RedirectFidelityReport.tenant_id == tenant_id,
                 m.RedirectFidelityReport.destination_id == destination_id,
                 m.RedirectFidelityReport.tool == tool, m.RedirectFidelityReport.complete.is_(True),
                 m.RedirectFidelityReport.id != before_id)
         .order_by(m.RedirectFidelityReport.run_at.desc()))
    return q.first()


@router.post("/fidelity-runs", status_code=201)
async def run_fidelity(body: FidelityIn, user=Depends(require_role(*TENANT_ADMIN))):
    try:
        face = fidelity.face_for_tool(body.tool)
    except fidelity.FidelityRefused as exc:
        _err(404, exc.message)
    if body.face and body.face != face:
        _err(422, f"la herramienta {body.tool} usa la cara {face}")
    dest_uuid = _uuid(body.destination_id, "destino")
    tenant = str(user.tenant_id)
    with _db(user) as db:
        snap = load_from_session(db, tenant, always=True)
    scope = RequestScope(tenant_id=tenant, user_id=str(user.id) if getattr(user, "id", None) else None,
                         group_ids=((str(user.group_id),) if getattr(user, "group_id", None) else ()))
    try:
        posture = residency.effective_posture(snap.postures, scope, redirected=True,
                                              tenant_region=residency.resolve_profile(), regions=snap.regions,
                                              relaxations=snap.relaxations)
        dest = fidelity.ensure_allowed(str(dest_uuid), snap.destinations, offers=snap.offers,
                                       scope=scope, posture=posture)
    except ValueError as exc:
        _err(409, f"configuración inválida: {exc}")
    except fidelity.FidelityRefused as exc:
        _err(404 if exc.code == "not_found" else 403, exc.message)
    key = (tenant, str(dest_uuid))
    if key in _RUNNING:
        _err(409, "ya hay una prueba de fidelidad en curso para este destino")
    _RUNNING.add(key)
    try:
        sender = (SENDER_FACTORY or fidelity.engine_sender)(
            dest, decrypt_credential(snap.credentials.get(str(dest_uuid))), face=face, tenant_id=tenant)
        report = await fidelity.run(dest, face, body.tool, send=sender, price=_price,
                                    budget=fidelity.Budget.from_env(), tenant_id=tenant,
                                    tool_version=body.tool_version, run_by=str(getattr(user, "id", "") or "") or None)
    finally:
        _RUNNING.discard(key)
    with _db(user) as db:
        row = m.RedirectFidelityReport(
            tenant_id=user.tenant_id, destination_id=dest_uuid, face=face, tool=body.tool,
            tool_version=body.tool_version, corpus_version=report["corpus_version"],
            results=report["results"], verdict=report["verdict"], complete=report["complete"],
            pass_rate=report["pass_rate"], cost=report["cost"], run_by=getattr(user, "id", None))
        db.add(row)
        db.flush()
        db.refresh(row)
        prev = _previous(db, user.tenant_id, dest_uuid, body.tool, row.id)
        out = _report_dict(row)
        out["regressions"] = fidelity.regressions(prev.results, report["results"]) if prev is not None else []
        out["compared_with"] = ({"id": str(prev.id), "tool_version": prev.tool_version,
                                 "run_at": prev.run_at.isoformat()} if prev is not None else None)
    return out


@router.get("/fidelity-runs")
def list_fidelity(destination_id: Optional[str] = None, tool: Optional[str] = None, limit: int = 20,
                  user=Depends(require_role(*READERS))):
    with _db(user) as db:
        q = db.query(m.RedirectFidelityReport).filter(m.RedirectFidelityReport.tenant_id == user.tenant_id)
        if destination_id:
            q = q.filter(m.RedirectFidelityReport.destination_id == _uuid(destination_id, "destino"))
        if tool:
            q = q.filter(m.RedirectFidelityReport.tool == tool)
        rows = q.order_by(m.RedirectFidelityReport.run_at.desc()).limit(max(1, min(limit, 100))).all()
        return {"data": [_report_dict(r) for r in rows]}


@router.get("/fidelity-runs/{run_id}")
def get_fidelity(run_id: str, user=Depends(require_role(*READERS))):
    with _db(user) as db:
        row = db.get(m.RedirectFidelityReport, _uuid(run_id, "informe"))
        if row is None or row.tenant_id != user.tenant_id:
            _err(404, "informe inexistente")
        return _report_dict(row)


# ── comparador de costos ────────────────────────────────────────────────────────────────

def _load_audit(db, tenant_id, start: datetime, end: datetime) -> list:
    if AUDIT_SOURCE is not None:
        return AUDIT_SOURCE(db, tenant_id, start, end)
    from src.models.audit import AuditLog
    q = (db.query(AuditLog.api_key_id, AuditLog.user_id, AuditLog.user_group_id, AuditLog.prompt_tokens,
                  AuditLog.completion_tokens, AuditLog.cost_usd, AuditLog.routing_decision)
         .filter(AuditLog.tenant_id == tenant_id, AuditLog.timestamp >= start, AuditLog.timestamp < end,
                 AuditLog.routing_decision["extensions"].has_key("redirect"))        # noqa: W601 — JSONB
         .order_by(AuditLog.timestamp.desc()).limit(MAX_AUDIT_ROWS))
    return [dict(zip(("api_key_id", "user_id", "user_group_id", "prompt_tokens", "completion_tokens",
                      "cost_usd", "routing_decision"), r)) for r in q]


def _period(value: Optional[str], default: datetime, what: str) -> datetime:
    if not value:
        return default
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _err(422, f"{what}: fecha ISO 8601")
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@router.get("/cost-comparison")
def cost_comparison(from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
                    scope: Optional[str] = None, user=Depends(require_role(*READERS))):
    now = datetime.now(timezone.utc)
    end = _period(to, now, "to")
    start = _period(from_, end - timedelta(days=DEFAULT_PERIOD_DAYS), "from")
    if start >= end:
        _err(422, "from debe ser anterior a to")
    sc = _scope_param(scope)
    with _db(user) as db:
        snap = load_from_session(db, str(user.tenant_id), always=True)
        rows = _load_audit(db, user.tenant_id, start.replace(tzinfo=None), end.replace(tzinfo=None))
    out = costs.compare(rows, published=snap.published, destinations=snap.destinations, price=_price, scope=sc)
    out.update({"from": start.isoformat(), "to": end.isoformat(), "scope": f"{sc[0]}:{sc[1]}",
                "truncated": len(rows) >= MAX_AUDIT_ROWS})
    return out
