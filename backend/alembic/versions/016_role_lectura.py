"""rol `lectura` (spec 017 FR-003): amplía el CHECK ck_users_role al quinto rol canónico.

Contexto (matriz 017, contracts/matriz-roles.md): `lectura` es un rol de SOLO-VITRINA — lee
`vitrinas_lectura` (audit, reports, costs-read) y NADA más: sin chat (403 explícito), sin
gestión, sin config de producto, sin asiento (seat) ni prueba de dueño. El vocabulario lo
sostiene el mismo `CHECK (role IN (...))` que nació en la 010; esta migración lo REEMPLAZA
sumando el literal, espejo del `VALID_ROLES`/`CheckConstraint` del modelo (models/user.py) que
cambian en el MISMO PR (Regla 2 del contrato: paquete acoplado).

Por qué DROP + ADD y no un ALTER in-place: Postgres no permite editar el predicado de un CHECK;
el patrón idempotente (DROP IF EXISTS + ADD) es EXACTAMENTE el que la 010 usa para este mismo
constraint (010:181-185), así que ORM y esquema real no divergen.

Seguridad para installs con datos: es puramente AMPLIATORIA (agrega un valor permitido; no
reescribe filas ni toca datos), así que ninguna fila existente puede violar el CHECK nuevo.

⚠ Espejo del motor (custom_auth.py, `_IDENTITY_SQL`): el `u.role` que resuelve el plano interno
(`api/internal.py`) YA viaja el rol tal cual, así que un `lectura` fluye sin cambio de SQL. El
gate de que `lectura` no consuma inferencia byok vive en el motor (T024/#137, BLOQUEADA): esta
migración NO lo toca. El camino JWT del Playground lo gatea T010.

Revision ID: 016
Revises: 015
Create Date: 2026-08-21
"""
from alembic import op

revision = '016'
down_revision = '015'
branch_labels = None
depends_on = None

_ROLES_CON_LECTURA = "('super_admin', 'tenant_admin', 'compliance_officer', 'client', 'lectura')"
_ROLES_SIN_LECTURA = "('super_admin', 'tenant_admin', 'compliance_officer', 'client')"


def _set_check(valores: str) -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_role")
    op.execute(f"""
        ALTER TABLE users ADD CONSTRAINT ck_users_role
        CHECK (role IN {valores})
    """)


def upgrade():
    _set_check(_ROLES_CON_LECTURA)


def downgrade():
    # Reversión al vocabulario de 4 roles. Si la instalación ya tiene usuarios `lectura`, el
    # ADD del CHECK viejo FALLA por diseño (la fila violaría el predicado): revertir el rol exige
    # antes migrar/borrar esas filas — no se hace en silencio.
    _set_check(_ROLES_SIN_LECTURA)
