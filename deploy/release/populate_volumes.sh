#!/usr/bin/env bash
# Puebla los volúmenes nombrados del compose prod que NADIE llenaba en el camino
# compose (hallazgo de la auditoría pre-piloto 2026-07-22): licenses (el .lic),
# litellm_config (config.yaml templado + extensiones) y branding (brand.json).
# En el camino nube lo hace cloud-init (020 US4); este script es su equivalente
# selfhosted — idempotente, se puede re-correr tras actualizar el perfil.
#
# Uso: deploy/release/populate_volumes.sh <client-slug> <archivo.lic>
#   Requiere el perfil RENDERIZADO (deploy/release/render_profile.sh <slug>).
set -euo pipefail

SLUG="${1:?uso: populate_volumes.sh <client-slug> <archivo.lic>}"
LIC="${2:?uso: populate_volumes.sh <client-slug> <archivo.lic>}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROFILES_ROOT="${PROFILES_ROOT:-$REPO_ROOT/deploy/clients}"
RENDERED="$PROFILES_ROOT/$SLUG/rendered"
# El nombre de proyecto compose fija el prefijo de los volúmenes nombrados.
PROJECT="${COMPOSE_PROJECT:-sentinel-guardian}"

[ -f "$RENDERED/config.yaml" ] || { echo "❌ falta $RENDERED/config.yaml (correr render_profile.sh $SLUG)"; exit 2; }
[ -f "$RENDERED/brand.json" ]  || { echo "❌ falta $RENDERED/brand.json (correr render_profile.sh $SLUG)"; exit 2; }
[ -f "$LIC" ] || { echo "❌ no existe el archivo de licencia: $LIC"; exit 2; }

copy_into() { # volumen destino_relativo archivo...
    local vol="$1"; shift
    local dest="$1"; shift
    docker volume create "${PROJECT}_${vol}" >/dev/null
    docker run --rm -v "${PROJECT}_${vol}:/vol" -v "$(cd "$(dirname "$1")" && pwd):/src:ro" \
        alpine:3 sh -c "mkdir -p /vol/$dest && cp /src/$(basename "$1") /vol/$dest/ && chmod 644 /vol/$dest/$(basename "$1")"
}

# 1) Licencia → licenses:/  (el backend la lee en /app/config/licenses/client.lic)
docker volume create "${PROJECT}_licenses" >/dev/null
docker run --rm -v "${PROJECT}_licenses:/vol" -v "$(cd "$(dirname "$LIC")" && pwd):/src:ro" \
    alpine:3 sh -c "cp /src/$(basename "$LIC") /vol/client.lic && chmod 644 /vol/client.lic"
echo "✅ licenses ← $(basename "$LIC") (→ client.lic)"

# Config del motor → litellm_config:/ (el motor lee /app/config; el backend
#    /app/litellm_config — y ESCRIBE ahí en el alta de modelos de la UI, como
#    usuario sentinel 10001:999: sin el chown el alta muere con permission denied).
docker volume create "${PROJECT}_litellm_config" >/dev/null
docker run --rm -v "${PROJECT}_litellm_config:/vol" -v "$RENDERED:/src:ro" \
    alpine:3 sh -c "cp /src/config.yaml /vol/config.yaml && chown 10001:999 /vol /vol/config.yaml && chmod 664 /vol/config.yaml"
# Las extensiones del motor (guardrail/auth/logger) viajan junto al config:
docker run --rm -v "${PROJECT}_litellm_config:/vol" -v "$REPO_ROOT/litellm/extensions:/ext:ro" \
    alpine:3 sh -c "mkdir -p /vol/extensions && cp /ext/*.py /vol/extensions/"
# El supervisor del motor (spec 033) viaja por el MISMO canal templado, no por imagen
# nueva: la del motor es la stock pinneada. Va en la raíz del volumen porque el
# entrypoint de compose.prod.yml lo invoca como /app/config/supervisor.py — el `cp`
# de extensiones de arriba es un glob sobre /ext, así que NO alcanza a este fichero.
# Sin esta línea el motor arranca contra un entrypoint inexistente y no levanta.
# Queda de root a propósito: el motor monta este volumen `:ro` y sólo necesita leerlo.
docker run --rm -v "${PROJECT}_litellm_config:/vol" -v "$REPO_ROOT/litellm:/sup:ro" \
    alpine:3 sh -c "cp /sup/supervisor.py /vol/supervisor.py && chmod 644 /vol/supervisor.py"
echo "✅ litellm_config ← config.yaml + extensiones + supervisor.py"

# 2b) Rutas del auto-router (spec 030) → MISMO volumen: el backend lo lee en cada
#     decisión de ruteo (/app/litellm_config/auto_router.json) y lo REESCRIBE desde el
#     panel «Modelos & Ollama» (PUT atómico tmp + os.replace), como 10001:999. El chown
#     de arriba nombra /vol y /vol/config.yaml, así que NO alcanza a este fichero nuevo:
#     se chownea acá explícitamente (sin esto el fichero queda de root — la escritura
#     atómica sobreviviría por el chown del directorio, pero el estado quedaría
#     inconsistente con config.yaml y cualquier escritura in-place moriría).
#     No es un .tmpl: no lleva variables de perfil (los modelos ya son nombres finales).
#     ⚠ Re-correr el script PISA las rutas editadas por el admin desde el panel, igual
#     que pisa el config.yaml — es el precio de la idempotencia declarada arriba.
AUTO_ROUTER="$PROFILES_ROOT/$SLUG/auto_router.json"
if [ -f "$AUTO_ROUTER" ]; then
    docker run --rm -v "${PROJECT}_litellm_config:/vol" -v "$PROFILES_ROOT/$SLUG:/src:ro" \
        alpine:3 sh -c "cp /src/auto_router.json /vol/auto_router.json \
            && chown 10001:999 /vol/auto_router.json && chmod 664 /vol/auto_router.json"
    echo "✅ litellm_config ← auto_router.json (rutas del auto-router)"
else
    echo "ℹ️  $SLUG sin auto_router.json → el auto-router arranca con defaults (enabled=false)"
fi

# 3) Branding → branding:/ (el frontend sirve /srv/branding)
docker volume create "${PROJECT}_branding" >/dev/null
docker run --rm -v "${PROJECT}_branding:/vol" -v "$RENDERED:/src:ro" \
    alpine:3 sh -c "cp /src/brand.json /vol/brand.json"
if ls "$PROFILES_ROOT/$SLUG/"*.png "$PROFILES_ROOT/$SLUG/"*.svg >/dev/null 2>&1; then
    docker run --rm -v "${PROJECT}_branding:/vol" -v "$PROFILES_ROOT/$SLUG:/src:ro" \
        alpine:3 sh -c "cp /src/*.png /src/*.svg /vol/ 2>/dev/null || true"
fi
echo "✅ branding ← brand.json (+ assets si hay)"

echo ""
echo "Volúmenes poblados para el proyecto compose '$PROJECT'."
echo "Levantar con: docker compose -p $PROJECT -f deploy/docker/compose.prod.yml --profile selfhosted \\"
echo "  --env-file .../instance.env --env-file .../secrets.env up -d"
