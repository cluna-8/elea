#!/usr/bin/env bash
# Entrypoint PROD del backend (spec 020 US1): migraciones + workers, sin --reload.
# Los workers se dimensionan por env (default 2: la VM v1 es chica a propósito).
set -euo pipefail

cd /app

# 1) Esperar a que Postgres acepte conexiones (primer arranque: la DB inicializa
#    en paralelo — sin esto, alembic muere con connection-refused y el
#    contenedor entra en crash-loop; hallazgo del ensayo pre-piloto 2026-07-22).
python - <<'PYWAIT'
import os, sys, time
import psycopg2
dsn = dict(host=os.getenv("POSTGRES_HOST", "db"), port=os.getenv("POSTGRES_PORT", "5432"),
           dbname=os.getenv("POSTGRES_DB"), user=os.getenv("POSTGRES_USER"),
           password=os.getenv("POSTGRES_PASSWORD"))
for i in range(60):
    try:
        psycopg2.connect(connect_timeout=3, **dsn).close()
        print(f"db lista (intento {i+1})"); sys.exit(0)
    except Exception:
        time.sleep(2)
print("db inalcanzable tras 120s", file=sys.stderr); sys.exit(1)
PYWAIT

# 2) Alembic con REINTENTOS: en el primer arranque el motor corre SUS propias
#    migraciones (Prisma, ~6-8 min) sobre la misma base — la contención de locks
#    DDL puede tumbar un intento; reintentar es benigno (alembic es idempotente).
for intento in 1 2 3 4 5; do
    if python -m alembic upgrade head; then
        break
    fi
    echo "alembic: intento $intento falló (¿contención con las migraciones del motor?); reintento en 20s" >&2
    [ "$intento" = 5 ] && { echo "alembic: agotados los reintentos" >&2; exit 1; }
    sleep 20
done

exec python -m uvicorn src.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --no-access-log
