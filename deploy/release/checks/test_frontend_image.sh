#!/usr/bin/env bash
# T007 (US1, SC-001): la imagen prod del frontend sirve ESTÁTICOS (vite build),
# no un dev server, y corre non-root.
set -euo pipefail
IMG="${FRONTEND_IMG:-sentinel-frontend:prod}"

fail() { echo "❌ $1"; exit 1; }
docker image inspect "$IMG" >/dev/null 2>&1 || fail "imagen $IMG no existe (buildear con make build-frontend)"

user=$(docker image inspect -f '{{.Config.User}}' "$IMG")
[ -n "$user" ] && [ "$user" != "root" ] && [ "$user" != "0" ] || fail "corre como root (User='$user')"

# Sin toolchain de node en la capa final: el build quedó en la etapa builder.
docker run --rm "$IMG" sh -c 'command -v node' >/dev/null 2>&1 \
    && fail "la capa final contiene node (el vite build debe quedar en la etapa builder)" || true

# Estáticos horneados (index de vite build presente).
docker run --rm "$IMG" sh -c 'test -f /srv/index.html' \
    || fail "sin estáticos horneados (/srv/index.html ausente)"

# El proceso es el file server (caddy), no npm/vite.
cmd=$(docker image inspect -f '{{.Config.Cmd}} {{.Config.Entrypoint}}' "$IMG")
echo "$cmd" | grep -qiE "npm|vite" && fail "el proceso es un dev server ($cmd)" || true

echo "✅ frontend prod image OK ($IMG, user=$user)"
