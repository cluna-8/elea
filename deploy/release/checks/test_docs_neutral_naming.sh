#!/usr/bin/env bash
# 022 T022 (US3, FR-013/SC-004): el sitio publicado NO expone el motor — grep de la
# lista COMPARTIDA de nombres prohibidos (prohibited_names.txt, la misma del check de
# la UI) sobre TODO el HTML/CSS/JS de la imagen. Sin allowlist: en la doc no hay
# contrato wire que justifique una mención.
set -euo pipefail
IMG="${DOCS_IMG:-basa-docs:prod}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

fail() { echo "❌ $1"; exit 1; }
docker image inspect "$IMG" >/dev/null 2>&1 || fail "imagen $IMG no existe (buildear con make build-docs)"

while IFS= read -r name; do
    case "$name" in ''|\#*) continue ;; esac
    leaks=$(docker run --rm --entrypoint sh "$IMG" -c \
        "grep -roil '$name' /usr/share/nginx/html 2>/dev/null | head -5" || true)
    [ -z "$leaks" ] || fail "'$name' (motor/internals) filtrado en el sitio publicado:
$leaks"
done < "$HERE/prohibited_names.txt"

echo "✅ naming neutro OK: 0 menciones de motor/internals en el sitio publicado"
