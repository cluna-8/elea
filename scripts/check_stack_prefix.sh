#!/usr/bin/env bash
# issue #223 / PR #230: fija el render de container_name del compose de dev.
#
# Por qué no pytest: el contenedor de la suite no monta la raíz, no ve docker-compose.yml.
# Por qué `docker compose config` y no grep del YAML: hay que clavar la interpolación
# real (${STACK_PREFIX:-basa}), no el texto fuente.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="$REPO_ROOT/docker-compose.yml"
SERVICIOS=(backend db frontend litellm nlp-analyzer redis)

fail=0
error() { echo "❌ $1"; fail=1; }

nombres() {
    local prefix="${1-}"
    (
        cd "$REPO_ROOT"
        if [ -z "$prefix" ]; then
            env -u STACK_PREFIX docker compose -f "$COMPOSE" config
        else
            STACK_PREFIX="$prefix" docker compose -f "$COMPOSE" config
        fi
    ) 2>/dev/null | awk '/^[[:space:]]*container_name:[[:space:]]*/ { print $2 }' | sort
}

esperados() {
    local p="$1"
    local s
    for s in "${SERVICIOS[@]}"; do
        printf '%s-%s\n' "$p" "$s"
    done | sort
}

cmp_nombres() {
    local etiqueta="$1" prefix="$2"
    local got exp
    got="$(nombres "$prefix")"
    exp="$(esperados "$prefix")"
    if [ -z "$got" ]; then
        error "$etiqueta: docker compose config no emitió ningún container_name"
        return
    fi
    if [ "$got" != "$exp" ]; then
        error "$etiqueta: render distinto al esperado (prefix='$prefix')"
        echo "   esperado:"
        echo "$exp" | sed 's/^/     /'
        echo "   obtenido:"
        echo "$got" | sed 's/^/     /'
    fi
}

[ -f "$COMPOSE" ] || { echo "❌ no encuentro $COMPOSE"; exit 1; }

cmp_nombres "default (STACK_PREFIX unset)" "basa"
cmp_nombres "STACK_PREFIX=foo" "foo"

if [ "$fail" -eq 0 ]; then
    echo "✅ STACK_PREFIX: default basa-* y prefix foo-* (6 servicios)"
fi
exit "$fail"
