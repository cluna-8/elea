#!/usr/bin/env bash
# 022 T012+T013 (US2, SC-003): las 9 secciones publican contenido REAL (no placeholders)
# y las páginas migradas del corpus conservan la leyenda de estado 🟢/🟡/🔵 (honestidad SDD).
# Corre contra la IMAGEN (el artefacto publicado), no contra el fuente.
set -euo pipefail
IMG="${DOCS_IMG:-basa-docs:prod}"

fail() { echo "❌ $1"; exit 1; }
docker image inspect "$IMG" >/dev/null 2>&1 || fail "imagen $IMG no existe (buildear con make build-docs)"

cname="basa-docs-content-check-$$"
trap 'docker rm -f "$cname" >/dev/null 2>&1 || true' EXIT
docker run -d --name "$cname" --network none "$IMG" >/dev/null
sleep 1

# T012: cada sección con contenido no-placeholder (peso mínimo del HTML + sin marcador de stub).
sections=(overview install-deploy white-label administration integrations api-reference \
          compliance operations release-notes)
for s in "${sections[@]}"; do
    html=$(docker exec "$cname" cat "/usr/share/nginx/html/latest/$s/index.html" 2>/dev/null) \
        || fail "sección $s ausente del sitio publicado"
    echo "$html" | grep -q "en construcción" && fail "sección $s sigue siendo un stub ('en construcción')"
    [ "$(printf '%s' "$html" | wc -c)" -ge 8000 ] \
        || fail "sección $s sospechosamente vacía ($(printf '%s' "$html" | wc -c) bytes de HTML)"
done

# T013: la leyenda de estado sobrevivió la migración (en el HTML publicado).
for marker in 🟢 🟡 🔵; do
    docker exec "$cname" grep -rq "$marker" /usr/share/nginx/html \
        || fail "la leyenda de estado se perdió en la migración (falta $marker en el sitio)"
done

echo "✅ contenido OK: 9 secciones reales publicadas; leyenda 🟢/🟡/🔵 preservada"
