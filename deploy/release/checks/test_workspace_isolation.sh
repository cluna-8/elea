#!/usr/bin/env bash
# T022 (US4, Principio III): dos clientes = dos workspaces con state AISLADO.
# Copia el módulo a tmp con backend local (override estándar) y verifica que
# cada workspace escribe su propio state dir — sin colisión.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
cp -R "$REPO_ROOT/deploy/terraform/." "$WORK/"
rm -rf "$WORK/.terraform" "$WORK/envs"
printf 'terraform {\n  backend "local" {}\n}\n' > "$WORK/backend_override.tf"

if command -v tofu >/dev/null 2>&1; then
    TOFU=(tofu -chdir="$WORK")
else
    TOFU=(docker run --rm -v "$WORK":/work -w /work ghcr.io/opentofu/opentofu:1.8)
fi

"${TOFU[@]}" init -backend=false -input=false >/dev/null 2>&1 || true
"${TOFU[@]}" init -input=false >/dev/null
"${TOFU[@]}" workspace new cliente-a >/dev/null
"${TOFU[@]}" workspace new cliente-b >/dev/null
[ -d "$WORK/terraform.tfstate.d/cliente-a" ] || { echo "❌ workspace cliente-a sin state dir propio"; exit 1; }
[ -d "$WORK/terraform.tfstate.d/cliente-b" ] || { echo "❌ workspace cliente-b sin state dir propio"; exit 1; }
echo "✅ aislamiento por cliente OK: un workspace = un state propio (cliente-a / cliente-b)"
