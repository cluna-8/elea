#!/usr/bin/env bash
# T035 (US6, FR-028): el bundle contiene TODAS las imágenes que el release
# referencia y docker load las restaura sin registry. Valida el MECANISMO
# save/manifest/load con las imágenes prod locales + una imagen chica como
# doble de las de terceros (motor/db/redis) para no forzar pulls.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
fail() { echo "❌ $1"; exit 1; }

docker image inspect basa-backend:prod basa-frontend:prod >/dev/null 2>&1 \
    || fail "faltan las imágenes prod locales (make -C deploy build)"

BACKEND_IMAGE=basa-backend:prod FRONTEND_IMAGE=basa-frontend:prod \
LITELLM_IMAGE=caddy:2-alpine CADDY_IMAGE=caddy:2-alpine DOCS_IMAGE=basa-docs:prod \
NLP_ANALYZER_IMAGE=caddy:2-alpine \
POSTGRES_IMAGE=caddy:2-alpine REDIS_IMAGE=caddy:2-alpine \
    "$REPO_ROOT/deploy/release/bundle.sh" example "$WORK/bundle" >/dev/null

[ -f "$WORK/bundle/images.tar" ] || fail "sin images.tar"
[ -f "$WORK/bundle/MANIFEST" ] || fail "sin MANIFEST"
[ -f "$WORK/bundle/profile/config.yaml" ] || fail "el perfil renderizado no viaja en el bundle"

# docker load restaura todas las imágenes ÚNICAS del manifiesto, sin registry.
expected=$(grep -v "^#" "$WORK/bundle/MANIFEST" | awk '{print $1}' | sort -u | wc -l | tr -d ' ')
loaded=$(docker load -i "$WORK/bundle/images.tar" | grep -c "Loaded image" || true)
[ "$loaded" -ge "$expected" ] || fail "docker load restauró $loaded imágenes (únicas esperadas: $expected)"

echo "✅ bundle air-gapped OK: $loaded/$expected imágenes únicas restauradas por docker load, perfil incluido"
