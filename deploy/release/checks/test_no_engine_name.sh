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

# Lista COMPARTIDA con el check del sitio de docs (022 delta F2): una sola fuente.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
while IFS= read -r name; do
    case "$name" in ''|\#*) continue ;; esac
    # 1) Bundle de la UI. Allowlist de CONTRATO WIRE (no texto visible al usuario):
    #    - litellm_params: identificador del contrato admin-API↔motor (020)
    #    - presidio: valor del enum guardian_type (016) — la prosa visible fue
    #      neutralizada (022); renombrar el enum = cambio de contrato del módulo
    #      seguridad (issue abierto, owner módulo seguridad)
    leaks=$(docker run --rm "$IMG" sh -c \
        "grep -roih '${name}[a-z_]*' /srv 2>/dev/null | sort -u | grep -viE '^(litellm_params|presidio)$' || true")
    [ -z "$leaks" ] || fail "el motor se filtra en la UI buildeada: $leaks"
    # 2) Branding packs: cero menciones, sin excepción.
    leaks=$(grep -roih "$name" "$REPO_ROOT/deploy/branding" 2>/dev/null | sort -u || true)
    [ -z "$leaks" ] || fail "el motor aparece en el branding pack ($name)"
done < "$HERE/prohibited_names.txt"

# 3) La marca es runtime-config: el bundle referencia /branding/brand.json.
docker run --rm "$IMG" sh -c "grep -rq '/branding/brand.json' /srv/assets" \
    || fail "el bundle no consume /branding/brand.json (marca horneada, no config)"

echo "✅ marca blanca OK: motor no expuesto; marca como config en runtime"
