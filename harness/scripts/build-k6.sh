#!/usr/bin/env bash
# build-k6.sh — construye el binario k6 versionado del harness (spec 035, T023; research R1).
#
# Corre el one-liner VERIFICADO de R1 (07-ago): xk6 build de k6 v1.8.0 + xk6-sse v0.1.12,
# PINEADOS, para x86_64 (linux/amd64 — la caja de examen Hetzner es amd64). Deja el binario
# en harness/bin/k6 y su sha256 en harness/bin/k6.sha256 (entra al fingerprint como
# versiones_instrumento). El binario NO se commitea (bin/ está gitignored): se versiona por
# hash, se reconstruye reproducible.
#
# ⚠️ NO k6 v2.x (rompió xk6-sse). Uso:  ./scripts/build-k6.sh
set -euo pipefail

K6_VERSION="${K6_VERSION:-v1.8.0}"
XK6_SSE_VERSION="${XK6_SSE_VERSION:-v0.1.12}"
PLATFORM="${PLATFORM:-linux/amd64}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${HERE}/bin"
mkdir -p "${OUT}"

echo "→ k6 ${K6_VERSION} + xk6-sse ${XK6_SSE_VERSION} (${PLATFORM})"
docker run --rm --platform "${PLATFORM}" -v "${OUT}:/xk6" grafana/xk6 build "${K6_VERSION}" \
  --with "github.com/phymbert/xk6-sse@${XK6_SSE_VERSION}" \
  --output /xk6/k6

# sha256 → fingerprint (portable macOS/Linux).
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "${OUT}/k6" | tee "${OUT}/k6.sha256"
else
  shasum -a 256 "${OUT}/k6" | tee "${OUT}/k6.sha256"
fi

echo "→ verificación:"
"${OUT}/k6" version || echo "  (no ejecutable en este host: normal si PLATFORM != host arch)"
echo "✓ binario versionado: ${OUT}/k6  (registrá el sha256 en el fingerprint del run)"
