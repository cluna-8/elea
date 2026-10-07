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

# T093 (057, QA M10): `MASKING_NONCE_KEY` (clave del servidor de los marcadores estables por conversación):
# (a) jamás con un valor literal de ejemplo en un artefacto versionado (vacía, `<generar>` o una referencia `${…}`
#     sin valor por defecto; el patrón ${MASKING_NONCE_KEY:-valor} también es un default sobre un secreto);
# (b) un artefacto que ACTIVA la extensión (`GATEWAY_PLUGINS=<algo>`) la tiene que declarar, y no vacía: con la
#     extensión activa sin clave los marcadores salen aleatorios y la caché del proveedor no rinde;
# (c) `gen_secrets.sh` la genera: ≥ 32 caracteres hexadecimales y distinta en cada instalación.
NONCE_PATHS=("$REPO_ROOT/deploy" "$REPO_ROOT/sentinel/docker" "$REPO_ROOT/sentinel/extensions.env.example"
             "$REPO_ROOT/.env.example" "$REPO_ROOT/docker-compose.yml")
ejemplos=$(grep -rEn '^[[:space:]]*(-[[:space:]]*)?#?[[:space:]]*MASKING_NONCE_KEY[[:space:]]*[:=][[:space:]]*["'"'"']?[^[:space:]"'"'"'$<#]' \
    "${NONCE_PATHS[@]}" 2>/dev/null | grep -v "/rendered/" | grep -v "test_no_default_secrets.sh" || true)
if [ -n "$ejemplos" ]; then
    echo "❌ MASKING_NONCE_KEY con un valor literal en un artefacto versionado:"; echo "$ejemplos"; fail=1
fi
defaults=$(grep -rEn '\$\{MASKING_NONCE_KEY:-[^}]' "${NONCE_PATHS[@]}" 2>/dev/null | grep -v "test_no_default_secrets.sh" || true)
if [ -n "$defaults" ]; then
    echo "❌ MASKING_NONCE_KEY con un valor por defecto (\${MASKING_NONCE_KEY:-…}):"; echo "$defaults"; fail=1
fi
activan=$(grep -rlE '^[[:space:]]*GATEWAY_PLUGINS[[:space:]]*=[[:space:]]*[^[:space:]#]' \
    "$REPO_ROOT/deploy" "$REPO_ROOT/sentinel/docker" "$REPO_ROOT/sentinel/extensions.env.example" 2>/dev/null \
    | grep -v "/rendered/" | grep -v "test_no_default_secrets.sh" || true)
for f in $activan; do
    if ! grep -qE '^[[:space:]]*MASKING_NONCE_KEY[[:space:]]*=[[:space:]]*[^[:space:]#]' "$f"; then
        echo "❌ $f activa la extensión (GATEWAY_PLUGINS) y no declara MASKING_NONCE_KEY (ni vacía ni ausente)"; fail=1
    fi
done
if [ -x "$REPO_ROOT/deploy/release/gen_secrets.sh" ] && [ -d "$REPO_ROOT/deploy/clients/example" ]; then
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    "$REPO_ROOT/deploy/release/gen_secrets.sh" example "$tmp/a.env" >/dev/null 2>&1 || true
    "$REPO_ROOT/deploy/release/gen_secrets.sh" example "$tmp/b.env" >/dev/null 2>&1 || true
    ka=$(grep -E '^MASKING_NONCE_KEY=' "$tmp/a.env" 2>/dev/null | cut -d= -f2- || true)
    kb=$(grep -E '^MASKING_NONCE_KEY=' "$tmp/b.env" 2>/dev/null | cut -d= -f2- || true)
    if ! [[ "$ka" =~ ^[0-9a-f]{32,}$ ]]; then
        echo "❌ gen_secrets.sh no genera MASKING_NONCE_KEY (≥ 32 caracteres hexadecimales)"; fail=1
    elif [ "$ka" = "$kb" ]; then
        echo "❌ gen_secrets.sh repite MASKING_NONCE_KEY entre dos instalaciones"; fail=1
    fi
fi

[ "$fail" = 0 ] && echo "✅ cero secretos default en el camino de producción"
exit $fail
