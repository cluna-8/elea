#!/usr/bin/env bash
# Entrypoint PROD del backend (spec 020 US1): migraciones + workers, sin --reload.
# Los workers se dimensionan por env (default 2: la VM v1 es chica a propósito).
set -euo pipefail

# Alembic corre acá (explícito y logueado) — el auto-run del import queda como
# cinturón (RUN_ALEMBIC_ON_STARTUP), pero el camino prod no depende de él.
cd /app
python -m alembic upgrade head

exec python -m uvicorn src.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --no-access-log
