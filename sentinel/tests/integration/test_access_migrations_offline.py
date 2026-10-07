"""Migración de los perfiles de acceso (069 T046) en modo offline (`--sql`), sin Postgres ni Docker."""
import io
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_redirect_migrations_offline import _cfg  # noqa: E402

from alembic import command  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

NEW = "a7d2f9c4b816"
TABLES = ("ext_access_profile", "ext_access_profile_rule", "ext_access_assignment", "ext_ai_act_ceiling",
          "ext_access_key_profile")


@pytest.fixture
def sql(tmp_path):
    buf = io.StringIO()
    command.upgrade(_cfg(tmp_path, buf), "heads", sql=True)
    return buf.getvalue()


def test_misma_rama_y_cabeza_propia(tmp_path):
    script = ScriptDirectory.from_config(_cfg(tmp_path, io.StringIO()))
    assert script.get_revision(NEW).down_revision == "e4a9c15b7d30"
    assert "e4a9c15b7d30" not in script.get_heads()   # la cabeza actual es la estrategia por regla (US10), que cuelga de NEW
    assert re.fullmatch(r"[0-9a-f]{12}", NEW)


def test_crea_las_tablas_despues_de_las_del_catalogo(sql):
    for t in TABLES:
        assert f"CREATE TABLE {t}" in sql
    assert sql.index("CREATE TABLE ext_catalog_entry") < sql.index("CREATE TABLE ext_access_profile")


def test_rls_en_todas(sql):
    for t in TABLES:
        assert f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY" in sql
        assert f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY" in sql
        assert f"CREATE POLICY tenant_isolation_bootstrap ON {t}" in sql
    for t in TABLES:
        if t != "ext_access_profile_rule":
            pol = re.search(rf"CREATE POLICY tenant_isolation ON {t} (.*)", sql).group(1)
            assert "app.current_tenant" in pol and "bypass_rls" in pol


def test_las_reglas_siguen_a_su_perfil(sql):
    pol = re.search(r"CREATE POLICY tenant_isolation ON ext_access_profile_rule (.*)", sql).group(1)
    assert "FROM ext_access_profile p" in pol


def test_la_base_no_se_toca_el_perfil_de_llave_es_tabla_propia(sql):
    assert not re.search(r"ALTER TABLE (api_keys|users|groups|tenants)\b", sql.split(
        "CREATE TABLE ext_access_profile")[1])
    assert "CREATE TABLE ext_access_key_profile" in sql and "api_key_id UUID NOT NULL" in sql


def test_modelos_orm_y_migracion_tienen_las_mismas_columnas(sql):
    from sentinel.access import models
    for table in models.AccessBase.metadata.sorted_tables:
        block = sql[sql.index(f"CREATE TABLE {table.name} ("):]
        block = block[:block.index(";")]
        cols = set(re.findall(r"^\s{4}(\w+) ", block, flags=re.M)) - {"CONSTRAINT", "PRIMARY",
                                                                        "UNIQUE", "FOREIGN", "CHECK"}
        assert cols == {c.name for c in table.columns}, table.name
    assert set(models.TABLES) == set(TABLES)


def test_vocabularios_orm_iguales_a_los_de_la_migracion(sql):
    from sentinel.access import models
    def vocab(name):
        m = re.search(rf"CONSTRAINT {name} CHECK \(\w+ IN \((.*?)\)\)", sql, re.S)
        return set(re.findall(r"'(\w+)'", m.group(1)))
    assert vocab("ck_ext_access_profile_kind") == set(models.KINDS)
    assert vocab("ck_ext_access_rule_effect") == set(models.EFFECTS)
    assert vocab("ck_ext_access_rule_selector") == set(models.SELECTORS)
    assert vocab("ck_ext_access_assignment_subject") == set(models.SUBJECT_TYPES)
    assert vocab("ck_ext_ai_act_ceiling_risk") == set(models.RISK_LEVELS)


def test_downgrade_existe():
    import importlib.util
    from test_redirect_migrations_offline import MIGR
    spec = importlib.util.spec_from_file_location("m", next(MIGR.glob(f"{NEW}_*.py")))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.revision == NEW and callable(m.downgrade)
