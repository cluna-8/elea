"""Contract test de las credenciales de la API de usuarios (rama fix/auth-credenciales).

Fija las cuatro garantías del arreglo, cada una con la consecuencia observable que se olvida
primero si sólo se mira el código de estado:

- **No hay contraseña por defecto.** El alta sin contraseña (o con una corta, o vacía) es
  422; el usuario creado con contraseña válida entra con ESA y no con la que traía cableada
  el endpoint (``basa123``), que es lo que abría todas las cuentas del despliegue.
- **El hash guardado no es reversible.** Lo almacenado es bcrypt, no el sha256 sin sal.
- **Los usuarios ya cargados no quedan afuera.** Un ``password_hash`` legacy sigue
  verificando, y el primer login válido lo convierte a bcrypt sin script de migración: el
  SEGUNDO login (ya contra el hash nuevo) también tiene que funcionar.
- **El bootstrap de admin no es una puerta abierta.** Sólo corre mientras la instalación no
  tiene dueño (ningún usuario administrativo); si ya lo tiene y 'admin' no existe, el login
  es un 401 normal. Los clients sembrados por el perfil no cuentan como dueño: si contaran,
  el runbook (que siembra antes del primer login) dejaría la instalación sin admin.

Monta una app con SÓLO el router de usuarios y no ``src.main.app`` a propósito: el archivo
necesita dos bases vivas a la vez —una virgen para los tests de bootstrap y otra poblada
para el resto— y el override de ``get_db`` es por app, así que con la app global compartida
la segunda base le pisaría la sesión a la primera.
"""
import asyncio
import hashlib
import sys
import threading
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

# Mismo enganche de path que los otros contract tests: los harness de DB viven en ``tests/``
# y ``tests/integration/``, y desde ``tests/contract/`` no se ven solos.
_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import (fresh_db, owner_engine, require_postgres,  # noqa: E402
                               run_alembic)
from seat_gate_harness import mock_engine  # noqa: E402
from src.auth.passwords import hash_password  # noqa: E402

require_postgres()

DB_PRINCIPAL = "basa_test_auth_credenciales"
DB_BOOTSTRAP = "basa_test_auth_bootstrap"

ADMIN_PASSWORD = "admin-de-prueba-1"
CLAVE_VALIDA = "clave-de-prueba-1"
CLAVE_NUEVA = "clave-nueva-de-prueba"
CORTA = "corta-11-ch"  # 11 caracteres: uno menos que el mínimo


def _montar(dbname):
    """DB fresca a head + app con sólo el router de usuarios. Devuelve (client, factory, cerrar)."""
    fresh_db(dbname)
    run_alembic(dbname, "upgrade", "head")
    engine = owner_engine(dbname)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    from src.api.users import router as users_router
    from src.database import get_db

    app = FastAPI()
    app.include_router(users_router, prefix="/api/v1")

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), factory, engine.dispose


def _legacy(raw):
    """El formato que escribía el backend antes de este arreglo."""
    return hashlib.sha256(raw.encode()).hexdigest()


def _sembrar(factory, username, password_hash, role="client"):
    """Usuario por DB directa: el alta por API pasa por el gate de seats y por el
    provisioning al motor, y ninguna de las dos cosas tiene que ver con credenciales."""
    from src.models.user import User
    db = factory()
    try:
        db.add(User(username=username, email=f"{username}@basa.com.ar",
                    password_hash=password_hash, role=role, is_active=True))
        db.commit()
    finally:
        db.close()


def _hash_en_db(factory, username):
    from src.models.user import User
    db = factory()
    try:
        fila = db.query(User).filter(User.username == username).first()
        return fila.password_hash if fila else None
    finally:
        db.close()


def _vaciar_usuarios(factory):
    from src.models.user import User
    db = factory()
    try:
        db.query(User).delete()
        db.commit()
    finally:
        db.close()


def _login(client, username, password):
    return client.post("/api/v1/users/login",
                       json={"username": username, "password": password})


def _sesion(client, username, password):
    resp = _login(client, username, password)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _payload(username, password, role="compliance_officer"):
    """Rol administrativo a propósito: no es seat, así el alta no depende del tope de la
    licencia de la suite (lo que se mide acá es la credencial)."""
    return {"username": username, "email": f"{username}@basa.com.ar", "role": role,
            "password": password}


def _nombre(prefijo):
    return f"{prefijo}-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def api():
    client, factory, cerrar = _montar(DB_PRINCIPAL)
    headers = _sesion(client, "admin", ADMIN_PASSWORD)  # bootstrap sobre la DB virgen
    yield client, factory, headers
    cerrar()


@pytest.fixture(scope="module")
def bootstrap_api():
    client, factory, cerrar = _montar(DB_BOOTSTRAP)
    yield client, factory
    cerrar()


@pytest.fixture
def virgen(bootstrap_api):
    """Instalación virgen antes de CADA test de bootstrap: todos parten de la tabla vacía y
    el que la puebla no puede condicionar al siguiente."""
    client, factory = bootstrap_api
    _vaciar_usuarios(factory)
    return client, factory


@pytest.fixture(autouse=True)
def _motor(monkeypatch):
    """El alta provisiona en el motor; sin el doble, todo POST /users sería un 503."""
    return mock_engine(monkeypatch)


# ── Alta: la contraseña por defecto ya no existe ──────────────────────────────────


def test_alta_sin_password_da_422(api):
    client, _, headers = api
    nombre = _nombre("sin-clave")

    resp = client.post("/api/v1/users", headers=headers, json={
        "username": nombre, "email": f"{nombre}@basa.com.ar", "role": "compliance_officer",
    })

    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize("password", [CORTA, ""])
def test_alta_con_password_corta_da_422_en_espanol(api, password):
    """La cadena vacía entra acá y no por el schema: el ``or "basa123"`` la trataba como
    'no me dieron contraseña' y le ponía la conocida."""
    client, _, headers = api

    resp = client.post("/api/v1/users", headers=headers,
                       json=_payload(_nombre("corta"), password))

    assert resp.status_code == 422, resp.text
    detalle = str(resp.json()["detail"])
    assert "12" in detalle
    assert "contraseña" in detalle.lower()


def test_alta_valida_entra_con_su_password_y_no_con_la_de_fabrica(api):
    client, factory, headers = api
    nombre = _nombre("alta-ok")

    resp = client.post("/api/v1/users", headers=headers, json=_payload(nombre, CLAVE_VALIDA))
    assert resp.status_code == 201, resp.text

    assert _login(client, nombre, CLAVE_VALIDA).status_code == 200
    assert _login(client, nombre, "basa123").status_code == 401
    assert _login(client, nombre, "").status_code == 401


def test_el_hash_almacenado_no_es_el_sha256_de_la_password(api):
    client, factory, headers = api
    nombre = _nombre("hash")

    assert client.post("/api/v1/users", headers=headers,
                       json=_payload(nombre, CLAVE_VALIDA)).status_code == 201

    almacenado = _hash_en_db(factory, nombre)
    assert almacenado.startswith("$2")
    assert almacenado != _legacy(CLAVE_VALIDA)
    assert CLAVE_VALIDA not in almacenado


# ── Login: migración perezosa del formato legacy ──────────────────────────────────


def test_login_legacy_rehashea_a_bcrypt_y_el_segundo_login_sigue_entrando(api):
    """Los usuarios ya cargados entran igual, y quedan convertidos sin script de migración.
    El segundo login es la mitad que importa: verifica contra el hash NUEVO."""
    client, factory, _ = api
    nombre = _nombre("legacy")
    _sembrar(factory, nombre, _legacy(CLAVE_VALIDA))

    assert _login(client, nombre, CLAVE_VALIDA).status_code == 200

    convertido = _hash_en_db(factory, nombre)
    assert convertido.startswith("$2"), "el login válido debía dejar el hash en bcrypt"
    assert convertido != _legacy(CLAVE_VALIDA)

    assert _login(client, nombre, CLAVE_VALIDA).status_code == 200
    assert _login(client, nombre, "otra-clave-larga").status_code == 401


def test_login_legacy_con_password_incorrecta_no_toca_el_hash(api):
    """El re-hash cuelga del login VÁLIDO: un intento fallido no puede reescribir nada."""
    client, factory, _ = api
    nombre = _nombre("legacy-fail")
    _sembrar(factory, nombre, _legacy(CLAVE_VALIDA))

    assert _login(client, nombre, "otra-clave-larga").status_code == 401

    assert _hash_en_db(factory, nombre) == _legacy(CLAVE_VALIDA)


def test_login_de_cuenta_con_centinela_no_es_un_500(api):
    """Los clientes sembrados llevan ``!seeded-client-no-login`` en el hash: no verifica en
    ningún formato, y eso es un 401, no un error del servidor."""
    client, factory, _ = api
    nombre = _nombre("centinela")
    _sembrar(factory, nombre, "!seeded-client-no-login")

    assert _login(client, nombre, "!seeded-client-no-login").status_code == 401


# ── Cambio de la contraseña propia ────────────────────────────────────────────────


def test_cambio_propio_rechaza_la_password_actual_incorrecta(api):
    client, factory, _ = api
    nombre = _nombre("propio-mal")
    from src.auth.passwords import hash_password
    _sembrar(factory, nombre, hash_password(CLAVE_VALIDA))
    sesion = _sesion(client, nombre, CLAVE_VALIDA)

    resp = client.post("/api/v1/users/me/password", headers=sesion,
                       json={"current_password": "no-es-la-actual", "new_password": CLAVE_NUEVA})

    assert resp.status_code == 401, resp.text
    # y la credencial sigue siendo la de antes
    assert _login(client, nombre, CLAVE_VALIDA).status_code == 200
    assert _login(client, nombre, CLAVE_NUEVA).status_code == 401


def test_cambio_propio_sin_sesion_da_401(api):
    client, _, _ = api

    resp = client.post("/api/v1/users/me/password",
                       json={"current_password": CLAVE_VALIDA, "new_password": CLAVE_NUEVA})

    assert resp.status_code == 401, resp.text


def test_cambio_propio_con_nueva_corta_da_422(api):
    client, factory, _ = api
    nombre = _nombre("propio-corta")
    from src.auth.passwords import hash_password
    _sembrar(factory, nombre, hash_password(CLAVE_VALIDA))
    sesion = _sesion(client, nombre, CLAVE_VALIDA)

    resp = client.post("/api/v1/users/me/password", headers=sesion,
                       json={"current_password": CLAVE_VALIDA, "new_password": CORTA})

    assert resp.status_code == 422, resp.text
    assert "12" in str(resp.json()["detail"])


def test_cambio_propio_exitoso_reemplaza_la_credencial(api):
    client, factory, _ = api
    nombre = _nombre("propio-ok")
    from src.auth.passwords import hash_password
    _sembrar(factory, nombre, hash_password(CLAVE_VALIDA))
    sesion = _sesion(client, nombre, CLAVE_VALIDA)

    resp = client.post("/api/v1/users/me/password", headers=sesion,
                       json={"current_password": CLAVE_VALIDA, "new_password": CLAVE_NUEVA})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ok"}
    assert _login(client, nombre, CLAVE_NUEVA).status_code == 200
    assert _login(client, nombre, CLAVE_VALIDA).status_code == 401


def test_cambio_propio_sobre_hash_legacy(api):
    """Un usuario heredado tiene que poder cambiar su contraseña sin loguear antes: la
    verificación de la actual también lee el formato viejo."""
    client, factory, _ = api
    nombre = _nombre("propio-legacy")
    _sembrar(factory, nombre, _legacy(CLAVE_VALIDA))
    sesion = _sesion(client, nombre, CLAVE_VALIDA)  # este login ya lo convierte

    resp = client.post("/api/v1/users/me/password", headers=sesion,
                       json={"current_password": CLAVE_VALIDA, "new_password": CLAVE_NUEVA})

    assert resp.status_code == 200, resp.text
    assert _login(client, nombre, CLAVE_NUEVA).status_code == 200


# ── Reseteo por el administrador ──────────────────────────────────────────────────


def _id_de(client, headers, nombre):
    usuarios = client.get("/api/v1/users", headers=headers).json()
    return next(u["id"] for u in usuarios if u["username"] == nombre)


def test_reset_admin_no_exige_la_actual(api):
    client, factory, headers = api
    nombre = _nombre("reset-ok")
    _sembrar(factory, nombre, _legacy("la-vieja-que-nadie-sabe"))
    user_id = _id_de(client, headers, nombre)

    resp = client.post(f"/api/v1/users/{user_id}/password", headers=headers,
                       json={"new_password": CLAVE_NUEVA})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ok"}
    assert _login(client, nombre, CLAVE_NUEVA).status_code == 200
    assert _hash_en_db(factory, nombre).startswith("$2")


def test_reset_de_usuario_inexistente_da_404(api):
    client, _, headers = api

    resp = client.post(f"/api/v1/users/{uuid.uuid4()}/password", headers=headers,
                       json={"new_password": CLAVE_NUEVA})

    assert resp.status_code == 404, resp.text


def test_reset_con_password_corta_da_422(api):
    client, factory, headers = api
    nombre = _nombre("reset-corta")
    from src.auth.passwords import hash_password
    _sembrar(factory, nombre, hash_password(CLAVE_VALIDA))
    user_id = _id_de(client, headers, nombre)

    resp = client.post(f"/api/v1/users/{user_id}/password", headers=headers,
                       json={"new_password": CORTA})

    assert resp.status_code == 422, resp.text
    assert _login(client, nombre, CLAVE_VALIDA).status_code == 200, "no debía cambiar nada"


def test_reset_no_lo_puede_hacer_un_no_admin(api):
    """El reseteo sin contraseña actual es admin-only: si lo pudiera llamar cualquiera con
    sesión, se apropiaría de la cuenta del vecino. Por eso existe /me/password aparte."""
    client, factory, headers = api
    from src.auth.passwords import hash_password
    atacante = _nombre("cliente")
    victima = _nombre("victima")
    _sembrar(factory, atacante, hash_password(CLAVE_VALIDA))
    _sembrar(factory, victima, hash_password(CLAVE_VALIDA))
    sesion = _sesion(client, atacante, CLAVE_VALIDA)
    user_id = _id_de(client, headers, victima)

    resp = client.post(f"/api/v1/users/{user_id}/password", headers=sesion,
                       json={"new_password": CLAVE_NUEVA})

    assert resp.status_code == 403, resp.text
    assert _login(client, victima, CLAVE_NUEVA).status_code == 401


# ── Bootstrap del primer admin ────────────────────────────────────────────────────


def test_bootstrap_crea_el_admin_en_instalacion_virgen(virgen):
    client, factory = virgen

    resp = _login(client, "admin", ADMIN_PASSWORD)

    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["role"] == "tenant_admin"
    assert _hash_en_db(factory, "admin").startswith("$2")


def test_bootstrap_exige_el_minimo_de_longitud(virgen):
    """Sin esto, el arreglo dejaba la puerta principal de una instalación nueva abierta con
    una contraseña de tres letras."""
    client, factory = virgen

    resp = _login(client, "admin", CORTA)

    assert resp.status_code == 422, resp.text
    assert _hash_en_db(factory, "admin") is None, "no debía crear el admin"


@pytest.mark.parametrize("role", ["tenant_admin", "super_admin"])
def test_bootstrap_no_se_dispara_si_la_instalacion_ya_tiene_dueno(virgen, role):
    """El agujero: bastaba con que no existiera el usuario 'admin'. En un despliegue con
    usuarios ya cargados, el primero que golpeaba el login se creaba un tenant_admin con la
    contraseña que quisiera y se quedaba con el tenant.

    Los dos roles administrativos cuentan como dueño porque ninguno se puede crear sin una
    sesión admin: su existencia prueba que la instalación ya tuvo administrador. El
    compliance_officer NO cuenta —quedó read-only en 017/US1—: ese caso lo cubre
    test_bootstrap_se_dispara_aunque_exista_un_auditor."""
    client, factory = virgen
    _sembrar(factory, _nombre("dueno"), _legacy(CLAVE_VALIDA), role=role)

    resp = _login(client, "admin", ADMIN_PASSWORD)

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "Credenciales incorrectas."
    assert _hash_en_db(factory, "admin") is None, "no debía crear el admin"


def test_bootstrap_sobrevive_al_seed_de_clients(virgen):
    """El runbook siembra los clients del perfil ANTES del primer login del dueño.

    Con el gate por 'tabla vacía' esa instalación quedaba sin ningún admin y sin vía de
    crear uno (``POST /users`` es admin-only): bloqueada en sede. Un client sembrado no es
    un dueño, así que el bootstrap sigue disponible."""
    client, factory = virgen
    _sembrar(factory, _nombre("cliente-sembrado"), "!seeded-client-no-login", role="client")

    resp = _login(client, "admin", ADMIN_PASSWORD)

    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["role"] == "tenant_admin"


def test_bootstrap_se_dispara_aunque_exista_un_auditor(virgen):
    """El compliance_officer quedó read-only en toda la matriz 017/US1 (T006, #246/#250): su
    sola existencia ya no prueba que la instalación tuvo un admin. Si una sede se siembra sólo
    con un auditor, el gate por dueño NO debe bloquear el bootstrap —``POST /users`` es
    admin-only, así que sin bootstrap la instalación quedaría sin admin y sin vía de crear uno.
    Un auditor read-only no es un dueño."""
    client, factory = virgen
    _sembrar(factory, _nombre("auditor"), _legacy(CLAVE_VALIDA), role="compliance_officer")

    resp = _login(client, "admin", ADMIN_PASSWORD)

    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["role"] == "tenant_admin"
    assert _hash_en_db(factory, "admin").startswith("$2")


# ── P1 del gate r2: el bootstrap no valida/hashea antes del dueño-gate ─────────────


def test_admin_inexistente_con_dueno_password_corta_es_401_no_422(virgen):
    """Con dueño y sin user 'admin', un login `admin` con password corta es un 401 normal —no
    422—. El 422 (que devolvía el reorden del bootstrap de la r1) filtraba que el bootstrap ES
    posible acá: oráculo de existencia de 'admin'. El pre-check `_es_sin_dueno` deja el
    `validar_password` detrás del dueño-gate."""
    client, factory = virgen
    _sembrar(factory, _nombre("dueno"), _legacy(CLAVE_VALIDA), role="tenant_admin")

    resp = _login(client, "admin", CORTA)

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "Credenciales incorrectas."


def test_admin_inexistente_con_dueno_no_quema_bcrypt(virgen, monkeypatch):
    """Mitad DoS del P1: con dueño y sin user 'admin', el login `admin` NO invoca bcrypt. El
    reorden hasheaba ~250 ms SIN autenticar en cada POST → ~16 req/s saturaban el executor
    acotado con hashes anónimos. El pre-check corta ANTES de hashear."""
    client, factory = virgen
    _sembrar(factory, _nombre("dueno"), _legacy(CLAVE_VALIDA), role="tenant_admin")

    from src.auth import passwords
    hashes = {"n": 0}
    real = passwords.hash_password

    def _spy(raw):
        hashes["n"] += 1
        return real(raw)

    monkeypatch.setattr(passwords, "hash_password", _spy)

    assert _login(client, "admin", ADMIN_PASSWORD).status_code == 401
    assert hashes["n"] == 0, "quemó bcrypt sin pasar el dueño-gate"


# ── P2 del gate r2: clava el P1 de la r1 (conexión NO retenida durante el bcrypt) ──


@pytest.mark.asyncio
async def test_login_no_retiene_conexion_del_pool_durante_bcrypt(monkeypatch):
    """Mientras el bcrypt del login corre en el executor, NINGUNA conexión del pool queda
    retenida. Engine PROPIO (el override de la suite fija una sola conexión y no mide el pool).
    Si una fase de DB dejara de correr en `run_in_threadpool` o retuviera la conexión a través
    del await, `checkedout()` > 0 durante el bloqueo del verify → rojo. Es el test que faltaba:
    nada rojeaba si mañana el fix de la r1 se revierte."""
    dbname = "basa_test_auth_pool"
    fresh_db(dbname)
    run_alembic(dbname, "upgrade", "head")
    engine = owner_engine(dbname)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    _sembrar(factory, "u-pool", hash_password(CLAVE_VALIDA), role="client")

    from src.api.users import LoginRequest, login
    from src.auth import passwords

    en_vuelo = threading.Event()
    soltar = threading.Event()
    capturado = {}

    def _verify_bloqueante(raw, stored):
        capturado["checkedout"] = engine.pool.checkedout()
        en_vuelo.set()
        soltar.wait(timeout=5)
        return True

    monkeypatch.setattr(passwords, "verify_password", _verify_bloqueante)

    db = factory()
    try:
        tarea = asyncio.create_task(
            login(LoginRequest(username="u-pool", password=CLAVE_VALIDA), db))
        # esperar (sin bloquear el loop) a que el verify esté en vuelo dentro del executor
        await asyncio.get_running_loop().run_in_executor(None, lambda: en_vuelo.wait(5))
        assert capturado.get("checkedout") == 0, (
            f"login retuvo {capturado.get('checkedout')} conexión(es) del pool durante el bcrypt")
        soltar.set()
        resp = await tarea
        assert "access_token" in resp
    finally:
        soltar.set()
        db.close()
        engine.dispose()


# ── #239: el ALTA tampoco retiene conexión del pool en NINGUNO de sus dos awaits ──


@pytest.mark.asyncio
async def test_create_user_no_retiene_conexion_del_pool_en_sus_awaits(monkeypatch):
    """Hermano del test de login de acá arriba, para `create_user` (#239).

    El handler es `async` y tiene DOS awaits: el bcrypt y la llamada de red al motor. En los
    dos, `checkedout()` tiene que ser 0. El del motor importa incluso más que el del bcrypt:
    una red colgada retiene la conexión mucho más que los ~250 ms del hash.

    Es un testigo POSITIVO, no un assert negativo que pasaría igual sin el arreglo: el spy se
    instala sobre `passwords.hash_password` Y sobre el nombre reexportado en `api.users`, así
    que también intercepta la llamada SYNC directa del árbol de control. Sobre `7b69313` sin
    el fix, el spy corre con la conexión ya tomada por el query de unicidad y esto rojea con
    `checkedout == 1` — que es el bug del #239 y el P1 de la ronda 2 del #167 a la vez.
    """
    dbname = "basa_test_alta_pool"
    fresh_db(dbname)
    run_alembic(dbname, "upgrade", "head")
    engine = owner_engine(dbname)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    from src.api import users as users_api
    from src.auth import passwords
    from src.schemas.user import UserCreate
    from src.services import ai_engine_client

    capturado = {}
    real_hash = passwords.hash_password

    def _hash_spy(raw):
        capturado["bcrypt"] = engine.pool.checkedout()
        return real_hash(raw)

    async def _motor_spy(user_id):
        capturado["motor"] = engine.pool.checkedout()
        return "engine-uid-239"

    monkeypatch.setattr(passwords, "hash_password", _hash_spy)
    monkeypatch.setattr(users_api, "hash_password", _hash_spy)
    monkeypatch.setattr(ai_engine_client, "create_user", _motor_spy)

    db = factory()
    # El username va por constante y no literal al lado del kwarg `password`: ese par
    # dispara el detector genérico "Username Password" de GitGuardian y pone el PR en rojo
    # por una contraseña de fixture (`CLAVE_VALIDA`, de una DB de test efímera). De paso, el
    # nombre se usa dos veces y acá se escribe una.
    usuario = "alta-pool"
    try:
        creado = await users_api.create_user(
            UserCreate(username=usuario, email=f"{usuario}@basa.com.ar",
                       role="admin", password=CLAVE_VALIDA),
            db,
        )
        # Los dos awaits se ejercieron de verdad: sin esto, un handler que dejara de hashear
        # o de provisionar pasaría el test por ausencia en vez de por invariante.
        assert "bcrypt" in capturado, "el alta no llegó a hashear: el testigo no midió nada"
        assert "motor" in capturado, "el alta no llamó al motor: el testigo no midió nada"

        assert capturado["bcrypt"] == 0, (
            f"el alta retuvo {capturado['bcrypt']} conexión(es) del pool durante el bcrypt")
        assert capturado["motor"] == 0, (
            f"el alta retuvo {capturado['motor']} conexión(es) del pool durante la llamada "
            "de red al motor")

        assert creado.engine_user_id == "engine-uid-239"
        assert creado.username == usuario
    finally:
        db.close()
        engine.dispose()
