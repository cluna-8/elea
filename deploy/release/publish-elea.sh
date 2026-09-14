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
# Uso (desde cualquier directorio, logueado en ghcr con `docker login ghcr.io`):
#   deploy/release/publish-elea.sh                # tag = fecha de hoy + latest
#   VERSION=2026-09-14 deploy/release/publish-elea.sh
#   ONLY="backend tabular" deploy/release/publish-elea.sh   # solo algunas
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REGISTRY="${REGISTRY:-ghcr.io/cluna-8}"
VERSION="${VERSION:-$(date +%Y-%m-%d)}"
ONLY="${ONLY:-backend frontend engine nlp rag-client tabular}"

# nombre corto → imagen publicada | Dockerfile (relativo al repo) | contexto (relativo al repo)
declare -A IMAGE=(  [backend]=elea-guardian-backend  [frontend]=elea-guardian-frontend [engine]=elea-guardian-engine
                    [nlp]=elea-guardian-nlp          [rag-client]=elea-rag-client      [tabular]=elea-tabular )
declare -A DFILE=(  [backend]=backend/Dockerfile.standalone [frontend]=frontend/Dockerfile [engine]=litellm/Dockerfile
                    [nlp]=presidio-analyzer/Dockerfile      [rag-client]=client/Dockerfile [tabular]=tabular/Dockerfile )
declare -A CTX=(    [backend]=.        [frontend]=frontend [engine]=litellm
                    [nlp]=presidio-analyzer [rag-client]=client [tabular]=tabular )

for short in $ONLY; do
  name="${IMAGE[$short]:?imagen desconocida: $short}"
  ref="${REGISTRY}/${name}"
  echo "── build ${ref}:${VERSION}  (${DFILE[$short]}, contexto ${CTX[$short]})"
  docker build -f "${REPO_ROOT}/${DFILE[$short]}" -t "${ref}:${VERSION}" -t "${ref}:latest" "${REPO_ROOT}/${CTX[$short]}"
  if [ "$short" = backend ]; then
    # Chequeo del bug de arriba antes de publicar: la política compartida tiene que importar.
    docker run --rm --entrypoint sh "${ref}:${VERSION}" -c \
      'cd /app && python -c "import sys; sys.path.insert(0, \"/app/litellm_config\"); import extensions.sentinel_governance"' \
      || { echo "✗ la imagen del backend no trae litellm/extensions — no se publica"; exit 1; }
  fi
  docker push -q "${ref}:${VERSION}"
  docker push -q "${ref}:latest"
  echo "PINNED ${name}=$(docker inspect --format='{{index .RepoDigests 0}}' "${ref}:${VERSION}")"
done

echo
echo "Listo. Probá el instalador desde cero antes de sincronizarlo a Azure DevOps (ver elea-installer/README.md)."
