#!/usr/bin/env bash
# 022 T026+T027 (US4, FR-014/FR-015, SC-005): la búsqueda resuelve contra un índice
# LOCAL con la red bloqueada, y NO existe integración con ningún buscador SaaS
# (Algolia DocSearch prohibido: rompería el air-gap).
set -euo pipefail
IMG="${DOCS_IMG:-basa-docs:prod}"
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"

fail() { echo "❌ $1"; exit 1; }
docker image inspect "$IMG" >/dev/null 2>&1 || fail "imagen $IMG no existe (buildear con make build-docs)"

cname="basa-docs-search-check-$$"
trap 'docker rm -f "$cname" >/dev/null 2>&1 || true' EXIT
docker run -d --name "$cname" --network none "$IMG" >/dev/null
sleep 1

# T026: el índice se sirve LOCAL con la red bloqueada y contiene contenido real indexado.
idx=$(docker exec "$cname" wget -qO- http://127.0.0.1:8080/search/search_index.json) \
    || fail "search_index.json no se sirve con la red bloqueada"
for term in retenci air-gap licencia; do
    echo "$idx" | grep -qi "$term" || fail "el índice de búsqueda no contiene '$term' (¿índice vacío?)"
done

# El worker/JS de búsqueda vive DENTRO de la imagen (lunr precomputado, sin backend).
docker exec "$cname" sh -c 'ls /usr/share/nginx/html/assets/javascripts/workers/search.*.min.js' >/dev/null \
    || fail "el worker de búsqueda no está embebido en la imagen"

# T027: cero integración SaaS de búsqueda (config del sitio + sitio publicado).
# (grep de busybox dentro del contenedor: sin --include; -r sobre todo el site.)
for token in algolia docsearch typesense; do
    grep -rqi "$token" "$REPO_ROOT/docs/mkdocs"*.yml && fail "buscador SaaS '$token' en la config del sitio" || true
    if docker exec "$cname" grep -rqi "$token" /usr/share/nginx/html; then
        fail "buscador SaaS '$token' en el sitio publicado"
    fi
done

echo "✅ búsqueda offline OK: índice local con contenido real, worker embebido, 0 SaaS"
