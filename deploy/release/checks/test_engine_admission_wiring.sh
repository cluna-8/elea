#!/usr/bin/env bash
# issue #151 (nota N3 del gate round 2 de #135): invariante de CABLEADO de las perillas de
# admisión al motor. No prueba código —eso ya lo hace tests/unit/test_engine_gate.py—: prueba
# que una INSTALACIÓN pueda girarlas.
#
# El agujero que cierra: el tope de admisión del nodo C1 se mergeó env-tuneable, pero ninguna
# de sus cinco variables llegaba al contenedor en el perfil de producción. Los defaults son
# sanos, así que nada se veía roto; simplemente el operador NO PODÍA cambiar nada — ni para
# los gates 250/500 ni para la sede, donde el modelo local es lento y el tope hay que
# ajustarlo. Un perfil que no cablea una perilla la vuelve decorativa, y encima en silencio.
#
# Se verifica, para las 5 envs y en los DOS planos (prod y dev):
#   1. que el servicio `backend` las reciba, en forma `${VAR:-<default>}` (o sea: overrideable
#      desde el entorno de la instalación, con un default explícito y no vacío — un `- VAR=`
#      pelado es "no seteado" para el código y engaña al que lee el compose);
#   2. que ese default caiga DENTRO del rango que declara el código: un default fuera de
#      rango se ignora con un warning en el log y el operador se queda creyendo que giró algo;
#   3. que la variable esté documentada en `.env.example` SIN comentar y que haya llegado a la
#      referencia de configuración del sitio (que se genera de ahí — single-source 022 US5).
# Y de yapa, el `WEB_CONCURRENCY:-2` del perfil prod, porque el contract test del catálogo del
# motor (backend/tests/contract/test_catalogo_motor_paralelismo.py) lo tiene que repetir como
# constante: su contenedor no monta la raíz del repo y no puede leer este compose.
#
# Por qué acá y no en pytest: mismo motivo que test_redis_wiring.sh — el contenedor de la
# suite sólo monta `backend/` y `litellm/`, así que no ve ningún compose. El fallo vive en los
# ficheros del despliegue; la comprobación tiene que mirar ahí.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

PROD="$REPO_ROOT/deploy/docker/compose.prod.yml"
DEV="$REPO_ROOT/docker-compose.yml"
ENV_EXAMPLE="$REPO_ROOT/.env.example"
CONFIG_REF="$REPO_ROOT/docs/docs/api-reference/configuration.md"
ENGINE_GATE="$REPO_ROOT/backend/src/services/engine_gate.py"

VARS=(
    SENTINEL_ENGINE_MAX_CONCURRENCY
    SENTINEL_ENGINE_QUEUE_TIMEOUT_SECONDS
    SENTINEL_ENGINE_TIMEOUT_SECONDS
    SENTINEL_GW_BYOK_TIMEOUT_SECONDS
    SENTINEL_GW_BYOK_READ_TIMEOUT_SECONDS
)

fail=0
error() { echo "❌ $1"; fail=1; }

# Bloque de UN servicio del compose (desde `  <nombre>:` hasta el siguiente servicio de la
# misma indentación). Mismo helper que test_redis_wiring.sh: si el fichero se reestructura el
# bloque sale vacío y la comprobación falla ruidosa en vez de pasar por casualidad.
bloque_servicio() {
    awk -v svc="$2" '
        $0 ~ "^  " svc ":$" { dentro = 1; next }
        dentro && /^  [a-zA-Z_-]+:$/ { dentro = 0 }
        dentro { print }
    ' "$1"
}

# ── 1+2) cableado en los dos planos, con el default dentro del rango del código ────────────
verificar_plano() {
    local fichero="$1" etiqueta="$2" bloque
    bloque="$(bloque_servicio "$fichero" backend)"
    if [ -z "$bloque" ]; then
        error "$etiqueta: no pude aislar el servicio 'backend' (¿cambió la estructura?)"
        return
    fi
    for var in "${VARS[@]}"; do
        local linea default
        linea="$(grep -E "^\s*(- *)?${var}[:=]" <<<"$bloque" | head -1 || true)"
        if [ -z "$linea" ]; then
            error "$etiqueta: el servicio 'backend' no recibe $var — la perilla queda clavada
   en el default del código y la instalación no puede girarla (issue #151)"
            continue
        fi
        # Forma exigida: ${VAR:-<default>}. Un literal ("8") no se puede overridear sin
        # reeditar el compose; un ${VAR} pelado deja la env vacía = default silencioso.
        default="$(sed -nE "s/.*\\\$\{${var}:-([^}]*)\}.*/\1/p" <<<"$linea")"
        if [ -z "$default" ]; then
            error "$etiqueta: $var no viaja como \${${var}:-<default>} con default explícito:
   $(echo "$linea" | sed 's/^\s*//')"
            continue
        fi
        verificar_rango "$etiqueta" "$var" "$default"
    done
}

# El rango es del CÓDIGO (engine_gate.py), no de este script: se extrae de la llamada al
# helper para que no puedan divergir. Un default de perfil fuera de rango no explota — el
# código lo descarta con un warning y usa el suyo—, que es justo lo peor: el operador cree
# que configuró y no configuró nada.
verificar_rango() {
    local etiqueta="$1" var="$2" default="$3" linea minimo maximo
    linea="$(grep -E "_env_(int|float)\(\"${var}\"" "$ENGINE_GATE" | head -1 || true)"
    if [ -z "$linea" ]; then
        error "$etiqueta: $var no aparece en engine_gate.py — o se renombró la env en el
   código y el perfil quedó cableando un fantasma, o al revés"
        return
    fi
    maximo="$(sed -nE 's/.*maximo=([0-9.]+).*/\1/p' <<<"$linea")"
    # Los floats no declaran mínimo: el helper exige 0 < v (un timeout de 0 es no tener
    # timeout). Los enteros sí (`minimo=1`).
    minimo="$(sed -nE 's/.*minimo=([0-9.]+).*/\1/p' <<<"$linea")"
    [ -n "$maximo" ] || { error "$etiqueta: no pude leer el techo de $var en engine_gate.py"; return; }
    awk -v d="$default" -v mn="${minimo:-}" -v mx="$maximo" 'BEGIN {
        if (d !~ /^[0-9]+(\.[0-9]+)?$/) exit 1        # "", "abc", "1e9": el código lo descarta igual
        if (mn == "") { if (!(d + 0 > 0 && d + 0 <= mx + 0)) exit 1 }
        else          { if (!(d + 0 >= mn + 0 && d + 0 <= mx + 0)) exit 1 }
    }' || error "$etiqueta: el default de $var ($default) queda fuera del rango que
   impone el código (${minimo:-0 (exclusivo)}..$maximo): el motor de configuración lo
   descartaría con un warning y usaría el default interno — perilla decorativa"
}

verificar_plano "$PROD" "compose.prod.yml"
verificar_plano "$DEV"  "docker-compose.yml (dev)"

# ── 3) documentación single-source ────────────────────────────────────────────────────────
for var in "${VARS[@]}"; do
    grep -qE "^${var}=" "$ENV_EXAMPLE" \
        || error ".env.example no declara $var sin comentar — el generador de la referencia
   de configuración (docs/gen_config_reference.py) sólo ve las líneas VAR=valor, así que la
   perilla existiría en el producto y no en la documentación"
    grep -qF "\`$var\`" "$CONFIG_REF" \
        || error "$var no llegó a docs/docs/api-reference/configuration.md — regenerar con
   'make -C deploy docs-refs' (el job check-docs vigila la deriva)"
done

# ── 4) la constante que el contract test del catálogo no puede leer desde su contenedor ────
grep -qE '\$\{WEB_CONCURRENCY:-2\}' "$PROD" \
    || error "compose.prod.yml ya no fija WEB_CONCURRENCY=2 por default:
   backend/tests/contract/test_catalogo_motor_paralelismo.py repite ese 2 como constante para
   comparar el tope del motor contra el TOTAL del backend (tope por proceso × workers). Si el
   perfil cambia y la constante no, el contract test mide una instalación que no existe"

[ "$fail" = 0 ] && echo "✅ perillas de admisión cableadas en prod y dev (5/5), defaults dentro
   del rango del código, documentadas en .env.example y en la referencia del sitio"
exit $fail
