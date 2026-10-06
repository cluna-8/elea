"""Comandos de mantenimiento del backend, para correr DENTRO del contenedor.

    python -m src.cli crear-super-admin --usuario <usuario> --email <email>

`crear-super-admin` provee el primer `super_admin` de la instalación. Hace falta porque
`POST /users` sólo deja asignar `super_admin`/`compliance_officer` a un `super_admin`
(`auth.rbac.exigir_super_admin_para_rol`) y ninguna migración lo autogenera: sin este
comando, el primero no tendría de dónde salir. Es genérico —no distingue on-prem de cloud—
e idempotente: si ya existe un `super_admin`, no hace nada. No lo invoca nada más que el
operador: ni el arranque, ni una migración, ni un endpoint.

La contraseña se genera acá (alta entropía), sale UNA sola vez por stdout y no se guarda en
ningún archivo ni log; en la base queda sólo el hash, con `must_change_password` activado
(el panel obliga a cambiarla en el primer ingreso).
"""
import argparse
import secrets
import sys
import uuid
from typing import Optional

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth.passwords import hash_password
from .database import SessionLocal
from .models.tenant import DEFAULT_TENANT_ID
from .models.user import User
from .services.auth_events import AUTH_BOOTSTRAP_SUPER_ADMIN, emit_auth_event

#: 24 bytes aleatorios → 32 caracteres url-safe (192 bits). Entra en los 72 bytes que bcrypt
#: mira, así que ningún bit de la entropía se pierde en el hash.
_BYTES_DE_ENTROPIA = 24

_EMAIL = TypeAdapter(EmailStr)


class AltaRechazada(ValueError):
    """El alta no se hizo y el mensaje dice por qué (pensado para el operador)."""


def _hay_super_admin(db: Session) -> bool:
    return db.query(User).filter(User.role == "super_admin").count() > 0


def _campo_ocupado(db: Session, usuario: str, email: str) -> Optional[str]:
    """`"usuario"` o `"email"` si ya lo usa alguien (unicidad por tenant), si no `None`."""
    if db.query(User).filter(User.tenant_id == DEFAULT_TENANT_ID,
                             User.username == usuario).first():
        return "usuario"
    if db.query(User).filter(User.tenant_id == DEFAULT_TENANT_ID,
                             User.email == email).first():
        return "email"
    return None


def crear_super_admin(db: Session, *, usuario: str, email: str) -> Optional[str]:
    """Crea el primer `super_admin` y devuelve su contraseña en claro (la única vez que
    existe). Devuelve `None`, sin tocar nada, si ya hay un `super_admin`.

    Levanta `AltaRechazada` si el usuario/email no son válidos o ya los usa otra cuenta:
    nunca asciende a un usuario existente. Fila + evento de auditoría van en la MISMA
    transacción (`emit_auth_event` no commitea); el evento es metadata-only (ids y rol).
    """
    usuario = (usuario or "").strip()
    if not usuario:
        raise AltaRechazada("el usuario no puede estar vacío.")
    try:
        email = _EMAIL.validate_python((email or "").strip())
    except ValidationError:
        raise AltaRechazada(f"el email {email!r} no es válido.") from None

    if _hay_super_admin(db):
        return None
    ocupado = _campo_ocupado(db, usuario, email)
    if ocupado:
        raise AltaRechazada(f"el {ocupado} ya lo usa otra cuenta; no se creó nada.")

    password = secrets.token_urlsafe(_BYTES_DE_ENTROPIA)
    user = User(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, username=usuario, email=email,
                password_hash=hash_password(password), role="super_admin", is_active=True,
                must_change_password=True)
    try:
        db.add(user)
        db.flush()
        emit_auth_event(db, AUTH_BOOTSTRAP_SUPER_ADMIN, target_user_id=str(user.id),
                        new_role="super_admin", tenant_id=DEFAULT_TENANT_ID)
        db.commit()
    except IntegrityError:
        # Dos invocaciones a la vez: la restricción UNIQUE del esquema es la autoridad.
        db.rollback()
        raise AltaRechazada("el usuario o el email ya existen (otra invocación ganó la "
                            "carrera); no se creó nada.") from None
    return password


def _main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.cli",
                                     description="Comandos de mantenimiento del backend.")
    sub = parser.add_subparsers(dest="comando", required=True)
    crear = sub.add_parser("crear-super-admin",
                           help="crea el primer super_admin si no hay ninguno (idempotente)")
    crear.add_argument("--usuario", required=True)
    crear.add_argument("--email", required=True)
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        password = crear_super_admin(db, usuario=args.usuario, email=args.email)
    except AltaRechazada as exc:
        print(f"No se creó el super_admin: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

    if password is None:
        print("Ya existe un super_admin: no se creó nada.", file=sys.stderr)
        return 0
    print(f"usuario: {args.usuario.strip()}")
    print(f"contraseña: {password}")
    print("Se muestra UNA sola vez y no queda guardada en ningún lado. Deberá cambiarla en "
          "el primer ingreso.", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
