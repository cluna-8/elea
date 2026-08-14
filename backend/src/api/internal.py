"""Plano interno: resolución de identidad de una Connection para el MOTOR.

Por qué existe (2026-07-27, víspera del install de la Cámara): `custom_auth` del motor
resolvía la identidad consultando `api_keys`/`users`/`groups`/`tenants` con el prisma
client del propio motor. Desde que el motor tiene base PROPIA (`basa_engine`, para que su
migrador Prisma no dropee las tablas del producto como "drift" — ensayo 2026-07-22) esas
tablas quedaron fuera de su alcance: **todo byok devolvía 401** con
`relation "api_keys" does not exist`. El ensayo no lo detectaba porque nunca ejercitó byok.

Por qué HTTP y no una segunda conexión SQL desde el motor: la imagen upstream del motor no
trae ningún driver de Postgres y tampoco trae `pip` ni `uv` (está construida con uv y sin
instalador), así que agregar `asyncpg` obligaba a derivar la imagen. HTTP no cuesta nada:
`httpx` ya viene en la imagen. Y además pone el SQL donde vive el esquema que consulta —
el backend es el dueño de estas tablas, el motor sólo necesita el resultado.

Seguridad: el ingress niega /api/v1/internal/* con 404 (Caddyfile.ingress), así que esto
sólo se alcanza por la red de compose. Encima se exige el secreto compartido que ambos
servicios YA tienen (`LITELLM_MASTER_KEY`) — no hay un secreto nuevo que provisionar.
"""
import hmac
import json
import logging
import os
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.tenant import DEFAULT_TENANT_ID
from ..services.budget_service import BudgetService
# Vocabulario cerrado de la columna `model` (018, capa B). Se REUSA la del gateway en vez de
# copiar el literal: dos definiciones del mismo centinela son dos oportunidades de que una se
# quede vieja, y este es un valor cuya igualdad exacta sostiene la exclusión de la cadena de
# licencias en media docena de lectores. El porqué completo vive en su bloque de doctrina.
from .gateway import MODELO_CADENA_USURPADA, sanear_modelo_declarado

logger = logging.getLogger("basa-secure-gateway.internal")

router = APIRouter(prefix="/internal", tags=["Internal"], include_in_schema=False)

# Mismo SQL que vivía en litellm/extensions/custom_auth.py (_IDENTITY_SQL). Se mueve acá
# porque consulta tablas de ESTA base: una sola copia, del lado del dueño del esquema.
_IDENTITY_SQL = text("""
SELECT k.id::text AS key_id, k.tenant_id::text AS tenant_id, k.user_id::text AS user_id,
       k.group_id::text AS group_id, k.tool_type, k.upstream_mode, k.redact_enabled,
       k.compression_mode AS key_compression_mode, k.allowed_models, k.allowed_tools,
       k.rpm_limit, k.tpm_limit, k.is_active, k.expires_at::text AS expires_at,
       u.username, u.role, u.client_type, u.display_label,
       g.compression_mode AS group_compression_mode,
       t.slug AS tenant_slug, t.compression_mode AS tenant_compression_mode,
       (SELECT sp.entity_configs FROM security_policies sp
         WHERE sp.tenant_id = k.tenant_id AND sp.is_active = true LIMIT 1) AS entity_configs,
       -- issue #104: `ORDER BY gd.created_at, gd.id` en las TRES subconsultas de `pii_masking`.
       -- Sin él, con dos guardianes `pii_masking` activos cada subconsulta podía elegir una
       -- fila distinta (custom_names de una, nlp_fail_mode de otra) y la identidad resuelta
       -- quedaba internamente incoherente, además de diferir del backend y de `/health`. Es el
       -- MISMO desempate determinista que el LATERAL del presupuesto de abajo ya usa (#76).
       (SELECT gd.config->'custom_names' FROM guardians gd
         WHERE gd.tenant_id = k.tenant_id AND gd.guardian_type = 'pii_masking'
           AND gd.is_active = true ORDER BY gd.created_at, gd.id LIMIT 1) AS custom_names,
       (SELECT gd.config->'custom_entities' FROM guardians gd
         WHERE gd.tenant_id = k.tenant_id AND gd.guardian_type = 'pii_masking'
           AND gd.is_active = true ORDER BY gd.created_at, gd.id LIMIT 1) AS custom_entities,
       -- issue #63: qué hacer si el analyzer NLP no responde (`block` | `degrade`).
       -- ⚠️ ESPEJO de litellm/extensions/custom_auth.py (_IDENTITY_SQL): si una copia lo trae
       -- y la otra no, la postura del admin depende de qué env está cableada y el bug del #63
       -- (degradar sin que nadie lo decida) renace por el camino que no lo lleva. El ORDER BY
       -- del #104 también es espejo: las dos copias eligen la misma fila más antigua.
       -- `->>` y no `->`: el consumidor compara contra un str del vocabulario cerrado, y un
       -- valor JSON entrecomillado ("degrade" con comillas) no matchearía nunca.
       (SELECT gd.config->>'nlp_fail_mode' FROM guardians gd
         WHERE gd.tenant_id = k.tenant_id AND gd.guardian_type = 'pii_masking'
           AND gd.is_active = true ORDER BY gd.created_at, gd.id LIMIT 1) AS nlp_fail_mode,
       bud.max_spend_usd AS max_budget_usd,
       bud.current_spend_usd AS spend_usd
FROM api_keys k
LEFT JOIN users u ON u.id = k.user_id
LEFT JOIN groups g ON g.id = k.group_id
LEFT JOIN tenants t ON t.id = k.tenant_id
-- Presupuesto APLICABLE a esta Connection (issue #76, decisión A de JF = rechazo duro):
-- el motor no puede frenar el gasto de lo que no ve, y hasta acá la identidad no llevaba
-- ni el techo ni el gasto, así que TODO el tráfico byok gastaba sin límite mientras el
-- Playground sí frenaba. Se elige UNA fila —la misma que `BudgetService.update_budget`
-- cargaría— y no las dos capas: el contrato del plano interno es un par escalar
-- (max_budget_usd, spend_usd) y un par no puede expresar el OR dual-capa de
-- `has_sufficient_budget`. Orden: personal del dueño de la llave primero, el del grupo de
-- respaldo — el mismo que arma `get_applicable_budgets` (budget_service.py:105), que apila
-- el personal antes que el del grupo (budget_service.py:112-118). El grupo sale de la llave
-- o, si la llave no lo fija, del User (mismo fallback que el servicio). El desempate por
-- created_at/id es determinismo puro: `get_personal_budget` usa `.first()` sin ORDER BY, y
-- con dos presupuestos del mismo dueño los dos planos podrían elegir filas distintas.
-- ⚠️ ESTE BLOQUE ES ESPEJO del de litellm/extensions/custom_auth.py (_IDENTITY_SQL, camino
-- de desarrollo con base compartida): los dos tienen que resolver el MISMO presupuesto o el
-- corte de #76 dependería de qué env está cableada. Se cambian juntos.
LEFT JOIN LATERAL (
    SELECT b.max_spend_usd, b.current_spend_usd
      FROM budgets b
     WHERE (b.user_id IS NOT NULL AND b.user_id = k.user_id)
        OR (b.group_id IS NOT NULL AND b.group_id = COALESCE(k.group_id, u.group_id))
     ORDER BY CASE WHEN b.user_id = k.user_id THEN 0 ELSE 1 END, b.created_at, b.id
     LIMIT 1
) bud ON TRUE
WHERE k.key_hash = :key_hash
""")


def _require_internal_secret(x_basa_internal: str = Header(default="")) -> None:
    """Fail-closed: si el secreto no está configurado en el backend, NADIE pasa. Un
    default vacío que aceptara la cabecera vacía convertiría esto en un endpoint abierto."""
    expected = os.environ.get("LITELLM_MASTER_KEY", "")
    if not expected or not hmac.compare_digest(x_basa_internal, expected):
        # Mismo 404 que emite el ingress: desde fuera, este endpoint no existe.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


def _a_float(valor) -> Optional[float]:
    """`Numeric` de Postgres llega como `Decimal`; el contrato con el motor habla en
    floats de JSON. `None` se preserva (significa "no hay presupuesto"), no se colapsa a 0:
    un techo de 0.0 querría decir "sin crédito" y frenaría a un cliente que no tiene
    presupuesto configurado."""
    if valor is None:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError, InvalidOperation):
        return None


@router.get("/identity", dependencies=[Depends(_require_internal_secret)])
def resolve_identity(key_hash: str = Query(min_length=64, max_length=64),
                     db: Session = Depends(get_db)):
    """Devuelve la fila de identidad de una Connection, o `null` si no existe.

    `null` (200) y no 404: para el motor "no hay tal key" es una respuesta legítima que
    debe traducirse a 401 del lado del cliente, distinta de "no pude preguntar" (que es
    fail-closed y sí es un error de transporte)."""
    row = db.execute(_IDENTITY_SQL, {"key_hash": key_hash}).mappings().first()
    if row is None:
        return {"row": None}

    datos = dict(row)
    # Presupuesto (issue #76). Nombres EXACTOS del contrato con el motor:
    # `max_budget_usd` (float|None) y `spend_usd` (float, SIEMPRE presente). Sin
    # presupuesto configurado, el techo se OMITE —no viaja como 0— y el gasto vale 0.0:
    # así el consumidor distingue "sin límite configurado" de "límite agotado".
    maximo = _a_float(datos.pop("max_budget_usd", None))
    gasto = _a_float(datos.pop("spend_usd", None))
    if maximo is not None:
        datos["max_budget_usd"] = maximo
    datos["spend_usd"] = gasto if gasto is not None else 0.0

    # Las columnas NULL se ELIMINAN del JSON, no viajan como `null`. Es el MISMO filtro que
    # hoy aplica el consumidor al recibir (custom_auth.py:238) y que existe porque todo
    # el motor lee con `identity.get(campo, DEFAULT)`: con la clave presente valiendo None,
    # `.get("redact_enabled", True)` devuelve None (falsy) y el motor deja de enmascarar
    # (verificado en vivo el 2026-07-27). Se aplica también acá, del lado del emisor, para
    # que la garantía sea del contrato y no de la disciplina de cada consumidor.
    return {"row": {k: v for k, v in datos.items() if v is not None}}


# ── Auditoría durable del plano MOTOR ────────────────────────────────────────────────
# Mismo motivo que /identity: `audit_logs` (el registro canónico) vive en ESTA base, y
# desde la separación de bases el INSERT del motor fallaba en cada pedido byok con
# "relation audit_logs does not exist" — tragado como no-fatal. Resultado: el tráfico de
# HERRAMIENTAS (la superficie principal del producto) no dejaba rastro durable, sólo la
# vitrina efímera de Redis. Para un producto cuya promesa es "interceptar y REGISTRAR
# todo", ese era el gap más caro del core.

_INSERT_AUDIT_SQL = text("""
INSERT INTO audit_logs (
    id, tenant_id, timestamp, user_id, api_key_id, model,
    prompt_tokens, completion_tokens, cost_usd, pii_detected, masked_entities,
    compliance_status, latency_ms, user_group_id, applied_layers, blocked_by_layer
) VALUES (
    gen_random_uuid(), CAST(:tenant_id AS uuid), NOW(), CAST(:user_id AS uuid),
    CAST(:api_key_id AS uuid), :model,
    :prompt_tokens, :completion_tokens, :cost_usd, :pii_detected,
    CAST(:masked_entities AS jsonb),
    :compliance_status, :latency_ms, CAST(:user_group_id AS uuid),
    CAST(:applied_layers AS jsonb), :blocked_by_layer
)
""")


class AuditEntry(BaseModel):
    """Fila de auditoría que emite el motor. El emisor está autenticado con el secreto
    compartido (misma confianza que cuando insertaba directo en la base), pero el saneo
    por vocabulario se mantiene igual (hallazgo A3 de la 027): la procedencia confiable
    evita la falsificación; el saneo evita que texto libre termine en el JSONB (C1).
    Son dos defensas distintas y hacen falta las dos.

    Fila de BLOQUEO (spec 031, contrato §Fila de bloqueo): el modelo ya la soporta sin
    campos nuevos — `compliance_status` (convención D1: prefijo `blocked_`, filtro canónico
    `LIKE 'blocked%'`) y `blocked_by_layer` (layer_key del registry 027) existen desde la
    027 y son opcionales, así que el payload de ÉXITO de `basa_audit_logger` sigue
    insertando exactamente igual. Lo único que se relaja acá es `tenant_id` (ver abajo)."""
    # Antes obligatorio. Un bloqueo sin identidad resoluble (llave master, o el edge case
    # "llave inválida" de la spec) llegaría sin tenant y el 422 de Pydantic haría
    # DESAPARECER la fila del intento — exactamente el agujero que la 031 paga. La columna
    # es NOT NULL, así que la ausencia se resuelve al tenant por defecto (mismo fallback
    # que ya aplica el emisor en basa_audit_logger.py:152), y el intento queda registrado
    # con atribución anónima en lugar de perderse.
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    api_key_id: Optional[str] = None
    model: str = "desconocido"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    pii_detected: bool = False
    masked_entities: list = []
    compliance_status: str = "passed"
    latency_ms: int = 0
    user_group_id: Optional[str] = None
    applied_layers: Optional[list] = None
    blocked_by_layer: Optional[str] = None


def _entidades_saneadas(items: list) -> list:
    """Vocabulario cerrado: sólo {type, count}, con type acotado y count entero. Todo lo
    demás se descarta — jamás texto del pedido en el registro durable."""
    limpias = []
    for it in items[:50]:
        if not isinstance(it, dict):
            continue
        tipo, cuenta = it.get("type"), it.get("count")
        if isinstance(tipo, str) and 0 < len(tipo) <= 64 and isinstance(cuenta, int):
            limpias.append({"type": tipo, "count": cuenta})
    return limpias


def _acumular_gasto(db: Session, entry: "AuditEntry") -> None:
    """Descuenta el pedido del presupuesto aplicable (issue #76, mitad "contador").

    El plano chat ya lo hace en su camino feliz (chat.py:1353) con el MISMO servicio; el
    plano motor no lo hacía por ningún lado, así que el gasto byok —la superficie principal
    del producto— nunca movía el contador: el panel de costes mostraba solo el Playground.
    Se reusa `BudgetService.update_budget` (nada de SQL duplicado): así la precedencia
    personal→grupo, el reset y el conteo de tokens son los mismos en los dos planos.

    El coste que se acumula es el del EVENTO, no el de la tabla local de precios: lo
    calculó el motor contra la respuesta real del proveedor. Que el presupuesto y la suma
    de `cost_usd` de `audit_logs` cierren es un requisito de auditoría — si acá
    recalculáramos con `MODEL_PRICING`, la fila diría una cosa y el contador otra.
    """
    if not (entry.cost_usd or entry.prompt_tokens or entry.completion_tokens):
        return  # fila de bloqueo (0/0/0): no hubo consumo que cargarle a nadie
    BudgetService.update_budget(
        db=db,
        user_id=entry.user_id,
        group_id=entry.user_group_id,
        prompt_tokens=entry.prompt_tokens,
        completion_tokens=entry.completion_tokens,
        model=entry.model,
        override_cost=Decimal(str(entry.cost_usd or 0)),
    )


@router.post("/audit", dependencies=[Depends(_require_internal_secret)])
def record_audit(entry: AuditEntry, db: Session = Depends(get_db)):
    entidades = _entidades_saneadas(entry.masked_entities)
    # El `model` que llega acá nació como texto del cliente al otro lado del motor, y `license`
    # es el literal reservado de la cadena de licencias (021): quien lo escriba se vuelve
    # inmortal para la retención, invisible para la vitrina y capaz de envenenar `verify_chain`.
    # Misma defensa que en la puerta, misma función — el porqué completo, con los lectores y el
    # precedente de `api/inspect.py`, está en `gateway.sanear_modelo_declarado`.
    #
    # Diferencia deliberada con `/gw`: acá se sanea y **nada más, nunca se rechaza**. Esta fila
    # llega del motor DESPUÉS del hecho —el pedido ya se sirvió o ya se bloqueó, la política ya
    # dictaminó—, así que un 4xx no impide nada: tira auditoría durable ya generada, que es
    # justo el agujero que la 031 cerró acá mismo (`tenant_id` dejó de ser obligatorio para que
    # un bloqueo sin identidad resoluble no desapareciera por un 422) y el que la 018 protege.
    # El rechazo tiene sentido en la puerta, donde todavía hay un pedido que rechazar.
    modelo = sanear_modelo_declarado(entry.model)
    if modelo != entry.model:
        logger.warning(
            "[basa-internal] el emisor declaró el literal reservado de la cadena de licencias "
            "como modelo; la fila se registra con el centinela %s (tenant=%s user=%s)",
            MODELO_CADENA_USURPADA, entry.tenant_id, entry.user_id)
    db.execute(_INSERT_AUDIT_SQL, {
        "tenant_id": entry.tenant_id or str(DEFAULT_TENANT_ID),
        "user_id": entry.user_id,
        "api_key_id": entry.api_key_id,
        "model": modelo[:128],
        "prompt_tokens": entry.prompt_tokens,
        "completion_tokens": entry.completion_tokens,
        "cost_usd": entry.cost_usd,
        "pii_detected": entry.pii_detected,
        "masked_entities": json.dumps(entidades),
        "compliance_status": entry.compliance_status[:64],
        "latency_ms": entry.latency_ms,
        "user_group_id": entry.user_group_id,
        # None ⇒ SQL NULL, no JSON null: NULL significa "pedido sin atribución" (el motor
        # hoy no la produce — T025); [] afirmaría "ninguna capa corrió", que sería mentira.
        "applied_layers": json.dumps(entry.applied_layers) if entry.applied_layers is not None else None,
        "blocked_by_layer": entry.blocked_by_layer[:64] if entry.blocked_by_layer else None,
    })
    db.commit()

    # DESPUÉS del commit de la fila y con su propio try: el registro es el entregable de
    # este endpoint y no puede caerse porque el contador de gasto falle. Pero tampoco se
    # traga en silencio —la 031 existe para terminar con eso—: queda en el log del servicio
    # con nivel de error y traza.
    try:
        _acumular_gasto(db, entry)
    except Exception:
        db.rollback()
        logger.exception(
            "[basa-internal] la fila de auditoría se registró pero el presupuesto NO se "
            "actualizó (tenant=%s user=%s modelo=%s coste=%s)",
            entry.tenant_id, entry.user_id, entry.model, entry.cost_usd)
    return {"ok": True}


# ── Escribibilidad de la auditoría (spec 031, contrato §probe) ───────────────────────
# El modo `closed` (BASA_AUDIT_FAIL) exige rechazar ANTES de llamar al proveedor cuando la
# auditoría no puede escribirse — no gastar dinero en tráfico inauditable (FR-005). El
# backend resuelve eso contra su propia sesión; el MOTOR no tiene driver de Postgres (misma
# restricción que parió este plano), así que pregunta por HTTP.

# Techo del `SELECT 1`: esto vive en el pre-call de cada pedido del guardrail en modo
# closed, así que una base colgada tiene que resolverse como "no escribible" rápido en vez
# de sumar su latencia al pedido. Constante y no env: el contrato §Config declara UNA sola
# variable nueva (BASA_AUDIT_FAIL) y otra perilla sin documentar es deuda.
_PROBE_TIMEOUT_MS = 1500


@router.get("/audit/probe", dependencies=[Depends(_require_internal_secret)])
def audit_probe(db: Session = Depends(get_db)):
    """200 `{"writable": true}` si la base de auditoría contesta; 503 si no.

    El 503 también trae `writable: false` en el cuerpo: el llamador puede decidir por
    código de estado o por campo, sin que las dos lecturas se contradigan.

    Es un `SELECT 1` (lo que fija el contrato), no un INSERT de prueba: la pregunta es "¿la
    base responde?" y ensuciar `audit_logs` con filas sonda para responderla contaminaría
    el registro que este endpoint protege.
    """
    try:
        # Statement timeout LOCAL a la transacción de esta request: se va con el rollback y
        # no toca la configuración del servidor ni la de las otras sesiones del pool.
        db.execute(text(f"SET LOCAL statement_timeout = {_PROBE_TIMEOUT_MS}"))
        db.execute(text("SELECT 1"))
        return {"writable": True}
    except Exception as exc:
        logger.error("[basa-internal] auditoría NO escribible: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"writable": False,
                     "detail": "la base de auditoría no responde"},
        )
    finally:
        # Cierra la transacción abierta por el SET LOCAL/SELECT. `close()` de get_db la
        # cerraría igual, pero dejarla abierta hasta ahí retiene la conexión del pool en
        # una transacción idle por cada probe, que en modo closed es uno por pedido.
        try:
            db.rollback()
        except Exception:  # base caída: el rollback también falla y da igual
            pass
