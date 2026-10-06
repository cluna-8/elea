#!/usr/bin/env bash
# Región por defecto de la instalación (spec 057 T095; research R28; QA re-análisis F1 y M1).
#
#   · el override de desarrollo de la extensión (`sentinel/docker/compose.dev.yml`) fija
#     `SENTINEL_ENTITY_REGION` con default `latam_ar` en el backend Y en el motor (Eleia es la línea de América);
#   · `sentinel/extensions.env.example` la fija en `latam_ar`;
#   · `docker-compose.yml` (la suite de CI) y `deploy/docker/compose.prod.yml` (que `bundle.sh` empaqueta para TODO
#     perfil de cliente, incluidos los europeos, cuyo enmascarado depende de los patrones de `eu`) CONSERVAN `eu`:
#     cambiarlo cambia la base para todos. Un perfil que active la extensión sin fijar la región cae en el respaldo
#     fail-closed y `/api/v1/redirect/health` lo informa.
#
# SIN Docker: lectura estática. Cada afirmación se prueba también contra una copia MUTADA, que tiene que fallar.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
fail() { echo "❌ $1"; exit 1; }

DEV="sentinel/docker/compose.dev.yml"
BASE="docker-compose.yml"
PROD="deploy/docker/compose.prod.yml"
EXT_ENV="sentinel/extensions.env.example"

# check_tree <raíz>: devuelve 0 si la región por defecto de cada archivo es la que corresponde.
check_tree() {
  local r="$1" n
  n="$(grep -cE 'SENTINEL_ENTITY_REGION=\$\{SENTINEL_ENTITY_REGION:-latam_ar\}' "$r/$DEV")" || true
  [ "$n" -ge 2 ] || { echo "compose.dev.yml: el default latam_ar tiene que estar en backend y motor (hay $n)"; return 1; }
  grep -qE '^SENTINEL_ENTITY_REGION=latam_ar$' "$r/$EXT_ENV" || { echo "extensions.env.example no fija latam_ar"; return 1; }
  n="$(grep -cE 'SENTINEL_ENTITY_REGION[:=]? *"?\$\{SENTINEL_ENTITY_REGION:-eu\}' "$r/$BASE")" || true
  [ "$n" -ge 2 ] || { echo "docker-compose.yml perdió su default eu (hay $n)"; return 1; }
  n="$(grep -cE 'SENTINEL_ENTITY_REGION: *"\$\{SENTINEL_ENTITY_REGION:-eu\}"' "$r/$PROD")" || true
  [ "$n" -ge 2 ] || { echo "compose.prod.yml perdió su default eu (hay $n)"; return 1; }
  if grep -nE 'SENTINEL_ENTITY_REGION[^#]*:-latam' "$r/$BASE" "$r/$PROD" >/dev/null; then
    echo "la base o el compose de producción no pueden defaultear a latam"; return 1
  fi
  return 0
}

msg="$(check_tree "$REPO_ROOT")" || fail "$msg"
echo "✅ la región por defecto es latam_ar solo en desarrollo de la extensión; la base y producción conservan eu"

# ── mutaciones: cada una tiene que ser detectada ───────────────────────────────────────────────
mutate() {  # mutate <archivo> <sed> <descripción>
  rm -rf "$WORK/m" && mkdir -p "$WORK/m/sentinel/docker" "$WORK/m/deploy/docker"
  for f in "$DEV" "$BASE" "$PROD" "$EXT_ENV"; do mkdir -p "$WORK/m/$(dirname "$f")"; cp "$REPO_ROOT/$f" "$WORK/m/$f"; done
  sed -i -E "$2" "$WORK/m/$1"
  if check_tree "$WORK/m" >/dev/null 2>&1; then fail "la mutación «$3» no fue detectada"; fi
}
mutate "$DEV"     's/:-latam_ar\}/:-eu}/'                                 "dev vuelve a eu"
mutate "$BASE"    's/SENTINEL_ENTITY_REGION:-eu\}/SENTINEL_ENTITY_REGION:-latam_ar}/' "la base defaultea a latam"
mutate "$PROD"    's/SENTINEL_ENTITY_REGION:-eu\}/SENTINEL_ENTITY_REGION:-latam_ar}/' "producción defaultea a latam"
mutate "$EXT_ENV" 's/^SENTINEL_ENTITY_REGION=latam_ar$/SENTINEL_ENTITY_REGION=/' "el entorno de ejemplo no fija la región"
echo "✅ 4 mutaciones detectadas"
