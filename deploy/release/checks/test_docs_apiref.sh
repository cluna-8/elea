#!/usr/bin/env bash
# 022 T030+T031 (US5, FR-016/FR-017/FR-018, SC-006):
#  (a) DERIVA: el openapi.json y configuration.md commiteados son EXACTAMENTE lo que
#      generan sus fuentes (backend / .env.example) — si el backend cambió y nadie
#      regeneró, este check pone el release en rojo (single-source de verdad).
#  (b) ANTI-FUGA: ninguna página del sitio se deriva de las specs internas de Spec Kit
#      ni de los internos de docs/ (COORDINATION, retros).
set -euo pipefail
IMG="${DOCS_IMG:-basa-docs:prod}"
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"

fail() { echo "❌ $1"; exit 1; }

# (a) deriva del API reference
tmp=$(mktemp -d); trap 'rm -rf "$tmp"; docker rm -f basa-docs-apiref-check >/dev/null 2>&1 || true' EXIT
(cd "$REPO_ROOT" && docker compose run --rm --no-deps -e BRAND_NAME="AI Gateway" backend python scripts/export_openapi.py 2>/dev/null) > "$tmp/openapi.json" \
    || fail "no pude exportar el OpenAPI del backend"
diff -q "$tmp/openapi.json" "$REPO_ROOT/docs/docs/api-reference/openapi.json" >/dev/null \
    || fail "openapi.json DESACTUALIZADO vs el backend — regenerar: make -C deploy docs-refs"

# (a2) deriva del config reference
cp "$REPO_ROOT/docs/docs/api-reference/configuration.md" "$tmp/configuration.committed.md"
(cd "$REPO_ROOT" && python3 docs/gen_config_reference.py 2>/dev/null)
if ! diff -q "$REPO_ROOT/docs/docs/api-reference/configuration.md" "$tmp/configuration.committed.md" >/dev/null; then
    cp "$tmp/configuration.committed.md" "$REPO_ROOT/docs/docs/api-reference/configuration.md"
    fail "configuration.md DESACTUALIZADO vs .env.example — regenerar: make -C deploy docs-refs"
fi

# (b) anti-fuga de contexto interno en el sitio publicado
docker image inspect "$IMG" >/dev/null 2>&1 || fail "imagen $IMG no existe (buildear con make build-docs)"
docker create --name basa-docs-apiref-check "$IMG" >/dev/null
docker cp -q basa-docs-apiref-check:/usr/share/nginx/html "$tmp/site"
for marker in 'speckit' 'Spec Kit' 'specs/0' 'COORDINATION-019' 'retros/'; do
    hits=$(grep -rl "$marker" "$tmp/site" 2>/dev/null | head -3 || true)
    [ -z "$hits" ] || fail "contexto interno filtrado al sitio ('$marker'):
$hits"
done

echo "✅ API/config reference single-source al día; 0 fuga de contexto interno"
