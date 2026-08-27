#!/usr/bin/env bash
# Bundle AIR-GAPPED v1 (spec 020 US6, FR-028): tarball autocontenido con TODAS
# las imágenes pinneadas + compose prod + perfil renderizado + checks. Se
# instala con docker load en un host SIN registry (caso Elea / on-prem).
#
# Uso: BACKEND_IMAGE=... FRONTEND_IMAGE=... LITELLM_IMAGE=... DOCS_IMAGE=... \
#      NLP_ANALYZER_IMAGE=... \
#      CADDY_IMAGE=caddy:2-alpine POSTGRES_IMAGE=postgres:16 REDIS_IMAGE=redis:7-alpine \
#      deploy/release/bundle.sh <client-slug> [outdir]
set -euo pipefail
SLUG="${1:?uso: bundle.sh <client-slug> [outdir]}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${2:-$REPO_ROOT/deploy/release/bundle-$SLUG}"
# Staging SIEMPRE desde cero: `cp -R x $OUT/x` sobre un staging de una corrida
# anterior copia ADENTRO (x/x anidado) en vez de reemplazar, y el bundle se lleva
# los archivos viejos — un secrets.env stale con overrides de ensayo llegó a
# empaquetarse así el 2026-07-27 (el instalador habría escuchado en :8085).
rm -rf "$OUT"
mkdir -p "$OUT"

# TODAS las imágenes del release (edge case: una imagen fuera del tarball =
# pull en runtime = install roto sin egress). Incluye las selfhosted on-prem.
IMAGES=(
  "${BACKEND_IMAGE:?}" "${FRONTEND_IMAGE:?}" "${LITELLM_IMAGE:?}" "${DOCS_IMAGE:?sitio de docs por marca (022)}"
  "${NLP_ANALYZER_IMAGE:?analizador NLP (016) — sin él el motor enmascara con regex}"
  "${CADDY_IMAGE:-caddy:2-alpine}" "${POSTGRES_IMAGE:-postgres:16}" "${REDIS_IMAGE:-redis:7-alpine}"
)

# Arquitectura del bundle = la de las imágenes, y TODAS deben coincidir. Descubierto el
# 2026-07-27: el Mac (arm64) construyó todo en arm64 y la sede del cliente es x86_64 —
# cada contenedor habría muerto con "exec format error" recién al arrancar. El gate
# frena acá, donde todavía se puede reconstruir, no en la sede.
BUNDLE_ARCH="$(docker image inspect --format '{{.Architecture}}' "${BACKEND_IMAGE}")"
for img in "${IMAGES[@]}"; do
  A="$(docker image inspect --format '{{.Architecture}}' "$img")"
  [ "$A" = "$BUNDLE_ARCH" ] || { echo "❌ $img es $A pero el bundle es $BUNDLE_ARCH — rebuild/pull con --platform linux/$BUNDLE_ARCH"; exit 1; }
done
echo "── arquitectura del bundle: linux/$BUNDLE_ARCH"

echo "── docker save (${#IMAGES[@]} imágenes)"
docker save "${IMAGES[@]}" -o "$OUT/images.tar"

# Plugin compose de la MISMA arch: el docker.io de Ubuntu no lo trae y en una sede sin
# internet no hay apt que lo salve — install.sh lo instala sólo si el host no lo tiene.
case "$BUNDLE_ARCH" in
  amd64) COMPOSE_SRC="$REPO_ROOT/deploy/release/vendor/docker-compose-linux-x86_64" ;;
  arm64) COMPOSE_SRC="$REPO_ROOT/deploy/release/vendor/docker-compose-linux-aarch64" ;;
  *)     COMPOSE_SRC="" ;;
esac
if [ -n "$COMPOSE_SRC" ] && [ -f "$COMPOSE_SRC" ]; then
  cp "$COMPOSE_SRC" "$OUT/docker-compose-plugin" && chmod +x "$OUT/docker-compose-plugin"
  echo "── plugin compose incluido ($(cat "$REPO_ROOT/deploy/release/vendor/VERSION" 2>/dev/null || echo '?'), $BUNDLE_ARCH)"
else
  echo "⚠️  sin binario compose para $BUNDLE_ARCH en deploy/release/vendor/ — el host deberá traer el plugin"
fi

"$REPO_ROOT/deploy/release/render_profile.sh" "$SLUG"
cp "$REPO_ROOT/deploy/docker/compose.prod.yml" "$OUT/"
cp -R "$REPO_ROOT/deploy/clients/$SLUG/rendered" "$OUT/profile"
cp -R "$REPO_ROOT/deploy/release/checks" "$OUT/checks"
# Aviso de atribución MIT: la licencia exige que el copyright + permission notice
# acompañe a toda copia redistribuida (viaja dentro del tarball, no en el repo).
cp "$REPO_ROOT/deploy/release/THIRD_PARTY_NOTICES.txt" "$OUT/THIRD_PARTY_NOTICES.txt"

# Bind mounts RELATIVOS que exige el compose (Caddyfile.ingress, initdb/...).
# Descubierto en el ensayo del 2026-07-27, y era fatal en las dos direcciones:
# faltaba el Caddyfile, así que Docker creaba un DIRECTORIO vacío en su lugar y el
# ingress no arrancaba (sin puerta de entrada al producto); y faltaba initdb/, así que
# 01-engine-db.sql no corría y la base del motor NO SE CREABA — eso último en silencio,
# con el stack aparentemente "casi arriba". La lista se deriva del propio compose para
# que agregar un mount nuevo no vuelva a romper el tarball sin aviso.
for rel in $(grep -oE '\./[A-Za-z0-9_./-]+' "$REPO_ROOT/deploy/docker/compose.prod.yml" | sort -u); do
  src="$REPO_ROOT/deploy/docker/${rel#./}"
  [ -e "$src" ] || { echo "❌ el compose monta '$rel' y no existe en deploy/docker/"; exit 1; }
  cp -R "$src" "$OUT/${rel#./}"
done

# Entregable white-label de la EXTENSIÓN (028 US1/US7): si el cliente tiene brand-pack,
# lo renderizamos y viaja en el bundle (edge case simétrico al de las imágenes: un
# artefacto fuera del tarball = fetch en runtime = install roto sin egress).
EXT_BRAND_JSON="$REPO_ROOT/deploy/clients/$SLUG/brand.extension.json"
EXT_ZIP_NAME="extension-$SLUG.zip"
EXT_INCLUDED=0
if [ -f "$EXT_BRAND_JSON" ]; then
  "$REPO_ROOT/deploy/release/render_extension_brand.sh" "$SLUG" "$EXT_BRAND_JSON" >/dev/null
  cp "$REPO_ROOT/deploy/clients/$SLUG/rendered/$EXT_ZIP_NAME" "$OUT/$EXT_ZIP_NAME"
  EXT_INCLUDED=1
  echo "── extensión white-label incluida: $EXT_ZIP_NAME"
else
  echo "── $SLUG sin brand.extension.json → bundle sin extensión de navegador"
fi

# Extensiones del MOTOR (guardrail, custom_auth, audit logger). Sin ellas el motor no
# arranca —el config las referencia por módulo— y, si arrancara, no aplicaría NINGUNA
# política: el tráfico saldría sin enmascarar. No viajaban en el tarball (ensayo
# 2026-07-27): el único camino que las instalaba era populate_volumes.sh leyéndolas del
# REPO, que en la sede del cliente no existe.
mkdir -p "$OUT/engine-extensions"
cp "$REPO_ROOT"/litellm/extensions/*.py "$OUT/engine-extensions/"

# Kit de confianza del certificado (issue #51). Cuando el ingress termina TLS con su CA
# interna (LAN sin dominio público), cada puesto tiene que confiar en esa CA o la
# extensión de navegador NO conecta —exige https fuera de localhost—. En la sede no hay
# repo del que sacar los instaladores: viajan en el tarball, como todo lo demás.
# La `root.crt` NO se puede incluir acá: la genera el ingress en su primer arranque; se
# extrae ya en el servidor con `trust-kit/export-ca.sh`.
mkdir -p "$OUT/trust-kit"
cp "$REPO_ROOT"/deploy/release/trust-kit/install-ca.ps1 \
   "$REPO_ROOT"/deploy/release/trust-kit/install-ca.bat \
   "$REPO_ROOT"/deploy/release/trust-kit/install-ca-macos.sh \
   "$REPO_ROOT"/deploy/release/trust-kit/export-ca.sh "$OUT/trust-kit/"
chmod +x "$OUT/trust-kit/export-ca.sh" "$OUT/trust-kit/install-ca-macos.sh"
echo "── kit de confianza del certificado incluido (trust-kit/)"

# Instalador AUTOCONTENIDO. Antes el bundle no traía ninguno y el procedimiento real
# vivía en populate_volumes.sh, que no puede correr en la sede: está fuera del tarball,
# lee las extensiones del repo, y hace `docker run alpine:3` — un PULL, o sea imposible
# sin salida a internet, que es justo el caso de uso de este bundle. Este script usa una
# imagen que YA viene en images.tar para copiar a los volúmenes.
cat > "$OUT/install.sh" <<'INSTALLER'
#!/usr/bin/env bash
# Instalador air-gapped. No necesita red, ni el repo, ni imágenes extra.
#
# Uso:  ./install.sh <fichero.lic> [nombre-de-proyecto]
#   El nombre de proyecto fija el prefijo de los volúmenes (default: basa).
#   Puertos: INGRESS_HTTP_PORT / INGRESS_HTTPS_PORT (default 80/443).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIC="${1:?uso: ./install.sh <fichero.lic> [nombre-de-proyecto]}"
PROJECT="${2:-basa}"
[ -f "$LIC" ] || { echo "❌ no existe el fichero de licencia: $LIC"; exit 2; }
command -v docker >/dev/null || { echo "❌ docker no está instalado o no está en el PATH"; exit 1; }

# Preflight de ARQUITECTURA: una imagen de otra arch no falla al cargar sino recién al
# arrancar, con un críptico "exec format error" contenedor por contenedor. Mejor acá.
BUNDLE_ARCH="$(awk -F': ' '/^# arch:/{print $2; exit}' "$HERE/MANIFEST" 2>/dev/null || true)"
HOST_ARCH="$(uname -m)"
case "$HOST_ARCH" in x86_64) HOST_ARCH=amd64 ;; aarch64|arm64) HOST_ARCH=arm64 ;; esac
if [ -n "$BUNDLE_ARCH" ] && [ "$BUNDLE_ARCH" != "$HOST_ARCH" ]; then
  if [ "${BASA_ALLOW_ARCH_MISMATCH:-}" = "1" ]; then
    echo "⚠️  bundle $BUNDLE_ARCH sobre host $HOST_ARCH — siguiendo por BASA_ALLOW_ARCH_MISMATCH=1"
    echo "    (sólo funciona con emulación binfmt/Rosetta activa; rendimiento degradado)"
  else
    echo "❌ este bundle trae imágenes $BUNDLE_ARCH y el host es $HOST_ARCH — hace falta el bundle $HOST_ARCH"
    echo "   (si el host tiene emulación binfmt/Rosetta y es a propósito: BASA_ALLOW_ARCH_MISMATCH=1 ./install.sh …)"
    exit 1
  fi
fi

# El docker.io de Ubuntu viene SIN el plugin compose; si el bundle trae el binario
# (misma arch), se instala acá y la sede no necesita internet para nada.
if ! docker compose version >/dev/null 2>&1; then
  if [ -f "$HERE/docker-compose-plugin" ]; then
    echo "── el host no tiene 'docker compose': instalando el plugin incluido en el bundle"
    PLUG_DIR=/usr/local/lib/docker/cli-plugins
    if ! mkdir -p "$PLUG_DIR" 2>/dev/null || [ ! -w "$PLUG_DIR" ]; then
      PLUG_DIR="$HOME/.docker/cli-plugins"; mkdir -p "$PLUG_DIR"
    fi
    cp "$HERE/docker-compose-plugin" "$PLUG_DIR/docker-compose" && chmod +x "$PLUG_DIR/docker-compose"
    docker compose version >/dev/null 2>&1 || { echo "❌ no pude habilitar 'docker compose' (¿ejecutar con sudo?)"; exit 1; }
  else
    echo "❌ falta el plugin 'docker compose' y este bundle no trae el binario"; exit 1
  fi
fi

echo "── 1/4 cargando imágenes desde el tarball (sin red)"
docker load -i "$HERE/images.tar"

# Imagen auxiliar para poblar volúmenes: se elige una que acaba de cargarse, para no
# depender de ningún pull. redis:7-alpine trae sh/cp/chown y pesa poco.
HELPER="$(awk '/^redis:/{print $1; exit}' "$HERE/MANIFEST")"
[ -n "$HELPER" ] || HELPER="redis:7-alpine"

echo "── 2/4 poblando volúmenes (licencia, config del motor, extensiones, branding)"
vol() { docker volume create "${PROJECT}_$1" >/dev/null; }
vol licenses; vol litellm_config; vol branding
LIC_DIR="$(cd "$(dirname "$LIC")" && pwd)"; LIC_FILE="$(basename "$LIC")"
docker run --rm --entrypoint sh \
  -v "${PROJECT}_licenses:/vol" -v "$LIC_DIR:/src:ro" "$HELPER" \
  -c "cp /src/$LIC_FILE /vol/client.lic && chmod 644 /vol/client.lic"
# El backend ESCRIBE en litellm_config al dar de alta modelos por la UI, como 10001:999.
docker run --rm --entrypoint sh \
  -v "${PROJECT}_litellm_config:/vol" -v "$HERE/profile:/src:ro" -v "$HERE/engine-extensions:/ext:ro" "$HELPER" \
  -c "cp /src/config.yaml /vol/config.yaml && mkdir -p /vol/extensions && cp /ext/*.py /vol/extensions/ \
      && chown -R 10001:999 /vol && chmod 664 /vol/config.yaml"
# Rutas del auto-router (spec 030) al mismo volumen. Opcional: un perfil sin
# auto_router.json deja el router en sus defaults (apagado) en vez de romper el install.
docker run --rm --entrypoint sh \
  -v "${PROJECT}_litellm_config:/vol" -v "$HERE/profile:/src:ro" "$HELPER" \
  -c "if [ -f /src/auto_router.json ]; then cp /src/auto_router.json /vol/auto_router.json \
        && chown 10001:999 /vol/auto_router.json && chmod 664 /vol/auto_router.json; fi"
docker run --rm --entrypoint sh \
  -v "${PROJECT}_branding:/vol" -v "$HERE/profile:/src:ro" "$HELPER" \
  -c "cp /src/brand.json /vol/brand.json"

echo "── 3/4 levantando el stack"
docker compose -p "$PROJECT" -f "$HERE/compose.prod.yml" --profile selfhosted \
  --env-file "$HERE/profile/instance.env" --env-file "$HERE/profile/secrets.env" up -d

echo "── 4/4 comprobando"
echo "   ⚠️  en el PRIMER arranque el motor puede reportarse 'unhealthy' por timeout"
echo "       aunque haya arrancado bien: corre sus propias migraciones. Esperá y repetí."
docker compose -p "$PROJECT" -f "$HERE/compose.prod.yml" --profile selfhosted \
  --env-file "$HERE/profile/instance.env" --env-file "$HERE/profile/secrets.env" ps
cat <<FIN

✅ instalado. Proyecto compose: '$PROJECT'

   Siguiente:
     1. curl -s http://localhost:\${INGRESS_HTTP_PORT:-80}/api/v1/health/license
        → anotá chain.genesis_license_id (es la génesis de auditoría de esta instalación)
     2. primer login como 'admin' en el navegador: la contraseña que escribas QUEDA
        (mínimo 12 caracteres)
     3. si el acceso va por https con la CA interna del ingress, armá el kit de
        confianza ANTES de repartir la extensión (sin él no conecta):
          ./trust-kit/export-ca.sh --project $PROJECT --url https://<host>
     4. la extensión de navegador está en este mismo directorio

   Para parar o reiniciar hay que repetir los --env-file; sin ellos compose no puede
   interpolar las variables obligatorias y falla:
     docker compose -p $PROJECT -f compose.prod.yml --profile selfhosted \\
       --env-file profile/instance.env --env-file profile/secrets.env down
FIN
INSTALLER
chmod +x "$OUT/install.sh"

# sha256 portable (Linux: sha256sum; macOS: shasum -a 256).
sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}';
  else shasum -a 256 "$1" | awk '{print $1}'; fi
}

# Manifiesto: imágenes con digest (docker load) + artefactos con sha256 (verificación
# del install air-gapped). Las líneas de imagen llevan $2 = "sha256:<id>" (formato de
# docker); las de artefacto un sha256 pelado → el check las distingue por ese prefijo.
{
  echo "# bundle $SLUG — $(date -u +%FT%TZ)"
  echo "# arch: $BUNDLE_ARCH"
  echo "# images (docker load):"
  for img in "${IMAGES[@]}"; do
    echo "$img $(docker image inspect -f '{{.Id}}' "$img")"
  done
  echo "# artifacts (sha256):"
  if [ "$EXT_INCLUDED" -eq 1 ]; then
    echo "$EXT_ZIP_NAME $(sha256 "$OUT/$EXT_ZIP_NAME")"
  fi
  echo "THIRD_PARTY_NOTICES.txt $(sha256 "$OUT/THIRD_PARTY_NOTICES.txt")"
} > "$OUT/MANIFEST"

# --no-xattrs: el tar de macOS mete xattrs de proveniencia que el tar de Linux escupe
# como 60 warnings "LIBARCHIVE.xattr" — inofensivos pero alarmantes en plena instalación.
tar -C "$(dirname "$OUT")" --no-xattrs -czf "$OUT.tar.gz" "$(basename "$OUT")"
echo "✅ bundle: $OUT.tar.gz (linux/$BUNDLE_ARCH — instalar: ./install.sh <lic> [proyecto])"
