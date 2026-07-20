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

build_and_push() {
    local name="$1" dockerfile="$2"
    local ref="${REGISTRY}/${name}:${VERSION}"
    echo "── build ${ref}"
    docker build -f "${REPO_ROOT}/deploy/docker/${dockerfile}" -t "${ref}" "${REPO_ROOT}"
    docker push "${ref}"
    local digest
    digest=$(docker inspect --format='{{index .RepoDigests 0}}' "${ref}")
    echo "PINNED ${name}=${digest}"
}

build_and_push basa-backend backend.prod.Dockerfile
build_and_push basa-frontend frontend.prod.Dockerfile

echo
echo "Pegá los digests PINNED en el tfvars del cliente (deploy/terraform/envs/<slug>/)"
echo "o en el manifiesto del bundle air-gapped (deploy/release/bundle.sh)."
