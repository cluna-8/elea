"""Harness compartido para los tests de la migración 010 (spec 013).

Crea bases de datos de test descartables contra el Postgres de Docker Compose y corre
alembic programáticamente. Las migraciones y las conexiones de test usan un rol
**NOSUPERUSER** (``rls_owner``) dueño de las tablas: así ``FORCE ROW LEVEL SECURITY``
es observable (un superuser como ``sentinel_admin`` bypasea RLS SIEMPRE, incluso con
FORCE — la trampa está documentada en el header de la 010 y testeada explícitamente).

Los tests se auto-skipean si Postgres no está disponible (mismo patrón que los smoke
tests live del repo). Host: localhost:5433 (docker-compose de sentinel-guardian) o el env
POSTGRES_* cuando corren dentro del container backend.
"""
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

BACKEND_ROOT = Path(__file__).resolve().parent.parent

PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
# En el host el compose publica 5433 (5432 lo ocupa el repo demo gatelite); dentro
# del container backend el env trae POSTGRES_PORT=5432.
PG_PORT = os.getenv("POSTGRES_PORT") or ("5433" if PG_HOST == "localhost" else "5432")
ADMIN_USER = os.getenv("POSTGRES_USER", "sentinel_admin")
ADMIN_PASSWORD = os.getenv("POSTGRES_PASSWORD", "sentinelsecurepass123")

RLS_OWNER = "rls_owner"
RLS_OWNER_PASSWORD = "rls-owner-secret"

DEFAULT_TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")

# IDs deterministas del seed legacy (pre-010) para asserts de backfill
LEGACY = {
    "group": uuid.UUID("11111111-0000-0000-0000-000000000001"),
    "user_admin": uuid.UUID("11111111-0000-0000-0000-000000000011"),
    "user_officer": uuid.UUID("11111111-0000-0000-0000-000000000012"),
    "user_clinician": uuid.UUID("11111111-0000-0000-0000-000000000013"),
    "user_developer": uuid.UUID("11111111-0000-0000-0000-000000000014"),
    "user_dirty": uuid.UUID("11111111-0000-0000-0000-000000000015"),
    "key_linked": uuid.UUID("11111111-0000-0000-0000-000000000021"),
    "key_orphan": uuid.UUID("11111111-0000-0000-0000-000000000022"),
    "key_dup": uuid.UUID("11111111-0000-0000-0000-000000000023"),
}


def url(user: str, password: str, dbname: str) -> str:
    return f"postgresql://{user}:{password}@{PG_HOST}:{PG_PORT}/{dbname}"


def require_postgres():
    """Skip a nivel módulo si el Postgres de Compose no está levantado."""
    try:
        engine = create_engine(url(ADMIN_USER, ADMIN_PASSWORD, "postgres"),
                               connect_args={"connect_timeout": 3})
        with engine.connect():
            pass
        engine.dispose()
    except Exception:
        pytest.skip(
            f"Postgres no disponible en {PG_HOST}:{PG_PORT} — levantar `docker compose up -d db`",
            allow_module_level=True,
        )


def _admin(dbname: str = "postgres"):
    return create_engine(url(ADMIN_USER, ADMIN_PASSWORD, dbname),
                         isolation_level="AUTOCOMMIT")


def ensure_rls_owner():
    """Rol NOSUPERUSER dueño de las tablas de test (ver docstring del módulo)."""
    engine = _admin()
    with engine.connect() as cx:
        cx.execute(text(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{RLS_OWNER}') THEN
                    CREATE ROLE {RLS_OWNER} LOGIN PASSWORD '{RLS_OWNER_PASSWORD}' NOSUPERUSER;
                END IF;
            END $$;
        """))
    engine.dispose()


def fresh_db(dbname: str):
    """DROP + CREATE de la base de test, con rls_owner como dueño."""
    ensure_rls_owner()
    engine = _admin()
    with engine.connect() as cx:
        cx.execute(text(f"""
            SELECT pg_terminate_backend(pid) FROM pg_stat_activity
            WHERE datname = '{dbname}' AND pid != pg_backend_pid()
        """))
        cx.execute(text(f"DROP DATABASE IF EXISTS {dbname}"))
        cx.execute(text(f"CREATE DATABASE {dbname} OWNER {RLS_OWNER}"))
    engine.dispose()


def run_alembic(dbname: str, action: str, revision: str):
    """Corre alembic contra la DB de test conectado como rls_owner (dueño)."""
    overrides = {
        "POSTGRES_HOST": PG_HOST,
        "POSTGRES_PORT": PG_PORT,
        "POSTGRES_USER": RLS_OWNER,
        "POSTGRES_PASSWORD": RLS_OWNER_PASSWORD,
        "POSTGRES_DB": dbname,
    }
    saved = {k: os.environ.get(k) for k in overrides}
    os.environ.update(overrides)
    try:
        cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
        getattr(command, action)(cfg, revision)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def owner_engine(dbname: str):
    return create_engine(url(RLS_OWNER, RLS_OWNER_PASSWORD, dbname))


def superuser_engine(dbname: str):
    return create_engine(url(ADMIN_USER, ADMIN_PASSWORD, dbname))


def seed_legacy_single_tenant(engine):
    """Puebla la DB en revisión 009 como un despliegue on-prem real (sin tenant_id):
    roles legacy sucios incluidos, filas huérfanas incluidas (edge cases del backfill)."""
    ids = LEGACY
    with engine.begin() as cx:
        cx.execute(text(
            "INSERT INTO groups (id, name) VALUES (:id, 'legacy-group')"
        ), {"id": ids["group"]})

        for key, username, role in [
            ("user_admin", "legacy-admin", "admin"),
            ("user_officer", "legacy-officer", "compliance_officer"),
            ("user_clinician", "legacy-clinician", "clinician"),
            ("user_developer", "legacy-developer", "developer"),
            ("user_dirty", "legacy-dirty", "hacker"),
        ]:
            cx.execute(text("""
                INSERT INTO users (id, username, email, password_hash, role, group_id)
                VALUES (:id, :username, :email, 'x', :role, :group_id)
            """), {"id": ids[key], "username": username, "email": f"{username}@legacy.sentinel.com.ar",
                   "role": role, "group_id": ids["group"]})

        cx.execute(text("""
            INSERT INTO api_keys (id, key_hash, key_preview, user_id, group_id, name)
            VALUES (:id, 'hash-linked', 'sk-...linked', :user_id, :group_id, 'linked-key')
        """), {"id": ids["key_linked"], "user_id": ids["user_admin"], "group_id": ids["group"]})
        # Duplicada del mismo user (patrón legacy real: N keys por usuario) — la 010
        # debe deduplicar (la más NUEVA queda activa) antes del índice único parcial.
        cx.execute(text("""
            INSERT INTO api_keys (id, key_hash, key_preview, user_id, group_id, name, created_at)
            VALUES (:id, 'hash-dup', 'sk-...dup', :user_id, :group_id, 'duplicate-key',
                    NOW() + interval '1 hour')
        """), {"id": ids["key_dup"], "user_id": ids["user_admin"], "group_id": ids["group"]})
        # Huérfana: sin user ni group (edge case FR-005 — cae al default tenant)
        cx.execute(text("""
            INSERT INTO api_keys (id, key_hash, key_preview, name)
            VALUES (:id, 'hash-orphan', 'sk-...orphan', 'orphan-key')
        """), {"id": ids["key_orphan"]})

        cx.execute(text("""
            INSERT INTO budgets (user_id, max_spend_usd, max_tokens, reset_period)
            VALUES (:user_id, 100, 1000000, 'monthly')
        """), {"user_id": ids["user_admin"]})
        cx.execute(text("""
            INSERT INTO budgets (max_spend_usd, max_tokens, reset_period)
            VALUES (50, 500000, 'monthly')
        """))

        cx.execute(text("""
            INSERT INTO audit_logs (user_id, model, prompt_tokens, completion_tokens,
                                    cost_usd, compliance_status, latency_ms)
            VALUES (:user_id, 'sentinel-model', 10, 20, 0.001, 'passed', 100)
        """), {"user_id": ids["user_clinician"]})
        # Huérfana: user_id NULL (edge case FR-005)
        cx.execute(text("""
            INSERT INTO audit_logs (model, prompt_tokens, completion_tokens,
                                    cost_usd, compliance_status, latency_ms)
            VALUES ('sentinel-model', 5, 5, 0.0005, 'passed', 80)
        """))

        cx.execute(text("""
            INSERT INTO security_policies (name, entity_configs)
            VALUES ('legacy-policy', '{"PERSON": "MASK"}')
        """))
        cx.execute(text("INSERT INTO guardians (name, guardian_type) VALUES ('legacy-guardian', 'regex')"))
        cx.execute(text("""
            INSERT INTO compliance_projects (name, legal_basis) VALUES ('legacy-project', 'consent')
        """))
        cx.execute(text("""
            INSERT INTO consent_records (user_id, consent_type, version)
            VALUES (:user_id, 'ai_use', 'v1')
        """), {"user_id": ids["user_clinician"]})
        cx.execute(text("INSERT INTO dpa_registry (provider_name) VALUES ('legacy-provider')"))
        cx.execute(text("""
            INSERT INTO data_subject_requests (request_type, subject_identifier, date_received)
            VALUES ('access', 'subject-1', '2026-01-01')
        """))
        cx.execute(text("INSERT INTO human_reviews (reviewer_id) VALUES ('legacy-reviewer')"))
        cx.execute(text("""
            INSERT INTO retention_policies (log_type, retention_days) VALUES ('audit', 365)
        """))


# Las 13 tablas que la 010 BACKFILLEÓ. Este es el contrato que consume
# test_migration_010: cada una tiene filas del seed legacy, tenant_id NOT NULL y
# fk_<tabla>_tenant. NO agregar acá tablas nacidas después de la 010: no tienen backfill
# que verificar y el seed legacy (revisión 009) no puede poblarlas.
TENANT_TABLES = [
    "groups", "users", "api_keys", "budgets", "audit_logs", "consent_records",
    "security_policies", "guardians", "compliance_projects", "dpa_registry",
    "data_subject_requests", "human_reviews", "retention_policies",
]

# Tablas tenant-scoped nacidas DESPUÉS de la 010: sin backfill (nacen con tenant_id), pero
# la exigencia de aislamiento es IDÉNTICA. Existen como lista aparte porque la omisión de
# governance_profiles en la 012 (hallazgo A1) fue invisible justamente por apoyarse en una
# lista hardcodeada con dos significados mezclados. **Toda tabla nueva con tenant_id se
# agrega acá el mismo día que su migración.**
POST_010_TENANT_TABLES = [
    "governance_profiles",   # 027 — decide qué capas de seguridad corren por tenant
    "sso_providers",         # 017 US2 (T013) — proveedores SSO por tenant
]

# Universo COMPLETO bajo aislamiento por tenant: lo que debe tener ENABLE + FORCE RLS y las
# dos policies. Es la lista que corresponde barrer en los tests de RLS
# (test_migration_012.py ya la usa; test_rls_isolation.py sigue barriendo TENANT_TABLES y
# debería migrar a esta en un cambio aparte — está fuera del alcance de la 027).
RLS_TENANT_TABLES = TENANT_TABLES + POST_010_TENANT_TABLES


def migrated_legacy_db(dbname: str):
    """Pipeline completo: DB fresca → 009 → seed legacy → head. Devuelve engine (owner)."""
    fresh_db(dbname)
    run_alembic(dbname, "upgrade", "009")
    engine = owner_engine(dbname)
    seed_legacy_single_tenant(engine)
    run_alembic(dbname, "upgrade", "head")
    return engine
