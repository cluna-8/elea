#!/usr/bin/env bash
# Publica las imágenes de PRODUCCIÓN pinneadas por tag+digest (spec 020 T010, FR-004).
# Reusa la disciplina de pin de la 014 (la imagen LiteLLM ya viaja pinneada; acá
# se publican backend/frontend propias). El digest impreso al final es el que
# consumen el módulo OpenTofu (compute) y el bundle air-gapped (bundle.sh).
#
# Uso: REGISTRY=registry.example.com/basa VERSION=1.0.0 deploy/release/publish.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REGISTRY="${REGISTRY:?falta REGISTRY (p.ej. ghcr.io/distribuidor)}"
VERSION="${VERSION:?falta VERSION (semver del release)}"

# $1 nombre de imagen, $2 Dockerfile (relativo al repo), $3 contexto de build
# (relativo al repo; por defecto la raíz, que es lo que necesitan backend/frontend).
build_and_push() {
    local name="$1" dockerfile="$2" context="${3:-.}"
    local ref="${REGISTRY}/${name}:${VERSION}"
    echo "── build ${ref}"
    docker build -f "${REPO_ROOT}/${dockerfile}" -t "${ref}" "${REPO_ROOT}/${context}"
    docker push "${ref}"
    local digest
    digest=$(docker inspect --format='{{index .RepoDigests 0}}' "${ref}")
    echo "PINNED ${name}=${digest}"
}

# $1 nombre de imagen publicada, $2 referencia upstream (pin por digest)
# (rename de marca #302): pull+tag+push del upstream pinneado, sin modificarlo.
retag_upstream() {
    local name="$1" upstream_ref="$2"
    local ref="${REGISTRY}/${name}:${VERSION}"
    echo "── retag upstream ${upstream_ref} → ${ref}"
    docker pull "${upstream_ref}"
    docker tag "${upstream_ref}" "${ref}"
    docker push "${ref}"
    local digest
    digest=$(docker inspect --format='{{index .RepoDigests 0}}' "${ref}")
    echo "PINNED ${name}=${digest}"
}

build_and_push basa-backend  deploy/docker/backend.prod.Dockerfile
build_and_push basa-frontend deploy/docker/frontend.prod.Dockerfile
# Analizador NLP (spec 016): Dockerfile y contexto propios fuera de deploy/docker.
# El nombre publicado es neutro (Principio VII) aunque el directorio del repo no lo sea.
build_and_push basa-nlp-analyzer presidio-analyzer/Dockerfile presidio-analyzer

# Motor de IA (rename de marca, issue #302): la imagen upstream es la de LiteLLM
# pinneada por digest (spec 014); se publica como basa-engine sin modificarla —
# solo retag+push. El input es el pin real del vendor (ghcr.io/berriai/litellm@sha256:...),
# no una var de compose.
retag_upstream basa-engine "${UPSTREAM_ENGINE_IMAGE:?falta UPSTREAM_ENGINE_IMAGE (p.ej. ghcr.io/berriai/litellm@sha256:...)}"

echo
echo "Pegá los digests PINNED en el tfvars del cliente (deploy/terraform/envs/<slug>/)"
echo "o en el manifiesto del bundle air-gapped (deploy/release/bundle.sh)."
