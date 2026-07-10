"""Tests del shim de compatibilidad RBAC post-013 (SC-002, cero regresión).

Los gates de la API siguen escritos con nombres legacy ('admin', 'developer'…);
el shim expande el rol canónico del usuario migrado a sus equivalentes hasta el
refactor RBAC definitivo (spec 017). Unit tests puros, sin DB.
"""
import pytest

from src.auth.rbac import effective_roles
from src.models.user import User, normalize_legacy_role


def _user(role, display_label=None):
    return User(username="u", email="u@t", password_hash="x",
                role=role, display_label=display_label)


def test_tenant_admin_keeps_legacy_admin_gates():
    assert "admin" in effective_roles(_user("tenant_admin"))


def test_super_admin_passes_admin_gates():
    assert "admin" in effective_roles(_user("super_admin"))


def test_migrated_developer_keeps_key_management():
    """developer→client+label conserva sus permisos legacy (create_key/revoke_key)."""
    roles = effective_roles(_user("client", display_label="developer"))
    assert "developer" in roles and "client" in roles


def test_migrated_clinician_keeps_review_access():
    roles = effective_roles(_user("client", display_label="clinician"))
    assert "clinician" in roles


def test_plain_client_gets_no_legacy_expansion():
    assert effective_roles(_user("client")) == {"client"}
    assert effective_roles(_user("client", display_label="hacker")) == {"client"}


def test_compliance_officer_unchanged():
    assert effective_roles(_user("compliance_officer")) == {"compliance_officer"}


def test_normalize_legacy_role_mapping():
    assert normalize_legacy_role("admin") == ("tenant_admin", None)
    assert normalize_legacy_role("clinician") == ("client", "clinician")
    assert normalize_legacy_role("developer") == ("client", "developer")
    assert normalize_legacy_role("tenant_admin") == ("tenant_admin", None)
    assert normalize_legacy_role("client", "vendedor") == ("client", "vendedor")


def test_normalize_rejects_unknown_roles():
    with pytest.raises(ValueError, match="inválido"):
        normalize_legacy_role("hacker")
