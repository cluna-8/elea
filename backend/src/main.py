import os
import logging
from pathlib import Path
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .database import engine, Base
from .models import *  # Import all models to register them
from .api import api_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("basa-secure-gateway")


def _run_alembic_upgrade_head() -> None:
    """Apply Alembic migrations to head on startup (idempotent).

    This is the source of truth for the DB schema in production: the running schema is
    driven by migrations, not by SQLAlchemy model metadata drift. Disabled when
    RUN_ALEMBIC_ON_STARTUP != 'true' (default: enabled).
    """
    if os.getenv("RUN_ALEMBIC_ON_STARTUP", "true").lower() != "true":
        logger.info("Alembic auto-run disabled by RUN_ALEMBIC_ON_STARTUP env.")
        return
    try:
        from alembic.config import Config
        from alembic import command

        backend_root = Path(__file__).resolve().parent.parent
        cfg = Config(str(backend_root / "alembic.ini"))
        cfg.set_main_option("script_location", str(backend_root / "alembic"))
        command.upgrade(cfg, "head")
        logger.info("Alembic migrations applied (upgrade head).")
    except Exception as e:
        # Do not crash startup: log loudly so ops notice. Inference will still fail fast
        # on schema mismatch, which is preferable to silent drift.
        logger.error("Alembic auto-run failed (schema may be stale): %s", e)


def _create_tables_legacy() -> None:
    """Dev convenience: create tables from model metadata. Gated behind
    CREATE_TABLES_ON_STARTUP=true (default: false) because create_all can mask
    migration drift — only the legacy/dev path uses it. Production uses Alembic.
    """
    if os.getenv("CREATE_TABLES_ON_STARTUP", "false").lower() != "true":
        return
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created (CREATE_TABLES_ON_STARTUP=true).")
    except Exception as e:
        logger.error("Error creating database tables: %s", e)


# Schema initialization: Alembic is the source of truth (default). create_all is opt-in for dev.
if os.getenv("CREATE_TABLES_ON_STARTUP", "false").lower() == "true":
    _create_tables_legacy()
else:
    _run_alembic_upgrade_head()

# Gate de ARRANQUE de licencia (spec 021 US1): verificación Ed25519 OFFLINE del
# token inyectado por la 020. Fail-closed para la CREACIÓN de seats (gate en
# keys/users), pero jamás mata el proceso (SC-013) — initialize() no levanta.
from .licensing import entitlement as license_entitlement  # noqa: E402

license_entitlement.initialize()

app = FastAPI(
    title="Basa Secure AI Gateway API (by basa dev)",
    description="Secure, white-labeled AI gateway with PII/PHI masking, budgets, and compliance policies.",
    version="1.0.0",
)

# Include API Router
app.include_router(api_router)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://localhost:5173"],  # New and old frontend development ports
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# Global exception handler — never leak tracebacks to the client. Full tracebacks in server
# logs are gated behind DEBUG=true (default off in production) to keep logs low-noise and avoid
# accidental disclosure if logs are aggregated/shipped.
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    _debug = os.getenv("DEBUG", "false").lower() == "true"
    logger.error(
        "Unhandled exception on %s %s: %s",
        request.method, request.url.path, exc,
        exc_info=_debug,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An internal server error occurred. Please contact administrator.",
            "error_type": "InternalServerError"
        }
    )

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "basa-secure-ai-gateway-backend",
        "version": "1.0.0"
    }
