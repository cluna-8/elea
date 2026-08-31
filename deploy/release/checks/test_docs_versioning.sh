#!/usr/bin/env bash
# 022 T035 (US6, FR-019/FR-020, SC-007): el sitio publica ≥2 versiones con mike
# (selector via versions.json), y la i18n ES/EN sirve la variante correcta con
# fallback explícito al primario (jamás 404) — todo con la red bloqueada.
set -euo pipefail
IMG="${DOCS_IMG:-sentinel-docs:prod}"

fail() { echo "❌ $1"; exit 1; }
docker image inspect "$IMG" >/dev/null 2>&1 || fail "imagen $IMG no existe (buildear con make build-docs)"

cname="sentinel-docs-ver-check-$$"
trap 'docker rm -f "$cname" >/dev/null 2>&1 || true' EXIT
docker run -d --name "$cname" --network none "$IMG" >/dev/null

# Esperar readiness explícito evita depender de un tiempo fijo de arranque
# bajo condiciones variables del runner (issue #145): reintenta contra un
# endpoint liviano ya usado por este check, con límite acotado — si nginx
# nunca responde, falla con diagnóstico claro en vez de esperar indefinidamente.
ready=0
intentos=0
while [ "$intentos" -lt 20 ]; do
    docker exec "$cname" wget -qO /dev/null "http://127.0.0.1:8080/versions.json" 2>/dev/null \
        && { ready=1; break; }
    intentos=$((intentos + 1))
    sleep 0.5
done
[ "$ready" = 1 ] || fail "el contenedor de docs no respondió tras 10s de espera (¿nginx no arrancó?)"

w() { docker exec "$cname" wget -qO- "http://127.0.0.1:8080/$1"; }

# FR-019: ≥2 versiones publicadas + alias latest en versions.json (la fuente del selector).
vj=$(w versions.json) || fail "versions.json ausente"
echo "$vj" | grep -q '"1.0"' || fail "la versión 1.0 no está publicada"
echo "$vj" | grep -q '"dev"' || fail "la versión dev no está publicada"
echo "$vj" | grep -q '"latest"' || fail "el alias latest no existe"

# Cada versión sirve su propia doc; la raíz redirige a latest.
w 1.0/index.html >/dev/null || fail "/1.0/ no sirve"
w dev/index.html >/dev/null || fail "/dev/ no sirve"
w index.html | grep -qi 'latest' || fail "la raíz no redirige a latest"

# FR-020: EN sirve su variante; una página SIN traducción degrada al ES (no 404).
w latest/en/index.html | grep -q 'TODAY' || fail "la landing EN no sirve contenido en inglés"
w latest/en/administration/index.html | grep -qi 'multi-tenant' \
    || fail "página sin traducción EN no degrada al contenido ES (¿404?)"

echo "✅ versionado + i18n OK: 2 versiones + latest, selector con versions.json, EN con fallback ES"
