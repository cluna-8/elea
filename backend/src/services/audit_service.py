import logging
import os
import time
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from uuid import UUID

from ..models.audit import AuditLog
from .redis_client import get_redis

logger = logging.getLogger("basa-secure-gateway.audit")


# ── Política de fallo de auditoría (spec 031, D4/D5 + contrato §Config) ───────────
#
# `BASA_AUDIT_FAIL` decide qué pasa cuando la fila durable NO se puede escribir:
#
#   * `open`   (DEFAULT, y el del piloto): el tráfico se sigue sirviendo, pero el fallo
#              deja de ser invisible — se reintenta acotado, se cuenta en Redis y se
#              loguea con nivel error. Nunca un `print`, nunca un `return None` mudo.
#   * `closed` instalaciones que exigen «sin auditoría no hay servicio»: la escritura
#              agotada propaga `AuditUnavailableError`, que los planos convierten en 503
#              honesto (mismo patrón que el fail-closed de licencias, 021).
#
# Es el ÚNICO lector de la env en el backend (T001: helper único): chat, gateway y health
# preguntan por acá, así que un typo o un valor raro degrada a `open` en un solo lugar.
AUDIT_FAIL_OPEN = "open"
AUDIT_FAIL_CLOSED = "closed"
AUDIT_FAIL_ENV = "BASA_AUDIT_FAIL"

# Contador de pérdidas (contrato §Contador de pérdidas). Sin TTL a propósito: es
# CONSTANCIA de que hubo eventos sin registrar, no una métrica que se auto-borra.
REDIS_KEY_AUDIT_LOST = "basa:audit:lost"
REDIS_KEY_AUDIT_LAST_FAIL = "basa:audit:last_fail"

# Presupuesto FIJO de reintentos (D5): 2 reintentos, backoff 0.2 s y 0.5 s → 3 intentos
# y <1,5 s en el peor caso. Es el edge case anti-DoS de la spec: ante una avalancha de
# fallos el contador es la válvula, jamás una cola infinita ni un backoff que crezca.
AUDIT_RETRY_BACKOFFS_SECONDS = (0.2, 0.5)

# Timeout del `SELECT 1` del pre-check `closed`: barato a propósito (se paga por request
# durante una caída), y corto para que el 503 llegue antes que el timeout del cliente.
AUDIT_PROBE_TIMEOUT_MS = 1500


class AuditUnavailableError(RuntimeError):
    """La fila durable de auditoría no se pudo escribir y la instalación corre en
    `BASA_AUDIT_FAIL=closed`.

    Excepción TIPADA a propósito: los planos (chat, gateway, passthrough) la capturan por
    tipo para devolver un 503 honesto — no un 500 genérico ni, peor, un 200 sobre tráfico
    que nadie registró. En `open` jamás se lanza (compatibilidad con todos los callers
    previos a la 031).
    """


def audit_fail_mode() -> str:
    """`open` | `closed` leído de `BASA_AUDIT_FAIL` (contrato §Config).

    Default `open` si la env falta, viene vacía o trae cualquier otra cosa: una env mal
    tipeada NO puede convertirse en un corte de servicio silencioso — el fail-closed es
    una decisión explícita de la instalación, no un accidente de configuración.
    Se lee por llamada (no se cachea en un módulo) para que un `docker compose up -d` con
    la env cambiada surta efecto sin rebuild y para que los tests la puedan monkeypatchear.
    """
    raw = os.getenv(AUDIT_FAIL_ENV, "").strip().lower()
    return AUDIT_FAIL_CLOSED if raw == AUDIT_FAIL_CLOSED else AUDIT_FAIL_OPEN


def _wait(seconds: float) -> None:
    """Indirección del sleep del backoff — punto de monkeypatch de los tests (que no
    tienen por qué pagar 0,7 s reales para verificar el presupuesto de reintentos)."""
    time.sleep(seconds)


def record_audit_loss(reason: str = "") -> None:
    """Deja constancia de UN evento de auditoría perdido (contrato §Contador de pérdidas):
    `INCR basa:audit:lost` + `SET basa:audit:last_fail <iso>`.

    Tolerante a Redis caído: si el contador tampoco se puede escribir, queda el
    `logger.error` — que es el piso de esta spec (que la pérdida NUNCA sea silenciosa).
    Jamás propaga: es el camino de degradación, no puede él mismo romper el request.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        redis_conn = get_redis()
        if redis_conn is None:
            logger.error(
                "audit: evento PERDIDO sin contador — Redis no disponible (%s). "
                "motivo=%s ts=%s", REDIS_KEY_AUDIT_LOST, reason, now_iso,
            )
            return
        redis_conn.incr(REDIS_KEY_AUDIT_LOST)
        redis_conn.set(REDIS_KEY_AUDIT_LAST_FAIL, now_iso)
    except Exception as exc:  # noqa: BLE001 — el contador es best-effort, el log NO
        logger.error(
            "audit: evento PERDIDO y el contador de pérdidas falló (%s): %s | motivo=%s ts=%s",
            REDIS_KEY_AUDIT_LOST, exc, reason, now_iso,
        )


# ── Estado de la degradación NLP (issue #63) ─────────────────────────────────────────
#
# Vive en ESTE módulo —y no en uno nuevo— por la misma razón por la que el contador de
# pérdidas vive acá: es el sitio del backend que ya sabe escribir "constancia de algo que
# salió mal" en Redis con la disciplina correcta (tolerante a Redis caído, jamás propaga,
# el `logger.error` como piso innegociable). Duplicar ese patrón en otro archivo es cómo se
# terminan teniendo dos formas distintas de contar la misma clase de hecho.
#
# Las claves son las MISMAS que escribe el plano motor (`litellm/extensions/basa_guardrail.py`,
# `_marcar_nlp_degradado`): el health tiene que poder responder "¿se está degradando?" sin
# preguntarle a cada plano por separado, igual que ya hace con `basa:audit:lost`.
#
# Sin TTL, igual que el contador de pérdidas: es CONSTANCIA, no una métrica que se auto-borre.
# El único que limpia es `GET /api/v1/health` cuando CONFIRMA que el analyzer volvió a
# responder (un solo punto de reseteo, documentado allá) — nunca el paso del tiempo.
REDIS_KEY_NLP_DEGRADED_SINCE = "basa:nlp:degraded_since"
REDIS_KEY_NLP_DEGRADED_COUNT = "basa:nlp:degraded_requests"


def record_nlp_degradation(reason: str = "") -> None:
    """Deja constancia de UNA request servida con regex por analyzer NLP caído (issue #63).

    `SET NX` en `degraded_since` (instante de la PRIMERA degradación: el operador necesita
    "desde cuándo", no "la última vez") + `INCR` del contador. El `logger.error` es
    obligatorio y va SIEMPRE, aunque Redis ande: la promesa del #63 es que degradar nunca sea
    silencioso, y un contador que nadie mira no es ruido suficiente.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    logger.error(
        "nlp: pedido servido con detección REGEX de dev porque el motor NLP no responde "
        "(nlp_fail_mode=degrade). Cobertura de PII REDUCIDA. motivo=%s ts=%s", reason, now_iso,
    )
    try:
        redis_conn = get_redis()
        if redis_conn is None:
            logger.error("nlp: degradación sin marca de estado — Redis no disponible (%s)",
                         REDIS_KEY_NLP_DEGRADED_SINCE)
            return
        redis_conn.set(REDIS_KEY_NLP_DEGRADED_SINCE, now_iso, nx=True)
        redis_conn.incr(REDIS_KEY_NLP_DEGRADED_COUNT)
    except Exception as exc:  # noqa: BLE001 — la marca es best-effort, el log NO
        logger.error("nlp: degradación y la marca de estado (%s) también falló: %s",
                     REDIS_KEY_NLP_DEGRADED_SINCE, exc)
        # #8 (#105): con `socket_timeout` acotado (redis_client), una marca que no responde
        # falla RÁPIDO en vez de colgar el request. Esa marca perdida se cuenta REUTILIZANDO
        # el contador de pérdidas ya existente (`basa:audit:lost` + /health) — no un mecanismo
        # nuevo. `record_audit_loss` es best-effort y jamás propaga.
        record_audit_loss(reason=f"nlp_degradation_mark/{reason}")


def clear_nlp_degradation() -> None:
    """Borra la marca de degradación — SOLO cuando se confirmó que el analyzer volvió.

    Deliberadamente no lo llama el camino caliente: cobrar un `DEL` por request sana sería
    pagar en el 99,9% de los pedidos por una limpieza que sirve una vez. El punto de reseteo
    es el probe de `GET /api/v1/health`, que ya pregunta si el analyzer responde.
    """
    try:
        redis_conn = get_redis()
        if redis_conn is None:
            return
        redis_conn.delete(REDIS_KEY_NLP_DEGRADED_SINCE, REDIS_KEY_NLP_DEGRADED_COUNT)
    except Exception as exc:  # noqa: BLE001
        logger.warning("nlp: no se pudo limpiar la marca de degradación: %s", exc)


def read_nlp_degradation() -> tuple:
    """`(degraded_since, degraded_requests)` desde Redis.

    Misma distinción que `_leer_contadores_de_perdida` del health: `None` en el contador es
    "no se pudo leer", NO "cero". `degraded_since` en `None` con contador `0` es el estado
    sano; con contador `None` es "no sabemos". Nunca propaga.
    """
    try:
        redis_conn = get_redis()
        if redis_conn is None:
            return None, None
        desde = redis_conn.get(REDIS_KEY_NLP_DEGRADED_SINCE)
        crudo = redis_conn.get(REDIS_KEY_NLP_DEGRADED_COUNT)
    except Exception as exc:  # noqa: BLE001
        logger.warning("nlp: estado de degradación ilegible (%s)", exc)
        return None, None

    if isinstance(desde, bytes):
        desde = desde.decode()
    if crudo is None:
        return desde, 0
    try:
        return desde, int(crudo.decode() if isinstance(crudo, bytes) else crudo)
    except (TypeError, ValueError):
        logger.warning("nlp: valor ilegible en %s: %r", REDIS_KEY_NLP_DEGRADED_COUNT, crudo)
        return desde, None


def audit_writable(db: Session) -> bool:
    """`SELECT 1` con timeout corto sobre la sesión de auditoría (D4).

    Es el pre-check del modo `closed`: se corre ANTES de llamar al proveedor para no
    gastar dinero en tráfico que no se va a poder registrar (FR-005, literal). Barato a
    propósito — durante una caída se paga por request, así que no puede costar los 3
    intentos del escritor.

    Devuelve False ante cualquier fallo (incluye timeout) y deja la sesión utilizable
    (rollback), para que el caller pueda responder 503 sin arrastrar una transacción
    abortada.

    CONTRATO DEL CALLER: llamarlo ANTES de agregar nada a la sesión. Cierra su transacción
    con `rollback` en ambos caminos —obligado, porque `SET LOCAL statement_timeout` vive
    hasta el fin de la transacción y dejarlo pegado le pondría 1,5 s de techo a todas las
    sentencias siguientes del request—, así que trabajo pendiente sin commitear se
    perdería. En el uso previsto (pre-check del modo `closed`, antes de llamar al
    proveedor) no hay nada pendiente.
    """
    try:
        # `statement_timeout` sólo existe en Postgres; en cualquier otro bind (o en una
        # sesión fake de tests) se salta sin abortar la transacción. Se consulta el
        # dialecto en vez de intentar-y-fallar: un `SET` fallido deja la transacción
        # abortada en Postgres y convertiría un probe sano en un 503 fantasma.
        if _dialect_name(db) == "postgresql":
            db.execute(text(f"SET LOCAL statement_timeout = {AUDIT_PROBE_TIMEOUT_MS}"))
        db.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("audit: la base de auditoría NO es escribible: %s", exc)
        return False
    finally:
        # `SET LOCAL` muere con la transacción: el rollback devuelve la sesión a un estado
        # limpio en ambos caminos (probe OK y probe caído).
        _safe_rollback(db)


def _dialect_name(db: Session) -> str:
    try:
        return db.get_bind().dialect.name
    except Exception:  # noqa: BLE001 — sesión sin bind (tests) → sin timeout de sentencia
        return ""


def _safe_rollback(db: Session) -> None:
    try:
        db.rollback()
    except Exception as exc:  # noqa: BLE001
        logger.warning("audit: rollback falló: %s", exc)


class AuditService:
    @staticmethod
    def log_transaction(
        db: Session,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        pii_detected: bool,
        masked_entities: List[Dict[str, Any]],
        compliance_status: str,
        latency_ms: int,
        tokens_saved_by_optimization: int = 0,
        cost_saved_usd: float = 0.0,
        compression_strategy: str = "none",
        compression_reversed: bool = False,
        user_id: Optional[UUID] = None,
        api_key_id: Optional[UUID] = None,
        guardian_events: Optional[List[Dict[str, Any]]] = None,
        review_token=None,
        ai_disclosure_delivered: bool = False,
        processing_purpose: Optional[str] = None,
        user_group_id=None,
        tenant_id: Optional[UUID] = None,
        applied_layers: Optional[List[Dict[str, Any]]] = None,
        blocked_by_layer: Optional[str] = None,
        # Keyword-only a propósito: la firma ya arrastra 20+ parámetros posicionales y un
        # dict suelto al final es indistinguible de cualquier otro si se pasa por posición.
        *,
        routing_decision: Optional[Dict[str, Any]] = None,
    ) -> Optional[AuditLog]:
        """
        Creates a secure audit log entry for a transaction.
        Ensures absolutely no raw prompt text or PII is recorded.

        Atribución por pedido (spec 027, contrato evento-monitor-atribucion §5-§7):
        ``applied_layers`` es la lista EXHAUSTIVA de capas del perfil con su status y su
        decisión sobre este pedido, y ``blocked_by_layer`` el ``layer_key`` del registry
        que produjo el bloqueo (escalar aparte para que la query de bloqueos sea trivial).
        Ambos son **opcionales**: los callers previos a la 027 (gateway passthrough,
        cualquier script) siguen llamando igual y persisten ``NULL``, que en esas columnas
        significa exactamente "fila anterior a la atribución 027" — no "ninguna capa".

        C1: lo que entra por ``applied_layers`` son SOLO códigos del registry y contadores.
        El productor es ``build_attribution`` (única puerta, valida contra vocabularios
        cerrados); acá no se re-valida para no duplicar la barrera, pero tampoco se
        transforma: se persiste tal cual llega, porque el contrato exige que la columna, el
        evento del motor y el del gateway lleven **el mismo elemento sin transformar**
        (prohibido que un productor "resuma distinto").

        Ruteo automático (spec 030, data-model §2-§3): ``routing_decision`` es la copia
        DURABLE de la decisión del auto-router —``{requested, route, score, model_selected,
        degraded, reason}``— que además viaja por dos superficies efímeras (Debugger y
        vitrina). Opcional: sólo lo manda el camino ``model == "auto"``; en cualquier otra
        consulta persiste ``NULL``, que significa "no pasó por el auto-router" (por eso la
        columna no tiene default). Metadata-only, igual que ``applied_layers``: ruta y
        score son etiqueta de config y número, JAMÁS texto del prompt. Va en su PROPIA
        columna y no dentro de ``guardian_events`` — ese campo está congelado porque la
        hash-chain de licencias lo relee posicionalmente (licensing/audit_events.py:92-93)
        — así que la cadena de hash no ve esta columna y no cambia.

        Fallo de escritura (spec 031 D5 — paga la deuda que la 027 dejó declarada acá):
        antes, CUALQUIER fallo dropeaba la fila y devolvía ``None`` que ningún caller
        miraba: el producto que vende "logueamos TODO" perdía el registro en silencio (ya
        pasó: pérdida total del rastro byok en el ensayo del piloto). Ahora:

        * **reintento acotado** de ``AUDIT_RETRY_BACKOFFS_SECONDS`` (2 reintentos, 0.2 s
          y 0.5 s) — absorbe el fallo transitorio sin pérdida ni ruido;
        * **al agotar**: ``logger.error`` + ``INCR basa:audit:lost`` + ``SET
          basa:audit:last_fail`` (tolerante a Redis caído);
        * en ``BASA_AUDIT_FAIL=open`` (default) devuelve ``None`` como siempre — los
          callers previos a la 031 no cambian de comportamiento, sólo dejan rastro;
        * en ``closed`` propaga ``AuditUnavailableError`` para que el plano responda 503.
        """
        # Masked entities parameter format: [{"type": "PERSON", "count": 2}]
        # We summarize the counts from the list of masked entities. Se calcula UNA vez,
        # fuera del bucle de reintentos: es trabajo puro y no tiene por qué repetirse.
        summary_entities = []
        if masked_entities:
            entity_counts = {}
            for ent in masked_entities:
                ent_type = ent.get("type", "UNKNOWN")
                # F5: respetar el `count` real cuando el caller pasa entidades ya
                # agregadas (p.ej. [{"type":"EMAIL_ADDRESS","count":3}]); default 1
                # cuando la lista es una entrada por entidad sin `count`.
                entity_counts[ent_type] = entity_counts.get(ent_type, 0) + ent.get("count", 1)

            summary_entities = [{"type": k, "count": v} for k, v in entity_counts.items()]

        total_attempts = len(AUDIT_RETRY_BACKOFFS_SECONDS) + 1
        last_error: Optional[Exception] = None

        for attempt in range(total_attempts):
            try:
                # Instancia NUEVA por intento: tras un `rollback` la instancia anterior
                # queda expulsada de la sesión y re-añadirla es terreno resbaladizo
                # (estado transitorio/detached según cómo haya fallado el commit).
                log_entry = AuditLog(
                    user_id=user_id,
                    api_key_id=api_key_id,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost_usd,
                    pii_detected=pii_detected,
                    masked_entities=summary_entities if pii_detected else None,
                    compliance_status=compliance_status,
                    latency_ms=latency_ms,
                    tokens_saved_by_optimization=tokens_saved_by_optimization,
                    cost_saved_usd=cost_saved_usd,
                    compression_strategy=compression_strategy,
                    compression_reversed=compression_reversed,
                    guardian_events=guardian_events or [],
                    # `guardian_events` queda CONGELADO como legado (D6: la hash-chain de
                    # licencias lo relee posicionalmente). La atribución nueva NO lo pisa ni lo
                    # migra: vive en su propia columna, al lado.
                    applied_layers=applied_layers,
                    blocked_by_layer=blocked_by_layer,
                    routing_decision=routing_decision,
                    review_token=review_token,
                    ai_disclosure_delivered=ai_disclosure_delivered,
                    processing_purpose=processing_purpose,
                    user_group_id=user_group_id,
                    timestamp=datetime.utcnow()
                )
                # tenant_id explícito sólo si el caller lo resolvió (spec 014 US4); si es
                # None se respeta el default del modelo (DEFAULT_TENANT_ID) — nunca None.
                if tenant_id is not None:
                    log_entry.tenant_id = tenant_id

                db.add(log_entry)
                db.commit()

            except Exception as exc:  # noqa: BLE001
                last_error = exc
                _safe_rollback(db)
                if attempt < total_attempts - 1:
                    backoff = AUDIT_RETRY_BACKOFFS_SECONDS[attempt]
                    logger.warning(
                        "audit: escritura falló (intento %d/%d): %s — reintento en %.1fs",
                        attempt + 1, total_attempts, exc, backoff,
                    )
                    _wait(backoff)
                continue

            # Commit OK: la fila YA es durable. El `refresh` va en su propio try y NO puede
            # disparar un reintento — si la conexión muere justo después del commit,
            # reintentar insertaría una SEGUNDA fila del mismo evento (auditoría duplicada,
            # que para un producto de compliance es tan malo como la que falta).
            try:
                db.refresh(log_entry)
            except Exception as exc:  # noqa: BLE001
                logger.warning("audit: refresh post-commit falló (la fila ya está escrita): %s", exc)

            if attempt:
                # El transitorio absorbido SÍ se dice (en info): sin esto una base que
                # falla la mitad de las veces se ve idéntica a una sana.
                logger.info(
                    "audit: fila escrita tras %d reintento(s) — fallo transitorio absorbido",
                    attempt,
                )
            logger.info(f"Audit log saved: ID {log_entry.id} | Cost ${cost_usd:.6f} | PII: {pii_detected} | Compliance: {compliance_status}")
            return log_entry

        # Presupuesto agotado: la fila NO existe. A partir de acá el evento está perdido y
        # lo único innegociable es que se sepa.
        mode = audit_fail_mode()
        logger.error(
            "audit: EVENTO NO REGISTRADO tras %d intentos (modo=%s, compliance=%s, model=%s): %s",
            total_attempts, mode, compliance_status, model, last_error, exc_info=last_error,
        )
        # Se cuenta en los DOS modos: en `closed` la petición se rechaza, pero el intento
        # de escritura que no llegó a la base sigue siendo un agujero del registro y el
        # health tiene que poder mostrarlo.
        record_audit_loss(reason=f"log_transaction/{compliance_status}")

        if mode == AUDIT_FAIL_CLOSED:
            raise AuditUnavailableError(
                "auditoría no disponible — la instalación exige registro (audit_fail=closed)"
            ) from last_error
        return None
