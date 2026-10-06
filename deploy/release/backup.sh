#!/usr/bin/env bash
# Respaldo de las DOS bases del gateway en UNA sola copia.
#
# Desde que el motor tiene base propia (ENGINE_DB, ver deploy/docker/initdb/01-engine-db.sh)
# un `pg_dump` de POSTGRES_DB ya no alcanza: deja afuera las llaves virtuales y los
# contadores de gasto del motor. Este script vuelca las dos y las empaqueta juntas.
#
# Qué produce: <dir>/guardian-backup-<UTC>.tar (modo 0600: tiene identidad y auditoría)
#   gateway.dump  pg_dump -Fc de POSTGRES_DB (usuarios, llaves, presupuestos, audit_logs…)
#   engine.dump   pg_dump -Fc de ENGINE_DB   (tablas del motor: llaves virtuales, gasto…)
#   MANIFEST      nombres de las bases, hora, sha256 de cada dump. Sin secretos.
#
# «Consistente», con la honestidad que corresponde: cada dump es una foto transaccional de
# SU base, pero Postgres no ofrece una foto atómica entre dos bases. Por eso:
#   · el orden es SIEMPRE backend primero, motor después. Una llave creada entre los dos
#     volcados queda en el motor sin estar en el backend (huérfana e inocua); al revés, el
#     backend apuntaría (`api_keys.engine_key_token`) a una llave que el motor no tiene;
#   · la copia es TODO o NADA: se arma en un directorio temporal, cada dump se verifica
#     (`pg_restore -l`) y recién entonces se publica con un `mv`; si algo falla no queda un
#     .tar a medias que alguien pueda tomar por bueno.
# Para una foto exacta, pará el motor durante el respaldo (`docker compose stop engine`).
#
# Uso:  backup.sh [-o DIR] [--env-file ARCHIVO]
#   -o DIR            carpeta destino (default: .). Guardala FUERA del servidor de la base.
#   --env-file ARCHIVO lee POSTGRES_USER/POSTGRES_DB/ENGINE_DB/STACK_PREFIX/DB_CONTAINER de
#                     ahí (se PARSEA, no se ejecuta). Lo ya exportado en el entorno manda.
# Entorno:
#   DB_CONTAINER      contenedor de Postgres (default: ${STACK_PREFIX:-sentinel}-db)
#   POSTGRES_USER, POSTGRES_DB   como en el .env del stack (obligatorias)
#   ENGINE_DB         base del motor (default: sentinel_engine, igual que el compose)
# Restaurar: ver docs/docs/operations/index.md §6.2 (`pg_restore --no-owner` de cada .dump
# en su base; probalo en un stack limpio, un respaldo que no se restauró no es respaldo).
set -euo pipefail

destino="."
env_file=""
while [ $# -gt 0 ]; do
    case "$1" in
        -o) destino="${2:?falta el directorio tras -o}"; shift 2 ;;
        --env-file) env_file="${2:?falta el archivo tras --env-file}"; shift 2 ;;
        -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "backup.sh: argumento desconocido '$1' (probá --help)" >&2; exit 2 ;;
    esac
done

# Lee UNA clave de un .env sin ejecutarlo: solo líneas `CLAVE=valor` exactas, comillas
# externas opcionales. Lo demás (comentarios, `$(…)`, backticks) se ignora.
leer_env() {
    local clave="$1" linea
    linea="$(grep -E "^${clave}=" "$env_file" | tail -n1 || true)"
    linea="${linea#"${clave}="}"
    linea="${linea%\"}"; linea="${linea#\"}"; linea="${linea%\'}"; linea="${linea#\'}"
    printf '%s' "$linea"
}
if [ -n "$env_file" ]; then
    [ -r "$env_file" ] || { echo "backup.sh: no puedo leer $env_file" >&2; exit 2; }
    for k in POSTGRES_USER POSTGRES_DB ENGINE_DB STACK_PREFIX DB_CONTAINER; do
        if [ -z "${!k:-}" ]; then
            v="$(leer_env "$k")"
            [ -z "$v" ] || export "$k=$v"
        fi
    done
fi

usuario="${POSTGRES_USER:-}"
base_gw="${POSTGRES_DB:-}"
base_motor="${ENGINE_DB:-sentinel_engine}"
contenedor="${DB_CONTAINER:-${STACK_PREFIX:-sentinel}-db}"
[ -n "$usuario" ] || { echo "backup.sh: falta POSTGRES_USER" >&2; exit 2; }
[ -n "$base_gw" ] || { echo "backup.sh: falta POSTGRES_DB" >&2; exit 2; }
[ "$base_gw" != "$base_motor" ] || {
    echo "backup.sh: POSTGRES_DB y ENGINE_DB son la MISMA base ('$base_gw'): el stack sigue con base compartida; no hay dos bases que respaldar" >&2
    exit 2
}
mkdir -p "$destino"

pg() { docker exec -i "$contenedor" "$@"; }

existe_base() {
    local n
    n="$(pg psql -U "$usuario" -d postgres -At -v "db=$1" \
        <<<"SELECT count(*) FROM pg_database WHERE datname = :'db'")"
    [ "$n" = "1" ]
}
existe_base "$base_gw" || { echo "backup.sh: no existe la base '$base_gw' en $contenedor" >&2; exit 1; }
existe_base "$base_motor" || {
    echo "backup.sh: no existe la base del motor '$base_motor' en $contenedor — ¿el stack ya la separó? (ENGINE_DB, deploy/docker/initdb/01-engine-db.sh)" >&2
    exit 1
}

tmp="$(mktemp -d "${destino%/}/.backup-XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
umask 077

# Orden fijo: backend primero, motor después (ver cabecera).
pg pg_dump -U "$usuario" -Fc --dbname "$base_gw"    > "$tmp/gateway.dump"
pg pg_dump -U "$usuario" -Fc --dbname "$base_motor" > "$tmp/engine.dump"

# Un dump que no se puede leer no es una copia: se descubre acá, no el día del restore.
for f in gateway engine; do
    [ -s "$tmp/$f.dump" ] || { echo "backup.sh: $f.dump quedó vacío" >&2; exit 1; }
    pg pg_restore -l < "$tmp/$f.dump" > /dev/null \
        || { echo "backup.sh: $f.dump no se puede leer con pg_restore" >&2; exit 1; }
done

sha() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'; else shasum -a 256 "$1" | awk '{print $1}'; fi; }
{
    echo "formato=guardian-backup-v1"
    echo "creado_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "gateway_db=$base_gw"
    echo "engine_db=$base_motor"
    echo "orden_de_volcado=gateway,engine"
    echo "sha256 gateway.dump=$(sha "$tmp/gateway.dump")"
    echo "sha256 engine.dump=$(sha "$tmp/engine.dump")"
} > "$tmp/MANIFEST"

nombre="guardian-backup-$(date -u +%Y%m%dT%H%M%SZ).tar"
tar -C "$tmp" -cf "$tmp/$nombre" gateway.dump engine.dump MANIFEST
chmod 600 "$tmp/$nombre"
mv "$tmp/$nombre" "${destino%/}/$nombre"
echo "✅ copia de las dos bases ('$base_gw' + '$base_motor'): ${destino%/}/$nombre"
echo "   Llevala fuera del servidor de la base; probá restaurarla en un stack limpio."
