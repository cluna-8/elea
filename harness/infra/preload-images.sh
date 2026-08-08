#!/usr/bin/env bash
# Precarga de imágenes al SUT por docker save/load + scp (research R4, opción b: sin
# registry, encaja con la caja sin egress y con el patrón air-gap de la casa).
# ORDEN CRÍTICO: precargar ANTES de cerrar el firewall de egress — una vez cerrado, el
# SUT no puede hacer pull de ningún lado.
#
# Uso: ./preload-images.sh <sut_public_ip> <imagen1> [imagen2 ...]
set -euo pipefail

SUT_IP="${1:?uso: preload-images.sh <sut_public_ip> <imagen...>}"
shift
IMAGES=("$@")
[ "${#IMAGES[@]}" -gt 0 ] || { echo "error: pasá al menos una imagen"; exit 1; }

echo "→ Empaquetando ${#IMAGES[@]} imágenes con docker save…"
TARBALL="$(mktemp -t itv-images-XXXX).tar.gz"
docker save "${IMAGES[@]}" | gzip > "$TARBALL"
echo "  tarball: $TARBALL ($(du -h "$TARBALL" | cut -f1))"

echo "→ Copiando al SUT ($SUT_IP)…"
scp "$TARBALL" "root@${SUT_IP}:/tmp/itv-images.tar.gz"

echo "→ Cargando en el SUT…"
ssh "root@${SUT_IP}" 'gunzip -c /tmp/itv-images.tar.gz | docker load && rm -f /tmp/itv-images.tar.gz'

rm -f "$TARBALL"
echo "✓ Imágenes precargadas. AHORA sí se puede cerrar el firewall de egress (tofu apply del firewall)."
