#!/usr/bin/env bash
# T006 (US1, SC-001): la imagen prod del backend es non-root, sin toolchain en la
# capa final, sin --reload, con healthcheck. Rojo si falta cualquiera.
set -euo pipefail
IMG="${BACKEND_IMG:-basa-backend:prod}"

fail() { echo "❌ $1"; exit 1; }
docker image inspect "$IMG" >/dev/null 2>&1 || fail "imagen $IMG no existe (buildear con make build-backend)"

user=$(docker image inspect -f '{{.Config.User}}' "$IMG")
[ -n "$user" ] && [ "$user" != "root" ] && [ "$user" != "0" ] || fail "corre como root (User='$user')"

hc=$(docker image inspect -f '{{.Config.Healthcheck}}' "$IMG")
[ "$hc" != "<nil>" ] || fail "sin HEALTHCHECK"

cmd=$(docker image inspect -f '{{.Config.Cmd}} {{.Config.Entrypoint}}' "$IMG")
echo "$cmd" | grep -q -- "--reload" && fail "el proceso usa --reload (imagen de dev)" || true

# Toolchain fuera de la capa final: ni gcc ni build-essential presentes.
if docker run --rm --entrypoint sh "$IMG" -c 'command -v gcc || dpkg -l build-essential 2>/dev/null | grep -q ^ii' >/dev/null 2>&1; then
    fail "la capa final contiene toolchain (gcc/build-essential)"
fi

# Código horneado: /app/src existe DENTRO de la imagen (sin bind-mount).
docker run --rm --entrypoint sh "$IMG" -c 'test -f /app/src/main.py' \
    || fail "el código no está horneado en la imagen (/app/src/main.py ausente)"

echo "✅ backend prod image OK ($IMG, user=$user)"
