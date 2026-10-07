"""057 R40 — migración del default de la etiqueta de un id publicado (`label_mode` → `requested`). Offline, sin Postgres.

Solo cambia el DEFAULT de la columna: no reescribe filas (lo que un administrador dejó en `destination` o `custom` es
suyo), no toca la restricción CHECK ni la RLS, y baja al valor anterior."""
import io
import re
from pathlib import Path

import pytest

alembic = pytest.importorskip("alembic")
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
MIGR = ROOT / "sentinel" / "migrations"
ENV = "ALEMBIC_EXTRA_VERSION_LOCATIONS"
REV, PREV = "0529902015ad", "89a92524eef6"
TABLE = "sentinel_redirect_published_model"


def _cfg(buf=None):
    cfg = Config(str(ROOT / "backend" / "alembic.ini"), output_buffer=buf)
    cfg.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    return cfg


@pytest.fixture(autouse=True)
def _ubicacion(monkeypatch):
    monkeypatch.setenv(ENV, str(MIGR))


def test_la_migracion_tiene_id_hash_cuelga_de_la_anterior_y_es_la_cabeza_de_la_extension():
    from src import migration_locations as ml
    script = ScriptDirectory.from_config(_cfg())
    ml.extend_script_directory(script)
    rev = script.get_revision(REV)
    assert re.fullmatch(r"[0-9a-f]{12}", rev.revision) and rev.down_revision == PREV
    assert REV in script.get_heads() and PREV not in script.get_heads()


def test_upgrade_solo_cambia_el_default_y_no_reescribe_filas():
    buf = io.StringIO()
    command.upgrade(_cfg(buf), f"{PREV}:{REV}", sql=True)
    sql = buf.getvalue()
    assert f"ALTER TABLE {TABLE} ALTER COLUMN label_mode SET DEFAULT 'requested'" in sql
    assert not re.search(r"\bUPDATE (?!alembic_version)|\bDELETE\b|DROP CONSTRAINT|POLICY", sql), "no toca filas, CHECK ni RLS"


def test_downgrade_vuelve_al_default_anterior():
    buf = io.StringIO()
    command.downgrade(_cfg(buf), f"{REV}:{PREV}", sql=True)
    assert f"ALTER TABLE {TABLE} ALTER COLUMN label_mode SET DEFAULT 'destination'" in buf.getvalue()


def test_el_orm_tiene_el_mismo_default_que_la_migracion():
    from sentinel.redirect import models as m
    col = m.RedirectPublishedModel.__table__.c.label_mode
    assert col.default.arg == "requested" and col.server_default.arg == "requested"
