"""Migración nueva de Eleia (057 T026): región con postura por defecto, reglas de habilitación, relajaciones del
enmascarado forzado y jurisdicción de control en la ficha (data-model §1–§4). Offline, sin Postgres.

Fija la forma del DDL (columnas, restricciones, índice parcial, FKs, RLS con filas de instalación legibles por toda
empresa y escribibles solo con bypass) y que los modelos del ORM tienen las mismas columnas que la migración.
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
ENV = "ALEMBIC_EXTRA_VERSION_LOCATIONS"
REGION, RULE, RELAX = ("sentinel_redirect_region", "ext_catalog_enablement_rule",
                       "sentinel_redirect_masking_relaxation")


def _cfg(buf=None):
    cfg = Config(str(ROOT / "backend" / "alembic.ini"), output_buffer=buf)
    cfg.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    return cfg


@pytest.fixture(scope="module")
def sql():
    import os
    os.environ[ENV] = str(MIGR)
    try:
        buf = io.StringIO()
        command.upgrade(_cfg(buf), "f7a3c1d9e508:89a92524eef6", sql=True)
        return buf.getvalue()
    finally:
        os.environ.pop(ENV, None)


def _tabla(sql, nombre):
    bloque = sql[sql.index(f"CREATE TABLE {nombre} ("):]
    return bloque[:bloque.index(";")]


def test_la_migracion_cuelga_de_la_que_trae_sentinel_y_la_sigue_la_cabeza_actual():
    import os
    os.environ[ENV] = str(MIGR)
    try:
        from src import migration_locations as ml
        script = ScriptDirectory.from_config(_cfg())
        ml.extend_script_directory(script)
    finally:
        os.environ.pop(ENV, None)
    rev = script.get_revision("89a92524eef6")
    assert rev.down_revision == "f7a3c1d9e508" and re.fullmatch(r"[0-9a-f]{12}", rev.revision)
    # la cabeza de la extensión es hoy el default de la etiqueta (057 R40), que cuelga de esta
    assert "89a92524eef6" not in script.get_heads() and "f7a3c1d9e508" not in script.get_heads()
    assert script.get_revision("0529902015ad").down_revision == "89a92524eef6"


def test_crea_las_tres_tablas_y_la_columna_de_control(sql):
    for t in (REGION, RULE, RELAX):
        assert f"CREATE TABLE {t} (" in sql, t
    assert re.search(r"ALTER TABLE ext_compliance_sheet ADD COLUMN control_jurisdiction VARCHAR\(8\);", sql)
    # nullable y sin default: NULL = sin cargar (no cuenta como «en región»)
    assert "control_jurisdiction VARCHAR(8) NOT NULL" not in sql


def test_la_region_trae_la_postura_por_defecto_con_la_paridad_de_sentinel_de_fabrica(sql):
    r = _tabla(sql, REGION)
    assert "default_posture VARCHAR(24) DEFAULT 'reject_offregion' NOT NULL" in r
    assert "ck_redirect_region_default_posture" in r
    for valor in ("reject_offregion", "masked_offregion", "masked_all", "allow"):
        assert f"'{valor}'" in r
    assert "jsonb_array_length(jurisdictions) > 0" in r                    # no vacía
    assert "REFERENCES tenants (id) ON DELETE CASCADE" in r
    assert "uq_redirect_region_name" in sql


def test_la_regla_de_habilitacion_es_unica_por_nivel_tipo_y_valor(sql):
    r = _tabla(sql, RULE)
    assert "kind IN ('provider','api_host','jurisdiction')" in r.replace("\n", " ")
    assert "reason TEXT NOT NULL" in r and "created_by_role VARCHAR(32) NOT NULL" in r
    assert re.search(r"CREATE UNIQUE INDEX uq_enablement_rule ON ext_catalog_enablement_rule "
                     r"\(COALESCE\(tenant_id, [^)]*\), kind, value\)", sql)


def test_la_relajacion_apunta_a_la_entrada_y_la_baja_no_borra_la_fila(sql):
    r = _tabla(sql, RELAX)
    assert "REFERENCES ext_catalog_entry (id) ON DELETE CASCADE" in r
    assert "revoked_at TIMESTAMP WITH TIME ZONE" in r and "revoke_reason TEXT" in r
    assert "created_by_role IN ('compliance_officer','super_admin')" in r.replace("\n", " ")
    # una sola vigente por (nivel, empresa, entrada); las revocadas son historial
    assert re.search(r"CREATE UNIQUE INDEX uq_masking_relaxation_active ON "
                     r"sentinel_redirect_masking_relaxation \(COALESCE\(tenant_id, [^)]*\), entry_id\) "
                     r"WHERE revoked_at IS NULL", sql)


@pytest.mark.parametrize("tabla", [REGION, RULE, RELAX])
def test_rls_forzada_con_filas_de_instalacion_legibles_y_escritura_solo_con_bypass(sql, tabla):
    assert f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY" in sql
    assert f"ALTER TABLE {tabla} FORCE ROW LEVEL SECURITY" in sql
    assert f"CREATE POLICY tenant_isolation_bootstrap ON {tabla}" in sql
    politica = re.search(rf"CREATE POLICY tenant_isolation ON {tabla} USING \((.*?)\) WITH CHECK \((.*?)\);", sql, re.S)
    assert politica, tabla
    usando, chequeo = politica.groups()
    assert "tenant_id IS NULL" in usando                                  # la instalación la ve toda empresa
    assert "app.current_tenant" in usando
    assert "tenant_id IS NOT NULL AND tenant_id =" in chequeo and "app.bypass_rls" in chequeo   # escribir: la propia o bypass


def test_ninguna_tabla_nueva_guarda_secretos_ni_contenido(sql):
    for t in (REGION, RULE, RELAX):
        assert not re.search(r"\b(api_key|secret|password|token|prompt|content|ciphertext)\b", _tabla(sql, t)), t


def test_los_modelos_tienen_las_mismas_columnas_que_la_migracion(sql):
    from sentinel.catalog import models as cm
    from sentinel.redirect import models as rm
    for modelo, nombre in ((rm.RedirectRegion, REGION), (cm.EnablementRule, RULE),
                           (rm.RedirectMaskingRelaxation, RELAX)):
        bloque = _tabla(sql, nombre)
        cols = set(re.findall(r"^\s{4}(\w+) ", bloque, flags=re.M)) - {"CONSTRAINT", "PRIMARY", "UNIQUE", "FOREIGN", "CHECK"}
        assert cols == {c.name for c in modelo.__table__.columns}, nombre
    assert "control_jurisdiction" in {c.name for c in cm.ComplianceSheet.__table__.columns}
