# Imagen de PRODUCCIÓN del backend (spec 020 US1 — FR-001/FR-003).
# Multistage: la etapa builder compila deps (psycopg2 y cía) con toolchain; la
# final es slim SIN build-essential, non-root, sin --reload, con healthcheck.
# Contexto de build: la RAÍZ del repo (docker build -f este archivo .).
# Un codebase, dos perfiles: el compose de dev sigue usando backend/Dockerfile.

# Base pinneada por digest (python:3.12-slim, resuelta 2026-07-20; bump vía publish.sh)
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS builder

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt .
# Wheels precompiladas: la etapa final instala SIN toolchain.
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

# libpq5 = runtime de postgres (sin -dev); curl para el healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --create-home --uid 10001 sentinel

WORKDIR /app
COPY --from=builder /wheels /tmp/wheels
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/tmp/wheels -r requirements.txt \
    && rm -rf /tmp/wheels

# Código HORNEADO (FR-003): sin bind-mounts de fuente en prod.
COPY backend/src ./src
COPY backend/alembic ./alembic
COPY backend/alembic.ini .
# Herramientas de operador (seed del perfil, true-up) — necesarias en el
# install/día-2. license_out/ (claves emitidas) JAMÁS entra: solo los .py.
COPY backend/scripts/*.py ./scripts/
# Librería de política compartida (014): en dev se monta; en prod se hornea en el
# MISMO path que el compose usa, así gateway.py la encuentra sin tocar código.
COPY litellm/extensions ./litellm_config/extensions
COPY deploy/docker/entrypoint/backend.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && chown -R sentinel:sentinel /app

USER sentinel
EXPOSE 8000
# El período largo tolera migraciones Alembic en el arranque.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
