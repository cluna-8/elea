"""Estado REAL de cada capa de gobernanza (spec 027, US1/T013 — data-model §4).

Este módulo responde **la** pregunta de la US1: para un alcance dado (modo de conexión y,
opcionalmente, superficie), ¿qué le pasa de verdad a cada capa? Y la responde con un
default inseguro: lo que no se puede confirmar se reporta ``no_disponible``, jamás
``aplicandose``.

**El estado se CALCULA en cada consulta y JAMÁS se persiste** (D4). No hay columna de
estado, no hay caché de estado, no hay fila que actualizar: persistirlo sería reintroducir
exactamente el bug que la feature elimina —un dato que dice "activo" mientras el runtime
dice otra cosa—. Lo único cacheado es la **sonda al motor** (30 s, ai_engine_client), que
es una lectura del runtime, no un estado derivado.

Tres fuentes, tres preguntas distintas (data-model §4):

- **A. Declarativo** — ¿qué *es* la capa y qué se desea? Registry ``GOVERNANCE_LAYERS`` +
  la decisión resuelta por la cascada + la credencial cargada en ``guardians``.
- **B. Sonda al motor** — ¿está *cargada*? ``ai_engine_client.probe_loaded_guardrails``.
  Fundamental porque el motor **ignora en silencio** los nombres de guardrail desconocidos
  (D4): sin la sonda, "activada" y "no-op invisible" son indistinguibles.
- **C. Evidencia por pedido** — ¿*corrió* de verdad? Las ``applied_layers`` recientes de
  ``audit_logs``. Metadata-only (C1): entran códigos de capa y nada más.

**Por qué ``is_active`` de ``guardians`` NO es una fuente**: es **deseo**, no estado (D4).
Los 5 ``engine_guardrail_name`` sembrados apuntan a guardrails que el motor no tiene
cargados; leer ese booleano y llamarlo "activo" es la mentira que 027 existe para borrar.
Acá ``guardians`` se lee para exactamente dos cosas: si hay credencial cargada (el
booleano, nunca el valor) y con qué nombre de motor se cablea la capa (uso interno).

**Constitución VII (white-label)**: los nombres de guardrail del motor y los
``guardian_types`` del registry se usan SOLO para el cruce interno con la sonda; nunca
salen en un ``motivo``, en un log ni en la respuesta. El ``motivo`` sale de un **catálogo
cerrado** definido acá abajo (garantía (f) del contrato): jamás del mensaje de una
excepción del motor o de la sonda, que naturalmente lleva hosts internos, nombres de
proveedor y tracebacks.

**Constraint C1**: nada de lo que produce este módulo lleva texto libre del usuario, valor
detectado ni fragmento de prompt — solo códigos del catálogo y copy fijo del producto.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Mapping, Tuple

from ..models.audit import AuditLog
from ..models.guardian import Guardian
from .governance_catalog import (
    GOVERNANCE_LAYERS,
    LAYER_KEYS,
    GovernanceLayer,
    MODE_GATEWAY_MODELS,
    MODE_SUBSCRIPTION,
    PLANE_BACKEND,
    PLANE_ENGINE,
    PLANE_GATEWAY,
    Profile,
    STATUS_APPLIED,
)

logger = logging.getLogger("sentinel-secure-gateway.governance")

# ── Vocabulario cerrado de estados (contrato #4) ──────────────────────────────────
ESTADO_APLICANDOSE = "aplicandose"
ESTADO_REQUIERE_CREDENCIAL = "requiere_credencial"
ESTADO_DELEGADA = "delegada"
ESTADO_NO_DISPONIBLE = "no_disponible"
ESTADO_DEGRADADA = "degradada"
ESTADOS = frozenset({
    ESTADO_APLICANDOSE, ESTADO_REQUIERE_CREDENCIAL, ESTADO_DELEGADA,
    ESTADO_NO_DISPONIBLE, ESTADO_DEGRADADA,
})

# ── Catálogo CERRADO de motivos (garantía (f) del contrato) ───────────────────────
#
# Todo `motivo` que sale de este módulo es una de estas constantes o el `delegation_reason`
# del registry. Ninguna otra fuente: ni `str(exc)`, ni el cuerpo de la respuesta del motor,
# ni el nombre del guardrail. La razón no es estética — el texto de una excepción del motor
# contiene nombres de proveedor externo (Constitución VII), hosts internos y, cuando el
# error viene de un guardrail, fragmentos del contenido inspeccionado (C1). Un catálogo
# cerrado hace que ese texto no tenga por dónde llegar a la UI.
#
# El copy cumple FR-013: cada motivo distingue **"esta capa no la aplicamos nosotros"** de
# **"estás desprotegido"**, recordando qué sigue protegiendo al pedido (el piso).
_PISO_SIGUE = ("El piso no negociable —interceptar, registrar, detectar datos personales y "
               "bloquear secretos— se sigue aplicando.")

MOTIVO_PISO = ("Forma parte del piso no negociable: se aplica a todo el tráfico de este "
               "alcance y ninguna configuración puede desactivarla.")
MOTIVO_APLICANDOSE = "Se está aplicando al tráfico de este alcance."
MOTIVO_REQUIERE_CREDENCIAL = (
    "Está activada, pero falta cargar la credencial del servicio que la ejecuta. Hasta que "
    "se cargue no se aplica y no la reportamos como activa. " + _PISO_SIGUE)
MOTIVO_APAGADA = (
    "Desactivada por configuración para este alcance: no la aplicamos nosotros. " + _PISO_SIGUE)
MOTIVO_FUERA_DE_ALCANCE = (
    "No interviene en este modo de conexión: solo puede aplicarse al tráfico hacia modelos "
    "administrados por la pasarela. " + _PISO_SIGUE)
MOTIVO_MOTOR_SIN_CONFIRMAR = (
    "No pudimos confirmar con el motor de la pasarela que esta capa esté cargada, así que no "
    "afirmamos que se esté aplicando. " + _PISO_SIGUE)
MOTIVO_NO_CARGADA = (
    "El motor de la pasarela no tiene cargada esta capa: está ofrecida por el producto pero "
    "no se ejecuta sobre el tráfico. " + _PISO_SIGUE)
MOTIVO_SIN_CABLEADO = (
    "No hay ninguna instancia configurada que ejecute esta capa, así que no se aplica. "
    + _PISO_SIGUE)
MOTIVO_SIN_EVIDENCIA = (
    "Está cargada, pero todavía no registramos tráfico que confirme que se ejecutó; no la "
    "damos por aplicada hasta confirmarlo. " + _PISO_SIGUE)
MOTIVO_SERVICIO_NO_CONFIRMADO = (
    "El servicio propio que ejecuta esta capa no está confirmado, así que no la damos por "
    "aplicada. " + _PISO_SIGUE)
MOTIVO_DEGRADADA = (
    "Venía aplicándose y dejó de confirmarse: la reportamos como degradada, nunca como "
    "activa. " + _PISO_SIGUE)
MOTIVO_DEGRADADA_SERVICIO = (
    "Venía aplicándose y el servicio propio que la ejecuta dejó de confirmarse: la "
    "reportamos como degradada, nunca como activa. " + _PISO_SIGUE)

# Congelado para el test negativo de white-label y para que agregar un motivo nuevo sea un
# cambio consciente en este archivo, no un f-string improvisado en un router.
MOTIVOS = frozenset({
    MOTIVO_PISO, MOTIVO_APLICANDOSE, MOTIVO_REQUIERE_CREDENCIAL, MOTIVO_APAGADA,
    MOTIVO_FUERA_DE_ALCANCE, MOTIVO_MOTOR_SIN_CONFIRMAR, MOTIVO_NO_CARGADA,
    MOTIVO_SIN_CABLEADO, MOTIVO_SIN_EVIDENCIA, MOTIVO_SERVICIO_NO_CONFIRMADO,
    MOTIVO_DEGRADADA, MOTIVO_DEGRADADA_SERVICIO,
})


# ── Qué planos intervienen en cada modo ───────────────────────────────────────────
#
# El estado se reporta por (plano, superficie), nunca como escalar global (data-model §4.2):
# un escalar volvería a mentir, solo que más fino. La correspondencia sale del mapeo de
# rutas efectivas de la librería compartida:
#
#   subscription    ← gateway-passthrough                 ⇒ plano `gateway`
#   gateway-models  ← engine-guardrail, chat-ui, byok     ⇒ planos `engine` + `backend`
#
# Consecuencia buscada: una capa que solo existe en el motor (moderación, anti-inyección,
# content-safety, guardrails de plataforma) **no interviene** en el tráfico de suscripción.
# Eso se reporta como delegación cuando el registry la declara delegable, y como
# "fuera de alcance" cuando no — nunca como un falso "te falta credencial".
_SCOPE_PLANES: Mapping[str, frozenset] = {
    MODE_SUBSCRIPTION: frozenset({PLANE_GATEWAY}),
    MODE_GATEWAY_MODELS: frozenset({PLANE_ENGINE, PLANE_BACKEND}),
}

# Nombre con el que NUESTRO propio guardrail está registrado en el motor. Es el que ejecuta
# el piso y el enmascarado dentro del plano motor: una sola pieza de código nuestra, no un
# guardrail de proveedor. Configurable por env porque un despliegue white-label puede
# registrarlo con otro nombre; se usa SOLO para el cruce con la sonda y nunca sale en una
# respuesta.
_OWN_GUARDRAIL_DEFAULT = "sentinel-guardian"

# Ventana de evidencia (fuente C). Corta a propósito: "corrió hace un rato" es lo que
# distingue `degradada` de `no_disponible`, y una ventana larga haría que una capa caída
# siguiera reportándose viva durante horas. El límite de filas acota el costo de la lectura
# en instalaciones con mucho tráfico.
_EVIDENCE_WINDOW_MINUTES = 15
_EVIDENCE_ROW_LIMIT = 200


def _own_guardrail_name() -> str:
    return os.getenv("SENTINEL_ENGINE_GUARDRAIL_NAME", _OWN_GUARDRAIL_DEFAULT).strip() or _OWN_GUARDRAIL_DEFAULT


@dataclass(frozen=True)
class StatusInputs:
    """Todo lo que el cálculo necesita de la base, leído UNA vez por consulta.

    Existe para que ``compute_layer_state`` sea una función **pura**: mismos inputs, mismo
    estado. Sin esto, el cálculo tendría queries adentro y sería intesteable salvo con una
    base viva por caso — que es como se termina sin tests para justo la lógica que decide
    si el producto afirma o no que una protección está corriendo.
    """

    # layer_key → hay credencial cargada (solo el booleano; el valor cifrado jamás se lee).
    credentials: frozenset = frozenset()
    # layer_key → nombres de guardrail del motor con los que se cablea. USO INTERNO: se
    # cruzan contra la sonda y no salen en ninguna respuesta (Constitución VII).
    engine_names: Mapping[str, frozenset] = field(default_factory=dict)
    # layer_key con evidencia reciente de ejecución (fuente C), metadata-only.
    evidence: frozenset = frozenset()
    # Servicios propios confirmados (``requires_service`` del registry, sidecar de la 016).
    services: frozenset = frozenset()


# ── Lecturas (fuente A y C) ───────────────────────────────────────────────────────


def _guardians_of_tenant(db, tenant_id) -> Tuple:
    """Filas de ``guardians`` del tenant. **Query propia, filtrada por tenant**
    (Constitución III) y de solo lectura.

    Deliberadamente NO se llama a ``get_or_create_default_guardians``: ese camino BORRA la
    tabla entera y re-siembra cuando hay menos de 9 filas (guardian_service.py:33-36), o
    sea que consultar el estado destruiría la configuración del cliente. Consultar jamás
    debe escribir.
    """
    if db is None:
        return ()
    try:
        query = db.query(Guardian)
        if tenant_id is not None:
            query = query.filter(Guardian.tenant_id == tenant_id)
        return tuple(query.all())
    except Exception:
        # Metadata-only y fail-closed: sin filas no hay credenciales ni cableado, así que
        # ninguna capa opcional puede reportarse aplicándose. Degrada hacia menos afirmación.
        logger.warning("governance: no se pudieron leer las instancias de guardián")
        return ()


def _credentials_and_wiring(guardians) -> Tuple[frozenset, dict]:
    """Cruza las filas de ``guardians`` con el registry por ``guardian_type``.

    El enlace es LÓGICO, nunca por FK (D1): el seed borra y re-siembra la tabla, así que
    cualquier FK moriría en el próximo arranque. Una capa puede tener N instancias (el
    mismo concepto con proveedores distintos): alcanza con que UNA tenga credencial para
    que la capa deje de estar en ``requiere_credencial``.
    """
    by_type: dict = {}
    for guardian in guardians:
        by_type.setdefault(getattr(guardian, "guardian_type", None), []).append(guardian)

    credentials = set()
    engine_names: dict = {}
    own = _own_guardrail_name()
    for layer_key in LAYER_KEYS:
        layer = GOVERNANCE_LAYERS[layer_key]
        # SOLO guardianes activos: el enforcement (`_engine_guardrails_for_profile`) salta los
        # inactivos, así que contar su credencial o su cableado acá reportaría una capa como
        # disponible/aplicándose que el pedido siguiente NO va a ejecutar — sobre-reporte, la
        # mentira que 027 borra. No contradice D4 (is_active no DECLARA estado): acá is_active
        # solo decide qué instancias aportan al INPUT, en la misma dirección fail-closed que el
        # enforcement. La confirmación de "corre" la sigue dando la sonda + la evidencia.
        instancias = [g for t in layer.guardian_types for g in by_type.get(t, ())
                      if getattr(g, "is_active", False)]
        if any(getattr(g, "service_api_key_encrypted", None) for g in instancias):
            credentials.add(layer_key)
        if _carried_by_own_guardrail(layer):
            engine_names[layer_key] = frozenset({own})
        else:
            engine_names[layer_key] = frozenset(
                n for n in (getattr(g, "engine_guardrail_name", None) for g in instancias)
                if isinstance(n, str) and n
            )
    return frozenset(credentials), engine_names


def _carried_by_own_guardrail(layer: GovernanceLayer) -> bool:
    """¿La ejecuta NUESTRO guardrail dentro del motor, o una pieza de un tercero?

    Se deriva del registry en vez de listarse a mano: una capa que además de ``engine``
    corre en ``gateway`` o ``backend`` es, por construcción, código nuestro compartido por
    los tres call-sites (el piso y el enmascarado). Una capa que **solo** existe en el plano
    motor es una pieza registrada por nombre en el motor, y ese nombre es justo el que el
    motor ignora en silencio si no lo conoce (D4).

    La distinción decide si hace falta evidencia por pedido para afirmar que la capa corre:
    ver ``_requires_evidence``.
    """
    return bool(layer.planes - {PLANE_ENGINE})


def recent_evidence(db, tenant_id) -> frozenset:
    """Capas con evidencia reciente de ejecución (fuente C), leída de ``applied_layers``.

    Metadata-only por construcción: se leen ``layer_code`` y ``status``, nada más — la
    columna, por C1, no puede llevar otra cosa. Sirve para lo que ninguna otra fuente
    distingue: *nunca se confirmó* (``no_disponible``) vs *venía corriendo y se cayó*
    (``degradada``).

    Fail-closed: cualquier problema de lectura devuelve el conjunto vacío, y el conjunto
    vacío solo puede quitar afirmaciones de ejecución, nunca agregarlas.
    """
    if db is None or tenant_id is None:
        return frozenset()
    desde = datetime.utcnow() - timedelta(minutes=_EVIDENCE_WINDOW_MINUTES)
    try:
        filas = (db.query(AuditLog.applied_layers)
                 .filter(AuditLog.tenant_id == tenant_id,      # Constitución III — SIEMPRE
                         AuditLog.timestamp >= desde,
                         AuditLog.applied_layers.isnot(None))
                 .order_by(AuditLog.timestamp.desc())
                 .limit(_EVIDENCE_ROW_LIMIT)
                 .all())
    except Exception:
        logger.warning("governance: no se pudo leer la evidencia reciente de aplicación")
        return frozenset()

    vistas = set()
    for (applied,) in filas:
        if not isinstance(applied, list):
            continue
        for entry in applied:
            if not isinstance(entry, dict) or entry.get("status") != STATUS_APPLIED:
                continue
            code = entry.get("layer_code")
            if code in GOVERNANCE_LAYERS:
                vistas.add(code)
    return frozenset(vistas)


def confirmed_services() -> frozenset:
    """Servicios propios confirmados (``requires_service``).

    Hoy **vacío**: ninguna capa del catálogo inicial declara ``requires_service``, así que
    el conjunto no cambia ningún estado. Existe con nombre propio para que la regla 2b de
    data-model §4.1 esté implementada de verdad y no "pendiente": cuando la 016 declare el
    sidecar NLP, la única pieza que falta es el healthcheck acá adentro — y hasta entonces
    el default vacío es fail-closed (una capa que declare un servicio no confirmado jamás
    reporta ``aplicandose``).
    """
    return frozenset()


def gather_status_inputs(db, tenant_id) -> StatusInputs:
    """Las tres lecturas de una consulta de estado, en un solo lugar."""
    credentials, engine_names = _credentials_and_wiring(_guardians_of_tenant(db, tenant_id))
    return StatusInputs(credentials=credentials, engine_names=engine_names,
                        evidence=recent_evidence(db, tenant_id),
                        services=confirmed_services())


# ── Máquina de estados (data-model §4.1) ──────────────────────────────────────────


def _requires_evidence(layer: GovernanceLayer) -> bool:
    """¿Hace falta evidencia por pedido para afirmar que esta capa corre?

    Sí para las capas que el motor ejecuta **por nombre** (las de proveedor): el hallazgo
    central de D4 es que un nombre desconocido no matchea, no rompe y no deja rastro, así
    que "está en la lista" no prueba que se ejecutó sobre el tráfico.

    No para las que ejecuta nuestro propio guardrail: ahí la sonda confirma que la pieza de
    código está cargada y esa pieza es la misma que corre en los otros dos planos. Exigirles
    evidencia haría que una instalación recién levantada mostrara el enmascarado —el control
    insignia del producto, activo por default— como ``no_disponible`` hasta que pasara el
    primer pedido, que es precisamente el tipo de reporte engañoso que la US1 elimina
    (quickstart SC-001 espera el piso y ``pii_masking`` aplicándose sin tráfico previo).
    """
    return not _carried_by_own_guardrail(layer)


def compute_layer_state(layer: GovernanceLayer, *, desired: bool, mode: str,
                        probe, inputs: StatusInputs) -> Tuple[str, str]:
    """Estado efectivo + motivo de UNA capa en UN alcance. **Función pura.**

    Evaluación en orden, primer match gana (data-model §4.1):

    2. La delegación es propiedad del **modo**, no del deseo ni de la credencial.
    1. Credencial faltante solo se reporta si la capa está **deseada** — una capa apagada
       por decisión cae al default y no genera un falso "te falta credencial".
    2b. Servicio propio requerido y no confirmado ⇒ nunca ``aplicandose``; ``degradada`` si
       venía aplicándose, ``no_disponible`` si nunca estuvo arriba.
    3. ``aplicandose`` exige deseo + confirmación (sonda o carga estructural) + evidencia
       cuando corresponde.
    4. Estuvo aplicándose y dejó de confirmarse ⇒ ``degradada``.
    5. **Cualquier otro caso ⇒ ``no_disponible``** (default fail-closed): motor
       inalcanzable, nombre que el motor no conoce, capa sin cablear, sin información.

    **Por qué la delegación va antes que la credencial** (única desviación del orden
    literal de la tabla, deliberada y con precedente en el mismo repo): en modo suscripción
    la protección la aporta el extremo upstream, así que la credencial de nuestro proveedor
    no cambiaría absolutamente nada del tráfico. Con el orden inverso, la MISMA capa
    reportaba **peor** estado cuando el admin la encendía (``requiere_credencial``) que
    cuando la dejaba apagada (``delegada``), y le pedía cargar una credencial inútil. Es
    exactamente el reordenamiento que ya hizo ``build_attribution``
    (sentinel_governance.py, chain de ``applied_layers``) con el mismo argumento; mantenerlo acá
    es lo que evita que el producto se contradiga a sí mismo, con la vista de gobernanza
    diciendo "te falta credencial" y la atribución del pedido diciendo ``delegated``.

    Devuelve ``(estado, motivo)`` con el motivo tomado del catálogo cerrado de arriba o del
    ``delegation_reason`` del registry — nunca de una excepción ni de la sonda.
    """
    planes_del_alcance = _SCOPE_PLANES.get(mode, _SCOPE_PLANES[MODE_GATEWAY_MODELS])
    planes_activos = layer.planes & planes_del_alcance
    tuvo_evidencia = layer.layer_key in inputs.evidence

    # 2 — delegada al proveedor upstream (FR-013): la protección la aporta el extremo
    # upstream, así que ni pedimos credencial ni afirmamos que la aplicamos nosotros.
    if layer.delegable_to_upstream and mode == MODE_SUBSCRIPTION:
        return ESTADO_DELEGADA, (layer.delegation_reason or MOTIVO_FUERA_DE_ALCANCE)

    # 1 — credencial faltante (solo si la capa está deseada).
    if desired and layer.requires_credential and layer.layer_key not in inputs.credentials:
        return ESTADO_REQUIERE_CREDENCIAL, MOTIVO_REQUIERE_CREDENCIAL

    # 2b — servicio propio requerido sin confirmar. El "estructural" de la sonda NO aplica:
    # el código puede estar en el proceso y el servicio caído igual.
    if desired and layer.requires_service and layer.requires_service not in inputs.services:
        if tuvo_evidencia:
            return ESTADO_DEGRADADA, MOTIVO_DEGRADADA_SERVICIO
        return ESTADO_NO_DISPONIBLE, MOTIVO_SERVICIO_NO_CONFIRMADO

    # ¿La capa siquiera interviene en este alcance?
    if not planes_activos:
        return ESTADO_NO_DISPONIBLE, MOTIVO_FUERA_DE_ALCANCE

    # Confirmación de carga. Si el motor participa del alcance, manda la sonda; si la capa
    # corre solo en planos nuestros (gateway/backend), la carga es estructural: el código
    # está en el propio proceso que atiende el pedido.
    nombres = frozenset(inputs.engine_names.get(layer.layer_key, ()))
    if PLANE_ENGINE in planes_activos:
        confirmada = any(probe.has(nombre) for nombre in nombres)
    else:
        confirmada = True

    # 3 — aplicándose.
    if desired and confirmada and (tuvo_evidencia or layer.is_floor
                                   or not _requires_evidence(layer)):
        return ESTADO_APLICANDOSE, (MOTIVO_PISO if layer.is_floor else MOTIVO_APLICANDOSE)

    # 4 — degradada: estuvo confirmada y dejó de estarlo.
    if desired and tuvo_evidencia and not confirmada:
        return ESTADO_DEGRADADA, MOTIVO_DEGRADADA

    # 5 — default fail-closed, con el motivo más informativo del catálogo cerrado.
    return ESTADO_NO_DISPONIBLE, _motivo_no_disponible(
        layer, desired=desired, confirmada=confirmada, nombres=nombres, probe=probe)


def _motivo_no_disponible(layer: GovernanceLayer, *, desired: bool, confirmada: bool,
                          nombres: frozenset, probe) -> str:
    """El motivo del ``no_disponible``, del catálogo cerrado.

    Distinguir los motivos ES el requisito (FR-013): "la apagaste vos", "el producto la
    ofrece pero el motor no la tiene cargada" y "el motor no responde y por eso no
    afirmamos nada" son tres situaciones con acciones distintas para el admin, y colapsarlas
    en un "no disponible" pelado es la mitad de la mentira que 027 viene a borrar.
    """
    if not desired:
        return MOTIVO_APAGADA
    if not confirmada:
        if not nombres:
            return MOTIVO_SIN_CABLEADO
        if not getattr(probe, "confirmed", False):
            return MOTIVO_MOTOR_SIN_CONFIRMAR
        return MOTIVO_NO_CARGADA
    # Confirmada, deseada y aun así no aplicándose: falta la evidencia de ejecución.
    return MOTIVO_SIN_EVIDENCIA


# ── Serialización pública (shape del contrato) ────────────────────────────────────


def layer_status_payload(layer: GovernanceLayer, decision, *, mode: str, probe,
                         inputs: StatusInputs) -> dict:
    """El dict de UNA capa, con el shape EXACTO del contrato (7 claves, ni una más).

    Los tres campos declarativos salen de ``to_public_dict()`` y no de ``asdict()``: el
    dataclass lleva ``guardian_types`` con nombres de proveedor externo en claro, y
    publicarlos rompería el white-label (Constitución VII). Los cuatro computados
    mantienen los dos ejes **independientes** (garantía (c)): ``decision_resuelta`` es lo
    que el admin decidió, ``estado_efectivo`` es lo que pasa de verdad — una capa ``on``
    puede estar perfectamente ``no_disponible``.
    """
    publico = layer.to_public_dict()
    desired = bool(decision and decision.decision == "on")
    estado, motivo = compute_layer_state(layer, desired=desired, mode=mode,
                                         probe=probe, inputs=inputs)
    return {
        "layer_key": publico["layer_key"],
        "tier": publico["tier"],
        "planes": publico["planes"],          # LISTA, no escalar: el piso corre en los tres
        "decision_resuelta": decision.decision if decision else None,
        "origen": decision.origin if decision else None,
        "estado_efectivo": estado,
        "motivo": motivo,
    }


def build_status_layers(profile: Profile, *, probe, inputs: StatusInputs) -> list:
    """Las capas de un alcance, en el orden canónico del catálogo (determinista, FR-006).

    Exhaustiva sobre el registry: **toda** capa aparece, también las apagadas y las que no
    intervienen en este modo. Si una capa pudiera faltar, "no la aplicamos" y "ni siquiera
    la consideramos" volverían a ser indistinguibles.
    """
    return [
        layer_status_payload(GOVERNANCE_LAYERS[key], profile.decision_for(key),
                             mode=profile.mode, probe=probe, inputs=inputs)
        for key in LAYER_KEYS
    ]
