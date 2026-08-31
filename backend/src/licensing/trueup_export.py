"""True-up export firmado con la deployment key (spec 021 US5, T041 — FR-029).

Export 100% LOCAL (sin egress) de lo que la caja registró: seats del tenant
licenciado + historial COMPLETO de eventos de licencia encadenados (metadata-
only) + hash-head + contador, firmado Ed25519 con la deployment key. El
operador lo genera y lo envía a Sentinel fuera de banda (renovación/true-up).

El verificador (lado Sentinel, ESTE mismo módulo — artefacto cross-party) valida:
firma vs la pública registrada; la cadena interna del export; la génesis del
onboarding en el PRIMER export; y la CONTINUIDAD entre exports sucesivos —
contador no-decreciente y head previo ANCESTRO del nuevo. Eso es lo que vuelve
detectable el truncado de cola que la verificación local no puede ver (T039):
quien borra historial produce un export cuyo head previo ya no es ancestro.

El lector de la cadena es UNO SOLO y vive en ``audit_events.chained_entries``: este módulo lo
IMPORTA en vez de copiarlo. Tenía su propia copia (``_chained_entries``) y las dos hacían
``"seq" in guardian_events[0]`` sin mirar el tipo — con ``in`` buscando subcadena sobre un
string, una fila ``model='license'`` deforme tiraba abajo el export con ``TypeError`` (HALLAZGO
2 del gate adversarial de la 018; la guarda y su porqué están allá). Que sea la MISMA que la de
``verify_chain`` no es prolijidad: dos criterios distintos de «qué fila es un eslabón» harían
que el papel firmado y la verificación local hablen de historiales distintos.
"""
import base64
import logging
from datetime import datetime, timezone
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization

from .audit_events import chained_entries, entry_hash, genesis_anchor
from .entitlement import expected_tenant_id, get_state
from .seat_counter import count_active_seats
from .token import canonical_payload_bytes
from . import deployment_key

logger = logging.getLogger(__name__)

SCHEMA = 1
KIND = "sentinel-trueup"


class TrueUpError(Exception):
    pass


def build_payload(session_factory=None, now: Optional[datetime] = None) -> dict:
    """Payload SIN firmar: refleja el estado registrado por la caja."""
    if session_factory is None:
        from ..database import SessionLocal
        session_factory = SessionLocal
    now = now or datetime.now(timezone.utc)
    lic_state = get_state()
    token = lic_state.token
    tenant_id = expected_tenant_id()
    db = session_factory()
    try:
        from ..models.license_state import LicenseRuntimeState
        state = db.query(LicenseRuntimeState).filter(LicenseRuntimeState.id == 1).one_or_none()
        # SNAPSHOT al contador leído (hardening post-review): un emit que
        # comitea entre las dos lecturas metería eventos por encima del head
        # firmado → export auto-inconsistente (falso tamper). Lo que entre
        # después va al próximo export; la continuidad no se afecta.
        counter_snapshot = state.event_counter if state else 0
        events = [e for e in chained_entries(db) if e["seq"] <= counter_snapshot]
        return {
            "schema": SCHEMA,
            "kind": KIND,
            "tenant_id": tenant_id,
            "license_id": token.license_id if token else None,
            "distributor_id": token.distributor_id if token else None,
            "pool_id": token.pool_id if token else None,
            "license_status": lic_state.status,
            "max_seats": token.max_seats if token else None,
            "seats_used": count_active_seats(db, tenant_id),
            "generated_at": now.isoformat(),
            "genesis_license_id": state.genesis_license_id if state else None,
            "hash_head": state.hash_head if state else None,
            "counter": state.event_counter if state else 0,
            "range": {"from_seq": events[0]["seq"] if events else None,
                      "to_seq": events[-1]["seq"] if events else None},
            "events": events,  # historial COMPLETO, metadata-only (chico por diseño)
        }
    finally:
        db.close()


def generate_signed_export(session_factory=None, now: Optional[datetime] = None) -> dict:
    payload = build_payload(session_factory=session_factory, now=now)
    sig = deployment_key.sign(canonical_payload_bytes(payload))
    return {**payload, "sig": base64.b64encode(sig).decode()}


def verify_export(doc: dict, deployment_public_pem: str,
                  expected_genesis_license_id: Optional[str] = None,
                  previous: Optional[dict] = None) -> None:
    """Verificación lado-Sentinel. Levanta TrueUpError con el motivo; si no
    levanta, el export es consistente."""
    payload = dict(doc)
    sig_b64 = payload.pop("sig", None)
    if not sig_b64:
        raise TrueUpError("export sin firma")
    try:
        public = serialization.load_pem_public_key(deployment_public_pem.encode())
        public.verify(base64.b64decode(sig_b64), canonical_payload_bytes(payload))
    except (InvalidSignature, ValueError) as exc:
        raise TrueUpError(f"firma inválida (byte alterado o clave equivocada): {exc}") from exc

    # Cadena interna: re-computa desde la génesis declarada.
    hash_by_seq = {}
    running = genesis_anchor(payload.get("genesis_license_id"))
    expected_seq = 1
    for event in sorted(payload.get("events", []), key=lambda e: e["seq"]):
        if event["seq"] != expected_seq:
            raise TrueUpError(f"cadena interna inválida: falta seq {expected_seq}")
        if event["prev_hash"] != running:
            raise TrueUpError(f"cadena interna inválida: prev_hash no coincide en seq {event['seq']}")
        running = entry_hash(event)
        hash_by_seq[event["seq"]] = running
        expected_seq += 1
    last_seq = expected_seq - 1
    if last_seq != (payload.get("counter") or 0):
        raise TrueUpError(f"contador ({payload.get('counter')}) no coincide con el historial ({last_seq})")
    if last_seq and payload.get("hash_head") != running:
        raise TrueUpError("hash_head no coincide con el historial recomputado")

    # PRIMER export: la génesis debe ser la registrada en el onboarding. Una
    # génesis 'unlicensed' (boot inicial sin .lic, estado soportado SC-013) se
    # acepta SOLO si la cadena la ata al license_id del onboarding: el evento
    # license_genesis_anchored con ese id, sin ningún evento licenciado antes.
    if expected_genesis_license_id is not None:
        genesis = payload.get("genesis_license_id")
        if genesis == "unlicensed":
            events_sorted = sorted(payload.get("events", []), key=lambda e: e["seq"])
            anchored = next((e for e in events_sorted
                             if e["event_type"] == "license_genesis_anchored"), None)
            if anchored is None or anchored["license_id"] != expected_genesis_license_id \
                    or any(e.get("license_id") for e in events_sorted
                           if e["seq"] < anchored["seq"]):
                raise TrueUpError("génesis 'unlicensed' sin anclaje válido al license_id "
                                  "del onboarding")
        elif genesis != expected_genesis_license_id:
            raise TrueUpError("génesis no coincide con la registrada en el onboarding")

    # Continuidad entre exports sucesivos (la pieza anti-truncado, FR-028).
    if previous is not None:
        prev_counter = previous.get("counter") or 0
        if (payload.get("counter") or 0) < prev_counter:
            raise TrueUpError(f"contador retrocede ({payload.get('counter')} < {prev_counter}) "
                              "— posible truncado")
        if prev_counter and hash_by_seq.get(prev_counter) != previous.get("hash_head"):
            raise TrueUpError("head del export previo no es ancestro del nuevo historial "
                              "— posible truncado/reescritura")
