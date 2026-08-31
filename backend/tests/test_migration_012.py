"""Tests de la migración 012 — esquema, constraints, RLS y simetría del downgrade (spec 027).

Cubre lo que T006 pide ("upgrade+downgrade limpios") y el hallazgo A1 de la verificación
adversarial: ``governance_profiles`` es la única tabla nueva con ``tenant_id`` y, encima,
la que decide QUÉ CAPAS DE SEGURIDAD CORREN — sin RLS, un UPSERT/DELETE por PK con un id
ajeno (patrón habitual del CRUD del repo) apaga ``pii_masking`` de OTRO tenant.

Corre contra el Postgres de Docker Compose conectado como ``rls_owner`` (rol NOSUPERUSER
dueño de las tablas): con ``sentinel_admin`` —superuser— la RLS se bypasea SIEMPRE, incluso con
FORCE, y estos tests pasarían en verde sin probar nada. Self-skip si Postgres no está.
"""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from migration_harness import (
    DEFAULT_TENANT, RLS_TENANT_TABLES, fresh_db, owner_engine, require_postgres,
    run_alembic,
)

require_postgres()

DB = "sentinel_test_migration_012"

TENANT_B = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000000cc")

# Fila válida de referencia: el default de tenant, el alcance más común.
VALID_ROW = {
    "scope_type": "tenant_default",
    "scope_value": "*",
    "layer_key": "pii_masking",
    "decision": "off",
    "updated_by": "admin-de-prueba",
}


@pytest.fixture(scope="module")
def engine():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    eng = owner_engine(DB)
    yield eng
    eng.dispose()


def _insert(cx, tenant_id=DEFAULT_TENANT, **overrides):
    row = dict(VALID_ROW, **overrides)
    row["id"] = overrides.get("id", uuid.uuid4())
    row["tenant_id"] = tenant_id
    cx.execute(text("""
        INSERT INTO governance_profiles
            (id, tenant_id, scope_type, scope_value, layer_key, decision, updated_by)
        VALUES (:id, :tenant_id, :scope_type, :scope_value, :layer_key, :decision, :updated_by)
    """), row)
    return row["id"]


# ── Esquema ────────────────────────────────────────────────────────────────────────────

def test_table_has_the_named_constraints_of_the_contract(engine):
    """data-model §1.1: el UNIQUE y los 3 CHECKs van NOMBRADOS — el CRUD de US2 hace
    UPSERT ``ON CONFLICT ON CONSTRAINT`` y el router traduce el nombre a un 422."""
    with engine.connect() as cx:
        names = {r.conname: r.contype for r in cx.execute(text("""
            SELECT conname, contype FROM pg_constraint
            WHERE conrelid = 'governance_profiles'::regclass
        """))}
    assert names.get("uq_governance_profiles_scope") == "u"
    assert names.get("ck_governance_profiles_scope_type") == "c"
    assert names.get("ck_governance_profiles_decision") == "c"
    assert names.get("ck_governance_profiles_scope_pair") == "c"
    assert names.get("fk_governance_profiles_tenant") == "f"


def test_text_columns_are_bounded(engine):
    """Hallazgo BAJA: la tabla se EXPORTA como evidencia de auditoría y no tiene purga.
    ``updated_by`` acotada a 120 (username/id del admin, jamás el email) y ``layer_key``
    a 64 (clave del registry, no texto libre) son el único límite de esquema que queda:
    layer_key va sin FK ni CHECK a propósito (D1)."""
    with engine.connect() as cx:
        lengths = {r.column_name: r.character_maximum_length for r in cx.execute(text("""
            SELECT column_name, character_maximum_length
            FROM information_schema.columns WHERE table_name = 'governance_profiles'
        """))}
    assert lengths["updated_by"] == 120
    assert lengths["layer_key"] == 64


def test_audit_logs_attribution_columns_and_partial_index(engine):
    """data-model §3: applied_layers JSONB + blocked_by_layer VARCHAR, y el índice de
    bloqueos PARCIAL — sin el WHERE se paga el índice sobre toda la tabla de auditoría,
    cuando los bloqueos son la excepción."""
    with engine.connect() as cx:
        types = {r.column_name: r.data_type for r in cx.execute(text("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_name = 'audit_logs'
              AND column_name IN ('applied_layers', 'blocked_by_layer')
        """))}
        indexdef = cx.execute(text("""
            SELECT indexdef FROM pg_indexes
            WHERE tablename = 'audit_logs' AND indexname = 'ix_audit_logs_tenant_blocked_layer'
        """)).scalar()

    assert types == {"applied_layers": "jsonb", "blocked_by_layer": "character varying"}
    assert indexdef is not None, "falta ix_audit_logs_tenant_blocked_layer"
    assert "(tenant_id, blocked_by_layer)" in indexdef
    assert "WHERE (blocked_by_layer IS NOT NULL)" in indexdef, \
        f"el índice debe ser PARCIAL, no total: {indexdef}"


# ── Constraints: cada CHECK y el UNIQUE, ejercitados de verdad ──────────────────────────

def test_valid_row_of_every_scope_type_is_accepted(engine):
    """Control positivo: sin esto, un CHECK roto que rechace TODO pasaría los tests
    negativos de abajo en verde."""
    with engine.begin() as cx:
        _insert(cx, scope_type="tenant_default", scope_value="*")
        _insert(cx, scope_type="connection_mode", scope_value="subscription")
        _insert(cx, scope_type="surface", scope_value="claude-code")
        total = cx.execute(text("SELECT COUNT(*) FROM governance_profiles")).scalar()
    assert total == 3


@pytest.mark.parametrize("overrides, constraints", [
    # enum de scope_type CERRADO: 'group'/'client' son de la cascada 015, no de la 027.
    # Un scope_type inválido viola los DOS CHECKs a la vez (el compuesto solo contempla los
    # tres tipos válidos) y Postgres no garantiza cuál reporta: se acepta cualquiera.
    ({"scope_type": "group", "scope_value": "*"},
     ("ck_governance_profiles_scope_type", "ck_governance_profiles_scope_pair")),
    # no existe decision='inherit': heredar es la AUSENCIA de fila (D2)
    ({"decision": "inherit"}, ("ck_governance_profiles_decision",)),
    # el default de tenant exige el centinela '*' (el UNIQUE de PG no deduplica NULLs)
    ({"scope_type": "tenant_default", "scope_value": "subscription"},
     ("ck_governance_profiles_scope_pair",)),
    # cada scope_type ata su dominio: un tool_type no es un modo de conexión
    ({"scope_type": "connection_mode", "scope_value": "claude-code"},
     ("ck_governance_profiles_scope_pair",)),
    # superficie fuera del enum (p.ej. la API de Responses, issue #28): rechazada hasta que
    # este CHECK y ck_api_keys_tool_type evolucionen en la MISMA migración
    ({"scope_type": "surface", "scope_value": "responses-api"},
     ("ck_governance_profiles_scope_pair",)),
])
def test_checks_reject_invalid_scopes(engine, overrides, constraints):
    with pytest.raises(IntegrityError) as exc:
        with engine.begin() as cx:
            _insert(cx, **overrides)
    assert any(name in str(exc.value) for name in constraints), str(exc.value)


def test_unique_scope_rejects_duplicate_decision(engine):
    """Una sola decisión por (tenant, alcance, capa): dos filas contradictorias para el
    mismo alcance harían no determinista al resolutor (FR-006)."""
    with engine.begin() as cx:
        _insert(cx, scope_type="surface", scope_value="cursor", layer_key="pii_masking",
                decision="off")
    with pytest.raises(IntegrityError) as exc:
        with engine.begin() as cx:
            _insert(cx, scope_type="surface", scope_value="cursor", layer_key="pii_masking",
                    decision="on")
    assert "uq_governance_profiles_scope" in str(exc.value)


def test_same_scope_different_tenant_is_allowed(engine):
    """El UNIQUE incluye tenant_id: dos tenants deciden distinto sobre la misma capa."""
    with engine.begin() as cx:
        cx.execute(text("""
            INSERT INTO tenants (id, name, slug, deployment_mode)
            VALUES (:id, 'Tenant B', 'tenant-b-012', 'cloud') ON CONFLICT (id) DO NOTHING
        """), {"id": TENANT_B})
        _insert(cx, tenant_id=TENANT_B, scope_type="surface", scope_value="cursor",
                layer_key="pii_masking", decision="on")
        rows = cx.execute(text("""
            SELECT tenant_id FROM governance_profiles
            WHERE scope_value = 'cursor' AND layer_key = 'pii_masking'
        """)).fetchall()
    assert {r.tenant_id for r in rows} == {DEFAULT_TENANT, TENANT_B}


# ── RLS (hallazgo A1) ──────────────────────────────────────────────────────────────────

def test_rls_enabled_forced_and_two_policies_on_every_tenant_table(engine):
    """A1: ENABLE + FORCE + las DOS policies de la 010, con el MISMO predicado. Barre el
    universo COMPLETO (RLS_TENANT_TABLES) y no solo la tabla nueva: el agujero apareció
    justamente porque nadie barría las tablas posteriores a la 010."""
    with engine.connect() as cx:
        for table in RLS_TENANT_TABLES:
            flags = cx.execute(text("""
                SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t
            """), {"t": table}).one()
            assert flags.relrowsecurity, f"{table}: RLS no habilitada"
            # Sin FORCE el DUEÑO de la tabla —el rol del runtime— bypasea sus policies.
            assert flags.relforcerowsecurity, f"{table}: falta FORCE RLS"

            policies = {r.policyname: r for r in cx.execute(text(
                "SELECT policyname, qual, with_check FROM pg_policies WHERE tablename = :t"
            ), {"t": table})}
            assert set(policies) == {"tenant_isolation", "tenant_isolation_bootstrap"}, \
                f"{table}: policies inesperadas {set(policies)}"

            # El NOMBRE no alcanza: el predicado real debe scopear por el GUC y admitir el
            # bypass explícito, en USING y en WITH CHECK (lectura y escritura).
            strict = policies["tenant_isolation"]
            for pred in (strict.qual, strict.with_check):
                assert "app.current_tenant" in pred and "app.bypass_rls" in pred, \
                    f"{table}: predicado inesperado: {pred}"
            # La ventana bootstrap de la 010 (se elimina en 017, para TODAS a la vez)
            boot = policies["tenant_isolation_bootstrap"]
            for pred in (boot.qual, boot.with_check):
                assert "app.current_tenant" in pred, f"{table}: bootstrap inesperada: {pred}"


def test_governance_profiles_predicate_is_identical_to_the_010_tables(engine):
    """El predicado se copió literal de la 010: si alguien lo 'mejora' acá, esta tabla
    queda con una semántica de aislamiento propia y la 017 la dejaría atrás."""
    with engine.connect() as cx:
        preds = {r.tablename: (r.qual, r.with_check) for r in cx.execute(text("""
            SELECT tablename, qual, with_check FROM pg_policies
            WHERE policyname = 'tenant_isolation'
              AND tablename IN ('governance_profiles', 'api_keys')
        """))}
    assert preds["governance_profiles"] == preds["api_keys"]


def test_cross_tenant_write_by_pk_is_blocked(engine):
    """EL escenario de A1, textual: el CRUD admin de US2 hace UPSERT/DELETE por PK
    (``filter(GovernanceProfile.id == profile_id)``). Con la sesión scopeada al tenant A,
    pasar el id de una fila del tenant B no debe apagar NADA."""
    victim = uuid.uuid4()
    with engine.begin() as cx:
        _insert(cx, id=victim, tenant_id=TENANT_B, scope_type="tenant_default",
                scope_value="*", layer_key="secret_detection", decision="on")

    with engine.begin() as cx:
        cx.execute(text("SELECT set_config('app.current_tenant', :t, true)"),
                   {"t": str(DEFAULT_TENANT)})
        assert cx.execute(text(
            "SELECT COUNT(*) FROM governance_profiles WHERE id = :id"
        ), {"id": victim}).scalar() == 0, "la fila del otro tenant es visible"

        updated = cx.execute(text(
            "UPDATE governance_profiles SET decision = 'off' WHERE id = :id"
        ), {"id": victim}).rowcount
        deleted = cx.execute(text(
            "DELETE FROM governance_profiles WHERE id = :id"
        ), {"id": victim}).rowcount
    assert (updated, deleted) == (0, 0), "RLS no frenó la escritura cross-tenant por PK"

    # Y la fila del tenant B quedó intacta (se lee con el bypass explícito).
    with engine.begin() as cx:
        cx.execute(text("SELECT set_config('app.bypass_rls', 'on', true)"))
        decision = cx.execute(text(
            "SELECT decision FROM governance_profiles WHERE id = :id"
        ), {"id": victim}).scalar()
    assert decision == "on"


def test_cross_tenant_insert_rejected_by_with_check(engine):
    """Con la sesión scopeada al tenant A, sembrar una decisión a nombre de B tampoco va.
    (El WITH CHECK de RLS levanta InsufficientPrivilege, no CheckViolation — de ahí el
    DBAPIError en vez del IntegrityError de los CHECKs de esquema.)"""
    with pytest.raises(DBAPIError, match="row-level security") as exc:
        with engine.begin() as cx:
            cx.execute(text("SELECT set_config('app.current_tenant', :t, true)"),
                       {"t": str(DEFAULT_TENANT)})
            _insert(cx, tenant_id=TENANT_B, scope_type="surface", scope_value="copilot")
    assert "row-level security" in str(exc.value)


# ── Ida y vuelta (T006) ────────────────────────────────────────────────────────────────

def test_downgrade_then_reupgrade_is_clean(engine):
    """T006: el downgrade no deja restos (tabla, columnas, ambos índices, policies) y un
    upgrade posterior vuelve a head sin errores — con la RLS re-armada, no solo la tabla."""
    run_alembic(DB, "downgrade", "011")

    with engine.connect() as cx:
        assert cx.execute(text("SELECT to_regclass('governance_profiles')")).scalar() is None
        leftovers = cx.execute(text("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name = 'audit_logs'
              AND column_name IN ('applied_layers', 'blocked_by_layer')
        """)).scalar()
        assert leftovers == 0
        assert cx.execute(text(
            "SELECT COUNT(*) FROM pg_indexes WHERE indexname = 'ix_audit_logs_tenant_blocked_layer'"
        )).scalar() == 0
        assert cx.execute(text(
            "SELECT COUNT(*) FROM pg_policies WHERE tablename = 'governance_profiles'"
        )).scalar() == 0
        # Fuera de la feature no se pierde nada: audit_logs sigue en pie.
        assert cx.execute(text("SELECT to_regclass('audit_logs')")).scalar() is not None

    run_alembic(DB, "upgrade", "head")
    with engine.connect() as cx:
        assert cx.execute(text("SELECT to_regclass('governance_profiles')")).scalar() is not None
        flags = cx.execute(text("""
            SELECT relrowsecurity, relforcerowsecurity FROM pg_class
            WHERE relname = 'governance_profiles'
        """)).one()
        assert flags.relrowsecurity and flags.relforcerowsecurity
        assert cx.execute(text(
            "SELECT COUNT(*) FROM pg_policies WHERE tablename = 'governance_profiles'"
        )).scalar() == 2
        # Cero seed (§5): la postura por defecto emerge del registry en código, no de filas.
        assert cx.execute(text("SELECT COUNT(*) FROM governance_profiles")).scalar() == 0


def test_upgrade_body_is_idempotent(engine):
    """Re-ejecutar el CUERPO de la 012 sobre el esquema ya migrado (stamp 011 → upgrade
    head) no falla ni duplica policies — el patrón IF NOT EXISTS / DROP POLICY del repo."""
    run_alembic(DB, "stamp", "011")
    run_alembic(DB, "upgrade", "head")

    with engine.connect() as cx:
        assert cx.execute(text(
            "SELECT COUNT(*) FROM pg_policies WHERE tablename = 'governance_profiles'"
        )).scalar() == 2
        assert cx.execute(text(
            "SELECT COUNT(*) FROM pg_indexes WHERE indexname = 'ix_audit_logs_tenant_blocked_layer'"
        )).scalar() == 1
