"""Migraciones adicionales (seam de extensión): ALEMBIC_EXTRA_VERSION_LOCATIONS.

Sin la env, alembic ve exactamente el árbol del core y se sigue migrando a `head` (las
~15 harness que llaman `upgrade head` no cambian). Con la env, se suman los directorios
extra como `version_locations` y los entrypoints migran a `heads` (cada extensión es su
propia rama). Todo corre en modo offline (--sql): no hace falta Postgres.
"""
import io
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from src import migration_locations as ml

BACKEND = Path(__file__).resolve().parents[2]
ENV = "ALEMBIC_EXTRA_VERSION_LOCATIONS"

_MIGRACION_EXTRA = '''
from alembic import op

revision = "ext0001"
down_revision = None
branch_labels = ("ext_test",)
depends_on = None


def upgrade():
    op.execute("SELECT 'ext-marker-{tag}'")


def downgrade():
    pass
'''


def _cfg(buf=None):
    cfg = Config(str(BACKEND / "alembic.ini"), output_buffer=buf)
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def _dir_extra(tmp_path, tag="a", rev="ext0001"):
    d = tmp_path / f"versions_{tag}"
    d.mkdir()
    src = _MIGRACION_EXTRA.format(tag=tag).replace("ext0001", rev).replace("ext_test", f"ext_{tag}")
    (d / f"{rev}_extra.py").write_text(src)
    return d


# ── Parseo de la env ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("valor", [None, "", "  ", f" ,{os.pathsep} "])
def test_sin_env_no_hay_extras_y_el_target_es_head(monkeypatch, valor):
    if valor is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, valor)
    assert ml.extra_version_locations() == []
    assert ml.upgrade_target() == "head"


def test_separa_por_coma_y_por_pathsep(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV, f"/a, /b{os.pathsep}/c")
    assert ml.extra_version_locations() == ["/a", "/b", "/c"]
    assert ml.upgrade_target() == "heads"


# ── ScriptDirectory ───────────────────────────────────────────────────────────────
def test_sin_env_el_script_directory_queda_intacto(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    script = ScriptDirectory.from_config(_cfg())
    heads_antes = script.get_heads()
    ml.extend_script_directory(script)
    assert script.version_locations is None
    assert script.get_heads() == heads_antes
    assert len(heads_antes) == 1


def test_con_env_suma_la_rama_extra(monkeypatch, tmp_path):
    extra = _dir_extra(tmp_path)
    monkeypatch.setenv(ENV, str(extra))
    script = ScriptDirectory.from_config(_cfg())
    (core_head,) = ScriptDirectory.from_config(_cfg()).get_heads()
    ml.extend_script_directory(script)
    assert str(extra) in script.version_locations
    assert str(BACKEND / "alembic" / "versions") in script.version_locations
    assert set(script.get_heads()) == {core_head, "ext0001"}


def test_directorio_inexistente_falla_explicito(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV, str(tmp_path / "no-existe"))
    script = ScriptDirectory.from_config(_cfg())
    with pytest.raises(ml.MigrationLocationError, match="no-existe"):
        ml.extend_script_directory(script)


def test_idempotente(monkeypatch, tmp_path):
    extra = _dir_extra(tmp_path)
    monkeypatch.setenv(ENV, str(extra))
    script = ScriptDirectory.from_config(_cfg())
    ml.extend_script_directory(script)
    ml.extend_script_directory(script)
    assert script.version_locations.count(str(extra)) == 1


# ── De punta a punta por env.py (lo mismo que hace `alembic upgrade` del CLI) ────────
def test_env_py_sin_env_migra_solo_el_core(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    buf = io.StringIO()
    command.upgrade(_cfg(buf), "head", sql=True)
    assert "ext-marker" not in buf.getvalue()


def test_env_py_con_env_aplica_las_ramas_extra(monkeypatch, tmp_path):
    a = _dir_extra(tmp_path, "a", "exta001")
    b = _dir_extra(tmp_path, "b", "extb001")
    monkeypatch.setenv(ENV, f"{a},{b}")
    buf = io.StringIO()
    command.upgrade(_cfg(buf), ml.upgrade_target(), sql=True)
    sql = buf.getvalue()
    assert "ext-marker-a" in sql and "ext-marker-b" in sql


# ── El arranque de la app usa `heads` sólo con la env ─────────────────────────────
@pytest.mark.parametrize("valor,esperado", [(None, "head"), ("/x", "heads")])
def test_main_elige_target(monkeypatch, valor, esperado):
    import src.main as main

    if valor is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, valor)
    monkeypatch.setenv("RUN_ALEMBIC_ON_STARTUP", "true")
    llamados = []
    monkeypatch.setattr(command, "upgrade", lambda cfg, rev: llamados.append(rev))
    main._run_alembic_upgrade_head()
    assert llamados == [esperado]
