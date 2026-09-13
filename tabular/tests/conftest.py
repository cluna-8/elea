"""Los tests nunca tocan /data: el módulo `app.main` crea el store al importarse."""
import os
import tempfile

os.environ.setdefault("TABULAR_DATA_DIR", tempfile.mkdtemp(prefix="tabular-tests-"))
os.environ.setdefault("TABULAR_INTERNAL_TOKEN", "test-internal-token")
