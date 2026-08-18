"""API de gobernanza — estado honesto de las capas + CRUD del perfil (spec 027, US1/US2).

Router **admin-only** montado bajo ``/api/v1/governance``. Expone ``GET /status`` (US1) y
el CRUD del perfil de gobernanza (US2/T023: ``GET`` y ``PUT /profile``,
``DELETE /profile/{scope_type}/{scope_value}/{layer_key}``).

``GET /status`` responde las dos preguntas de la US1:

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

Y tres más que sostienen el CRUD del perfil (US2, contrato ``PUT /profile``):

5. **El piso no es configurable, y el rechazo no es silencioso** (FR-003 / SC-004): un
   ``layer_key`` de ``tier=floor`` responde 422 **sin escribir fila** y el intento queda
   registrado en el log estructurado (metadata-only). La validación de acá es la que
   *responde*; la que *garantiza* es el resolutor, que ignora toda fila de piso —una fila
   contrabandeada por SQL directo es inerte (data-model §1.4)—.

   **Dónde NO se registra, y por qué** (hallazgo A1 de la verificación adversarial de US2):
   la primera versión publicaba estos eventos en ``basa:gw:events``, el feed que sirve
   ``/gw/events``. Ese feed no exigía sesión, así que la configuración de gobernanza
   —``layer_key``, alcance, ``updated_by`` y ``tenant``— salía por un endpoint abierto: la
   misma información que este router protege con ``require_role("admin")`` (invariante #1 del
   contrato). Se cortó de raíz: los eventos de **cambio de configuración** no van a ningún
   feed. La constancia de un cambio aceptado es la propia fila (``updated_by`` /
   ``updated_at``); la del intento rechazado cabalga sobre la auditoría de la 018
   (data-model §1.4, mismo corte que D6). El monitor volvió a ser lo que era: la vitrina del
   **tráfico**, no de la configuración.
6. **La respuesta de una escritura es la verdad recalculada, no un eco** (garantía (d)):
   el PUT devuelve la fila persistida **y** el ``estado_efectivo`` recomputado con el
   mismo servicio que alimenta ``GET /status``. Encender una capa que el motor no tiene
   cargada NO devuelve 200-verde: acepta el deseo y responde ``no_disponible`` con motivo.
7. **La configuración nunca promete más alcance del que tiene** (garantía (b), D5
   refinada): una fila de superficie que RELAJA (``decision='off'`` sobre capa opcional) se
   acepta —es el caso insignia de D8— pero la respuesta explicita que solo rige para el
   tráfico cuya superficie es confiable (el ``tool_type`` provisionado en la Connection),
   nunca para la superficie derivada del User-Agent, que es spoofeable.
"""
import logging
import uuid
from datetime import datetime
from typing import List, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth.rbac import require_role
from ..auth.session import get_current_user
from ..database import get_db
from ..models.governance import GovernanceProfile
from ..models.tenant import DEFAULT_TENANT_ID, Tenant
from ..models.user import User
from ..services import ai_engine_client
from ..services.governance_catalog import (
    CONNECTION_MODES,
    DECISIONS,
    GOVERNANCE_LAYERS,
    OFF,
    SCOPE_CONNECTION_MODE,
    SCOPE_SURFACE,
    SCOPE_TENANT_DEFAULT,
    SCOPE_TYPES,
    SURFACES,
    TENANT_DEFAULT_SCOPE_VALUE,
    get_layer,
)
from ..services.governance_resolution import resolve_tenant_profile
from ..services.governance_status import (
    ESTADO_APLICANDOSE,
    build_status_layers,
    gather_status_inputs,
    layer_status_payload,
)
from ..services.redis_client import get_redis

logger = logging.getLogger("basa-secure-gateway.governance")

router = APIRouter(
    prefix="/governance",
    tags=["Governance"],
    dependencies=[Depends(require_role("admin", "compliance_officer"))],  # lectura de config; writes re-cierran a admin por-endpoint
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


# ── Shapes del CRUD del perfil (US2) ──────────────────────────────────────────────


class ProfileRowSchema(BaseModel):
    """Una fila de decisión, con las 6 claves del contrato.

    No lleva ``id`` ni ``tenant_id``: la clave natural del recurso es
    ``(scope_type, scope_value, layer_key)`` —el UNIQUE de la tabla— y el tenant es el del
    alcance de la sesión, no un parámetro que el cliente pueda mover. Exponer el UUID de la
    fila invitaría a un ``PUT /profile/{id}`` que la clave natural hace innecesario y que
    abriría el camino de escritura por-id que la RLS existe para atajar.
    """

    scope_type: str
    scope_value: str
    layer_key: str
    decision: str
    updated_by: str
    updated_at: Optional[datetime]


class ProfileListSchema(BaseModel):
    """Respuesta de ``GET /profile``.

    ``filas`` lleva **solo lo configurado**: la ausencia de fila ES "heredar" (D2), así que
    el endpoint no fabrica filas implícitas ni "completa" el catálogo. Quien quiera la
    postura completa —lo configurado más lo heredado— tiene ``GET /status``, que es el que
    resuelve la cascada. Mezclar las dos cosas acá volvería indistinguible "el admin decidió
    esto" de "esto es el default de producto", que es justo la distinción que ``origen``
    hace consultable en el status (FR-006).
    """

    tenant_id: str
    filas: List[ProfileRowSchema] = []


class EstadoPorModoSchema(BaseModel):
    """El estado recomputado de la capa escrita, para UN modo de conexión."""

    mode: str
    estado_efectivo: str
    motivo: str


class PropagacionSchema(BaseModel):
    """Honestidad sobre la propagación del cambio al motor (garantía (e)).

    ``confirmada`` es lo que el producto puede **afirmar**, no lo que le gustaría: hoy es
    siempre ``False`` y el motivo dice por qué. Ver ``_signal_engine_identity_invalidation``:
    la señal se emite, pero todavía no hay consumidor que la confirme, y un ``True`` sin
    confirmación sería exactamente la clase de mentira que esta feature vino a borrar.
    """

    confirmada: bool
    motivo: str


class ProfileWriteSchema(BaseModel):
    """Respuesta del ``PUT``: la verdad recalculada (garantía (d)), no un eco del body.

    ``estado_efectivo``/``motivo`` son el **colapso fail-closed** de ``por_modo``: si la
    capa no se está aplicando en alguno de los modos del alcance, el escalar reporta ese
    caso, nunca el optimista. La UI setea su estado desde esta respuesta y jamás desde el
    valor que mandó (D7).
    """

    fila: ProfileRowSchema
    estado_efectivo: str
    motivo: str
    por_modo: List[EstadoPorModoSchema] = []
    propagacion: PropagacionSchema


class ProfilePutBody(BaseModel):
    """Body del ``PUT``: UNA decisión por la clave natural del UNIQUE.

    Los cuatro campos son ``str`` a propósito, sin ``Enum`` de pydantic: los valores se
    validan abajo con un 422 que **nombra el campo y ecoa el valor recibido** (garantía (c)),
    porque ese ``detail`` es el mensaje que la UI muestra en el rollback. El 422 genérico de
    pydantic devuelve una lista de objetos que la UI no sabe renderizar.
    """

    scope_type: str
    scope_value: str
    layer_key: str
    decision: str


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


# ── Validación del CRUD (data-model §1.2 y §1.4) ──────────────────────────────────

# Dominio canónico de ``scope_value`` por eje. Es el espejo EXACTO del CHECK
# ``ck_governance_profiles_scope_pair`` (models/governance.py): la base es el backstop, pero
# el que responde con un mensaje útil es este mapa. Si alguna vez divergen, el síntoma es un
# 500 por IntegrityError en lugar de un 422 legible — por eso el contract test recorre el
# producto cartesiano de los tres ejes y no una muestra.
_SCOPE_VALUE_DOMAIN = {
    SCOPE_TENANT_DEFAULT: (TENANT_DEFAULT_SCOPE_VALUE,),   # centinela '*': el UNIQUE no dedup NULLs
    SCOPE_CONNECTION_MODE: tuple(CONNECTION_MODES),
    SCOPE_SURFACE: tuple(SURFACES),
}

# Orden canónico de los ejes en el 422, para que el mensaje sea determinista.
_SCOPE_TYPES_ORDENADOS = (SCOPE_TENANT_DEFAULT, SCOPE_CONNECTION_MODE, SCOPE_SURFACE)


def _unprocessable(campo: str, valor: str, admitidos) -> HTTPException:
    """422 que **nombra el campo** y ecoa el valor recibido (garantía (c)).

    Nombrar el campo no es cosmética: el body del PUT tiene cuatro campos y el ``detail`` es
    el texto que la UI muestra cuando revierte el toggle (patrón ``testGuardian``). Un "valor
    inválido" pelado obliga al admin a adivinar cuál de los cuatro.
    """
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=(f"Valor no válido para '{campo}': '{_echo(str(valor))}'. "
                f"Valores admitidos: {', '.join(admitidos)}."),
    )


def _validate_scope(scope_type: str, scope_value: str) -> Tuple[str, str]:
    """``(scope_type, scope_value)`` validados como **par**, no como campos sueltos.

    El dominio de ``scope_value`` DEPENDE del eje: ``'*'`` solo es legal en
    ``tenant_default``, y ``'claude-code'`` solo en ``surface``. Validarlos por separado
    aceptaría ``('connection_mode', '*')``, que pasa dos validaciones sueltas y muere en el
    CHECK compuesto de la base con un 500.
    """
    if scope_type not in SCOPE_TYPES:
        raise _unprocessable("scope_type", scope_type, _SCOPE_TYPES_ORDENADOS)
    dominio = _SCOPE_VALUE_DOMAIN[scope_type]
    if scope_value not in dominio:
        raise _unprocessable(f"scope_value (para scope_type='{scope_type}')",
                             scope_value, dominio)
    return scope_type, scope_value


def _validate_layer_key(layer_key: str):
    """La capa existe en el registry. Devuelve la ``GovernanceLayer``.

    El registry vive en código (D1) y no en la base, así que esta es la única validación
    posible del lado del esquema: ``layer_key`` no tiene FK ni CHECK a propósito, porque
    duplicar el catálogo en la DB lo volvería mutable por ``UPDATE`` — y con él, el piso.
    """
    layer = get_layer(layer_key)
    if layer is None:
        raise _unprocessable("layer_key", layer_key, tuple(GOVERNANCE_LAYERS))
    return layer


def _updated_by(user: Optional[User]) -> str:
    """Identidad del admin para la columna ``updated_by`` — **username o id, JAMÁS el email**.

    El contrato de la columna (models/governance.py) no es un detalle de estilo: esta tabla
    se exporta como evidencia de auditoría y **no tiene purga por retención**, así que un
    email acá queda en claro para siempre (C1). El fallback es el id, no el correo, y el
    centinela ``'system'`` cubre las escrituras sin sesión (que hoy no existen: el router es
    admin-only). Se trunca a 120 —el largo de la columna— para que un username absurdo
    devuelva un dato recortado y no un 500 por ``value too long``.
    """
    username = getattr(user, "username", None)
    if isinstance(username, str) and username.strip():
        return username.strip()[:120]
    ident = getattr(user, "id", None)
    return (str(ident)[:120] if ident is not None else "system")


# ── Registro de cambios de configuración (FR-003, garantía (f)) ───────────────────

EVENTO_CAMBIO = "governance_profile_updated"
EVENTO_RESET = "governance_profile_reset"
EVENTO_PISO = "governance_floor_violation"


def _registrar_evento_de_gobernanza(evento: str, *, tenant, layer_key: str, scope_type: str,
                                    scope_value: str, updated_by: str,
                                    decision: Optional[str] = None,
                                    filas: Optional[int] = None) -> None:
    """Registra el cambio (o el intento rechazado) en el log estructurado. **Metadata-only.**

    Los campos son los que fija data-model §1.4 para ``governance_floor_violation``
    —{tenant, layer_key, scope_type, scope_value, updated_by, ts}— y se reusan para los tres
    eventos, porque un rechazo y un cambio aceptado se registran con la misma información:
    quién, qué capa, qué alcance, cuándo. ``decision`` y ``filas`` son el detalle del caso
    aceptado, y son valores **cerrados** (enum validado / entero), no texto: acá no entra ni
    el body crudo, ni un mensaje de excepción, ni nada que haya escrito un usuario final (C1).

    **Por qué esto NO se publica en el feed del monitor** (hallazgo A1): ``basa:gw:events`` lo
    sirve ``/gw/events``, que hasta este fix no exigía sesión —y aun exigiéndola ahora, es la
    vitrina del **tráfico**, no de la configuración—. Publicar acá un evento con ``layer_key``,
    alcance, ``updated_by`` y ``tenant`` era sacar por un canal más laxo exactamente lo que
    este router protege con ``require_role("admin")`` (invariante #1 del contrato). Un segundo
    canal de salida para un dato admin-only es un segundo lugar donde puede fugarse, y no
    compraba nada que la fila y el log no den.

    **Dónde queda la constancia, entonces**: para un cambio ACEPTADO, en la propia fila
    (``updated_by`` / ``updated_at``) — evidencia durable que ya existe hoy. Para un intento
    RECHAZADO no hay fila que escribir, así que queda esta línea de log, y la fila durable
    cabalga sobre el mecanismo de auditoría de la 018 (data-model §1.4, mismo corte que D6).
    Se documenta el corte en vez de inventar una tabla: una tabla de auditoría propia de la
    027 competiría con la que la 018 está por definir.

    Nivel: ``warning`` para el intento contra el piso (es un evento de seguridad: alguien pidió
    apagar algo que no se apaga) e ``info`` para los cambios legítimos.
    """
    log = logger.warning if evento == EVENTO_PISO else logger.info
    log("governance: %s (tenant=%s layer=%s scope=%s/%s decision=%s filas=%s by=%s)",
        evento, tenant, layer_key, scope_type, scope_value,
        decision if decision is not None else "-",
        filas if filas is not None else "-", updated_by)


# ── Invalidación del cache de identidad del motor (garantía (e)) ──────────────────

# Señal de invalidación: un contador monótono por tenant. El consumidor previsto compara su
# epoch cacheada contra ésta y descarta la entrada si cambió — el patrón barato que no
# necesita ni pub/sub ni una entrada por key.
_EPOCH_KEY_PREFIX = "basa:governance:epoch:"
# TTL del cache de identidad del motor (custom_auth.py:65). Es el tamaño REAL de la ventana
# en la que el tráfico en curso puede seguir resolviéndose con la postura anterior.
_ENGINE_IDENTITY_TTL_S = 60

# Motivo del catálogo cerrado (misma regla que los ``motivo`` del status: sin nombres de
# proveedor, sin texto de excepción). Dice la verdad completa y con número: qué ya rige, qué
# puede tardar y cuánto.
MOTIVO_PROPAGACION_PENDIENTE = (
    "El cambio quedó guardado y ya rige para esta vista y para las consultas de estado. El "
    "motor de la pasarela resuelve la identidad de cada Connection con un cache propio de "
    f"hasta {_ENGINE_IDENTITY_TTL_S} segundos, así que el tráfico en curso puede seguir "
    "resolviéndose con la postura anterior durante ese lapso."
)


def _signal_engine_identity_invalidation(tenant) -> PropagacionSchema:
    """Emite la señal de invalidación del cache de identidad del motor. **Hook, no garantía.**

    Qué hace hoy, exactamente: incrementa ``basa:governance:epoch:<tenant>`` en el Redis
    compartido, antes de responder. Eso es todo lo que este lado del sistema puede hacer.

    **Qué falta, con precisión** (y por qué esta función devuelve ``confirmada=False``):

    - El cache que hay que invalidar es ``custom_auth._cache``
      (litellm/extensions/custom_auth.py:66): un ``dict`` **en el proceso del motor**,
      keyeado por ``key_hash``, con TTL de 60 s (``_CACHE_TTL_S``, :65).
    - El motor corre en **otro contenedor**. No hay endpoint de flush, no hay pub/sub, y
      ``custom_auth`` **no lee Redis en ninguna línea**: hoy no existe ningún camino por el
      que el backend alcance ese dict.
    - Lo que falta es del lado del motor y son ~3 líneas en ``custom_auth``: leer
      ``basa:governance:epoch:<tenant>`` (o recibirla por otro canal) y descartar la entrada
      cacheada cuando la epoch difiere de la que se guardó con ella. Ese archivo está
      **congelado** para esta entrega (lo reescribe el PR #21), así que el consumidor no se
      escribe acá.
    - **Consecuencia observable, y por eso se reporta**: la garantía (e) del contrato NO se
      cumple todavía, y **SC-006 no puede marcarse verde sobre esta pieza**: durante hasta
      60 s tras el cambio, una Connection ya resuelta en el motor puede seguir aplicando la
      postura anterior. Los planos que consultan la base por pedido (chat del backend, vista
      de estado) sí ven el cambio de inmediato.

    Por qué se emite igual la señal en vez de dejar un ``pass`` con un TODO: el productor es
    la mitad que sí puede existir hoy y la que fija el nombre de la clave; con ella escrita,
    cerrar el gap es agregar el lector. Lo que NO se hace es contar el ``INCR`` como
    invalidación: el valor de retorno dice ``confirmada=False`` porque **nadie lo confirma**,
    y un ``True`` optimista acá sería la misma mentira de "activo" que la feature borra.
    """
    client = get_redis()
    if client is not None:
        try:
            client.incr(f"{_EPOCH_KEY_PREFIX}{tenant}")
        except Exception:  # noqa: BLE001
            logger.warning("governance: no se pudo emitir la señal de invalidación de perfil")
    return PropagacionSchema(confirmada=False, motivo=MOTIVO_PROPAGACION_PENDIENTE)


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


# ── CRUD del perfil (US2 / T023) ──────────────────────────────────────────────────

# Honestidad de alcance de la fila de superficie que RELAJA (garantía (b), D5 refinada).
# No es una advertencia decorativa: el resolutor aplica estas filas SOLO cuando la superficie
# del pedido viene del ``tool_type`` provisionado en la Connection. Al tráfico cuya superficie
# se deriva del User-Agent —spoofeable— las filas que relajan se tratan como *heredar*. Sin
# esta frase, el admin apaga el enmascarado "para coding tools" y cree haber cubierto un
# alcance que la implementación deliberadamente no cubre.
MOTIVO_ALCANCE_SUPERFICIE = (
    "Esta decisión relaja una capa para una herramienta: aplica solo a Connections con esta "
    "herramienta declarada. Al tráfico cuya herramienta se deduce del cliente (dato que se "
    "puede falsear) no se le relaja nada."
)


def _row_schema(row: GovernanceProfile) -> ProfileRowSchema:
    return ProfileRowSchema(
        scope_type=row.scope_type,
        scope_value=row.scope_value,
        layer_key=row.layer_key,
        decision=row.decision,
        updated_by=row.updated_by,
        updated_at=row.updated_at,
    )


def _modos_del_alcance(scope_type: str, scope_value: str) -> Tuple[str, ...]:
    """Los modos de conexión sobre los que hay que recalcular el estado de la capa escrita.

    Una fila de ``connection_mode`` afecta a un solo modo. Una de ``tenant_default`` o de
    ``surface`` afecta a **los dos**: una superficie (p.ej. ``claude-code``) puede llegar
    tanto por suscripción como hacia modelos de la pasarela, y el estado de una capa no es
    el mismo en los dos casos (una capa del plano motor está ``delegada`` en suscripción y
    puede estar ``aplicandose`` en el otro). Reportar un solo modo elegido a dedo sería
    inventar un alcance.
    """
    if scope_type == SCOPE_CONNECTION_MODE:
        return (scope_value,)
    return tuple(CONNECTION_MODES)


def _estado_recalculado(db, tenant, layer, *, scope_type: str, scope_value: str,
                        decision: str, probe, inputs) -> Tuple[str, str, list]:
    """La verdad recalculada de la capa escrita (garantía (d)): ``(estado, motivo, por_modo)``.

    Se recalcula **con el mismo servicio que alimenta ``GET /status``** —no con una segunda
    implementación "para la respuesta del PUT"—: dos cálculos del mismo estado se
    desincronizan, y el día que lo hagan el PUT diría verde mientras la vista dice
    ``no_disponible``, que es literalmente la contradicción que 027 vino a eliminar.

    ``surface_trusted=True`` acá es correcto y no una concesión: el admin está configurando
    la superficie tal como está **provisionada**, que es el origen confiable de D5. Lo que la
    respuesta agrega —y por eso existe ``MOTIVO_ALCANCE_SUPERFICIE``— es que el tráfico con
    superficie *derivada* no recibe la relajación.

    **Colapso fail-closed**: el escalar reporta el primer modo que NO esté ``aplicandose``.
    Si la capa se aplica en un modo y no en el otro, la respuesta muestra el que no —jamás el
    optimista—, y ``por_modo`` queda para el detalle. Encender una capa que el motor no tiene
    cargada no puede devolver 200-verde.
    """
    surface = scope_value if scope_type == SCOPE_SURFACE else None
    por_modo = []
    for modo in _modos_del_alcance(scope_type, scope_value):
        profile = resolve_tenant_profile(db, tenant, mode=modo, surface=surface,
                                         surface_trusted=surface is not None)
        payload = layer_status_payload(layer, profile.decision_for(layer.layer_key),
                                       mode=modo, probe=probe, inputs=inputs)
        por_modo.append(EstadoPorModoSchema(mode=modo,
                                            estado_efectivo=payload["estado_efectivo"],
                                            motivo=payload["motivo"]))

    peor = next((e for e in por_modo if e.estado_efectivo != ESTADO_APLICANDOSE), por_modo[0])
    motivo = peor.motivo
    # Honestidad de alcance: solo cuando la fila RELAJA por superficie. Una fila de superficie
    # que AGREGA protección sí aplica también al tráfico con superficie derivada (el resolutor
    # solo ignora las que relajan), así que advertir ahí sería una advertencia falsa.
    if scope_type == SCOPE_SURFACE and decision == OFF and not layer.is_floor:
        motivo = f"{MOTIVO_ALCANCE_SUPERFICIE} {motivo}"
    return peor.estado_efectivo, motivo, por_modo


@router.get("/profile", response_model=ProfileListSchema)
async def list_governance_profile(
    tenant_id: Optional[str] = Query(None, description="Solo en instalaciones de una sola organización"),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    """Las filas de decisión configuradas del tenant. **Lo no configurado no está.**

    La ausencia de fila **es** "heredar" (D2, mismo idioma que ``redact_enabled=NULL`` de la
    013): este endpoint no fabrica filas implícitas ni completa el catálogo con los defaults
    de producto. Si las fabricara, el default de producto pasaría a parecer un dato editable
    —y borrable— cuando en realidad vive en el registry en código; y "el admin decidió esto"
    dejaría de distinguirse de "esto es lo que trae el producto".

    Orden determinista (eje, valor, capa) para que dos lecturas seguidas no barajen la tabla
    que la UI está mostrando.
    """
    tenant = _resolve_target_tenant(db, user, tenant_id)
    filas = (db.query(GovernanceProfile)
             .filter(GovernanceProfile.tenant_id == tenant)   # Constitución III — SIEMPRE
             .order_by(GovernanceProfile.scope_type,
                       GovernanceProfile.scope_value,
                       GovernanceProfile.layer_key)
             .all())
    return ProfileListSchema(tenant_id=str(tenant), filas=[_row_schema(f) for f in filas])


@router.put("/profile", response_model=ProfileWriteSchema, dependencies=[Depends(require_role("admin"))])
async def upsert_governance_profile(
    body: ProfilePutBody = Body(...),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    """Configura **una** decisión por la clave natural ``(scope_type, scope_value, layer_key)``.

    Orden de validación, deliberado: primero el par de alcance, después la capa, después la
    decisión, y **al final** el piso. Así el evento ``governance_floor_violation`` que
    registra el intento sale siempre con campos ya validados —un evento de auditoría con
    ``scope_value='<basura del cliente>'`` sería un canal de inyección de texto libre a un
    registro que se exporta (C1)—. Un intento contra el piso con alcance inválido se rechaza
    igual, por el 422 de alcance.

    **No acepta ``tenant_id``**, a diferencia del ``GET``: leer la gobernanza de otra
    organización en una instalación single-tenant es la concesión que hace SC-007; escribirla
    no lo es. Mientras el tier super-admin de la constitución III siga siendo forward-looking
    ([D9]), un camino de escritura cross-tenant sería exactamente el agujero que la RLS de la
    tabla existe para atajar. Se escribe siempre sobre el tenant de la sesión.
    """
    tenant = _resolve_target_tenant(db, user, None)
    scope_type, scope_value = _validate_scope(body.scope_type, body.scope_value)
    layer = _validate_layer_key(body.layer_key)
    if body.decision not in DECISIONS:
        raise _unprocessable("decision", body.decision, tuple(sorted(DECISIONS)))
    updated_by = _updated_by(user)

    # FR-003 / SC-004: el piso no se configura, y el rechazo queda registrado. Sin fila
    # escrita: se registra ANTES de responder y se devuelve 422, no 200 con la fila ignorada.
    if layer.is_floor:
        _registrar_evento_de_gobernanza(EVENTO_PISO, tenant=tenant, layer_key=layer.layer_key,
                                        scope_type=scope_type, scope_value=scope_value,
                                        updated_by=updated_by)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(f"La capa '{layer.layer_key}' forma parte del piso no negociable: se "
                    "aplica a todo el tráfico y ninguna configuración puede desactivarla ni "
                    "modificarla. El intento quedó registrado."),
        )

    fila = _upsert_row(db, tenant, scope_type=scope_type, scope_value=scope_value,
                       layer_key=layer.layer_key, decision=body.decision,
                       updated_by=updated_by)

    _registrar_evento_de_gobernanza(EVENTO_CAMBIO, tenant=tenant, layer_key=layer.layer_key,
                                    scope_type=scope_type, scope_value=scope_value,
                                    updated_by=updated_by, decision=body.decision)
    # ANTES de responder (garantía (e)) — con el alcance honesto que documenta la función.
    propagacion = _signal_engine_identity_invalidation(tenant)

    probe = await ai_engine_client.probe_loaded_guardrails()
    inputs = gather_status_inputs(db, tenant)
    estado, motivo, por_modo = _estado_recalculado(
        db, tenant, layer, scope_type=scope_type, scope_value=scope_value,
        decision=body.decision, probe=probe, inputs=inputs)

    return ProfileWriteSchema(fila=_row_schema(fila), estado_efectivo=estado, motivo=motivo,
                              por_modo=por_modo, propagacion=propagacion)


def _upsert_row(db, tenant, *, scope_type: str, scope_value: str, layer_key: str,
                decision: str, updated_by: str) -> GovernanceProfile:
    """UPSERT por la clave natural, con la carrera contemplada.

    ``updated_at`` se setea a mano y no se deja al ``onupdate`` del modelo: cuando el admin
    re-confirma la MISMA decisión, SQLAlchemy no emite UPDATE (ninguna columna cambió) y la
    fila quedaría con la marca de tiempo vieja. En una tabla que se exporta como evidencia de
    auditoría, "cuándo se confirmó esta postura por última vez" es justamente el dato.

    La carrera de dos admins escribiendo el mismo alcance a la vez existe y la ataja el
    UNIQUE: el perdedor recibe ``IntegrityError``, rehace la lectura y actualiza. Sin este
    reintento el segundo PUT sería un 500 en una operación idempotente por definición.
    """
    def _buscar():
        return (db.query(GovernanceProfile)
                .filter(GovernanceProfile.tenant_id == tenant,   # Constitución III — SIEMPRE
                        GovernanceProfile.scope_type == scope_type,
                        GovernanceProfile.scope_value == scope_value,
                        GovernanceProfile.layer_key == layer_key)
                .first())

    fila = _buscar()
    if fila is None:
        fila = GovernanceProfile(tenant_id=tenant, scope_type=scope_type,
                                 scope_value=scope_value, layer_key=layer_key,
                                 decision=decision, updated_by=updated_by)
        db.add(fila)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            fila = _buscar()
            if fila is None:
                raise
        else:
            db.refresh(fila)
            return fila

    fila.decision = decision
    fila.updated_by = updated_by
    fila.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(fila)
    return fila


@router.delete("/profile/{scope_type}/{scope_value}/{layer_key}",
               status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_role("admin"))])
async def delete_governance_profile(
    scope_type: str = Path(..., description="Eje del alcance"),
    scope_value: str = Path(..., description="Valor del eje"),
    layer_key: str = Path(..., description="Clave de la capa"),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    """Volver a **heredar**: borra la decisión explícita de ese alcance.

    No existe ``decision='inherit'``: el idioma de la herencia es la **ausencia de fila**, el
    mismo que ``redact_enabled=NULL``. Por eso "heredar" es un DELETE y no un tercer valor
    del enum.

    **Idempotente** (garantía (a)): si la fila no existe, igual 204 — el estado que el
    cliente pidió ("que este alcance herede") ya es el estado resultante, así que un 404
    describiría el mundo, no el pedido, y obligaría a la UI a tratar como error un caso en el
    que no hay nada que arreglar.

    Los enums se validan igual que en el PUT (422 nombrando el campo): un typo que devolviera
    204 le diría al admin que reseteó un alcance que nunca tocó. La única excepción es una
    capa de **piso**, que se acepta y resuelve en 204 sin más: no puede haber fila suya
    escrita por esta API, y si una llegó por SQL directo, borrarla solo puede mejorar las
    cosas (el resolutor ya la ignoraba).
    """
    tenant = _resolve_target_tenant(db, user, None)
    scope_type, scope_value = _validate_scope(scope_type, scope_value)
    layer = _validate_layer_key(layer_key)
    updated_by = _updated_by(user)

    borradas = (db.query(GovernanceProfile)
                .filter(GovernanceProfile.tenant_id == tenant,   # Constitución III — SIEMPRE
                        GovernanceProfile.scope_type == scope_type,
                        GovernanceProfile.scope_value == scope_value,
                        GovernanceProfile.layer_key == layer.layer_key)
                .delete(synchronize_session=False))
    db.commit()

    # Se registra el pedido, no solo el efecto: "intenté volver a heredar y no había nada" es
    # información de auditoría igual de válida que el borrado, y el contador lo distingue sin
    # cambiar el código de respuesta.
    _registrar_evento_de_gobernanza(EVENTO_RESET, tenant=tenant, layer_key=layer.layer_key,
                                    scope_type=scope_type, scope_value=scope_value,
                                    updated_by=updated_by, filas=borradas)
    _signal_engine_identity_invalidation(tenant)   # misma invalidación que el PUT, garantía (b)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
