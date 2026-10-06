#!/bin/sh
# Crea la base PROPIA del motor del gateway (nombre en ENGINE_DB, default sentinel_engine).
#
# Por qué una base aparte: el migrador del motor, en el primer arranque contra una
# base que tiene tablas pero no su libro de migraciones —y tras cualquier actualización que
# traiga migraciones nuevas—, aplica un diff «base viva → su schema» que DROPea como
# «drift» toda tabla ajena. Compartir base con el backend destruía el esquema del producto
# (reproducido dos veces: ensayo pre-piloto 2026-07-22 y análisis de bases del motor
# 2026-10). Bases separadas = aislamiento permanente, también ante upgrades del motor.
#
# UN solo script para los dos caminos, para que el nombre no pueda divergir:
#   · initdb de Postgres (compose de producción): el entrypoint de la imagen lo ejecuta —o
#     lo SOURCEA, si no es ejecutable— al inicializar un volumen VACÍO, por el socket local.
#   · servicio de un solo disparo (compose de desarrollo): corre contra `db` por TCP
#     (PGHOST/PGPASSWORD) en CADA `up`, así que también sirve con un volumen que ya existe,
#     donde initdb no vuelve a correr.
# Es IDEMPOTENTE: el CREATE DATABASE solo se emite si la base no existe.
#
# Reglas del script (cada una evita un fallo que ya mordió o que el entrypoint haría mudo):
#   · POSIX sh: lo corre busybox en el servicio de un disparo (imagen alpine).
#   · Todo en un subshell: sourceado dentro del entrypoint, ni sus `set` ni un `exit`
#     pueden tocar el shell que lo llama. Si algo falla, el subshell sale != 0 y el
#     entrypoint (que corre con `set -e`) aborta la inicialización ruidosamente.
#   · Sin OWNER explícito: `CREATE DATABASE … OWNER CURRENT_USER` NO es SQL válido
#     (fix del ensayo 2026-07-27); omitirlo deja de dueño al rol que ejecuta, que es
#     POSTGRES_USER.
#   · El nombre viaja como VARIABLE de psql (`-v db=…`) y se cita con %I / :'db': nada de
#     concatenarlo en el texto del SQL.
(
    set -eu
    engine_db="${ENGINE_DB:-sentinel_engine}"
    usuario="${POSTGRES_USER:-${PGUSER:-}}"
    if [ -z "$usuario" ]; then
        echo "01-engine-db: falta POSTGRES_USER (o PGUSER) para conectarse a Postgres" >&2
        exit 1
    fi
    echo "01-engine-db: asegurando la base del motor '$engine_db'"
    psql -v ON_ERROR_STOP=1 -v "db=$engine_db" --username "$usuario" --dbname postgres <<'SQL'
SELECT format('CREATE DATABASE %I', :'db')
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'db')
\gexec
SQL
)
