"""Tests de la cascada de defaults de contexto (spec 013 US4, SC-007, FR-022).

Unit tests puros (sin DB): la resolución vive en servicio, no en DB. Los 3 casos por
campo: hereda del tenant, hereda del group (más específico), override del user gana.
"""
import uuid

from src.models.compliance import ComplianceProject  # noqa: F401 — registra FKs
from src.models.tenant import Tenant
from src.models.user import Group, User
from src.services.context_resolution import resolve_context_defaults

PROJECT_TENANT = uuid.uuid4()
PROJECT_GROUP = uuid.uuid4()
PROJECT_USER = uuid.uuid4()


def _tenant():
    return Tenant(
        name="T", slug="t",
        default_legal_basis="consent",
        default_risk_level="minimal",
        default_compliance_project_id=PROJECT_TENANT,
    )


def test_inherits_from_tenant_when_no_group_or_user_override():
    user = User(username="u", email="u@t", password_hash="x", role="client")
    group = Group(name="g")  # sin defaults propios
    resolved = resolve_context_defaults(user=user, group=group, tenant=_tenant())

    assert resolved.legal_basis == "consent"
    assert resolved.risk_level == "minimal"
    assert resolved.compliance_project_id == PROJECT_TENANT


def test_group_default_beats_tenant():
    user = User(username="u", email="u@t", password_hash="x", role="client")
    group = Group(
        name="g",
        default_legal_basis="contract",
        default_risk_level="high_risk_annex3",
        compliance_project_id=PROJECT_GROUP,
    )
    resolved = resolve_context_defaults(user=user, group=group, tenant=_tenant())

    assert resolved.legal_basis == "contract"
    assert resolved.risk_level == "high_risk_annex3"
    assert resolved.compliance_project_id == PROJECT_GROUP


def test_user_override_beats_group_and_tenant():
    user = User(
        username="u", email="u@t", password_hash="x", role="client",
        legal_basis="legitimate_interest",
        risk_level="limited",
        compliance_project_id=PROJECT_USER,
    )
    group = Group(name="g", default_legal_basis="contract",
                  compliance_project_id=PROJECT_GROUP)
    resolved = resolve_context_defaults(user=user, group=group, tenant=_tenant())

    assert resolved.legal_basis == "legitimate_interest"
    assert resolved.risk_level == "limited"
    assert resolved.compliance_project_id == PROJECT_USER


def test_partial_overrides_resolve_per_field():
    """La precedencia es POR CAMPO: un user puede overridear solo legal_basis y
    seguir heredando risk_level del group y el proyecto del tenant."""
    user = User(username="u", email="u@t", password_hash="x", role="client",
                legal_basis="vital_interest")
    group = Group(name="g", default_risk_level="high_risk_annex3")
    resolved = resolve_context_defaults(user=user, group=group, tenant=_tenant())

    assert resolved.legal_basis == "vital_interest"       # override user
    assert resolved.risk_level == "high_risk_annex3"      # hereda group
    assert resolved.compliance_project_id == PROJECT_TENANT  # hereda tenant


def test_missing_layers_do_not_explode():
    resolved = resolve_context_defaults(user=None, group=None, tenant=None)
    assert resolved.legal_basis is None
    assert resolved.risk_level is None
    assert resolved.compliance_project_id is None
