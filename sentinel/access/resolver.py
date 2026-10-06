"""Resolutor único de modelos permitidos (069 research D6/D7; FR-010…FR-014a). FUNCIÓN PURA.

    permitidos = (∪ perfiles de empresa de la PRIMERA capa no vacía: usuario → grupo → organización)
                 ∩ techo(riesgo efectivo) ∩ perfil de la llave

- **Perfil** = las entradas que cumplen algún `include`, menos las que cumplen algún `exclude`;
  sin ningún `include` ⇒ vacío.
- **Sin perfiles de empresa en ninguna capa** ⇒ la empresa no restringe (rige solo el techo).
- **Techo**: el perfil `ceiling` del nivel de riesgo efectivo. Sin techo definido para ese nivel ⇒ no
  restringe. El riesgo efectivo es el MÁS ESTRICTO entre el del usuario (ya resuelto usuario → grupo →
  organización) y el de la llave: la clasificación de la llave solo endurece. Orden de rigor:
  `minimal < limited < high_risk_annex3 < high_risk_annex1` (Anexo I, productos regulados, es el más
  estricto; ambos «alto riesgo» superan a limitado). Riesgo del usuario vacío o desconocido ⇒ el techo
  MÁS ESTRICTO: la intersección de todos los techos definidos (si no hay ninguno ⇒ sin techo). El
  riesgo de la llave vacío = la llave no clasifica (no endurece); uno no vacío y desconocido ⇒ también
  el techo más estricto.
- **Perfil de llave**: solo achica (∩).
- Datos inconsistentes (perfil asignado que no existe, etc.) ⇒ `PermitidosNoResueltos`: jamás
  «vacío = todo».
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

from sentinel.redirect.residency import satisfies

# De menos a más estricto.
RISK_ORDER = ("minimal", "limited", "high_risk_annex3", "high_risk_annex1")
LAYERS = ("user", "group", "tenant")


class PermitidosNoResueltos(Exception):
    """No se pudo decidir qué modelos están permitidos: el pedido se rechaza (FR-014a)."""


@dataclass(frozen=True)
class Rule:
    effect: str
    selector: str
    value: str


@dataclass(frozen=True)
class Profile:
    id: str
    kind: str
    name: str
    rules: tuple = ()


@dataclass
class AccessSnapshot:
    """Instantánea por organización. `assignments`: `(subject_type, subject_id) → [profile_id]`;
    `ceilings`: `risk_level → profile_id`; `key_profiles`: `key_id → profile_id`."""
    tenant_id: str
    profiles: dict = field(default_factory=dict)
    assignments: dict = field(default_factory=dict)
    ceilings: dict = field(default_factory=dict)
    key_profiles: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Permitidos:
    ids: frozenset
    restringe: bool
    techo: dict
    perfiles: tuple
    llave: dict


def strictness(risk: Optional[str]) -> Optional[int]:
    return RISK_ORDER.index(risk) if risk in RISK_ORDER else None


def _matches(rule: Rule, entry: Mapping[str, Any]) -> bool:
    v = rule.value
    if rule.selector == "semaforo":
        return (entry.get("semaforo") or {}).get("estado") == v
    if rule.selector == "jurisdiccion":
        return satisfies(entry.get("jurisdiccion"), {v})
    if rule.selector == "proveedor":
        return entry.get("provider") == v
    if rule.selector == "capacidad":
        return entry.get("capability") == v
    if rule.selector == "entrada":
        return v in (str(entry.get("public_id")), str(entry.get("id")))
    raise PermitidosNoResueltos(f"selector desconocido: {rule.selector!r}")


def evaluate_profile(profile: Profile, entries: Iterable[Mapping[str, Any]]) -> frozenset:
    """Ids (`public_id`) de las entradas que el perfil permite."""
    inc = [r for r in profile.rules if r.effect == "include"]
    exc = [r for r in profile.rules if r.effect == "exclude"]
    out = set()
    for e in entries:
        if any(_matches(r, e) for r in inc) and not any(_matches(r, e) for r in exc):
            out.add(e["public_id"])
    return frozenset(out)


def _profile(snap: AccessSnapshot, pid, kind: str) -> Profile:
    p = snap.profiles.get(str(pid))
    if p is None or p.kind != kind:
        raise PermitidosNoResueltos(f"perfil {pid} inexistente o de otro tipo")
    return p


def _company_layer(snap, *, user_id, group_id):
    """(origen, [perfiles]) de la primera capa no vacía, o (None, [])."""
    for origin, sid in (("user", user_id), ("group", group_id), ("tenant", snap.tenant_id)):
        if sid is None:
            continue
        ids = snap.assignments.get((origin, str(sid))) or []
        if ids:
            return origin, [_profile(snap, i, "company") for i in ids]
    return None, []


def effective_risk_level(user_risk: Optional[str], key_risk: Optional[str]):
    """→ `(nivel | None, origen)`. `None` = desconocido ⇒ techo más estricto. `origen`:
    `user` | `key` (la llave endureció) | `desconocido`."""
    u = strictness(user_risk)
    if u is None:
        return None, "desconocido"
    if not key_risk:
        return RISK_ORDER[u], "user"
    k = strictness(key_risk)
    if k is None:
        return None, "desconocido"
    return (RISK_ORDER[k], "key") if k > u else (RISK_ORDER[u], "user")


def modelos_permitidos(snapshot: AccessSnapshot, entries: Iterable[Mapping[str, Any]], *,
                       user_id=None, group_id=None, key_id=None, user_risk: Optional[str] = None,
                       key_risk: Optional[str] = None) -> Permitidos:
    entries = list(entries)
    todos = frozenset(e["public_id"] for e in entries)
    allowed = todos
    restringe = False

    # 1) empresa
    origin, profs = _company_layer(snapshot, user_id=user_id, group_id=group_id)
    perfiles = ()
    if profs:
        restringe = True
        union = frozenset().union(*(evaluate_profile(p, entries) for p in profs))
        allowed &= union
        perfiles = tuple({"id": p.id, "name": p.name, "origen": origin} for p in profs)

    # 2) techo por riesgo
    level, riesgo_origen = effective_risk_level(user_risk, key_risk)
    if level is not None:
        pids = [snapshot.ceilings[level]] if level in snapshot.ceilings else []
    else:
        pids = list(snapshot.ceilings.values())       # desconocido ⇒ todos los techos definidos (∩)
    techo = {"risk_level": level, "origen": riesgo_origen if pids else "sin_techo", "count": None}
    if pids:
        restringe = True
        ceil = todos
        for pid in pids:
            ceil &= evaluate_profile(_profile(snapshot, pid, "ceiling"), entries)
        allowed &= ceil
        techo["count"] = len(ceil)

    # 3) perfil de la llave (solo achica)
    llave = {"profile_id": None}
    kp = snapshot.key_profiles.get(str(key_id)) if key_id is not None else None
    if kp is not None:
        restringe = True
        allowed &= evaluate_profile(_profile(snapshot, kp, "key"), entries)
        llave = {"profile_id": str(kp)}

    return Permitidos(ids=allowed if restringe else todos, restringe=restringe, techo=techo,
                      perfiles=perfiles, llave=llave)
