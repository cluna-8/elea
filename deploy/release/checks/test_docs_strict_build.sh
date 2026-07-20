#!/usr/bin/env bash
# 022 T007 (US1, FR-003): el build es ESTRICTO — un link interno roto DEBE romper el build
# (fixture negativo). El caso positivo lo cubre el build normal de la imagen (make build-docs).
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"

fail() { echo "❌ $1"; exit 1; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cp -R "$REPO_ROOT/docs/." "$tmp/docs-broken/"
rm -rf "$tmp/docs-broken/site" "$tmp/docs-broken/.cache"

# Fixture negativo: página con un link interno roto.
cat > "$tmp/docs-broken/docs/overview/broken-fixture.md" <<'EOF'
# Fixture

[link roto](../no-existe/nada.md)
EOF

if docker build -q -f "$REPO_ROOT/docs/Dockerfile" "$tmp/docs-broken" >/dev/null 2>&1; then
    fail "el build con un link interno roto NO falló (--strict no está haciendo su trabajo)"
fi

echo "✅ build estricto OK: el fixture con link roto rompe el build (como debe)"
