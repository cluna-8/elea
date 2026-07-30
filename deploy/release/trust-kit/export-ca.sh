#!/usr/bin/env bash
# Exporta la CA raíz interna del ingress y arma el KIT DE CONFIANZA que se le
# entrega al IT del cliente. Se corre EN EL SERVIDOR de la instalación, una vez,
# después de `install.sh`.
#
# Contexto (issue #51): cuando el ingress termina TLS con su CA interna
# (`tls internal`, típico de una LAN sin dominio público), cada puesto de trabajo
# tiene que confiar en esa CA — la extensión de navegador exige https para
# cualquier host que no sea localhost, así que esto es parte OBLIGATORIA del
# onboarding, no un extra.
#
# Uso:
#   ./export-ca.sh --url https://192.168.1.50
#   ./export-ca.sh --project camara --url https://pasarela.interna --out /tmp/kit
#
# Opciones:
#   --project <nombre>   Proyecto compose de la instalación (default: basa).
#   --container <nombre> Contenedor del ingress, si no sigue la convención.
#   --url <url>          URL https por la que los puestos llegan a la pasarela.
#                        Queda escrita en gateway-url.txt para que el instalador
#                        de los puestos verifique sin que nadie teclee nada.
#   --out <directorio>   Dónde dejar el kit (default: ./kit-certificado).
#   -h | --help          Esta ayuda.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="basa"
CONTAINER=""
URL=""
OUT="./kit-certificado"

# Ruta de la raíz de la CA interna dentro del contenedor de Caddy (volumen /data).
CA_EN_CONTENEDOR="/data/caddy/pki/authorities/local/root.crt"

uso() {
  # El bloque de comentarios de cabecera ES la ayuda: se imprime hasta la primera
  # linea que no sea comentario. Sin numeros de linea magicos que se pudran.
  awk 'NR>1 && /^#/ { sub(/^#[ ]?/, ""); print; next } NR>1 { exit }' "$0"
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --project)   PROJECT="${2:?--project necesita un nombre}"; shift 2 ;;
    --container) CONTAINER="${2:?--container necesita un nombre}"; shift 2 ;;
    --url)       URL="${2:?--url necesita una dirección}"; shift 2 ;;
    --out)       OUT="${2:?--out necesita un directorio}"; shift 2 ;;
    -h|--help)   uso 0 ;;
    *) echo "❌ opción desconocida: $1"; uso 2 ;;
  esac
done

command -v docker >/dev/null || { echo "❌ docker no está en el PATH"; exit 2; }

if [ -z "$CONTAINER" ]; then
  CONTAINER="${PROJECT}-ingress-1"
fi
docker inspect "$CONTAINER" >/dev/null 2>&1 || {
  echo "❌ no encuentro el contenedor del ingress: $CONTAINER"
  echo "   Contenedores del proyecto '$PROJECT':"
  docker ps --filter "name=${PROJECT}-" --format '     {{.Names}}  ({{.Status}})' || true
  echo "   Indique el correcto con --container <nombre>."
  exit 2
}

mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"

echo "── extrayendo la CA raíz interna de $CONTAINER"
if ! docker cp "${CONTAINER}:${CA_EN_CONTENEDOR}" "$OUT/root.crt" 2>/dev/null; then
  echo "❌ el ingress no tiene una CA interna en $CA_EN_CONTENEDOR"
  echo
  echo "   Suele significar una de dos cosas, y ninguna es un fallo:"
  echo "     · el ingress sirve HTTP plano (INGRESS_HOST=\":80\") — no hay TLS ni"
  echo "       CA que distribuir, pero entonces la extensión de navegador NO podrá"
  echo "       conectarse por IP/dominio (exige https fuera de localhost);"
  echo "     · el TLS lo termina un certificado público o de la CA del cliente —"
  echo "       en ese caso no hay nada que instalar en los puestos."
  exit 2
fi

command -v openssl >/dev/null || { echo "❌ falta openssl (necesario para la huella SHA-256)"; exit 2; }
HUELLA="$(openssl x509 -in "$OUT/root.crt" -noout -fingerprint -sha256 | sed 's/^.*=//')"
CADUCA="$(openssl x509 -in "$OUT/root.crt" -noout -enddate | sed 's/^notAfter=//')"
SUJETO="$(openssl x509 -in "$OUT/root.crt" -noout -subject | sed 's/^subject= *//')"

echo "── copiando los instaladores de puesto"
for f in install-ca.ps1 install-ca.bat install-ca-macos.sh; do
  cp "$HERE/$f" "$OUT/$f"
done
chmod +x "$OUT/install-ca-macos.sh"

if [ -n "$URL" ]; then
  printf '%s\n' "$URL" > "$OUT/gateway-url.txt"
  echo "── gateway-url.txt: $URL"
else
  echo "⚠️  sin --url: los instaladores de puesto van a preguntar la dirección por pantalla."
  echo "   Recomendado: volver a correr con --url https://<direccion-de-la-pasarela>"
fi

cat <<FIN

✅ kit de confianza listo en: $OUT

   CA raíz    : $SUJETO
   Caduca     : $CADUCA
   SHA-256    : $HUELLA

   ⚠️  Entregue esa huella SHA-256 al IT del cliente por un canal DISTINTO del que
       lleva el fichero (teléfono, por ejemplo). Es lo que les permite comprobar
       que la CA que instalan es la de esta instalación y no otra cosa.

   En cada puesto Windows:  doble-click en install-ca.bat
   En cada Mac:             ./install-ca-macos.sh
   Para toda la flota AD:   directiva de grupo (ver la documentación del producto)
FIN
