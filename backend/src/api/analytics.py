import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
import httpx

from ..database import get_db
from ..auth.rbac import require_authenticated
from ..auth.session import get_current_user
from ..models.tenant import DEFAULT_TENANT_ID
from ..models.user import User
from ..services.governance_catalog import (
    GOVERNANCE_LAYERS,
    LAYER_KEYS,
    STATUS_APPLIED,
    VERDICT_ALLOW,
)
# El copy legible de cada capa vive junto a la otra superficie que el backend renderiza
# (la vitrina de /gw/monitor). Se importa en vez de copiarse: dos tablas de nombres para
# las mismas capas se desincronizan, y el nombre que ve el Admin en el panel tiene que ser
# el mismo que ve en el monitor.
from .monitor import LAYER_LABELS

router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"],
    dependencies=[Depends(require_authenticated())],
)
logger = logging.getLogger("basa-secure-gateway.analytics")

# Las filas de licencia (spec 021) son EVIDENCIA de lifecycle, no tráfico gobernado: mismo
# corte que compliance.py:361 y reports.py:139. Contarlas acá era el segundo defecto del
# agregado viejo — con la query anterior, cada transición de licencia entraba como una
# "activación de guardián".
_LICENSE_MODEL = "license"

_ENGINE_URL = os.getenv("BASA_ENGINE_API_BASE", "http://engine:4000")
_ENGINE_KEY = os.getenv("BASA_ENGINE_MASTER_KEY", "")


def _range_dates(range_param: str) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    if range_param == "day":
        from_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif range_param == "month":
        from_dt = now - timedelta(days=30)
    else:  # default: week
        from_dt = now - timedelta(days=7)
    return from_dt, now


# ── Actuaciones por capa de gobernanza (spec 027, T031) ───────────────────────────
#
# Qué reemplaza y por qué. El agregado anterior leía ``guardian_events`` cruzando
# ``ev->>'guardrail_name'`` contra ``guardians.engine_guardrail_name``: **ningún productor
# escribe esa clave** (grep: cero ocurrencias), así que el LEFT JOIN nunca ataba y todo
# caía en el ``COALESCE`` genérico. Encima no filtraba por ``model``, de modo que cada fila
# de licencia (``model='license'``, spec 021) —que lleva su eslabón de hash-chain en
# ``guardian_events``— contaba como "activación de guardián". El panel mostraba, con
# nombre de guardián, un número que no medía protección: exactamente la clase de mentira
# que la 027 existe para borrar.
#
# La fuente nueva es ``audit_logs.applied_layers`` (data-model §3), que sí tiene productor
# y esquema: se cuentan los elementos con ``status='applied'`` y ``decision`` distinta de
# ``allow`` — la capa **corrió y actuó** (enmascaró, marcó o bloqueó). Contar los ``allow``
# inflaría el número con cada pedido inocuo; contar los ``skipped`` /
# ``requires_credential`` lo inflaría con capas que ni siquiera corrieron.
#
# ``guardian_events`` queda congelado como legado (D6): no se le agregan lectores.
_LAYER_ACTIVATIONS_SQL = text("""
    SELECT
        el->>'layer_code' AS layer_code,
        COUNT(*)          AS activations
    FROM audit_logs al
    -- El CASE es la guarda de tipo: `jsonb_array_elements` revienta con un objeto o un
    -- 'null'::jsonb, y filtrar en el WHERE no alcanza porque el LATERAL se evalúa antes.
    -- Con NULL (fila pre-027) el '[]' no produce filas y el pedido sale del agregado sin
    -- contarse como cero-protección: eso lo informa el bloque de cobertura de abajo.
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(al.applied_layers) = 'array'
             THEN al.applied_layers ELSE '[]'::jsonb END
    ) AS el
    WHERE al.tenant_id = :tenant_id
      AND al.timestamp >= :from_dt AND al.timestamp <= :to_dt
      AND al.model <> :license_model
      -- Un elemento sin `layer_code` no es atribuible a nada: agruparlo daría una barra
      -- sin nombre en el panel. Se descarta acá y no se disfraza de "genérico" —el
      -- COALESCE genérico del agregado viejo es justo lo que hacía el número inútil.
      AND el->>'layer_code' IS NOT NULL
      AND el->>'status' = :status_applied
      AND el->>'decision' IS NOT NULL
      AND el->>'decision' <> :verdict_allow
    GROUP BY 1
    ORDER BY 2 DESC, 1
""")

# Cobertura de la atribución: "no hay registro" ≠ "ninguna capa actuó". Sin este corte, las
# filas históricas (``applied_layers`` NULL, anteriores a la 027) se leerían como pedidos
# que nadie protegió, y el panel volvería a afirmar más de lo que sabe.
_LAYER_COVERAGE_SQL = text("""
    SELECT
        COUNT(*) FILTER (WHERE jsonb_typeof(applied_layers) = 'array')              AS con_registro,
        COUNT(*) FILTER (WHERE jsonb_typeof(applied_layers) IS DISTINCT FROM 'array') AS sin_registro
    FROM audit_logs
    WHERE tenant_id = :tenant_id
      AND timestamp >= :from_dt AND timestamp <= :to_dt
      AND model <> :license_model
""")


def _layer_activations(db: Session, *, tenant_id, from_dt: datetime, to_dt: datetime) -> dict:
    """Cuántas veces actuó cada capa en el período, por tenant.

    Unidad: **una actuación por pedido y capa**, no la suma de los ``count``. El ``count``
    del elemento cuenta ocurrencias dentro de un pedido (entidades, secretos); sumarlo acá
    mezclaría dos unidades y un solo pedido con 40 entidades se leería como 40 incidentes.

    El nombre visible sale del **registry** (``to_public_dict()['layer_key']`` → copy del
    producto) y jamás de ``guardians.name``: ese nombre es editable por el cliente y
    white-label, así que un rename reescribiría la lectura de la analítica histórica
    (data-model §3.1). Un ``layer_code`` que no esté en el registry —productor más nuevo
    que este backend— se muestra por su código: es metadata segura (Constitución VII) y
    ocultarlo falsearía el total.

    Degradación honesta: si la query falla, se devuelven contadores vacíos **y**
    ``atribucion_disponible=False``, para que "no pude medir" no se lea como "cero
    incidentes".
    """
    # El alcance (tenant + ventana + exclusión de licencias) es el MISMO en las dos
    # queries: si divergiera, la cobertura describiría un universo distinto del que se
    # cuenta y los dos números dejarían de ser comparables.
    alcance = {
        "tenant_id": str(tenant_id),
        "from_dt": from_dt,
        "to_dt": to_dt,
        "license_model": _LICENSE_MODEL,
    }
    try:
        rows = db.execute(_LAYER_ACTIVATIONS_SQL, {
            **alcance,
            "status_applied": STATUS_APPLIED,
            "verdict_allow": VERDICT_ALLOW,
        }).fetchall()
        cobertura = db.execute(_LAYER_COVERAGE_SQL, alcance).fetchone()
    except Exception as exc:  # noqa: BLE001 — el panel no cae por un agregado
        logger.warning("agregado de capas de gobernanza falló: %s", exc)
        return {
            "total": 0,
            "by_guardian": {},
            "by_layer": [],
            "atribucion_disponible": False,
            "requests_con_atribucion": 0,
            "requests_sin_atribucion": 0,
        }

    by_layer = []
    for row in rows:
        code = row.layer_code
        capa = GOVERNANCE_LAYERS.get(code)
        # `to_public_dict` y no el dataclass crudo: `guardian_types` lleva nombres de
        # proveedor externo en claro y no puede salir en una respuesta HTTP (Const. VII).
        code_publico = capa.to_public_dict()["layer_key"] if capa else code
        by_layer.append({
            "layer_code": code_publico,
            "label": LAYER_LABELS.get(code_publico, code_publico),
            "activations": int(row.activations or 0),
        })
    # Orden canónico del registry como desempate, para que dos períodos con los mismos
    # números no barajen las barras del panel.
    orden = {key: i for i, key in enumerate(LAYER_KEYS)}
    by_layer.sort(key=lambda r: (-r["activations"], orden.get(r["layer_code"], len(orden)),
                                 r["layer_code"]))
    return {
        "total": sum(r["activations"] for r in by_layer),
        # Clave legada que consume el panel (DashboardPage): {nombre visible: contador}.
        "by_guardian": {r["label"]: r["activations"] for r in by_layer},
        "by_layer": by_layer,
        "atribucion_disponible": True,
        "requests_con_atribucion": int(getattr(cobertura, "con_registro", 0) or 0),
        "requests_sin_atribucion": int(getattr(cobertura, "sin_registro", 0) or 0),
    }


@router.get("/summary")
def get_analytics_summary(
    range: str = Query("week", pattern="^(day|week|month)$"),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    from_dt, to_dt = _range_dates(range)
    # Tenant del usuario autenticado — mismo patrón que governance.py:_resolve_target_tenant.
    # El agregado de capas SIEMPRE filtra por tenant (Constitución III): decide qué se le
    # muestra al Admin sobre su propia protección, y mezclar organizaciones ahí es el bug
    # que `governance_resolution` documenta y no replica. Los agregados de costo/tokens de
    # este endpoint siguen sin filtro por herencia: cambiarlos es su propio trabajo.
    tenant = getattr(user, "tenant_id", None) or DEFAULT_TENANT_ID

    # Core aggregation query
    core_sql = text("""
        SELECT
            COUNT(*)                                              AS total_requests,
            COALESCE(SUM(cost_usd), 0)                          AS total_cost_usd,
            COALESCE(SUM(prompt_tokens), 0)                     AS total_prompt_tokens,
            COALESCE(SUM(completion_tokens), 0)                 AS total_completion_tokens,
            COALESCE(SUM(tokens_saved_by_optimization), 0)      AS tokens_saved,
            COALESCE(SUM(cost_saved_usd), 0)                    AS cost_saved_usd,
            COALESCE(ROUND(AVG(latency_ms)), 0)                 AS avg_latency_ms,
            COUNT(*) FILTER (WHERE pii_detected = TRUE)         AS pii_incidents,
            COUNT(*) FILTER (WHERE compliance_status = 'allowed' OR compliance_status = 'passed') AS compliance_passed,
            COUNT(*) FILTER (WHERE compliance_status = 'blocked_prohibited' OR compliance_status = 'blocked_by_policy') AS compliance_blocked,
            COUNT(*) FILTER (WHERE compression_reversed = TRUE) AS compression_reversions
        FROM audit_logs
        WHERE timestamp >= :from_dt AND timestamp <= :to_dt
    """)
    core_row = db.execute(core_sql, {"from_dt": from_dt, "to_dt": to_dt}).fetchone()

    # Per-model breakdown (spec 012 US6 — ratio de compresión + ahorro por modelo)
    models_sql = text("""
        SELECT
            model,
            COUNT(*)           AS requests,
            COALESCE(SUM(cost_usd), 0) AS cost_usd,
            COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
            COALESCE(SUM(tokens_saved_by_optimization), 0) AS tokens_saved,
            COALESCE(SUM(cost_saved_usd), 0) AS cost_saved_usd,
            COUNT(*) FILTER (WHERE compression_reversed = TRUE) AS reversions
        FROM audit_logs
        WHERE timestamp >= :from_dt AND timestamp <= :to_dt
        GROUP BY model
        ORDER BY requests DESC
        LIMIT 10
    """)
    model_rows = db.execute(models_sql, {"from_dt": from_dt, "to_dt": to_dt}).fetchall()

    # Actuaciones por capa de gobernanza (spec 027, T031) — ver _layer_activations.
    activations = _layer_activations(db, tenant_id=tenant, from_dt=from_dt, to_dt=to_dt)

    return {
        "range": range,
        "from_date": from_dt.isoformat(),
        "to_date": to_dt.isoformat(),
        "total_requests": core_row.total_requests or 0,
        "total_cost_usd": float(core_row.total_cost_usd or 0),
        "total_prompt_tokens": core_row.total_prompt_tokens or 0,
        "total_completion_tokens": core_row.total_completion_tokens or 0,
        "tokens_saved_by_optimization": core_row.tokens_saved or 0,
        "cost_saved_usd": float(core_row.cost_saved_usd or 0),
        "avg_latency_ms": int(core_row.avg_latency_ms or 0),
        "pii_incidents": core_row.pii_incidents or 0,
        "compliance_passed": core_row.compliance_passed or 0,
        "compliance_blocked": core_row.compliance_blocked or 0,
        "compression_reversions": core_row.compression_reversions or 0,
        "models": [
            {
                "model": r.model,
                "requests": r.requests,
                "cost_usd": float(r.cost_usd or 0),
                # spec 012 US6 — ratio de compresión + ahorro por modelo
                "prompt_tokens": int(r.prompt_tokens or 0),
                "tokens_saved": int(r.tokens_saved or 0),
                "cost_saved_usd": float(r.cost_saved_usd or 0),
                "compression_ratio": round(
                    (r.tokens_saved or 0) / r.prompt_tokens, 4
                ) if (r.prompt_tokens or 0) > 0 else 0.0,
                "reversions": int(r.reversions or 0),
            }
            for r in model_rows
        ],
        # Nombre legado de la clave (lo consume el panel); la fuente ya no son los
        # "guardianes" sino las capas que ACTUARON sobre el tráfico (spec 027, FR-009).
        # `by_guardian` se mantiene con el mismo shape {nombre: contador} para no romper
        # DashboardPage; `by_layer` es la lista anclada al código de capa —identidad
        # estable— y los dos contadores de cobertura distinguen "sin registro" de "ninguna
        # capa actuó".
        "guardian_activations": {
            "total": activations["total"],
            "by_guardian": activations["by_guardian"],
            "by_layer": activations["by_layer"],
            "atribucion_disponible": activations["atribucion_disponible"],
            "requests_con_atribucion": activations["requests_con_atribucion"],
            "requests_sin_atribucion": activations["requests_sin_atribucion"],
        },
    }


@router.get("/engine-status")
async def get_engine_status():
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(
                f"{_ENGINE_URL}/health/readiness",
                headers={"Authorization": f"Bearer {_ENGINE_KEY}"},
            )
            if r.status_code < 400:
                return {"status": "online", "checked_at": checked_at}
    except Exception:
        pass
    return {"status": "offline", "checked_at": checked_at}
