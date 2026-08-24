"""Matriz canónica rol×superficie (spec 017, FR-001/002/003) — fuente única en código.

Espejo 1:1 de ``specs/017-auth-rbac-sso/contracts/matriz-roles.md``. El harness FR-005
(``tests/integration/test_role_matrix.py``) recorre TODOS los endpoints gateados y falla si
el código diverge de esta tabla; un endpoint gateado sin superficie mapeada acá = rojo
(feature, no bug). Cambiar la matriz = cambiar el .md contrato Y este archivo en el MISMO PR.

Roles canónicos (post-013): ``super_admin``, ``tenant_admin``, ``compliance_officer``,
``client``, ``lectura`` (nuevo en 017). En C2 ``super_admin`` es operativamente equivalente a
``tenant_admin`` (su semántica cross-tenant despierta con el multi-tenant real — out of scope).
Los literales legacy de los 15 routers (``admin``, ``clinician``, ``developer``) NO se
renombran: el shim (``auth/rbac.effective_roles``) traduce el rol canónico a ellos; los labels
sectoriales siguen siendo display (D9).
"""
from enum import Enum


class Rol(str, Enum):
    SUPER_ADMIN = "super_admin"
    TENANT_ADMIN = "tenant_admin"
    COMPLIANCE_OFFICER = "compliance_officer"
    CLIENT = "client"
    LECTURA = "lectura"


class Acceso(str, Enum):
    RW = "RW"          # lee y escribe
    R = "R"            # solo lectura
    W = "W"            # solo escritura — única excepción nombrada: auditor resolviendo reviews
    PROPIO = "propio"  # solo lo suyo (client: su perfil / sus keys / su uso) — como hoy
    NINGUNO = "-"      # sin acceso (en chat_playground = 403 explícito)


# ── La matriz (por grupo de superficie) — 1:1 con contracts/matriz-roles.md ────────────
# `super_admin` ≡ `tenant_admin` en C2. El grupo agrupa routers/endpoints homogéneos; el
# mapeo endpoint→grupo lo consume el harness FR-005 (T004) y el recableado de require_role (T006).
MATRIZ: "dict[str, dict[Rol, Acceso]]" = {
    "gestion_iam": {  # users, keys, groups
        Rol.SUPER_ADMIN: Acceso.RW, Rol.TENANT_ADMIN: Acceso.RW,
        Rol.COMPLIANCE_OFFICER: Acceso.R, Rol.CLIENT: Acceso.PROPIO, Rol.LECTURA: Acceso.NINGUNO,
    },
    "config_producto": {  # guardians, policy, router_config, governance, budgets
        Rol.SUPER_ADMIN: Acceso.RW, Rol.TENANT_ADMIN: Acceso.RW,
        Rol.COMPLIANCE_OFFICER: Acceso.R, Rol.CLIENT: Acceso.NINGUNO, Rol.LECTURA: Acceso.NINGUNO,
    },
    "compliance_config": {  # retention (FR-009 018), security policies, consent admin
        Rol.SUPER_ADMIN: Acceso.RW, Rol.TENANT_ADMIN: Acceso.RW,
        Rol.COMPLIANCE_OFFICER: Acceso.R, Rol.CLIENT: Acceso.NINGUNO, Rol.LECTURA: Acceso.NINGUNO,
    },
    "artefactos_compliance": {  # projects, DPAs, DSRs
        Rol.SUPER_ADMIN: Acceso.RW, Rol.TENANT_ADMIN: Acceso.RW,
        Rol.COMPLIANCE_OFFICER: Acceso.R, Rol.CLIENT: Acceso.NINGUNO, Rol.LECTURA: Acceso.NINGUNO,
    },
    "human_reviews_resolver": {  # aprobar/rechazar — única escritura del auditor, nombrada
        Rol.SUPER_ADMIN: Acceso.RW, Rol.TENANT_ADMIN: Acceso.RW,
        Rol.COMPLIANCE_OFFICER: Acceso.W, Rol.CLIENT: Acceso.NINGUNO, Rol.LECTURA: Acceso.NINGUNO,
    },
    "vitrinas_lectura": {  # audit, monitor, reports, costs-read, health detallado
        Rol.SUPER_ADMIN: Acceso.R, Rol.TENANT_ADMIN: Acceso.R,
        Rol.COMPLIANCE_OFFICER: Acceso.R, Rol.CLIENT: Acceso.PROPIO, Rol.LECTURA: Acceso.R,
    },
    "costs_config": {  # budgets write, compression por grupo
        Rol.SUPER_ADMIN: Acceso.RW, Rol.TENANT_ADMIN: Acceso.RW,
        Rol.COMPLIANCE_OFFICER: Acceso.R, Rol.CLIENT: Acceso.NINGUNO, Rol.LECTURA: Acceso.NINGUNO,
    },
    "chat_playground": {  # POST /chat/completions camino JWT (FR-003: el JWT gatea rol — activo desde T010)
        Rol.SUPER_ADMIN: Acceso.RW, Rol.TENANT_ADMIN: Acceso.RW,
        Rol.COMPLIANCE_OFFICER: Acceso.RW, Rol.CLIENT: Acceso.RW, Rol.LECTURA: Acceso.NINGUNO,  # 403
    },
}


def _acceso(rol: Rol, grupo: str) -> Acceso:
    return MATRIZ[grupo].get(rol, Acceso.NINGUNO)


def puede_escribir(rol: Rol, grupo: str) -> bool:
    return _acceso(rol, grupo) in (Acceso.RW, Acceso.W)


def puede_leer(rol: Rol, grupo: str) -> bool:
    return _acceso(rol, grupo) in (Acceso.RW, Acceso.R, Acceso.W, Acceso.PROPIO)


def roles_con_escritura(grupo: str) -> "set[Rol]":
    """Roles habilitados a MUTAR el grupo — lo que un `require_role` de mutación debe permitir."""
    return {r for r, a in MATRIZ[grupo].items() if a in (Acceso.RW, Acceso.W)}


def roles_con_lectura(grupo: str) -> "set[Rol]":
    """Roles habilitados a LEER el grupo — lo que un `require_role` de lectura debe permitir
    (excluye `PROPIO`: ése no es acceso al grupo entero sino a lo propio del `client`)."""
    return {r for r, a in MATRIZ[grupo].items() if a in (Acceso.RW, Acceso.R, Acceso.W)}
