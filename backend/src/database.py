import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Database URL configuration
POSTGRES_USER = os.getenv("POSTGRES_USER", "basa_admin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "basasecurepass123")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "db")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "basa_gateway")

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

# Dependency to get db session in FastAPI routes
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
