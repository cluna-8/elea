"""API de gobernanza — estado honesto de las capas (spec 027, US1/T014).

Router **admin-only** montado bajo ``/api/v1/governance``. En esta entrega expone un solo
endpoint, ``GET /status``, que responde las dos preguntas de la US1:

- FR-001 / SC-001: para cada capa, **qué le pasa de verdad** (aplicándose, requiere
  credencial, delegada, degradada, no disponible) — jamás "activa" para algo que no corre.
- FR-010 / SC-002: **qué protege hoy al tráfico de suscripción y qué al tráfico hacia
  modelos de la pasarela**, en UNA sola respuesta y sin leer código ni archivos.

Decisiones que sostienen el contrato (contracts/api-gobernanza.md):

1. **Admin-only en el router, no en la UI** (invariante #1): la dependencia va en el
   ``APIRouter`` —espejo exacto de ``guardians.py:17``— y no en cada handler. El gating del
   nav del frontend es cosmético; la protección real es ésta. Rol insuficiente → 403, sin
   sesión → 401.
2. **White-label estructural** (invariante #2, Constitución VII): las respuestas se
   serializan con ``response_model``, así que aunque un cálculo agregara una clave de más,
   FastAPI la recorta antes de emitirla. Los nombres de guardrail del motor y el payload
   crudo de la sonda se consumen SOLO adentro del backend: no hay camino por el que
   lleguen a la UI.
3. **El estado se calcula, no se lee**: no existe columna de estado que consultar.
   ``is_active`` de ``guardians`` es **deseo** y este endpoint no lo devuelve como estado
   — devolverlo es exactamente la mentira que la feature elimina (D4).
4. **Fail-closed**: si el motor no responde, la sonda no confirma nada y las capas del
   plano motor caen a ``no_disponible`` con motivo. Nunca ``aplicandose`` sin confirmación.

El CRUD del perfil (``GET/PUT /profile``, ``DELETE /profile/...``) es de la US2 y no vive
todavía en este archivo.
"""
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.rbac import require_role
from ..auth.session import get_current_user
from ..database import get_db
from ..models.tenant import DEFAULT_TENANT_ID, Tenant
from ..models.user import User
from ..services import ai_engine_client
from ..services.governance_catalog import CONNECTION_MODES, SURFACES
from ..services.governance_resolution import resolve_tenant_profile
from ..services.governance_status import build_status_layers, gather_status_inputs

router = APIRouter(
    prefix="/governance",
    tags=["Governance"],
    dependencies=[Depends(require_role("admin"))],
)


# ── Shapes públicos ───────────────────────────────────────────────────────────────


class LayerStatusSchema(BaseModel):
    """Una capa, con el shape EXACTO del contrato: 7 claves, ni una más.

    ``decision_resuelta`` y ``estado_efectivo`` son ejes **independientes** (garantía (c)):
    una capa ``on`` puede estar perfectamente ``no_disponible``. El deseo del admin no
    fabrica ejecución, y ésa es toda la tesis de la feature.
    """

    layer_key: str
    tier: str
    planes: List[str]          # LISTA: el piso corre en los tres planos a la vez
    decision_resuelta: Optional[str]
    origen: Optional[str]      # hace consultable la precedencia de la cascada (FR-006)
    estado_efectivo: str
    motivo: str                # catálogo cerrado — jamás texto de una excepción


class ModeStatusSchema(BaseModel):
    """Bloque por modo de conexión: el que responde SC-002 de un vistazo."""

    mode: str
    layers: List[LayerStatusSchema]


class ScopeSchema(BaseModel):
    mode: Optional[str]
    surface: Optional[str]
    tenant_id: str


class GovernanceStatusSchema(BaseModel):
    """Respuesta de ``GET /status``.

    ``modes`` solo viene en el resumen (sin ``mode``): es el bloque por modo de conexión
    que responde "qué protege a cada tipo de tráfico" en una vista.

    ``layers`` viene **siempre**: con ``mode`` es la resolución concreta de ese alcance; sin
    ``mode`` es la unión de los bloques por modo. Que la clave exista en los dos casos es lo
    que permite escribir un chequeo automatizado de SC-001 —"ninguna capa aplicándose sin
    confirmación"— con una sola forma de recorrer la respuesta.
    """

    scope: ScopeSchema
    modes: List[ModeStatusSchema] = []
    layers: List[LayerStatusSchema] = []


# ── Validación de parámetros ──────────────────────────────────────────────────────


def _echo(value: str) -> str:
    """Eco acotado del valor recibido para el 422 (garantía (e): el error lo NOMBRA).

    Se trunca porque el valor lo controla el cliente y el ``detail`` termina renderizado en
    la UI: un parámetro de 10 KB no tiene por qué viajar de vuelta.
    """
    return value[:40]


def _validate_enum(value: Optional[str], dominio, campo: str) -> Optional[str]:
    if value is None or value == "":
        return None
    if value not in dominio:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(f"Valor no válido para '{campo}': '{_echo(value)}'. "
                    f"Valores admitidos: {', '.join(dominio)}."),
        )
    return value


def _resolve_target_tenant(db: Session, user: Optional[User], tenant_id: Optional[str]) -> uuid.UUID:
    """Tenant sobre el que se consulta, con el gate honesto de la garantía (g).

    El tier super-admin de la constitución es **forward-looking**: hoy ``require_role("admin")``
    no distingue al admin de un tenant del admin de la instalación. Apoyar una lectura
    cross-tenant en un tier que todavía no existe sería exactamente el agujero que el RBAC
    de la 017 viene a cerrar, así que:

    - sin ``tenant_id``: siempre el tenant del usuario autenticado;
    - con ``tenant_id`` en una instalación **single-tenant** (un solo tenant, el caso
      on-premise y el del stack dev): se acepta — ahí admin ES el admin de la instalación y
      SC-007 lo necesita para consultar un tenant recién creado;
    - con ``tenant_id`` en una instalación con **más de un tenant**: **403 siempre**, hasta
      que exista el RBAC que distinga los dos roles;
    - tenant inexistente: 404.
    """
    propio = getattr(user, "tenant_id", None) or DEFAULT_TENANT_ID
    if tenant_id is None or tenant_id == "":
        return propio

    if db.query(Tenant).count() > 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("Consultar la gobernanza de otra organización requiere un rol de "
                    "administración de la instalación, que todavía no existe. Se puede "
                    "consultar la gobernanza de la organización propia."),
        )
    try:
        pedido = uuid.UUID(tenant_id)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Valor no válido para 'tenant_id': '{_echo(str(tenant_id))}'.",
        )
    if not db.query(Tenant).filter(Tenant.id == pedido).first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="La organización indicada no existe.")
    return pedido


# ── Endpoint ──────────────────────────────────────────────────────────────────────


@router.get("/status", response_model=GovernanceStatusSchema)
async def get_governance_status(
    mode: Optional[str] = Query(None, description="Modo de conexión del alcance consultado"),
    surface: Optional[str] = Query(None, description="Herramienta/superficie del alcance"),
    tenant_id: Optional[str] = Query(None, description="Solo en instalaciones de una sola organización"),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    """Estado REAL de cada capa de gobernanza.

    - **Sin parámetros**: resumen por modo de conexión — para cada modo, todas las capas con
      su decisión resuelta y su estado efectivo (FR-010 / SC-002).
    - **Con ``mode``** (y opcionalmente ``surface``): la resolución concreta de ese alcance.

    Las capas de piso aparecen SIEMPRE, con ``tier=floor``, ``decision_resuelta=on`` y
    ``origen=floor`` (garantía (b)): no existe representación de piso apagado, porque el
    piso no sale de la configuración sino del registry en código.

    La sonda al motor se consulta **una sola vez** por request y viene cacheada ~30 s, así
    abrir la vista no dispara una llamada autenticada al motor por pageview (invariante #2).
    """
    mode = _validate_enum(mode, CONNECTION_MODES, "mode")
    surface = _validate_enum(surface, SURFACES, "surface")
    tenant = _resolve_target_tenant(db, user, tenant_id)

    probe = await ai_engine_client.probe_loaded_guardrails()
    inputs = gather_status_inputs(db, tenant)

    def _layers_de(modo: str) -> list:
        # surface_trusted=True: acá el admin pregunta por la superficie tal como está
        # PROVISIONADA (el tool_type de la Connection, dato que carga él), que es el origen
        # confiable de D5. La superficie derivada del User-Agent es una propiedad del
        # tráfico en vivo, no de la configuración, y por eso no se consulta por este
        # endpoint: para ese caso el resolutor ya ignora las filas que relajan.
        profile = resolve_tenant_profile(db, tenant, mode=modo, surface=surface,
                                         surface_trusted=bool(surface))
        return build_status_layers(profile, probe=probe, inputs=inputs)

    scope = ScopeSchema(mode=mode, surface=surface, tenant_id=str(tenant))

    if mode:
        return GovernanceStatusSchema(scope=scope, modes=[], layers=_layers_de(mode))

    modes = [ModeStatusSchema(mode=modo, layers=_layers_de(modo)) for modo in CONNECTION_MODES]
    # La unión, para el chequeo automatizado de SC-001: una sola forma de recorrer la
    # respuesta sirva o no `mode`.
    union = [capa for bloque in modes for capa in bloque.layers]
    return GovernanceStatusSchema(scope=scope, modes=modes, layers=union)
