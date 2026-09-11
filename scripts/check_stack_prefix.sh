#!/usr/bin/env bash
# issue #223 / PR #230: fija el render de container_name del compose de dev.
#
# Por qué no pytest: el contenedor de la suite no monta la raíz, no ve docker-compose.yml.
# Por qué `docker compose config` y no grep del YAML: hay que clavar la interpolación
# real (${STACK_PREFIX:-sentinel}), no el texto fuente.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="$REPO_ROOT/docker-compose.yml"
# La lista va A MANO a propósito: si se derivara del propio compose, el check compararía el
# archivo contra sí mismo y pasaría siempre. El precio es que un rename de servicio la deja
# atrás — y eso ya pasó: #329 renombró `litellm`→`engine` (`docker-compose.yml`) y nadie tocó
# este archivo, así que el paso 2 de `backend-tests` (ci.yml) voltea el job entero antes de
# levantar la base. El rojo es del rename, no del PR que lo descubre.
SERVICIOS=(backend db engine frontend nlp-analyzer redis)
# `frontend` vive detrás de `profiles: ["full"]` (spec 040, 668ced5) — sin pedir ese
# perfil, `docker compose config` lo omite en silencio y el render "obtenido" queda
# corto por uno, para CUALQUIER prefix. `client`/`anythingllm` quedan detrás de
# `profiles: ["rag"]` y no están en SERVICIOS, así que no se piden acá: pedirlos
# metería servicios de más y el compare exacto de abajo fallaría igual, por el otro lado.
export COMPOSE_PROFILES=full

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

cmp_nombres "default (STACK_PREFIX unset)" "sentinel"
cmp_nombres "STACK_PREFIX=foo" "foo"

if [ "$fail" -eq 0 ]; then
    # El conteo se DERIVA de la lista y no se retipea: hoy imprime lo mismo (6), pero un
    # servicio que se agregue a `SERVICIOS` ya no deja el número viejo en la línea de ÉXITO,
    # que es donde nadie lo mira. Misma clase que el rename de arriba: un conteo escrito a
    # mano es un ancla que vence cuando la estructura crece.
    echo "✅ STACK_PREFIX: default sentinel-* y prefix foo-* (${#SERVICIOS[@]} servicios)"
fi
exit "$fail"
