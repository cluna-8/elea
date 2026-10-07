#!/usr/bin/env bash
# Prepara lo que el motor monta en desarrollo con sentinel/docker/compose.dev.yml (spec 057 T021):
#   .dev/extensions/  litellm/extensions/*.py (base) + sentinel/engine/redirect_*.py (extensión)
#   .dev/config.yaml  litellm/config.yaml + sentinel/engine/profile-fragment.yaml fusionado AL FINAL
#                     (el guard queda después del guardrail de la base; contrato S11)
# Siempre parte de cero: repetirlo da el mismo resultado y no arrastra archivos de versiones viejas.
# No usa Docker. Sale con error si el fusionador rechaza el fragmento (nombres duplicados).
#
# Uso: sentinel/docker/prepare-dev.sh      (SENTINEL_DEV_DIR cambia el destino; por defecto sentinel/docker/.dev)
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${SENTINEL_DEV_DIR:-$REPO_ROOT/sentinel/docker/.dev}"

rm -rf "$OUT"
mkdir -p "$OUT/extensions"
cp "$REPO_ROOT"/litellm/extensions/*.py "$OUT/extensions/"
cp "$REPO_ROOT"/sentinel/engine/redirect_*.py "$OUT/extensions/"
cp "$REPO_ROOT/litellm/config.yaml" "$OUT/config.yaml"
python3 "$REPO_ROOT/deploy/release/fragment_merge.py" "$OUT/config.yaml" \
    "$REPO_ROOT/sentinel/engine/profile-fragment.yaml" \
    || { rm -rf "$OUT"; echo "❌ no se pudo fusionar el fragmento de perfil en el config del motor"; exit 1; }
echo "✅ $OUT listo (extensiones del motor + config fusionado)"
