"""Eventos de licencia → AuditLog inmutable existente, ENCADENADOS por hash
(spec 021, FR-022/024/025/028).

Reusa el canal append-only de la 013 SIN cambios de schema del dominio: cada
transición de licencia es una fila con ``model='license'`` y el detalle
metadata-only dentro de ``guardian_events``. NUNCA se persiste el token crudo,
la firma ni claves (Constraint C1).

Cadena (US5/T032): cada entrada lleva ``seq`` y ``prev_hash`` (hash del evento
anterior; génesis anclada al ``license_id``); el head y el contador viven en
``license_runtime_state`` (fila singleton) y se actualizan en la MISMA
transacción que el evento, bajo ``SELECT … FOR UPDATE`` — serializa requests,
el thread del scheduler y N workers. Borrar/editar un evento intermedio rompe
un eslabón (verify_chain); el truncado de cola sólo lo detecta la continuidad
entre true-up exports (trueup_export.py) — límite documentado en T039.
"""
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = logging.getLogger(__name__)

EVENT_LOADED = "license_loaded"
EVENT_GRACE = "license_grace"
EVENT_EXPIRED = "license_expired"
EVENT_INVALID = "license_invalid"
EVENT_MISMATCH = "license_tenant_mismatch"
EVENT_MISSING = "license_missing"
EVENT_SEAT_LIMIT = "license_seat_limit_exceeded"
# Transiciones de la reconciliación (US3, FR-016): entrada/salida de over_seat.
EVENT_OVER_SEAT = "license_over_seat"
EVENT_OVER_SEAT_RESOLVED = "license_over_seat_resolved"
# Anti-rollback de reloj (US5, FR-023).
EVENT_CLOCK_ROLLBACK = "license_clock_rollback_suspected"
# Anclaje diferido de la génesis (hardening post-review US5): si el primer boot
# fue SIN licencia (génesis 'unlicensed'), el primer license_id con firma
# válida queda atado a la cadena por este evento — el verificador del true-up
# lo exige para aceptar una génesis 'unlicensed' (si no, el primer export de un
# deployment honesto que arrancó sin .lic acusaría tamper sin remediación).
EVENT_GENESIS_ANCHORED = "license_genesis_anchored"

_GENESIS_PREFIX = "sentinel-genesis:"


def genesis_anchor(license_id: Optional[str]) -> str:
    """Ancla de la génesis de la cadena: derivable del license_id que el
    onboarding registra (FR-028) — el primer true-up se verifica contra ella."""
    return hashlib.sha256(f"{_GENESIS_PREFIX}{license_id or 'unlicensed'}".encode()).hexdigest()


def entry_hash(entry: dict) -> str:
    """Hash de UNA entrada encadenada (incluye su prev_hash y seq): canónico
    con el MISMO esquema que la firma del token (sort_keys/separators)."""
    from .token import canonical_payload_bytes
    return hashlib.sha256(canonical_payload_bytes(entry)).hexdigest()


def _locked_state(db, license_id: Optional[str]):
    """Fila singleton bajo FOR UPDATE; la crea (con génesis anclada) si no
    existe — INSERT … ON CONFLICT DO NOTHING tolera la carrera entre workers."""
    from ..models.license_state import LicenseRuntimeState

    state = (db.query(LicenseRuntimeState)
             .filter(LicenseRuntimeState.id == 1)
             .with_for_update().one_or_none())
    if state is None:
        genesis_id = license_id or "unlicensed"
        db.execute(pg_insert(LicenseRuntimeState.__table__).values(
            id=1, genesis_license_id=genesis_id,
            hash_head=genesis_anchor(genesis_id), event_counter=0,
        ).on_conflict_do_nothing(index_elements=["id"]))
        state = (db.query(LicenseRuntimeState)
                 .filter(LicenseRuntimeState.id == 1)
                 .with_for_update().one())
    return state


# Las claves que los dos lectores leen SIN preguntar: `seq` (ordena, mide contigüidad y se
# compara contra el contador persistido) y `prev_hash` (el eslabón propiamente dicho).
_CHAIN_LINK_KEYS = ("seq", "prev_hash")


def _is_chain_link(event) -> bool:
    """¿Este primer ``guardian_event`` es un eslabón LEGIBLE de la cadena?

    Guarda de TIPO, no de contenido: dice si la fila se puede LEER como eslabón, no si el
    eslabón es honesto. Que uno bien formado mienta lo sigue decidiendo el hash.

    Hasta acá el filtro era ``"seq" in r.guardian_events[0]``, y alcanzaba… mientras ese primer
    evento fuera un objeto. Sobre un string es peor que inútil: ``in`` busca SUBCADENA, así que
    ``["seq"]`` pasa el filtro —y ``["consequence"]`` también, sin ni siquiera nombrar la
    clave— y el ``e["seq"]`` de dos líneas más abajo levanta ``TypeError: string indices must be
    integers``. UNA sola fila ``model='license'`` deforme dejaba fuera de servicio la
    verificación de la cadena Y el export de true-up: la evidencia con la que el operador le
    factura al cliente, caída por una excepción sin capturar. Es el HALLAZGO 2 del gate
    adversarial de la 018; la tabla con el efecto medido de cada forma está al pie de
    ``tests/integration/test_retencion_dataset_abusivo.py``.

    Por qué la guarda va acá y no alcanza con la capa B: ``gateway.sanear_modelo_declarado``
    saca el literal reservado del codominio de lo auditable DESDE AHORA, pero no puede sanear
    hacia atrás la base de un cliente ya instalado. Una fila vieja basta, y el que la sufre es
    el lector.

    Las DOS claves y no sólo ``seq`` porque ``verify_chain`` lee ``prev_hash`` sin ``get``
    (``KeyError``). Y el ``seq`` entero porque es la clave de ordenamiento: con un ``seq``
    string mezclado entre ints, el ``sorted`` de ``chained_entries`` revienta comparando ``str``
    con ``int`` antes de que nadie llegue a mirar un hash. El ``bool`` queda afuera del ``int``
    a propósito: para Python ``True`` es 1 y ningún emisor escribe eso.

    Gemelo del predicado del clasificador de retención
    (``services/retention/classifier.py::_trae_seq_de_cadena_en_memoria``), que ya pedía
    ``isinstance(..., dict)`` por este mismo motivo. Queda una asimetría deliberada: acá se
    exige ADEMÁS ``prev_hash`` y el tipo del ``seq``, o sea que este filtro es MÁS estricto. Es
    el lado seguro de la asimetría —la cadena nunca deja de leer un eslabón que la purga sí
    protege, que es el orden inverso al que causaría el incidente de FR-003— al precio de que
    una fila deforme CON forma de objeto siga siendo inmortal para la retención.
    """
    if not isinstance(event, dict):
        return False
    if not all(key in event for key in _CHAIN_LINK_KEYS):
        return False
    seq = event["seq"]
    return isinstance(seq, int) and not isinstance(seq, bool)


def chained_entries(db) -> list:
    """Los eslabones LEGIBLES de la cadena, ordenados por ``seq``.

    Lector ÚNICO de las filas de la cadena: lo comparten ``verify_chain`` y el export de true-up
    (``trueup_export.build_payload``). Compartido y no copiado porque los dos tienen que
    considerar eslabón a las MISMAS filas — si uno adoptara una fila que el otro descarta, el
    papel firmado y la verificación local hablarían de historiales distintos.

    Una fila deforme se SALTEA en vez de reventar. No es indulgencia: no es un eslabón
    verificable, así que no hay nada que verificar en ella, y el precio de la alternativa es que
    la evidencia ENTERA deje de leerse. Tampoco entra a ``issues``: acusar manipulación por una
    fila que el emisor de la 021 nunca escribió es el deployment acusándose solo, que es el
    incidente de confianza que FR-003 vino a evitar. Si el salteo tiene que dejar rastro
    (contador aparte en el reporte, o log), es una decisión de producto y no de esta guarda.

    Y si la fila deforme fuese un eslabón LEGÍTIMO al que alguien le rompió el jsonb, saltearla
    no lo tapa: deja un hueco de ``seq`` y ``verify_chain`` lo reporta igual que un borrado.
    """
    from ..models.audit import AuditLog

    rows = db.query(AuditLog).filter(AuditLog.model == "license").all()
    return sorted(
        (r.guardian_events[0] for r in rows
         if isinstance(r.guardian_events, list) and r.guardian_events
         and _is_chain_link(r.guardian_events[0])),
        key=lambda e: e["seq"],
    )


def verify_chain(db) -> dict:
    """Verificación LOCAL de la cadena: eslabones contiguos, hashes válidos y
    head/contador persistidos consistentes. Devuelve {ok, issues, checked}.
    Límite (contrato T039): el truncado de cola/wipe total NO es detectable
    acá — lo ancla la continuidad entre true-up exports.

    ``checked`` cuenta eslabones LEGIBLES: las filas ``model='license'`` deformes no suman ni
    rompen la verificación (el porqué, en ``chained_entries``)."""
    from ..models.license_state import LicenseRuntimeState

    state = db.query(LicenseRuntimeState).filter(LicenseRuntimeState.id == 1).one_or_none()
    entries = chained_entries(db)
    issues = []
    if state is None:
        if entries:
            issues.append("hay eventos encadenados pero falta license_runtime_state")
        return {"ok": not issues, "issues": issues, "checked": 0}
    running = genesis_anchor(state.genesis_license_id)
    expected_seq = 1
    for entry in entries:
        if entry["seq"] != expected_seq:
            issues.append(f"eslabón roto: falta seq {expected_seq} (salta a {entry['seq']})")
            expected_seq = entry["seq"]
        if entry["prev_hash"] != running:
            issues.append(f"hash inválido en seq {entry['seq']}: prev_hash no coincide "
                          "(evento anterior editado/borrado)")
        running = entry_hash(entry)
        expected_seq += 1
    if state.event_counter != (entries[-1]["seq"] if entries else 0):
        issues.append(f"contador persistido ({state.event_counter}) no coincide con el "
                      f"último seq ({entries[-1]['seq'] if entries else 0})")
    if entries and state.hash_head != running:
        issues.append("head persistido no coincide con el hash recomputado del último evento")
    return {"ok": not issues, "issues": issues, "checked": len(entries)}

_EVENT_BY_STATUS = {
    "active": EVENT_LOADED,
    "grace": EVENT_GRACE,
    "expired": EVENT_EXPIRED,
    "invalid": EVENT_INVALID,
    "mismatch": EVENT_MISMATCH,
    "missing": EVENT_MISSING,
}

# Convención del canal existente: passed | flagged_high_risk | blocked_by_policy.
_COMPLIANCE_BY_EVENT = {
    EVENT_LOADED: "passed",
    EVENT_GRACE: "flagged_high_risk",  # advierte: opera pero la renovación urge
    EVENT_OVER_SEAT_RESOLVED: "passed",
    EVENT_GENESIS_ANCHORED: "passed",
}


def emit_license_event(db, event_type: str, *, tenant_id=None, license_id=None,
                       seats_used: Optional[int] = None, max_seats: Optional[int] = None,
                       reason: Optional[str] = None,
                       now: Optional[datetime] = None) -> None:
    """Persiste UNA transición de licencia como fila del AuditLog (metadata-only),
    ENCADENADA (FR-028): entrada + head/contador avanzan en la misma tx.
    ``now`` viene del tick que la origina (reloj inyectable); default = reloj real."""
    from ..models.audit import AuditLog
    from ..models.tenant import DEFAULT_TENANT_ID

    now = now or datetime.now(timezone.utc)
    state = _locked_state(db, license_id)
    row_tenant = tenant_id or DEFAULT_TENANT_ID
    if isinstance(row_tenant, str):
        row_tenant = uuid.UUID(row_tenant)
    # Anclaje diferido de génesis (one-shot): génesis 'unlicensed' + primer
    # license_id con firma válida → evento de binding ANTES del evento real.
    if (license_id and state.genesis_license_id == "unlicensed"
            and state.anchored_license_id is None):
        _append_chained(db, state, row_tenant, EVENT_GENESIS_ANCHORED,
                        license_id=license_id, seats_used=None, max_seats=None,
                        reason=("primer license_id con firma válida — ata la génesis "
                                "'unlicensed' al license_id del onboarding"),
                        now=now)
        state.anchored_license_id = license_id
    _append_chained(db, state, row_tenant, event_type,
                    license_id=license_id, seats_used=seats_used,
                    max_seats=max_seats, reason=reason, now=now)
    # Marca monotónica (FR-023): el ÚLTIMO ts de licencia visto; nunca retrocede.
    now_naive = now.replace(tzinfo=None)
    if state.monotonic_ts is None or now_naive > state.monotonic_ts:
        state.monotonic_ts = now_naive
    db.commit()


def _append_chained(db, state, row_tenant, event_type, *, license_id,
                    seats_used, max_seats, reason, now) -> dict:
    """Un eslabón: entrada + fila AuditLog + avance de head/contador (misma tx,
    el caller ya tiene la fila singleton bajo FOR UPDATE)."""
    from ..models.audit import AuditLog

    seq = state.event_counter + 1
    entry = {
        "event_type": event_type,
        "license_id": license_id,
        "seats_used": seats_used,
        "max_seats": max_seats,
        "reason": reason,
        "ts": now.isoformat(),
        "prev_hash": state.hash_head,
        "seq": seq,
    }
    db.add(AuditLog(
        tenant_id=row_tenant,
        model="license",
        prompt_tokens=0,
        completion_tokens=0,
        cost_usd=0,
        pii_detected=False,
        compliance_status=_COMPLIANCE_BY_EVENT.get(event_type, "blocked_by_policy"),
        latency_ms=0,
        guardian_events=[entry],
    ))
    state.hash_head = entry_hash(entry)
    state.event_counter = seq
    return entry


def emit_state_event(state, session_factory=None) -> None:
    """Evento por ESTADO de licencia: gate de arranque (US1/T012) y
    transiciones en runtime del ciclo de vida (US4/T029, via
    ``entitlement.refresh``). El tenant de la fila es SIEMPRE el del deployment
    (existe por seed 013); si el token era de otro tenant, ese dato viaja en
    ``reason`` (no como FK, que no existiría acá).

    IDENTIDAD BAJO RLS (spec 018, FR-006 / Contrato 2). Este emisor corre fuera de
    todo request —el gate de arranque y el tick del scheduler de reconciliación— y
    escribe en ``audit_logs``, que está bajo ``FORCE ROW LEVEL SECURITY``. Hasta la
    018 abría la sesión PELADA, y funcionaba por un accidente: la policy permisiva
    ``tenant_isolation_bootstrap`` de la 010 deja pasar cualquier fila mientras nadie
    setee el GUC. La 017 tiene mandato escrito de eliminar esa policy; el día que lo
    haga, este INSERT rebota contra el ``WITH CHECK`` y —porque el emisor es
    fail-soft, ver el ``except`` de abajo— la cadena de licencias dejaría de crecer
    EN SILENCIO. Una cadena que deja de crecer sin avisar es peor que una rota: el
    true-up siguiente no acusa tamper, simplemente no tiene qué exportar.

    Por eso el trabajo va dentro de ``tenant_context(None, bypass=True)``
    (``database.py``). **Sin precedente: este PR estrena ``bypass=True`` en producción**
    —antes no había ninguno en ``backend/src``, sólo el ejercicio de
    ``tests/test_rls_isolation.py``—, así que el listón lo fija esta rama en vez de
    heredarlo. (La letra original citaba ``api/gateway.py:901`` como precedente; ahí hay
    ``with tenant_context(tid):``, tenant SCOPEADO y sin bypass: el opuesto semántico.
    Corregido en el Contrato 2 del 14-ago.) El bypass, y no un tenant
    scopeado, porque estas filas se escriben para el tenant del DEPLOYMENT mientras
    el token puede ser de otro (``license_tenant_mismatch``) y ``verify_chain`` relee
    la cadena ENTERA: el emisor de la cadena es, por definición, cross-tenant. Es
    explícito y localizado —nunca queda de default de sesión: los ContextVar vuelven a
    su valor de reposo al salir del ``with``, y hay test que lo muerde—, que es el
    contrato para todo job batch de la 018.

    Con una precisión que importa para quien copie este patrón: lo que NO muere con el
    ``with`` es el GUC ya inyectado. El listener de ``database.py:44-61`` lo setea con
    ``set_config(..., true)``, o sea ``SET LOCAL``, y eso vive hasta el fin de la
    TRANSACCIÓN. Por eso la sesión se abre y se cierra ACÁ ADENTRO: una sesión creada
    afuera que abriera su transacción dentro del bloque seguiría con el bypass puesto
    después de salir. Es la regla que el purgador (018, T008) hereda escrita —recibe una
    ``session_factory``, jamás una ``Session`` ya viva—, y el motivo por el que este
    emisor toma ``session_factory`` y no ``db``.
    """
    from ..database import tenant_context
    from .entitlement import expected_tenant_id

    event_type = _EVENT_BY_STATUS.get(state.status, EVENT_INVALID)
    token = state.token
    if session_factory is None:
        from ..database import SessionLocal
        session_factory = SessionLocal
    with tenant_context(None, bypass=True):
        db = session_factory()
        try:
            emit_license_event(
                db,
                event_type,
                tenant_id=expected_tenant_id(),
                license_id=token.license_id if token else None,
                max_seats=token.max_seats if token else None,
                reason=state.reason,
                now=state.checked_at,  # el ts de la evidencia = el del tick evaluado
            )
        except Exception:  # noqa: BLE001 — fail-soft (criterio de AuditService)
            db.rollback()
            logger.exception("licencia: fallo al persistir el evento %s", event_type)
        finally:
            db.close()
