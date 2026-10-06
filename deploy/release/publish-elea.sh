#!/usr/bin/env bash
# Publica las imágenes que consume `elea-installer` (ghcr.io/cluna-8/elea-*).
#
# Por qué existe (14-sep-2026, prueba del instalador desde cero): el backend publicado a mano
# con `backend/Dockerfile` (el de desarrollo) arranca en bucle con
# `ModuleNotFoundError: No module named 'extensions'` — en dev esa carpeta llega por un bind
# mount (`./litellm:/app/litellm_config`) que la imagen no tiene. La imagen distribuible es
# `backend/Dockerfile.standalone`, construida DESDE LA RAÍZ del repo. Este script fija el
# Dockerfile y el contexto correctos de cada imagen para que no vuelva a pasar.
#
# Variantes `-ext` (spec 057 T091, FR-004d): después de las base, `backend-ext`, `frontend-ext` y
# `engine-ext` construyen la MISMA imagen base recién publicada más la extensión `sentinel/`
# (sentinel/docker/*.Dockerfile, contexto = RAÍZ del repo) y la publican con tag propio
# `<VERSION>-ext`. NUNCA tocan `latest`: el instalador solo las usa con ELEA_REDIRECT=1.
#
# Uso (desde cualquier directorio, logueado en ghcr con `docker login ghcr.io`):
#   deploy/release/publish-elea.sh                # tag = fecha de hoy + latest (y <fecha>-ext de las -ext)
#   VERSION=2026-09-14 deploy/release/publish-elea.sh
#   ONLY="backend tabular" deploy/release/publish-elea.sh   # solo algunas
#   ONLY="backend engine backend-ext engine-ext" deploy/release/publish-elea.sh
#   DRY_RUN=1 deploy/release/publish-elea.sh      # modo de prueba: imprime los comandos de Docker y no ejecuta ninguno
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REGISTRY="${REGISTRY:-ghcr.io/cluna-8}"
VERSION="${VERSION:-$(date +%Y-%m-%d)}"
DRY_RUN="${DRY_RUN:-0}"
ONLY="${ONLY:-backend frontend engine nlp rag-client tabular backend-ext frontend-ext engine-ext}"

# nombre corto → imagen publicada | Dockerfile (relativo al repo) | contexto (relativo al repo)
declare -A IMAGE=(  [backend]=elea-guardian-backend  [frontend]=elea-guardian-frontend [engine]=elea-guardian-engine
                    [nlp]=elea-guardian-nlp          [rag-client]=elea-rag-client      [tabular]=elea-tabular
                    [backend-ext]=elea-guardian-backend [frontend-ext]=elea-guardian-frontend [engine-ext]=elea-guardian-engine )
declare -A DFILE=(  [backend]=backend/Dockerfile.standalone [frontend]=frontend/Dockerfile [engine]=litellm/Dockerfile
                    [nlp]=presidio-analyzer/Dockerfile      [rag-client]=client/Dockerfile [tabular]=tabular/Dockerfile
                    [backend-ext]=sentinel/docker/backend.Dockerfile [frontend-ext]=sentinel/docker/frontend.Dockerfile
                    [engine-ext]=sentinel/docker/engine.Dockerfile )
declare -A CTX=(    [backend]=.        [frontend]=frontend [engine]=litellm
                    [nlp]=presidio-analyzer [rag-client]=client [tabular]=tabular
                    [backend-ext]=. [frontend-ext]=. [engine-ext]=. )

# Con DRY_RUN=1 los comandos de Docker se imprimen (`+ docker …`) y no se ejecutan.
run() { if [ "$DRY_RUN" = 1 ]; then echo "+ $*"; else "$@"; fi; }

for short in $ONLY; do
  name="${IMAGE[$short]:?imagen desconocida: $short}"
  ref="${REGISTRY}/${name}"
  if [[ "$short" == *-ext ]]; then
    # Variante -ext: deriva de la base recién publicada (BASE_IMAGE), tag propio, jamás `latest`.
    tag="${VERSION}-ext"
    echo "── build ${ref}:${tag}  (${DFILE[$short]}, contexto = raíz del repo, base ${ref}:${VERSION})"
    run docker build -f "${REPO_ROOT}/${DFILE[$short]}" --build-arg "BASE_IMAGE=${ref}:${VERSION}" -t "${ref}:${tag}" "${REPO_ROOT}"
    if [ "$short" = backend-ext ]; then
      # La extensión tiene que importar desde la imagen, con PYTHONPATH y sin ninguna variable de activación.
      run docker run --rm --entrypoint sh "${ref}:${tag}" -c \
        'cd /app && python -c "import sentinel.redirect.api, sentinel.catalog.api, sentinel.redirect.plugin"' \
        || { echo "✗ la imagen backend -ext no importa la extensión — no se publica"; exit 1; }
    fi
    run docker push -q "${ref}:${tag}"
    if [ "$DRY_RUN" = 1 ]; then echo "PINNED ${name}:${tag} (simulado)"; else
      echo "PINNED ${name}=$(docker inspect --format='{{index .RepoDigests 0}}' "${ref}:${tag}")"; fi
    continue
  fi
  echo "── build ${ref}:${VERSION}  (${DFILE[$short]}, contexto ${CTX[$short]})"
  run docker build -f "${REPO_ROOT}/${DFILE[$short]}" -t "${ref}:${VERSION}" -t "${ref}:latest" "${REPO_ROOT}/${CTX[$short]}"
  if [ "$short" = backend ]; then
    # Chequeo del bug de arriba antes de publicar: la política compartida tiene que importar.
    run docker run --rm --entrypoint sh "${ref}:${VERSION}" -c \
      'cd /app && python -c "import sys; sys.path.insert(0, \"/app/litellm_config\"); import extensions.sentinel_governance"' \
      || { echo "✗ la imagen del backend no trae litellm/extensions — no se publica"; exit 1; }
  fi
  run docker push -q "${ref}:${VERSION}"
  run docker push -q "${ref}:latest"
  if [ "$DRY_RUN" = 1 ]; then echo "PINNED ${name}:${VERSION} (simulado)"; else
    echo "PINNED ${name}=$(docker inspect --format='{{index .RepoDigests 0}}' "${ref}:${VERSION}")"; fi
done

echo
echo "Listo. Probá el instalador desde cero antes de sincronizarlo a Azure DevOps (ver elea-installer/README.md)."
