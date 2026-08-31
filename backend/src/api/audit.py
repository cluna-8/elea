import csv
import enum
import io
import logging
from datetime import datetime
from typing import List, Optional, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.audit import AuditLog
from ..auth.rbac import require_role
# Quién decide qué fila es un bloqueo, un eslabón de licencia o un rechazo nuestro: ya no esta
# pantalla (spec 018, FR-002). El porqué, en el bloque del filtro de estado, acá abajo.
from ..services.retention.classifier import dice_licencia, es_bloqueo, es_rechazo

router = APIRouter(
    prefix="/audit-logs",
    tags=["Audit Logs"],
    # vitrinas_lectura (matriz 017): `lectura` LEE la bitácora de auditoría (list + export).
    # Endpoints homogéneos de sólo-lectura del rastro de auditoría; sin config ni mutación.
    dependencies=[Depends(require_role("admin", "compliance_officer", "lectura"))],
)
logger = logging.getLogger("sentinel-secure-gateway.audit")


# ── Filtro de estado (spec 031, FR-006 + contrato §UI) ───────────────────────────────
#
# Hasta la 031 el officer tenía que INFERIR el bloqueo: filtrar por un
# `compliance_status` exacto exigía conocer de memoria los valores (`blocked_prohibited`,
# `blocked_secret`, `blocked_guardian`…) o adivinar por «0/0 tokens». Ahora hay un filtro
# explícito sobre la convención D1: prefijo `blocked_`, con el filtro canónico del producto.
#
# Es un Enum y no un string libre A PROPÓSITO: un valor mal escrito devuelve 422 en vez de
# ignorarse en silencio. En una pantalla de cumplimiento, un filtro que se ignora es peor
# que un error — el officer cree estar viendo SÓLO los bloqueos y está viendo todo.
#
# ── De dónde sale el criterio (spec 018, FR-002) ──
#
# QUÉ fila es un bloqueo, cuál un eslabón de licencia y cuál un rechazo nuestro ya NO se
# define acá. Hasta la 018 esta pantalla tenía sus propias constantes —`BLOQUEADO_LIKE`,
# `MODELO_LICENCIA`, `RECHAZADO_LIKE`—, o sea una SEGUNDA definición de «qué es un bloqueo»
# conviviendo con la del purgador de retención, que decide con ese mismo criterio qué se
# BORRA. Dos copias del criterio es que un día la pantalla informe «3 bloqueos» y la purga
# cuente esas mismas filas en otra clase, y que el officer no tenga forma de saber cuál de
# las dos le mintió. Hoy la definición es una sola y vive en
# `services/retention/classifier.py`; acá se consumen sus primitivas (`es_bloqueo`,
# `dice_licencia`, `es_rechazo`), importadas arriba.
#
# Ojo con qué se unificó y qué NO. Lo unificado es la DEFINICIÓN (una sola fuente para «qué
# dice esta fila»), no el CRITERIO de exclusión de la cadena: la purga excluye por la FORMA de
# `guardian_events` y esta pantalla por el LITERAL de `model`, a propósito y por dictamen del
# manager del 14-ago. El argumento está entero en `_build_query`, acá abajo, y en el docstring
# de `dice_licencia()`.
#
# El RAZONAMIENTO de cada literal se mudó CON la constante, entero y no resumido: por qué la
# hash-chain de licencias (021) se excluye aunque varias de sus transiciones escriban
# `compliance_status='blocked_by_policy'` y caigan de lleno en el prefijo de bloqueo (FR-010,
# mismo criterio que el agregado de cobertura de analytics tras el hallazgo de la 028); y por
# qué los rechazos NUESTROS —capacidad (`rejected_saturated`, gate #135 H4) y presupuesto
# agotado (`rejected_budget`, #157)— no son bloqueos (no los impidió ninguna capa) pero
# tampoco permitidos (nunca se sirvieron), y por eso quedan fuera de los DOS baldes hasta que
# tengan el suyo en el ciclo 2. Está completo en los docstrings de `dice_licencia()`,
# `es_bloqueo()` y `es_rechazo()` y en los comentarios de `MODELO_LICENCIA`,
# `PREFIJO_BLOQUEADO` y `PREFIJO_RECHAZADO` del clasificador. Leerlo ahí antes de tocar este
# filtro: acá se ve el EFECTO, allá se decide.
#
# Lo que sí sigue siendo decisión de esta pantalla es que ninguna de las dos exclusiones
# ESCONDE nada: sin filtro `estado`, licencias y rechazos siguen visibles en el listado. Son
# auditoría durable y el officer los tiene que poder ver para explicar por qué ese pedido no
# salió.


class EstadoFiltro(str, enum.Enum):
    BLOQUEADOS = "bloqueados"
    PERMITIDOS = "permitidos"


# ── La vista LÓGICA de `guardian_events` (spec 018) ──────────────────────────────────
#
# Lo que se GUARDA en `audit_logs.guardian_events` y lo que esta API EXPONE dejaron de ser la
# misma cosa, y esta frontera es donde vuelven a serlo.
#
# ── Qué pasó del lado del almacenamiento ──
#
# El blob de eventos de guardián de una fila de tráfico lo devuelve el motor, o sea que en
# última instancia lo elige alguien de AFUERA. Persistirlo pelado deja al inspeccionado
# eligiendo qué hay en la posición 0 de esa columna, y esa posición decide cosas graves: el
# portón de la purga (`classifier.es_trafico_demostrable()`) sólo habilita el borrado si el
# primer evento NO trae ninguna de las tres marcas de la cadena —`seq`, `prev_hash` y
# `event_type`—, y el lector de la cadena relee ese mismo `[0]`
# (`audit_events.chained_entries`, `:130`, que consumen `verify_chain` —`:159`— y
# `trueup_export.build_payload` —`:47`, vía el import de `:31`—; la copia que ese módulo
# tenía se borró y hoy IMPORTA la única).
# Un upstream que conteste `guardrail_events: [{"seq": 1}]` sobre una fila de tráfico común se
# compraba de un saque los tres premios del hallazgo de `model='license'`: fila inmortal,
# invisible en los baldes de la vitrina y veneno para `verify_chain`. Por eso el plano de
# escritura (`api/chat.py`) mete los eventos del motor dentro de un sobre nuestro —
# `[{"upstream": [ev1, ev2, …]}]`—: la posición 0 pasa a ser de la casa y el de afuera ya no
# la puede escribir.
#
# (De los tres premios, el de la vitrina ya NO se lo compra por esta vía desde el dictamen del
# 14-ago: esta pantalla excluye por el LITERAL de `model`, no por la forma. Se lo compra por la
# Capa B, que es la que le impide escribir ese literal. Ver `_build_query`.)
#
# ── Por qué la desenvoltura va acá y no en el frontend ──
#
# Ese sobre es una defensa de ALMACENAMIENTO y no tiene por qué llegarle al officer. Lo que
# las pantallas enseñan es la LISTA DE EVENTOS: cuántos guardianes se activaron en ese pedido
# y cuáles. Si el sobre se filtrara a la respuesta, `AuditPage.tsx:409`
# (`log.guardian_events?.length ?? 0`) contaría UN evento por pedido pasara lo que pasara, y
# el detalle (`:500-502`) dibujaría un `{upstream: […]}` en vez de los eventos. Ninguna de las
# dos pantallas toca la base —`AuditPage.tsx:218` llama `api.getAuditLogs()` y
# `CompliancePage.tsx:112-118` llama `api.getPendingReviews()`—, así que la frontera donde se
# desenvuelve es ésta y el frontend no se toca. Que además es donde no tenemos tests: una
# desenvoltura allá sería una promesa sin nadie que la sostenga.
#
# ── Por qué UN helper y no tres desenvolturas ──
#
# Los tres consumidores (el listado, el conteo del CSV y el contexto de revisión pendiente de
# `api/compliance.py`) llaman a la MISMA función. Tres copias del mismo desarmado son tres
# oportunidades de que una quede vieja el día que el sobre cambie, y la que quedara vieja no
# rompería nada visible: devolvería un número plausible y distinto del de las otras dos, que
# es exactamente cómo se ve un informe de compliance que no cuadra y nadie sabe por qué.
#
# Vive en la vitrina y no en el clasificador porque es una decisión de PRESENTACIÓN (qué ve el
# officer), no del criterio de retención: el purgador y los lectores de la cadena siguen
# leyendo la columna CRUDA, con el sobre puesto, que es de donde les viene la defensa.
# `api/compliance.py` importa esta función en vez de repetirla.

# Clave del sobre. Literal acá y no import de `api/chat.py` A PROPÓSITO: esto no es una
# constante compartida entre dos módulos que cambian juntos, es el formato de datos YA
# PERSISTIDOS. Las filas escritas ayer tienen esta clave adentro para siempre; el día que el
# plano de escritura elija otra, este lector tiene que seguir sabiendo desarmar las viejas —
# un import lo haría cambiar de opinión sobre el pasado.
CLAVE_SOBRE_UPSTREAM = "upstream"


def desenvolver_eventos_guardian(eventos):
    """Vista lógica de `guardian_events`: la lista PLANA de eventos, con sobre o sin él.

    Contrato: una fila con el blob ANIDADO sale con la misma forma y el mismo conteo que una
    fila equivalente sin anidar. Es lo que hace que el sobre sea invisible para quien consume
    la API y que agregarlo no haya sido un cambio de contrato encubierto.

    Se desarma ELEMENTO POR ELEMENTO y no sólo la lista de un solo sobre: el plano de
    escritura concatena los disparos NUESTROS con los del motor, así que la fila puede quedar
    tanto `[{"upstream": […]}]` como `[disparo_nuestro, {"upstream": […]}]`. Las dos formas
    tienen que dar la misma lista plana que daban antes del sobre; una desenvoltura que sólo
    contemplara la primera dejaría el sobre a la vista justo en las filas donde también actuó
    un guardián nuestro, que son las interesantes.

    Un elemento es sobre sólo si es un objeto con ESA clave y NADA MÁS, y con una lista
    adentro. Las tres condiciones son para no confundirlo con un evento real que casualmente
    hable de un upstream. Lo que no cumple las tres pasa INTACTO: si mañana el sobre cambia de
    forma, el officer ve un objeto raro —feo, evidente y reportable— en vez de perder eventos
    en silencio.

    No se recursa: el sobre es de un solo nivel y su contenido es dato del motor. Recursar
    sería dejar que el de afuera decida cuánto desarma este lector.

    Lo que NO es lista vuelve tal cual (incluido `None`, que la columna es nullable y hoy
    viaja como `null` en la respuesta). Acá no se normaliza nada: normalizar sería cambiar la
    forma que la API viene devolviendo, que es justo lo contrario de lo que se promete arriba.
    """
    if not isinstance(eventos, list):
        return eventos
    plano = []
    for evento in eventos:
        if (isinstance(evento, dict)
                and set(evento) == {CLAVE_SOBRE_UPSTREAM}
                and isinstance(evento[CLAVE_SOBRE_UPSTREAM], list)):
            plano.extend(evento[CLAVE_SOBRE_UPSTREAM])
        else:
            plano.append(evento)
    return plano


class AuditLogResponseSchema(BaseModel):
    id: UUID
    timestamp: datetime
    user_id: Optional[UUID]
    api_key_id: Optional[UUID]
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    pii_detected: bool
    masked_entities: Optional[List[Any]]
    compliance_status: str
    latency_ms: int
    tokens_saved_by_optimization: int
    guardian_events: Optional[List[Any]]
    # Capa que bloqueó (spec 027, `layer_key` del registry; NULL en filas anteriores y en
    # las permitidas). Va en el listado porque SC-005 pide que el officer vea «qué capa» sin
    # abrir otra vista: con el badge de bloqueo a secas tendría el "qué" pero no el "por
    # dónde". Campo opcional ⇒ los consumidores previos a la 031 no se enteran.
    blocked_by_layer: Optional[str] = None

    # La desenvoltura cuelga del SCHEMA y no del endpoint por dos razones. Una: cualquier
    # vista futura que devuelva esta forma la hereda sin acordarse — un endpoint nuevo que
    # olvidara llamar al helper filtraría el sobre. La otra es más dura: hacerlo sobre la
    # instancia ORM (`log.guardian_events = …`) ensuciaría la fila en la sesión y SQLAlchemy
    # podría flushear el blob DESENVUELTO de vuelta a la base, o sea desarmar en disco la
    # defensa de almacenamiento desde una pantalla de sólo lectura. Acá se transforma el valor
    # ya extraído, camino a la respuesta, y la fila no se entera.
    @field_validator("guardian_events", mode="before")
    @classmethod
    def _vista_logica(cls, valor):
        return desenvolver_eventos_guardian(valor)

    class Config:
        from_attributes = True


class AuditLogListResponseSchema(BaseModel):
    total: int
    logs: List[AuditLogResponseSchema]


def _build_query(db, pii_detected, compliance_status, from_date, to_date, estado=None):
    """Query común del listado y del export. La cadena de licencias se excluye por LITERAL.

    O sea `model = 'license'` pelado (`classifier.dice_licencia()`), como en `main` — NO por la
    forma de `guardian_events`, que es lo que usa la purga. Que los dos criterios no coincidan
    es el dictamen del manager del 14-ago, y la razón cabe en una línea:

        purga = por forma (irreversible → no confía en nadie); vitrina = por literal
        (reversible → y el literal ya es nuestro gracias a la Capa B)

    Las dos mitades importan:

    * **reversible**. Una fila mal escondida de un balde se sigue viendo en el listado sin
      filtro `estado`, que no la toca; un `DELETE` mal decidido no se deshace. Por eso el
      criterio de BORRADO no puede depender de una columna que escribe el inspeccionado y el
      de esta pantalla sí puede;
    * **el literal ya es nuestro**. La Capa B (`gateway.sanear_modelo_declarado`, consumida por
      `api/gateway.py` en la puerta y por `api/internal.py:279` del lado del motor) desaloja
      `license` al centinela `license__cliente` antes de que toque la columna, así que en una
      instalación nueva el cliente no se puede pedir a sí mismo el escondite. Las dos piezas se
      leen juntas: si alguien saca ese saneo, esta exclusión deja de ser una exclusión.

    Y por qué NO `~es_licencia()` (literal **más** el `seq` del eslabón), que fue lo que se
    probó antes: con esa exclusión una fila de licencia LEGÍTIMA pre-US5 —trae `event_type` y
    no trae `seq`, porque la hash-chain llegó recién el 20-jul— se le muestra al officer en el
    balde «bloqueados», mezclada con los intentos de fuga de los usuarios. Medido: `total=1`
    donde `main` da `0`. Es superficie viva de cliente y no se negocia.

    NOTA (no bloqueante, y es HERENCIA de `main`, no una regresión de esta ronda): un spoof
    VIEJO con `model='license'` que ya esté escrito en la base de una instalación sigue
    invisible en estos dos baldes. Lo que cambió con la 018 es que ahora ES purgable —el portón
    de la purga no mira esta columna—, así que el problema se extingue solo con las corridas en
    vez de quedarse para siempre.
    """
    query = db.query(AuditLog)
    if pii_detected is not None:
        query = query.filter(AuditLog.pii_detected == pii_detected)
    if compliance_status is not None:
        query = query.filter(AuditLog.compliance_status == compliance_status)
    if estado is not None:
        # Los dos valores son complementarios sobre el MISMO universo (tráfico que el firewall
        # llegó a resolver, sin los eslabones de licencia ni los rechazos por capacidad):
        # `bloqueados` + `permitidos` = todo lo que el filtro considera, sin filas que se
        # caigan entre ambos ni que aparezcan en los dos.
        #
        # Las dos exclusiones van ANTES de la bifurcación, no dentro de cada rama: es lo que
        # hace que la complementariedad sea cierta por construcción y no por acordarse de
        # repetir el filtro en las dos ramas.
        query = query.filter(~dice_licencia())
        query = query.filter(~es_rechazo())
        if estado == EstadoFiltro.BLOQUEADOS:
            query = query.filter(es_bloqueo())
        else:
            query = query.filter(~es_bloqueo())
    if from_date:
        try:
            query = query.filter(AuditLog.timestamp >= datetime.fromisoformat(from_date))
        except ValueError:
            pass
    if to_date:
        try:
            query = query.filter(AuditLog.timestamp <= datetime.fromisoformat(to_date))
        except ValueError:
            pass
    return query


_ESTADO_DESC = ("Aísla el resultado del pedido: `bloqueados` = intentos impedidos "
                "(compliance_status con prefijo `blocked_`), `permitidos` = el resto. "
                "Excluye los eslabones de licencia (model='license'), que no son tráfico, y "
                "los rechazos por capacidad (prefijo `rejected_`), que no se sirvieron ni los "
                "impidió una política. Sin `estado` siguen apareciendo en el listado.")


@router.get("", response_model=AuditLogListResponseSchema)
def list_audit_logs(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    pii_detected: Optional[bool] = Query(None),
    compliance_status: Optional[str] = Query(None),
    estado: Optional[EstadoFiltro] = Query(None, description=_ESTADO_DESC),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = _build_query(db, pii_detected, compliance_status, from_date, to_date, estado)
    total = query.count()
    logs = query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit).all()
    return {"total": total, "logs": logs}


@router.get("/export")
def export_audit_logs_csv(
    pii_detected: Optional[bool] = Query(None),
    compliance_status: Optional[str] = Query(None),
    estado: Optional[EstadoFiltro] = Query(None, description=_ESTADO_DESC),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Streams audit logs as CSV. No prompt text or PII is included.

    Acepta los MISMOS filtros que el listado (incluido `estado`, spec 031): el officer que
    filtró «Bloqueados» en pantalla y exporta tiene que llevarse esas filas y no la tabla
    entera — un export que ignora el filtro visible es una trampa silenciosa.
    """
    query = _build_query(db, pii_detected, compliance_status, from_date, to_date, estado)
    # Limit export to 5000 rows to avoid memory exhaustion
    logs = query.order_by(AuditLog.timestamp.desc()).limit(5000).all()

    def generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "id", "timestamp", "model",
            "prompt_tokens", "completion_tokens", "cost_usd",
            "pii_detected", "compliance_status", "latency_ms",
            "tokens_saved_by_optimization", "guardian_events_count",
        ])
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate()

        for log in logs:
            writer.writerow([
                str(log.id),
                log.timestamp.isoformat() if log.timestamp else "",
                log.model,
                log.prompt_tokens,
                log.completion_tokens,
                float(log.cost_usd),
                log.pii_detected,
                log.compliance_status,
                log.latency_ms,
                log.tokens_saved_by_optimization,
                # Sobre la vista LÓGICA, no sobre lo guardado. La columna se llama
                # `guardian_events_count` y significa «cuántos guardianes se activaron en este
                # pedido»; contar los elementos del jsonb daría 1 en toda fila con sobre y el
                # número cambiaría de significado sin cambiar de nombre. Es una columna de un
                # export de compliance: el officer la compara mes contra mes y no tiene forma
                # de saber que el de este mes cuenta otra cosa.
                len(desenvolver_eventos_guardian(log.guardian_events) or []),
            ])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()

    filename = f"audit_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
