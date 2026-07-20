"""Exporta el esquema OpenAPI del backend (spec 022 US5, FR-016 — single source).

El API reference del sitio de docs se GENERA de este export: jamás se escriben
páginas de endpoints a mano. Determinista (sort_keys) para que el check de deriva
pueda diffear. El import de src.main sobrevive sin DB (alembic/licensing fail-soft),
así que el export no necesita el stack completo.

Uso:  docker compose run --rm --no-deps backend python scripts/export_openapi.py
      (stdout → docs/docs/api-reference/openapi.json; ver make -C deploy docs-openapi)
"""
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from src.main import app  # noqa: E402

json.dump(app.openapi(), sys.stdout, indent=2, sort_keys=True, ensure_ascii=False)
sys.stdout.write("\n")
