"""Comandos de mantenimiento del backend, para correr DENTRO del contenedor.

    python -m src.cli crear-super-admin --username <usuario> --email <email>
    python -m src.cli resetear-super-admin --username <usuario>

`crear-super-admin` provee el primer `super_admin` de la instalación. Hace falta porque
`POST /users` sólo deja asignar `super_admin`/`compliance_officer` a un `super_admin`
(`auth.rbac.exigir_super_admin_para_rol`) y ninguna migración lo autogenera: sin este
comando, el primero no tendría de dónde salir. Es genérico —no distingue on-prem de cloud—
e idempotente: si ya existe un `super_admin`, no hace nada. No lo invoca nada más que el
operador: ni el arranque, ni una migración, ni un endpoint.

`resetear-super-admin` recupera una contraseña perdida cuando no hay otro super_admin que la
resetee. Se corre sólo desde el servidor (exec dentro del contenedor): la autorización ES el
acceso al servidor.

Contrato de salida (lo consume el instalador): la contraseña se genera acá (alta entropía) y
sale UNA sola vez por stdout, en una línea `PASSWORD=<valor>`; todo lo demás va por stderr y
nada se guarda en archivos ni logs (en la base queda sólo el hash, con `must_change_password`
activado: el panel obliga a cambiarla en el primer ingreso). Códigos de salida: 0 = hecho
(stdout con `PASSWORD=`), 3 = `crear-super-admin` y ya existe un super_admin (no toca nada),
1 = rechazado (usuario/email inválidos u ocupados; usuario a resetear inexistente o que no es
super_admin), 2 = argumentos inválidos.
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
from .services.auth_events import (AUTH_BOOTSTRAP_SUPER_ADMIN, AUTH_SUPER_ADMIN_PASSWORD_RESET,
                                   emit_auth_event)

#: 24 bytes aleatorios → 32 caracteres url-safe (192 bits). Entra en los 72 bytes que bcrypt
#: mira, así que ningún bit de la entropía se pierde en el hash.
_BYTES_DE_ENTROPIA = 24

_EMAIL = TypeAdapter(EmailStr)

#: Código de salida de `crear-super-admin` cuando ya hay un super_admin (no es un error).
SALIDA_YA_EXISTE = 3


class AltaRechazada(ValueError):
    """El alta no se hizo y el mensaje dice por qué (pensado para el operador)."""


def _nueva_password() -> str:
    return secrets.token_urlsafe(_BYTES_DE_ENTROPIA)


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

    password = _nueva_password()
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


def _super_admins_con_username(db: Session, usuario: str) -> list:
    return db.query(User).filter(User.username == usuario, User.role == "super_admin").all()


def resetear_super_admin(db: Session, *, usuario: str) -> str:
    """Genera una contraseña nueva para el `super_admin` `usuario` y la devuelve en claro (la
    única vez que existe). Vuelve a forzar el cambio en el próximo ingreso y deja su evento de
    auditoría (metadata-only) en la misma transacción.

    Levanta `AltaRechazada` si no existe un `super_admin` con ese username: el comando nunca
    resetea a una cuenta de otro rol (sería un camino para tomar cuentas ajenas)."""
    usuario = (usuario or "").strip()
    if not usuario:
        raise AltaRechazada("el usuario no puede estar vacío.")
    encontrados = _super_admins_con_username(db, usuario)
    if not encontrados:
        raise AltaRechazada(f"no existe un super_admin con el usuario {usuario!r}.")
    if len(encontrados) > 1:
        raise AltaRechazada(f"hay más de un super_admin con el usuario {usuario!r} (tenants "
                            "distintos): no se resetea ninguno.")
    user = encontrados[0]
    password = _nueva_password()
    user.password_hash = hash_password(password)
    user.must_change_password = True
    emit_auth_event(db, AUTH_SUPER_ADMIN_PASSWORD_RESET, target_user_id=str(user.id),
                    tenant_id=user.tenant_id)
    db.commit()
    return password


def _main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.cli",
                                     description="Comandos de mantenimiento del backend.")
    sub = parser.add_subparsers(dest="comando", required=True)
    crear = sub.add_parser("crear-super-admin",
                           help="crea el primer super_admin si no hay ninguno (idempotente)")
    crear.add_argument("--username", "--usuario", dest="username", required=True)
    crear.add_argument("--email", required=True)
    reset = sub.add_parser("resetear-super-admin",
                           help="genera una contraseña nueva para un super_admin existente")
    reset.add_argument("--username", "--usuario", dest="username", required=True)
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.comando == "crear-super-admin":
            password = crear_super_admin(db, usuario=args.username, email=args.email)
            if password is None:
                print("Ya existe un super_admin: no se creó nada.", file=sys.stderr)
                return SALIDA_YA_EXISTE
            hecho = f"super_admin {args.username.strip()!r} creado."
        else:
            password = resetear_super_admin(db, usuario=args.username)
            hecho = f"contraseña del super_admin {args.username.strip()!r} reseteada."
    except AltaRechazada as exc:
        print(f"No se hizo nada: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

    print(f"PASSWORD={password}")
    print(f"{hecho} La contraseña se muestra UNA sola vez y no queda guardada en ningún lado; "
          "deberá cambiarla en el primer ingreso.", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
