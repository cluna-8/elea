#!/usr/bin/env bash
# Bundle AIR-GAPPED v1 (spec 020 US6, FR-028): tarball autocontenido con TODAS
# las imágenes pinneadas + compose prod + perfil renderizado + checks. Se
# instala con docker load en un host SIN registry (caso Elea / on-prem).
#
# Uso: BACKEND_IMAGE=... FRONTEND_IMAGE=... LITELLM_IMAGE=... DOCS_IMAGE=... \
#      NLP_ANALYZER_IMAGE=... \
#      CADDY_IMAGE=caddy:2-alpine POSTGRES_IMAGE=postgres:16 REDIS_IMAGE=redis:7-alpine \
#      deploy/release/bundle.sh <client-slug> [outdir]
set -euo pipefail
SLUG="${1:?uso: bundle.sh <client-slug> [outdir]}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${2:-$REPO_ROOT/deploy/release/bundle-$SLUG}"
mkdir -p "$OUT"

# TODAS las imágenes del release (edge case: una imagen fuera del tarball =
# pull en runtime = install roto sin egress). Incluye las selfhosted on-prem.
IMAGES=(
  "${BACKEND_IMAGE:?}" "${FRONTEND_IMAGE:?}" "${LITELLM_IMAGE:?}" "${DOCS_IMAGE:?sitio de docs por marca (022)}"
  "${NLP_ANALYZER_IMAGE:?analizador NLP (016) — sin él el motor enmascara con regex}"
  "${CADDY_IMAGE:-caddy:2-alpine}" "${POSTGRES_IMAGE:-postgres:16}" "${REDIS_IMAGE:-redis:7-alpine}"
)

echo "── docker save (${#IMAGES[@]} imágenes)"
docker save "${IMAGES[@]}" -o "$OUT/images.tar"

"$REPO_ROOT/deploy/release/render_profile.sh" "$SLUG"
cp "$REPO_ROOT/deploy/docker/compose.prod.yml" "$OUT/"
cp -R "$REPO_ROOT/deploy/clients/$SLUG/rendered" "$OUT/profile"
cp -R "$REPO_ROOT/deploy/release/checks" "$OUT/checks"

# Entregable white-label de la EXTENSIÓN (028 US1/US7): si el cliente tiene brand-pack,
# lo renderizamos y viaja en el bundle (edge case simétrico al de las imágenes: un
# artefacto fuera del tarball = fetch en runtime = install roto sin egress).
EXT_BRAND_JSON="$REPO_ROOT/deploy/clients/$SLUG/brand.extension.json"
EXT_ZIP_NAME="extension-$SLUG.zip"
EXT_INCLUDED=0
if [ -f "$EXT_BRAND_JSON" ]; then
  "$REPO_ROOT/deploy/release/render_extension_brand.sh" "$SLUG" "$EXT_BRAND_JSON" >/dev/null
  cp "$REPO_ROOT/deploy/clients/$SLUG/rendered/$EXT_ZIP_NAME" "$OUT/$EXT_ZIP_NAME"
  EXT_INCLUDED=1
  echo "── extensión white-label incluida: $EXT_ZIP_NAME"
else
  echo "── $SLUG sin brand.extension.json → bundle sin extensión de navegador"
fi

# sha256 portable (Linux: sha256sum; macOS: shasum -a 256).
sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}';
  else shasum -a 256 "$1" | awk '{print $1}'; fi
}

# Manifiesto: imágenes con digest (docker load) + artefactos con sha256 (verificación
# del install air-gapped). Las líneas de imagen llevan $2 = "sha256:<id>" (formato de
# docker); las de artefacto un sha256 pelado → el check las distingue por ese prefijo.
{
  echo "# bundle $SLUG — $(date -u +%FT%TZ)"
  echo "# images (docker load):"
  for img in "${IMAGES[@]}"; do
    echo "$img $(docker image inspect -f '{{.Id}}' "$img")"
  done
  if [ "$EXT_INCLUDED" -eq 1 ]; then
    echo "# artifacts (sha256):"
    echo "$EXT_ZIP_NAME $(sha256 "$OUT/$EXT_ZIP_NAME")"
  fi
} > "$OUT/MANIFEST"

tar -C "$(dirname "$OUT")" -czf "$OUT.tar.gz" "$(basename "$OUT")"
echo "✅ bundle: $OUT.tar.gz (instalar: docker load -i images.tar; compose up con profile/)"
