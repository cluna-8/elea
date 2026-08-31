#!/usr/bin/env bash
# T030/T033 (US5, FR-025): CERO secretos default del compose de dev en CUALQUIER
# artefacto del camino de producción. La lista crece con cada default que se
# retire; encontrar uno acá = release bloqueado.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

DEFAULTS=(
  "sentinelsecurepass123"
  "sentinel_master_key_9999"
  "test-jwt-secret"
)
# Camino PROD: todo deploy/ (Dockerfiles, compose prod, cloud-init, perfiles,
# módulo tofu, branding) — el compose de DEV (raíz) queda explícitamente fuera.
PROD_PATHS=("$REPO_ROOT/deploy")

fail=0
for secret in "${DEFAULTS[@]}"; do
    hits=$(grep -rl "$secret" "${PROD_PATHS[@]}" 2>/dev/null | grep -v "/rendered/" | grep -v "test_no_default_secrets.sh" || true)
    if [ -n "$hits" ]; then
        echo "❌ default '$secret' en el camino prod:"; echo "$hits"; fail=1
    fi
done
# Patrón ${VAR:-default} sobre variables SENSIBLES en artefactos prod:
hits=$(grep -rEn '\$\{(POSTGRES_PASSWORD|SENTINEL_ENGINE_MASTER_KEY|JWT_SECRET_KEY|FERNET_SECRET_KEY):-' \
    "$REPO_ROOT/deploy" 2>/dev/null || true)
if [ -n "$hits" ]; then
    echo "❌ fallback default sobre secreto en camino prod:"; echo "$hits"; fail=1
fi
[ "$fail" = 0 ] && echo "✅ cero secretos default en el camino de producción"
exit $fail
