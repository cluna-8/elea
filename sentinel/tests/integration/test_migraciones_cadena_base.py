"""Cadena de migraciones de la extensión sobre la base de Eleia (057 T016; research R5).

Todo offline (`--sql` y `ScriptDirectory`), sin Postgres ni Docker. Las cabezas se **calculan**
sobre el árbol real (nada de ids fijos): el backend tiene una sola, y con la costura S4
(`ALEMBIC_EXTRA_VERSION_LOCATIONS`) la extensión suma la suya, que cuelga de `010`.

Lo que fija:
1. sin la variable, una sola cabeza del backend y la rama de la extensión no existe;
2. con la variable, dos cabezas (la del backend, sin cambios, y la de la extensión);
3. la rama de la extensión es lineal, de ids hash, con etiqueta `sentinel_redirect` y cuelga de
   `010` (`depends_on`), nunca de la cadena del backend;
4. ninguna migración de la extensión crea, altera ni borra tablas `LiteLLM_*` ni
   `_prisma_migrations` (la base se comparte con el motor, cuyo migrador borra tablas ajenas);
   todas sus tablas llevan prefijo `sentinel_redirect_` o `ext_` y sus FKs apuntan solo a
   `tenants`, `groups` o tablas propias.
"""
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
BACKEND = ROOT / "backend"
ENV = "ALEMBIC_EXTRA_VERSION_LOCATIONS"
ETIQUETA = "sentinel_redirect"
PREFIJOS_PROPIOS = ("sentinel_redirect_", "ext_")
TABLAS_DE_LA_BASE_PERMITIDAS = {"tenants", "groups"}
HASH = re.compile(r"^[0-9a-f]{12}$")


def _cfg(buf=None) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"), output_buffer=buf)
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def _script(monkeypatch, con_extension: bool) -> ScriptDirectory:
    """ScriptDirectory del backend; con la costura S4 solo si `con_extension`."""
    from src import migration_locations as ml

    if con_extension:
        monkeypatch.setenv(ENV, str(MIGR))
    else:
        monkeypatch.delenv(ENV, raising=False)
    script = ScriptDirectory.from_config(_cfg())
    ml.extend_script_directory(script)
    return script


def _rama_extension(script: ScriptDirectory) -> list:
    """Revisiones de la rama `sentinel_redirect`, de la raíz a la cabeza."""
    revs = [r for r in script.walk_revisions() if ETIQUETA in (r.branch_labels or ())
            or (r.path and Path(r.path).parent == MIGR)]
    return list(reversed(revs))  # walk_revisions va de la cabeza a la raíz


# ── 1. Sin la variable: una sola cabeza, igual que hoy ────────────────────────────────
def test_sin_variable_una_sola_cabeza_del_backend(monkeypatch):
    script = _script(monkeypatch, con_extension=False)
    heads = script.get_heads()
    assert len(heads) == 1, heads
    # la cabeza del backend no vive en sentinel/migrations
    assert Path(script.get_revision(heads[0]).path).parent == BACKEND / "alembic" / "versions"
    assert _rama_extension(script) == []


# ── 2. Con la variable: dos cabezas, la del backend sin cambios ───────────────────────
def test_con_variable_dos_cabezas_y_la_del_backend_no_cambia(monkeypatch):
    (cabeza_backend,) = _script(monkeypatch, con_extension=False).get_heads()
    script = _script(monkeypatch, con_extension=True)
    heads = script.get_heads()
    assert len(heads) == 2, heads
    assert cabeza_backend in heads
    (cabeza_ext,) = [h for h in heads if h != cabeza_backend]
    assert Path(script.get_revision(cabeza_ext).path).parent == MIGR
    assert HASH.match(cabeza_ext), f"id por hash (alembic revision), no a mano: {cabeza_ext}"


# ── 3. La rama de la extensión: lineal, con etiqueta, colgada de 010 ──────────────────
def test_la_rama_de_la_extension_cuelga_de_010_y_es_lineal(monkeypatch):
    script = _script(monkeypatch, con_extension=True)
    rama = _rama_extension(script)
    assert len(rama) >= 7, [r.revision for r in rama]  # las 7 de Sentinel (sin el wizard) + la de Eleia
    raiz = rama[0]
    assert raiz.down_revision is None
    assert ETIQUETA in (raiz.branch_labels or ())
    deps = raiz.dependencies
    deps = (deps,) if isinstance(deps, str) else tuple(deps or ())
    assert deps == ("010",), "la rama cuelga de 010 por depends_on"
    for previa, siguiente in zip(rama, rama[1:]):
        assert siguiente.down_revision == previa.revision, (
            f"{siguiente.revision} no encadena sobre {previa.revision}: la rama no es lineal"
        )
    for r in rama:
        assert HASH.match(r.revision), f"id por hash: {r.revision}"
    # ninguna cuelga de la cadena del backend salvo por `010`
    rev_backend = {
        r.revision for r in script.walk_revisions() if Path(r.path).parent != MIGR
    }
    for r in rama:
        assert set(r.nextrev) <= {x.revision for x in rama}
        assert (set(r._all_down_revisions) - {"010"}) <= {x.revision for x in rama}
        assert not (set(r._all_down_revisions) - {"010"}) & rev_backend


def test_el_wizard_del_portal_no_viene_en_la_rama(monkeypatch):
    """`b8c4d7e2a915_wizard_profile` es del Portal de Sentinel (HANDOFF §1(b)): no se porta."""
    script = _script(monkeypatch, con_extension=True)
    assert "b8c4d7e2a915" not in {r.revision for r in script.walk_revisions()}
    assert not list(MIGR.glob("b8c4d7e2a915*"))


# ── 4. Lo que las migraciones pueden tocar en la base compartida con el motor ─────────
def _sql_de_la_rama(monkeypatch) -> str:
    """SQL offline de la rama completa de la extensión (de `010` a su cabeza)."""
    from src import migration_locations as ml  # noqa: F401  (env.py lo importa igual)

    monkeypatch.setenv(ENV, str(MIGR))
    buf = io.StringIO()
    command.upgrade(_cfg(buf), f"010:{ETIQUETA}@head", sql=True)
    return buf.getvalue()


def test_las_migraciones_no_tocan_tablas_del_motor(monkeypatch):
    sql = _sql_de_la_rama(monkeypatch)
    assert "sentinel_redirect_" in sql, "el SQL de la rama no se generó"
    assert not re.search(r"litellm_|_prisma_migrations", sql, re.IGNORECASE), (
        "una migración de la extensión toca tablas del motor"
    )
    # además del SQL, el código fuente (por si un op dinámico no llegara al modo offline)
    for f in sorted(MIGR.glob("*.py")):
        assert not re.search(r"litellm_|_prisma_migrations", f.read_text(), re.IGNORECASE), f.name


def test_todas_las_tablas_y_fks_son_propias_o_de_tenants_y_groups(monkeypatch):
    sql = _sql_de_la_rama(monkeypatch)
    creadas = set(re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?\"?([a-z0-9_]+)\"?", sql, re.IGNORECASE))
    assert creadas, "la rama no crea ninguna tabla"
    for t in creadas:
        assert t.startswith(PREFIJOS_PROPIOS), f"tabla fuera de los prefijos de la extensión: {t}"
    # toda tabla que se altera, indexa o borra es propia (ninguna de la base ni del motor)
    tocadas = set(re.findall(r"ALTER TABLE (?:ONLY )?\"?([a-z0-9_]+)\"?", sql, re.IGNORECASE))
    tocadas |= set(re.findall(r"DROP TABLE (?:IF EXISTS )?\"?([a-z0-9_]+)\"?", sql, re.IGNORECASE))
    tocadas |= set(re.findall(r"CREATE (?:UNIQUE )?INDEX [^\n]*? ON \"?([a-z0-9_]+)\"?", sql, re.IGNORECASE))
    for t in tocadas:
        assert t.startswith(PREFIJOS_PROPIOS), f"la rama toca una tabla que no es suya: {t}"
    # FKs: solo a tenants, groups o tablas propias
    destinos = set(re.findall(r"REFERENCES \"?([a-z0-9_]+)\"?", sql, re.IGNORECASE))
    assert destinos, "la rama no declara FKs (se esperan al menos a tenants)"
    for d in destinos:
        assert d in TABLAS_DE_LA_BASE_PERMITIDAS or d.startswith(PREFIJOS_PROPIOS), (
            f"FK a una tabla que no es de la extensión ni tenants/groups: {d}"
        )
