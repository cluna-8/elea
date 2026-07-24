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
# Las líneas de IMAGEN tienen $2 = "sha256:<id>"; las de ARTEFACTO (zip de extensión)
# un sha256 pelado — se excluyen del conteo de imágenes por ese prefijo.
expected=$(grep -v "^#" "$WORK/bundle/MANIFEST" | awk '$2 ~ /^sha256:/ {print $1}' | sort -u | wc -l | tr -d ' ')
loaded=$(docker load -i "$WORK/bundle/images.tar" | grep -c "Loaded image" || true)
[ "$loaded" -ge "$expected" ] || fail "docker load restauró $loaded imágenes (únicas esperadas: $expected)"

# 028 US1/US7: el entregable de la extensión viaja en el bundle y su sha256 coincide
# con el MANIFEST (si el cliente del test tiene brand.extension.json — 'example' la tiene).
ext_line=$(grep -E '^extension-.*\.zip ' "$WORK/bundle/MANIFEST" || true)
if [ -n "$ext_line" ]; then
    ext_name=$(printf '%s\n' "$ext_line" | awk '{print $1}')
    ext_sha=$(printf '%s\n' "$ext_line" | awk '{print $2}')
    [ -f "$WORK/bundle/$ext_name" ] || fail "el zip de la extensión ($ext_name) no viaja en el bundle"
    if command -v sha256sum >/dev/null 2>&1; then
        actual=$(sha256sum "$WORK/bundle/$ext_name" | awk '{print $1}')
    else
        actual=$(shasum -a 256 "$WORK/bundle/$ext_name" | awk '{print $1}')
    fi
    [ "$actual" = "$ext_sha" ] || fail "sha256 del zip de la extensión no coincide con el MANIFEST ($actual != $ext_sha)"
    ext_msg=" + extensión $ext_name (sha256 OK)"
else
    ext_msg=" (sin extensión para este cliente)"
fi

echo "✅ bundle air-gapped OK: $loaded/$expected imágenes únicas restauradas por docker load, perfil incluido$ext_msg"
