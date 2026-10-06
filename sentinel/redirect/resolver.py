"""Resolver puro de la política (data-model §0/§1/§4/§5; research D1; FR-001…011).

Entradas: dicts planos (filas ya leídas por el llamador). Sin I/O, sin reloj, sin azar:
mismo input ⇒ mismo resultado en pasarela, vista previa y sombra.

Orden de reglas (data-model §5): 1) alcance más específico → 2) regla con `request_class`
informada → 3) regla general → 4) por tier → 5) sin regla ⇒ «modelo no disponible».
Decisión de implementación: las reglas atadas al id publicado se agotan en todos los alcances
antes de caer a las reglas por tier (una regla por id es más específica que una por tier).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Optional

from . import credentials, residency
from .scopes import RequestScope, applicable, most_specific, scope_key

STATES = ("off", "shadow", "on")
FACES = ("claude", "codex", "openai_generic")
REQUEST_CLASSES = ("main", "subagent", "workflow", "compaction", "auxiliary")
NATIVE_FAMILIES = {
    "claude": frozenset({"anthropic_messages"}),
    "codex": frozenset({"openai_responses"}),
    "openai_generic": frozenset({"openai_chat", "openai_responses"}),
}
STRATEGIES = ("order", "cheapest")
_RESIDENCY_REASONS = frozenset({"residency", "foreign_entity"})


@dataclass(frozen=True)
class Resolved:
    published: dict
    rule_id: Any
    destination: dict
    target_index: int
    engine_model: str
    fidelity: str                       # native | translated
    forced_masking: bool
    residency_mode: str
    jurisdiction_served: Optional[str]
    substitution_reason: Optional[str]  # None | fallback_unavailable | residency | offer_withdrawn | cost_ordering
    skipped: tuple = ()                 # ((destination_id, reason), ...)
    # Destinos elegibles que siguen al elegido, en el orden de la regla (069 FR-008b): si el pedido
    # necesita una capacidad que el elegido no tiene, se pasa al siguiente que sí la tenga.
    alternatives: tuple = ()            # (Alternative, ...)
    strategy: str = "order"             # estrategia de la regla (069 US10): order | cheapest


@dataclass(frozen=True)
class Alternative:
    destination: dict
    engine_model: str
    fidelity: str
    forced_masking: bool
    residency_mode: str
    jurisdiction_served: Optional[str]
    target_index: int


@dataclass(frozen=True)
class Unavailable:
    kind: str                           # not_published | no_rule | no_eligible_target
    error_class: str                    # unavailable (404) | residency (403) | not_allowed (403)
    skipped: tuple = ()
    published: Optional[dict] = None
    rule_id: Any = None


def effective_state(policy_rows: Iterable[Mapping[str, Any]], scope: RequestScope) -> str:
    row = most_specific(policy_rows, scope)
    if row is None:
        return "off"
    state = row.get("state")
    if state not in STATES:
        raise ValueError(f"estado de política desconocido: {state!r}")
    return state


def published_models(rows: Iterable[Mapping[str, Any]], scope: RequestScope,
                     face: Optional[str] = None) -> list:
    """Unión de alcances; para un mismo (cara, id) gana el más específico. Orden por (cara, id)."""
    chosen: dict = {}
    for r in applicable(rows, scope):          # ya viene de más a menos específico
        if face is not None and r.get("face") != face:
            continue
        chosen.setdefault((r.get("face"), r.get("public_id")), dict(r))
    return [chosen[k] for k in sorted(chosen, key=lambda k: (str(k[0]), str(k[1])))]


def find_published(rows, scope: RequestScope, face: str, public_id: str) -> Optional[dict]:
    for r in published_models(rows, scope, face):
        if r.get("public_id") == public_id:
            return r
    return None


def select_rule(rules: Iterable[Mapping[str, Any]], scope: RequestScope, *,
                published_model_id: Any, family_tier: Optional[str],
                request_class: Optional[str]) -> Optional[dict]:
    rules = applicable(rules, scope)

    def pick(candidates):
        # alcance más específico primero; dentro del mismo alcance, clase informada > general
        best, best_key = None, None
        for idx, r in enumerate(candidates):
            rc = r.get("request_class")
            if rc is not None and rc != request_class:
                continue
            key = (scope_key(r, scope), 0 if rc is not None else 1, idx)
            if best_key is None or key < best_key:
                best, best_key = r, key
        return best

    by_id = [r for r in rules if published_model_id is not None
             and r.get("published_model_id") == published_model_id]
    found = pick(by_id)
    if found is None and family_tier:
        by_tier = [r for r in rules if r.get("published_model_id") is None
                   and r.get("family_tier") == family_tier]
        found = pick(by_tier)
    return dict(found) if found is not None else None


def _offer_for(dest: Mapping[str, Any], offers: Iterable[Mapping[str, Any]], tenant_id: str):
    for o in offers:
        if o.get("destination_id") == dest.get("id") and o.get("tenant_id") in ("*", tenant_id):
            return o
    return None


def check_target(dest: Optional[Mapping[str, Any]], offers: Iterable[Mapping[str, Any]],
                 scope: RequestScope, posture: residency.Posture,
                 permitidos: Optional[frozenset] = None):
    """→ (None, ResidencyDecision) si es elegible; (motivo, None) si no.

    `permitidos` (069 US2): `public_id` del catálogo que el perfil efectivo permite; `None` = ninguna
    política restringe. Un destino fuera del conjunto (o sin `public_id`) se salta con
    `profile_not_allowed`. Sigue siendo puro: el conjunto lo calcula el llamador."""
    if dest is None:
        return "not_found", None
    offer = None
    if dest.get("level") == "installation":
        offer = _offer_for(dest, offers, scope.tenant_id)
        if offer is None:
            return "not_offered", None
    elif dest.get("tenant_id") != scope.tenant_id:
        return "not_found", None               # BYOK de otro tenant: invisible, no «ajeno»
    if dest.get("role", "text") != "text":
        return "not_found", None               # entrada de embeddings/imagen/audio: no es un destino de chat
    if permitidos is not None and dest.get("public_id") not in permitidos:
        return "profile_not_allowed", None
    status = dest.get("status")
    if status != "active":
        return (status if status in ("inactive", "revoked") else "inactive"), None
    if dest.get("blocked_by_default") and not (dest.get("enabled_at") or (offer or {}).get("enabled_at")):
        return "blocked_by_default", None
    provider = dest.get("provider")
    if provider not in credentials.PROVIDER_FAMILY:
        return "not_found", None
    if credentials.requires_secret(provider) and not dest.get("has_credential"):
        return "no_credential", None
    if credentials.requires_api_base(provider) and not dest.get("api_base"):
        return "no_credential", None
    decision = residency.evaluate(posture, dest)
    if not decision.allowed:
        return decision.reason, None
    return None, decision


def _substitution_reason(skipped: tuple) -> Optional[str]:
    if not skipped:
        return None
    first = skipped[0][1]
    if first in _RESIDENCY_REASONS:
        return "residency"
    if first == "not_offered":
        return "offer_withdrawn"
    return "fallback_unavailable"


def estimated_cost(dest: Mapping[str, Any]) -> Optional[float]:
    """Costo estimado por millón de tokens (entrada + salida, USD) o `None` si el destino no tiene precio."""
    price = dest.get("price_override")
    if not isinstance(price, Mapping):
        return None
    try:
        return float(price["input_per_mtok"]) + float(price["output_per_mtok"])
    except (KeyError, TypeError, ValueError):
        return None


def _cost_key(dest: Mapping[str, Any], idx: int) -> tuple:
    """Más barato primero; sin precio al final; empate ⇒ orden de la regla (069 US10, FR-056)."""
    cost = estimated_cost(dest)
    return (cost is None, cost or 0.0, idx)


def fidelity(face: str, destination: Mapping[str, Any]) -> str:
    return "native" if destination.get("protocol_family") in NATIVE_FAMILIES.get(face, ()) else "translated"


def resolve(*, scope: RequestScope, face: str, public_id: str, request_class: Optional[str],
            published_rows: Iterable[Mapping[str, Any]], rules: Iterable[Mapping[str, Any]],
            destinations: Mapping[Any, Mapping[str, Any]], offers: Iterable[Mapping[str, Any]],
            posture: residency.Posture, permitidos: Optional[frozenset] = None):
    """`posture` = `residency.effective_posture(..., redirected=True, ...)`, la calcula el llamador.
    `permitidos`: ver `check_target`; si TODOS los destinos se saltan por perfil ⇒ `not_allowed`."""
    published = find_published(published_rows, scope, face, public_id)
    if published is None:
        return Unavailable(kind="not_published", error_class="unavailable")
    rc = request_class if request_class in REQUEST_CLASSES else None
    rule = select_rule(rules, scope, published_model_id=published.get("id"),
                       family_tier=published.get("family_tier"), request_class=rc)
    if rule is None:
        return Unavailable(kind="no_rule", error_class="unavailable", published=published)
    offers = list(offers)
    skipped = []
    eligible = []                       # [(idx, dest, model, decision)] en el orden de la regla
    for idx, dest_id in enumerate(rule.get("targets") or ()):
        dest = destinations.get(dest_id)
        reason, decision = check_target(dest, offers, scope, posture, permitidos)
        if reason is not None:
            if not eligible:
                skipped.append((dest_id, reason))
            continue
        dest = dict(dest)
        eligible.append((idx, dest, credentials.family_model(dest["provider"], dest["real_model"]), decision))
    if eligible:
        reason = _substitution_reason(tuple(skipped))
        if rule.get("strategy") == "cheapest":
            ordered = sorted(eligible, key=lambda e: _cost_key(e[1], e[0]))
            if ordered[0][0] != eligible[0][0] and reason is None:
                reason = "cost_ordering"
            eligible = ordered
        idx, dest, model, decision = eligible[0]
        first = Resolved(
            published=published, rule_id=rule.get("id"), destination=dest, target_index=idx,
            engine_model=model, fidelity=fidelity(face, dest),
            forced_masking=decision.forced_masking, residency_mode=decision.mode,
            jurisdiction_served=decision.jurisdiction_served,
            substitution_reason=reason, skipped=tuple(skipped),
            strategy="cheapest" if rule.get("strategy") == "cheapest" else "order")
        alternatives = [Alternative(d, mdl, fidelity(face, d), dec.forced_masking, dec.mode,
                                    dec.jurisdiction_served, i) for i, d, mdl, dec in eligible[1:]]
        return replace(first, alternatives=tuple(alternatives)) if alternatives else first
    all_residency = bool(skipped) and all(r in _RESIDENCY_REASONS for _, r in skipped)
    all_profile = bool(skipped) and all(r == "profile_not_allowed" for _, r in skipped)
    return Unavailable(kind="no_eligible_target",
                       error_class="residency" if all_residency else
                       "not_allowed" if all_profile else "unavailable",
                       skipped=tuple(skipped), published=published, rule_id=rule.get("id"))
