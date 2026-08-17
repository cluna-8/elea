"""Pytest config for Basa Secure AI Gateway smoke tests (F0-7).

Makes ``src`` importable and ensures a JWT secret is present for unit tests that
touch the session module. Live integration tests (against http://localhost:8081)
self-skip when the backend is not reachable.
"""
import os
import sys
from pathlib import Path

import pytest

# Put backend/src on the path so `from src.services...` and package imports work.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "src"))

# Librería compartida basa_guardian_policy (spec 014): vive en <repo>/litellm/extensions
# (montada como /app/litellm_config/extensions dentro del container backend). Se importa
# como `from extensions import basa_guardian_policy` desde ambos hogares.
for _shared in (BACKEND_ROOT / "litellm_config", BACKEND_ROOT.parent / "litellm"):
    if (_shared / "extensions").is_dir():
        sys.path.insert(0, str(_shared))
        break

# Unit tests need a JWT secret; fail-closed behaviour is tested explicitly by
# clearing this env in the relevant test.
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-with-at-least-32-chars-xxx")
os.environ.setdefault("FERNET_SECRET_KEY", "")  # encryption off in unit tests

# Headroom module is optional/fail-open; tests that need it set the env themselves.
os.environ.setdefault("COMPRESSION_HEADROOM_ENABLED", "true")

# Motor de detección NLP: APAGADO en la suite (issue #63). El servicio `backend` del compose
# —donde corre esta suite— trae `NLP_ANALYZER_URL` cableada, pero el sidecar `nlp-analyzer`
# NO se levanta para los tests. Con la env puesta y nadie contestando, todo el plano `/gw`
# resolvería fail-closed y la suite mediría "el sidecar no está" en vez de la política.
#
# Se BORRA en vez de apuntarla a un doble global: el camino NLP es exactamente lo que el #63
# vino a hacer verificable, así que los tests que lo ejercitan la setean ELLOS
# (`monkeypatch.setenv`) y doblan `presidio_analyze` — la misma disciplina que ya usan los
# tests del guardrail del motor con `_PRESIDIO_URL`. Un doble global escondería qué test
# depende del NLP y cuál no.
os.environ.pop("NLP_ANALYZER_URL", None)

# Reconciliación de seats (spec 021 US3): scheduler APAGADO en la suite. Los
# tests que usan `with TestClient(app)` disparan el lifespan, y el scheduler
# real correría contra SessionLocal (la DB VIVA del compose, no la DB de test
# del override de get_db), commiteando audit ahí y contaminando el registry
# global. Los tests de US3 arrancan el scheduler con interval explícito.
os.environ.setdefault("BASA_LICENSE_RECONCILE_INTERVAL_SECONDS", "0")

# Purga de retención (spec 018 FR-001): scheduler APAGADO en la suite, por el MISMO motivo
# que la reconciliación de arriba y con una consecuencia peor. El job corre contra
# SessionLocal —la DB VIVA del compose, no la DB de test del override de get_db— y lo que
# hace es BORRAR FILAS de audit_logs: un `TestClient(app)` que dispare el lifespan con la
# purga encendida se lleva puesta la auditoría de la caja de desarrollo, en silencio y sin
# forma obvia de atarlo a un test. Los tests de la purga la arrancan ELLOS, con
# session_factory e intervalo explícitos.
os.environ.setdefault("BASA_PURGE_ENABLED", "false")

# Licencia dev de la suite (spec 021): el enforcement es fail-closed, así que
# sin un entitlement válido TODA creación de Connection/Client devolvería
# 402/403 y rompería los tests preexistentes. Se emite un token efímero para
# el tenant default ANTES de cualquier import de src.main; los tests negativos
# de licencia overridean el env y llaman entitlement.initialize(force=True).
from license_fixtures import install_default_test_license  # noqa: E402

install_default_test_license()


@pytest.fixture(autouse=True)
def _reset_presidio_http_client_singleton():
    """`presidio_analyze` reusa un `httpx.AsyncClient` módulo-level (#167). Sin
    resetearlo, el PRIMER test que lo crea (con lo que sea que `httpx.AsyncClient`
    esté monkeypatcheado en ESE momento) deja el objeto cacheado para TODOS los tests
    que corran después en la sesión — aunque vuelvan a monkeypatchear `httpx.AsyncClient`
    con su propio doble, `_get_http_client()` ve el singleton ya no-None y nunca
    reconstruye.

    Autouse GLOBAL (no por-archivo) a propósito: `basa_guardian_policy.py` se importa
    por DOS caminos distintos en esta suite (`from extensions import
    basa_guardian_policy` vs el `import basa_guardian_policy` a secas de
    `basa_guardrail.py`, que se agrega su propio directorio a `sys.path`) — son DOS
    entradas de `sys.modules` con globals INDEPENDIENTES. Un reset local a un solo
    archivo de test sólo limpia UNA de las dos copias; cualquier test en OTRO archivo
    que pase por el otro camino de import sigue viendo el singleton viejo. Se resetean
    las dos, si están cargadas."""
    for _modname in ("basa_guardian_policy", "extensions.basa_guardian_policy"):
        _mod = sys.modules.get(_modname)
        if _mod is not None:
            _mod._http_client = None
    yield
    for _modname in ("basa_guardian_policy", "extensions.basa_guardian_policy"):
        _mod = sys.modules.get(_modname)
        if _mod is not None:
            _mod._http_client = None
