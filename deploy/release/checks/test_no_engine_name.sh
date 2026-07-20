#!/usr/bin/env bash
# T012/T015 (US2, FR-007): 0 menciones del motor upstream expuestas al usuario
# en los artefactos de marca blanca, y la marca es runtime-config (no baked).
#
# Allowlist documentada: `litellm_params` — identificador del CONTRATO WIRE
# entre el frontend admin y la API del backend (que a su vez proxya la API de
# gestión del motor). No es texto visible al usuario; renombrarlo rompería el
# contrato sin ganancia de marca blanca. Cualquier OTRA aparición es fuga.
set -euo pipefail
IMG="${FRONTEND_IMG:-basa-frontend:prod}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

fail() { echo "❌ $1"; exit 1; }
docker image inspect "$IMG" >/dev/null 2>&1 || fail "imagen $IMG no existe (buildear primero)"

# 1) Bundle de la UI: grep ci de 'litellm' fuera del identificador wire permitido.
leaks=$(docker run --rm "$IMG" sh -c \
    "grep -roih 'litellm[a-z_]*' /srv 2>/dev/null | sort -u | grep -viE '^litellm_params$' || true")
[ -z "$leaks" ] || fail "el motor se filtra en la UI buildeada: $leaks"

# 2) Branding packs: cero menciones, sin excepción.
leaks=$(grep -roih "litellm" "$REPO_ROOT/deploy/branding" 2>/dev/null | sort -u || true)
[ -z "$leaks" ] || fail "el motor aparece en el branding pack"

# 3) La marca es runtime-config: el bundle referencia /branding/brand.json.
docker run --rm "$IMG" sh -c "grep -rq '/branding/brand.json' /srv/assets" \
    || fail "el bundle no consume /branding/brand.json (marca horneada, no config)"

echo "✅ marca blanca OK: motor no expuesto; marca como config en runtime"
