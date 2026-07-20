#!/usr/bin/env bash
# 022 T021 (US3, SC-004): dos marcas del sitio difieren SOLO en tokens de marca.
# Construye la marca base y la marca ejemplo (aegis, derivada del brand-pack de la 020),
# extrae ambos sites y verifica: mismo set de páginas, y tras normalizar los tokens de
# marca (nombres) y excluir los ASSETS de marca (css/logo), 0 diferencias => never fork.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"

fail() { echo "❌ $1"; exit 1; }

BRAND_A_NAME="Basa Secure AI Gateway"
BRAND_B_NAME="Aegis AI Firewall"

work=$(mktemp -d)
trap 'rm -rf "$work"; docker rm -f docs-wl-a docs-wl-b >/dev/null 2>&1 || true' EXIT

echo "── build marca base + marca aegis"
docker build -q -f "$REPO_ROOT/docs/Dockerfile" -t basa-docs:wl-base "$REPO_ROOT/docs" >/dev/null \
    || fail "build marca base falló"
docker build -q -f "$REPO_ROOT/docs/Dockerfile" --build-arg BRAND=aegis -t basa-docs:wl-aegis "$REPO_ROOT/docs" >/dev/null \
    || fail "build marca aegis falló (¿falta docs/mkdocs.aegis.yml / docs/brand/aegis?)"

docker create --name docs-wl-a basa-docs:wl-base >/dev/null
docker create --name docs-wl-b basa-docs:wl-aegis >/dev/null
docker cp -q docs-wl-a:/usr/share/nginx/html "$work/a"
docker cp -q docs-wl-b:/usr/share/nginx/html "$work/b"

# La marca se aplica donde el site_name manda: el <title> de las páginas.
# (El contenido PUEDE mencionar "Aegis" como ejemplo en prosa — eso no es marca aplicada.)
grep -q "<title>.*$BRAND_B_NAME" "$work/b/index.html" || fail "el site_name de aegis no se aplicó (<title>)"
grep -q "<title>.*$BRAND_B_NAME" "$work/a/index.html" && fail "el sitio base lleva el título de aegis" || true
grep -q "<title>.*$BRAND_A_NAME" "$work/a/index.html" || fail "el sitio base perdió su site_name"

# Normalizar AMBOS tokens de marca en AMBOS árboles (consistente) y excluir los
# assets de marca (css/logo: SON la config del brand-pack).
export BRAND_A_NAME BRAND_B_NAME
for d in a b; do
    rm -rf "$work/$d/assets/brand"
    find "$work/$d" -type f \( -name '*.html' -o -name '*.json' -o -name '*.xml' \) -exec perl -pi -e '
        s/\Q$ENV{BRAND_A_NAME}\E/__BRAND__/g;
        s/\Q$ENV{BRAND_B_NAME}\E/__BRAND__/g;
        s/<meta name="description" content="[^"]*">/<meta name="description" content="__TAGLINE__">/g;
    ' {} +
done

diffs=$(diff -rq "$work/a" "$work/b" 2>&1 || true)
[ -z "$diffs" ] || fail "las marcas difieren en CONTENIDO (debería ser solo tokens/assets de marca):
$(echo "$diffs" | head -10)"

echo "✅ white-label OK: 2 marcas comparten contenido idéntico; difieren solo en tokens/assets de marca"
