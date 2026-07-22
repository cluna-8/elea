"""Fixtures e2e (spec 019) — corren contra el STACK VIVO, no TestClient.

A diferencia de ``tests/integration`` (TestClient + httpx mockeado), esta suite cruza
procesos de verdad: ``gateway (backend:8000) → motor LiteLLM (litellm:4000) → Postgres
(db:5432) → custom_auth → BasaGuardrail``. Se corre desde un container efímero unido a
la red del compose::

    docker compose -p basa-guardian run --rm --no-deps backend pytest tests/e2e/ -v

El seed de la Connection (=``APIKey``) se inserta en la MISMA base ``basa_gateway`` vía
SQLAlchemy directo (``SessionLocal``), así el gateway y el motor la resuelven por HTTP.
``user_id=NULL`` evita colisión con el índice único ``(tenant_id, user_id, tool_type)``
(en Postgres los NULL son distintos entre sí). El GUC de RLS queda sin setear → aplica
la policy permisiva ``tenant_isolation_bootstrap``, la MISMA ventana pre-tenant que usa
el gateway para resolver keys (``_resolve_attribution`` abre ``SessionLocal`` sin
``tenant_context``). Cleanup SIEMPRE (teardown en ``finally``, aun si el test falla).
"""
import os
import time
import urllib.error
import urllib.request
import uuid
import warnings

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

# ``tests/conftest.py`` (parent, se importa antes que este) ya puso backend/ y backend/src
# en sys.path, así que estos imports de producción resuelven dentro del container.
from src.database import SessionLocal
from src.models.budget import APIKey
from src.models.tenant import DEFAULT_TENANT_ID
from src.models.user import User
from src.services.key_material import hash_key, key_preview

# Puerta única del gateway sobre HTTP vivo. Override por env para correr fuera del
# compose (p.ej. contra el puerto publicado 8091), default = DNS interno de la red.
_BASE_URL = os.getenv("BASA_E2E_BASE_URL", "http://backend:8000/api/v1/gw")

# Margen del teardown para la CARRERA CON EL MOTOR (flaky #41). El logger del motor audita
# en un callback asíncrono (``async_log_success_event``) que corre DESPUÉS de que el gateway
# ya respondió: cuando el test termina, el INSERT en ``audit_logs`` que referencia a esta
# Connection puede estar todavía en vuelo, y el ``DELETE FROM api_keys`` del teardown se
# lleva un ``ForeignKeyViolation`` (``audit_logs_api_key_id_fkey``). Nada de esto es de la
# 027 — es el orden entre dos procesos.
#
# Purgar-y-borrar de una sola pasada NO alcanza, y está medido: con el DELETE de
# ``audit_logs`` primero, en la MISMA transacción, el INSERT del motor entró ENTRE las dos
# sentencias y el commit explotó igual. Por eso el borrado es idempotente y REINTENTADO
# hasta este margen: cada reintento vuelve a purgar lo que haya aparecido mientras tanto.
_TEARDOWN_MARGEN_S = float(os.getenv("BASA_E2E_TEARDOWN_MARGEN_S", "15"))
_TEARDOWN_PASO_S = 0.5


def _filtro_audit(api_key_id=None, user_id=None):
    """``(where, params)`` de las filas de ``audit_logs`` que referencian lo sembrado.

    Scopeado por tenant a propósito (misma disciplina que el resto del repo: nadie toca
    filas de otro tenant, ni en un teardown). Si el motor escribiera la fila con OTRO
    tenant, este filtro no la vería, el borrado terminaría avisando y ese aviso sería el
    hallazgo — que es exactamente de lo que uno querría enterarse."""
    cond, params = [], {"t": DEFAULT_TENANT_ID}
    if api_key_id is not None:
        cond.append("api_key_id = :k")
        params["k"] = api_key_id
    if user_id is not None:
        cond.append("user_id = :u")
        params["u"] = user_id
    if not cond:
        return None, params
    return f"tenant_id = :t AND ({' OR '.join(cond)})", params


def _filas_audit(db, api_key_id=None, user_id=None) -> int:
    """Cuántas filas de ``audit_logs`` quedan referenciando lo sembrado (solo para el
    aviso del teardown)."""
    where, params = _filtro_audit(api_key_id, user_id)
    if where is None:
        return 0
    db.rollback()   # una transacción abortada previa deja la sesión inutilizable
    return int(db.execute(text(f"SELECT count(*) FROM audit_logs WHERE {where}"),
                          params).scalar() or 0)


def _borrar_sin_carrera(db, api_key_id=None, user_id=None) -> None:
    """Teardown resistente a la carrera con el motor: purga las filas de ``audit_logs``
    que referencian lo sembrado y RECIÉN AHÍ borra la Connection (y el usuario, si hay).

    Reintenta hasta ``_TEARDOWN_MARGEN_S`` porque el INSERT del motor puede llegar tarde:
    cada vuelta re-purga y re-intenta el borrado. Si el INSERT aterriza DESPUÉS del commit
    del teardown no hay nada que arreglar — el que falla entonces es el logger del motor,
    que ya trata su INSERT como best-effort (``[basa-audit] INSERT no fatal``), y lo único
    que se pierde es la fila de auditoría de una key sintética de test.

    Y no borra en silencio: si tras el margen la fila referenciante sigue ahí, el problema
    dejó de ser la carrera conocida (se resuelve en menos de un segundo) y el teardown lo
    DICE con warning, además de dejar la Connection inerte — una virtual key de test viva
    en la base es residuo de credencial, no un detalle cosmético."""
    limite = time.monotonic() + _TEARDOWN_MARGEN_S
    borrado = [(APIKey, api_key_id), (User, user_id)]   # la key primero: api_keys.user_id → users
    where, params = _filtro_audit(api_key_id, user_id)
    while True:
        try:
            db.rollback()
            if where is not None:
                db.execute(text(f"DELETE FROM audit_logs WHERE {where}"), params)
            for modelo, pk in borrado:
                obj = db.get(modelo, pk) if pk is not None else None
                if obj is not None:
                    db.delete(obj)
            db.commit()
            return
        except IntegrityError:
            db.rollback()
            if time.monotonic() >= limite:
                break
            time.sleep(_TEARDOWN_PASO_S)

    quedan = _filas_audit(db, api_key_id, user_id)
    for modelo, pk in borrado:
        obj = db.get(modelo, pk) if pk is not None else None
        if obj is not None:
            obj.is_active = False
    db.commit()
    warnings.warn(
        f"teardown e2e: no se pudo borrar lo sembrado tras {_TEARDOWN_MARGEN_S:g}s "
        f"(api_key_id={api_key_id}, user_id={user_id}); quedan {quedan} filas de audit_logs "
        f"referenciándolo en el tenant del fixture. Se dejó desactivado, NO borrado.",
        stacklevel=2,
    )


@pytest.fixture(scope="session")
def base_url() -> str:
    return _BASE_URL


@pytest.fixture
def borrado_sin_carrera():
    """Expone ``_borrar_sin_carrera`` a los fixtures que viven en los módulos de test:
    todo lo que se siembra para un pedido byok compite con el logger del motor, así que
    el teardown tiene que ser el MISMO en todos (si no, el flaky #41 vuelve por la otra
    puerta)."""
    return _borrar_sin_carrera


@pytest.fixture(scope="session", autouse=True)
def live_stack(base_url):
    """e2e = opcional: si el gateway no responde (CI sin stack), skip toda la suite en
    vez de fallar. Con el stack vivo, ``GET /gw`` devuelve 200 (gw_info) y los tests
    corren de verdad."""
    try:
        with urllib.request.urlopen(base_url, timeout=3) as resp:
            if resp.status != 200:
                pytest.skip(f"gateway respondió {resp.status} en {base_url}; e2e requiere stack vivo")
    except (urllib.error.URLError, OSError) as exc:
        pytest.skip(f"stack no vivo ({base_url}): {exc}; e2e opcional sin stack")


@pytest.fixture
def gw(base_url):
    """Cliente HTTP síncrono apuntado a la puerta única (timeout holgado: byok cruza
    hasta el motor)."""
    with httpx.Client(base_url=base_url, timeout=120.0) as client:
        yield client


@pytest.fixture
def monitor_headers():
    """Header de sesión para leer el feed del monitor (spec 027, hallazgo A1).

    ``GET /gw/events`` dejó de ser público: publica la atribución por capa de cada pedido
    —qué capa bloqueó y cuáles no corrieron, la postura de seguridad del tenant— y ahora exige
    sesión de ``admin``/``compliance_officer``. Una virtual key **no** sirve: no resuelve a un
    usuario de sesión (``rbac.require_role``), que es justamente el diseño.

    El token se firma en proceso en vez de hacer login por HTTP porque este container corre
    con el MISMO ``JWT_SECRET_KEY`` que el backend vivo (misma definición de servicio en el
    compose), así que el backend lo acepta; y así el fixture no depende de que exista un admin
    con contraseña conocida en la instalación. Teardown siempre: el usuario se borra en
    ``finally`` aunque el test falle.
    """
    from src.auth.session import create_session_token

    rand = uuid.uuid4().hex[:8]
    db = SessionLocal()
    user = User(
        tenant_id=DEFAULT_TENANT_ID,
        username=f"e2e-monitor-{rand}",
        email=f"e2e-monitor-{rand}@e2e.local",
        password_hash="!e2e-no-login",
        role="tenant_admin",       # el rol canónico post-013 que el shim expande a 'admin'
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    user_id = user.id
    token = create_session_token(str(user.id), user.role, user.username)
    try:
        yield {"Authorization": f"Bearer {token}"}
    finally:
        # Este usuario es de sesión (lee el feed), no atribuye pedidos byok; aun así el
        # borrado va por el mismo camino: ``audit_logs.user_id`` también lo referencia y
        # la carrera con el motor no distingue para qué se sembró la fila.
        _borrar_sin_carrera(db, user_id=user_id)
        db.close()


@pytest.fixture
def seeded_byok_key():
    """Seedea una Connection byok activa (=``APIKey``) en la base compartida y devuelve
    su virtual key en claro. Teardown: purga la auditoría que la referencia y borra la
    fila por id, reintentando contra la carrera con el motor (#41); ``finally`` → siempre,
    aun si el test falla. ``user_id=NULL`` → sin colisión con el índice único parcial."""
    rand = uuid.uuid4().hex[:8]
    plain = f"sk-basa-e2e-{rand}"
    db = SessionLocal()
    row = APIKey(
        key_hash=hash_key(plain),
        tenant_id=DEFAULT_TENANT_ID,
        key_preview=key_preview(plain),
        name=f"e2e-conn-{rand}",
        tool_type="chat-ui",
        upstream_mode="byok",
        is_active=True,
        user_id=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    key_id = row.id
    try:
        yield plain
    finally:
        _borrar_sin_carrera(db, api_key_id=key_id)
        db.close()
