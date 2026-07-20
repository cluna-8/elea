#!/usr/bin/env bash
# 022 T006 (US1, SC-001/SC-002): la imagen del sitio de docs es estática, non-root,
# y funciona COMPLETA con la red bloqueada (0 egress en runtime).
set -euo pipefail
IMG="${DOCS_IMG:-basa-docs:prod}"

fail() { echo "❌ $1"; exit 1; }
docker image inspect "$IMG" >/dev/null 2>&1 || fail "imagen $IMG no existe (buildear con make build-docs)"

user=$(docker image inspect -f '{{.Config.User}}' "$IMG")
[ -n "$user" ] && [ "$user" != "root" ] && [ "$user" != "0" ] || fail "corre como root (User='$user')"

# Sin toolchain en la capa final: el build MkDocs quedó en la etapa builder.
docker run --rm --entrypoint sh "$IMG" -c 'command -v python3 || command -v mkdocs' >/dev/null 2>&1 \
    && fail "la capa final contiene la toolchain de build (python/mkdocs)" || true

# ── 0 egress runtime: contenedor con --network none; se navega DESDE ADENTRO (loopback). ──
cname="basa-docs-airgap-check-$$"
trap 'docker rm -f "$cname" >/dev/null 2>&1 || true' EXIT
docker run -d --name "$cname" --network none "$IMG" >/dev/null
sleep 2

# Todas las secciones + el índice de búsqueda cargan sin red.
sections=(index.html versions.json latest/index.html latest/overview/index.html \
          latest/install-deploy/index.html latest/white-label/index.html \
          latest/administration/index.html latest/integrations/index.html \
          latest/api-reference/index.html latest/compliance/index.html \
          latest/operations/index.html latest/release-notes/index.html \
          latest/en/index.html latest/search/search_index.json)
for p in "${sections[@]}"; do
    docker exec "$cname" wget -qO /dev/null "http://127.0.0.1:8080/$p" \
        || fail "con la red bloqueada, /$p no carga (¿sección ausente o nginx roto?)"
done

# ── Auditoría estática: NINGUNA referencia load-bearing a un host externo en lo publicado.
#    (src=/href= en HTML y url()/@import en CSS; los comentarios/licencias del JS no cargan nada.)
externals=$(docker exec "$cname" sh -c \
    'grep -rEoh "(src|href)=\"https?://[^\"]+\"" /usr/share/nginx/html --include="*.html" 2>/dev/null; \
     grep -rEoh "url\(https?://[^)]+\)|@import \"https?://[^\"]+\"" /usr/share/nginx/html --include="*.css" 2>/dev/null' \
    | grep -vE '127\.0\.0\.1|localhost' | sort -u || true)
[ -z "$externals" ] || fail "referencias externas load-bearing en el HTML/CSS publicado:
$externals"

echo "✅ docs prod image OK ($IMG, user=$user): ${#sections[@]} rutas sirven con --network none, 0 refs externas"
