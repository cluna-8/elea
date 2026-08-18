from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, NamedTuple, Optional
from uuid import UUID
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..database import get_db
from ..licensing.gate import enforce_seat_gate
from ..models.tenant import DEFAULT_TENANT_ID
from ..models.user import User, Group, normalize_legacy_role
from ..schemas.user import (UserCreate, UserResponse, GroupCreate, GroupResponse, UserBase,
                            PasswordChangeRequest, PasswordResetRequest)
from ..services import ai_engine_client
from ..services.ai_engine_client import AIEngineClientError
from ..auth.session import create_session_token, get_current_user
# hash_password vivía acá como sha256 sin sal; ahora es bcrypt y vive en auth.passwords.
# Se sigue importando con el mismo nombre porque hay tests que lo toman de este módulo.
from ..auth.passwords import (hash_password, hash_password_async, necesita_rehash,
                              validar_password, verify_password, verify_password_async)
from ..auth.rbac import require_role

router = APIRouter(prefix="/users", tags=["Users"])


class LoginRequest(BaseModel):
    username: str
    password: str


#: Roles cuya sola existencia PRUEBA que la instalación ya tuvo un administrador: ninguno de
#: los tres se puede crear sin una sesión admin (``POST /users`` es admin-only). ``client``
#: queda afuera a propósito: el seed del perfil los siembra por config, sin nadie logueado.
ROLES_QUE_PRUEBAN_DUENO = ("tenant_admin", "super_admin", "compliance_officer")


def _sin_dueno(db: Session) -> bool:
    """¿La instalación todavía no tiene dueño?

    El gate NO es "la tabla users está vacía", aunque sea la señal más obvia: el runbook de
    instalación siembra los clients del perfil (``seed_clients_from_config``, filas
    ``role='client'`` con un ``password_hash`` centinela que no verifica nunca) ANTES del
    primer login del dueño. Con el gate por tabla vacía, cualquier perfil con clients dejaba
    la instalación sin ningún admin y sin forma de crear uno —``POST /users`` exige
    ``require_role("admin")``—: bloqueada, y sin salida documentada que no sea SQL a mano.

    Lo que se mira entonces es lo que la condición quería decir: que nadie sea dueño todavía.
    Una instalación con 124 usuarios cargados por alguien ya tiene el suyo, así que el agujero
    de apropiación sigue cerrado. Queda una ventana inherente al "primer login crea el dueño":
    entre el arranque y ese primer login, el primero que llegue gana. Por eso el runbook pone
    el bootstrap inmediatamente después del arranque y antes de exponer el host.
    """
    return db.query(User).filter(User.role.in_(ROLES_QUE_PRUEBAN_DUENO)).count() == 0


# ── Login sin retener conexión del pool a través de bcrypt (#167 ronda 2, P1 del gate) ──
# Con `login` async y la conexión del pool RETENIDA a través del await de bcrypt (la Session
# no cierra su transacción hasta commit/close), bajo ráfaga de logins el pool (30/proceso) se
# agotaba y un `pool.get()` BLOQUEANTE corría en el event loop → los coroutines que esperaban
# bcrypt no podían resumir ni devolver su conexión → freeze en cascada de ~30 s del proceso
# ENTERO (gateway incluido), peor que el #167 original.
# Regla: NINGUNA conexión retenida a través de un await del executor. Cada fase de DB corre en
# `run_in_threadpool` (fuera del event loop) sobre la Session INYECTADA (`get_db`, para
# respetar el override de los tests) y CIERRA su transacción antes de volver —rollback tras
# leer, commit tras escribir— así la conexión vuelve al pool ANTES del bcrypt. Entre fases se
# pasa un snapshot PLANO, desacoplado del ORM (nada de reloads perezosos sin transacción).


class _LoginSnapshot(NamedTuple):
    """Instantánea plana del usuario para el login, desacoplada del ORM: se arma con la
    transacción abierta y se devuelve con la conexión ya liberada, para que el login awaitee
    bcrypt sin retenerla."""
    id: UUID
    username: str
    role: str
    display_label: Optional[str]
    email: str
    password_hash: str
    is_active: bool


def _instantanea(user: Optional[User]) -> Optional[_LoginSnapshot]:
    if user is None:
        return None
    return _LoginSnapshot(
        id=user.id, username=user.username, role=user.role,
        display_label=user.display_label, email=user.email,
        password_hash=user.password_hash, is_active=user.is_active,
    )


def _cargar_usuario_para_login(db: Session, username: str) -> Optional[_LoginSnapshot]:
    """Lee el usuario por username y LIBERA la conexión (rollback cierra la txn de lectura →
    vuelve al pool) antes de volver, para que no quede retenida a través del await de bcrypt
    (#167 ronda 2). Corre en `run_in_threadpool`, nunca en el event loop."""
    try:
        return _instantanea(db.query(User).filter(User.username == username).first())
    finally:
        db.rollback()


def _bootstrap_admin_si_sin_dueno(db: Session, password_hash: str) -> Optional[_LoginSnapshot]:
    """Crea el primer admin SÓLO si la instalación no tiene dueño. La contraseña llega ya
    hasheada (el bcrypt ocurrió afuera, sin conexión retenida); el check + insert es atómico.
    Si otro login ganó la carrera y ya existe `admin`, devuelve ese. Libera la conexión al
    salir (el rollback del `finally` es no-op tras el commit del insert)."""
    try:
        existente = db.query(User).filter(User.username == "admin").first()
        if existente is not None:
            return _instantanea(existente)
        if not _sin_dueno(db):
            return None
        user = User(
            username="admin",
            email="admin@basa.com.ar",  # .local es TLD reservado: EmailStr del response lo rechaza (bug heredado)
            password_hash=password_hash,
            role="tenant_admin",  # canónico post-013 (equivale al legacy 'admin' vía shim RBAC)
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return _instantanea(user)
    finally:
        db.rollback()


def _actualizar_hash_de_login(db: Session, user_id: UUID, nuevo_hash: str) -> None:
    """Re-hash perezoso del formato legacy: persiste el hash nuevo (computado afuera del pool)
    y libera la conexión al salir (#167 ronda 2)."""
    try:
        db.query(User).filter(User.id == user_id).update(
            {User.password_hash: nuevo_hash}
        )
        db.commit()
    finally:
        db.rollback()


def _es_sin_dueno(db: Session) -> bool:
    """Pre-check del bootstrap en su propia fase de DB (conexión liberada al salir): sólo si la
    instalación NO tiene dueño se valida/hashea la contraseña. Sin esto, cada POST con
    username='admin' en una caja que YA tiene dueño quema ~250 ms de bcrypt SIN autenticar
    (satura el executor acotado → DoS de logins legítimos) y una password corta filtra 422 vs
    401 (oráculo de existencia de 'admin'). Restaura el gate viejo (`_sin_dueno` antes de todo,
    P1 del gate r2). El check atómico dentro de `_bootstrap_admin_si_sin_dueno` sigue siendo la
    AUTORIDAD: TOCTOU benigno — si un dueño aparece entre este pre-check y el insert, el insert
    lo respeta (devuelve el admin existente)."""
    try:
        return _sin_dueno(db)
    finally:
        db.rollback()


@router.post("/login")
async def login(body: LoginRequest, db: Session = Depends(get_db)):
    # Fase DB (en threadpool, conexión liberada al volver): buscar el usuario.
    snap = await run_in_threadpool(_cargar_usuario_para_login, db, body.username)

    # Bootstrap del primer admin, SÓLO si la instalación no tiene dueño (raro, controlado por
    # runbook). El pre-check `_es_sin_dueno` va ANTES de validar/hashear: sin él, cada POST con
    # username='admin' en una caja con dueño quemaría bcrypt sin autenticar (DoS del executor)
    # y filtraría 422 vs 401 (P1 del gate r2). El hash se computa antes del insert; el check +
    # insert atómico dentro de `_bootstrap_admin_si_sin_dueno` es la autoridad final.
    if snap is None and body.username == "admin" and await run_in_threadpool(_es_sin_dueno, db):
        try:
            validar_password(body.password)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        hashed = await hash_password_async(body.password)
        snap = await run_in_threadpool(_bootstrap_admin_si_sin_dueno, db, hashed)

    if (snap is None or not snap.is_active
            or not await verify_password_async(body.password, snap.password_hash)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")

    # Migración perezosa del formato viejo (ver auth/passwords): único momento con la
    # contraseña en claro. El hash nuevo se computa fuera del pool y se persiste en una fase
    # DB propia — nunca reteniendo la conexión a través del await del hash.
    if necesita_rehash(snap.password_hash):
        nuevo = await hash_password_async(body.password)
        await run_in_threadpool(_actualizar_hash_de_login, db, snap.id, nuevo)

    token = create_session_token(str(snap.id), snap.role, snap.username)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(snap.id),
            "username": snap.username,
            "role": snap.role,
            "display_label": snap.display_label,
            "email": snap.email,
        },
    }


# --- Group Endpoints ---

@router.post("/groups", response_model=GroupResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_role("admin"))])
async def create_group(group_in: GroupCreate, db: Session = Depends(get_db)):
    if db.query(Group).filter(Group.name == group_in.name).first():
        raise HTTPException(status_code=400, detail="Group with this name already exists")

    group = Group(name=group_in.name, description=group_in.description)
    db.add(group)
    db.commit()
    db.refresh(group)

    try:
        engine_team_id = await ai_engine_client.create_team(name=group_in.name)
        group.engine_team_id = engine_team_id
        db.commit()
        db.refresh(group)
    except AIEngineClientError:
        db.delete(group)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The AI engine is unavailable. The team was not created. Please try again.",
        )

    return group


@router.get("/groups", response_model=List[GroupResponse], dependencies=[Depends(require_role("admin", "compliance_officer"))])
def list_groups(db: Session = Depends(get_db)):
    return db.query(Group).all()


# --- User Endpoints ---

@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_role("admin"))])
async def create_user(user_in: UserCreate, db: Session = Depends(get_db)):
    # Primero la contraseña: es lo único que no se puede corregir después sin que el usuario
    # quede con una credencial conocida. El alta sin contraseña ya no existe (había un
    # `or "basa123"` acá, y una cadena vacía pasaba el `if` del schema).
    try:
        validar_password(user_in.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if db.query(User).filter(User.username == user_in.username).first():
        raise HTTPException(status_code=400, detail="Username already registered")

    if user_in.group_id:
        if not db.query(Group).filter(Group.id == user_in.group_id).first():
            raise HTTPException(status_code=404, detail="Group not found")

    # Acepta nombres legacy del frontend heredado (admin/clinician/developer) y los
    # normaliza al enum canonico post-013 (ck_users_role) conservando la etiqueta.
    try:
        role, display_label = normalize_legacy_role(user_in.role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if role == "client":
        # Gate de licencia (spec 021 US2, FR-009): sólo los Clients son seats;
        # los roles administrativos no consumen licencia. ANTES de crear el
        # User local y de provisionar en el motor.
        enforce_seat_gate(db, tenant_id=DEFAULT_TENANT_ID)
    user = User(
        username=user_in.username,
        email=user_in.email,
        password_hash=hash_password(user_in.password),
        role=role,
        display_label=display_label,
        group_id=user_in.group_id,
        is_active=user_in.is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    try:
        engine_user_id = await ai_engine_client.create_user(user_id=user_in.email)
        user.engine_user_id = engine_user_id
        db.commit()
        db.refresh(user)
    except AIEngineClientError:
        db.delete(user)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The AI engine is unavailable. The user was not created. Please try again.",
        )

    return user


@router.get("", response_model=List[UserResponse], dependencies=[Depends(require_role("admin", "compliance_officer"))])
def list_users(db: Session = Depends(get_db)):
    return db.query(User).all()


@router.get("/{user_id}", response_model=UserResponse, dependencies=[Depends(require_role("admin", "compliance_officer"))])
def get_user(user_id: UUID, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/{user_id}", response_model=UserResponse, dependencies=[Depends(require_role("admin"))])
def update_user(user_id: UUID, user_in: UserBase, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    data = user_in.dict(exclude_unset=True)
    # Mismo puente que create_user: acepta roles legacy sin violar ck_users_role
    if "role" in data:
        try:
            data["role"], label = normalize_legacy_role(data["role"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if label:
            data.setdefault("display_label", label)
    for field, value in data.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


# --- Password Endpoints ---
# El literal /me/password va ANTES de /{user_id}/password: FastAPI resuelve por orden de
# registro, y al revés "me" entraría como user_id y moriría en el parseo del UUID.

@router.post("/me/password")
def change_own_password(
    body: PasswordChangeRequest,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    """Cambio de la contraseña propia, para cualquier rol autenticado."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida: sesión JWT válida no proporcionada o expirada.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # La identidad se comprueba antes de la política: mientras no se pruebe quién es, no
    # tiene por qué enterarse de qué contraseñas acepta el sistema.
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="La contraseña actual no es correcta.")
    try:
        validar_password(body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"status": "ok"}


@router.post("/{user_id}/password", dependencies=[Depends(require_role("admin"))])
def reset_user_password(user_id: UUID, body: PasswordResetRequest, db: Session = Depends(get_db)):
    """Reseteo por el administrador (no exige la contraseña actual: no la conoce)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    try:
        validar_password(body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"status": "ok"}


# --- Spend Endpoints ---

@router.get("/{user_id}/spend", dependencies=[Depends(require_role("admin", "compliance_officer"))])
async def get_user_spend(user_id: UUID, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.engine_user_id:
        return {"spend_usd": None, "max_budget": None, "remaining": None}
    try:
        return await ai_engine_client.get_user_spend(user.engine_user_id)
    except AIEngineClientError:
        return {"spend_usd": None, "max_budget": None, "remaining": None}


@router.get("/groups/{group_id}/spend", dependencies=[Depends(require_role("admin", "compliance_officer"))])
async def get_group_spend(group_id: UUID, db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if not group.engine_team_id:
        return {"spend_usd": None, "max_budget": None, "remaining": None}
    try:
        return await ai_engine_client.get_team_spend(group.engine_team_id)
    except AIEngineClientError:
        return {"spend_usd": None, "max_budget": None, "remaining": None}
