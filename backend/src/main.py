import logging
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

# Create database tables on startup (automatic migration for development)
try:
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully.")
except Exception as e:
    logger.error(f"Error creating database tables: {e}")

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
)

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
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
