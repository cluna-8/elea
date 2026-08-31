import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional
from uuid import UUID

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

# Database URL configuration
POSTGRES_USER = os.getenv("POSTGRES_USER", "sentinel_admin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "sentinelsecurepass123")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "db")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "sentinel_gateway")

SQLALCHEMY_DATABASE_URL = (
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

# Create SQLAlchemy engine with connection pooling for high performance
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_size=10,          # Minimum number of connections to keep in the pool
    max_overflow=20,       # Maximum number of connections that can be opened beyond pool_size
    pool_timeout=30,       # Seconds to wait before giving up on getting a connection from the pool
    pool_recycle=1800,     # Recycle connections after 30 minutes to prevent silent drops by RDS/Firewall
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# ── Contexto de tenant por request (spec 013, FR-024) ─────────────────────────────
# La capa de identidad (custom_auth del firewall 014 / auth 017) setea estos
# ContextVars con la identidad RESUELTA; NUNCA se setea un default silencioso acá
# (SC-3, fail-closed). Mientras nadie los setea, el GUC no se inyecta y aplica la
# policy permisiva tenant_isolation_bootstrap de la migración 010 (ventana de deploy
# on-prem); la 017 elimina esa policy al cablear la identidad por request.
current_tenant_id: ContextVar[Optional[UUID]] = ContextVar("current_tenant_id", default=None)
rls_bypass: ContextVar[bool] = ContextVar("rls_bypass", default=False)


@event.listens_for(SessionLocal, "after_begin")
def _inject_tenant_guc(session, transaction, connection):
    """Inyecta los GUC de RLS al inicio de CADA transacción de la sesión.

    ``SET LOCAL`` muere con el commit; los code paths heredados commitean a mitad de
    request, así que el GUC se re-inyecta por transacción (no una vez por sesión).
    ``set_config(..., true)`` = SET LOCAL con bind params.
    """
    tenant_id = current_tenant_id.get()
    if tenant_id is not None:
        connection.exec_driver_sql(
            "SELECT set_config('app.current_tenant', %s, true)", (str(tenant_id),)
        )
    if rls_bypass.get():
        # Solo super_admin (cross-tenant, cloud) — la capa de identidad lo decide.
        connection.exec_driver_sql(
            "SELECT set_config('app.bypass_rls', 'on', true)", ()
        )


@contextmanager
def tenant_context(tenant_id: Optional[UUID], bypass: bool = False):
    """Scopea el tenant efectivo (y el bypass de super_admin) para el bloque actual.

    Uso: servicios/tests; la 014/017 lo llaman desde la identidad resuelta por request.
    """
    token_tenant = current_tenant_id.set(tenant_id)
    token_bypass = rls_bypass.set(bypass)
    try:
        yield
    finally:
        current_tenant_id.reset(token_tenant)
        rls_bypass.reset(token_bypass)


# Dependency to get db session in FastAPI routes
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
