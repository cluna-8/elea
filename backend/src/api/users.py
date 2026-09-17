from datetime import datetime
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
                            UserPatch, PasswordChangeRequest, PasswordResetRequest)
from ..services import ai_engine_client
from ..services.ai_engine_client import AIEngineClientError
from ..services.budget_service import BudgetService
from ..services.auth_events import (emit_auth_event, AUTH_BOOTSTRAP_ADMIN,
                                    AUTH_ROLE_CHANGED)
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
#: los dos roles administrativos se puede crear sin una sesión admin (``POST /users`` es
#: admin-only), así que su presencia demuestra que hubo un dueño. El ``compliance_officer``
#: quedó AFUERA en 017/US1 (T006, #246/#250): perdió toda escritura en la matriz —es un auditor
#: solo-lectura—, así que su sola existencia ya no prueba que hubo un admin. Un auditor
#: read-only no debe bloquear el bootstrap: una instalación sembrada sólo con él quedaría sin
#: admin y sin vía de crear uno. ``client`` queda afuera por la misma razón: el seed del perfil
#: los siembra por config, sin nadie logueado.
ROLES_QUE_PRUEBAN_DUENO = ("tenant_admin", "super_admin")


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
    tenant_id: UUID
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
        id=user.id, tenant_id=user.tenant_id, username=user.username, role=user.role,
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
            email="admin@sentinel.com.ar",  # .local es TLD reservado: EmailStr del response lo rechaza (bug heredado)
            password_hash=password_hash,
            role="tenant_admin",  # canónico post-013 (equivale al legacy 'admin' vía shim RBAC)
            is_active=True,
        )
        db.add(user)
        # flush (no commit) asigna user.id (default uuid4) SIN cerrar la tx: el evento
        # de bootstrap se emite ACÁ, en la fase de DB síncrona (run_in_threadpool) y en
        # la MISMA tx que el insert — nunca en el handler async, para no retener la
        # conexión a través de un await (#167/#238). Sólo se emite si este insert creó
        # el admin (los caminos de carrera perdida ya retornaron arriba, sin emitir).
        db.flush()
        emit_auth_event(db, AUTH_BOOTSTRAP_ADMIN,
                        target_user_id=str(user.id), tenant_id=DEFAULT_TENANT_ID)
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

    token = create_session_token(str(snap.id), snap.role, snap.username, str(snap.tenant_id))
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
def list_groups(include_inactive: bool = False, db: Session = Depends(get_db)):
    q = db.query(Group)
    if not include_inactive:
        q = q.filter(Group.is_active.is_(True))
    return q.all()


@router.delete("/groups/{group_id}", dependencies=[Depends(require_role("admin"))])
def deactivate_group(group_id: UUID, db: Session = Depends(get_db)):
    """Baja de equipo (spec 054, 17-sep) — NO física, mismo criterio que
    `deactivate_user` (`DELETE /users/{id}`, más arriba): hasta esta spec un equipo se
    podía crear pero nunca dar de baja, "un error grave" reportado en vivo probando la
    atribución de costos (spec 053) — se necesitaba un equipo descartable para probar y
    no había forma de sacarlo de encima.

    Revoca las Connections que cuelgan directo del grupo (`api_keys.group_id`, distinto
    de las que cuelgan de un usuario del grupo — esas ya las revoca `deactivate_user`
    cuando corresponda), y libera a los miembros actuales a "sin equipo" — mismo
    criterio que `orphan_owned_workspaces` deja espacios "sin asignar" en vez de
    borrarlos. La auditoría histórica (`audit_logs.user_group_id`, `budgets.group_id`)
    NUNCA se toca — sigue visible bajo el nombre del grupo, igual que con un usuario
    dado de baja.
    """
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado.")
    if not group.is_active:
        raise HTTPException(status_code=409, detail="El grupo ya está dado de baja.")

    from ..models.budget import APIKey
    db.query(APIKey).filter(APIKey.group_id == group.id, APIKey.is_active.is_(True)) \
        .update({"is_active": False}, synchronize_session=False)

    miembros_afectados = db.query(User).filter(User.group_id == group.id) \
        .update({"group_id": None}, synchronize_session=False)

    group.is_active = False
    group.deactivated_at = datetime.utcnow()

    db.commit()
    return {"status": "deactivated", "id": str(group.id), "members_unassigned": miembros_afectados}


# --- User Endpoints ---

# ── El alta tampoco retiene conexión a través de sus awaits (#239) ────────────────────
# `create_user` es `async` y hasheaba con el `hash_password` SYNC: ~100-300 ms de bcrypt
# BLOQUEANDO el event loop en cada alta. El swap de una línea por `await
# hash_password_async` cierra ese bug y REABRE el P1 de la ronda 2 del #167 descrito en el
# comentario de arriba: el handler ya tiene la conexión RETENIDA cuando llega al hash (la
# toma el query de unicidad de username y la Session no la suelta hasta commit/close), así
# que awaitear ahí la retiene a través del executor. Medido sobre PG16 vivo con
# `engine.pool.checkedout()`: 0 al abrir la Session, **1 tras el query de unicidad**.
# La cura es la MISMA partición en fases que `login`, y por eso cubre de una sola vez los
# DOS awaits del handler: el bcrypt y la llamada de red al motor. Ese segundo hold es
# PRE-EXISTENTE, no del delta —`db.refresh()` re-adquiere después del commit y el
# `ai_engine_client.create_user` de abajo se awaitea con esa conexión tomada—, y una red que
# cuelga retiene mucho más que los ~250 ms del bcrypt. Escribir las fases para el bcrypt y
# dejar el otro await con la conexión tomada era más código para preservar un hold conocido.
# Detalle que hace que este caso se LEA como seguro sin serlo: `commit()` suelta la
# conexión, pero un `refresh()` posterior la vuelve a tomar.


def _validar_alta(db: Session, user_in: UserCreate) -> tuple:
    """Fase DB del pre-check del alta: unicidad de username, existencia del grupo y gate de
    licencia. Devuelve `(role, display_label)` y LIBERA la conexión al salir, para que no
    quede retenida a través del bcrypt (#239). Corre en `run_in_threadpool`.

    Va ANTES del hash por la misma razón que `_es_sin_dueno` en el login: un alta que va a
    ser rechazada no debe quemar ~250 ms del executor acotado de bcrypt.

    `normalize_legacy_role` es CPU pura y no necesita la conexión, pero se resuelve ACÁ
    ADENTRO a propósito: su 422 va entre el 404 del grupo y el gate de licencia, y sacarlo
    de esta fase le cambiaría la precedencia a los errores (un rol inválido con username
    duplicado devolvería 422 donde hoy devuelve 400).
    """
    try:
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
        return role, display_label
    finally:
        db.rollback()


def _insertar_usuario(db: Session, user_in: UserCreate, role: str,
                      display_label: Optional[str], password_hash: str) -> UserResponse:
    """Fase DB del insert. La contraseña llega YA hasheada (el bcrypt ocurrió afuera, sin
    conexión retenida). Devuelve la instantánea PLANA ya validada contra el response_model,
    armada con la transacción todavía abierta: devolver el objeto ORM obligaría a
    serializarlo con la conexión suelta y la instancia expirada, o sea un reload perezoso en
    el event loop —justo lo que esta partición evita."""
    try:
        # Bug real encontrado en una prueba de punta a punta en vivo (09-sep): la
        # migración 018 solo backfillea `account_type='service'` para usuarios `svc.%`
        # YA EXISTENTES al momento de migrar — ninguna cuenta de servicio creada DESPUÉS
        # (cada instalación nueva de `install.sh` crea las suyas en su primer arranque)
        # quedaba marcada, así que reaparecía en la tabla principal de personas — el
        # bug original que reportó Tomás Mc Nally, de vuelta en cualquier instalación
        # fresca. Mismo criterio de prefijo que `_proposito_de()`, más abajo en este
        # archivo (y que `install.sh`: `svc.anythingllm-provider`, `svc.rag-masking`).
        account_type = "service" if user_in.username.startswith("svc.") else "person"
        user = User(
            username=user_in.username,
            email=user_in.email,
            password_hash=password_hash,
            role=role,
            display_label=display_label,
            group_id=user_in.group_id,
            is_active=user_in.is_active,
            account_type=account_type,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return UserResponse.model_validate(user)
    finally:
        db.rollback()


def _persistir_engine_user_id(db: Session, user_id: UUID, engine_user_id: str) -> UserResponse:
    """Fase DB que persiste el id del motor tras el provisioning, con la conexión liberada al
    salir. `.one()` a propósito: la fila la acabamos de commitear nosotros, así que su
    ausencia es una violación de invariante y no un camino esperado que convenga tapar."""
    try:
        user = db.query(User).filter(User.id == user_id).one()
        user.engine_user_id = engine_user_id
        db.commit()
        db.refresh(user)
        return UserResponse.model_validate(user)
    finally:
        db.rollback()


def _borrar_usuario(db: Session, user_id: UUID) -> None:
    """Compensación del alta cuando el motor no pudo provisionar: borra el User local que ya
    habíamos commiteado. `db.delete()` sobre la instancia (y no un `query.delete()` masivo)
    para respetar los cascades del ORM, igual que antes de la partición."""
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user is not None:
            db.delete(user)
            db.commit()
    finally:
        db.rollback()


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_role("admin"))])
async def create_user(user_in: UserCreate, db: Session = Depends(get_db)):
    # Primero la contraseña: es lo único que no se puede corregir después sin que el usuario
    # quede con una credencial conocida. El alta sin contraseña ya no existe (había un
    # `or "sentinel123"` acá, y una cadena vacía pasaba el `if` del schema).
    try:
        validar_password(user_in.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Fase DB (threadpool, conexión liberada al volver): unicidad, grupo, rol y licencia.
    role, display_label = await run_in_threadpool(_validar_alta, db, user_in)

    # El bcrypt, en el executor dedicado y SIN conexión retenida (#239 + P1 de la r2 del #167).
    password_hash = await hash_password_async(user_in.password)

    snap = await run_in_threadpool(_insertar_usuario, db, user_in, role, display_label,
                                   password_hash)

    try:
        # Red al motor: el otro await del handler, también sin conexión retenida.
        engine_user_id = await ai_engine_client.create_user(user_id=user_in.email)
    except AIEngineClientError:
        await run_in_threadpool(_borrar_usuario, db, snap.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The AI engine is unavailable. The user was not created. Please try again.",
        )

    return await run_in_threadpool(_persistir_engine_user_id, db, snap.id, engine_user_id)


# Propósito legible por cuenta de servicio conocida (spec 043 US4, T045): vocabulario
# cerrado, sin nombre de motor/proveedor (Constitución VII) — mismo criterio que
# `/gw/whoami`. Coincide por PREFIJO del username, que es la convención real del
# instalador (`svc.anythingllm-provider`, `svc.rag-masking`, ver install.sh).
_PROPOSITO_CUENTA_SERVICIO = {
    "svc.anythingllm-provider": "Habla con el motor de documentos en nombre del Hub.",
    "svc.rag-masking": "Protege los documentos antes de indexarlos en el Hub.",
}


def _proposito_de(username: str) -> str:
    for prefijo, texto in _PROPOSITO_CUENTA_SERVICIO.items():
        if username.startswith(prefijo):
            return texto
    return "Cuenta de servicio interna."


@router.get("", dependencies=[Depends(require_role("admin", "compliance_officer"))])
def list_users(include_service: bool = False, db: Session = Depends(get_db)):
    """Spec 043 (US4, T045): excluye cuentas de servicio por default (diagnostico.md §4 de
    la 043 — se listaban como personas). `?include_service=true` las trae con `purpose`."""
    query = db.query(User)
    if not include_service:
        query = query.filter(User.account_type != "service")
    users = query.all()
    out = []
    for u in users:
        row = UserResponse.model_validate(u).model_dump()
        row["account_type"] = u.account_type
        if u.account_type == "service":
            row["purpose"] = _proposito_de(u.username)
        out.append(row)
    return out


# El literal /me/budget va ANTES de /{user_id}: FastAPI resuelve por orden de registro
# dentro del mismo router, y al revés "me" entraría como user_id y moriría en el parseo
# del UUID (mismo motivo ya documentado para /me/password, más abajo).

@router.get("/me/budget")
def get_own_budget(
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    """Autoservicio de presupuesto (spec 043 US2, contrato 2): el propio Eleia Hub lo
    consume con la sesión JWT de la persona, sin necesitar una sesión de admin de fondo
    (antes leía `/budgets` completo con `ELEA_SERVICE_USERNAME=admin` y filtraba en
    memoria — diagnostico.md §5 de la 043). Prioriza el presupuesto PERSONAL sobre el de
    grupo (mismo orden que `BudgetService.update_budget`); si no hay ninguno configurado,
    reporta "sin límite" — igual que `has_sufficient_budget` ya trata ese caso: nadie queda
    bloqueado por un presupuesto que nunca se configuró."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida: sesión JWT válida no proporcionada o expirada.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    budget = BudgetService.get_personal_budget(db, str(user.id))
    if budget is None and user.group_id:
        budget = BudgetService.get_group_budget(db, str(user.group_id))
    if budget is None:
        return {"used_usd": 0.0, "max_usd": None, "status": "ok"}
    tiene_credito = BudgetService._budget_has_credit(budget)
    return {
        "used_usd": float(budget.current_spend_usd),
        "max_usd": float(budget.max_spend_usd),
        "status": "ok" if tiene_credito else "exceeded",
    }


@router.get("/{user_id}", response_model=UserResponse, dependencies=[Depends(require_role("admin", "compliance_officer"))])
def get_user(user_id: UUID, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/{user_id}", response_model=UserResponse)
def update_user(user_id: UUID, user_in: UserBase,
                actor: User = Depends(require_role("admin")),
                db: Session = Depends(get_db)):
    # Forma-2 de require_role (FR-004): inyecta el actor autenticado para auditar QUIÉN
    # mutó, con la MISMA puerta admin-only que antes vivía en dependencies=[...].
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    data = user_in.dict(exclude_unset=True)
    rol_anterior = user.role  # capturado ANTES del setattr, para auditar el cambio (FR-016)
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
    # Sólo si el rol efectivamente cambió (el normalizado != el anterior). El emit va ANTES
    # del único commit para que el evento viaje en la MISMA tx que la mutación de rol (el
    # contrato de auth_events, igual que el bootstrap): un solo commit atómico → o cambia el
    # rol Y queda auditado, o ninguna de las dos; nunca un cambio de identidad sin registro.
    # El handler es síncrono, así que corre sin await de por medio (sin la retención de
    # conexión del #167/#238). El actor va como metadata-only (id, jamás la sesión ni PII).
    if "role" in data and data["role"] != rol_anterior:
        emit_auth_event(db, AUTH_ROLE_CHANGED, actor_user_id=str(actor.id),
                        target_user_id=str(user.id), old_role=rol_anterior,
                        new_role=data["role"])
    db.commit()
    db.refresh(user)
    return user


def _bloquear_baja_insegura(db: Session, actor: User, user: User) -> None:
    """Las dos guardas de baja (spec 043 US5): nadie se da de baja a sí mismo, y el
    último admin activo del tenant no se puede desactivar (la instancia se queda sin
    forma de administrarse — la recuperación pasa por tocar la base a mano).

    Bug real encontrado en verificación en vivo (09-sep): estas dos guardas SOLO vivían
    en `DELETE /users/{id}` (deactivate_user). El toggle "Desactivar" del panel llama a
    `PATCH` con `is_active=false` — mismo efecto visible, cero guarda — así que cualquier
    caller de PATCH (un curl directo, un futuro cliente que no repita el guard de UI de
    UsersPage.tsx) podía autodesactivarse o dejar el tenant sin ningún admin activo. Se
    confirmó en vivo: un PATCH directo a la única cuenta admin devolvió 200, la dejó
    `is_active=false`, y el siguiente request con su JWT quedó 401 — sin otra cuenta
    admin, la única salida era un UPDATE manual en Postgres."""
    if actor.id == user.id:
        raise HTTPException(status_code=409, detail="No podés darte de baja a vos mismo.")

    if user.role in ("super_admin", "tenant_admin", "admin"):
        otros_admins_activos = (
            db.query(User)
            .filter(User.tenant_id == user.tenant_id,
                    User.role.in_(("super_admin", "tenant_admin", "admin")),
                    User.id != user.id,
                    User.deactivated_at.is_(None),
                    User.is_active.is_(True))
            .count()
        )
        if otros_admins_activos == 0:
            raise HTTPException(status_code=409,
                                detail="No se puede dar de baja al último admin activo del tenant.")


@router.patch("/{user_id}", response_model=UserResponse)
def patch_user(user_id: UUID, user_in: UserPatch,
               actor: User = Depends(require_role("admin")),
               db: Session = Depends(get_db)):
    """Spec 043 (US5, T052): actualización PARCIAL — solo cambia lo que el caller mandó,
    a diferencia de `PUT` (reemplazo completo, se mantiene por compatibilidad hacia
    atrás). Misma validación de unicidad y misma auditoría de cambio de rol que `PUT`."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    data = user_in.model_dump(exclude_unset=True)
    rol_anterior = user.role

    # Mismas dos guardas que DELETE (ver _bloquear_baja_insegura): solo aplican cuando
    # el PATCH efectivamente apaga is_active — editar rol/email de alguien inactivo, o
    # reactivar, no pasa por acá.
    if "is_active" in data and data["is_active"] is False and user.is_active:
        _bloquear_baja_insegura(db, actor, user)

    if "role" in data and data["role"] is not None:
        try:
            data["role"], label = normalize_legacy_role(data["role"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if label:
            data.setdefault("display_label", label)

    # Unicidad por tenant (username/email) — mismo criterio que el índice
    # uq_users_tenant_username/uq_users_tenant_email, chequeado ANTES de tocar la fila
    # para devolver un 409 legible en vez de que lo levante el commit.
    if "username" in data and data["username"] != user.username:
        dup = db.query(User).filter(User.tenant_id == user.tenant_id,
                                    User.username == data["username"],
                                    User.id != user.id).first()
        if dup:
            raise HTTPException(status_code=409,
                                detail=f"El nombre de usuario '{data['username']}' ya está en uso.")
    if "email" in data and data["email"] != user.email:
        dup = db.query(User).filter(User.tenant_id == user.tenant_id,
                                    User.email == data["email"],
                                    User.id != user.id).first()
        if dup:
            raise HTTPException(status_code=409,
                                detail=f"El email '{data['email']}' ya está en uso.")

    era_activo = user.is_active
    for field, value in data.items():
        setattr(user, field, value)

    if "role" in data and data["role"] != rol_anterior:
        emit_auth_event(db, AUTH_ROLE_CHANGED, actor_user_id=str(actor.id),
                        target_user_id=str(user.id), old_role=rol_anterior,
                        new_role=data["role"])

    # Bug real encontrado en revisión (09-sep): el toggle "Desactivar" del panel llama
    # a ESTE endpoint (PATCH, no DELETE) con is_active=false — sin esto, la persona ve el
    # badge "Desactivado" pero sus Connections seguían activas, porque custom_auth.py
    # solo mira `api_keys.is_active` (el flag de la LLAVE), nunca el del usuario. Mismo
    # criterio que `deactivate_user` (DELETE), pero acá NO se reactivan llaves al volver
    # a activar al usuario — una reactivación no debe restaurar en silencio la capacidad
    # de una llave potencialmente comprometida; si hace falta, se emite una nueva.
    if "is_active" in data and era_activo and not data["is_active"]:
        from ..models.budget import APIKey
        db.query(APIKey).filter(APIKey.user_id == user.id, APIKey.is_active.is_(True)) \
            .update({"is_active": False}, synchronize_session=False)

    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}")
def deactivate_user(user_id: UUID, actor: User = Depends(require_role("admin")),
                    db: Session = Depends(get_db)):
    """Baja definitiva (spec 043 US5, T053/T054/T055) — NO física: revoca llaves y
    sesiones (`is_active=False` bloquea el JWT en `get_current_user`, que ya filtra por
    esa columna), libera el asiento, y cierra sus espacios propios a "sin asignar"
    (FR-042, workspace_service.orphan_owned_workspaces). La auditoría histórica del
    usuario NUNCA se toca — sigue visible bajo su identidad."""
    if actor.id == user_id:
        raise HTTPException(status_code=409, detail="No podés darte de baja a vos mismo.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.role in ("super_admin", "tenant_admin", "admin"):
        otros_admins_activos = (
            db.query(User)
            .filter(User.tenant_id == user.tenant_id,
                    User.role.in_(("super_admin", "tenant_admin", "admin")),
                    User.id != user.id,
                    User.deactivated_at.is_(None),
                    User.is_active.is_(True))
            .count()
        )
        if otros_admins_activos == 0:
            raise HTTPException(status_code=409,
                                detail="No se puede dar de baja al último admin activo del tenant.")

    from ..models.budget import APIKey
    db.query(APIKey).filter(APIKey.user_id == user.id, APIKey.is_active.is_(True)) \
        .update({"is_active": False}, synchronize_session=False)

    user.is_active = False
    user.deactivated_at = datetime.utcnow()

    from ..services import workspace_service
    espacios_afectados = workspace_service.orphan_owned_workspaces(db, user.tenant_id, user.id)

    db.commit()
    return {"status": "deactivated", "id": str(user.id), "workspaces_unassigned": espacios_afectados}


# --- Password Endpoints ---
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
