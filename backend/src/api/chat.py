import time
import json
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
from ..services import auto_router_service
from ..services.atomic_file import escribir_atomico
from ..services.budget_service import (
    STATUS_BUDGET_EXHAUSTED,
    BudgetService,
    has_known_pricing,
)
from ..services.presidio_service import PresidioService
from ..services.optimization_service import OptimizationService
from ..services.compliance_service import ComplianceService
from ..services.audit_service import (
    AuditService,
    AuditUnavailableError,
    audit_exige_registro,
    audit_fail_mode,
    audit_writable,
    detalle_503_audit,
    record_audit_loss,
    riesgo_aplicado,
)
from ..services.engine_gate import (
    ENGINE_TIMEOUT_SECONDS,
    HEADER_REJECTED,
    HEADER_REJECTED_SATURATED,
    RETRY_AFTER_SATURATED,
    STATUS_SATURATED,
    EngineSaturatedError,
    adquirir_turno,
)
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
# Tercer call-site del saneo del literal reservado (spec 018, capa B). Import NOMBRADO y no
# `_gw_plane.sanear_modelo_declarado` a propósito: un `grep sanear_modelo_declarado` tiene que
# devolver los TRES escritores de `audit_logs.model` —`/gw`, `/internal/audit` y este plano— o
# la próxima ronda vuelve a contar dos.
from .gateway import sanear_modelo_declarado

router = APIRouter(prefix="/chat", tags=["Playground Chat"])
logger = logging.getLogger("sentinel-secure-gateway.chat")

_ENGINE_URL = os.getenv("SENTINEL_ENGINE_API_BASE", "http://engine:4000")
# Lado BACKEND del secreto compartido del plano interno: acá SÍ va el nombre nuevo, porque
# el compose se lo pasa a ESTE contenedor como SENTINEL_ENGINE_MASTER_KEY (igual que
# `internal.py`, `analytics.py`, `costs.py` y `ai_engine_client.py`). La asimetría con
# `litellm/extensions/`, que sigue leyendo LITELLM_MASTER_KEY, es deliberada: adentro del
# motor el nombre lo impone la imagen upstream. Los dos nombres resuelven al MISMO valor.
_ENGINE_MASTER_KEY = os.getenv("SENTINEL_ENGINE_MASTER_KEY", "sentinel_master_key_9999")

# Guardia de calidad (spec 012 US6): reintenta con el prompt original si la respuesta
# tras compresión es anómala (vacía/muy corta). Fail-open; raro (solo si se comprimió).
_REVERSAL_GUARD = os.getenv("COMPRESSION_REVERSAL_GUARD", "true").lower() == "true"


# Timeout (segundos) de la llamada al motor de IA. Configurable por env sin rebuild
# (`SENTINEL_ENGINE_TIMEOUT_SECONDS`): un modelo local/self-hosted (Ollama del cliente) puede tardar
# bastante más que un proveedor cloud, así que el hardcode de 15 s cortaba respuestas legítimas.
#
# El parser vive ahora en `engine_gate` y es COMPARTIDO con el byok de `/gw` (que tenía su propio
# 120 s hardcodeado). El de acá —previo a #131— parseaba sin guardia de rango: un `1e9` pasaba
# crudo y dejaba la llamada al motor efectivamente SIN timeout, que es el cuelgue que el nodo C1
# vino a matar. Mismo nombre de env, ahora acotado (finito, 0 < v ≤ 600 s).
_ENGINE_TIMEOUT_SECONDS = ENGINE_TIMEOUT_SECONDS

_EU_COMPLIANT_PROVIDERS = {"bedrock", "vertex_ai", "azure", "watsonx", "ollama", "ollama_chat"}

# El copy del 503 (`AUDIT_CLOSED_DETAIL`/`AUDIT_POLICY_DETAIL` + `detalle_503_audit()`) y la
# cascada del riesgo (`riesgo_aplicado()`) nacieron acá en T006 y viven desde T007 en
# `services/audit_service.py`, junto a la matriz que alimentan: el plano `/gw` es su segundo
# consumidor y una copia por plano es lo que `tasks.md` declara NO_APTO. Se importan arriba;
# el texto del 503 se conservó carácter por carácter en la mudanza (SC-002, medido).


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

    Qué fila aporta el **vocabulario** (qué entidades y qué nombres propios del cliente): la
    ``pii_masking`` ACTIVA más antigua (``created_at, id``), el MISMO desempate determinista
    que usan el escritor del catálogo custom y los planos de tráfico (#104/#119), para que
    todos coincidan en la fila que gobierna. Esto NO gatea el piso con el toggle de la UI
    (SC-004): la detección corre igual —lo que trae a este camino es el toggle de gobernanza
    ``pii_masking:off``, que NO es el ``is_active`` de la fila (una instalación por defecto la
    tiene activa)—; el filtro sólo decide de qué fila sale el vocabulario, y si no hay ninguna
    activa se usa el default de producto (igual que el tráfico, que tampoco lee filas inactivas).

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
        # issue #119: la ACTIVA más antigua (`created_at, id`) — mismo desempate determinista
        # que el escritor del catálogo custom y los lectores de tráfico (#104), para que TODOS
        # coincidan en la fila que gobierna. Sin él, con dos `pii_masking` activos este piso
        # podía leer entidades/nombres de una fila distinta a la que el panel edita.
        pii_guardian = min(
            (g for g in guardians if g.guardian_type == "pii_masking" and g.is_active),
            key=lambda g: (g.created_at, g.id), default=None)
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


async def _publish_chat_event(*, db: Session, user, tenant_id, model: str, status: str,
                              prompt: str, entities, attribution,
                              routing: Optional[dict] = None) -> None:
    """Evento de monitor del plano chat — **único** punto de emisión de este plano.

    Best-effort de punta a punta (contrato §9): cualquier fallo de esta función se traga —
    la respuesta al cliente, sea un bloqueo o una respuesta del modelo, jamás depende de la
    vitrina.

    El evento lo serializa el emisor del gateway, no una copia local: el contrato §8 exige
    esquema idéntico entre los tres productores, y la única forma de que eso no se
    desincronice es que haya UN serializador. Acá se arma la identidad equivalente —el chat
    no tiene Connection, así que la superficie es constante del plano y el cliente es el
    usuario de sesión— y se delega. Mismo precedente que `inspect.py`.

    El preview va SIEMPRE display-masked (§10), con pase propio sobre mapa desechable +
    scrub de secretos, **independientemente** de qué capas alcanzaron a correr. En el punto
    de bloqueo esto no es un detalle: se bloquea ANTES de que el enmascarado corra, así que
    sin este pase el evento sería el canal por donde el texto crudo —el que motivó el
    bloqueo— llega al feed.

    ``routing`` (spec 030) es el objeto decisión COMPLETO del auto-router o ``None``. No se
    recorta acá: la proyección al subset del evento la hace el serializador del gateway
    (`_publish_monitor`), que es el único lugar donde el contrato del evento se decide.
    ``None`` ⇒ el gateway omite la clave, que es la codificación de "este pedido no pasó
    por el router" (distinta de "el router no eligió ruta").
    """
    try:
        preview = await _gw_plane._safe_preview({"messages": [{"role": "user", "content": prompt}]})
        ident = {
            "tool_type": _CHAT_SURFACE,
            "client_username": getattr(user, "username", None),
            "tenant_slug": _tenant_slug(db, tenant_id),
        }
        _gw_plane._publish_monitor(
            ident, _CHAT_SURFACE, model, status,
            _summarize_entities(entities), preview,
            surface=_CHAT_SURFACE, attribution=attribution, routing=routing,
        )
    except Exception:  # noqa: BLE001
        pass  # vitrina: jamás afecta la request


async def _publish_block_event(*, db: Session, user, tenant_id, model: str, status: str,
                               prompt: str, entities, attribution) -> None:
    """Evento de monitor **en el punto de bloqueo** del plano chat (contrato §13).

    Hasta la 027 los `raise HTTPException` de bloqueo de este endpoint precedían a TODO
    registro: un pedido bloqueado no dejaba fila ni evento, o sea que el caso donde el
    firewall hace su trabajo era justo el único invisible en la vitrina (research D6). Acá
    se publica antes del `raise`, con el mismo esquema que los otros dos productores
    (§8) más `applied_layers`/`blocked_by_layer`.

    Esto es la VITRINA y nada más: efímera (TTL 300 s) y best-effort. La FILA DURABLE del
    bloqueo la escribe `_registrar_bloqueo`, que llama a esta función después de persistir
    (spec 031 D2 — el corte que la 027 declaró acá se pagó). Los dos registros conviven a
    propósito y **cuentan la misma historia**: el `status` y la atribución son el MISMO
    objeto, no dos derivaciones que puedan divergir (riesgo R3 del research). Lo único que
    puede diferir es el desglose de entidades cuando el enmascarado está apagado: la fila
    lleva el hallazgo del piso —es un registro de cumplimiento y tiene que decir qué había—
    y la vitrina sigue mostrando lo que se enmascaró, que es cero. A propósito y en la
    dirección segura: el registro durable nunca afirma menos de lo que se detectó.

    Sin `routing` a propósito: un pedido bloqueado se rechaza ANTES de llegar al modelo, y
    aunque el auto-router ya haya elegido destino, ese destino no procesó nada. Contarlo en
    la vitrina daría a entender que el pedido viajó a ese modelo. La decisión SÍ va en la
    fila durable (columna `routing_decision`), que es donde el officer necesita saber qué
    modelo se habría usado sin que eso signifique que el texto viajó.
    """
    await _publish_chat_event(db=db, user=user, tenant_id=tenant_id, model=model,
                              status=status, prompt=prompt, entities=entities,
                              attribution=attribution)


def _entidades_de_fila(floor_entities, detected) -> list:
    """Desglose `[{"type","count"}]` que va a las columnas legadas de la fila durable.

    Una sola expresión para los CUATRO escritores de fila que llegan con entidades ya
    medidas (bloqueo por política, bloqueo por residencia, rechazo por capacidad y el camino
    feliz). Los otros dos escritores del plano —el bloqueo AI-Act y el rechazo por
    presupuesto— no pasan por acá: cortan ANTES de que corra ningún detector y mandan
    `entities=[]`, que dice «no hay medición» en vez de inventar un cero.

    Para los cuatro que sí pasan, la regla es una sola: manda el hallazgo del PISO
    (`_floor_entities`), que corre esté o no encendido el enmascarado; sólo cuando el
    detector de piso no pudo confirmar nada (`None`) se cae a lo que el enmascarado sí
    produjo. Nunca al revés: derivar de lo enmascarado haría que una fila con
    `pii_masking=off` dijera "no hubo datos personales" justo cuando los hubo y encima
    salieron en claro (el hallazgo adversarial que fija `test_chat_audit_row_pii`).
    """
    return _summarize_entities(detected) if floor_entities is None else floor_entities


# ── El literal reservado de la cadena de licencias no lo elige el cliente ─────────────
#
# `ChatRequest.model` es un `str` LIBRE del body y termina en `audit_logs.model`, la misma
# columna que escriben `/gw` y `/internal/audit`. `license` es la marca de los eslabones de la
# hash-chain de licencias (021), así que quien se lo ponga a su propia fila se lleva premios
# que no le tocan: la fila se sale de los agregados que todavía excluyen a mano por
# `model <> 'license'` (`api/compliance.py`, `api/reports.py`, `api/analytics.py`) y queda a la
# vista de `verify_chain`, que relee TODAS las filas con ese nombre.
#
# El daño de ESTE plano, reproducido sin privilegios contra la app real: un
# `POST /chat/completions {"model": "license", "message": "<algo que dispare un guardián>"}`
# con cualquier usuario autenticado deja un bloqueo REAL que después no aparece en el
# dashboard de compliance ni en el informe ejecutivo (`total_logs = 0`, `total_transactions =
# 0` medidos con esas filas en la tabla). O sea: el registro miente por omisión justo en el
# pedido que el firewall impidió — un usuario del Playground se borra del resumen del DPO
# eligiendo cómo se llama su propio pedido.
#
# Por qué NO se rechaza el pedido acá, a diferencia de `/gw`: el 422 de la puerta es un
# contrato acordado de ese plano; estrenar un 4xx nuevo en el endpoint del Playground es una
# decisión de producto que esta ronda no tomó, y no hace falta — con el nombre desalojado la
# fila ya vuelve a ser mortal, contable y visible, que son las tres propiedades que el ataque
# le sacaba. Mismo criterio que `/internal/audit`: sanear y nada más.
def _modelo_auditable(declarado):
    """El `model` que puede ir a la columna auditada. Reusa el saneo de `gateway`.

    La función vive allá y no se reimplementa acá porque el vocabulario reservado tiene que
    crecer en UN solo lugar: el porqué completo —los lectores que comparan por igualdad, el
    precedente de `api/inspect.py`, por qué saneo y no rechazo, por qué el centinela dice la
    verdad en vez de disfrazar la fila— está en `gateway.sanear_modelo_declarado`.

    Lo único que este plano agrega es el `logger.warning`: en `/gw` el intento se le contesta
    al cliente con un 422 y queda a la vista, acá el pedido sigue su curso normal, así que sin
    esta línea el desalojo sería invisible para quien opera la instalación.
    """
    saneado = sanear_modelo_declarado(declarado)
    if saneado != declarado:
        logger.warning(
            "[sentinel-chat] el pedido declaró el literal reservado de la cadena de licencias "
            "como modelo; la fila durable se registra con el centinela %s", saneado)
    return saneado


# ── `guardian_events[0]` es NUESTRO, lo diga quien lo diga upstream ───────────────────
#
# **Quién lee esa posición.** El lector ÚNICO de la cadena de licencias —`chained_entries`
# (`licensing/audit_events.py:130`), que consumen `verify_chain` (`:170`) y el export de
# true-up (`trueup_export.build_payload`, `:65`, vía el import de `:31` que reemplazó la copia
# local que ese módulo tenía)— y el portón de la purga de retención
# (`services/retention/classifier.py`, `es_trafico_demostrable()`). Los dos agarran
# `guardian_events[0]` y le miran las marcas que escribe el emisor de la cadena:
# `chained_entries` pide `seq` **y** `prev_hash` (`_is_chain_link`, `:87`); el portón saca de
# lo purgable a cualquier primer evento que traiga `seq`, `prev_hash` **o** `event_type`. Es
# una lectura POSICIONAL y es deliberada —barrer la lista entera dejaría comprar la exclusión
# metiendo la marca en la segunda posición, donde la cadena ni mira—, así que el índice 0 es
# una superficie de ataque con nombre y apellido.
#
# **Qué se metía ahí.** La mitad de esta lista la escribe quien conteste upstream: es
# `guardrail_info.guardrail_events` de la respuesta del motor, y esa forma no la fijamos
# nosotros. Un `developer` puede registrar un modelo con `api_base` apuntando a un servidor
# propio y devolver `[{"seq": 7, "prev_hash": "…", "event_type": "license_loaded"}]`; sin
# triggers locales —el caso NORMAL, un pedido que no disparó ningún guardián— ese objeto ajeno
# quedaba tal cual en el índice 0 de una fila de tráfico.
#
# **El arreglo es ANIDAR, no quitar claves**, y las dos razones son de fondo:
#
# * un strip de claves reservadas es una lista CERRADA que se pudre. El día que la cadena
#   estrene una cuarta clave, el strip de tres queda viejo y nadie se entera —falla callado y
#   del lado inseguro—. Anidar es allowlist por construcción: lo ajeno vive DENTRO de una
#   clave nuestra, mire lo que mire el lector que se escriba mañana;
# * a un blob que no es un objeto no se le pueden quitar claves, y ése es un caso vivo: con
#   `["seq"]` el `"seq" in eventos[0]` de los lectores da True por SUBCADENA (`in` sobre un
#   string busca subcadena) y el `e["seq"]` de la línea siguiente revienta con TypeError —el
#   verificador de la evidencia con la que se factura, caído por una fila. Anidado, el índice 0
#   es siempre un dict con una sola clave que no le dice nada a nadie.
#
# **Lo LOCAL no se toca.** `guardian_triggers` lo arma este backend (`GuardianService`), es lo
# que la vitrina y el Debugger ya leen, y no hay nadie del otro lado que lo pueda dictar.
#
# **Alcance, dicho con todas las letras: desde el dictamen del 14-ago este anidado ES EL ÚNICO
# CERROJO frente a la purga. No es defensa en profundidad. Si se saca, no hay nada detrás.**
#
# La exclusión de la purga dejó de mirar `model` en cualquier forma: la compra SÓLO la forma de
# `guardian_events[0]` (`classifier.es_trafico_demostrable()`). O sea que el saneo de
# `_modelo_auditable` (`:503`) ya no es «la otra mitad» de esta defensa — protege la VITRINA,
# que sigue excluyendo por el literal (`api/audit.py:271`, `~dice_licencia()`), y nada más.
# Lo único que hoy impide que quien conteste upstream se compre la inmortalidad frente a la
# purga —devolviendo `[{"seq": 7, "prev_hash": "…", "event_type": "license_loaded"}]` y
# quedándose con el índice 0 de una fila de tráfico— es que esta función ANIDE lo ajeno.
#
# Y no es una lectura del código, es una medición: al 14-ago
# `grep -rn 'es_licencia' backend/src/ litellm/ --include='*.py'` devuelve la `def` del propio
# `classifier.es_licencia` y prosa de comentarios, y CERO llamadores. No hay una segunda condición
# esperando en ningún archivo. Quien mañana agregue un consumidor de `es_licencia()` —literal
# **más** `seq`— está reintroduciendo `model` en una decisión de la que el dictamen lo sacó a
# propósito: que lea antes el docstring de `classifier.dice_licencia()`, donde está el argumento
# completo de por qué purga y vitrina no comparten criterio.
def _eventos_de_la_fila(triggers, upstream) -> list:
    """`guardian_events` de la fila durable: triggers locales tal cual, upstream anidado."""
    return list(triggers or []) + ([{"upstream": upstream}] if upstream else [])


async def _registrar_bloqueo(*, db: Session, user, api_key_obj, group, tenant_id,
                             model: str, estado: str, prompt: str, entities, attribution,
                             start_time: float, routing: Optional[dict] = None,
                             entidades_fila: Optional[list] = None,
                             cabeceras_del_503: Optional[dict] = None) -> None:
    """**Registrar → bloquear**: fila DURABLE del rechazo y, después, evento de vitrina.

    Es el pago del corte D6 de la 027 (spec 031 US1/FR-002): cuando nació este helper, los 3
    puntos de bloqueo por política de este endpoint publicaban al monitor efímero y hacían
    `raise` antes del único `log_transaction`, así que a los 300 s de un intento impedido no
    quedaba NADA. Para un producto que se vende como «logueamos todo para compliance», el
    evento más importante —«se intentó y se impidió»— era el único sin rastro.

    Hoy tiene CINCO llamadores, y no todos son bloqueos de política. Conviene no meterlos en
    la misma bolsa, porque lo que le decimos al officer cambia:

    * **Bloqueos de política** (3) — una capa del firewall impidió el pedido:
      `blocked_prohibited` (AI-Act), `blocked_by_policy` (guardián de postura) y
      `blocked_residency`. El `compliance_status` empieza con `blocked` y entra al filtro
      canónico `LIKE 'blocked%'`.
    * **Rechazos NUESTROS** (2) — no lo impidió ninguna capa, el pedido simplemente no se
      sirvió y el motivo es de la casa: `rejected_saturated` (tope de admisión al motor,
      #135) y `rejected_budget` (tope de presupuesto agotado, #157). Prefijo `rejected` a
      propósito: contarlos como bloqueos le mentiría al officer sobre cuántos intentos
      bloqueó el firewall.

    Lo que sí comparten los cinco —y por eso comparten helper— es la matriz: fila durable
    primero, vitrina después, respuesta al final.

    Decisiones que este helper encapsula (una sola vez, para los cinco llamadores):

    * **La fila va PRIMERO.** Si el proceso muere en el medio, lo que tiene que sobrevivir
      es el registro durable, no la vitrina.
    * **Reusa `log_transaction`** (D2): un solo escritor, así el retry acotado y el contador
      de pérdidas de la US2 valen también para los bloqueos, sin una segunda vía de
      escritura que mantener.
    * **`compliance_status` es el MISMO literal que ya viaja al monitor** (D1 + riesgo R3):
      los cinco literales de arriba, que la tabla de la vitrina ya conoce (`monitor.py`), y
      ninguno necesitó columna nueva ni migración. Los tres `blocked_*` entran al filtro
      canónico `LIKE 'blocked%'`; los dos `rejected_*` quedan fuera de los DOS baldes del
      filtro binario de la vitrina de auditoría (`api/audit.py`), que es justo lo que hace
      falta para no contarlos ni como bloqueo ni como pedido permitido.
    * **Tokens 0/0 y coste 0** (contrato §Fila de bloqueo): no se consumió proveedor. El
      estado de bloqueo es EXPLÍCITO en su columna, así que el officer no tiene que
      interpretar un 0/0 para saber que el pedido no se sirvió (FR-006).
    * **Atribución completa**: usuario, llave, grupo y tenant si se resolvieron; `NULL`
      cuando no (el intento se registra igual — edge case de la spec).

    Qué pasa si la fila NO se puede escribir:

    * `open` (default): el usuario recibe EXACTAMENTE la misma respuesta de siempre (el 400
      del bloqueo, el 402 del presupuesto, el 503 de saturación). El escritor ya contó la
      pérdida y la logueó con nivel error; hacer fallar distinto un rechazo por un problema
      de la base sería castigar al usuario por algo que no es suyo. El `except` ancho es
      para lo IMPREVISTO (en `open` `log_transaction` no lanza): ahí se cuenta acá, porque
      lo único innegociable es que la pérdida no sea silenciosa.
    * `closed`: `AuditUnavailableError` → 503 honesto con el copy del contrato, **en lugar
      del código que el llamador iba a devolver**. Esto es observable desde afuera y hay que
      decirlo con todas las letras: en `closed` y con la auditoría caída, un bloqueo de
      política no responde 400 sino 503, y el rechazo por presupuesto no responde 402 sino
      503. No es un bug de precedencia: la instalación pidió «sin registro no hay servicio»,
      y un 402 sin fila diría «te negamos servicio y quedó registrado» cuando no quedó nada.
      La vitrina se publica igual ANTES de responder: el rechazo ocurrió de verdad y el
      operador tiene que poder verlo mientras diagnostica la caída de la auditoría.

    El parámetro se llama `estado` y no `status` porque en este módulo `status` es el enum
    de códigos HTTP de FastAPI: el shadowing dejaría al helper sin poder nombrar su 503.

    `cabeceras_del_503` es para los llamadores cuyo rechazo tiene un CONTRATO DE WIRE propio
    (H6 del gate de #135). Hoy sólo el rechazo por capacidad: La ITV acordó que
    `X-Sentinel-Rejected: saturated` viaja en TODO 503 de saturación, y si la auditoría se cae
    mientras se registra uno, el 503 que sale por esta puerta sigue siendo la respuesta a un
    pedido saturado. Sin la cabecera, el harness de carga lo contaría como un 503 ajeno —de
    Caddy, del proxy de la sede— y el drill mediría mal justo en el caso interesante. Los
    otros CUATRO llamadores no la pasan: ni los tres bloqueos de política ni el rechazo por
    presupuesto tienen contrato de wire acordado para su respuesta.
    """
    # Saneo del literal reservado (018 capa B) para los CINCO llamadores de una vez: los cinco
    # escriben `audit_logs.model` por acá, y el `model` que traen sale —directo o vía el
    # re-ruteo del guardián— del `str` libre de `ChatRequest.model`. Va en el HELPER y no en
    # cada call-site por el mismo motivo por el que la fila durable vive acá: un saneo repetido
    # cinco veces se olvida en el sexto rechazo que alguien agregue, y el que se olvide no falla
    # ruidosamente — deja una fila que el DPO no ve. El porqué largo, arriba de
    # `_modelo_auditable`.
    #
    # El valor saneado se usa TAMBIÉN para el evento de vitrina de más abajo: la fila durable y
    # la vitrina tienen que nombrar el mismo pedido igual, o el operador que compara las dos
    # pantallas durante un incidente ve dos pedidos donde hubo uno.
    model = _modelo_auditable(model)
    resumen = _summarize_entities(entities) if entidades_fila is None else entidades_fila
    fallo_closed: Optional[AuditUnavailableError] = None
    try:
        AuditService.log_transaction(
            db=db,
            # Spec 038 T006: la decisión servir/cortar del pedido, resuelta ACÁ y no
            # recibida del llamador. Tres de los cinco llamadores de este helper corren
            # ANTES del punto donde el endpoint calcula `_applied_risk_level` (gate de
            # presupuesto, residencia y capacidad), así que exigirles el dato obligaría a
            # subir la resolución del riesgo por encima de ellos —un movimiento de código
            # en el camino caliente— o a que cada uno la copiara. Este helper ya recibe
            # `api_key_obj`/`user`/`group`, que es todo lo que la cascada necesita.
            exige_registro=audit_exige_registro(
                riesgo_aplicado(api_key_obj, user, group)),
            # Modelo del pedido, tal como lo conoce el llamador. En los llamadores que
            # corren DESPUÉS del auto-router es el modelo efectivo (con «auto»,
            # `request.model` ya es el destino que eligió el router, y lo pedido viaja
            # textual en `routing`). El gate de presupuesto corre ANTES del router, así que
            # ahí es el modelo PEDIDO y puede ser literalmente «auto»: ver el comentario de
            # ese llamador.
            model=model,
            prompt_tokens=0,
            completion_tokens=0,
            cost_usd=0.0,
            pii_detected=bool(resumen),
            masked_entities=resumen,
            compliance_status=estado,
            latency_ms=int((time.time() - start_time) * 1000),
            user_id=getattr(user, "id", None),
            api_key_id=getattr(api_key_obj, "id", None),
            user_group_id=getattr(group, "id", None),
            applied_layers=attribution.applied_layers if attribution else None,
            blocked_by_layer=attribution.blocked_by_layer if attribution else None,
            routing_decision=routing,
            tenant_id=tenant_id,
        )
    except AuditUnavailableError as exc:
        fallo_closed = exc
    except Exception as exc:  # noqa: BLE001
        logger.error("audit: la fila durable del bloqueo (%s) no se pudo escribir: %s",
                     estado, exc, exc_info=exc)
        record_audit_loss(reason=f"chat/{estado}")

    await _publish_block_event(db=db, user=user, tenant_id=tenant_id, model=model,
                               status=estado, prompt=prompt, entities=entities,
                               attribution=attribution)

    if fallo_closed is not None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detalle_503_audit(),
            headers=cabeceras_del_503,
        ) from fallo_closed


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


def _read_engine_config() -> dict:
    """Config del motor parseado, o `{}` si no se pudo leer.

    Los tres escritores (`register_model`, `delete_model`, `set_fallback`) siguen leyendo
    por su cuenta porque necesitan distinguir "no se pudo leer" de "está vacío" y responder
    500: escribir sobre un `{}` fabricado borraría el catálogo entero del cliente.
    """
    try:
        with open(_get_config_path(), "r") as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo leer el catálogo del motor: %s", type(exc).__name__)
        return {}


def _write_engine_config(config_data: dict) -> None:
    """Persiste el catálogo del motor de forma ATÓMICA. Único escritor del `config.yaml`.

    Los cuatro endpoints que editan el catálogo (alta, baja, credenciales y respaldos)
    pasan por acá. La escritura in-place que había antes truncaba el fichero antes de
    volcar el contenido nuevo: un proceso que muriera —o un reinicio— en esa ventana
    dejaba al motor arrancando con un YAML cortado, o sea al cliente sin catálogo.
    """
    escribir_atomico(
        _get_config_path(),
        lambda f: yaml.safe_dump(config_data, f, default_flow_style=False),
    )


def _catalog_model_names(config_data: Optional[dict] = None):
    """`model_name`s del catálogo del motor, o `None` si el config no se pudo leer.

    `None` y `set()` NO significan lo mismo para el auto-router: con un conjunto vacío
    TODA ruta quedaría rota (`target_missing`) y el ruteo degradaría entero por un problema
    de LECTURA del catálogo, no de configuración. `None` = "no verificable" → el router no
    valida el destino y sirve por la ruta ganadora. Degradar por no poder mirar sería
    castigar al usuario por un fallo que no es suyo ni de la config.
    """
    datos = _read_engine_config() if config_data is None else config_data
    if not datos:
        return None
    return {m.get("model_name") for m in (datos.get("model_list") or [])
            if isinstance(m, dict) and m.get("model_name")}


# Providers que identifican un modelo LOCAL (self-hosted del cliente) en el catálogo del
# motor. Se mira el `litellm_params.model` —el contrato con el motor— y no el `model_name`,
# que es white-label: en el piloto el modelo local se llama `camara-comercio-local` y no
# tiene la palabra "ollama" a la vista, justamente para que el motor no se filtre al cliente.
_LOCAL_PROVIDER_PREFIXES = ("ollama/", "ollama_chat/")


def _is_local_entry(entry: dict) -> bool:
    """¿La entrada del catálogo es un modelo local del cliente?"""
    if not isinstance(entry, dict):
        return False
    model_full = (entry.get("litellm_params") or {}).get("model") or ""
    return isinstance(model_full, str) and model_full.startswith(_LOCAL_PROVIDER_PREFIXES)


def _local_models(config_data: dict) -> list:
    """Entradas locales del catálogo, en el orden en que están declaradas."""
    return [m for m in (config_data.get("model_list") or []) if _is_local_entry(m)]


def _router_config_safe() -> dict:
    """Config del auto-router, o los defaults si falta / está rota.

    Tolerante a propósito: los consumidores de acá (el dropdown de modelos, la elección
    del respaldo local) son features de conveniencia, y un `auto_router.json` roto no puede
    dejar sin catálogo al chat. El camino que SÍ tiene que enterarse del error es
    `route()`, que lo reporta como degradación con motivo.
    """
    try:
        return auto_router_service.load_config()
    except Exception as exc:  # noqa: BLE001
        logger.warning("auto-router: config ilegible (%s) — se usan los defaults",
                       type(exc).__name__)
        return dict(auto_router_service.DEFAULT_CONFIG)


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

def _gate_rol_chat(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    """FR-003 (T010, spec 017): en el camino de SESIÓN (JWT) el rol gatea el chat. `lectura`
    (chat_playground=NINGUNO en la matriz canónica) → 403; el resto de los roles de sesión
    conservan RW. Va como **dependency** a propósito: corre ANTES de validar el body, así un rol
    negado recibe el 403-por-rol y no un 422 de cuerpo (mismo orden que `require_role` en el resto
    de la matriz-ley). NO toca las virtual keys (`sk-*`) —la vía de inferencia del cliente— ni la
    ausencia de credencial: su auth y su fail-closed 401 siguen viviendo en el handler."""
    if not (authorization and authorization.startswith("Bearer ")):
        return
    token = authorization.replace("Bearer ", "").strip()
    if token.startswith("sk-"):
        return
    from ..auth.session import decode_session_token
    from ..models.user import User as UserModel
    from ..auth.matrix import Rol, puede_escribir
    payload = decode_session_token(token)
    if not payload:
        return  # token inválido/expirado: el handler ya responde 401, no lo duplico acá
    uid = payload.get("sub")
    if not uid:
        return
    user = db.query(UserModel).filter(UserModel.id == uid, UserModel.is_active == True).first()
    if user is None:
        return
    try:
        permitido = puede_escribir(Rol(user.role), "chat_playground")
    except ValueError:
        permitido = False  # rol fuera de la matriz → fail-closed
    if not permitido:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Acción no permitida para el rol '{user.role}'. "
                   f"El chat interno no está disponible para tu rol.",
        )


@router.post("/completions", dependencies=[Depends(_gate_rol_chat)])
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
        # Registrar → responder (issue #157): negar servicio sin fila durable deja al officer
        # sin poder reconstruir a quién le negamos servicio por presupuesto y cuándo. Misma
        # matriz que el rechazo por capacidad: fila primero, respuesta después, y los modos
        # `open`/`closed` los resuelve `_registrar_bloqueo`.
        #
        # Lo que ese reparto de responsabilidades implica ACÁ, y que conviene no dejar
        # implícito porque es OBSERVABLE por el cliente: en `audit_fail=closed`, si la
        # auditoría está caída, `_registrar_bloqueo` levanta su propio 503 y el cliente
        # recibe **503 en vez del 402 de abajo**. El código HTTP cambia, y está bien que
        # cambie: la instalación pidió «sin registro no hay servicio», así que responder 402
        # sin fila afirmaría «te negamos servicio y quedó registrado» cuando no quedó nada.
        # En `open` (default) el 402 sale intacto y la pérdida se cuenta. Los dos cruces los
        # fija `tests/integration/test_chat_budget_audit.py`.
        #
        # Qué se pasa y qué NO, porque este gate corre ANTES del resto del pipeline:
        # * `model=request.model` es el modelo PEDIDO, no el efectivo: la reasignación del
        #   auto-router ocurre más abajo, así que en un pedido con `auto` la fila dice
        #   literalmente «auto». Es lo que el usuario pidió y es verdad; elegir un destino
        #   por nuestra cuenta inventaría un modelo que nadie eligió.
        # * `entities=[]` no es una medición de cero: ningún detector corrió todavía (el
        #   pipeline de guardianes arranca después). Mismo criterio que el bloqueo AI-Act.
        # * sin `routing`: el auto-router todavía no decidió nada, y `routing_decision` NULL
        #   es exactamente eso.
        # * sin `cabeceras_del_503`: este 402 no tiene contrato de wire acordado con La ITV.
        await _registrar_bloqueo(
            db=db, user=user, api_key_obj=api_key_obj, group=group, tenant_id=_tenant_id,
            model=request.model, estado=STATUS_BUDGET_EXHAUSTED,
            prompt=request.message, entities=[],
            attribution=build_attribution(profile, verdicts),
            start_time=start_time,
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Presupuesto mensual agotado para la llave virtual o el usuario/equipo."
        )

    # 1c. Auto-router semántico (spec 030 US1, research R2)
    #
    # El ruteo ocurre ACÁ: después de autenticar y de los gates baratos (rate limit,
    # presupuesto) y ANTES del pipeline de protección. Las dos mitades importan:
    #
    # * **Antes del pipeline** (FR-010): a partir de esta línea el modelo efectivo fluye por
    #   TODO el pipeline como si el usuario lo hubiera elegido a mano — enmascarado,
    #   guardianes, residencia, auditoría y coste corren exactamente igual. El ruteo elige
    #   destino y nada más: no cortocircuita ninguna capa ni la relaja.
    # * **Después de los gates**: un pedido que va a terminar en 401/429/402 no gasta una
    #   llamada de embeddings. El ruteo es lo único del endpoint que cuesta tiempo y CPU
    #   antes de saber si el pedido siquiera se va a servir.
    #
    # `request.model` se REASIGNA al modelo efectivo a propósito, en vez de arrastrar una
    # variable paralela por las ~600 líneas siguientes: hay una decena de consumidores de
    # "qué modelo es este pedido" (los tres bloqueos de política, el rechazo por capacidad,
    # el guardián de ruteo, la residencia, la auditoría, el costeo del presupuesto), y una
    # variable nueva obligaría a acordarse de cambiarlos TODOS — el que se olvidara
    # reportaría «auto», que no es un modelo y no se puede pricear ni auditar. (El gate de
    # presupuesto de más arriba es la excepción declarada: corre ANTES de esta reasignación
    # y por eso su fila SÍ puede decir «auto», que es lo que el usuario pidió.)
    #
    # Lo que el usuario pidió no se pierde: viaja textual dentro de la decisión
    # (`requested`), que va al Debugger, a la vitrina y a la columna durable. O sea: la
    # reasignación no borra información, la mueve a donde es legible.
    _routing_decision: Optional[Dict[str, Any]] = None
    if request.model == auto_router_service.AUTO_MODEL:
        # El servicio NUNCA levanta: toda caída al default viaja como decisión con
        # `degraded` + `reason` (FR-004, la degradación jamás es silenciosa).
        _routing_decision = await auto_router_service.route(
            request.message, available_models=_catalog_model_names())
        _effective_model = _routing_decision.get("model_selected") or ""
        if not _effective_model:
            # Único caso sin modelo servible: no hay `auto_router.json` y por lo tanto
            # tampoco un `default_model` que leer. Mandar `model=""` al motor sería un 400
            # críptico y elegir un modelo por nuestra cuenta sería inventar un destino que
            # nadie configuró — con el agravante de que podría ser un cloud en una
            # instalación que eligió local. Se falla honesto y se dice qué falta.
            logger.error("auto-router: sin modelo servible (reason=%s) — pedido rechazado",
                         _routing_decision.get("reason"))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="El ruteo automático no está configurado en esta instalación (falta "
                       "el modelo por defecto). Elegí un modelo concreto de la lista o pedile "
                       "al administrador que configure el ruteo.",
            )
        logger.info("auto-router: ruta=%s score=%s modelo=%s degradado=%s motivo=%s",
                    _routing_decision.get("route"), _routing_decision.get("score"),
                    _effective_model, _routing_decision.get("degraded"),
                    _routing_decision.get("reason"))
        request.model = _effective_model

    # 2. Compliance: AI Act Check (Prohibited practices block immediately)
    #
    # La evaluación AI-Act es PISO: ningún alcance puede apagarla (FR-002/SC-004). Por eso
    # el override por-pedido pasa a ser **solo restrictivo**, igual que el header
    # `X-Sentinel-Redact` del gateway (contrato resolutor #5): puede forzar la evaluación, no
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
        # Bloqueo de política 1/3 (contrato §13 de la 027 + spec 031 D2): la fila DURABLE y la
        # atribución se emiten ACÁ, antes del raise — registrar → bloquear.
        #
        # `entities=[]` no es un descuido: el AI-Act corta ANTES del pipeline de guardianes,
        # así que en este punto todavía no corrió ningún detector. Una lista vacía dice "no
        # hay medición", que es la verdad; inventar un cero sería afirmar que se miró.
        await _registrar_bloqueo(
            db=db, user=user, api_key_obj=api_key_obj, group=group, tenant_id=_tenant_id,
            model=request.model, estado=compliance_result["status"],
            prompt=request.message, entities=[],
            attribution=build_attribution(profile, verdicts),
            start_time=start_time, routing=_routing_decision,
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
        # Bloqueo de política 2/3 (contrato §13 + spec 031 D2). `blocked_by_layer` sale del
        # veredicto de la capa que bloqueó —`secret_detection` o `pii_detection`— y JAMÁS
        # del nombre del guardián, que es editable y white-label (D6).
        #
        # El desglose de entidades de la fila sale del PISO, igual que en el camino feliz:
        # el pedido se bloqueó, pero saber CUÁNTOS datos personales llevaba es justo lo que
        # el officer necesita del intento impedido.
        await _registrar_bloqueo(
            db=db, user=user, api_key_obj=api_key_obj, group=group, tenant_id=_tenant_id,
            model=request.model, estado="blocked_by_policy",
            prompt=request.message, entities=_entities,
            attribution=build_attribution(profile, verdicts, credentials=_credentials),
            start_time=start_time, routing=_routing_decision,
            entidades_fila=_entidades_de_fila(_floor_entities, _entities),
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
    _applied_risk_level = riesgo_aplicado(api_key_obj, user, group)
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
            # Bloqueo de política 3/3 (contrato §13 + spec 031 D2). Este bloqueo sale de la
            # residencia de datos del proyecto de cumplimiento, que **no es una capa del
            # registry**: la fila y el evento llevan la atribución de lo que sí corrió y
            # `blocked_by_layer` queda en NULL — que en la fila durable significa "bloqueado
            # por una regla fuera del catálogo de capas", legible junto al
            # `compliance_status=blocked_residency` que sí nombra el motivo. Atribuírselo a
            # `ai_act_evaluation` porque "suena a cumplimiento" sería falsear el registro —
            # y falsear la atribución es exactamente lo que esta spec existe para terminar.
            # Si la residencia debe ser gobernable y atribuible, entra al catálogo por su
            # propia spec.
            await _registrar_bloqueo(
                db=db, user=user, api_key_obj=api_key_obj, group=group,
                tenant_id=_tenant_id, model=routed_model, estado="blocked_residency",
                prompt=request.message, entities=_entities,
                attribution=build_attribution(profile, verdicts, credentials=_credentials),
                start_time=start_time, routing=_routing_decision,
                entidades_fila=_entidades_de_fila(_floor_entities, _entities),
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
    # Se llama `eventos_del_upstream` y no `guardian_events` porque el nombre tiene que decir
    # de QUIÉN es el dato: lo que caiga acá lo escribe quien conteste del otro lado, y por eso
    # no entra verbatim a la fila (ver `_eventos_de_la_fila`).
    eventos_del_upstream: list = []

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

    # ── `audit_fail=closed`: no se gasta proveedor en tráfico inauditable ─────────────
    #
    # FR-005 es literal —"ANTES de llamar al proveedor"— y por eso el chequeo va acá y no
    # junto al `log_transaction` del final: para cuando la fila se escribe, la respuesta ya
    # se pagó y ya no se puede des-servir (el caso streaming queda documentado en la spec:
    # la petición aceptada se completa, el corte aplica a las siguientes).
    #
    # En `open` NO se ejecuta NADA de esto: ni un `SELECT 1` ni una lectura extra. La
    # instalación que pidió continuidad explícita no paga su latencia. En `policy` (spec
    # 038, el default desde D1) lo paga SÓLO el pedido que no se puede servir sin fila —el
    # `and` corta antes del `audit_writable` cuando la matriz dice servir—, así que el
    # tráfico `minimal`/`limited` sigue sin pagar un solo SELECT.
    #
    # `audit_writable` cierra su propia transacción con `rollback` —obligado, porque deja un
    # `statement_timeout` de sentencia que si no moriría pegado al resto del request—, así
    # que se llama en el único punto del endpoint donde no hay trabajo sin commitear: los
    # bloqueos ya salieron por `raise` y el `review_entry` todavía no se agregó. Los objetos
    # ORM ya cargados quedan expirados y se refrescan solos al leerlos; es un par de SELECT
    # extra que sólo paga el modo `closed` durante una caída de la auditoría.
    _exige_registro = audit_exige_registro(_applied_risk_level)
    if _exige_registro and not audit_writable(db):
        logger.error("audit: el pedido exige registro (modo=%s riesgo=%s) y la base de "
                     "auditoría no responde — se rechaza ANTES de llamar al proveedor "
                     "(model=%s)", audit_fail_mode(), _applied_risk_level, routed_model)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detalle_503_audit(),
        )

    # ── Tope de ADMISIÓN hacia el motor (nodo C1) ─────────────────────────────────────
    #
    # UNA sola adquisición para todo el diálogo con el motor: la llamada normal y —si se
    # dispara— el reintento de reversión, que vive dentro de este mismo `async with` porque es
    # el MISMO pedido del usuario. Re-adquirir para el reintento lo pondría a hacer cola detrás
    # de pedidos nuevos, o lo rechazaría a mitad de camino con la respuesta ya pagada.
    #
    # El turno se suelta en el `__aexit__`, o sea también si el motor timeoutea, si devuelve
    # 4xx/5xx o si el cuerpo levanta: un turno que se filtrara por un camino de error bajaría el
    # tope de forma permanente hasta reiniciar el worker, que es peor que no tener tope.
    #
    # `async with A, B` y no un bloque anidado a propósito: el alcance del turno tiene que ser
    # EXACTAMENTE el de la conexión al motor, ni un statement más.
    try:
        async with adquirir_turno(), httpx.AsyncClient() as client:
            # `temperature` FIJO sacado (31-ago): los modelos de razonamiento (ej.
            # azure-gpt-5.1-chat) rechazan cualquier valor que no sea el default (1) —
            # "Unsupported value: 'temperature' does not support 0.3 with this model"
            # real, en vivo. Mismo bug que ya se había corregido para el portal
            # (commit 68f1b22) pero seguía presente en este endpoint. Sin la clave, cada
            # modelo usa su propio default — no hay control de temperatura expuesto al
            # usuario hoy, así que omitirla no saca ninguna funcionalidad real.
            raw_request_json = {
                "model": routed_model,
                "messages": [{"role": "user", "content": optimized_prompt}],
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

                # Lo que el upstream dice sobre SUS guardrails. Se guarda crudo en una variable
                # que declara de quién es y se anida recién al escribir la fila
                # (`_eventos_de_la_fila`). El `isinstance` es del mismo asunto: `guardrail_info`
                # tampoco tiene forma garantizada —la fija quien responda—, y un no-objeto
                # levantaba un `AttributeError` que salía por el `except` ancho de más abajo
                # como «error al ejecutar el modelo», o sea el diagnóstico apuntando al lado
                # equivocado.
                _info_upstream = res_data.get("guardrail_info")
                eventos_del_upstream = (
                    _info_upstream.get("guardrail_events")
                    if isinstance(_info_upstream, dict) else None) or []

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
                if "bloqueada" in body_lower or "guardrail" in body_lower or "sentinel" in body_lower:
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
                error_detail = "Sentinel Gateway error"
                try:
                    error_json = response.json()
                    if "error" in error_json and "message" in error_json["error"]:
                        error_detail = error_json["error"]["message"]
                except Exception:
                    error_detail = response.text

                # White-label
                error_detail = error_detail.replace("litellm", "Sentinel Gateway").replace("LiteLLM", "Sentinel Gateway")
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
    except EngineSaturatedError as exc:
        # El motor está a capacidad y este pedido NO se encoló (nodo C1).
        #
        # Registrar → bloquear, la MISMA matriz que los tres puntos de bloqueo de política:
        # fila durable primero (una sola por rechazo), vitrina después, respuesta al final —
        # incluidos los modos `open`/`closed`, que `_registrar_bloqueo` ya resuelve y acá no se
        # reimplementan. Un rechazo sin rastro sería justo el agujero que cerró la 031: el día
        # que la sede pregunte «¿cuántos pedidos rebotamos el martes?», la respuesta tiene que
        # estar en la base y no en el recuerdo de nadie.
        #
        # El estado NO es un `blocked_*`: ninguna capa bloqueó nada (ver `STATUS_SATURATED`).
        logger.warning("engine_gate: pedido rechazado por capacidad (model=%s): %s",
                       routed_model, exc)
        # Contrato de wire de La ITV: la cabecera viaja en TODO 503 de saturación, incluido el
        # que puede salir de `_registrar_bloqueo` si la auditoría está caída en modo `closed`
        # (H6 del gate). Se arma una sola vez y se usa en los dos caminos para que no puedan
        # divergir.
        cabeceras_de_saturacion = {"Retry-After": RETRY_AFTER_SATURATED,
                                   HEADER_REJECTED: HEADER_REJECTED_SATURATED}
        await _registrar_bloqueo(
            db=db, user=user, api_key_obj=api_key_obj, group=group, tenant_id=_tenant_id,
            model=routed_model, estado=STATUS_SATURATED,
            prompt=request.message, entities=_entities,
            attribution=build_attribution(profile, verdicts, credentials=_credentials),
            start_time=start_time, routing=_routing_decision,
            entidades_fila=_entidades_de_fila(_floor_entities, _entities),
            cabeceras_del_503=cabeceras_de_saturacion,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            # Detalle HONESTO: se dice lo que pasó y lo que se decidió, sin disfrazarlo de
            # error del modelo. `code` es el mismo literal que va a la fila durable, para que
            # el harness de carga (y cualquier cliente) distinga este rechazo sin parsear copy.
            detail={
                "code": STATUS_SATURATED,
                "message": ("El modelo está a capacidad; el pedido no se encoló para no "
                            "degradar el resto del producto. Reintentá en unos segundos."),
            },
            headers=cabeceras_de_saturacion,
        ) from exc
    except Exception as e:
        # Check if we were able to reach the server. If yes, it's a model execution error.
        if "response" in locals() and response is not None:
            err_msg = str(e)
            if "litellm." in err_msg:
                parts = err_msg.split(":", 1)
                if len(parts) > 1:
                    err_msg = parts[1].strip()
            err_msg = err_msg.replace("litellm", "Sentinel Gateway").replace("LiteLLM", "Sentinel Gateway")
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

    # Modelo con el que se PRICEA: el que CONTESTÓ (FR-009 / Principio V, research R7).
    #
    # El motor devuelve en `model` quién respondió de verdad — verificado en vivo el 28-jul:
    # con OpenAI caído, la respuesta llegó del modelo local y el campo lo decía. Es la única
    # fuente honesta cuando `router_settings.fallbacks` sustituye el destino sin avisar.
    # Respaldo: `routed_model`, que es lo que efectivamente se le mandó al motor (ya incluye
    # el re-ruteo del guardián `sensitive_routing`); `request.model` sería lo que el pipeline
    # eligió antes de ese guardián y por lo tanto una afirmación más débil.
    #
    # SOLO en el camino «auto», a propósito: el gap —cobrar el modelo pedido cuando contestó
    # otro— es viejo y general, pero generalizarlo acá cambiaría el coste de TODO el tráfico
    # a días de la demo. Queda anotado en research R7 para su propia spec. En el camino auto
    # no es una mejora opcional: el literal «auto» no pricea nada y el ruteo existe
    # precisamente para que el ahorro sea visible y cierto.
    #
    # El nombre de la respuesta se adopta solo si el tarifario lo CONOCE: los proveedores
    # devuelven ids versionados (`gpt-4o-mini-2024-07-18`) que no están en la tabla y
    # caerían en el `default` conservador de $5/$15 — cobrar treinta veces de más por un
    # modelo económico, en nombre de la honestidad, sería el mismo bug al revés.
    _billing_model = request.model
    if _routing_decision is not None:
        _answered_model = (raw_response_json.get("model")
                           if isinstance(raw_response_json, dict) else None)
        _billing_model = (_answered_model
                          if isinstance(_answered_model, str) and has_known_pricing(_answered_model)
                          else routed_model)

    cost = actual_cost if actual_cost is not None else BudgetService.calculate_cost(_billing_model, prompt_tokens, completion_tokens)

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
    # devuelve atribución propia — eso es T025 (`sentinel_guardrail.py`), bloqueada por el
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
    #
    # La regla vive en `_entidades_de_fila` porque los otros tres escritores que llegan con
    # entidades ya medidas (bloqueo por política, bloqueo por residencia y el rechazo por
    # capacidad) la necesitan idéntica: una fila de rechazo que contara la PII distinto que
    # una servida haría que el mismo texto apareciera con dos hallazgos según lo hubiéramos
    # dejado pasar.
    _pii_row_entities = _entidades_de_fila(_floor_entities, entities_detected)
    _pii_row_detected = bool(_pii_row_entities)

    # SEXTO escritor de la columna, y el único que no pasa por `_registrar_bloqueo` (018 capa
    # B). El camino feliz no está fuera de tiro: alcanza con que exista un modelo llamado
    # `license` en el catálogo del motor —un `developer` lo registra— para que un pedido
    # SERVIDO se escriba con el literal reservado y se borre de los mismos agregados. Se sanea
    # acá, con la misma función, y el valor saneado es el que después va también al evento de
    # vitrina del final: una sola variable para que la fila y la vitrina no puedan divergir.
    #
    # Lo que a propósito NO se sanea: `routed_model` —lo que se le mandó al motor, y el motor
    # tiene que recibir el nombre que el cliente eligió o el pedido no se sirve— y
    # `_billing_model`, que no toca ninguna columna durable (es el tarifario y el badge de
    # honestidad del Playground). Renombrar ahí cambiaría un precio por un motivo de auditoría.
    _modelo_de_la_fila = _modelo_auditable(request.model)

    # Save to Audit Log
    #
    # ── Por qué esta llamada está envuelta y antes no lo estaba ──────────────────────
    #
    # `log_transaction` propaga `AuditUnavailableError` cuando el pedido exige registro y la
    # escritura se agotó. Medido con AST sobre `main@179ad0f9`: de los CINCO call-sites del
    # escritor, éste era el ÚNICO de un plano de tráfico sin `except` alguno —
    # `_registrar_bloqueo` y `gateway._audit` la capturan por tipo. O sea que en `closed`,
    # con el pre-check ya pasado (la base contestó el `SELECT 1`) y el INSERT final
    # agotándose después, el usuario recibía un **500** con la respuesta del proveedor ya
    # pagada y tirada. Defecto preexistente de la 031, angosto porque sólo lo alcanzaba una
    # instalación en `closed` explícito.
    #
    # La 038 lo ENSANCHA —`policy` es el default y también corta—, así que se paga acá y no
    # como issue aparte: este PR es el que lo vuelve alcanzable para cualquier instalación.
    # El 503 es la respuesta honesta y la que el contrato ya define; el 500 no dice nada y
    # además invita a reintentar contra un backend que está sano.
    try:
        audit_log = AuditService.log_transaction(
            db=db,
            exige_registro=_exige_registro,
            # Modelo EFECTIVO: con «auto», `request.model` ya es el destino que el router
            # eligió (se reasignó al principio del endpoint). La fila jamás dice «auto» —
            # «auto» no es un modelo y una auditoría que lo registrara no podría responder
            # "¿a qué proveedor viajó este pedido?". Lo que el usuario pidió queda en
            # `routing_decision.requested`, que es donde se puede leer sin ambigüedad.
            model=_modelo_de_la_fila,
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
            # Triggers locales + lo del upstream ANIDADO: el índice 0 nunca es un objeto ajeno
            # (018 capa B — el porqué entero está arriba de `_eventos_de_la_fila`).
            guardian_events=_eventos_de_la_fila(guardian_triggers, eventos_del_upstream),
            # Atribución 027. `guardian_events` sigue igual, congelado como legado (D6: la
            # hash-chain de licencias lo relee posicionalmente); las columnas nuevas viven al
            # lado y son las que el dashboard y el monitor pasan a consultar.
            applied_layers=attribution.applied_layers,
            blocked_by_layer=attribution.blocked_by_layer,
            # Copia DURABLE de la decisión de ruteo (spec 030 FR-006, data-model §2-§3).
            # `None` en todo pedido no-«auto», y `None` significa exactamente "este pedido no
            # pasó por el auto-router" — no "el router no decidió". Columna propia: meterlo en
            # `guardian_events` rompería la hash-chain de licencias, que lo relee por posición.
            routing_decision=_routing_decision,
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
    except AuditUnavailableError as exc:
        # La respuesta del proveedor YA se pagó y acá se descarta a propósito: servirla
        # sería exactamente lo que el modo prohíbe —tráfico sin fila—, y el contrato de la
        # 031 ya define el 503 como la forma honesta de decirlo. El `record_audit_loss` no
        # se repite acá: lo hizo el escritor antes de propagar (audit_service, presupuesto
        # agotado), y contarlo dos veces inflaría `sentinel:audit:lost`, que es CONSTANCIA de
        # eventos perdidos y no una métrica de reintentos.
        logger.error("audit: la fila del pedido SERVIDO no se pudo escribir y el pedido "
                     "exige registro (modo=%s riesgo=%s) — 503 en vez del 200 (model=%s)",
                     audit_fail_mode(), _applied_risk_level, _modelo_de_la_fila)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detalle_503_audit(),
        ) from exc

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
        # Mismo modelo que el del cálculo de coste (R7): el presupuesto se descuenta por lo
        # que se consumió de verdad. Hoy `override_cost` manda igual, pero dejar acá el
        # modelo pedido sería una bomba dormida para el día que ese override desaparezca.
        model=_billing_model,
        override_cost=Decimal(str(cost))
    )

    # Attach rate limit headers if a virtual key was used
    if api_key_obj:
        if _rpm_remaining is not None:
            http_resp.headers["X-RateLimit-Remaining-Requests"] = str(_rpm_remaining)
        if _tpm_remaining is not None:
            http_resp.headers["X-RateLimit-Remaining-Tokens"] = str(_tpm_remaining)

    # Vitrina «Conexiones en vivo»: el ÉXITO del plano chat (spec 030, research R6/SC-004).
    #
    # Hasta acá este plano solo publicaba sus tres BLOQUEOS: en la vitrina, el chat existía
    # únicamente cuando el firewall rechazaba algo. Con el auto-router eso deja de ser una
    # laguna cosmética — la demo es "tres prompts, tres modelos destino, visibles sin tocar
    # nada" (SC-004), y eso no se puede ver si el camino feliz no publica.
    #
    # El `status` es el MISMO vocabulario que ya emiten los otros dos productores para un
    # pedido servido (`passed` / `flagged_high_risk`, gateway.py:285): la vitrina tiene una
    # tabla cerrada de estados y un literal inventado —«allowed», «masked»— caería en el
    # fallback gris de `estado()` y se leería como "estado desconocido". Lo que se enmascaró
    # ya viaja donde corresponde, en `masked_entities`, que es lo que la vitrina pinta como
    # `3× EMAIL_ADDRESS`.
    await _publish_chat_event(
        db=db, user=user, tenant_id=_tenant_id, model=_modelo_de_la_fila,
        status=compliance_result["status"], prompt=request.message,
        entities=entities_detected, attribution=attribution,
        routing=_routing_decision,
    )

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

    # Capa 04 del Debugger Técnico + decisión del auto-router (spec 030, FR-006).
    #
    # `auto_router` se AGREGA solo cuando el pedido fue «auto»: la clave AUSENTE significa
    # "este pedido no pasó por el router" y un `null` significaría "pasó y no decidió
    # nada", que es falso. Es la misma distinción ausencia-de-dato vs ausencia-de-acción
    # que el evento de la vitrina y la columna durable sostienen del otro lado, y la que
    # permite que el Debugger no pinte una sección de ruteo vacía en cada consulta normal.
    _layer_llm = {
        # `_billing_model`, no `routed_model`: tras un fallback del motor es el modelo que
        # CONTESTÓ (con la misma guarda de tarifario del coste) — el badge de honestidad
        # del Playground compara contra esto y con el modelo mandado jamás dispararía.
        "model_used": _billing_model,
        "latency_ms": latency_ms,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_usd": float(cost),
        "raw_request_json": raw_request_json,
        "raw_response_json": raw_response_json
    }
    if _routing_decision is not None:
        _layer_llm["auto_router"] = _routing_decision

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
            "layer_llm": _layer_llm,
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
    """Catálogo conversable: los modelos del motor, más el pseudo-modelo «auto».

    Dos cosas que este endpoint hace y que NO son cosméticas (spec 030, contrato §GET):

    1. **«auto» se antepone** cuando el router está encendido. No existe en el motor: lo
       inyecta este endpoint para que el usuario final lo elija como un modelo más (FR-001).
       Va PRIMERO porque el Playground y el portal preseleccionan el índice 0 — o sea que el
       orden acá es la decisión de producto "el ruteo inteligente es el default".
    2. **El modelo de embeddings se EXCLUYE.** `router-embeddings` es infraestructura del
       ruteo, no un modelo de conversación: si aparece en el desplegable, alguien lo elige y
       recibe un error del motor (un modelo de embeddings no contesta chat). Se filtra por el
       nombre que declara la config del router, no por un literal, para que un cliente que
       renombre su entrada de embeddings no lo vea reaparecer en la lista.
    """
    config_path = _get_config_path()
    try:
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f) or {}

        router_cfg = _router_config_safe()
        embedding_model = (router_cfg.get("embedding_model")
                           or auto_router_service.DEFAULT_CONFIG["embedding_model"])

        result = []
        if router_cfg.get("enabled"):
            result.append({
                "model_name": auto_router_service.AUTO_MODEL,
                "provider": auto_router_service.AUTO_MODEL,
                "model_id": auto_router_service.AUTO_MODEL,
                # Se declara configurado y conforme porque el destino REAL lo elige el
                # router entre los modelos del catálogo, y cada uno responde por sí mismo:
                # «auto» no habla con ningún proveedor, así que no tiene credencial propia
                # ni residencia propia que afirmar.
                "is_configured": True,
                "is_eu_compliant": True,
            })

        for m in config_data.get("model_list", []):
            if m.get("model_name") == embedding_model:
                continue
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

def _write_fallback(config_data: dict, model_name: str, fallback_model: Optional[str]) -> None:
    """Escribe (o borra) el respaldo de `model_name` en `router_settings.fallbacks`.

    Única implementación del formato del motor (`[{origen: [destino]}]`), compartida por el
    `PUT /fallbacks` del admin y por el alta automática de modelos: dos escritores con dos
    versiones del mismo formato es cómo un `fallbacks` termina con entradas duplicadas que
    el motor resuelve por orden de aparición.
    """
    if "router_settings" not in config_data:
        config_data["router_settings"] = {"disable_cooldowns": True}
    fallbacks = config_data["router_settings"].get("fallbacks", []) or []
    fallbacks = [item for item in fallbacks if isinstance(item, dict) and model_name not in item]
    if fallback_model:
        fallbacks.append({model_name: [fallback_model]})
    config_data["router_settings"]["fallbacks"] = fallbacks


def _default_local_model(config_data: dict) -> Optional[str]:
    """Modelo local al que debe caer un cloud (US3 / research R8), o `None` si no hay.

    Prioridad: el `default_model` del router **si es local**, si no el primer local
    declarado en el catálogo. El orden no es arbitrario — el `default_model` es la elección
    explícita del admin sobre "a qué modelo local va lo que no tiene destino", así que el
    respaldo de un cloud debe ser el mismo: dos respuestas distintas a la misma pregunta
    ("¿cuál es TU modelo local?") es exactamente lo que confunde en una instalación con
    varios Ollama, que es el caso que la spec vino a resolver.
    """
    locales = _local_models(config_data)
    if not locales:
        return None
    nombres = {m.get("model_name") for m in locales}
    preferido = _router_config_safe().get("default_model")
    if preferido in nombres:
        return preferido
    return locales[0].get("model_name")


@router.post("/models", dependencies=[Depends(require_role("admin", "developer"))])
async def register_model(model_in: ModelCreateSchema):
    # Mismo resolutor de path que el resto del plano (era una copia literal inline): con dos
    # resoluciones distintas, un cambio en una de ellas hace que el alta escriba en un
    # fichero y la lectura mire otro.
    config_path = _get_config_path()

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

    # Fallback siempre-a-local (spec 030 US3 / FR-007, decisión sellada de JF 28-jul).
    #
    # Un modelo cloud nace con respaldo al modelo local del cliente: si el proveedor se cae,
    # su gente sigue trabajando en el hardware propio y a coste 0, sin que nadie configure
    # nada. Es un DEFAULT, no una opción escondida — el admin puede cambiarlo después por el
    # `PUT /fallbacks`.
    #
    # Al revés jamás (`local → cloud`): eso sacaría los datos del host justo cuando falla la
    # única pieza que garantizaba que no salieran. Por eso este bloque exige que el modelo
    # nuevo NO sea local, y el PUT rechaza el mismo caso a mano (regla enforced en los dos
    # escritores, no solo documentada).
    #
    # GOTCHA OPERATIVO: el motor lee `config.yaml` al arrancar, así que el respaldo entra en
    # vigor recién con el próximo ciclo del supervisor (spec 033) — el admin lo dispara con
    # «Aplicar cambios del motor» (T006, `GET/POST /models/status` y `/models/apply` acá
    # arriba). Ya NO hace falta el `docker restart camara-litellm-1` manual que pedía
    # INSTALL-CAMARA.md antes de T006/T008; el paso quedó reemplazado por ese botón.
    fallback_local = None
    if not _is_local_entry(new_model_entry):
        fallback_local = _default_local_model(config_data)
        if fallback_local:
            _write_fallback(config_data, model_in.model_name, fallback_local)

    try:
        _write_engine_config(config_data)
    except Exception as e:
        logger.error(f"Failed to write litellm config: {e}")
        raise HTTPException(status_code=500, detail="Failed to save model configuration")

    mensaje = f"Model {model_in.model_name} registered successfully"
    if fallback_local:
        mensaje += f" (respaldo automático al modelo local «{fallback_local}»)"
    return {"status": "success", "message": mensaje, "fallback_model": fallback_local}

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
        _write_engine_config(config_data)
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
        _write_engine_config(config_data)
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
    """Define o borra el respaldo de un modelo (`router_settings` del config del motor).

    **El origen no puede ser un modelo local** (spec 030 US3 / FR-007). Un respaldo
    `local → cloud` significa: "cuando el modelo que corre en tu hardware falle, mandá los
    datos afuera" — o sea, romper la residencia justo en el momento en que nadie la está
    mirando, y hacerlo en silencio. La regla ya estaba escrita en el config del motor como
    comentario; acá pasa a estar **enforced** en el escritor, que es el único lugar donde
    puede dejar de ser una convención.

    Borrar el respaldo de un modelo local SÍ se permite: quitar una entrada nunca crea una
    fuga, y negarlo dejaría atrapado a un admin que heredó una configuración mal hecha.
    """
    config_path = _get_config_path()
    try:
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to read config")

    if body.fallback_model:
        origen = next((m for m in (config_data.get("model_list") or [])
                       if isinstance(m, dict) and m.get("model_name") == model_name), None)
        if origen is not None and _is_local_entry(origen):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"«{model_name}» es un modelo local: no se le puede configurar un "
                       "respaldo, porque una caída suya mandaría los datos fuera del host y "
                       "la residencia que motiva tener el modelo local se perdería. El "
                       "respaldo válido va al revés: de un modelo de la nube al local.",
            )

    _write_fallback(config_data, model_name, body.fallback_model)

    try:
        _write_engine_config(config_data)
    except Exception as e:
        logger.error("Failed to write config: %s", e)
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


# --- Supervisor del motor: estado y botón «Aplicar» (spec 033, T004/T005) ---
#
# El supervisor (litellm/supervisor.py, PR-A #301) vigila `config.yaml` y el sentinel
# `apply.trigger`, valida el YAML antes de matar al proceso viejo y publica su estado en
# `status.json`. Estos dos endpoints son la única superficie del backend sobre ese
# mecanismo: uno lo LEE, el otro lo DISPARA. Ninguno de los dos habla con Docker — los
# dos son archivos en un volumen compartido, que es justo lo que hace que "el backend
# jamás toca el daemon" siga siendo cierto con esta feature adentro.

_ENGINE_STATUS_KEYS = ("state", "ts", "last_error", "config_hash")
# Nombre SIN "STATUS"/"COMPLIANCE" a propósito: el censo de `test_retention_classifier.py`
# escanea el fuente por regex buscando constantes `*STATUS*`/`*COMPLIANCE*` asignadas a un
# literal — es la red que caza `compliance_status` de `audit_logs`, un vocabulario TOTALMENTE
# distinto al `state` de `status.json` del supervisor del motor. Con un nombre que contuviera
# "STATUS" (p. ej. `_ENGINE_STATUS_DESCONOCIDO`) el censo lo confunde con un emisor de
# auditoría sin inventariar; este literal no llega nunca a `audit_logs`.
_ENGINE_ESTADO_DESCONOCIDO = "unknown"


def _get_engine_status_path() -> str:
    """Ruta de `status.json` (spec 033): volumen `engine_status` montado `:ro`
    (`deploy/docker/compose.prod.yml:129`, la copia PR-A del compose — todavía no
    existe en `main` porque PR-B sale sin stackear sobre PR-A a propósito).

    Mismo patrón hardcoded+fallback que `_get_config_path()` de acá arriba, con una
    diferencia real: no hay un `status.json` de repo al que caer, porque lo escribe el
    supervisor en runtime — no es un fichero versionado. La ruta de fallback casi
    siempre va a estar ausente en dev/tests sin contenedor, y esa ausencia ES el caso
    "volumen todavía no montado" que ejercen los tests de T004, no un bug de resolución.
    """
    path = "/app/engine_status/status.json"
    if not os.path.exists(path):
        path = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                            "../../../litellm/engine_status/status.json"))
    return path


def _engine_status_desconocido(motivo: str) -> dict:
    return {"state": _ENGINE_ESTADO_DESCONOCIDO, "ts": None, "last_error": motivo,
            "config_hash": None}


# spec 033, T004. `last_error` sin maquillar es lo que la UI (T006) necesita mostrar.
# El caso "estado ausente" puede pasar si PR-B llega antes que PR-A al mismo entorno —
# no es un bug de resolución, ver `_get_engine_status_path()`. Mismo patrón
# 200-nunca-500 que `GET /chat/router-config`.
@router.get("/models/status", dependencies=[Depends(require_role("admin", "compliance_officer"))])
async def get_engine_status():
    """Estado del supervisor del motor.

    Expone el estado tal cual lo reporta el supervisor: `state`
    (`idle`/`applying`/`error`/`unknown`) + `ts` + `last_error` + `config_hash`, sin
    filtrar ni maquillar un `state=error` — el `last_error` real es lo que el panel
    necesita mostrar para que el admin sepa qué falló.

    **Contrato del caso ausente/corrupto: 200, nunca 500.** Si el supervisor todavía
    no publicó su estado, o lo publicado no se puede leer, responde con
    `state: "unknown"`, `ts`/`config_hash` en `null` y `last_error` con el motivo. Un
    supervisor caído no puede dejar al admin sin la única pantalla desde la que podría
    enterarse de por qué.
    """
    path = _get_engine_status_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            datos = json.load(f)
    except FileNotFoundError:
        return _engine_status_desconocido(
            "status.json no existe todavía: el volumen del motor puede no estar "
            "montado en este entorno, o el supervisor no arrancó."
        )
    except OSError as exc:
        logger.warning("engine status: no se pudo leer status.json (%s)", type(exc).__name__)
        return _engine_status_desconocido(f"status.json no se pudo leer ({type(exc).__name__}).")
    except ValueError as exc:
        logger.warning("engine status: status.json no parsea (%s)", type(exc).__name__)
        return _engine_status_desconocido(f"status.json ilegible ({type(exc).__name__}).")

    if not isinstance(datos, dict):
        return _engine_status_desconocido("status.json no contiene un objeto JSON.")

    return {clave: datos.get(clave) for clave in _ENGINE_STATUS_KEYS}


def _get_engine_sentinel_path() -> str:
    """Ruta del sentinel `apply.trigger` desde el lado del backend (`rw`). Reusa
    `_get_config_path()` para el directorio a propósito (decisión sellada del brief,
    §2): son dos endpoints (`register_model` y este) escribiendo en el mismo volumen
    que sirve `config.yaml`; un segundo resolutor de path es exactamente el bug que ya
    costó una vuelta acá (comentario de `register_model`, arriba)."""
    return os.path.join(os.path.dirname(_get_config_path()), "apply.trigger")


# Se declara un modelo (en vez de dejar el endpoint sin body) para que el gate de rol
# (`Depends` del decorador, nunca inline — regla #251) se pueda probar contra un cuerpo
# inválido: si el gate estuviera inline, un cuerpo que no parsea como este modelo
# devolvería 422 ANTES de llegar al chequeo de rol.
class ModelsApplyRequest(BaseModel):
    """Cuerpo del botón «Aplicar cambios del motor». No tiene campos obligatorios: el
    disparador es la llamada en sí, no el contenido del cuerpo. `reason` es opcional,
    para dejar un motivo legible junto al pedido."""
    reason: Optional[str] = None


# Re-escribe el sentinel `apply.trigger` en el MISMO directorio que resuelve
# `_get_config_path()` — el volumen donde el backend tiene `rw`. El supervisor lo
# espera en otro mountpoint del mismo volumen (`:ro`, `build_default()` de
# `supervisor.py`): es el mismo fichero visto por dos mountpoints, no dos resolutores.
#
# El disparador que mira el supervisor es el `mtime`, no el contenido
# (`Supervisor._stamps()` de `supervisor.py`): `escribir_atomico` hace temporal +
# `os.replace`, así que el mtime cambia en CADA llamada y re-postear vuelve a disparar
# un ciclo. Por eso nunca se borra el sentinel: el supervisor tampoco podría (su lado
# del volumen es `:ro`) y borrarlo no aportaría nada.
@router.post("/models/apply", dependencies=[Depends(require_role("admin"))])
async def apply_engine_changes(payload: Optional[ModelsApplyRequest] = None):
    """Dispara el relanzamiento supervisado del motor: el botón «Aplicar cambios del
    motor» del panel.

    Cada llamada dispara un nuevo ciclo de aplicación, sin importar si ya hay uno en
    curso o recién terminado — no hace falta esperar entre llamadas. El resultado del
    ciclo (éxito, o el error de validación si el config quedó mal escrito) se consulta
    con `GET /models/status`.
    """
    ts = time.time()
    escribir_atomico(
        _get_engine_sentinel_path(),
        lambda f: json.dump({"ts": ts, "reason": payload.reason if payload else None}, f),
    )
    return {"status": "ok", "ts": ts}
