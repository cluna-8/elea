"""BasaAuditLogger — auditoría metadata-only desde el motor (spec 014 US3).

``CustomLogger.async_log_success_event`` (firma confirmada, research T005) persiste
un ``AuditLog`` (tabla de la 013, misma DB) por request del motor: verdicto, tipos de
entidad enmascarada, tokens, costo, latencia, identidad tenant/client/tool.

**Scrub explícito (Constraint C1 / FR-015)**: JAMÁS se persiste texto de prompt ni el
mapa ``pii_tokens`` — se eliminan del payload antes de armar el INSERT, y el INSERT
solo lleva columnas de metadata. Test negativo en la suite.

Feed del monitor (FR-016/FR-017): eventos efímeros (metadata + previews acotados ya
ENMASCARADOS) publicados a una lista Redis con TTL corto — el backend los sirve en
``/gw/monitor``. Nada del feed contiene PII cruda.

**Fallo de escritura (spec 031 US2, T009 — FR-004)**: hasta esta spec, cada camino de
error de este módulo terminaba en un ``print`` que nadie leía: el motor decía "no fatal"
y seguía, y el rastro durable del tráfico byok —la superficie PRINCIPAL del producto—
desaparecía sin que nadie se enterara (pasó de verdad; ver ``_log``). Ahora: ``logging``
con nivel real, reintento ACOTADO del POST al plano interno, y al agotarlo la pérdida se
CUENTA en Redis (``basa:audit:lost`` / ``basa:audit:last_fail``) para que el health y el
banner de Logs de Auditoría la muestren. La política ``BASA_AUDIT_FAIL`` se lee para el
log, pero acá no puede haber ``closed``: este hook corre DESPUÉS de que la respuesta ya
se sirvió y una respuesta servida no se puede des-servir (el corte fail-closed vive en el
guardrail, que sí es pre-call).
"""
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone

from litellm.integrations.custom_logger import CustomLogger

sys.path.insert(0, os.path.dirname(__file__))
import basa_guardian_policy as policy  # noqa: E402

# Mismo patrón que las otras extensiones del motor (`basa-guardrail`, `basa-custom-auth`):
# un logger nombrado, que LITELLM_LOG y el recolector de logs del cliente ya capturan.
logger = logging.getLogger("basa-audit")

# Atribución por pedido (spec 027 T029): las DOS columnas nuevas entran acá con el MISMO
# esquema que el productor del gateway. El comentario "MISMO esquema que basa_audit_logger"
# de gateway.py dejó de ser convención y es contrato (evento-monitor-atribucion §8):
# extender un productor sin el otro rompe el render uniforme de la vitrina. Hoy este plano
# las escribe SIEMPRE en NULL — ver `_attribution_del_motor`.
_INSERT_AUDIT_SQL = """
INSERT INTO audit_logs (
    id, tenant_id, timestamp, user_id, api_key_id, model,
    prompt_tokens, completion_tokens, cost_usd, pii_detected, masked_entities,
    compliance_status, latency_ms, user_group_id, applied_layers, blocked_by_layer
) VALUES (
    gen_random_uuid(), $1::uuid, NOW(), $2::uuid, $3::uuid, $4,
    $5, $6, $7, $8, $9::jsonb, $10, $11, $12::uuid, $13::jsonb, $14
)
"""

_MONITOR_KEY = "basa:gw:events"
_MONITOR_CAP = 100
_MONITOR_TTL_S = 300  # efímero: la vitrina no persiste nada (C1)
_DISPLAY_CAP = 2000

# ── Política de fallo de auditoría (spec 031, contrato §Config y §Contador) ───────────
# ESPEJO de backend/src/services/audit_service.py: mismas claves, mismo presupuesto de
# reintentos, misma env. No se importa el módulo del backend porque el motor sólo monta
# este directorio (la imagen upstream no trae el paquete del producto ni instalador para
# agregarlo) — así que se cambian JUNTOS. Si divergen, el health del backend mostraría un
# contador y el motor estaría escribiendo en otro.
_REDIS_KEY_AUDIT_LOST = "basa:audit:lost"
_REDIS_KEY_AUDIT_LAST_FAIL = "basa:audit:last_fail"
_AUDIT_FAIL_ENV = "BASA_AUDIT_FAIL"

# Presupuesto FIJO: 2 reintentos (3 intentos) con backoff corto. Es el edge case
# anti-avalancha de la spec — ante una caída del backend el contador es la válvula, no
# una cola ni un backoff creciente que multiplique la carga sobre un servicio ya herido.
_AUDIT_RETRY_BACKOFFS_SECONDS = (0.2, 0.5)
_AUDIT_POST_TIMEOUT_S = 5.0


def audit_fail_mode() -> str:
    """`open` | `closed` (contrato §Config). Default `open` ante env ausente, vacía o
    ilegible: un typo en la configuración jamás puede convertirse en un corte de servicio.
    Acá sólo se usa para el log —este hook es post-respuesta— pero se lee con el MISMO
    criterio que el helper del backend para que los dos planos cuenten la misma historia."""
    return "closed" if os.environ.get(_AUDIT_FAIL_ENV, "").strip().lower() == "closed" else "open"


async def _esperar(segundos: float) -> None:
    """Indirección del backoff: punto de monkeypatch de los tests, que verifican el
    presupuesto de reintentos sin pagarlo."""
    await asyncio.sleep(segundos)


async def _registrar_perdida(motivo: str) -> None:
    """Deja constancia de UN evento de auditoría perdido (contrato §Contador de pérdidas):
    ``INCR basa:audit:lost`` + ``SET basa:audit:last_fail <iso>``.

    Sin TTL a propósito: es constancia de un agujero en el registro, no una métrica que se
    auto-borra. Tolerante a Redis caído — si el contador tampoco se puede escribir queda el
    ``logger.error``, que es el piso innegociable de esta spec: la pérdida NUNCA es
    silenciosa. Jamás propaga: es el camino de degradación, no puede él mismo romper nada.
    """
    ahora = datetime.now(timezone.utc).isoformat()
    try:
        import redis.asyncio as redis_lib
    except ImportError:
        logger.error("evento de auditoría PERDIDO y sin contador (no hay cliente Redis en "
                     "la imagen) | motivo=%s ts=%s", motivo, ahora)
        return
    client = None
    try:
        client = redis_lib.Redis(host=os.getenv("REDIS_HOST", "redis"),
                                 port=int(os.getenv("REDIS_PORT", "6379")))
        pipe = client.pipeline()
        pipe.incr(_REDIS_KEY_AUDIT_LOST)
        pipe.set(_REDIS_KEY_AUDIT_LAST_FAIL, ahora)
        await pipe.execute()
        logger.error("evento de auditoría PERDIDO — contado en %s | motivo=%s ts=%s",
                     _REDIS_KEY_AUDIT_LOST, motivo, ahora)
    except Exception as exc:  # noqa: BLE001 — el contador es best-effort, el log NO
        logger.error("evento de auditoría PERDIDO y el contador falló (%s): %s | "
                     "motivo=%s ts=%s", _REDIS_KEY_AUDIT_LOST, exc, motivo, ahora)
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001 — cerrar un cliente roto no aporta nada
                pass


def _no_llego_al_servidor(exc: Exception, httpx_mod) -> bool:
    """¿El pedido se puede reintentar SIN riesgo de duplicar la fila?

    Sólo si es seguro que nunca llegó al backend: fallo de conexión, timeout de conexión o
    de pool. Un ``ReadTimeout`` (o cualquier error después de haber mandado el cuerpo) es
    AMBIGUO y NO se reintenta: ``POST /internal/audit` no es idempotente —además de
    insertar la fila mueve el presupuesto del cliente (issue #76)— así que reintentar un
    envío que quizá sí se ejecutó duplicaría el registro Y cobraría dos veces. Para un
    producto de auditoría una fila duplicada es tan mentira como una fila faltante.
    """
    seguras = tuple(
        getattr(httpx_mod, nombre) for nombre in
        ("ConnectError", "ConnectTimeout", "PoolTimeout")
        if hasattr(httpx_mod, nombre)
    )
    return bool(seguras) and isinstance(exc, seguras)


async def _postear_al_plano_interno(audit_url: str, entry: dict) -> bool:
    """POST de la fila al plano interno del backend con reintento ACOTADO (contrato
    §internal: "1 reintento"; acá 2, el mismo presupuesto que el escritor del backend).

    Devuelve True si la fila quedó registrada. En cualquier salida negativa la pérdida YA
    quedó contada y logueada — el caller no tiene que acordarse de hacerlo.
    """
    try:
        import httpx
    except ImportError as exc:  # la imagen del motor SÍ trae httpx; si no, hay que saberlo
        logger.error("no se pudo auditar: httpx no disponible en la imagen (%s)", exc)
        await _registrar_perdida("audit-logger/sin-httpx")
        return False

    headers = {"X-Basa-Internal": os.environ.get("LITELLM_MASTER_KEY", "")}
    intentos = len(_AUDIT_RETRY_BACKOFFS_SECONDS) + 1
    motivo = "desconocido"

    for intento in range(intentos):
        try:
            async with httpx.AsyncClient(timeout=_AUDIT_POST_TIMEOUT_S) as client:
                respuesta = await client.post(audit_url, json=entry, headers=headers)
        except Exception as exc:  # noqa: BLE001
            if not _no_llego_al_servidor(exc, httpx):
                # Resultado DESCONOCIDO: puede haberse escrito o no. No se reintenta (ver
                # `_no_llego_al_servidor`) y se cuenta igual, porque el officer necesita
                # saber que hay un evento cuyo registro no está confirmado.
                logger.error("auditoría con resultado DESCONOCIDO (%r): no se reintenta "
                             "para no duplicar la fila ni el cargo — se cuenta como pérdida",
                             exc)
                await _registrar_perdida(f"audit-logger/ambiguo:{type(exc).__name__}")
                return False
            motivo = f"transporte:{type(exc).__name__}"
        else:
            if respuesta.status_code == 200:
                if intento:
                    logger.info("auditoría escrita tras %d reintento(s) — fallo transitorio "
                                "absorbido", intento)
                return True
            if respuesta.status_code < 500:
                # 4xx = el payload no va a mejorar reintentándolo (secreto mal, esquema
                # rechazado): pérdida inmediata y ruidosa, sin gastar el presupuesto.
                logger.error("el plano interno RECHAZÓ la fila con %s — no se reintenta",
                             respuesta.status_code)
                await _registrar_perdida(f"audit-logger/http-{respuesta.status_code}")
                return False
            # 5xx: el INSERT no se ejecutó (el endpoint commitea antes de responder), así
            # que reintentar es seguro y suele absorber un backend que está arrancando.
            motivo = f"http-{respuesta.status_code}"

        if intento < intentos - 1:
            backoff = _AUDIT_RETRY_BACKOFFS_SECONDS[intento]
            logger.warning("auditoría falló (intento %d/%d, %s) — reintento en %.1fs",
                           intento + 1, intentos, motivo, backoff)
            await _esperar(backoff)

    logger.error("EVENTO NO REGISTRADO tras %d intentos (modo=%s): %s",
                 intentos, audit_fail_mode(), motivo)
    await _registrar_perdida(f"audit-logger/{motivo}")
    return False


def _scrub(metadata: dict) -> dict:
    """Devuelve metadata sin material sensible: pii_tokens (mapa reversible) y
    cualquier texto crudo NUNCA se auditan."""
    clean = dict(metadata or {})
    clean.pop("pii_tokens", None)
    return clean


def _attribution_del_motor():
    """Atribución del pedido en el plano motor: hoy **no la hay** ⇒ ``(None, None)``.

    ``None`` **no** es lista vacía: significa *"este pedido no trae atribución"*, mientras
    que ``[]`` afirmaría "ninguna capa corrió", que sería mentira (el piso corre siempre).
    Por eso las dos columnas quedan SQL NULL y el evento del monitor lleva ``null``: la
    vitrina muestra "sin registro de capas", que es la verdad.

    **Por qué no se lee del metadata-home** (hallazgo A3 de la verificación adversarial de
    la US2, ALTA — atribución falsificable): hasta este fix, la atribución se leía de
    ``metadata['basa_governance']``. Ese home es la fusión de ``litellm_metadata`` y
    ``metadata`` (ver ``_log``), y ``metadata`` es un campo del **body**, o sea un canal que
    escribe el CLIENTE —y que además ganaba el merge—. El saneo que había validaba
    *vocabulario*, no *procedencia*: un cliente con virtual key mandando
    ``{"metadata": {"basa_governance": {"applied_layers": [{"layer_code": "pii_masking",
    "status": "applied", "decision": "mask", "count": 4}]}}}`` conseguía que su pedido
    quedara auditado como si el enmascarado hubiera corrido. Falsificar el registro de
    cumplimiento es exactamente la mentira que la 027 existe para borrar, así que el plano
    motor prefiere **no registrar** antes que registrar algo que no produjo —el mismo
    criterio con el que la spec corta la fila durable del bloqueo hacia la 018
    (data-model §3.4)—.

    **Estado del cableado (2026-07-22)**: el productor propio es **T025**
    (``basa_guardrail.py``), bloqueada por el PR #21, que reescribe el guardrail entero.
    Requisitos para cuando aterrice, para no reabrir A3:

    - La atribución tiene que llegar por un canal que el cliente **no pueda escribir**.
      Verificado en la imagen del motor (``litellm/proxy/litellm_pre_call_utils.py:1580``):
      el proxy **sobrescribe** ``metadata['user_api_key_metadata']`` con la metadata del
      objeto de auth, así que ESE subárbol no es escribible desde el body — pero tampoco
      sirve acá: es la identidad, y ``custom_auth`` la cachea 60 s por ``key_hash``, con lo
      que la atribución de un pedido se filtraría a los siguientes de la misma Connection.
    - Si igual tiene que viajar por metadata, el productor debe **sobreescribir la clave en
      cada pedido**, también cuando no haya nada que reportar. Ojo con los caminos donde el
      guardrail no corre (la API de Responses, issue #28): ahí un valor sembrado por el
      cliente sobreviviría igual. Un canal en proceso, correlacionado por pedido, no tiene
      ese problema.
    - El lector debe volver a sanear por vocabulario cerrado (4 claves de data-model §3.1,
      ``status``/``decision`` de los enums del registry, ``count`` entero y no ``bool``):
      la procedencia confiable evita la falsificación, el saneo evita la fuga de texto al
      JSONB (C1). Son dos defensas distintas y hacen falta las dos.
    """
    return None, None


class BasaAuditLogger(CustomLogger):
    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        try:
            await self._log(kwargs, response_obj, start_time, end_time)
        except Exception as exc:  # la auditoría no debe voltear la respuesta al cliente
            # Sigue sin ser fatal para el cliente, pero ya no es invisible: un fallo acá
            # (armado del payload, identidad ilegible…) significa que el pedido NO quedó
            # registrado, así que se cuenta como pérdida igual que un POST agotado.
            logger.exception("fallo al auditar el pedido (no fatal para el cliente, pero "
                             "el evento NO quedó registrado): %s", exc)
            await _registrar_perdida(f"audit-logger/excepcion:{type(exc).__name__}")

    async def _log(self, kwargs, response_obj, start_time, end_time):
        data = kwargs.get("litellm_params", {}) or {}
        # La identidad Basa viaja en el UserAPIKeyAuth.metadata (custom_auth) que el
        # proxy propaga como user_api_key_metadata dentro del metadata-home del request
        # — `litellm_metadata` en la ruta anthropic, `metadata` en el resto (024 D3;
        # antes se leía un solo home y los eventos byok bridged salían anónimos).
        basa = policy.proxy_identity_from(data) or policy.proxy_identity_from(kwargs)

        # Sin identidad de Connection = llamada INTERNA con la master key (el chat de la
        # consola, la generación de frases del router, embeddings…): ese tráfico ya lo
        # registra el plano que lo originó (chat.py escribe su propia fila) y registrarlo
        # acá también DUPLICABA cada petición del Playground en Logs de Auditoría, con el
        # costo contado dos veces en los agregados (hallazgo de JF, 29-jul: 2 llamadas →
        # 3 filas; qwen3:4b anónima + camara-comercio-local con usuario eran EL MISMO
        # pedido). Cada plano registra solo su propio tráfico: este logger existe para el
        # byok de herramientas, que siempre llega con identidad resuelta por custom_auth.
        if not (basa and (basa.get("key_id") or basa.get("client_id"))):
            logger.debug("pedido interno sin identidad de Connection: lo registra su "
                         "plano de origen, no este logger (modelo=%s)",
                         kwargs.get("model") or data.get("model"))
            return

        request_md = {}
        for key in ("litellm_metadata", "metadata"):
            home = kwargs.get(key) or data.get(key)
            if isinstance(home, dict):
                request_md.update(home)
        request_md = _scrub(request_md)

        usage = getattr(response_obj, "usage", None)
        prompt_tokens = completion_tokens = 0
        if usage is not None:
            get = usage.get if isinstance(usage, dict) else (lambda k, d=None: getattr(usage, k, d))
            prompt_tokens = get("prompt_tokens") or get("input_tokens") or 0
            completion_tokens = get("completion_tokens") or get("output_tokens") or 0

        cost = kwargs.get("response_cost") or 0
        try:
            latency_ms = int((end_time - start_time).total_seconds() * 1000)
        except Exception:
            latency_ms = 0

        masked = request_md.get("basa_masked_entities") or []
        compliance = (request_md.get("basa_compliance") or {}).get("status") or "passed"
        applied_layers, blocked_by_layer = _attribution_del_motor()

        # Registro DURABLE (nunca voltea la respuesta; el publish a Redis va después pase
        # lo que pase). El audit_logs canónico vive en la base del BACKEND: desde la
        # separación de bases (motor → basa_engine) el INSERT por prisma fallaba en cada
        # pedido byok con "relation audit_logs does not exist", tragado como no-fatal — o
        # sea, el tráfico de HERRAMIENTAS no dejaba rastro durable. Fix 2026-07-27: el
        # motor emite la fila al plano interno del backend (dueño del esquema), mismo
        # patrón y mismo secreto que la resolución de identidad. Sin la env (desarrollo,
        # base compartida) se conserva el INSERT directo por prisma.
        #
        # Y la lección del incidente, que es lo que paga la 031 (T009): aquel fallo estuvo
        # meses invisible porque el único rastro era un `print` "no fatal" en el stdout del
        # motor. Ya no: la escritura reintenta acotadamente y, si se pierde, se CUENTA
        # (`basa:audit:lost` + `basa:audit:last_fail`) y se loguea con nivel error. La
        # misma pérdida hoy se vería en minutos en el health y en el banner de Logs.
        entry = {
            "tenant_id": basa.get("tenant_id") or "00000000-0000-0000-0000-000000000001",
            "user_id": basa.get("client_id"),
            "api_key_id": basa.get("key_id"),
            "model": kwargs.get("model") or data.get("model") or "desconocido",
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "cost_usd": float(cost),
            "pii_detected": bool(masked),
            "masked_entities": masked,
            "compliance_status": compliance,
            "latency_ms": latency_ms,
            "user_group_id": basa.get("group_id"),
            # None (no "null"): SQL NULL = "pedido sin atribución", que es exactamente lo
            # que hoy produce el motor mientras T025 no cablee un productor propio.
            "applied_layers": applied_layers,
            "blocked_by_layer": blocked_by_layer,
        }
        audit_url = os.environ.get("BASA_AUDIT_URL", "").strip()
        if audit_url:
            # El reintento y el contador viven adentro: acá no hay nada que tragar.
            await _postear_al_plano_interno(audit_url, entry)
        else:
            await self._insertar_por_prisma(entry, masked, applied_layers, blocked_by_layer)

        await self._publish_monitor_event(basa, masked, compliance, kwargs,
                                          applied_layers, blocked_by_layer)

    async def _insertar_por_prisma(self, entry, masked, applied_layers, blocked_by_layer):
        """Camino de DESARROLLO (base compartida, sin `BASA_AUDIT_URL`): INSERT directo.

        Sin reintento a propósito: el prisma del motor apunta a su propia base y un fallo
        acá no es un transitorio de red sino un problema de esquema o de conexión que un
        reintento no arregla (y que en prod ni siquiera se ejerce). Lo que sí cambia
        respecto del `print` anterior es que la pérdida se cuenta y se loguea igual que en
        el camino de producción — el contador del health tiene que ser el mismo número.
        """
        # El import vive acá y no arriba del método `_log`: cuando la fila viaja por el
        # plano interno (producción) el prisma del motor es IRRELEVANTE, y el `return`
        # temprano que había —`if prisma_client is None: return`— tiraba en silencio TODA
        # la auditoría de un motor sin DATABASE_URL aunque `BASA_AUDIT_URL` estuviera bien
        # cableada. Otro fallo mudo menos.
        from litellm.proxy.proxy_server import prisma_client
        if prisma_client is None:
            logger.error("no se pudo auditar: el motor no tiene ni BASA_AUDIT_URL ni "
                         "cliente de base — el pedido NO deja rastro durable")
            await _registrar_perdida("audit-logger/sin-destino")
            return
        try:
            await prisma_client.db.query_raw(
                _INSERT_AUDIT_SQL,
                entry["tenant_id"], entry["user_id"], entry["api_key_id"],
                entry["model"], entry["prompt_tokens"], entry["completion_tokens"],
                entry["cost_usd"], entry["pii_detected"], json.dumps(masked),
                entry["compliance_status"], entry["latency_ms"], entry["user_group_id"],
                json.dumps(applied_layers) if applied_layers is not None else None,
                blocked_by_layer,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("INSERT de auditoría falló — EVENTO NO REGISTRADO (modo=%s): %s",
                         audit_fail_mode(), exc)
            await _registrar_perdida(f"audit-logger/insert:{type(exc).__name__}")

    async def _publish_monitor_event(self, basa, masked, compliance, kwargs,
                                     applied_layers=None, blocked_by_layer=None):
        """Feed efímero del monitor (vitrina, Principio VIII): metadata + preview
        ENMASCARADO (el texto que vio el upstream — nunca los valores originales)."""
        try:
            import redis.asyncio as redis_lib
        except ImportError:
            return
        try:
            client = redis_lib.Redis(host=os.getenv("REDIS_HOST", "redis"),
                                     port=int(os.getenv("REDIS_PORT", "6379")))
            messages = (kwargs.get("messages") or
                        (kwargs.get("litellm_params", {}) or {}).get("messages") or [])
            preview = ""
            for msg in reversed(messages):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    content = msg.get("content")
                    if isinstance(content, str):
                        preview = content[:_DISPLAY_CAP]
                    elif isinstance(content, list):
                        preview = " ".join(
                            b.get("text", "") for b in content
                            if isinstance(b, dict) and isinstance(b.get("text"), str)
                        )[:_DISPLAY_CAP]
                    break
            event = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "tool": basa.get("tool_type") or basa.get("ua_tool"),
                "client": basa.get("client_username"),
                "tenant": basa.get("tenant_slug"),
                "model": kwargs.get("model"),
                "compliance_status": compliance,
                "masked_entities": masked,
                "masked_preview": preview,  # ya enmascarado: es lo que vio el upstream
                # Contrato evento-monitor-atribucion §8: los campos nuevos viajan con el
                # MISMO shape que en la columna y que en el evento del gateway, serializados
                # sin transformar. `null` cuando el pedido no trae atribución — la vitrina
                # muestra "sin atribución", que es la verdad, en vez de una lista vacía que
                # afirmaría "ninguna capa corrió".
                "applied_layers": applied_layers,
                "blocked_by_layer": blocked_by_layer,
            }
            pipe = client.pipeline()
            pipe.lpush(_MONITOR_KEY, json.dumps(event, ensure_ascii=False))
            pipe.ltrim(_MONITOR_KEY, 0, _MONITOR_CAP - 1)
            pipe.expire(_MONITOR_KEY, _MONITOR_TTL_S)
            await pipe.execute()
            await client.aclose()
        except Exception as exc:  # noqa: BLE001
            # El monitor es vitrina: jamás afecta la request NI cuenta como pérdida de
            # auditoría (lo durable ya se resolvió arriba). Pero se dice en debug: un feed
            # vacío con tráfico real es, si no, imposible de diagnosticar.
            logger.debug("no se pudo publicar el evento del monitor (vitrina): %s", exc)
basa_audit_logger_instance = BasaAuditLogger()
