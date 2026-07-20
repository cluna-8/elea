#!/usr/bin/env bash
# T031 (US5, FR-019): los secretos generados van marcados sensitive en TODOS
# los outputs del módulo, y ningún artefacto prod los loguea/echoa en claro.
# (La otra mitad del contrato — remote state CIFRADO — es config del backend
# s3 del distribuidor: encrypt=true, documentada en terraform/README.md.)
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TF="$REPO_ROOT/deploy/terraform"
fail=0

# Todo output cuyo nombre huela a secreto DEBE ser sensitive.
while IFS=: read -r file line _; do
    block=$(sed -n "${line},$((line+5))p" "$file")
    echo "$block" | grep -q "sensitive[[:space:]]*=[[:space:]]*true" || {
        echo "❌ output sin sensitive en $file:$line"; fail=1; }
done < <(grep -rn 'output "\(.*password.*\|.*secret.*\|.*key.*\|admin_bootstrap\)"' "$TF" --include="*.tf" | grep -v "public_key")

# cloud-init: los secretos SOLO en secrets.env (0600), jamás en runcmd/echo.
grep -E "echo .*(PASSWORD|SECRET|MASTER_KEY)" "$TF/modules/compute/templates/cloud-init.yaml.tpl" \
    && { echo "❌ secreto echoado en cloud-init"; fail=1; } || true
grep -q 'permissions: "0600"' "$TF/modules/compute/templates/cloud-init.yaml.tpl" \
    || { echo "❌ secrets.env sin 0600"; fail=1; }

[ "$fail" = 0 ] && echo "✅ secretos sensitive en outputs; nada en claro fuera de secrets.env (0600)"
exit $fail
