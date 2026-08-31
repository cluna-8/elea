"""Harness compartido de los tests del gate de seats (spec 021, US2).

Monta la app FastAPI real contra una DB fresca migrada a head, con el motor
(ai_engine_client) mockeado como RECORDER: los tests del gate afirman tanto la
respuesta HTTP como que NO hubo provisioning al motor (FR-008: el rechazo es
ANTES de generate_key).
"""
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from license_fixtures import issue_files
from migration_harness import fresh_db, owner_engine, run_alembic


def build_app_client(dbname):
    """DB fresca → head + app real con get_db overrideado.

    Devuelve (client, factory, cleanup). El caller es dueño del ciclo de vida
    (fixture de módulo con yield + cleanup()).
    """
    fresh_db(dbname)
    run_alembic(dbname, "upgrade", "head")
    engine = owner_engine(dbname)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    from src.database import get_db
    from src.main import app

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    def cleanup():
        app.dependency_overrides.clear()
        engine.dispose()

    return client, factory, cleanup


def admin_headers(client):
    """Bootstrap del primer admin: sobre la tabla users VACÍA de la DB fresca, el login de
    'admin' lo crea (tenant_admin). La contraseña respeta el mínimo del producto porque el
    bootstrap ya no acepta cualquier cosa."""
    resp = client.post("/api/v1/users/login",
                       json={"username": "admin", "password": "gate-pass-12345"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


#: Contraseña de los usuarios minteados por `headers_for_role` (respeta el mínimo del
#: producto, que `validar_password` exige incluso en el bootstrap).
ROLE_PASS = "matriz-rol-superficie-12345"


def headers_for_role(client, factory, rol, *, display_label=None, sufijo="", prefijo="rol"):
    """Mintéa un usuario del rol canónico por DB directa (bypass del gate de seats de POST
    /users: lo que probamos es el rol, no la licencia) con hash real, y devuelve su sesión.

    Vive acá y no en un módulo de tests porque ya la usan dos superficies (la matriz-ley de
    `test_role_matrix.py` y la config SSO de `test_sso_config_api.py`) y era la tercera copia
    del mismo minteo — `test_router_config_api.py:_headers_no_admin` es la segunda.

    Ojo con el orden respecto de `admin_headers`: el bootstrap del primer admin sólo corre si
    la instalación no tiene dueño, y `ROLES_QUE_PRUEBAN_DUENO` (`api/users.py`) son SÓLO
    `tenant_admin`/`super_admin`. Mintear un `compliance_officer`, `client` o `lectura` antes
    del bootstrap NO lo bloquea; mintear un admin, SÍ.
    """
    from src.auth.passwords import hash_password
    from src.models.user import User

    # @sentinel.com.ar (no .test): UserResponse.email es EmailStr y rechaza el TLD reservado .test,
    # con lo que GET /users —que serializa a todos— explotaría al listar estos usuarios.
    nombre = f"{prefijo}-{rol.value}{sufijo}-{uuid.uuid4().hex[:8]}"
    db = factory()
    try:
        db.add(User(
            username=nombre, email=f"{nombre}@sentinel.com.ar",
            password_hash=hash_password(ROLE_PASS), role=rol.value,
            display_label=display_label, is_active=True,
        ))
        db.commit()
    finally:
        db.close()

    login = client.post("/api/v1/users/login", json={"username": nombre, "password": ROLE_PASS})
    assert login.status_code == 200, f"login {rol.value}: {login.text}"
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def rechazo_por_rol(rol):
    """El texto propio de `rbac.require_role` — lo que distingue un 403-por-ROL de cualquier
    otro 403 de la misma superficie (el de licencia, sin ir más lejos)."""
    return f"Acción no permitida para el rol '{rol.value}'"


def set_license(monkeypatch, tmp_path, **payload_overrides):
    """Emite un token efímero, apunta el env ahí y recarga el entitlement."""
    from src.licensing import entitlement
    keyset_path, lic_path, _priv = issue_files(tmp_path, payload_overrides or None)
    monkeypatch.delenv("SENTINEL_LICENSE_TOKEN", raising=False)
    monkeypatch.setenv("SENTINEL_LICENSE_PUBLIC_KEYS_FILE", str(keyset_path))
    monkeypatch.setenv("SENTINEL_LICENSE_TOKEN_FILE", str(lic_path))
    return entitlement.initialize(force=True, emit_audit=False)


def clear_license(monkeypatch):
    """Degradado por token ausente (FR-006): para probar el fail-closed del gate."""
    from src.licensing import entitlement
    monkeypatch.delenv("SENTINEL_LICENSE_TOKEN", raising=False)
    monkeypatch.setenv("SENTINEL_LICENSE_TOKEN_FILE", "/no/existe/token.lic")
    return entitlement.initialize(force=True, emit_audit=False)


def restore_suite_license():
    """Vuelve a la licencia dev de la suite (conftest) tras un test negativo."""
    from src.licensing import entitlement
    entitlement.initialize(force=True, emit_audit=False)


def seed_active_seats(factory, n, *, rpm_limit=60, prefix="seed", tenant_id=None):
    """N Connections ACTIVAS por DB directa; tenant default salvo ``tenant_id``
    explícito (tests de aislamiento de la reconciliación, T023).

    user_id queda NULL a propósito: el índice parcial
    uq_api_keys_tenant_user_tool no colisiona entre NULLs, así que N seats
    'anónimos' conviven con la misma tool.
    """
    from src.models.budget import APIKey
    db = factory()
    try:
        rows = []
        for i in range(n):
            row = APIKey(
                name=f"{prefix}-{i}",
                key_hash=f"hash-{prefix}-{uuid.uuid4()}",
                key_preview=f"sk-...{prefix}{i}",
                tool_type="claude-code",
                rpm_limit=rpm_limit,
                **({"tenant_id": tenant_id} if tenant_id is not None else {}),
            )
            db.add(row)
            rows.append(row)
        db.commit()
        return [row.id for row in rows]
    finally:
        db.close()


class EngineRecorder:
    """Doble del motor: registra provisioning para afirmar que NO ocurrió."""

    def __init__(self):
        self.generate_key_calls = []
        self.create_user_calls = []
        self.delete_key_calls = []


def mock_engine(monkeypatch):
    """Patchea ai_engine_client A NIVEL MÓDULO (keys.py y users.py referencian
    el mismo objeto módulo de services)."""
    from src.services import ai_engine_client
    recorder = EngineRecorder()

    async def fake_generate_key(**kwargs):
        recorder.generate_key_calls.append(kwargs)
        suffix = uuid.uuid4().hex
        return {"plain_key": f"sk-sentinel-{suffix}", "engine_key_token": f"sk-eng-{suffix}"}

    async def fake_create_user(user_id):
        recorder.create_user_calls.append(user_id)
        return f"engine-{uuid.uuid4().hex[:8]}"

    async def fake_delete_key(engine_key_token):
        recorder.delete_key_calls.append(engine_key_token)

    monkeypatch.setattr(ai_engine_client, "generate_key", fake_generate_key)
    monkeypatch.setattr(ai_engine_client, "create_user", fake_create_user)
    monkeypatch.setattr(ai_engine_client, "delete_key", fake_delete_key)
    return recorder


def clear_monotonic_mark(factory):
    """Resetea la marca anti-rollback (US5): los tests que inyectan relojes
    futuros la dejarían por delante del reloj real y el test siguiente del
    módulo abriría un episodio de rollback espurio."""
    from src.models.license_state import LicenseRuntimeState
    db = factory()
    try:
        db.query(LicenseRuntimeState).update({"monotonic_ts": None})
        db.commit()
    finally:
        db.close()


def create_tenant(factory, slug):
    """Tenant extra por DB directa (tests de aislamiento/reconciliación, US3)."""
    from src.models.tenant import Tenant
    db = factory()
    try:
        row = Tenant(name=slug, slug=slug)
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def current_seats(factory):
    """Conteo REAL de seats del tenant default con la misma definición del
    producto. Los tests fijan max_seats RELATIVO a esto (nunca constantes
    mágicas): cada test es autosuficiente e independiente del orden."""
    from migration_harness import DEFAULT_TENANT
    from src.licensing.seat_counter import count_active_seats
    db = factory()
    try:
        return count_active_seats(db, DEFAULT_TENANT)
    finally:
        db.close()


def license_audit_events(factory):
    from src.models.audit import AuditLog
    db = factory()
    try:
        rows = (db.query(AuditLog)
                .filter(AuditLog.model == "license")
                .order_by(AuditLog.timestamp).all())
        return [row.guardian_events[0] for row in rows]
    finally:
        db.close()
