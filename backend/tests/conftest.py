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

# Unit tests need a JWT secret; fail-closed behaviour is tested explicitly by
# clearing this env in the relevant test.
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-with-at-least-32-chars-xxx")
os.environ.setdefault("FERNET_SECRET_KEY", "")  # encryption off in unit tests

# Headroom module is optional/fail-open; tests that need it set the env themselves.
os.environ.setdefault("COMPRESSION_HEADROOM_ENABLED", "true")