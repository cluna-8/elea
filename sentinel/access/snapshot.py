"""Instantánea por organización de los perfiles de acceso (069 T048; D6) y perfiles sembrados."""
from __future__ import annotations

import uuid
from typing import Optional

from . import models as am
from .resolver import AccessSnapshot, Profile, Rule

# Perfiles que se crean al primer acceso de cada organización (`ensure_seed`). «Bloqueados» no es un
# selector: las entradas `blocked_by_default` sin habilitar el catálogo ya las deja fuera del servicio,
# así que «Todos salvo bloqueados» = todo lo que el catálogo sirve (los tres estados del semáforo).
SEEDS = (
    ("Todos salvo bloqueados", (("include", "semaforo", "eu_ok"), ("include", "semaforo", "standard"),
                                ("include", "semaforo", "unclassified"))),
    ("Solo admisibles UE", (("include", "semaforo", "eu_ok"),)),
)


def ensure_seed(db, tenant_id, actor_id: Optional[uuid.UUID] = None) -> bool:
    """Crea los perfiles sembrados si la organización no los tiene (ni siquiera archivados).
    No asigna nada. → True si creó algo (el llamador sube la versión)."""
    tid = uuid.UUID(str(tenant_id))
    if db.query(am.AccessProfile).filter_by(tenant_id=tid, seeded=True).first() is not None:
        return False
    for name, rules in SEEDS:
        p = am.AccessProfile(id=uuid.uuid4(), tenant_id=tid, kind="company", name=name, seeded=True,
                             version=1, created_by=actor_id, updated_by=actor_id)
        db.add(p)
        db.flush()
        for i, (effect, selector, value) in enumerate(rules):
            db.add(am.AccessProfileRule(profile_id=p.id, position=i, effect=effect, selector=selector,
                                        value=value))
    db.flush()
    return True


def load(db, tenant_id) -> AccessSnapshot:
    tid = uuid.UUID(str(tenant_id))
    snap = AccessSnapshot(tenant_id=str(tid))
    rows = db.query(am.AccessProfile).filter_by(tenant_id=tid).filter(
        am.AccessProfile.archived_at.is_(None)).all()
    ids = [p.id for p in rows]
    rules: dict = {}
    if ids:
        for r in (db.query(am.AccessProfileRule).filter(am.AccessProfileRule.profile_id.in_(ids))
                  .order_by(am.AccessProfileRule.position).all()):
            rules.setdefault(r.profile_id, []).append(Rule(r.effect, r.selector, r.value))
    for p in rows:
        snap.profiles[str(p.id)] = Profile(str(p.id), p.kind, p.name, tuple(rules.get(p.id, ())))
    for a in db.query(am.AccessAssignment).filter_by(tenant_id=tid).all():
        snap.assignments.setdefault((a.subject_type, str(a.subject_id)), []).append(str(a.profile_id))
    for c in db.query(am.AiActCeiling).filter_by(tenant_id=tid).all():
        snap.ceilings[c.risk_level] = str(c.profile_id)
    for k in db.query(am.AccessKeyProfile).filter_by(tenant_id=tid).all():
        snap.key_profiles[str(k.api_key_id)] = str(k.profile_id)
    return snap
