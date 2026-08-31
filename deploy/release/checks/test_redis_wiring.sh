#!/usr/bin/env bash
# costura → Falime (Factory): invariante de CABLEADO, no de código.
#
# issue #63 (hallazgo del review adversarial): el motor ESCRIBE en Redis claves que el
# backend LEE — el contador de eventos de auditoría perdidos (`sentinel:audit:*`, spec 031) y la
# marca de degradación de la detección NLP (`sentinel:nlp:*`) —, pero el servicio `litellm` del
# compose de producción NO recibía `REDIS_HOST`. En el perfil de NUBE, donde Redis es
# gestionado y no existe ningún host llamado `redis`, el motor escribía al vacío y
# `GET /api/v1/health` reportaba CERO degradaciones mientras el tráfico se servía con regex:
# la promesa central del issue ("degradar nunca es silencioso") se caía justo en el perfil
# que más la necesita, y sin ningún síntoma.
#
# Por qué acá y no en pytest: el contenedor de la suite sólo monta `backend/` y `litellm/`,
# no la raíz del repo, así que no puede ver ningún compose. Esta comprobación mira los
# ficheros del despliegue, que es donde vive el fallo.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

PROD="$REPO_ROOT/deploy/docker/compose.prod.yml"
DEV="$REPO_ROOT/docker-compose.yml"

fail=0

# Extrae el bloque de UN servicio (desde `  <nombre>:` hasta el siguiente servicio de la
# misma indentación). Suficientemente estricto: si el fichero se reestructura, el bloque sale
# vacío y la comprobación falla ruidosa en vez de pasar por casualidad.
bloque_servicio() {
    awk -v svc="$2" '
        $0 ~ "^  " svc ":$" { dentro = 1; next }
        dentro && /^  [a-zA-Z_-]+:$/ { dentro = 0 }
        dentro { print }
    ' "$1"
}

verificar() {
    local fichero="$1" servicio="$2" etiqueta="$3"
    local bloque
    bloque="$(bloque_servicio "$fichero" "$servicio")"
    if [ -z "$bloque" ]; then
        echo "❌ $etiqueta: no se pudo aislar el servicio '$servicio' (¿cambió la estructura?)"
        fail=1
        return
    fi
    for var in REDIS_HOST REDIS_PORT; do
        if ! grep -qE "^\s*(- *)?${var}[:=]" <<<"$bloque"; then
            echo "❌ $etiqueta: el servicio '$servicio' no recibe $var — los dos planos"
            echo "   escriben y leen las MISMAS claves de Redis y quedarían en instancias distintas"
            fail=1
        fi
    done
}

verificar "$PROD" backend "compose.prod.yml"
verificar "$PROD" litellm "compose.prod.yml"
verificar "$DEV"  backend "docker-compose.yml (dev)"
verificar "$DEV"  litellm "docker-compose.yml (dev)"

# El default del código es la red de seguridad del cableado: si los dos planos default-ean a
# hosts distintos, un despliegue que olvide la variable vuelve al mismo split-brain.
DEFAULT_BACKEND=$(grep -oE 'os\.getenv\("REDIS_HOST", "[^"]+"\)' \
    "$REPO_ROOT/backend/src/services/redis_client.py" | head -1 | sed -E 's/.*"([^"]+)"\)/\1/')
for ext in sentinel_guardrail sentinel_audit_logger; do
    DEFAULT_MOTOR=$(grep -oE '_REDIS_HOST_DEFAULT = "[^"]+"' \
        "$REPO_ROOT/litellm/extensions/${ext}.py" | head -1 | sed -E 's/.*"([^"]+)"/\1/')
    if [ "$DEFAULT_MOTOR" != "$DEFAULT_BACKEND" ]; then
        echo "❌ default de REDIS_HOST divergente: backend='$DEFAULT_BACKEND' vs ${ext}='$DEFAULT_MOTOR'"
        fail=1
    fi
done

[ "$fail" = 0 ] && echo "✅ cableado de Redis OK: backend y motor comparten endpoint en dev y prod (defaults alineados: '$DEFAULT_BACKEND')"
exit $fail
