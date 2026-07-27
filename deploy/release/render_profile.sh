#!/usr/bin/env bash
# Renderiza el perfil de un cliente (spec 020 US3): env + branding + config
# templado → deploy/clients/<slug>/rendered/ (gitignored), listo para el
# compute (cloud-init, US4) o el compose on-prem (US6).
# Deriva dominio y workspace del tenant.slug (FR-014, Principio III).
set -euo pipefail
SLUG="${1:?uso: render_profile.sh <client-slug>}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# El perfil puede vivir FUERA del repo del producto (repo del partner):
PROFILES_ROOT="${PROFILES_ROOT:-$REPO_ROOT/deploy/clients}"
PROFILE="$PROFILES_ROOT/$SLUG"
OUT="$PROFILE/rendered"
[ -d "$PROFILE" ] || { echo "❌ no existe el perfil $PROFILE"; exit 1; }

set -a; source "$PROFILE/client.env"; source "$PROFILE/branding.env"; set +a
[ "$TENANT_SLUG" = "$SLUG" ] || { echo "❌ TENANT_SLUG ($TENANT_SLUG) != dir del perfil ($SLUG)"; exit 1; }

export PRODUCT_DOMAIN="${PRODUCT_DOMAIN:-${TENANT_SLUG}.${BASE_DOMAIN}}"
export TOFU_WORKSPACE="${TENANT_SLUG}"
mkdir -p "$OUT"

# config.yaml del motor: SOLO se sustituyen las vars del PERFIL — los
# os.environ/* del runtime del motor quedan intactos (los resuelve LiteLLM).
# La lista se deriva del client.env del propio perfil: cada cliente declara
# sus CLIENT_* sin tocar este script (fix pre-piloto — antes era hardcodeada
# y una var nueva del template quedaba sin resolver).
PROFILE_VARS="$(grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' "$PROFILE/client.env" \
    | sed 's/=$//' | sed 's/^/${/;s/$/}/' | tr '\n' ' ')"
envsubst "$PROFILE_VARS" < "$PROFILE/config.yaml.tmpl" > "$OUT/config.yaml"
grep -q '\${' "$OUT/config.yaml" && { echo "❌ variables sin resolver en config.yaml"; exit 1; } || true

# brand.json desde branding.env (una sola fuente de verdad: env).
cat > "$OUT/brand.json" <<JSON
{
  "name": "${BRAND_NAME}",
  "tagline": "${BRAND_TAGLINE}",
  "supportContact": "${BRAND_SUPPORT}",
  "colors": {
    "primary": "${BRAND_COLOR_PRIMARY}",
    "background": "${BRAND_COLOR_BACKGROUND}",
    "panel": "${BRAND_COLOR_PANEL}"
  }
}
JSON

# env consolidado para el compose prod / cloud-init (sin secretos: US5 los junta).
{
  cat "$PROFILE/client.env"
  echo "PRODUCT_DOMAIN=${PRODUCT_DOMAIN}"
  echo "TOFU_WORKSPACE=${TOFU_WORKSPACE}"
  echo "BRAND_NAME=${BRAND_NAME}"
  echo "BRAND_SERVICE_ID=${TENANT_SLUG}-ai-gateway"
} > "$OUT/instance.env"

# Guarda de completitud de imágenes (hallazgo 2026-07-27, víspera del install de la
# Cámara): el perfil no declaraba NLP_ANALYZER_IMAGE, que compose.prod.yml exige con
# `${...:?}`. El render salía ✅ y el fallo aparecía recién en el `up` — en la sede del
# cliente. La lista NO se hardcodea: se deriva del propio compose, así que agregar un
# servicio nuevo con imagen pinneada queda cubierto sin tocar este script.
COMPOSE_PROD="$REPO_ROOT/deploy/docker/compose.prod.yml"
if [ -f "$COMPOSE_PROD" ]; then
  faltan=""
  # `image: "${VAR:?...}"` = variable obligatoria que el PERFIL debe aportar.
  for var in $(grep -oE '^[[:space:]]*image:[[:space:]]*"\$\{[A-Z_]+:\?' "$COMPOSE_PROD" \
                 | grep -oE '\{[A-Z_]+' | tr -d '{' | sort -u); do
    grep -qE "^${var}=" "$OUT/instance.env" || faltan="$faltan $var"
  done
  if [ -n "$faltan" ]; then
    echo "❌ el perfil '$SLUG' no declara imágenes que compose.prod.yml exige:$faltan"
    echo "   Agregalas a $PROFILE/client.env y volvé a renderizar."
    echo "   (sin esto el render sale verde y el stack revienta en el 'up', en sede)"
    exit 1
  fi
fi

echo "✅ perfil '$SLUG' renderizado en $OUT (dominio=$PRODUCT_DOMAIN workspace=$TOFU_WORKSPACE)"
