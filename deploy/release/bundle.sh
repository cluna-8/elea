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

# Manifiesto con digests: la verificación del install y el true-up de release.
{
  echo "# bundle $SLUG — $(date -u +%FT%TZ)"
  for img in "${IMAGES[@]}"; do
    echo "$img $(docker image inspect -f '{{.Id}}' "$img")"
  done
} > "$OUT/MANIFEST"

tar -C "$(dirname "$OUT")" -czf "$OUT.tar.gz" "$(basename "$OUT")"
echo "✅ bundle: $OUT.tar.gz (instalar: docker load -i images.tar; compose up con profile/)"
