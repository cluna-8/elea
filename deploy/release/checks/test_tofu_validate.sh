#!/usr/bin/env bash
# T021 (US4): fmt + validate del módulo OpenTofu completo. Corre con tofu local
# o via la imagen oficial (sin instalar nada). El plan/apply real necesita
# credenciales sandbox — ese paso es manual/CI con secrets (documentado).
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
CACHE="${TF_PLUGIN_CACHE_DIR:-/tmp/sentinel-tofu-cache}"
mkdir -p "$CACHE"

if command -v tofu >/dev/null 2>&1; then
    TOFU=(env TF_PLUGIN_CACHE_DIR="$CACHE" tofu -chdir="$REPO_ROOT/deploy/terraform")
else
    TOFU=(docker run --rm -v "$REPO_ROOT":/repo -v "$CACHE":/tfcache \
          -e TF_PLUGIN_CACHE_DIR=/tfcache -w /repo/deploy/terraform \
          ghcr.io/opentofu/opentofu:1.8)
fi

"${TOFU[@]}" fmt -check -recursive >/dev/null || { echo "❌ tofu fmt (correr: tofu fmt -recursive)"; exit 1; }
"${TOFU[@]}" init -backend=false -input=false >/dev/null
"${TOFU[@]}" validate || { echo "❌ tofu validate"; exit 1; }
echo "✅ módulo OpenTofu: fmt + validate verdes"
