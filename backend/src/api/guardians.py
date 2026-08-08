import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any, Tuple
from uuid import UUID
from pydantic import BaseModel, Field

from ..database import get_db
from ..models.guardian import Guardian
from ..models.tenant import DEFAULT_TENANT_ID
from ..services.audit_service import AuditService
from ..services.guardian_service import GuardianService
from ..services import ai_engine_client
from ..services import entity_catalog_service
from ..services.encryption_service import encrypt, decrypt
# Vocabulario del issue #63 desde la librería PURA compartida (ver el comentario del import
# equivalente en `health.py`): quién decide qué significa `nlp_fail_mode` es UNA función.
from ..services.presidio_service import policy
from ..services.governance_status import (
    MOTIVO_MOTOR_SIN_CONFIRMAR,
    MOTIVO_NO_CARGADA,
)
from ..auth.rbac import require_role

_log = logging.getLogger("basa-secure-gateway.guardians")

router = APIRouter(
    prefix="/guardians",
    tags=["Security Guardians"],
    dependencies=[Depends(require_role("admin"))],
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


@router.get("", response_model=List[GuardianResponseSchema])
async def list_guardians(db: Session = Depends(get_db)):
    guardians = GuardianService.get_or_create_default_guardians(db)
    # UNA sonda por request (viene cacheada ~30 s en el cliente del motor): la lista tiene 9
    # filas y sondear por fila convertiría cada pageview del admin en 9 llamadas al motor.
    probe = await ai_engine_client.probe_loaded_guardrails()
    return [_to_response(g, probe) for g in guardians]


@router.post("", response_model=GuardianResponseSchema, status_code=status.HTTP_201_CREATED)
async def create_guardian(payload: GuardianSchema, db: Session = Depends(get_db)):
    # El alta por API no puede fijar `engine_guardrail_name` (no está en el schema de
    # entrada), así que hoy este gate no puede disparar. Se llama igual para que el
    # invariante FR-007 valga para TODA puerta de activación y no dependa de que el schema
    # siga sin ese campo mañana.
    await _gate_activacion(payload, quiere_activar=bool(payload.is_active), ya_activo=False)
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
    # issue #104: el alta también audita. Antes, `POST` podía crear un `pii_masking` ACTIVO con
    # `nlp_fail_mode: degrade` SIN fila durable —el registro sólo colgaba del PUT—, dejando una
    # decisión de seguridad sin rastro. Tipo previo `None` (la fila no existía) ⇒ línea base el
    # default `block`: un alta con postura != `block` queda registrada igual que un PUT; un alta
    # en `block` (o de otro tipo) no genera ruido.
    _auditar_cambio_nlp_fail_mode(db, guardian, tipo_previo=None, previo=policy.NLP_FAIL_BLOCK)
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
    except (entity_catalog_service.UnsafePatternError,
            entity_catalog_service.InvalidEntityTypeError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except entity_catalog_service.DuplicateEntityTypeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/custom-entities/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_custom_entity(entity_id: str, db: Session = Depends(get_db)):
    try:
        entity_catalog_service.delete_custom_entity(db, DEFAULT_TENANT_ID, entity_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return None


# ── Registro durable del cambio de postura NLP (issue #63) ────────────────────────
#
# `nlp_fail_mode` decide si, con el detector real caído, el tráfico se RECHAZA o se sirve con
# media protección. Es una decisión de seguridad, y una decisión de seguridad que nadie puede
# reconstruir después no es auditable.
#
# GAP CONOCIDO (para #72): este repo NO tiene hoy un mecanismo genérico de auditoría de
# cambios de configuración — ningún endpoint de admin registra "quién cambió qué y cuándo".
# Lo que se hace acá es el mínimo honesto para ESTE campo, no la solución del problema
# general: una fila en `audit_logs` (la única bitácora durable que el compliance officer ya
# consulta) con `compliance_status` propio y CERO tokens/coste, más el `logger.warning`. Falta
# el actor: este endpoint depende de `require_role("admin")` y no recibe el `User`, así que la
# fila registra el HECHO, no el autor. Cerrar eso —actor + cobertura de todos los campos— es
# trabajo del issue #72, no de este fix.
_COMPLIANCE_CAMBIO_NLP = "config_change_nlp_fail_mode"


def _postura_efectiva(tipo: Optional[str], config: Optional[dict]) -> str:
    """Postura NLP que gobierna de verdad para una fila con ese `guardian_type` y esa `config`.

    Sólo un `pii_masking` gobierna la detección: si la fila no es `pii_masking`, su
    `nlp_fail_mode` está INERTE y la postura efectiva es el default fail-closed (`block`),
    aunque su config lleve `degrade` escrito. Esto es lo que cierra la evasión por doble PUT
    del #104 (parkear `degrade` en una fila mientras no es `pii_masking` y devolverle el tipo
    después): la línea base contra la que se compara no arrastra ese `degrade` inerte."""
    if tipo != "pii_masking":
        return policy.NLP_FAIL_BLOCK
    return policy.resolve_nlp_fail_mode(config or {})


def _auditar_cambio_nlp_fail_mode(db: Session, guardian, *, tipo_previo: Optional[str],
                                  previo: str) -> None:
    """Deja constancia durable si la postura ante el NLP caído cambió. Nunca propaga:
    un fallo del registro no puede voltear un guardado que ya se commiteó.

    El chequeo `pii_masking` mira el tipo ORIGINAL **y** el nuevo (issue #104). Evaluarlo sólo
    sobre el tipo ya mutado dejaba dos agujeros: el alta por `POST` de un `pii_masking` con
    `degrade` no registraba nada (el `previo`/`tipo_previo` de una fila nueva es "no existía",
    tratado como default `block`), y la evasión por doble PUT —sacar el tipo, guardar `degrade`,
    devolverlo— salía sin rastro. Si NINGUNO de los dos lados es `pii_masking` no hay postura NLP
    en juego y no hay nada que auditar."""
    tipo_actual = guardian.guardian_type
    if tipo_previo != "pii_masking" and tipo_actual != "pii_masking":
        return
    actual = _postura_efectiva(tipo_actual, guardian.config)
    if actual == previo:
        return
    _log.warning("guardianes: nlp_fail_mode cambió de %s a %s (guardián PII, tenant=%s)",
                 previo, actual, getattr(guardian, "tenant_id", None))
    try:
        AuditService.log_transaction(
            db=db,
            # Metadata-only: el "modelo" de esta fila es el códido del cambio, no un LLM.
            # Ni tokens ni coste — no hubo tráfico, hubo una decisión de configuración.
            model=f"{_COMPLIANCE_CAMBIO_NLP}:{previo}->{actual}",
            prompt_tokens=0, completion_tokens=0, cost_usd=0.0,
            pii_detected=False, masked_entities=[],
            compliance_status=_COMPLIANCE_CAMBIO_NLP, latency_ms=0,
            processing_purpose="administrative",
            tenant_id=getattr(guardian, "tenant_id", None),
        )
    except Exception as exc:  # noqa: BLE001
        _log.error("guardianes: el cambio de nlp_fail_mode (%s → %s) NO quedó registrado: %s",
                   previo, actual, exc)


@router.put("/{guardian_id}", response_model=GuardianResponseSchema)
async def update_guardian(guardian_id: UUID, payload: GuardianSchema, db: Session = Depends(get_db)):
    guardian = db.query(Guardian).filter(Guardian.id == guardian_id).first()
    if not guardian:
        raise HTTPException(status_code=404, detail="Guardian no encontrado.")

    # FR-007 — ANTES de mutar nada: el rechazo tiene que dejar la fila exactamente como
    # estaba. Se evalúa contra el `engine_guardrail_name` PERSISTIDO (el payload no lo
    # trae: el nombre de motor no es editable por API, Constitución VII).
    await _gate_activacion(guardian, quiere_activar=bool(payload.is_active),
                           ya_activo=bool(guardian.is_active))

    # issue #63/#104: la postura ante el motor NLP caído se captura ANTES de mutar, para poder
    # comparar. Se resuelve con `_postura_efectiva` (una clave borrada vuelve a `block`, y eso
    # también es un cambio de postura auditable). El `guardian_type` ORIGINAL se guarda aparte:
    # el chequeo `pii_masking` NO puede evaluarse sobre el tipo ya mutado (evasión por doble PUT
    # del #104), así que viaja explícito a `_auditar_cambio_nlp_fail_mode`.
    tipo_previo = guardian.guardian_type
    nlp_previo = _postura_efectiva(tipo_previo, guardian.config)

    guardian.name = payload.name
    guardian.guardian_type = payload.guardian_type
    guardian.is_active = payload.is_active
    guardian.config = payload.config
    guardian.fail_mode = payload.fail_mode
    guardian.apply_on = payload.apply_on

    if payload.service_api_key is not None:
        guardian.service_api_key_encrypted = encrypt(payload.service_api_key) if payload.service_api_key else None

    db.commit()
    _auditar_cambio_nlp_fail_mode(db, guardian, tipo_previo=tipo_previo, previo=nlp_previo)
    db.refresh(guardian)
    # Misma sonda (cacheada) que el GET: si el PUT devolviera la disponibilidad calculada
    # con otra fuente, la tarjeta cambiaría de forma al guardar y volvería sola al recargar.
    return _to_response(guardian, await ai_engine_client.probe_loaded_guardrails())


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
