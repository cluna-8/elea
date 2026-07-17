"""Pytest config for Basa Secure AI Gateway smoke tests (F0-7).

Makes ``src`` importable and ensures a JWT secret is present for unit tests that
touch the session module. Live integration tests (against http://localhost:8081)
self-skip when the backend is not reachable.
"""
import os
import sys
from pathlib import Path

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

# Reconciliación de seats (spec 021 US3): scheduler APAGADO en la suite. Los
# tests que usan `with TestClient(app)` disparan el lifespan, y el scheduler
# real correría contra SessionLocal (la DB VIVA del compose, no la DB de test
# del override de get_db), commiteando audit ahí y contaminando el registry
# global. Los tests de US3 arrancan el scheduler con interval explícito.
os.environ.setdefault("BASA_LICENSE_RECONCILE_INTERVAL_SECONDS", "0")

# Licencia dev de la suite (spec 021): el enforcement es fail-closed, así que
# sin un entitlement válido TODA creación de Connection/Client devolvería
# 402/403 y rompería los tests preexistentes. Se emite un token efímero para
# el tenant default ANTES de cualquier import de src.main; los tests negativos
# de licencia overridean el env y llaman entitlement.initialize(force=True).
from license_fixtures import install_default_test_license  # noqa: E402

install_default_test_license()