"""Migraciones propias de la 068 en modo offline (`--sql`), sin Postgres ni Docker (T027/T028).

Dos niveles:
1. Autocontenido: un árbol mínimo con una `010` de mentira (crea `tenants`) + las migraciones
   de `sentinel/migrations/` como rama extra. Fija la forma: rama propia, id hash, tablas,
   RLS con el patrón de la 010, visibilidad de destinos de instalación solo por oferta.
2. Con el árbol REAL del backend y la costura S4 (`ALEMBIC_EXTRA_VERSION_LOCATIONS`), si el
   venv del backend está disponible (si no, se saltea): `upgrade heads --sql` incluye la rama.
"""
import io
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MIGR = ROOT / "sentinel" / "migrations"
BACKEND = ROOT / "backend"
TABLES = ("sentinel_redirect_policy", "sentinel_redirect_posture", "sentinel_redirect_destination",
          "sentinel_redirect_offer", "sentinel_redirect_published_model", "sentinel_redirect_rule",
          "sentinel_redirect_config_audit", "sentinel_redirect_fidelity_report")

alembic = pytest.importorskip("alembic")
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

_ENV = '''
from alembic import context
context.configure(url="postgresql://x/y", literal_binds=True, dialect_opts={"paramstyle": "named"})
with context.begin_transaction():
    context.run_migrations()
'''
_CORE_010 = '''
from alembic import op
revision = "010"
down_revision = None
branch_labels = None
depends_on = None
def upgrade():
    op.execute("CREATE TABLE tenants (id uuid PRIMARY KEY)")
def downgrade():
    pass
'''


def _cfg(tmp_path, buf):
    script = tmp_path / "alembic"
    (script / "versions").mkdir(parents=True)
    (script / "env.py").write_text(_ENV)
    (script / "script.py.mako").write_text("")
    (script / "versions" / "010_core.py").write_text(_CORE_010)
    cfg = Config(output_buffer=buf)
    cfg.set_main_option("script_location", str(script))
    cfg.set_main_option("version_locations", f"{script / 'versions'} {MIGR}")
    cfg.set_main_option("path_separator", "space")
    return cfg


@pytest.fixture
def sql(tmp_path):
    buf = io.StringIO()
    command.upgrade(_cfg(tmp_path, buf), "heads", sql=True)
    return buf.getvalue()


def test_rama_propia_con_id_hash(tmp_path):
    script = ScriptDirectory.from_config(_cfg(tmp_path, io.StringIO()))
    revs = [r for r in script.walk_revisions() if str(Path(r.path).parent) == str(MIGR)]
    assert revs, "sin migraciones propias"
    for r in revs:
        assert re.fullmatch(r"[0-9a-f]{12}", r.revision), r.revision
    # Cada rama propia de la capa 2 (068 redirección, 070 perfil del wizard) tiene UNA raíz con etiqueta.
    roots = [r for r in revs if r.down_revision is None and "sentinel_redirect" in (r.branch_labels or ())]
    assert len(roots) == 1
    assert "010" in (roots[0].dependencies if isinstance(roots[0].dependencies, tuple)
                     else (roots[0].dependencies,))
    own_roots = [r for r in revs if r.down_revision is None]
    assert len(script.get_heads()) == 1 + len(own_roots)     # la 010 + una cabeza por rama propia


def test_crea_todas_las_tablas(sql):
    for t in TABLES:
        assert f"CREATE TABLE {t}" in sql, t
    assert sql.index("CREATE TABLE tenants") < sql.index("CREATE TABLE sentinel_redirect_policy")


def test_rls_con_el_patron_de_la_010(sql):
    for t in TABLES:
        assert f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY" in sql
        assert f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY" in sql
        assert re.search(rf"CREATE POLICY tenant_isolation ON {t} USING", sql)
        assert f"CREATE POLICY tenant_isolation_bootstrap ON {t}" in sql
    assert "current_setting('app.current_tenant', true)" in sql
    assert "current_setting('app.bypass_rls', true) = 'on'" in sql


def test_destinos_de_instalacion_solo_por_oferta_y_escritura_con_bypass(sql):
    pol = re.search(r"CREATE POLICY tenant_isolation ON sentinel_redirect_destination (.*)", sql).group(1)
    using, check = pol.split("WITH CHECK")
    assert "EXISTS (SELECT 1 FROM sentinel_redirect_offer o" in using
    assert "o.tenant_id IS NULL OR o.tenant_id =" in using
    assert "tenant_id IS NOT NULL" in check and "bypass_rls" in check and "EXISTS" not in check
    offer = re.search(r"CREATE POLICY tenant_isolation ON sentinel_redirect_offer (.*)", sql).group(1)
    assert offer.split("WITH CHECK")[1].strip().startswith("(current_setting('app.bypass_rls'")


def test_sin_contenido_de_pedidos_ni_credencial_en_claro(sql):
    dest = sql[sql.index("CREATE TABLE sentinel_redirect_destination"):]
    dest = dest[:dest.index(";")]
    assert "credential_encrypted TEXT" in dest
    assert not re.search(r"\b(api_key|secret|prompt|content)\b", dest)


def _backend_python():
    """Un intérprete que pueda importar el backend: `BACKEND_PYTHON`, el venv del backend o el
    actual. None si ninguno sirve (el test se saltea)."""
    for cand in (os.environ.get("BACKEND_PYTHON"), str(BACKEND / ".venv" / "bin" / "python"),
                 sys.executable):
        if cand and Path(cand).exists() and subprocess.run(
                [cand, "-c", "import src.models, alembic"], cwd=BACKEND,
                capture_output=True).returncode == 0:
            return cand
    return None


BACKEND_PY = _backend_python()


@pytest.mark.skipif(BACKEND_PY is None, reason="sin intérprete con las dependencias del backend")
def test_arbol_real_del_backend_con_la_costura_s4():
    code = ("import io; from alembic import command; from alembic.config import Config;"
            "b=io.StringIO(); c=Config('alembic.ini', output_buffer=b);"
            "command.upgrade(c, 'heads', sql=True); print(b.getvalue())")
    out = subprocess.run([BACKEND_PY, "-c", code], cwd=BACKEND, capture_output=True, text=True,
                         env={**os.environ, "ALEMBIC_EXTRA_VERSION_LOCATIONS": str(MIGR)}, timeout=300)
    assert out.returncode == 0, out.stderr[-3000:]
    for t in TABLES:
        assert f"CREATE TABLE {t}" in out.stdout
    # la rama propia corre DESPUÉS de la 010 (depends_on) y deja dos heads en alembic_version
    assert out.stdout.index("version_num='010'") < out.stdout.index("CREATE TABLE sentinel_redirect_policy")
    assert "Running upgrade  -> 0615e56e8251" in out.stdout


def test_modelos_orm_y_migracion_tienen_las_mismas_columnas(sql):
    from sentinel.redirect import models
    for table in models.RedirectBase.metadata.sorted_tables:
        block = sql[sql.index(f"CREATE TABLE {table.name} ("):]
        block = block[:block.index(";")]
        cols = set(re.findall(r"^\s{4}(\w+) ", block, flags=re.M)) - {"CONSTRAINT", "PRIMARY",
                                                                        "UNIQUE", "FOREIGN", "CHECK"}
        cols |= set(re.findall(rf"ALTER TABLE {table.name} ADD COLUMN (\w+) ", sql))   # migraciones posteriores
        assert cols == {c.name for c in table.columns}, table.name
    assert set(models.TABLES) == set(TABLES)
