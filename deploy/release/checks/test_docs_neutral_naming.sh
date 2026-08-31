#!/usr/bin/env bash
# 022 T022 (US3, FR-013/SC-004): el sitio publicado NO expone el motor — grep de la
# lista COMPARTIDA de nombres prohibidos (prohibited_names.txt, la misma del check de
# la UI) sobre TODO el sitio publicado de la imagen.
set -euo pipefail
IMG="${DOCS_IMG:-sentinel-docs:prod}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

fail() { echo "❌ $1"; exit 1; }
docker image inspect "$IMG" >/dev/null 2>&1 || fail "imagen $IMG no existe (buildear con make build-docs)"

# Allowlist de CONTRATO WIRE (mismo criterio que el check de la UI):
#   - litellm_params: identificador del contrato admin-API↔motor (campo del OpenAPI)
#   - litellm_master_key: env var REAL de config del deploy (issue #24: rename de fondo)
while IFS= read -r name; do
    case "$name" in ''|\#*) continue ;; esac
    leaks=$(docker run --rm --entrypoint sh "$IMG" -c \
        "grep -roih '${name}[a-z_]*' /usr/share/nginx/html 2>/dev/null | sort -u" \
        | grep -viE '^(litellm_params|litellm_master_key)$' || true)
    [ -z "$leaks" ] || fail "'$name' (motor/internals) filtrado en el sitio publicado: $leaks"
done < "$HERE/prohibited_names.txt"

echo "✅ naming neutro OK: 0 menciones de motor/internals en el sitio publicado"
