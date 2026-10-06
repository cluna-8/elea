#!/usr/bin/env bash
# Casos NEGATIVOS (y de nombre-agnosticismo) de test_redis_wiring.sh. Sin Docker: parte de los
# compose reales, les muta una copia en un tmp y corre el check apuntado a las copias
# (REDIS_WIRING_PROD / REDIS_WIRING_DEV). Demuestra que el check sigue DETECTANDO la falta de
# Redis en el motor —no sólo que pasa con los ficheros sanos—.
#
# Casos:
#   0. control: los compose reales pasan.
#   1. al motor se le quita REDIS_HOST/REDIS_PORT (prod y dev)  → debe FALLAR, nombrando al motor.
#   2. al motor se le quita sólo REDIS_PORT (prod)              → debe FALLAR.
#   3. el servicio del motor se renombra                        → debe seguir PASANDO (criterio por imagen).
#   4. ningún servicio con imagen de motor                      → debe FALLAR (no pasa por casualidad).
#   5. dos servicios con imagen de motor                        → debe FALLAR (no se adivina cuál).
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
CHECK="$REPO_ROOT/deploy/release/checks/test_redis_wiring.sh"
PROD="$REPO_ROOT/deploy/docker/compose.prod.yml"
DEV="$REPO_ROOT/docker-compose.yml"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

fallos=0
# Nombre del servicio del motor en un compose, por imagen (misma idea que el check).
motor_de() {
    awk '/^  [a-zA-Z_-]+:$/ { s=$1; sub(/:$/,"",s); next }
         /^    image:/ && ($0 ~ /litellm/ || $0 ~ /SENTINEL_ENGINE_IMAGE/) { print s; exit }' "$1"
}
# Quita las líneas que casan $2 SÓLO dentro del servicio $3 del fichero $1 (stdout).
quitar_en_servicio() {
    awk -v pat="$2" -v svc="$3" '
        $0 ~ "^  " svc ":$" { dentro = 1; print; next }
        dentro && /^  [a-zA-Z_-]+:$/ { dentro = 0 }
        dentro && $0 ~ pat { next }
        { print }
    ' "$1"
}
correr() { REDIS_WIRING_PROD="$1" REDIS_WIRING_DEV="$2" bash "$CHECK" 2>&1; }
esperar() { # nombre, rc esperado ("0"|"!0"), rc real, salida, [fragmento esperado en la salida]
    local nombre="$1" esperado="$2" rc="$3" salida="$4" frag="${5:-}" ok=1
    if [ "$esperado" = 0 ] && [ "$rc" != 0 ]; then ok=0; fi
    if [ "$esperado" != 0 ] && [ "$rc" = 0 ]; then ok=0; fi
    if [ -n "$frag" ] && ! grep -qF -- "$frag" <<<"$salida"; then ok=0; fi
    if [ "$ok" = 1 ]; then echo "  ✔ $nombre (rc=$rc)"; else
        echo "  ✘ $nombre (rc=$rc, esperado $esperado${frag:+, con '$frag'})"; sed 's/^/      | /' <<<"$salida"; fallos=1; fi
}

MOTOR_PROD="$(motor_de "$PROD")"; MOTOR_DEV="$(motor_de "$DEV")"
[ -n "$MOTOR_PROD" ] && [ -n "$MOTOR_DEV" ] || { echo "❌ no pude ubicar el motor en los compose reales"; exit 1; }

echo "test_redis_wiring (negativos) — motor prod='$MOTOR_PROD' dev='$MOTOR_DEV'"

out="$(correr "$PROD" "$DEV")"; esperar "0. control: compose reales" 0 $? "$out"

quitar_en_servicio "$PROD" 'REDIS_(HOST|PORT)[:=]' "$MOTOR_PROD" > "$WORK/prod_sin.yml"
quitar_en_servicio "$DEV"  'REDIS_(HOST|PORT)[:=]' "$MOTOR_DEV"  > "$WORK/dev_sin.yml"
out="$(correr "$WORK/prod_sin.yml" "$DEV")"; esperar "1a. prod: motor sin Redis" '!0' $? "$out" "el servicio '$MOTOR_PROD' no recibe REDIS_HOST"
out="$(correr "$PROD" "$WORK/dev_sin.yml")"; esperar "1b. dev: motor sin Redis" '!0' $? "$out" "el servicio '$MOTOR_DEV' no recibe REDIS_HOST"

quitar_en_servicio "$PROD" 'REDIS_PORT[:=]' "$MOTOR_PROD" > "$WORK/prod_sin_puerto.yml"
out="$(correr "$WORK/prod_sin_puerto.yml" "$DEV")"; esperar "2. prod: motor sin REDIS_PORT" '!0' $? "$out" "el servicio '$MOTOR_PROD' no recibe REDIS_PORT"

sed "s/^  ${MOTOR_PROD}:\$/  motor-renombrado:/" "$PROD" > "$WORK/prod_renombrado.yml"
sed "s/^  ${MOTOR_DEV}:\$/  motor-renombrado:/" "$DEV"  > "$WORK/dev_renombrado.yml"
out="$(correr "$WORK/prod_renombrado.yml" "$WORK/dev_renombrado.yml")"; esperar "3. motor renombrado sigue verificado" 0 $? "$out"

# Renombrado Y sin Redis: tampoco se escapa (el criterio no depende del nombre).
quitar_en_servicio "$WORK/prod_renombrado.yml" 'REDIS_(HOST|PORT)[:=]' motor-renombrado > "$WORK/prod_ren_sin.yml"
out="$(correr "$WORK/prod_ren_sin.yml" "$DEV")"; esperar "3b. renombrado y sin Redis → falla" '!0' $? "$out" "el servicio 'motor-renombrado' no recibe REDIS_HOST"

sed -E 's#^(    image:).*(litellm|SENTINEL_ENGINE_IMAGE).*#\1 "otra-cosa:1"#' "$PROD" > "$WORK/prod_sin_motor.yml"
out="$(correr "$WORK/prod_sin_motor.yml" "$DEV")"; esperar "4. sin servicio de motor → falla" '!0' $? "$out" "hay 0"

{ cat "$PROD"; printf '\n  motor-bis:\n    image: "${SENTINEL_ENGINE_IMAGE}"\n'; } > "$WORK/prod_dos.yml"
out="$(correr "$WORK/prod_dos.yml" "$DEV")"; esperar "5. dos motores → falla" '!0' $? "$out" "hay 2"

if [ "$fallos" = 0 ]; then echo "✅ test_redis_wiring negativos OK"; else echo "❌ test_redis_wiring negativos FALLÓ"; fi
exit $fallos
