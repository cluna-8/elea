"""Health de licencia (spec 021 US5, T034 — FR-027) y de AUDITORÍA (spec 031 US2, T009).

Metadata-only para operación/soporte: NUNCA el token crudo ni claves. Dos
niveles (lección del review de US4 — números no viajan a anónimos):

- sin sesión: sólo ``{status, clock_rollback_suspected}`` — suficiente para un
  probe de ops ("¿la licencia está sana?") sin filtrar dimensionamiento.
- con sesión válida (JWT): además ``seats_used/max_seats/expiry/reason`` y el
  resumen por tenant de la última reconciliación.

El mismo criterio de dos tiers se aplica al ``GET /api/v1/health`` de la 031: el
estado global (healthy/degraded) es público —es la pregunta que responde un probe— y
los NÚMEROS de auditoría (cuántos eventos se perdieron, cuándo fue el último fallo)
sólo viajan a admin/compliance_officer, que son exactamente los roles que pueden ver
Logs de Auditoría. Publicar "la auditoría lleva 40 eventos sin registrar" a un caller
anónimo es decirle a quien quiera fugar datos cuál es el mejor momento para hacerlo.
"""
import logging
import os
import threading
import time
from typing import Optional, Tuple

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth.rbac import effective_roles
from ..auth.session import get_current_user
from ..database import get_db
from ..licensing import reconcile
from ..licensing.entitlement import expected_tenant_id, get_state
from ..licensing.seat_counter import count_active_seats
from ..models.user import User
from ..services import audit_service
# La librería PURA compartida (`basa_guardian_policy`) ya viene resuelta por
# `presidio_service`, que hace el sys.path dance una sola vez: se reusa desde ahí en vez de
# agregar una CUARTA copia de ese bloque de import al repo. Acá sólo se necesita el
# vocabulario del issue #63 (`resolve_nlp_fail_mode`, `NLP_FAIL_DEGRADE`), que es la MISMA
# función que deciden los dos planos de tráfico — el health no puede tener su propio criterio.
from ..services.presidio_service import policy
from ..services.redis_client import get_redis

logger = logging.getLogger("basa-secure-gateway.health")

router = APIRouter(tags=["Health"])

# Tier detallado: solo roles de operación/soporte (hardening post-review — un
# user client autenticado tampoco tiene por qué ver dimensionamiento/reasons).
_DETAIL_ROLES = {"admin", "compliance_officer"}


@router.get("/health/license")
def license_health(user: Optional[User] = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    state = get_state()
    body = {
        "status": state.status,
        "clock_rollback_suspected": reconcile.clock_rollback_suspected(),
    }
    if user is None or effective_roles(user).isdisjoint(_DETAIL_ROLES):
        return body
    from ..models.license_state import LicenseRuntimeState
    runtime = db.query(LicenseRuntimeState).filter(LicenseRuntimeState.id == 1).one_or_none()
    token = state.token
    tenant_id = expected_tenant_id()
    recon = reconcile.get_tenant_status(tenant_id)
    body.update({
        "reason": state.reason,
        "expiry": token.expiry.isoformat() if token else None,
        "grace_days": token.grace_days if token else None,
        "max_seats": token.max_seats if token else None,
        "seats_used": count_active_seats(db, tenant_id),
        # Génesis EFECTIVA de la cadena: lo que el onboarding debe registrar
        # (si el primer boot fue sin licencia, viaja también el anclaje).
        "chain": {
            "genesis_license_id": runtime.genesis_license_id if runtime else None,
            "anchored_license_id": runtime.anchored_license_id if runtime else None,
            "event_counter": runtime.event_counter if runtime else 0,
        },
        "reconcile": {
            "tenant_status": recon.status if recon else None,
            "checked_at": recon.checked_at.isoformat() if recon else None,
        },
    })
    return body


# ── Health de auditoría (spec 031 US2, T009 — FR-004 / contrato §health) ─────────────
#
# Por qué un `/health` NUEVO bajo /api/v1 y no el `/health` raíz de main.py: ese endpoint
# es el `healthcheck` del contenedor (compose.prod.yml:95). Meterle una lectura de Redis
# y un `SELECT 1` convertiría una degradación de una dependencia en "contenedor unhealthy"
# → reinicio → caída del servicio entero por algo que la 031 define explícitamente como
# NO fatal en `open`. El probe del orquestador tiene que seguir contestando barato y
# siempre; este es el health de PRODUCTO, que es el que puede decir "degradado".
# Lo consume el quickstart (`curl .../api/v1/health | jq .audit`) y el banner de Logs.


def _leer_contadores_de_perdida() -> Tuple[Optional[int], Optional[str]]:
    """`(lost_events, last_failure_at)` desde Redis (contrato §Contador de pérdidas).

    Distinción que importa y que el consumidor NO puede adivinar solo:

    * ``0``    — la auditoría no ha perdido nada (la clave nunca se escribió).
    * ``N``    — hay N eventos sin registrar desde ``last_failure_at``.
    * ``None`` — **no se pudo leer el contador** (Redis caído o valor ilegible). Es
      deliberadamente distinto de ``0``: decir "cero pérdidas" cuando no se pudo mirar
      sería exactamente la mentira que esta spec existe para borrar.

    Nunca propaga: el health no puede caerse porque Redis no esté.
    """
    try:
        redis_conn = get_redis()
        if redis_conn is None:
            logger.warning("health: contador de auditoría ilegible — Redis no disponible")
            return None, None
        crudo = redis_conn.get(audit_service.REDIS_KEY_AUDIT_LOST)
        ultimo = redis_conn.get(audit_service.REDIS_KEY_AUDIT_LAST_FAIL)
    except Exception as exc:  # noqa: BLE001 — Redis caído no puede tumbar el health
        logger.warning("health: contador de auditoría ilegible (%s)", exc)
        return None, None

    perdidos: Optional[int]
    if crudo is None:
        perdidos = 0  # clave nunca escrita = jamás hubo una pérdida
    else:
        try:
            # `decode_responses=True` devuelve str, pero un cliente configurado distinto
            # (o un Redis compartido) puede devolver bytes: se normaliza acá y no en el
            # caller, para que el contrato del bloque sea siempre int|None.
            perdidos = int(crudo.decode() if isinstance(crudo, bytes) else crudo)
        except (TypeError, ValueError):
            logger.warning("health: valor ilegible en %s: %r",
                           audit_service.REDIS_KEY_AUDIT_LOST, crudo)
            perdidos = None
    if isinstance(ultimo, bytes):
        ultimo = ultimo.decode()
    return perdidos, ultimo


def _estado_de_auditoria(db: Session) -> Tuple[str, Optional[str]]:
    """`(modo, motivo_degradado)`.

    El pre-check de escribibilidad SÓLO se paga en `closed` (edge case de la spec: "el
    health refleja el estado, no un healthy mentiroso"). En `open` una auditoría caída no
    degrada el servicio —el tráfico se sigue sirviendo por diseño— y su señal es el
    contador + el banner, así que no hay razón para pagar un `SELECT 1` por cada probe.
    """
    modo = audit_service.audit_fail_mode()
    if modo != audit_service.AUDIT_FAIL_CLOSED:
        return modo, None
    if audit_service.audit_writable(db):
        return modo, None
    return modo, ("auditoría no escribible y la instalación exige registro "
                  "(audit_fail=closed): el tráfico nuevo se rechaza con 503")


# ── Estado de la detección NLP (issue #63) ───────────────────────────────────────────
#
# El bug que este bloque cierra: con `NLP_ANALYZER_URL` configurada y el sidecar caído, el
# producto podía seguir sirviendo con regex y NADA lo decía — ni el panel, ni el health, ni
# la fila de auditoría. "Degradar" es una postura legítima (`nlp_fail_mode = degrade`);
# "degradar sin que se note" no lo es.
#
# Los tres estados son distintos a propósito y no se colapsan:
#   * `not_configured` — no hay sidecar cableado. Es el modo regex de DESARROLLO (Constraint
#     SC-2), una elección de despliegue, no una avería: no degrada el health.
#   * `ok`             — configurado y respondiendo.
#   * `unreachable`    — configurado y NO responde. Sí degrada: o el tráfico se está
#     rechazando (`block`) o se está sirviendo con media protección (`degrade`).
_NLP_PROBE_TIMEOUT_S = 1.5
# Cache del probe: este endpoint es público y sin cache un bucle de monitorización lo
# convertiría en un DoS contra el sidecar (que además es el que atiende el tráfico real).
_NLP_PROBE_CACHE_TTL_S = 10.0
_nlp_probe_cache: Optional[Tuple[float, bool]] = None  # (monotonic, alcanzable)
# Single-flight (hallazgo del review adversarial del #63): este endpoint es `def` síncrono,
# o sea que FastAPI lo corre en el threadpool y N pedidos concurrentes entran de verdad en
# paralelo. Con el cache escrito DESPUÉS del probe y sin lock, los N que caen en la ventana
# disparaban N probes: martilleo al sidecar y N hilos del pool ocupados 1,5 s cada uno, todo
# disparable por callers ANÓNIMOS. El lock hace que sólo uno pruebe y el resto conteste con
# el último valor conocido.
_nlp_probe_lock = threading.Lock()
# Espera máxima del arranque en frío (ver `_nlp_alcanzable`): el probe + margen.
_NLP_PROBE_COLD_WAIT_S = _NLP_PROBE_TIMEOUT_S + 0.5


def _nlp_alcanzable(url: str) -> Tuple[bool, bool]:
    """`(alcanzable, fresco)` — `GET {url}/health`, con cache de ~10 s y single-flight.

    `fresco` es True SÓLO si esta llamada ejecutó el probe de verdad. Lo necesita el
    reseteo de la marca de degradación: borrar constancia a partir de un veredicto que puede
    tener 10 s de antigüedad haría que un poller cada 5 s limpiara marcas RECIÉN escritas
    durante una oscilación del sidecar — justo las que el operador tiene que ver.

    Concurrencia: si otro hilo ya está probando, se contesta con el último valor conocido en
    vez de encolar otro probe. La única espera es el arranque en frío (todavía no hay ningún
    valor): ahí sí conviene esperar al ganador, porque la alternativa es reportar
    `unreachable` sin haber preguntado nunca. Pasa una vez por proceso.

    Nunca propaga."""
    global _nlp_probe_cache
    cache = _nlp_probe_cache
    if cache is not None and time.monotonic() - cache[0] < _NLP_PROBE_CACHE_TTL_S:
        return cache[1], False

    # Las dos ramas van EXPLÍCITAS y no en un `acquire(blocking=en_frio, timeout=…)`
    # parametrizado: CPython prohíbe combinar `blocking=False` con un timeout distinto de -1
    # (`ValueError: can't specify a timeout for a non-blocking call`), y esa forma compacta
    # lo hacía en el camino MÁS común —cache presente y vencido, o sea cualquier worker a
    # partir de su segundo probe—, devolviendo 500 en todo `/health` con NLP configurado.
    # Separarlas hace que la combinación ilegal no se pueda volver a escribir por descuido.
    if cache is None:
        # Arranque en frío: conviene ESPERAR al ganador — la alternativa es reportar
        # `unreachable` sin haber preguntado nunca, o sea una alarma falsa. Pasa una vez.
        adquirido = _nlp_probe_lock.acquire(timeout=_NLP_PROBE_COLD_WAIT_S)
    else:
        # Ya hay un veredicto previo utilizable: nadie espera, se contesta con él.
        adquirido = _nlp_probe_lock.acquire(blocking=False)
    if not adquirido:
        # Otro hilo está probando. Con valor previo se contesta ese; sin valor previo
        # (arranque en frío que agotó la espera) se degrada honesto, sin probar.
        cache = _nlp_probe_cache
        return (cache[1] if cache is not None else False), False
    try:
        # Re-check bajo el lock: el ganador pudo terminar mientras esperábamos.
        cache = _nlp_probe_cache
        if cache is not None and time.monotonic() - cache[0] < _NLP_PROBE_CACHE_TTL_S:
            return cache[1], False
        try:
            r = httpx.get(f"{url.rstrip('/')}/health", timeout=_NLP_PROBE_TIMEOUT_S)
            alcanzable = r.status_code == 200
        except Exception as exc:  # noqa: BLE001 — el sidecar caído no puede tumbar el health
            logger.warning("health: el motor de detección NLP no responde (%s)", exc)
            alcanzable = False
        _nlp_probe_cache = (time.monotonic(), alcanzable)
        return alcanzable, True
    finally:
        _nlp_probe_lock.release()


def _fail_mode_efectivo(db: Session, tenant_id) -> str:
    """`nlp_fail_mode` que aplicaría HOY para el tenant de la sesión, resuelto por la MISMA
    función que usan los dos planos de tráfico. Se muestra en el health porque "qué va a
    pasar si el NLP se cae" es justamente la pregunta que el operador no podía responder
    antes del #63.

    El filtro por `tenant_id` es load-bearing (hallazgo del review adversarial): sin él,
    `.first()` sobre `guardians` devolvía la fila de CUALQUIER tenant, así que en una
    instalación multi-tenant un admin podía ver publicada la postura de otro — lectura
    cross-tenant, prohibida por Constitución III. Se resuelve igual que en `_nlp_context`
    del gateway, contra el tenant del que pregunta.

    Sin fila legible ⇒ el default fail-closed (`block`), que es lo que de verdad aplicaría."""
    from ..models.guardian import Guardian
    try:
        fila = (db.query(Guardian.config)
                .filter(Guardian.tenant_id == tenant_id,
                        Guardian.guardian_type == "pii_masking",
                        Guardian.is_active.is_(True))
                .first())
        return policy.resolve_nlp_fail_mode((fila[0] if fila else None) or {})
    except Exception as exc:  # noqa: BLE001
        logger.warning("health: config del guardián PII no legible (%s); se reporta el "
                       "default fail-closed", exc)
        return policy.resolve_nlp_fail_mode(None)


# Marcador del motivo para el tier anónimo: ahí `reason` no se publica, así que sólo
# importa su PRESENCIA (decide `status: degraded`). Redactar el motivo real cuesta una
# consulta a `guardians` y una lectura de Redis, y este endpoint es público: no se pagan
# para un campo que no va a viajar.
_MOTIVO_NLP_SIN_DETALLE = "detección NLP no disponible"


def _estado_nlp(db: Session, detallado: bool, tenant_id=None) -> Tuple[Optional[dict],
                                                                      Optional[str]]:
    """`(bloque_nlp|None, motivo_degradado|None)` del contrato §health (issue #63).

    Con `detallado=False` devuelve sólo si hay degradación (el bloque es del tier de
    operación) y **no toca ni la base ni Redis**: el probe al sidecar ya viene cacheado."""
    url = os.environ.get("NLP_ANALYZER_URL", "").strip()
    if not url:
        # Camino de dev/demo: honesto y visible, pero no es una avería que degrade el probe.
        if not detallado:
            return None, None
        return {"configured": False, "status": "not_configured",
                "degraded_since": None, "degraded_requests": 0,
                "fail_mode_efectivo": None}, None

    alcanzable, fresco = _nlp_alcanzable(url)
    if not detallado:
        # El tier anónimo NO escribe en Redis (hallazgo del review adversarial: el `clear`
        # estaba antes de este `return`, o sea que era una escritura disparable SIN
        # credenciales, y contradecía el docstring de arriba).
        return None, None if alcanzable else _MOTIVO_NLP_SIN_DETALLE

    if alcanzable and fresco:
        # ÚNICO punto de reseteo de la marca: se limpia cuando se CONFIRMA —ahora mismo, con
        # un probe FRESCO— que el analyzer volvió, no por el paso del tiempo (las claves no
        # tienen TTL a propósito). Exigir `fresco` evita que un poller cada 5 s borre marcas
        # recién escritas apoyándose en un veredicto cacheado de hasta 10 s de antigüedad:
        # durante una oscilación del sidecar, esas marcas son justo la evidencia que el
        # operador necesita. Y que sea sólo el camino de admin evita que un anónimo pueda
        # provocar el borrado.
        audit_service.clear_nlp_degradation()

    desde, degradadas = audit_service.read_nlp_degradation()
    fail_mode = _fail_mode_efectivo(db, tenant_id)
    bloque = {
        "configured": True,
        "status": "ok" if alcanzable else "unreachable",
        "degraded_since": None if alcanzable else desde,
        "degraded_requests": 0 if alcanzable else degradadas,
        "fail_mode_efectivo": fail_mode,
    }
    if alcanzable:
        return bloque, None
    if fail_mode == policy.NLP_FAIL_DEGRADE:
        return bloque, ("el motor de detección de datos personales no responde y la política "
                        "es degradar (nlp_fail_mode=degrade): el tráfico se está sirviendo "
                        "con detección por patrones, con cobertura de PII/PHI REDUCIDA")
    return bloque, ("el motor de detección de datos personales no responde y la política es "
                    "bloquear (nlp_fail_mode=block): el tráfico con enmascarado activo se "
                    "está rechazando")


@router.get("/health")
def service_health(user: Optional[User] = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Health del producto, con los bloques `audit` (031 §health) y `nlp` (issue #63).

    Tier anónimo: `{status, service, version}` — el estado global sí es público (un probe
    de ops sin credenciales tiene que poder preguntar "¿esto está sano?"), los números no.
    Tier admin/compliance_officer: además `audit {mode, lost_events, last_failure_at}`,
    `nlp {configured, status, degraded_since, degraded_requests, fail_mode_efectivo}` y el
    `reason` de la degradación.

    El bloque `nlp` va en el tier DETALLADO por el mismo criterio que los números de
    auditoría: "el detector de datos personales está caído ahora mismo" es exactamente el
    dato que le diría a quien quiera fugar información cuál es el mejor momento. Lo que sí
    es público es el `status: degraded` — un probe de ops tiene que verlo, y por sí solo no
    dice qué se cayó.
    """
    detallado = user is not None and not effective_roles(user).isdisjoint(_DETAIL_ROLES)
    modo, motivo_auditoria = _estado_de_auditoria(db)
    # El tenant sale de la SESIÓN, nunca de un parámetro del pedido: es lo que hace que un
    # admin vea la postura de su organización y sólo la suya (Constitución III).
    nlp, motivo_nlp = _estado_nlp(db, detallado, getattr(user, "tenant_id", None))
    # Los dos motivos se concatenan en vez de que el primero gane: si el stack está
    # degradado por dos razones distintas, esconder una haría que el operador arreglara la
    # que ve y creyera que terminó.
    motivos = [m for m in (motivo_auditoria, motivo_nlp) if m]
    body = {
        "status": "degraded" if motivos else "healthy",
        "service": os.getenv("BRAND_SERVICE_ID", "basa-secure-ai-gateway-backend"),
        "version": "1.0.0",
    }
    if not detallado:
        return body

    perdidos, ultimo_fallo = _leer_contadores_de_perdida()
    body["audit"] = {
        "mode": modo,
        "lost_events": perdidos,
        "last_failure_at": ultimo_fallo,
    }
    body["nlp"] = nlp
    body["reason"] = " | ".join(motivos) if motivos else None
    return body
