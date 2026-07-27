import time
import os
import re
import uuid
import httpx
import logging
import yaml
from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Response, status, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from ..database import get_db
from ..models.policy import SecurityPolicy
from ..models.guardian import Guardian
from ..models.audit import AuditLog
from ..models.compliance import ComplianceProject, HumanReview
from ..api.compliance import DEFAULT_DISCLOSURE_ES
from ..api.policy import get_or_create_default_policy
from ..services.budget_service import BudgetService
from ..services.presidio_service import PresidioService
from ..services.optimization_service import OptimizationService
from ..services.compliance_service import ComplianceService
from ..services.audit_service import AuditService
from ..services.guardian_service import GuardianService
from ..services.rate_limiter import check_rpm, check_tpm, RateLimitExceeded
from ..services.governance_catalog import (
    GOVERNANCE_LAYERS,
    ROUTE_CHAT_UI,
    build_attribution,
    map_effective_mode,
)
from ..services.governance_resolution import (
    build_connection_overrides,
    resolve_tenant_profile,
)
from ..auth.rbac import require_role, require_authenticated
# El display-masking del preview se REUSA del plano gateway (`_safe_preview`), no se
# reimplementa: el contrato del evento (§10) exige que TODO evento —incluidos los de punto
# de bloqueo, donde el enmascarado puede no haber corrido— lleve el preview enmascarado con
# un pase propio sobre mapa desechable + scrub de secretos. Dos implementaciones del mismo
# preview es dos formas distintas de fugarlo. Mismo precedente que `inspect.py`.
from . import gateway as _gw_plane

router = APIRouter(prefix="/chat", tags=["Playground Chat"])
logger = logging.getLogger("basa-secure-gateway.chat")

_ENGINE_URL = os.getenv("LITELLM_API_BASE", "http://litellm:4000")
_ENGINE_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY", "basa_master_key_9999")

# Guardia de calidad (spec 012 US6): reintenta con el prompt original si la respuesta
# tras compresión es anómala (vacía/muy corta). Fail-open; raro (solo si se comprimió).
_REVERSAL_GUARD = os.getenv("COMPRESSION_REVERSAL_GUARD", "true").lower() == "true"


# Timeout (segundos) de la llamada al motor de IA. Configurable por env sin rebuild:
# un modelo local/self-hosted (Ollama del cliente) puede tardar bastante más que un
# proveedor cloud, así que el hardcode de 15s cortaba respuestas legítimas. Default
# holgado (60s). Un valor no numérico o vacío cae al default.
def _resolve_engine_timeout(default: float = 60.0) -> float:
    raw = os.getenv("BASA_ENGINE_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


_ENGINE_TIMEOUT_SECONDS = _resolve_engine_timeout()

_EU_COMPLIANT_PROVIDERS = {"bedrock", "vertex_ai", "azure", "watsonx", "ollama", "ollama_chat"}


# ── Gobernanza del plano chat (spec 027 US2, T027) ────────────────────────────────
#
# El chat del backend es el TERCER call-site del resolutor único (D3: un resolutor, tres
# call-sites). Dos constantes del plano, ambas derivadas y no escritas a mano:
#
# * el **modo** sale de `map_effective_mode(ROUTE_CHAT_UI)` — jamás del `upstream_mode`
#   crudo de una Connection (esa columna es la intención declarada, no por dónde se ruteó
#   de verdad, D5). El chat siempre habla con los modelos administrados por la pasarela.
# * la **superficie** es `chat-ui` y es CONFIABLE: no se deduce de un User-Agent
#   spoofeable, se sabe porque el pedido entró por este endpoint. Por eso una decisión de
#   superficie que RELAJA (p.ej. masking off para el playground) sí puede aplicar acá,
#   mientras que la misma decisión derivada de un UA sería inerte (contrato resolutor #5).
_CHAT_SURFACE = "chat-ui"

# Fuerza relativa de un veredicto: cuando una capa produce varios en el mismo pedido
# (dos nombres enmascarados, un secreto redactado y otro bloqueado) se reporta el MÁS
# fuerte. Un bloqueo jamás puede quedar tapado por un `allow` posterior.
_VERDICT_RANK = {"allow": 0, "flag": 1, "mask": 2, "block": 3}


def _record_verdict(verdicts: dict, layer_key: str, decision: str, count: Optional[int] = None) -> None:
    """Acumula el veredicto de una capa quedándose con el más fuerte y con el contador
    conocido. C1: acá solo entran códigos del vocabulario cerrado y enteros."""
    prev = verdicts.get(layer_key)
    if prev is None:
        verdicts[layer_key] = {"decision": decision}
        if count is not None:
            verdicts[layer_key]["count"] = int(count)
        return
    if _VERDICT_RANK[decision] > _VERDICT_RANK[prev["decision"]]:
        prev["decision"] = decision
    if count is not None:
        prev["count"] = int(prev.get("count") or 0) + int(count)


def _guardian_type_by_name(guardians) -> Dict[str, str]:
    """Nombre de display → ``guardian_type``.

    Los triggers del pipeline identifican al guardián por su **nombre de display**, que es
    editable y white-label — por eso no puede viajar a `applied_layers` (un rename del
    cliente rompería la atribución histórica, D6). Este mapa es el traductor interno de ese
    nombre al tipo, y del tipo se llega al `layer_key` estable del registry.

    Los dos literales del final son los respaldos que `GuardianService` usa cuando la fila
    del guardián no existe: sin ellos, un pedido bloqueado en esa rama quedaría sin capa
    atribuible.
    """
    names = {g.name: g.guardian_type for g in guardians if g.name and g.guardian_type}
    names.setdefault("Secret Detector", "secret_detection")
    names.setdefault("PII Guard", "pii_masking")
    return names


def _verdicts_from_triggers(triggers, name_to_type: Dict[str, str], verdicts: dict) -> None:
    """Traduce los triggers del pipeline a veredictos por capa (los TRES ejes de D6).

    El `action` del trigger conflaba identidad, estado y decisión en un solo campo (ahí
    `DELEGATED` convivía con `MASK` y `BLOCK`); acá se separa: la capa sale del tipo del
    guardián, el estado lo decide `build_attribution` y la decisión es lo que la capa hizo
    con ESTE pedido. El `detail` del trigger —que lleva el nombre propio bloqueado y es la
    fuga que C1 prohíbe— **no se lee**: solo se miran `guardian` y `action`.
    """
    for trigger in triggers or []:
        if not isinstance(trigger, dict):
            continue
        gtype = name_to_type.get(trigger.get("guardian"))
        action = trigger.get("action")
        if gtype in ("pii_masking", "presidio"):
            # Un bloqueo por PII lo produce la DETECCIÓN (piso): el enmascarado es la
            # transformación, y si el pedido se bloqueó no hubo transformación alguna.
            if action == "BLOCK":
                _record_verdict(verdicts, "pii_detection", "block")
            elif action == "MASK":
                _record_verdict(verdicts, "pii_masking", "mask")
        elif gtype == "secret_detection":
            if action == "BLOCK":
                _record_verdict(verdicts, "secret_detection", "block", count=1)
            elif action == "REDACT":
                _record_verdict(verdicts, "secret_detection", "mask", count=1)
        elif gtype == "sensitive_routing":
            if action in ("REROUTE", "FLAG"):
                _record_verdict(verdicts, "sensitive_routing", "flag")
        # Cualquier otro trigger (el pseudo-guardián "Motor de IA" que marca DELEGATED, un
        # guardián de tipo no catalogado) se ignora: sin capa del registry no hay identidad
        # estable que reportar, y inventarla sería exactamente la mentira que 027 elimina.


# Vocabulario de entidades por defecto de la detección local. Espeja el literal que usa
# `GuardianService.process_prompt` cuando el guardián no tiene `entities` configuradas: no
# se importa porque ahí es una lista inline dentro de la función (guardian_service.py, hoy
# bloqueado por el PR #21). Vive acá para que la detección de PISO tenga el MISMO
# vocabulario que la rama que enmascara — si contaran distinto, "apagar el enmascarado no
# cambia la detección" (D8) dejaría de ser verificable.
_DEFAULT_PII_ENTITIES = ("PERSON", "DNI", "CUIL", "EMAIL_ADDRESS", "PHONE_NUMBER")


def _guardians_of_tenant(db: Session, tenant_id) -> list:
    """Instancias de guardián **del tenant del pedido** (Constitución III).

    Acá había un ``db.query(Guardian).all()`` sin filtro, justificado como "describe lo
    mismo que ejecutó el pipeline". El problema es que sus consumidores no describen: uno
    marca capas como "con credencial cargada" (`_credentials_from_guardians`) y el otro
    arma la lista de guardrails que ESTE pedido le manda al motor
    (`_engine_guardrails_for_profile`). Sin filtro, una credencial que cargó el tenant B
    hacía que un pedido del tenant A reportara esa capa como disponible, y le pedía al
    motor guardrails de otro cliente.

    Que el lado que EJECUTA siga sin filtrar (``get_or_create_default_guardians``, hoy
    bloqueado por el PR #21 / des-singletonización de la 015) no es motivo para propagar el
    cruce: filtrar acá solo puede **quitar** afirmaciones, nunca agregarlas, y degradar
    hacia menos afirmación es siempre la dirección segura. Residuo conocido mientras el
    otro lado no filtre: un trigger producido por un guardián de otro tenant puede quedar
    sin traducir a capa (`_guardian_type_by_name`) y por lo tanto sin veredicto. Se
    prefiere no afirmar antes que atribuirle al tenant una capa que no es suya.

    Gemela de ``governance_status._guardians_of_tenant``, y por el mismo motivo: es una
    lectura, así que **jamás** llama a ``get_or_create_default_guardians`` —ese camino BORRA
    la tabla entera y re-siembra cuando hay menos de 9 filas (P2 del research)—. Sin tenant
    legible devuelve vacío (fail-closed): sin filas no hay credencial que reportar ni
    guardrail que pedir.
    """
    if db is None or tenant_id is None:
        return []
    try:
        return db.query(Guardian).filter(Guardian.tenant_id == tenant_id).all()
    except Exception:  # noqa: BLE001
        # C1 / Constitución VII: se registra el hecho, nunca el motivo crudo del driver.
        logger.warning("governance: no se pudieron leer las instancias de guardián del tenant")
        return []


def _credentials_from_guardians(guardians) -> set:
    """Capas cuya credencial de servicio está efectivamente cargada (FR-007).

    La señal es `service_api_key_encrypted` en una fila ACTIVA del tipo correspondiente:
    es el único dato observable desde el backend que distingue "capa habilitada" de "capa
    utilizable". Sin ella, una capa deseada se reporta `requires_credential` en vez de
    declararse activa — que es justo lo que FR-007 prohíbe.
    """
    creds = set()
    for guardian in guardians:
        if not guardian.is_active or not getattr(guardian, "service_api_key_encrypted", None):
            continue
        for layer_key, layer in GOVERNANCE_LAYERS.items():
            if layer.requires_credential and guardian.guardian_type in layer.guardian_types:
                creds.add(layer_key)
    return creds


def _engine_guardrails_for_profile(guardians, profile) -> list:
    """Guardrails del motor que este pedido debe llevar, **filtrados por el perfil**.

    Antes la lista era "todos los guardianes activos con nombre de motor": la postura de
    gobernanza no participaba, así que apagar una capa por modo o por superficie no tenía
    ningún efecto sobre el tráfico del chat (FR-004/FR-005 sin enforcement real).

    Un guardián cuyo `guardian_type` no está en el catálogo se deja pasar **sin cambios**:
    027 no gobierna lo que no cataloga, y excluirlo sería apagar en silencio una capa que
    el cliente configuró. Queda registrado en la atribución por omisión (ninguna entrada lo
    nombra), que es la lectura honesta: no podemos afirmar nada sobre él.
    """
    selected = []
    for guardian in guardians:
        if not guardian.is_active or not getattr(guardian, "engine_guardrail_name", None):
            continue
        layer_key = next((k for k, l in GOVERNANCE_LAYERS.items()
                          if guardian.guardian_type in l.guardian_types), None)
        if layer_key is not None and not profile.is_on(layer_key):
            continue
        selected.append(guardian.engine_guardrail_name)
    return selected


async def _detect_floor_pii(prompt: str, guardians) -> Optional[list]:
    """Detecta la PII del pedido **sin transformar nada** — la capa de PISO ``pii_detection``.

    Hallazgo de la verificación adversarial de la US2: con el enmascarado apagado este
    plano no corría NINGÚN detector —todo el bloque de PII de
    ``GuardianService.process_prompt`` vive dentro de su ``if is_pii_active``— y sin embargo
    la atribución reportaba ``pii_detection: applied/allow``: afirmaba haber mirado y no
    encontrado nada, cuando ni siquiera había mirado. Eso rompía la promesa central de D8,
    que el owner aprobó explícitamente: **apagar el enmascarado no apaga la detección**; el
    pedido queda registrado como "PII detectada, no enmascarada por configuración".

    Mismo enfoque que ``_count_detected_pii`` del plano gateway: se corre el detector y se
    tira todo salvo el **agregado por tipo** —``[{"type","count"}]``, C1: nunca el valor
    detectado— no se muta el prompt, no se arma ``placeholder_map``, no sale nada distinto
    hacia el motor. Lo que cambia respecto del gateway es el DETECTOR:
    acá es el mismo que usa el pipeline del chat, con el vocabulario de entidades y los
    nombres propios del guardián del tenant. Si la rama que enmascara y la que no contaran
    con detectores distintos, la promesa de D8 no sería verificable: cambiaría el hallazgo
    al mover el toggle.

    El ``is_active`` de la fila NO se consulta: la detección es piso y no pide permiso a un
    toggle de la UI (SC-004). La fila aporta solo **vocabulario** (qué entidades y qué
    nombres propios del cliente), y si no existe se usa el default de producto.

    Devuelve el desglose POR TIPO y no un entero pelado porque el hallazgo del piso tiene
    dos lectores con la misma exigencia de verdad: ``applied_layers`` (que solo necesita el
    contador) y la columna legada ``masked_entities``, que es ``[{"type","count"}]`` y es lo
    que leen el informe de cumplimiento y el panel. Un contador sin tipos obligaba a que el
    call-site inventara un tipo o dejara la columna vacía — y "vacía" es justo la mentira
    que se está arreglando. El contador se deriva del desglose (``sum(count)``), así que las
    dos afirmaciones de la fila salen de la MISMA medición y no pueden divergir.

    ``None`` si el detector falla: sin veredicto la capa cae a ``not_configured`` —"no
    pudimos confirmar que corrió"— en vez de un cero tranquilizador, que sería una mentira
    con la forma exacta que 027 existe para eliminar.
    """
    if not prompt:
        return []
    try:
        pii_guardian = next((g for g in guardians if g.guardian_type == "pii_masking"), None)
        config = getattr(pii_guardian, "config", None) or {}
        entities_to_scan = config.get("entities") or list(_DEFAULT_PII_ENTITIES)
        raw_entities = await PresidioService.analyze_text(prompt)
        counts: Dict[str, int] = {}
        for ent in raw_entities:
            etype = ent.get("entity_type")
            if etype in entities_to_scan:
                counts[etype] = counts.get(etype, 0) + 1
        # Los nombres propios del cliente se cuentan como los cuenta el pipeline: una
        # ocurrencia por coincidencia distinta, no por repetición. Y con el MISMO tipo que
        # les pone el enmascarado (`PERSON`), para que mover el toggle no cambie el
        # vocabulario del hallazgo — solo si se enmascaró o no.
        for name in config.get("custom_names", []) or []:
            name = str(name).strip()
            if not name:
                continue
            pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
            hits = len(set(pattern.findall(prompt)))
            if hits:
                counts["PERSON"] = counts.get("PERSON", 0) + hits
        return [{"type": k, "count": v} for k, v in counts.items()]
    except Exception as exc:  # noqa: BLE001
        # C1: se loguea el HECHO, jamás el texto ni el valor detectado.
        logger.warning("governance: la detección de PII (piso) del plano chat falló; "
                       "capa sin veredicto: %s", exc)
        return None


def _summarize_entities(entities) -> list:
    """`[{"type","entity"}, …]` → `[{"type","count"}, …]`.

    El pipeline del chat arrastra el VALOR detectado en `entity` (lo necesita para
    desenmascarar); el evento de la vitrina jamás puede llevarlo (C1). Se agrega por tipo y
    se tira el valor — la misma reducción que hace `AuditService` antes de persistir.
    """
    counts: Dict[str, int] = {}
    for ent in entities or []:
        if not isinstance(ent, dict):
            continue
        etype = ent.get("type", "UNKNOWN")
        counts[etype] = counts.get(etype, 0) + int(ent.get("count", 1) or 1)
    return [{"type": k, "count": v} for k, v in counts.items()]


def _tenant_slug(db: Session, tenant_id) -> Optional[str]:
    """Slug del tenant para el evento de vitrina. Best-effort: un slug ausente empobrece el
    render, pero nada de la vitrina puede afectar la respuesta al cliente."""
    if not tenant_id:
        return None
    try:
        from ..models.tenant import Tenant
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        return getattr(tenant, "slug", None)
    except Exception:  # noqa: BLE001
        return None


async def _publish_block_event(*, db: Session, user, tenant_id, model: str, status: str,
                               prompt: str, entities, attribution) -> None:
    """Evento de monitor **en el punto de bloqueo** del plano chat (contrato §13).

    Hasta ahora los `raise HTTPException` de bloqueo de este endpoint precedían a TODO
    registro: un pedido bloqueado no dejaba fila ni evento, o sea que el caso donde el
    firewall hace su trabajo era justo el único invisible en la vitrina (research D6). Acá
    se publica antes del `raise`, con el mismo esquema que los otros dos productores
    (§8) más `applied_layers`/`blocked_by_layer`.

    **La FILA DURABLE del bloqueo NO es alcance de esta spec** (corte explícito, D6 /
    contrato §14): depende de la completitud de auditoría de la 018. Por eso acá NO se
    reordena el `raise` ni se fuerza un `log_transaction` — se emite la atribución donde
    ocurre el bloqueo, se publica al monitor, y el registro durable llega con la 018.

    Best-effort de punta a punta (§9): cualquier fallo de esta función se traga: la
    respuesta al cliente —incluido el bloqueo— jamás depende de la vitrina.

    El evento lo serializa el emisor del gateway, no una copia local: el contrato §8 exige
    esquema idéntico entre los tres productores, y la única forma de que eso no se
    desincronice es que haya UN serializador. Acá se arma la identidad equivalente —el chat
    no tiene Connection, así que la superficie es constante del plano y el cliente es el
    usuario de sesión— y se delega. Mismo precedente que `inspect.py`.
    """
    try:
        # §10: el preview SIEMPRE display-masked, con pase propio sobre mapa desechable +
        # scrub de secretos, **independientemente** de qué capas alcanzaron a correr. En el
        # punto de bloqueo esto no es un detalle: se bloquea ANTES de que el enmascarado
        # corra, así que sin este pase el evento sería el canal por donde el texto crudo
        # —el que motivó el bloqueo— llega al feed.
        preview = await _gw_plane._safe_preview({"messages": [{"role": "user", "content": prompt}]})
        ident = {
            "tool_type": _CHAT_SURFACE,
            "client_username": getattr(user, "username", None),
            "tenant_slug": _tenant_slug(db, tenant_id),
        }
        _gw_plane._publish_monitor(
            ident, _CHAT_SURFACE, model, status,
            _summarize_entities(entities), preview,
            surface=_CHAT_SURFACE, attribution=attribution,
        )
    except Exception:  # noqa: BLE001
        pass  # vitrina: jamás afecta la request


def _layer_entry(attribution, layer_key: str) -> dict:
    """Entrada de `applied_layers` de una capa. `applied_layers` es exhaustiva sobre el
    perfil, así que la capa siempre está; el default vacío es defensa, no un caso normal."""
    for entry in attribution.applied_layers:
        if entry.get("layer_code") == layer_key:
            return entry
    return {}


def _get_config_path() -> str:
    path = "/app/litellm_config/config.yaml"
    if not os.path.exists(path):
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../litellm/config.yaml"))
    return path


def _check_configured(params: dict, model_full: str) -> bool:
    api_key = params.get("api_key", "")
    if isinstance(api_key, str) and api_key.startswith("os.environ/"):
        env_var = api_key.split("/", 1)[1]
        return bool(os.getenv(env_var, "").strip())
    if api_key:
        return True
    if "bedrock" in model_full:
        return bool(os.getenv("AWS_ACCESS_KEY_ID", "").strip() and os.getenv("AWS_SECRET_ACCESS_KEY", "").strip())
    if "vertex_ai" in model_full:
        return bool(os.getenv("VERTEX_CREDENTIALS", "").strip())
    if "watsonx" in model_full:
        return bool(os.getenv("WATSONX_API_KEY", "").strip())
    if "ollama" in model_full or "host.docker.internal" in params.get("api_base", "") or "localhost" in params.get("api_base", ""):
        return True
    return False

class ChatRequest(BaseModel):
    message: str
    model: str
    override_pii_masking: Optional[bool] = None
    override_gdpr_mode: Optional[bool] = None
    override_ai_act_mode: Optional[bool] = None
    override_headroom_mode: Optional[bool] = None

HUMAN_REVIEW_FLAG_ES = (
    "⚠️ **Pendiente de validación sanitaria.** Esta respuesta ha sido generada por inteligencia artificial "
    "y está siendo revisada por un profesional sanitario. No aplique estas indicaciones hasta recibir confirmación."
)

@router.post("/completions")
async def chat_completions(
    request: ChatRequest,
    http_resp: Response,
    authorization: Optional[str] = Header(None),
    x_processing_purpose: Optional[str] = Header(None, alias="X-Processing-Purpose"),
    db: Session = Depends(get_db)
):
    start_time = time.time()
    
    # 0. Virtual Key / Session Authentication
    user = None
    group = None
    api_key_obj = None
    
    client_key: Optional[str] = None  # forwarded to engine if it's a real engine key

    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "").strip()

        if token.startswith("sk-"):
            # Virtual key path: validate against DB
            import hashlib
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            from ..models.budget import APIKey
            api_key_obj = db.query(APIKey).filter(APIKey.key_hash == token_hash, APIKey.is_active == True).first()
            if not api_key_obj:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Llave virtual (Virtual Key) inválida o inactiva."
                )
            if api_key_obj.user_id:
                user = api_key_obj.user
            if api_key_obj.group_id:
                group = api_key_obj.group
            if api_key_obj.engine_key_token:
                client_key = token
        else:
            # JWT session path: identify the logged-in user and their group
            from ..auth.session import decode_session_token
            from ..models.user import User as UserModel, Group as GroupModel
            payload = decode_session_token(token)
            if payload:
                uid = payload.get("sub")
                if uid:
                    user = db.query(UserModel).filter(UserModel.id == uid, UserModel.is_active == True).first()
                    if user and user.group_id:
                        group = db.query(GroupModel).filter(GroupModel.id == user.group_id).first()
            else:
                # Token present but invalid/expired — reject so the frontend forces re-login
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Sesión expirada. Por favor, vuelve a iniciar sesión.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

    if not user and not group and not api_key_obj:
        # Fail-closed: sin credencial no hay pedido. Acá había un fallback anónimo que
        # llamaba a `get_or_create_default_user`, y ese helper creaba —sin autenticación de
        # ninguna clase— un usuario 'admin' con rol tenant_admin y la contraseña 'admin'
        # (sha256, formato que el verificador sigue aceptando para no dejar afuera a los
        # usuarios ya cargados). O sea: la tercera contraseña por defecto del producto, la
        # única alcanzable por cualquiera en la red. Es lo que specs/014 FR-012 y la
        # Constraint C3 piden cerrar: sin identidad no hay atribución ni gobernanza.
        # Una virtual key válida SIN usuario ni grupo asignado sí sigue pasando (la
        # atribución queda incompleta, pero la credencial existe y es la del cliente).
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida: envía tu sesión o una llave virtual (Virtual Key) "
                   "en la cabecera Authorization.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 1a. Rate Limiting (RPM check before any expensive processing)
    _rpm_remaining = None
    _tpm_remaining = None
    if api_key_obj:
        try:
            _rpm_remaining = check_rpm(api_key_obj.id, api_key_obj.rpm_limit or 60)
        except RateLimitExceeded as e:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=e.message,
                headers={"Retry-After": str(e.retry_after)},
            )

    policy = get_or_create_default_policy(db)

    # 1b. Postura de gobernanza (spec 027 US2) — se resuelve UNA vez, al principio, y es
    # lo que decide qué capas corren en este pedido. Antes cada capa leía su propio flag
    # (policy.is_active, el override del body, la lista completa de guardianes activos):
    # tres fuentes distintas, ninguna consultable, y una postura por alcance imposible de
    # expresar. Ahora la fuente es única y la misma que usan los otros dos planos (D3).
    _tenant_id = getattr(user, "tenant_id", None) or getattr(api_key_obj, "tenant_id", None)
    profile = resolve_tenant_profile(
        db, _tenant_id,
        mode=map_effective_mode(ROUTE_CHAT_UI),
        surface=_CHAT_SURFACE,
        surface_trusted=True,   # la superficie la sabe el endpoint, no la afirma el cliente
        # Tri-estado CRUDO de la columna: None = sin override (la cascada sigue). Colapsarlo
        # a un default acá haría que TODA llave sin toggle presentara un override de nivel
        # Connection, tapando superficie, modo y tenant (contrato resolutor #2).
        connection_overrides=build_connection_overrides(
            getattr(api_key_obj, "redact_enabled", None)),
    )
    # Veredictos que las capas van produciendo a lo largo del pipeline. Se llena a medida
    # que cada capa corre y se convierte en atribución con `build_attribution`: lo que se
    # reporta es lo que REALMENTE pasó, nunca lo que se pretendía que pasara.
    verdicts: Dict[str, Any] = {}
    # El pedido entró por el firewall y va a quedar registrado: eso es el piso, y es lo
    # único que se puede afirmar sin ejecutar nada más.
    _record_verdict(verdicts, "interception_audit", "allow")

    # 1. Budget Enforcement
    user_id_check = user.id if user else None
    group_id_check = group.id if group else None
    
    if not BudgetService.has_sufficient_budget(db, user_id=user_id_check, group_id=group_id_check):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Presupuesto mensual agotado para la llave virtual o el usuario/equipo."
        )

    # 2. Compliance: AI Act Check (Prohibited practices block immediately)
    #
    # La evaluación AI-Act es PISO: ningún alcance puede apagarla (FR-002/SC-004). Por eso
    # el override por-pedido pasa a ser **solo restrictivo**, igual que el header
    # `X-Basa-Redact` del gateway (contrato resolutor #5): puede forzar la evaluación, no
    # saltearla. Sin esta regla, cualquiera que alcance este endpoint —incluido el camino
    # anónimo que cae al usuario por defecto— apagaba una capa de piso mandando un booleano
    # en el body. Ningún input por-request entra a la cascada como relajación.
    ai_act_mode = bool(policy.ai_act_mode)
    if request.override_ai_act_mode is True:
        ai_act_mode = True
    elif request.override_ai_act_mode is False and ai_act_mode:
        logger.info("governance: override AI-Act por pedido ignorado (piso, solo-restrictivo)")

    # La EVALUACIÓN corre SIEMPRE — es piso y no la apaga ningún alcance (FR-002/SC-004).
    # Antes se saltaba entera cuando `policy.ai_act_mode` estaba en off (un toggle que la UI
    # de Seguridad ya expone), y la capa de piso quedaba reportada `not_configured`: el
    # producto no podía decir si el texto pasó la evaluación o si nadie la había hecho.
    #
    # Lo que el toggle sigue decidiendo es si además **GATEA**: el tiering de la evaluación
    # AI-Act (qué evidencia pasa a bloqueo duro) es alcance de la 018, así que acá no se
    # cambia a quién se le bloquea el pedido — solo se deja de mentir sobre si se miró. Por
    # eso `compliance_result`, que alimenta la respuesta y la columna `compliance_status`
    # de la auditoría, conserva EXACTAMENTE la semántica de hoy.
    _ai_act_floor = ComplianceService.evaluate_prompt(request.message, True)
    compliance_result = (_ai_act_floor if ai_act_mode
                         else ComplianceService.evaluate_prompt(request.message, False))
    # La decisión que se registra es la que de verdad se tomó: con el gate apagado, una
    # práctica prohibida detectada se reporta `flag` (evaluada, marcada, no bloqueada) y
    # jamás `block` — `blocked_by_layer` solo puede nombrar a la capa que efectivamente
    # bloqueó (data-model §3.2).
    _record_verdict(verdicts, "ai_act_evaluation", {
        "blocked_prohibited": "block" if ai_act_mode else "flag",
        "flagged_high_risk": "flag",
    }.get(_ai_act_floor["status"], "allow"))
    if compliance_result["status"] == "blocked_prohibited":
        # Punto de bloqueo 1/3 (contrato §13): la atribución se emite ACÁ, antes del raise.
        await _publish_block_event(
            db=db, user=user, tenant_id=_tenant_id, model=request.model,
            status=compliance_result["status"], prompt=request.message, entities=[],
            attribution=build_attribution(profile, verdicts),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=compliance_result["reason"]
        )

    # El enmascarado lo decide la POSTURA, no un flag suelto: `pii_masking` es la capa
    # gobernable que absorbió el toggle `redact_enabled` de la 013 (D8, absorber sin
    # derogar), y su decisión ya resolvió la cascada Connection > superficie > modo >
    # tenant > default de producto. El override por-pedido queda solo-restrictivo por el
    # mismo motivo que el de AI-Act: relajar desde el body es el bypass que 027 cierra.
    is_pii_active = profile.is_on("pii_masking")
    if request.override_pii_masking is True:
        is_pii_active = True
    elif request.override_pii_masking is False and is_pii_active:
        logger.info("governance: override de enmascarado por pedido ignorado (solo-restrictivo)")

    # 3. Run prompt through the Security Guardians (PII, Secret Detection, Sensitive Routing)
    #
    # `override_secret_detection=True` es SC-004 aplicado donde se puede aplicar hoy: el
    # bloqueo de secretos es piso (D8) y hasta acá dependía de `guardian.is_active`, un
    # toggle que la UI de Seguridad expone — o sea que el piso era apagable con un clic. El
    # override lo fuerza sin tocar el archivo que ejecuta: `process_prompt` acepta la señal
    # y su rama sabe funcionar sin fila (acción BLOCK por defecto). Cambio de comportamiento
    # observable: desactivar ese guardián deja de desactivar el escaneo en este plano.
    #
    # `pii_masking` NO se fuerza: es la capa gobernable (D8), y su override ya viene de la
    # postura resuelta. La DETECCIÓN —que sí es piso— se cubre aparte, más abajo, porque
    # `process_prompt` conflaba detectar con enmascarar en el mismo `if`.
    guardian_overrides = {
        "override_pii_masking": is_pii_active,
        "override_secret_detection": True,
    }

    guardian_res = await GuardianService.process_prompt(
        db=db,
        prompt=request.message,
        selected_model=request.model,
        overrides=guardian_overrides
    )

    # Catálogo de guardianes DEL TENANT: hace falta para traducir triggers → capas, para
    # saber qué credenciales hay cargadas y para filtrar los guardrails del motor por
    # perfil. Una sola lectura, filtrada por tenant (Constitución III — ver
    # `_guardians_of_tenant`, que documenta por qué el filtro va acá aunque el lado que
    # ejecuta todavía no lo tenga).
    _guardians = _guardians_of_tenant(db, _tenant_id)
    _name_to_type = _guardian_type_by_name(_guardians)
    _credentials = _credentials_from_guardians(_guardians)
    _verdicts_from_triggers(guardian_res["triggers"], _name_to_type, verdicts)

    # ── Piso `pii_detection`: la detección corre SIEMPRE (D8 / FR-002) ────────────────
    #
    # Antes la atribución se leía de `entities_detected`, que solo existe cuando el
    # ENMASCARADO corrió: con `pii_masking=off` no corría ningún detector y la capa de piso
    # igual se reportaba `applied/allow` —"miré y no había"— sin haber mirado. Ahora hay
    # tres situaciones y cada una produce lo que de verdad se puede afirmar:
    #
    #   * la etapa de PII bloqueó el pedido  ⇒ el veredicto `block` de los triggers YA es el
    #     hallazgo de la capa; no hay contador honesto que agregarle;
    #   * el enmascarado corrió              ⇒ el hallazgo son las entidades que enmascaró;
    #   * el enmascarado NO corrió (apagado por la postura, o el pedido se bloqueó por
    #     secreto antes de llegar a esa etapa) ⇒ se corre el detector aparte, sobre el
    #     prompt, sin transformar nada.
    #
    # La tercera rama es la que hace verdadera la promesa de D8: `pii_detection: applied
    # [count]` + `pii_masking: skipped` ES el registro "PII detectada, no enmascarada por
    # configuración" (la frase la renderiza la UI desde los códigos; C1: el JSONB nunca
    # lleva texto). Y también cubre el camino de BLOQUEO: una capa inapagable que corrió no
    # puede quedar reportada como "sin información" justo en el pedido que el firewall
    # rechazó.
    _entities = guardian_res["entities_detected"]
    _pii_blocked = verdicts.get("pii_detection", {}).get("decision") == "block"
    # El escaneo de secretos precede a todo y corta la pasada: si bloqueó, la etapa de PII
    # nunca llegó a ejecutarse, por más que la postura la tuviera encendida.
    _masking_ran = is_pii_active and verdicts.get("secret_detection", {}).get("decision") != "block"

    # El hallazgo del piso se guarda **desglosado por tipo** (`[{"type","count"}]`) y no como
    # un entero: es la misma medición que después alimenta las columnas legadas de la fila
    # de auditoría (ver `_pii_row_*` antes del `log_transaction`). Una sola medición, dos
    # lectores — es la única forma de que la fila no pueda contradecirse a sí misma.
    if _pii_blocked:
        _floor_entities = None
    elif _masking_ran:
        _floor_entities = _summarize_entities(_entities)
    else:
        _floor_entities = await _detect_floor_pii(request.message, _guardians)
    _detected = (None if _floor_entities is None
                 else sum(int(e.get("count", 1) or 1) for e in _floor_entities))
    if _detected is not None:
        _record_verdict(verdicts, "pii_detection", "flag" if _detected else "allow",
                        count=_detected or None)

    if _masking_ran and not _pii_blocked:
        # Una capa que está ON y CORRIÓ se reporta `applied` con su decisión —`allow`
        # cuando no encontró nada—, haya o no entidades. Antes esto vivía dentro de un
        # `if _entities:`, así que para un texto SIN datos personales el chat reportaba
        # `not_configured/null` mientras el gateway reportaba `applied/allow` para la MISMA
        # postura: dos call-sites describiendo distinto la misma configuración rompen el
        # contrato del resolutor único (D3/SC-003). `not_configured` significa "no hay
        # información", nunca "no encontró nada".
        _record_verdict(verdicts, "pii_masking", "mask" if _entities else "allow",
                        count=len(_entities) or None)
    # El escaneo de secretos se fuerza ON más arriba (piso, SC-004), así que a esta altura
    # SIEMPRE corrió: si los triggers no reportaron nada, el `allow` es afirmable.
    if "secret_detection" not in verdicts:
        _record_verdict(verdicts, "secret_detection", "allow")

    # ── Qué queda del piso fuera del alcance de este archivo (SC-004) ────────────────
    # Las tres capas de piso de este plano ya no dependen de un toggle de la UI: la
    # evaluación AI-Act corre siempre (el toggle solo decide si además gatea, tiering =
    # 018), el escaneo de secretos se fuerza por override, y la detección de PII corre en
    # su propia pasada cuando el enmascarado está apagado. Pero el arreglo es **por
    # call-site, no estructural**: quien de verdad conflaba detectar con enmascarar (un
    # único `if is_pii_active` que envuelve el bloque entero) y quien lee `guardians` sin
    # filtro de tenant es `GuardianService.process_prompt`, hoy bloqueado por el PR #21
    # (spec 016). Mientras eso siga así, otro call-site que llame a `process_prompt` sin
    # pasar estos overrides vuelve a tener el piso apagable, y un trigger emitido por un
    # guardián de otro tenant puede quedar sin traducir a capa. El cierre estructural —el
    # que hace que el piso no sea representable como apagado en ningún caller— es de la
    # tarea que reescribe ese servicio, no de este archivo.

    if guardian_res["blocked"]:
        # Punto de bloqueo 2/3 (contrato §13). `blocked_by_layer` sale del veredicto de la
        # capa que bloqueó —`secret_detection` o `pii_detection`— y JAMÁS del nombre del
        # guardián, que es editable y white-label (D6).
        await _publish_block_event(
            db=db, user=user, tenant_id=_tenant_id, model=request.model,
            status="blocked_by_policy", prompt=request.message, entities=_entities,
            attribution=build_attribution(profile, verdicts, credentials=_credentials),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=guardian_res["block_reason"]
        )

    masked_prompt = guardian_res["prompt"]
    routed_model = guardian_res["model"]
    placeholder_map = guardian_res["placeholder_map"]
    entities_detected = guardian_res["entities_detected"]
    guardian_triggers = guardian_res["triggers"]

    # 4. Layer 1.5: Context Optimization (Ahorro de Costes IA — spec 012)
    optimized_prompt = masked_prompt
    tokens_saved = 0
    strategy_applied = "none"
    compression_reversed = False  # spec 012 US6 — guardia de reversión

    # Resolver config de compresión: override request > grupo > política global
    comp_cache_enabled = True
    if request.override_headroom_mode is not None:
        is_headroom_active = request.override_headroom_mode
        comp_strategy = "deterministic"
        comp_threshold = OptimizationService.DEFAULT_THRESHOLD
        comp_aggressiveness = "medium"
    elif group is not None and getattr(group, "compression_mode", "off") not in (None, "off"):
        is_headroom_active = True
        comp_strategy = group.compression_mode  # 'deterministic' | 'headroom'
        comp_threshold = group.compression_threshold_tokens or OptimizationService.DEFAULT_THRESHOLD
        comp_aggressiveness = group.compression_aggressiveness or "medium"
        comp_cache_enabled = bool(getattr(group, "compression_cache_enabled", True))
    else:
        _pol_comp = getattr(policy, "compression_mode", None)
        if _pol_comp is None:
            _pol_comp = getattr(policy, "headroom_mode", False)
        is_headroom_active = bool(_pol_comp)
        comp_strategy = "deterministic"
        comp_threshold = OptimizationService.DEFAULT_THRESHOLD
        comp_aggressiveness = "medium"

    if is_headroom_active:
        # Auto-detect contenido estructurado -> headroom incluso si la estrategia dice deterministic
        stripped = masked_prompt.lstrip()
        eff_strategy = "headroom" if (comp_strategy == "headroom" or stripped.startswith("{") or stripped.startswith("[")) else "deterministic"
        optimized_prompt, tokens_saved = OptimizationService.compress_context(
            masked_prompt, True, comp_threshold, comp_aggressiveness, eff_strategy,
            cache_enabled=comp_cache_enabled,
        )
        strategy_applied = eff_strategy if tokens_saved > 0 else "none"

    # 5. Layer 2: GDPR (flag de política, visible en pipeline_metadata). El
    # renombrado legacy a aliases "-eu" hardcodeados se ELIMINÓ (pre-piloto
    # 2026-07-22): un cliente 0km no hereda residuos del demo — la residencia
    # EU real la aplica el enforcement data-driven de ComplianceProject
    # (eu_region_required, más abajo), nunca una tabla en código.
    is_gdpr_active = request.override_gdpr_mode if request.override_gdpr_mode is not None else policy.gdpr_mode

    # 5b. Compliance — resolve project via hierarchy: key → user → group → global
    from datetime import timedelta
    from ..models.budget import APIKey as APIKeyModel

    resolved_project = None
    # 1. Key-level
    if api_key_obj and getattr(api_key_obj, "compliance_project_id", None):
        resolved_project = db.query(ComplianceProject).filter(
            ComplianceProject.id == api_key_obj.compliance_project_id,
            ComplianceProject.is_active == True
        ).first()
    # 2. User-level
    if not resolved_project and user and getattr(user, "compliance_project_id", None):
        resolved_project = db.query(ComplianceProject).filter(
            ComplianceProject.id == user.compliance_project_id,
            ComplianceProject.is_active == True
        ).first()
    # 3. Group-level
    if not resolved_project and group and getattr(group, "compliance_project_id", None):
        resolved_project = db.query(ComplianceProject).filter(
            ComplianceProject.id == group.compliance_project_id,
            ComplianceProject.is_active == True
        ).first()
    # 4. Global fallback
    active_projects = [resolved_project] if resolved_project else []

    _applied_project_name = resolved_project.name if resolved_project else None
    _applied_risk_level = (
        getattr(api_key_obj, "risk_level", None) or  # not stored on key, but future-proof
        (getattr(user, "risk_level", None) if user else None) or
        (getattr(group, "default_risk_level", None) if group else None)
    )
    _applied_legal_basis = (
        (getattr(user, "legal_basis", None) if user else None) or
        (getattr(group, "default_legal_basis", None) if group else None)
    )
    _user_group_id = group.id if group else None

    # EU region enforcement
    eu_safe_prefixes = ("azure-", "bedrock-", "vertex-", "ollama-")
    for proj in active_projects:
        if proj.eu_region_required and not any(routed_model.startswith(p) for p in eu_safe_prefixes):
            logger.warning("EU region enforcement blocked model %s for project %s", routed_model, proj.name)
            # Punto de bloqueo 3/3 (contrato §13). Este bloqueo sale de la residencia de
            # datos del proyecto de cumplimiento, que **no es una capa del registry**: se
            # publica el evento con la atribución de lo que sí corrió y `blocked_by_layer`
            # queda en NULL. Atribuírselo a `ai_act_evaluation` porque "suena a
            # cumplimiento" sería falsear el registro — y falsear la atribución es
            # exactamente lo que esta spec existe para terminar. Si la residencia debe ser
            # gobernable y atribuible, entra al catálogo por su propia spec.
            await _publish_block_event(
                db=db, user=user, tenant_id=_tenant_id, model=routed_model,
                status="blocked_residency", prompt=request.message, entities=_entities,
                attribution=build_attribution(profile, verdicts, credentials=_credentials),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="La política de residencia de datos exige procesamiento en la UE. El modelo seleccionado no está disponible para esta solicitud."
            )

    # Determine if AI disclosure and human review apply
    _deliver_disclosure = False
    _disclosure_message = None
    _review_token_val = None
    _human_review_flag = False   # hybrid model: flag without blocking

    for proj in active_projects:
        if proj.ai_disclosure_enabled and not _deliver_disclosure:
            one_hour_ago = datetime.utcnow() - timedelta(hours=1)
            recent = db.query(AuditLog).filter(
                AuditLog.api_key_id == (api_key_obj.id if api_key_obj else None),
                AuditLog.timestamp >= one_hour_ago,
                AuditLog.ai_disclosure_delivered == True
            ).first()
            if not recent:
                _deliver_disclosure = True
                _disclosure_message = proj.ai_disclosure_message or DEFAULT_DISCLOSURE_ES
        if proj.human_review_required and not _review_token_val:
            _review_token_val = uuid.uuid4()
            _human_review_flag = True

    # 6. Layer 3: LLM Execution with active guardrails
    llm_raw_response = ""
    prompt_tokens = len(optimized_prompt) // 4  # Estimate
    completion_tokens = 0
    guardian_events: list = []

    logger.info(f"Sending request to AI engine: model={routed_model}")
    actual_cost = None
    raw_request_json = None
    raw_response_json = None

    # Guardrails del motor para este pedido: la lista sale del PERFIL, no de "todo lo que
    # esté activo" (FR-004/FR-005 — sin este filtro, apagar una capa por modo o superficie
    # no tenía ningún efecto sobre el tráfico del chat). Se reemplaza
    # `ai_engine_client.get_active_guardrail_names`, que devuelve nombres sin el tipo y por
    # lo tanto no permite mapear cada guardrail a su capa.
    active_engine_guardrails = _engine_guardrails_for_profile(_guardians, profile)

    try:
        async with httpx.AsyncClient() as client:
            raw_request_json = {
                "model": routed_model,
                "messages": [{"role": "user", "content": optimized_prompt}],
                "temperature": 0.3
            }
            if active_engine_guardrails:
                raw_request_json["guardrails"] = active_engine_guardrails

            engine_auth_key = client_key if client_key else _ENGINE_MASTER_KEY
            response = await client.post(
                f"{_ENGINE_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {engine_auth_key}",
                    "Content-Type": "application/json"
                },
                json=raw_request_json,
                timeout=_ENGINE_TIMEOUT_SECONDS
            )
            if response.status_code == 200:
                res_data = response.json()
                llm_raw_response = res_data["choices"][0]["message"]["content"]
                prompt_tokens = res_data["usage"]["prompt_tokens"]
                completion_tokens = res_data["usage"]["completion_tokens"]
                raw_response_json = res_data

                # Capture guardrail events returned by the engine (if any)
                guardian_events = res_data.get("guardrail_info", {}).get("guardrail_events", []) or []

                # Extract exact cost from engine headers
                cost_str = response.headers.get("x-litellm-response-cost")

                # --- Guardia de calidad (spec 012 US6) — reversión ante anomalía ---
                # Si se aplicó compresión y la respuesta es anómala (vacía/muy corta),
                # reintenta UNA vez con el prompt original (sin comprimir) y marca el
                # evento. Solo se activa cuando hubo compresión real (raro). Fail-open:
                # cualquier fallo del reintento deja la respuesta original intacta.
                if (
                    _REVERSAL_GUARD
                    and tokens_saved > 0
                    and OptimizationService.response_is_anomalous(llm_raw_response, completion_tokens)
                ):
                    logger.warning(
                        "compression reversal guard triggered (tokens_saved=%s, completion_tokens=%s) "
                        "— retrying with the original uncompressed prompt",
                        tokens_saved, completion_tokens,
                    )
                    try:
                        reversal_req = dict(raw_request_json)
                        reversal_req["messages"] = [{"role": "user", "content": masked_prompt}]
                        rev_response = await client.post(
                            f"{_ENGINE_URL}/v1/chat/completions",
                            headers={
                                "Authorization": f"Bearer {engine_auth_key}",
                                "Content-Type": "application/json",
                            },
                            json=reversal_req,
                            timeout=_ENGINE_TIMEOUT_SECONDS,
                        )
                        if rev_response.status_code == 200:
                            rev_data = rev_response.json()
                            rev_content = rev_data["choices"][0]["message"]["content"]
                            # Solo aceptar el reintento si mejora la respuesta
                            if rev_content and len(rev_content.strip()) > len((llm_raw_response or "").strip()):
                                llm_raw_response = rev_content
                                prompt_tokens = rev_data["usage"]["prompt_tokens"]
                                completion_tokens = rev_data["usage"]["completion_tokens"]
                                raw_response_json = rev_data
                                tokens_saved = 0  # se descuenta el ahorro: se usó el prompt original
                                strategy_applied = "none"
                                compression_reversed = True
                                rev_cost = rev_response.headers.get("x-litellm-response-cost")
                                if rev_cost:
                                    try:
                                        actual_cost = Decimal(rev_cost)
                                    except Exception:
                                        pass
                                logger.info("compression reversal succeeded — original prompt restored")
                    except Exception as rev_err:  # fail-open: nunca rompe el flujo
                        logger.warning("compression reversal retry failed (%s) — keeping original response", rev_err)
                if cost_str:
                    try:
                        actual_cost = Decimal(cost_str)
                    except Exception:
                        pass
            elif response.status_code == 400:
                # Un 400 del motor NO siempre es un guardrail: puede ser un
                # modelo inexistente/config inválida. Conflarlos mandaba el
                # diagnóstico al lado equivocado (ensayo pre-piloto 2026-07-22).
                body_lower = (response.text or "").lower()
                if "bloqueada" in body_lower or "guardrail" in body_lower or "basa" in body_lower:
                    logger.warning("AI engine blocked request (guardrail): %s", response.text)
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="La petición fue bloqueada por las políticas de seguridad configuradas."
                    )
                logger.error("AI engine rejected request (config/modelo): %s", response.text)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El modelo solicitado no está disponible en el gateway. Verificá el catálogo de modelos."
                )
            else:
                logger.error("AI engine returned status %s: %s", response.status_code, response.text)
                error_detail = "Basa Gateway error"
                try:
                    error_json = response.json()
                    if "error" in error_json and "message" in error_json["error"]:
                        error_detail = error_json["error"]["message"]
                except Exception:
                    error_detail = response.text

                # White-label
                error_detail = error_detail.replace("litellm", "Basa Gateway").replace("LiteLLM", "Basa Gateway")
                if "litellm." in error_detail:
                    parts = error_detail.split(":", 1)
                    if len(parts) > 1:
                        error_detail = parts[1].strip()

                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Error del modelo ({routed_model}): {error_detail}"
                )
                
    except HTTPException:
        raise
    except Exception as e:
        # Check if we were able to reach the server. If yes, it's a model execution error.
        if "response" in locals() and response is not None:
            err_msg = str(e)
            if "litellm." in err_msg:
                parts = err_msg.split(":", 1)
                if len(parts) > 1:
                    err_msg = parts[1].strip()
            err_msg = err_msg.replace("litellm", "Basa Gateway").replace("LiteLLM", "Basa Gateway")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al ejecutar el modelo: {err_msg}"
            )
            
        # No response object => we never reached the AI engine (connection refused / timeout).
        # Fail-closed: do NOT fabricate a response. LiteLLM handles model-level fallbacks
        # (router_settings.fallbacks) and retries (num_retries) on its side; if it is unreachable
        # the gateway cannot serve inference and must surface the outage honestly.
        logger.error("AI engine unreachable, failing closed (no simulated response): %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="El motor de IA no está disponible. Reintente en unos minutos.",
        )

    # 6b. TPM check (after LLM: we now know actual token counts)
    if api_key_obj:
        try:
            _tpm_remaining = check_tpm(
                api_key_obj.id,
                api_key_obj.tpm_limit or 100000,
                prompt_tokens + completion_tokens,
            )
        except RateLimitExceeded as e:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=e.message,
                headers={"Retry-After": str(e.retry_after)},
            )

    # 7. Layer 4: Unmasking
    final_response = PresidioService.unmask_text(llm_raw_response, placeholder_map)

    # Apply AI disclosure (prepend if this is a new session)
    if _deliver_disclosure and _disclosure_message:
        final_response = f"ℹ️ {_disclosure_message}\n\n{final_response}"

    # Hybrid man-in-the-loop: append flag at the end (response delivered, not blocked)
    if _human_review_flag:
        final_response = f"{final_response}\n\n---\n{HUMAN_REVIEW_FLAG_ES}"

    # 8. Logging and Budget Update
    latency_ms = int((time.time() - start_time) * 1000)
    cost = actual_cost if actual_cost is not None else BudgetService.calculate_cost(request.model, prompt_tokens, completion_tokens)

    # Store human review record if required — save the AI response (not the prompt)
    if _review_token_val:
        # Strip the review flag banner before storing so the reviewer sees the clean response
        clean_response = llm_raw_response if llm_raw_response else final_response.split("\n\n---\n")[0]
        review_entry = HumanReview(
            review_token=_review_token_val,
            created_at=datetime.utcnow().isoformat(),
            response_text=clean_response,
        )
        db.add(review_entry)
        db.flush()

    # Ahorro USD real (spec 012 US3) — calculado sobre el modelo final enrutado
    cost_saved_usd = Decimal("0")
    if tokens_saved > 0:
        from ..services.budget_service import MODEL_PRICING
        _pricing = MODEL_PRICING.get(routed_model, MODEL_PRICING.get("default"))
        cost_saved_usd = (Decimal(tokens_saved) / Decimal("1000000")) * _pricing["input"]

    # Atribución final del pedido (FR-009, SC-005): exhaustiva sobre el perfil — TODA capa
    # aparece con su status, también las que no corrieron, porque sin eso "no la aplicamos"
    # y "no está protegido" vuelven a ser indistinguibles.
    #
    # Lo que NO se puede afirmar, no se afirma: las capas del motor (moderación,
    # anti-inyección, safety, guardrails de proveedor) se le PIDEN al motor en `guardrails`,
    # pero el motor **ignora en silencio** los nombres que no conoce (D4) y todavía no
    # devuelve atribución propia — eso es T025 (`basa_guardrail.py`), bloqueada por el
    # PR #21. Así que acá no se les fabrica veredicto: quedan `requires_credential` cuando
    # están deseadas sin credencial cargada, y `not_configured` cuando están deseadas y
    # cableadas pero sin confirmación de ejecución. El día que el guardrail escriba su
    # atribución, este call-site la incorpora sin cambiar de diseño.
    attribution = build_attribution(profile, verdicts, credentials=_credentials)

    # ── Columnas legadas de PII: la fila no puede contradecirse a sí misma ────────────
    #
    # Hallazgo de la ronda adversarial: `pii_detected` se derivaba de `entities_detected`,
    # que solo tiene contenido cuando el ENMASCARADO corrió. Con `pii_masking=off` la MISMA
    # fila decía `applied_layers: {pii_detection, applied, flag, count: 3}` y a la vez
    # `pii_detected=false` / `masked_entities=null`. Es la peor combinación posible: un
    # informe Art.30, el panel o cualquier query histórica —que leen las columnas legadas,
    # no el JSONB nuevo— afirmaban "no hubo datos personales" justo en los pedidos donde SÍ
    # los hubo y encima salieron sin enmascarar.
    #
    # SEMÁNTICA ELEGIDA (documentada acá porque el NOMBRE de la columna miente por historia
    # y no se puede renombrar sin romper a sus lectores):
    #
    #   * `pii_detected`   = hubo datos personales en el pedido. Es la DETECCIÓN (el piso),
    #                        no el enmascarado. Responde "¿este pedido llevaba PII?".
    #   * `masked_entities`= el desglose `[{type, count}]` de lo DETECTADO — metadata pura,
    #                        C1: jamás el valor. Mismo formato de siempre, así que el panel
    #                        y el export siguen leyendo igual.
    #
    # El matiz que las columnas legadas NO pueden expresar —"detectado pero no
    # enmascarado"— se resuelve del lado de la coherencia: las columnas afirman el piso (lo
    # verdadero y lo más protector para un informe), y si algo se NEUTRALIZÓ o no lo dice
    # `applied_layers` de la misma fila (`pii_masking: applied` vs `skipped`), que es el
    # registro nuevo y el que la 027 hace autoritativo. Una fila puede ahora decir "hubo 3
    # datos personales, el enmascarado estaba apagado por decisión" — antes decía "no hubo
    # nada" y a la vez "detecté 3".
    #
    # `_floor_entities is None` = el detector no pudo confirmar nada (falla del piso; el
    # camino de bloqueo no llega hasta acá, hace `raise` antes). Ahí se cae a lo que el
    # enmascarado sí produjo: es menos que la verdad pero nunca es una afirmación falsa —
    # nunca dice "no hubo PII" habiendo enmascarado alguna.
    _pii_row_entities = (_summarize_entities(entities_detected) if _floor_entities is None
                         else _floor_entities)
    _pii_row_detected = bool(_pii_row_entities)

    # Save to Audit Log
    audit_log = AuditService.log_transaction(
        db=db,
        model=request.model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=float(cost),
        pii_detected=_pii_row_detected,
        masked_entities=_pii_row_entities,
        compliance_status=compliance_result["status"],
        latency_ms=latency_ms,
        tokens_saved_by_optimization=tokens_saved,
        cost_saved_usd=float(cost_saved_usd),
        compression_strategy=strategy_applied,        # spec 012 US6 — telemetría por estrategia
        compression_reversed=compression_reversed,    # spec 012 US6 — guardia de reversión
        user_id=user.id if user else None,
        api_key_id=api_key_obj.id if api_key_obj else None,
        guardian_events=(guardian_triggers or []) + (guardian_events or []),
        # Atribución 027. `guardian_events` sigue igual, congelado como legado (D6: la
        # hash-chain de licencias lo relee posicionalmente); las columnas nuevas viven al
        # lado y son las que el dashboard y el monitor pasan a consultar.
        applied_layers=attribution.applied_layers,
        blocked_by_layer=attribution.blocked_by_layer,
        review_token=_review_token_val,
        ai_disclosure_delivered=_deliver_disclosure,
        processing_purpose=x_processing_purpose,
        user_group_id=_user_group_id,
        # La atribución 027 se scopea al tenant que HIZO el pedido (el mismo `_tenant_id` con
        # que se resolvió el perfil), no al DEFAULT: sin esto la evidencia de gobernanza de un
        # tenant no-default queda contabilizada contra otro. `log_transaction` solo lo aplica
        # si no es None, así que en el deploy de tenant único no cambia nada.
        tenant_id=_tenant_id,
    )

    # Link review record to audit log
    if _review_token_val and audit_log:
        review_entry.audit_log_id = audit_log.id
        db.commit()
    
    # Deduct from Budget
    BudgetService.update_budget(
        db=db,
        user_id=user.id if user else None,
        group_id=group.id if group else None,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        model=request.model,
        override_cost=Decimal(str(cost))
    )

    # Attach rate limit headers if a virtual key was used
    if api_key_obj:
        if _rpm_remaining is not None:
            http_resp.headers["X-RateLimit-Remaining-Requests"] = str(_rpm_remaining)
        if _tpm_remaining is not None:
            http_resp.headers["X-RateLimit-Remaining-Tokens"] = str(_tpm_remaining)

    # Return complete metadata package for the UI layer animation
    #
    # `pipeline_metadata` pasa a **derivarse** de `applied_layers` en vez de armarse a mano
    # con banderas hardcodeadas (Principio VIII / data-model §3.2): antes cada `active` era
    # una variable local que decía lo que se *pretendía* hacer, así que la UI podía pintar
    # una capa verde aunque no hubiera corrido. Ahora el estado que se muestra es el mismo
    # que quedó en la fila de auditoría — una sola verdad, un solo productor.
    #
    # `governance` es la atribución completa y es lo que la UI debe leer de acá en más; los
    # bloques `layer_*` se mantienen porque el playground los renderiza hoy. OJO C1:
    # `original_prompt` es texto crudo que se le devuelve a quien lo escribió (es su propio
    # prompt, en su propia respuesta) y por eso puede seguir acá — pero JAMÁS entra a
    # `applied_layers` ni a ningún evento: la atribución es solo códigos y contadores.
    _masking_entry = _layer_entry(attribution, "pii_masking")
    _detection_entry = _layer_entry(attribution, "pii_detection")
    return {
        "response": final_response,
        "pipeline_metadata": {
            "guardian_triggers": guardian_triggers,
            "governance": {
                "mode": profile.mode,
                "surface": profile.surface,
                "applied_layers": attribution.applied_layers,
                "blocked_by_layer": attribution.blocked_by_layer,
            },
            "layer_masking": {
                # Derivado: la capa está "activa" si REALMENTE se aplicó en este pedido.
                "active": _masking_entry.get("status") == "applied",
                "layer_status": _masking_entry.get("status"),
                # D8 hecho visible: detección aplicada + enmascarado apagado por
                # configuración = "datos personales detectados, no enmascarados".
                "detection_status": _detection_entry.get("status"),
                "original_prompt": request.message,
                "masked_prompt": masked_prompt,
                "entities_detected": entities_detected
            },
            "layer_optimization": {
                "active": is_headroom_active,
                "strategy_applied": strategy_applied,
                "original_length": len(masked_prompt),
                "optimized_length": len(optimized_prompt),
                "tokens_saved": tokens_saved,
                "cost_saved_usd": float(cost_saved_usd),
                "reversed": compression_reversed
            },
            "layer_compliance": {
                "gdpr_active": is_gdpr_active,
                "routed_model": routed_model,
                "ai_act_status": compliance_result["status"],
                "ai_act_reason": compliance_result["reason"],
                # Derivado: distingue "evaluado y pasó" de "no se evaluó" — con
                # `ai_act_mode` apagado en la política, `ai_act_status` dice 'passed' sin
                # que nadie haya mirado el texto, y esa ambigüedad es la que 027 elimina.
                "ai_act_layer_status": _layer_entry(attribution, "ai_act_evaluation").get("status"),
                "applied_project": _applied_project_name,
                "applied_risk_level": _applied_risk_level,
                "applied_legal_basis": _applied_legal_basis,
                "ai_disclosure_delivered": _deliver_disclosure,
                "human_review_pending": _human_review_flag,
                "review_token": str(_review_token_val) if _review_token_val else None,
                "processing_purpose": x_processing_purpose,
            },
            "layer_llm": {
                "model_used": routed_model,
                "latency_ms": latency_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": float(cost),
                "raw_request_json": raw_request_json,
                "raw_response_json": raw_response_json
            },
            "layer_unmasking": {
                "raw_response": llm_raw_response,
                "unmasked_response": final_response
            }
        }
    }

class ModelCreateSchema(BaseModel):
    model_name: str
    provider: str
    model_id: str
    api_key: Optional[str] = None
    api_base: Optional[str] = None

@router.get("/models", dependencies=[Depends(require_authenticated())])
async def list_available_models():
    config_path = _get_config_path()
    try:
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f) or {}

        result = []
        for m in config_data.get("model_list", []):
            params = m.get("litellm_params", {})
            model_full = params.get("model", "")
            provider = "local"
            model_id = model_full
            if "/" in model_full:
                provider, model_id = model_full.split("/", 1)
            result.append({
                "model_name": m.get("model_name"),
                "provider": provider,
                "model_id": model_id,
                "api_base": params.get("api_base"),
                "is_configured": _check_configured(params, model_full),
                "is_eu_compliant": provider in _EU_COMPLIANT_PROVIDERS,
            })
        return result
    except Exception as e:
        logger.warning("Failed to read models from config.yaml: %s", e)
        return []

@router.post("/models", dependencies=[Depends(require_role("admin", "developer"))])
async def register_model(model_in: ModelCreateSchema):
    config_path = "/app/litellm_config/config.yaml"
    if not os.path.exists(config_path):
        config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../litellm/config.yaml"))
    
    try:
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Failed to read litellm config: {e}")
        raise HTTPException(status_code=500, detail="Failed to read model configuration")

    if "model_list" not in config_data:
        config_data["model_list"] = []

    for m in config_data["model_list"]:
        if m.get("model_name") == model_in.model_name:
            raise HTTPException(status_code=400, detail="Model name already exists")

    litellm_params = {
        "model": f"{model_in.provider}/{model_in.model_id}" if model_in.provider != "local" else model_in.model_id
    }
    if model_in.api_key:
        litellm_params["api_key"] = model_in.api_key
    if model_in.api_base:
        litellm_params["api_base"] = model_in.api_base

    new_model_entry = {
        "model_name": model_in.model_name,
        "litellm_params": litellm_params
    }

    config_data["model_list"].append(new_model_entry)

    try:
        with open(config_path, "w") as f:
            yaml.safe_dump(config_data, f, default_flow_style=False)
    except Exception as e:
        logger.error(f"Failed to write litellm config: {e}")
        raise HTTPException(status_code=500, detail="Failed to save model configuration")

    return {"status": "success", "message": f"Model {model_in.model_name} registered successfully"}

@router.delete("/models/{model_name}", dependencies=[Depends(require_role("admin", "developer"))])
async def delete_model(model_name: str):
    config_path = _get_config_path()
    try:
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error("Failed to read config: %s", e)
        raise HTTPException(status_code=500, detail="Failed to read model configuration")

    if "model_list" not in config_data:
        raise HTTPException(status_code=404, detail="No models configured")

    original_len = len(config_data["model_list"])
    config_data["model_list"] = [m for m in config_data["model_list"] if m.get("model_name") != model_name]
    if len(config_data["model_list"]) == original_len:
        raise HTTPException(status_code=404, detail="Model not found")

    try:
        with open(config_path, "w") as f:
            yaml.safe_dump(config_data, f, default_flow_style=False)
    except Exception as e:
        logger.error("Failed to write config: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save model configuration")

    return {"status": "success", "message": f"Model {model_name} deleted successfully"}


class ModelCredentialSchema(BaseModel):
    # Identificador del CONTRATO WIRE con el motor (allowlisted en los checks de marca
    # blanca); el title explícito evita que el titulado automático exponga el vendor
    # en el OpenAPI publicado (constitución VII).
    litellm_params: Optional[dict] = Field(default=None, title="Parámetros del motor")


@router.patch("/models/{model_name}", dependencies=[Depends(require_role("admin", "developer"))])
async def update_model_credential(model_name: str, body: ModelCredentialSchema):
    """Merge de credenciales del motor (campos del contrato litellm_params) en config.yaml."""
    config_path = _get_config_path()
    try:
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error("Failed to read config: %s", e)
        raise HTTPException(status_code=500, detail="Failed to read model configuration")

    found = False
    for m in config_data.get("model_list", []):
        if m.get("model_name") == model_name:
            if body.litellm_params:
                m.setdefault("litellm_params", {}).update(
                    {k: v for k, v in body.litellm_params.items() if v}
                )
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail="Model not found")

    try:
        with open(config_path, "w") as f:
            yaml.safe_dump(config_data, f, default_flow_style=False)
    except Exception as e:
        logger.error("Failed to write config: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save model configuration")

    return {"status": "success", "message": f"Model {model_name} updated"}


# --- Fallback configuration ---

class FallbackBody(BaseModel):
    fallback_model: Optional[str] = None


@router.get("/fallbacks", dependencies=[Depends(require_role("admin", "developer"))])
async def get_fallbacks():
    """Returns the current fallback map: {model_name: fallback_model_name}."""
    config_path = _get_config_path()
    try:
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f) or {}
        raw = config_data.get("router_settings", {}).get("fallbacks", [])
        result: dict = {}
        for item in raw:
            for k, v in item.items():
                result[k] = v[0] if v else None
        return result
    except Exception:
        return {}


@router.put("/fallbacks/{model_name}", dependencies=[Depends(require_role("admin", "developer"))])
async def set_fallback(model_name: str, body: FallbackBody):
    """Set or clear the fallback model for a given model. Written to config.yaml router_settings."""
    config_path = _get_config_path()
    try:
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to read config")

    if "router_settings" not in config_data:
        config_data["router_settings"] = {"disable_cooldowns": True}

    fallbacks = config_data["router_settings"].get("fallbacks", [])
    fallbacks = [item for item in fallbacks if model_name not in item]
    if body.fallback_model:
        fallbacks.append({model_name: [body.fallback_model]})
    config_data["router_settings"]["fallbacks"] = fallbacks

    try:
        with open(config_path, "w") as f:
            yaml.safe_dump(config_data, f, default_flow_style=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to write config")

    return {"status": "ok"}


@router.get("/models/pricing", dependencies=[Depends(require_authenticated())])
async def get_models_pricing():
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{_ENGINE_URL}/model/info",
                headers={"Authorization": f"Bearer {_ENGINE_MASTER_KEY}"}
            )
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []

    result = []
    for m in data.get("data", []):
        info = m.get("model_info", {})
        input_cost = info.get("input_cost_per_token", 0) or 0
        output_cost = info.get("output_cost_per_token", 0) or 0
        result.append({
            "model_name": m.get("model_name"),
            "input_cost_per_million": round(float(input_cost) * 1_000_000, 4),
            "output_cost_per_million": round(float(output_cost) * 1_000_000, 4),
            "max_tokens": info.get("max_tokens"),
            "max_input_tokens": info.get("max_input_tokens"),
        })
    return result
