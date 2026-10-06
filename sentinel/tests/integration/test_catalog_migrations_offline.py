"""Migración del catálogo (069 T024) en modo offline (`--sql`), sin Postgres ni Docker."""
import io
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_redirect_migrations_offline import MIGR, _cfg  # noqa: E402

from alembic import command  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

NEW = "e4a9c15b7d30"
TABLES = ("ext_credential", "ext_catalog_entry", "ext_catalog_offer", "ext_compliance_sheet")


@pytest.fixture
def sql(tmp_path):
    buf = io.StringIO()
    command.upgrade(_cfg(tmp_path, buf), "heads", sql=True)
    return buf.getvalue()


def test_misma_rama_que_la_068_y_una_sola_cabeza_propia(tmp_path):
    script = ScriptDirectory.from_config(_cfg(tmp_path, io.StringIO()))
    nueva = script.get_revision("7b2d4f8a9c10")
    assert nueva.down_revision == "0615e56e8251"
    # la rama de redirección sigue: catálogo (069) → informes de fidelidad (068 US5), que es la cabeza
    assert "7b2d4f8a9c10" not in script.get_heads()
    assert script.get_revision("c3f1a7d9e204").down_revision == "7b2d4f8a9c10"
    assert "c3f1a7d9e204" not in script.get_heads()
    # pantalla única (US8): columnas nuevas de la entrada, cabeza de la rama de redirección
    assert script.get_revision(NEW).down_revision == "c3f1a7d9e204"
    # perfiles de acceso (069 US2) cuelgan de ella y son la cabeza actual de la rama
    assert script.get_revision("a7d2f9c4b816").down_revision == NEW
    assert NEW not in script.get_heads() and "a7d2f9c4b816" not in script.get_heads()
    # estrategia de la regla (069 US10) cuelga de ella y es la cabeza actual
    assert script.get_revision("d5b8e3a1c742").down_revision == "a7d2f9c4b816"
    assert "d5b8e3a1c742" not in script.get_heads()
    # parámetros no soportados de la ficha (069 enmienda) cuelgan de ella y son la cabeza actual
    assert script.get_revision("f7a3c1d9e508").down_revision == "d5b8e3a1c742"
    assert "f7a3c1d9e508" in script.get_heads()


def test_crea_las_tablas_despues_de_las_de_la_068(sql):
    for t in TABLES:
        assert f"CREATE TABLE {t}" in sql
    assert sql.index("CREATE TABLE sentinel_redirect_destination") < sql.index("CREATE TABLE ext_catalog_entry")
    assert sql.index("CREATE TABLE ext_credential") < sql.index("CREATE TABLE ext_catalog_entry")


def test_rls_en_todas(sql):
    for t in TABLES:
        assert f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY" in sql
        assert f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY" in sql
        assert f"CREATE POLICY tenant_isolation_bootstrap ON {t}" in sql


def test_credencial_de_instalacion_nunca_visible_a_una_organizacion(sql):
    pol = re.search(r"CREATE POLICY tenant_isolation ON ext_credential (.*)", sql).group(1)
    assert "EXISTS" not in pol and "tenant_id IS NULL" not in pol
    assert "bypass_rls" in pol


def test_entrada_de_instalacion_solo_por_oferta(sql):
    pol = re.search(r"CREATE POLICY tenant_isolation ON ext_catalog_entry (.*)", sql).group(1)
    using, check = pol.split("WITH CHECK")
    assert "FROM ext_catalog_offer o" in using
    assert "EXISTS" not in check and "bypass_rls" in check


def test_ficha_sigue_a_su_entrada(sql):
    pol = re.search(r"CREATE POLICY tenant_isolation ON ext_compliance_sheet (.*)", sql).group(1)
    using, check = pol.split("WITH CHECK")
    assert "FROM ext_catalog_entry e" in using and "FROM ext_catalog_entry e" in check
    assert "bypass_rls" in check


def test_el_secreto_solo_se_guarda_cifrado_y_env_ref_solo_de_instalacion(sql):
    cred = sql[sql.index("CREATE TABLE ext_credential"):]
    cred = cred[:cred.index(";")]
    assert "ciphertext TEXT" in cred and not re.search(r"\b(api_key|secret_value|plaintext)\b", cred)
    assert "ck_ext_credential_env_ref_level" in cred


def test_el_semaforo_no_se_almacena(sql):
    ficha = sql[sql.index("CREATE TABLE ext_compliance_sheet"):]
    ficha = ficha[:ficha.index(";")]
    assert not re.search(r"\b(semaforo|estado|traffic)\b", ficha)


def test_modelos_orm_y_migracion_tienen_las_mismas_columnas(sql):
    from sentinel.catalog import models
    for table in models.CatalogBase.metadata.sorted_tables:
        block = sql[sql.index(f"CREATE TABLE {table.name} ("):]
        block = block[:block.index(";")]
        cols = set(re.findall(r"^\s{4}(\w+) ", block, flags=re.M)) - {"CONSTRAINT", "PRIMARY",
                                                                        "UNIQUE", "FOREIGN", "CHECK"}
        cols |= set(re.findall(rf"ALTER TABLE {table.name} ADD COLUMN (\w+) ", sql))   # migraciones posteriores
        assert cols == {c.name for c in table.columns}, table.name
    assert set(models.TABLES) == set(TABLES)


def test_estrategia_de_la_regla(sql):
    assert re.search(r"ALTER TABLE sentinel_redirect_rule ADD COLUMN strategy VARCHAR\(16\) "
                     r"DEFAULT 'order' NOT NULL", sql)
    assert re.search(r"ADD CONSTRAINT ck_redirect_rule_strategy CHECK \(strategy IN \('order', ?'cheapest'\)\)", sql)


def test_vocabulario_de_proveedores_orm_igual_a_la_migracion(sql):
    from sentinel.catalog import models
    check = re.search(r"CONSTRAINT ck_ext_entry_provider CHECK \(provider IN \((.*?)\)\)", sql, re.S)
    assert set(re.findall(r"'(\w+)'", check.group(1))) == set(models.PROVIDERS)


def test_columnas_nuevas_de_la_entrada(sql):
    for col in ("limits", "base_model", "price_cache_read", "price_cache_write", "price_tiers", "advanced"):
        assert re.search(rf"ALTER TABLE ext_catalog_entry ADD COLUMN {col} ", sql), col
    assert re.search(r"ADD COLUMN limits JSONB DEFAULT '\{\}'::jsonb NOT NULL", sql)
    assert re.search(r"ADD COLUMN advanced JSONB DEFAULT '\{\}'::jsonb NOT NULL", sql)
    assert re.search(r"ADD COLUMN price_cache_read NUMERIC\(20, 12\)", sql)
    assert re.search(r"ADD COLUMN base_model TEXT", sql)
    assert sql.index("CREATE TABLE ext_catalog_entry") < sql.index("ADD COLUMN limits")


def test_rol_ampliado_reemplaza_el_check(sql):
    from sentinel.catalog import models
    assert "ALTER TABLE ext_catalog_entry DROP CONSTRAINT ck_ext_entry_role" in sql
    nuevo = re.findall(r"ADD CONSTRAINT ck_ext_entry_role CHECK \(role IN \((.*?)\)\)", sql)
    assert len(nuevo) == 1 and set(re.findall(r"'(\w+)'", nuevo[0])) == set(models.ROLES)
    assert set(models.ROLES) == {"text", "embeddings", "image", "audio", "rerank"}
    assert sql.rindex("DROP CONSTRAINT ck_ext_entry_role") > sql.index("CREATE TABLE ext_catalog_entry")


def test_downgrade_deja_el_check_anterior():
    import importlib.util
    spec = importlib.util.spec_from_file_location("m", next(MIGR.glob(f"{NEW}_*.py")))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.revision == NEW and m.down_revision == "c3f1a7d9e204" and callable(m.downgrade)


def test_parametros_no_soportados_de_la_ficha(sql):
    assert re.search(r"ALTER TABLE ext_catalog_entry ADD COLUMN unsupported_params JSONB "
                     r"DEFAULT '\[\]'::jsonb NOT NULL", sql)
    assert sql.index("CREATE TABLE ext_catalog_entry") < sql.index("ADD COLUMN unsupported_params")


def test_downgrade_quita_la_columna_de_parametros():
    import importlib.util
    spec = importlib.util.spec_from_file_location("m", next(MIGR.glob("f7a3c1d9e508_*.py")))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.revision == "f7a3c1d9e508" and m.down_revision == "d5b8e3a1c742" and callable(m.downgrade)
