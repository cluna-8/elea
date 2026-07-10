"""Cascada de defaults de contexto (spec 013 US4, FR-022).

Resuelve los defaults de contexto legal —``legal_basis``, ``risk_level``,
``compliance_project_id``— con precedencia **Client(User) > Group > Tenant**,
reutilizando el patrón override heredado (``User.legal_basis`` >
``Group.default_legal_basis``) y elevando ``Tenant`` como raíz.

Alcance 013: SOLO estos 3 defaults de contexto. La cascada de
``SecurityPolicy``/``entity_configs`` por capa es spec 015.
"""
from dataclasses import dataclass
from typing import Optional
from uuid import UUID


@dataclass(frozen=True)
class ResolvedContext:
    legal_basis: Optional[str]
    risk_level: Optional[str]
    compliance_project_id: Optional[UUID]


def _first_not_none(*values):
    for value in values:
        if value is not None:
            return value
    return None


def resolve_connection_toggles(key, group=None, tenant=None) -> dict:
    """Toggles operativos por Connection (spec 013 US5, FR-014): NULL = heredar,
    valor = override. NUNCA se confunde "no seteado" con "apagado".

    - ``redact_enabled``: sin override manda la política de masking vigente
      (masking-first, Principio I) → heredado = True hoy; el scope fino por
      group/policy es spec 015.
    - ``compression_mode``: hereda Group → Tenant → 'off'.
    - ``allowed_models`` / ``allowed_tools``: None = sin restricción propia (hereda).
    """
    return {
        "redact_enabled": key.redact_enabled if key.redact_enabled is not None else True,
        "compression_mode": _first_not_none(
            key.compression_mode,
            getattr(group, "compression_mode", None),
            getattr(tenant, "compression_mode", None),
            "off",
        ),
        "allowed_models": key.allowed_models,
        "allowed_tools": key.allowed_tools,
    }


def resolve_context_defaults(user=None, group=None, tenant=None) -> ResolvedContext:
    """Valor efectivo por campo: el override del User gana; si no, el default del
    Group; si no, el default del Tenant; si no, None.

    Los argumentos son opcionales para tolerar clients sin grupo o resoluciones
    parciales; la resolución vive en servicio, no en DB (decisión del plan 013).
    """
    return ResolvedContext(
        legal_basis=_first_not_none(
            getattr(user, "legal_basis", None),
            getattr(group, "default_legal_basis", None),
            getattr(tenant, "default_legal_basis", None),
        ),
        risk_level=_first_not_none(
            getattr(user, "risk_level", None),
            getattr(group, "default_risk_level", None),
            getattr(tenant, "default_risk_level", None),
        ),
        compliance_project_id=_first_not_none(
            getattr(user, "compliance_project_id", None),
            getattr(group, "compliance_project_id", None),
            getattr(tenant, "default_compliance_project_id", None),
        ),
    )
