import logging
import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any, Tuple
from uuid import UUID
from pydantic import BaseModel, Field

from ..database import get_db
from ..models.guardian import Guardian
from ..models.user import User
from ..models.tenant import DEFAULT_TENANT_ID
from ..services.audit_service import AuditService
from ..services.guardian_service import GuardianService
from ..services import ai_engine_client
from ..services import entity_catalog_service
from ..services.encryption_service import CifradoNoDisponible, encrypt, decrypt
# Vocabulario del issue #63 desde la librería PURA compartida (ver el comentario del import
# equivalente en `health.py`): quién decide qué significa `nlp_fail_mode` es UNA función.
from ..services.presidio_service import policy
from ..services.governance_status import (
    MOTIVO_MOTOR_SIN_CONFIRMAR,
    MOTIVO_NO_CARGADA,
)
from ..auth.rbac import require_role

_log = logging.getLogger("sentinel-secure-gateway.guardians")

router = APIRouter(
    prefix="/guardians",
    tags=["Security Guardians"],
    # config_producto: el auditor (compliance_officer) LEE la config (GET guardianes /
    # custom-entities). Los writes re-cierran a admin por-endpoint: create/update/delete ya
    # inyectan `actor: User = Depends(require_role("admin"))`; custom-entities y test lo agregan.
    dependencies=[Depends(require_role("admin", "compliance_officer"))],
)


# ── Disponibilidad real por guardián (spec 031, US3/T012 — FR-007) ─────────────────
#
# El eje que faltaba en esta pantalla es el de la 027 (D4): **deseo vs estado**.
# ``is_active`` es DESEO —lo que el admin pidió— y nunca fue prueba de que exista una
# pieza capaz de ejecutar ese guardián. Los 5 guardianes de nube del catálogo apuntan por
# nombre a guardrails que el motor no tiene cargados, y el motor **ignora en silencio** los
# nombres que no conoce: activarlos devolvía 200, pintaba el interruptor en verde y no
# cambiaba absolutamente nada del tráfico. Eso es exactamente la afirmación sin respaldo
# que la US3 borra.
#
# La disponibilidad **no se persiste ni se hardcodea como lista negra**: se resuelve contra
# la sonda al motor (``ai_engine_client.probe_loaded_guardrails``, la misma fuente B que usa
# ``governance_status``). Consecuencia buscada: el día que una instalación cargue de verdad
# uno de esos guardrails, su tarjeta deja de ser catálogo y el interruptor se habilita solo,
# sin tocar una línea de este archivo.
#
# El vocabulario NO es nuevo (instrucción explícita de la tarea): los motivos salen del
# catálogo CERRADO de ``governance_status`` — el mismo que ya distingue "el motor no
# responde" de "el motor no la tiene cargada", que son dos acciones distintas para el admin
# (FR-013 de la 027). Constitución VII: ni el ``engine_guardrail_name`` ni ningún nombre de
# proveedor viajan en la respuesta o en el error.

# Copy del rechazo. Marco de JF: son **features incoming del catálogo**, no promesas rotas —
# el mensaje explica por qué el interruptor no existe, sin pedir perdón y sin insinuar avería.
DETALLE_CATALOGO_INCOMING = (
    "Este guardián es parte del catálogo incoming del producto: en esta instalación no hay "
    "ningún guardrail instalado que lo ejecute, así que activarlo no cambiaría nada del "
    "tráfico y el producto no lo ofrece como interruptor."
)

# ── Planos donde se consume HOY la configuración de cada guardián ─────────────────
#
# Códigos cerrados; el copy visible lo pone la UI (igual que el resto de esta pantalla).
# **No sale del registry de capas a propósito**: el registry describe dónde *puede* correr
# la capa conceptual, y esta pantalla tiene que declarar dónde se lee de verdad ESTA fila
# de ``guardians`` (tabla de consumo real de la spec 031). Usar el registry acá sería
# sobre-declarar —justo el defecto que la US3 corrige—, así que la única dirección en la
# que este mapa puede equivocarse es la conservadora.
PLANO_CHAT_INTERNO = "chat_interno"
PLANO_API_BYOK = "api_byok"

_PLANOS_POR_TIPO: Dict[str, Tuple[str, ...]] = {
    "pii_masking": (PLANO_CHAT_INTERNO, PLANO_API_BYOK),
    "secret_detection": (PLANO_CHAT_INTERNO,),
    "sensitive_routing": (PLANO_CHAT_INTERNO,),
    "presidio": (PLANO_CHAT_INTERNO,),
}


def _planes_ejecucion(guardian_type: Optional[str]) -> List[str]:
    """Planos donde este guardián se ejecuta hoy. Lista vacía = ninguno (catálogo)."""
    return list(_PLANOS_POR_TIPO.get(guardian_type or "", ()))


def _disponibilidad(guardian, probe) -> Tuple[bool, Optional[str]]:
    """¿Existe en ESTA instalación una pieza que ejecute este guardián?

    Sin ``engine_guardrail_name`` el guardián lo ejecuta código NUESTRO dentro de nuestros
    propios procesos (el guardrail del motor y el plano chat comparten la misma pieza): la
    carga es estructural y no hay nada que sondear. Con nombre de motor, manda la sonda, y
    los tres desenlaces se distinguen igual que en ``governance_status._motivo_no_disponible``:
    cargado / el motor no lo tiene / no se pudo confirmar.

    Fail-closed: "no se pudo confirmar" cuenta como NO disponible. Preferimos negarle al
    admin un interruptor durante una caída del motor antes que dejarlo encender algo que
    quizás nadie ejecuta — que es la mentira que esta tarea elimina.
    """
    nombre = getattr(guardian, "engine_guardrail_name", None)
    if not nombre:
        return True, None
    if probe is not None and probe.has(nombre):
        return True, None
    if probe is None or not getattr(probe, "confirmed", False):
        return False, MOTIVO_MOTOR_SIN_CONFIRMAR
    return False, MOTIVO_NO_CARGADA


async def _gate_activacion(guardian_like, *, quiere_activar: bool, ya_activo: bool) -> None:
    """FR-007: activar un guardián sin guardrail que lo respalde es imposible.

    Se controla la **transición** apagado→encendido, no el hecho de que la fila esté
    encendida. Motivo: una fila heredada de una instalación anterior que ya venía en
    ``is_active=True`` haría fallar el guardado entero de la pantalla (la página persiste
    los 9 guardianes en un bucle) por un deseo viejo que el admin ya no puede ni tocar.
    Esa fila queda igualmente desarmada por el otro lado: el GET la reporta
    ``disponible=false`` y la UI la pinta como catálogo, así que su ``is_active`` ya no se
    lee en ningún lado como "esto corre".

    Tampoco se sondea al motor cuando no puede cambiar el resultado (guardián local, o
    petición que no enciende nada): la sonda cuelga de una pantalla de admin.
    """
    if not quiere_activar or ya_activo:
        return
    if not getattr(guardian_like, "engine_guardrail_name", None):
        return
    probe = await ai_engine_client.probe_loaded_guardrails()
    disponible, motivo = _disponibilidad(guardian_like, probe)
    if disponible:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"{DETALLE_CATALOGO_INCOMING} {motivo}",
    )


# ── H6 del gate de #137: aviso ante región no reconocida en escritura ──────────────
#
# `resolve_region` (litellm/extensions/sentinel_guardian_policy.py) cae al default en
# SILENCIO ante un typo o una región inexistente ("latam-ar", "ar", "Mars"…) — es la
# postura CORRECTA en LECTURA (Principio I regla (d): un typo no puede activar o
# desactivar reconocedores de otro país por accidente, patrón #131 de guardia
# ruidosa). Pero eso deja a un admin que escribe mal el código de región sin ninguna
# señal de que su cambio NO tuvo efecto — la pantalla sigue mostrando el valor que
# tipeó, mientras el motor sigue resolviendo el default de la instalación.
#
# NO se rechaza el write (422): `config` es `Dict[str, Any]` libre y `nlp_fail_mode`
# —la misma clase de campo— tampoco valida en escritura; endurecer sólo `region`
# introduciría una asimetría nueva entre dos campos que hoy comparten disciplina.
# El punto medio es hacer RUIDOSA la degradación silenciosa: WARNING con el tenant y
# el valor rechazado, mismo criterio que `_redact_header_override`/
# `record_nlp_degradation` usan para otras relajaciones que el sistema ignora en vez
# de aplicar.
def _advertir_region_no_reconocida(tenant_id, guardian_type: Optional[str],
                                   config: Optional[Dict[str, Any]]) -> None:
    if guardian_type != "pii_masking":
        return
    raw = (config or {}).get("region")
    if not isinstance(raw, str) or not raw.strip():
        return
    if raw.strip().lower() not in policy.STRUCTURED_ID_PATTERNS_BY_REGION:
        _log.warning(
            "guardianes: region=%r en pii_masking.config no es una región reconocida "
            "(tenant=%s) — resolve_region() la IGNORA y cae al default de la "
            "instalación; el admin que la escribió no tiene otra señal de que su "
            "cambio no tuvo efecto.", raw, tenant_id)


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
    # ── Estado, separado del deseo (spec 031 FR-007, vocabulario de la 027) ──
    # `is_active` de arriba es el DESEO. Estos tres campos son lo que de verdad hay
    # instalado, y son los que deciden si la UI pinta un interruptor o una tarjeta de
    # catálogo. `motivo_disponibilidad` sale del catálogo cerrado de `governance_status`:
    # nunca de una excepción, nunca con nombres de proveedor (Constitución VII).
    disponible: bool = True
    motivo_disponibilidad: Optional[str] = None
    planes_ejecucion: List[str] = Field(default_factory=list)

    class Config:
        from_attributes = True


class GuardianTestRequest(BaseModel):
    text: str


def _to_response(guardian: Guardian, probe=None) -> GuardianResponseSchema:
    disponible, motivo = _disponibilidad(guardian, probe)
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
        disponible=disponible,
        motivo_disponibilidad=motivo,
        planes_ejecucion=_planes_ejecucion(guardian.guardian_type),
    )


def _cifrar_credencial_de_servicio(valor: Optional[str]) -> Optional[str]:
    """Cifra la credencial de servicio del guardián, o corta con **503 sin escribir** (#283).

    Los dos handlers la llaman ANTES de tocar la fila. Ése es el punto: mientras el cifrado
    se hacía en el mismo renglón que la asignación, un `encrypt()` que fallaba dejaba la
    columna en NULL — en el alta se perdía la credencial recién cargada, y en la edición se
    **destruía una que estaba funcionando**, sin recuperación posible porque el texto en
    claro no se guarda en ningún lado. Levantando acá, la asignación no llega a ocurrir.

    503 y no 500: el servicio de cifrado no está disponible, la petición es correcta y
    reintentarla después de arreglar el despliegue es exactamente lo que corresponde.

    Un valor vacío devuelve `None` sin levantar, que es el contrato que ya tenían los dos
    handlers: en el alta significa «este guardián no lleva credencial» y en la edición es
    la forma explícita de borrarla. Eso no cambia — lo que cambia es que ahora el `None` de
    borrado deliberado y el de cifrado roto dejaron de ser el mismo valor.

    ⚠ El `if not valor` de abajo es REDUNDANTE y está medido como tal: `encrypt()` ya mira
    primero si hay algo que cifrar, así que quitarlo deja los 30 tests en verde (mutación
    corrida). Se queda para que el contrato de este helper no dependa del orden INTERNO de
    `encrypt()` — orden que sí está pineado, pero en `test_encryption_service.py`, no acá.
    Quien lo borre no va a ver un rojo; que lo lea acá es lo único que lo va a frenar.
    """
    if not valor:
        return None
    try:
        return encrypt(valor)
    except CifradoNoDisponible:
        # RUIDOSO, en el momento exacto: el único rastro que había era un warning emitido
        # UNA vez en el arranque del proceso, posiblemente días antes y sin relación visible
        # con la petición que perdió la credencial.
        # El texto tiene que valer para los DOS caminos que comparten este helper. «la
        # anterior quedó intacta» no valía en el alta (no hay anterior) y «el guardián quedó
        # sin tocar» tampoco (en el alta no hay guardián todavía). Lo único cierto en ambos
        # —y además lo único que el operador necesita saber— es que **no se escribió nada**.
        # Dos vueltas del gate de #295/#296 sobre la misma frase; ésta no habla de un sujeto
        # que puede no existir.
        _log.error("guardianes: FERNET_SECRET_KEY ausente o inválida — la credencial de "
                   "servicio NO se guardó y la petición se rechazó sin escribir nada")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="guardian_cifrado_no_disponible: el servicio de cifrado no está "
                   "configurado (FERNET_SECRET_KEY), así que la credencial NO se guardó. "
                   "La petición se rechazó sin escribir nada.",
        )


@router.get("", response_model=List[GuardianResponseSchema])
async def list_guardians(db: Session = Depends(get_db)):
    guardians = GuardianService.get_or_create_default_guardians(db)
    # UNA sonda por request (viene cacheada ~30 s en el cliente del motor): la lista tiene 9
    # filas y sondear por fila convertiría cada pageview del admin en 9 llamadas al motor.
    probe = await ai_engine_client.probe_loaded_guardrails()
    return [_to_response(g, probe) for g in guardians]


@router.post("", response_model=GuardianResponseSchema, status_code=status.HTTP_201_CREATED)
async def create_guardian(payload: GuardianSchema, db: Session = Depends(get_db),
                          actor: User = Depends(require_role("admin"))):
    # El alta por API no puede fijar `engine_guardrail_name` (no está en el schema de
    # entrada), así que hoy este gate no puede disparar. Se llama igual para que el
    # invariante FR-007 valga para TODA puerta de activación y no dependa de que el schema
    # siga sin ese campo mañana.
    await _gate_activacion(payload, quiere_activar=bool(payload.is_active), ya_activo=False)
    # H6 del gate de #137: aviso (no rechazo) si `config.region` no es reconocida.
    _advertir_region_no_reconocida(DEFAULT_TENANT_ID, payload.guardian_type, payload.config)
    # issue #104: postura efectiva del tenant ANTES del alta. El alta cae en DEFAULT_TENANT_ID
    # (el schema de entrada no trae tenant), que es donde la resolverá el bloque de abajo.
    postura_previa = _postura_efectiva_tenant(db, DEFAULT_TENANT_ID)
    region_previa = _region_efectiva_tenant(db, DEFAULT_TENANT_ID)  # H4 del gate de #137
    # #283: se cifra ANTES de construir la fila. Si el cifrado no está disponible esto
    # levanta 503 y no se llega a `db.add`, en vez del 201 con la credencial en la nada.
    clave_cifrada = _cifrar_credencial_de_servicio(payload.service_api_key)
    guardian = Guardian(
        name=payload.name,
        guardian_type=payload.guardian_type,
        is_active=payload.is_active,
        config=payload.config,
        fail_mode=payload.fail_mode,
        apply_on=payload.apply_on,
        service_api_key_encrypted=clave_cifrada,
    )
    db.add(guardian)
    db.commit()
    db.refresh(guardian)
    # issue #63/#104: el alta también audita — antes `POST` podía crear un `pii_masking` ACTIVO
    # con `degrade` sin fila durable. Se audita SI el alta movió la postura EFECTIVA del tenant:
    # un `pii_masking` activo que se vuelve gobernante en `degrade` queda registrado; uno INACTIVO
    # (o que no llega a ser el más antiguo, o de otro tipo) no cambia nada ⇒ no genera ruido.
    _auditar_cambio_postura_tenant(
        db, guardian.tenant_id, postura_previa,
        _postura_efectiva_tenant(db, guardian.tenant_id), actor,
        region_previo=region_previa,
        region_actual=_region_efectiva_tenant(db, guardian.tenant_id))
    return _to_response(guardian, await ai_engine_client.probe_loaded_guardrails())


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


@router.post("/custom-entities/draft", response_model=Dict[str, Any], dependencies=[Depends(require_role("admin"))])
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


@router.post("/custom-entities", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_role("admin"))])
async def create_custom_entity(payload: CustomEntityCreateRequest, db: Session = Depends(get_db)):
    """Persiste un patrón ya revisado (aceptado o editado a mano tras el draft) —
    único punto donde algo se activa en el firewall real. Revalida seguridad
    siempre, sin importar si vino de un draft de IA o se tipeó a mano.

    `async` + executor dedicado (#106): la revalidación ReDoS spawnea subprocesos y puede
    tardar ~12s con un regex catastrófico. Antes este handler era `def` (threadpool anyio,
    ~40 hilos compartidos con TODOS los endpoints síncronos), así que un admin hostil que
    disparara ~40 altas hostiles dejaba sin hilos al backend entero. Ahora la validación se
    deriva a un executor propio y acotado, aislada del threadpool general."""
    try:
        return await entity_catalog_service.create_custom_entity_async(
            db, DEFAULT_TENANT_ID,
            name=payload.name, entity_type=payload.entity_type, regex=payload.regex,
            score=payload.score, context=payload.context, region=payload.region,
            ai_generated=payload.ai_generated,
        )
    except (entity_catalog_service.UnsafePatternError,
            entity_catalog_service.InvalidEntityTypeError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except entity_catalog_service.DuplicateEntityTypeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/custom-entities/{entity_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_role("admin"))])
def delete_custom_entity(entity_id: str, db: Session = Depends(get_db)):
    try:
        entity_catalog_service.delete_custom_entity(db, DEFAULT_TENANT_ID, entity_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return None


# ── Registro durable del cambio de postura EFECTIVA del tenant (issue #63/#104 + H4 de #137) ─
#
# `nlp_fail_mode` decide si, con el detector real caído, el tráfico se RECHAZA o se sirve con
# media protección. `region` (H4 del gate de #137) decide qué identificadores de qué país se
# detectan. Las dos son decisiones de compliance, y una decisión de compliance que nadie puede
# reconstruir después no es auditable — antes de este PR sólo `nlp_fail_mode` dejaba fila.
#
# Lo que se audita es la postura EFECTIVA del tenant —la del `pii_masking` ACTIVO más antiguo,
# exactamente la fila que eligen los cuatro lectores del #104—, NO la de la fila aislada que se
# está tocando. Auditar la fila aislada dejaba una evasión (hallazgo round 2 del gate): con dos
# `pii_masking` activos (A viejo `block`, B nuevo `degrade`), `PUT A is_active=false` promueve a
# B y mueve la postura del tenant `block→degrade` sin cambiar ninguna fila de forma "auditable";
# y `DELETE` de la gobernante promueve a la siguiente. Comparando la postura efectiva ANTES y
# DESPUÉS de cada mutación, un solo criterio cubre: cambio de config, toggle de is_active,
# cambio de tipo, alta que se vuelve gobernante, y DELETE que promueve. Como bonus, un alta o
# edición que NO cambia la postura efectiva (p.ej. un `pii_masking` INACTIVO en `degrade`) no
# escribe nada: cero ruido. `region` sigue el MISMO criterio (`_region_efectiva_tenant`) y
# escribe su fila APARTE — un cambio que mueve las dos posturas a la vez deja DOS filas, una
# por decisión, no una combinada.
#
# ACTOR (FR-004 / #72, cableado en T006): los 3 handlers de mutación reciben el `User` vía
# `Depends(require_role("admin"))` —require_role ahora DEVUELVE el actor— y lo propagan hasta
# la fila `audit_logs` como `user_id`. La fila ya registra el HECHO **y el autor** (user_id →
# FK a users, que lleva el rol). Lo que sigue abierto del #72 es la COBERTURA GENÉRICA (todo
# endpoint de admin, todos los campos): el cambio de nlp_fail_mode y el de region quedan
# cerrados acá; el resto entra con el barrido de T006 sobre la matriz. El
# `require_role("admin")` del router sigue siendo la puerta; el del handler es sólo para
# inyectar el actor (chequeo barato: el `get_current_user` del que ambos dependen se cachea
# una vez por request).
_COMPLIANCE_CAMBIO_NLP = "config_change_nlp_fail_mode"
_COMPLIANCE_CAMBIO_REGION = "config_change_region"


def _postura_efectiva_tenant(db: Session, tenant_id) -> str:
    """Postura NLP que GOBIERNA el tráfico del tenant: la del `pii_masking` ACTIVO más antiguo.

    Corre EXACTAMENTE la misma selección que los cuatro lectores del #104 (`is_active=true`
    ORDER BY created_at, id LIMIT 1) — es un espejo de `health._fail_mode_efectivo` y de
    `gateway._nlp_context`, para que "qué se auditó" y "qué se sirve" no puedan divergir. Sin
    ninguna fila activa, el default fail-closed `block`, que es lo que esos lectores aplican.

    Es esta postura —no la de una fila aislada— la que hay que auditar: moverla desactivando,
    borrando o reordenando filas es un cambio de política igual que editar el `nlp_fail_mode`."""
    fila = (db.query(Guardian.config)
            .filter(Guardian.tenant_id == tenant_id,
                    Guardian.guardian_type == "pii_masking",
                    Guardian.is_active.is_(True))
            .order_by(Guardian.created_at, Guardian.id)
            .first())
    return policy.resolve_nlp_fail_mode((fila[0] if fila else None) or {})


def _region_efectiva_tenant(db: Session, tenant_id) -> str:
    """Región EFECTIVA del tenant: la de `pii_masking` ACTIVO más antiguo — MISMO desempate
    del #104/#119 que `_postura_efectiva_tenant`, `gateway._nlp_context` y los dos
    `_IDENTITY_SQL` (H4 del gate de #137: la región es una decisión de compliance —qué
    identificadores de qué país se detectan— y tiene que ser tan auditable como
    `nlp_fail_mode`).

    El default sin fila (o sin `region` en ninguna) NO es un literal propio: es
    `SENTINEL_ENTITY_REGION` de ESTE proceso — el MISMO default que `policy.resolve_region`
    usa en cada plano de tráfico. Auditar contra un default distinto al que gobierna el
    tráfico real dejaría que "lo que se auditó" y "lo que se sirve" pudieran divergir."""
    fila = (db.query(Guardian.config)
            .filter(Guardian.tenant_id == tenant_id,
                    Guardian.guardian_type == "pii_masking",
                    Guardian.is_active.is_(True))
            .order_by(Guardian.created_at, Guardian.id)
            .first())
    return policy.resolve_region(
        (fila[0] if fila else None) or {},
        default=os.environ.get("SENTINEL_ENTITY_REGION", policy.DEFAULT_REGION))


def _escribir_fila_compliance(db: Session, tenant_id, compliance_status: str, campo: str,
                              previo: str, actual: str, actor: "User | None" = None) -> None:
    """Fila durable de UN cambio de postura EFECTIVA. Extraído del cuerpo original de
    `_auditar_cambio_postura_tenant` (H4 del gate de #137) para que `nlp_fail_mode` y
    `region` compartan la MISMA disciplina —nunca propaga (un fallo del registro no puede
    voltear una mutación ya commiteada), mismo vocabulario cerrado y mismo actor
    (FR-004/#72)— sin duplicar el cuerpo. `campo` sólo alimenta el texto del log; el
    vocabulario auditable es `compliance_status`."""
    _log.warning("guardianes: %s EFECTIVO del tenant cambió de %s a %s (tenant=%s)",
                 campo, previo, actual, tenant_id)
    try:
        AuditService.log_transaction(
            db=db,
            # Metadata-only: el "modelo" de esta fila es el código del cambio, no un LLM.
            # Ni tokens ni coste — no hubo tráfico, hubo una decisión de configuración.
            model=f"{compliance_status}:{previo}->{actual}",
            prompt_tokens=0, completion_tokens=0, cost_usd=0.0,
            pii_detected=False, masked_entities=[],
            compliance_status=compliance_status, latency_ms=0,
            processing_purpose="administrative",
            tenant_id=tenant_id,
            # FR-004 / #72: el actor de la mutación. La fila ya no registra sólo el HECHO
            # sino el AUTOR (user_id → FK a users, que lleva el rol). `None` sólo en llamadas
            # internas sin request (no hay ninguna hoy: los 3 handlers pasan el actor).
            user_id=(actor.id if actor is not None else None),
        )
    except Exception as exc:  # noqa: BLE001
        _log.error("guardianes: el cambio de %s EFECTIVO (%s → %s) NO quedó "
                   "registrado: %s", campo, previo, actual, exc)


def _auditar_cambio_postura_tenant(db: Session, tenant_id, previo: str, actual: str,
                                   actor: "User | None" = None, *,
                                   region_previo: Optional[str] = None,
                                   region_actual: Optional[str] = None) -> None:
    """Escribe la(s) fila(s) durable(s) SI Y SÓLO SI la postura EFECTIVA del tenant cambió.
    Nunca propaga: un fallo del registro no puede voltear una mutación ya commiteada.

    `previo`/`actual` (nlp_fail_mode) los computa el handler con `_postura_efectiva_tenant`
    antes y después de la mutación (y de su commit). Comparar la postura efectiva —no la de
    la fila tocada— es lo que cierra la evasión por promoción del round 2 y, de paso, evita
    el ruido de altas/ediciones que no cambian lo que de verdad gobierna.

    `region_previo`/`region_actual` (H4 del gate de #137) son la MISMA disciplina para la
    región efectiva (`_region_efectiva_tenant`) — keyword-only y `None` por default: un
    caller que sólo audita `nlp_fail_mode` (los tests directos de esta función, de antes de
    este PR) sigue funcionando idéntico. Cuando el handler SÍ los pasa y difieren, se escribe
    una fila `config_change_region` APARTE de la de `nlp_fail_mode` —no una combinada— para
    que cada decisión de compliance quede en su propia fila, filtrable por separado."""
    if actual != previo:
        _escribir_fila_compliance(db, tenant_id, _COMPLIANCE_CAMBIO_NLP,
                                  "nlp_fail_mode", previo, actual, actor)
    if (region_previo is not None and region_actual is not None
            and region_actual != region_previo):
        _escribir_fila_compliance(db, tenant_id, _COMPLIANCE_CAMBIO_REGION,
                                  "region", region_previo, region_actual, actor)


@router.put("/{guardian_id}", response_model=GuardianResponseSchema)
async def update_guardian(guardian_id: UUID, payload: GuardianSchema, db: Session = Depends(get_db),
                          actor: User = Depends(require_role("admin"))):
    guardian = db.query(Guardian).filter(Guardian.id == guardian_id).first()
    if not guardian:
        raise HTTPException(status_code=404, detail="Guardian no encontrado.")

    # FR-007 — ANTES de mutar nada: el rechazo tiene que dejar la fila exactamente como
    # estaba. Se evalúa contra el `engine_guardrail_name` PERSISTIDO (el payload no lo
    # trae: el nombre de motor no es editable por API, Constitución VII).
    await _gate_activacion(guardian, quiere_activar=bool(payload.is_active),
                           ya_activo=bool(guardian.is_active))
    # H6 del gate de #137: aviso (no rechazo) si `config.region` no es reconocida.
    _advertir_region_no_reconocida(guardian.tenant_id, payload.guardian_type, payload.config)

    # issue #63/#104: se captura la postura EFECTIVA del tenant ANTES de tocar nada (sobre la DB
    # sin mutar) y se vuelve a leer DESPUÉS del commit. Cualquier cambio de config, de is_active
    # o de tipo que mueva la postura que de verdad gobierna —incluida la promoción de OTRA fila
    # al desactivar la gobernante— queda registrado; lo que no la mueve, no.
    tenant_id = guardian.tenant_id
    postura_previa = _postura_efectiva_tenant(db, tenant_id)
    region_previa = _region_efectiva_tenant(db, tenant_id)  # H4 del gate de #137

    # #283 — el invariante de esta edición: **nunca pisar una credencial sana con el
    # resultado de un cifrado fallido**. Por eso el cifrado se hace ACÁ, antes de tocar un
    # solo atributo de la fila, y no en el renglón de la asignación como estaba: si levanta,
    # el handler sale por el 503 sin haber mutado nada y la credencial anterior sigue en su
    # lugar. Mismo orden validar-todo-antes-de-escribir que `sso/admin_api`.
    rota_la_credencial = payload.service_api_key is not None
    clave_cifrada = (_cifrar_credencial_de_servicio(payload.service_api_key)
                     if rota_la_credencial else None)

    guardian.name = payload.name
    guardian.guardian_type = payload.guardian_type
    guardian.is_active = payload.is_active
    guardian.config = payload.config
    guardian.fail_mode = payload.fail_mode
    guardian.apply_on = payload.apply_on

    # Omitir el campo CONSERVA la credencial guardada; mandarlo vacío la borra a propósito.
    # Ese contrato no cambia: lo que cambia es que el NULL de borrado deliberado ya no
    # comparte camino con el de cifrado roto.
    if rota_la_credencial:
        guardian.service_api_key_encrypted = clave_cifrada

    db.commit()
    _auditar_cambio_postura_tenant(
        db, tenant_id, postura_previa, _postura_efectiva_tenant(db, tenant_id), actor,
        region_previo=region_previa, region_actual=_region_efectiva_tenant(db, tenant_id))
    db.refresh(guardian)
    # Misma sonda (cacheada) que el GET: si el PUT devolviera la disponibilidad calculada
    # con otra fuente, la tarjeta cambiaría de forma al guardar y volvería sola al recargar.
    return _to_response(guardian, await ai_engine_client.probe_loaded_guardrails())


@router.post("/{guardian_id}/test", response_model=Dict[str, Any], dependencies=[Depends(require_role("admin"))])
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
def delete_guardian(guardian_id: UUID, db: Session = Depends(get_db),
                    actor: User = Depends(require_role("admin"))):
    guardian = db.query(Guardian).filter(Guardian.id == guardian_id).first()
    if not guardian:
        raise HTTPException(status_code=404, detail="Guardian no encontrado.")
    # issue #104: borrar la gobernante PROMUEVE a la siguiente `pii_masking` activa y puede mover
    # la postura efectiva del tenant sin que ninguna fila "cambie" — la misma evasión que el PUT
    # con is_active=false. Se compara la postura efectiva antes/después del borrado. `tenant_id`
    # se captura ANTES del delete (después la instancia queda desprendida).
    tenant_id = guardian.tenant_id
    postura_previa = _postura_efectiva_tenant(db, tenant_id)
    region_previa = _region_efectiva_tenant(db, tenant_id)  # H4 del gate de #137
    db.delete(guardian)
    db.commit()
    _auditar_cambio_postura_tenant(
        db, tenant_id, postura_previa, _postura_efectiva_tenant(db, tenant_id), actor,
        region_previo=region_previa, region_actual=_region_efectiva_tenant(db, tenant_id))
    return None
