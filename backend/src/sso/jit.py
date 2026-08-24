"""Aprovisionamiento JIT por email (spec 017 US2, FR-008).

Traduce una ``Identity`` verificada por el IdP a un ``User`` local. Tres caminos
nombrados por la spec (:78-79, :144) y UNO más que la spec no nombra y acá se
cierra explícitamente:

1. **Centinela** — existe un User sembrado con ``!seeded-client-no-login``: se ACTIVA
   ese mismo User. Sin duplicar y **sin pasar por el seat gate** (ya existe: no hay
   seat nuevo que licenciar).
2. **Nuevo** — no hay User con ese email: alta ``role='client'`` por el MISMO camino
   de alta actual, **seat gate incluido** (espeja ``api/users.create_user``).
3. **Activo** — existe y puede operar: sólo login. No se toca NADA de la fila.
4. **Inactivo NO centinela** — existe pero ``is_active=False`` y su hash no es el
   centinela: **rechazo**. La spec no lo nombra; fail-closed es la única lectura
   segura. Un admin que desactiva a alguien lo desactiva de verdad; si SSO
   reactivara, el IdP sería un bypass de la baja local (escalada por la puerta de
   atrás). Sólo el centinela —que nace inerte a propósito— habilita activación.

**El invariante que manda (FR-008, spec:121): JAMÁS se re-asigna rol ni tenant.**
Ningún camino de este módulo escribe ``User.role`` ni ``User.tenant_id`` sobre una
fila existente. Venir de Entra no promueve a nadie: si el admin local puso
``lectura``, sigue ``lectura`` aunque el IdP lo llame como lo llame.

**Matching por email SIEMPRE acotado al tenant** (``uq_users_tenant_email``): el email
es único POR tenant, no global. Un match sin filtro de tenant sería un cruce.

Concurrencia (precedente ``api/users.login``): todas las fases DB son sync y se
invocan desde el handler async vía ``run_in_threadpool``; la conexión JAMÁS se
retiene a través del await de red al motor (P1 #238).
"""
import logging
import uuid
from typing import Optional

from fastapi import HTTPException, status

from ..licensing.gate import enforce_seat_gate
from ..models.user import User
from ..services.onboarding import _SEEDED_PASSWORD_SENTINEL

logger = logging.getLogger("basa-secure-gateway.sso.jit")

# Password de las identidades nacidas por SSO: su credencial vive en el IdP, no acá.
# Es un literal que NO es bcrypt ni sha256-legacy, así que ``verify_password`` devuelve
# False para SIEMPRE (passwords.py:70-73) — ninguna contraseña puede loguearlas por el
# camino local. Además evita quemar bcrypt en el alta (issue #239): no hay secreto que
# hashear, así que tampoco hay hash que computar.
SSO_PASSWORD_SENTINEL = "!sso-no-password"

# Rol de toda identidad aprovisionada por SSO. NUNCA se deriva de claims del IdP:
# el mapeo grupos-IdP→roles está anotado como futuro NO comprometido
# (contracts/proveedor-sso.md:39). Un claim no promueve.
JIT_DEFAULT_ROLE = "client"


class JitRechazado(HTTPException):
    """La identidad es válida para el IdP pero no puede operar acá."""

    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _es_centinela(user: User) -> bool:
    """¿Es un sembrado inerte, elegible para activarse por SSO?

    Compara contra el literal de ``onboarding`` (importado, no copiado: dos
    definiciones del mismo centinela son dos oportunidades de que una se olvide —
    misma razón que ``api/internal.py:37``).
    """
    return user.password_hash == _SEEDED_PASSWORD_SENTINEL


def buscar_por_email(db, email: str, tenant_id) -> Optional[User]:
    """User de ESTE tenant con ese email, o None. Fase DB sync (threadpool).

    El filtro por tenant no es decorativo: ``uq_users_tenant_email`` hace único el
    email POR tenant, así que sin él un email repetido entre tenants devolvería una
    fila ajena y el SSO del tenant A emitiría sesión sobre el User de B.
    """
    if isinstance(tenant_id, str):
        tenant_id = uuid.UUID(tenant_id)
    return (
        db.query(User)
        .filter(User.tenant_id == tenant_id, User.email == email)
        .first()
    )


def resolver_existente(db, user: User) -> User:
    """Caminos 1/3/4 sobre una fila que YA existe. Fase DB sync (threadpool).

    Devuelve el User habilitado a recibir sesión, o levanta ``JitRechazado``.
    NO toca ``role`` ni ``tenant_id`` en ninguna rama — ese es el invariante FR-008.
    """
    if user.is_active:
        # Camino 3 — activo: sólo login. Cero escrituras: no hay nada que reconciliar
        # y cualquier UPDATE acá sería una vía para que el IdP mute estado local.
        return user

    if _es_centinela(user):
        # Camino 1 — centinela: se activa ESTE User (sin duplicar, sin seat gate).
        # Único UPDATE que este módulo hace sobre una fila preexistente, y toca
        # exclusivamente ``is_active``. El hash centinela se DEJA como está: la
        # identidad la sigue custodiando el IdP y el login local debe seguir siendo
        # imposible para esta fila.
        user.is_active = True
        db.flush()
        logger.info("sso jit: centinela activado (user=%s tenant=%s)", user.id, user.tenant_id)
        return user

    # Camino 4 — inactivo y NO centinela: baja administrativa deliberada. Fail-closed.
    logger.warning(
        "sso jit: identidad rechazada — User inactivo no centinela (user=%s tenant=%s)",
        user.id, user.tenant_id,
    )
    raise JitRechazado(
        "sso_usuario_inactivo: la cuenta local está desactivada; "
        "el acceso por SSO no reactiva una baja administrativa."
    )


def _username_para(email: str, display_name: str) -> str:
    """Username de una identidad nueva. Determinístico y derivado del email.

    El email es la clave natural del matching (FR-008); usarlo también como username
    mantiene UNA sola identidad natural por fila. ``display_name`` del IdP va a
    ``display_label``, que es display y no participa de ninguna unicidad.
    """
    return email


def crear_jit(db, *, email: str, display_name: str, tenant_id) -> User:
    """Camino 2 — alta nueva. Fase DB sync (threadpool), SIN commit.

    Espeja ``api/users.create_user``: seat gate ANTES de insertar (sólo los ``client``
    son seats, spec 021 FR-009) y rol fijo ``client``. El caller commitea y provisiona
    en el motor DESPUÉS, fuera de esta fase.
    """
    if isinstance(tenant_id, str):
        tenant_id = uuid.UUID(tenant_id)

    # Gate de licencia ANTES de crear la fila (mismo orden que el alta por UI:
    # una identidad nueva por SSO consume seat igual que un alta manual, y sin
    # licencia no se crea). Levanta 402/403 desde ``licensing.gate``.
    enforce_seat_gate(db, tenant_id=tenant_id)

    user = User(
        tenant_id=tenant_id,
        username=_username_para(email, display_name),
        email=email,
        password_hash=SSO_PASSWORD_SENTINEL,
        role=JIT_DEFAULT_ROLE,
        display_label=display_name or None,
        is_active=True,
    )
    db.add(user)
    db.flush()
    logger.info("sso jit: identidad nueva aprovisionada (user=%s tenant=%s)", user.id, tenant_id)
    return user
