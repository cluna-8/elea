#!/usr/bin/env bash
# Confianza del certificado de la pasarela — macOS.
#
# Equivalente de install-ca.ps1 para los Mac de la flota: instala la CA raíz
# interna en el llavero del SISTEMA (no en el del usuario) y VERIFICA de verdad
# el resultado, con la evaluación de confianza del propio macOS.
#
# Hasta hoy este procedimiento se pasaba a mano por chat (issue #51); acá queda
# como parte del kit.
#
# Uso:
#   ./install-ca-macos.sh --cert root.crt --url https://192.168.1.50
#   ./install-ca-macos.sh                    # autodetecta el .crt y lee gateway-url.txt
#
# Opciones:
#   --cert <fichero>   CA raíz (.crt/.cer/.pem). Default: el único que haya al lado.
#   --url  <url>       URL https de la pasarela para verificar. Default: gateway-url.txt.
#   --skip-firefox     No toca la directiva de Firefox.
#   -h | --help        Esta ayuda.
#
# Salidas: 0 = verde · 1 = la verificación falló · 2 = error de entrada.
#
# Compatible con el bash 3.2 que trae macOS de fábrica (nada de mapfile ni de
# ${arr[@]} sobre arrays vacíos con `set -u`).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT=""
URL=""
SKIP_FIREFOX=0

verde() { printf '\033[32m%s\033[0m\n' "$1"; }
rojo()  { printf '\033[31m%s\033[0m\n' "$1"; }
ambar() { printf '\033[33m%s\033[0m\n' "$1"; }
paso()  { printf '\033[36m── %s\033[0m\n' "$1"; }

uso() {
  # El bloque de comentarios de cabecera ES la ayuda: se imprime hasta la primera
  # linea que no sea comentario. Sin numeros de linea magicos que se pudran.
  awk 'NR>1 && /^#/ { sub(/^#[ ]?/, ""); print; next } NR>1 { exit }' "$0"
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --cert)         CERT="${2:?--cert necesita un fichero}"; shift 2 ;;
    --url)          URL="${2:?--url necesita una dirección}"; shift 2 ;;
    --skip-firefox) SKIP_FIREFOX=1; shift ;;
    -h|--help)      uso 0 ;;
    *) rojo "❌ opción desconocida: $1"; uso 2 ;;
  esac
done

[ "$(uname -s)" = "Darwin" ] || { rojo "❌ este script es para macOS; en Windows use install-ca.ps1"; exit 2; }

echo
echo "  Confianza del certificado de la pasarela — instalación y verificación"
echo "  ---------------------------------------------------------------------"
echo

# ── 1. Elevación ─────────────────────────────────────────────────────────────
# El llavero del SISTEMA (a diferencia del llavero de inicio de sesión) exige root.
# Es exactamente el mismo error que en Windows: instalarlo "sólo para mí" no sirve.
if [ "$(id -u)" -ne 0 ]; then
  paso "el llavero del sistema exige privilegios: re-lanzando con sudo"
  REARGS=()
  if [ -n "$CERT" ]; then REARGS+=(--cert "$CERT"); fi
  if [ -n "$URL" ];  then REARGS+=(--url "$URL"); fi
  if [ "$SKIP_FIREFOX" -eq 1 ]; then REARGS+=(--skip-firefox); fi
  if [ "${#REARGS[@]}" -gt 0 ]; then
    exec sudo "$0" "${REARGS[@]}"
  else
    exec sudo "$0"
  fi
fi

# ── 2. Localizar el certificado ──────────────────────────────────────────────
if [ -z "$CERT" ]; then
  CANDIDATOS=()
  while IFS= read -r f; do
    [ -n "$f" ] && CANDIDATOS+=("$f")
  done < <(find "$HERE" -maxdepth 1 -type f \
             \( -name '*.crt' -o -name '*.cer' -o -name '*.pem' \) | sort)
  if [ "${#CANDIDATOS[@]}" -eq 1 ]; then
    CERT="${CANDIDATOS[0]}"
    paso "certificado detectado junto al script: $(basename "$CERT")"
  elif [ "${#CANDIDATOS[@]}" -eq 0 ]; then
    rojo "❌ no encuentro ningún .crt/.cer/.pem junto al script."
    echo "   Copie aquí la CA raíz que le entregó su proveedor, o use --cert <fichero>."
    exit 2
  else
    rojo "❌ hay varios certificados junto al script; elija con --cert:"
    printf '     %s\n' "${CANDIDATOS[@]}"
    exit 2
  fi
fi
[ -f "$CERT" ] || { rojo "❌ no existe el fichero: $CERT"; exit 2; }
CERT="$(cd "$(dirname "$CERT")" && pwd)/$(basename "$CERT")"

command -v openssl >/dev/null || { rojo "❌ falta openssl (viene de fábrica en macOS)"; exit 2; }
openssl x509 -in "$CERT" -noout >/dev/null 2>&1 \
  || { rojo "❌ el fichero no es un certificado X.509 legible (PEM o DER)"; exit 2; }

SUJETO="$(openssl x509 -in "$CERT" -noout -subject | sed 's/^subject= *//')"
EMISOR="$(openssl x509 -in "$CERT" -noout -issuer  | sed 's/^issuer= *//')"
HASTA="$(openssl x509 -in "$CERT" -noout -enddate  | sed 's/^notAfter=//')"
HUELLA="$(openssl x509 -in "$CERT" -noout -fingerprint -sha256 | sed 's/^.*=//')"

echo "  Certificado a instalar"
echo "    Emitido para : $SUJETO"
echo "    Emitido por  : $EMISOR"
echo "    Válido hasta : $HASTA"
ambar "    SHA-256      : $HUELLA"
echo "    ^ Coteje esa huella con la que le dio su proveedor antes de continuar."
echo

if ! openssl x509 -in "$CERT" -noout -checkend 0 >/dev/null 2>&1; then
  rojo "❌ el certificado ya CADUCÓ ($HASTA): instalarlo no serviría de nada."
  echo "   Pida a su proveedor la CA vigente."
  exit 2
fi

# ── 3. Llavero del SISTEMA (idempotente) ─────────────────────────────────────
LLAVERO=/Library/Keychains/System.keychain
paso "instalando en el llavero del sistema como raíz de confianza"

# `security` identifica los certificados del llavero por su hash SHA-1 (-Z).
HUELLA_SHA1="$(openssl x509 -in "$CERT" -noout -fingerprint -sha1 | sed 's/^.*=//; s/://g')"
if security find-certificate -a -Z "$LLAVERO" 2>/dev/null | grep -qi "SHA-1 hash: $HUELLA_SHA1"; then
  verde "   OK  ya estaba en el llavero del sistema (no se duplica)"
elif security add-trusted-cert -d -r trustRoot -k "$LLAVERO" "$CERT"; then
  verde "   OK  instalado y marcado como raíz de confianza"
else
  rojo "❌ no se pudo instalar en el llavero del sistema."
  echo "   Si la organización gestiona los Mac por MDM, despliegue la CA como perfil"
  echo "   de configuración (payload com.apple.security.root) en lugar de a mano."
  exit 1
fi

# ── 4. Firefox ───────────────────────────────────────────────────────────────
# Firefox trae su propio almacén (NSS) y NO mira el llavero de macOS salvo con la
# directiva empresarial ImportEnterpriseRoots. Se activa igual que en Windows, para
# que el equipo no quede "arreglado" en Safari/Chrome y roto en Firefox.
if [ "$SKIP_FIREFOX" -eq 0 ]; then
  paso "habilitando en Firefox la lectura de las raíces del sistema (ImportEnterpriseRoots)"
  FX_PLIST=/Library/Preferences/org.mozilla.firefox
  if defaults write "$FX_PLIST" EnterprisePoliciesEnabled -bool TRUE 2>/dev/null \
     && defaults write "$FX_PLIST" Certificates -dict-add ImportEnterpriseRoots -bool TRUE 2>/dev/null; then
    chmod 644 "${FX_PLIST}.plist" 2>/dev/null || true
    verde "   OK  habilitado (Firefox debe reiniciarse para tomarlo)"
  else
    ambar "   !!  no se pudo escribir la directiva de Firefox; Safari y Chrome funcionarán igual"
  fi
else
  ambar "   !!  Firefox omitido (--skip-firefox): allí el certificado NO será de confianza"
fi

# ── 5. URL de verificación ───────────────────────────────────────────────────
if [ -z "$URL" ] && [ -f "$HERE/gateway-url.txt" ]; then
  URL="$(head -n1 "$HERE/gateway-url.txt" | tr -d '[:space:]')"
  if [ -n "$URL" ]; then paso "URL de la pasarela leída de gateway-url.txt: $URL"; fi
fi
if [ -z "$URL" ]; then
  printf '  Dirección https de la pasarela (ej. https://192.168.1.50): '
  read -r URL || true
fi
if [ -z "$URL" ]; then
  rojo "❌ sin dirección no puedo verificar: el certificado quedó instalado, pero SIN COMPROBAR."
  echo "   Repita con:  $0 --url https://<direccion-de-la-pasarela>"
  exit 2
fi
case "$URL" in
  https://*) : ;;
  http://*)  rojo "❌ la dirección debe ser https:// (sobre http no hay certificado que verificar)"; exit 2 ;;
  *)         URL="https://$URL" ;;
esac
SIN_ESQUEMA="${URL#https://}"
HOSTPORT="${SIN_ESQUEMA%%/*}"
VHOST="${HOSTPORT%%:*}"
VPORT="${HOSTPORT##*:}"
if [ "$VPORT" = "$HOSTPORT" ]; then VPORT=443; fi

# ── 6. VERIFICACIÓN de verdad ────────────────────────────────────────────────
# Dos pasos, y el que manda es el segundo:
#   (a) handshake TLS contra la pasarela, para traerse la cadena que sirve;
#   (b) `security verify-cert`, que es la evaluación de confianza DEL SISTEMA —
#       la misma que hacen Safari y Chrome. No vale `curl`: el curl que trae
#       macOS valida contra su propio almacén y daría un verde/rojo que no
#       representa al navegador, que es lo que el usuario va a abrir.
paso "verificando con un handshake TLS real contra ${VHOST}:${VPORT}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# SNI sólo con nombre de host: enviar SNI con una IP literal va contra el RFC y
# algunos servidores cierran la conexión.
SNI=(); case "$VHOST" in
  *[!0-9.]*) SNI=(-servername "$VHOST") ;;
esac

set +e
if [ "${#SNI[@]}" -gt 0 ]; then
  openssl s_client -connect "${VHOST}:${VPORT}" "${SNI[@]}" -showcerts \
    </dev/null >"$TMP/s_client.txt" 2>"$TMP/s_client.err"
else
  openssl s_client -connect "${VHOST}:${VPORT}" -showcerts \
    </dev/null >"$TMP/s_client.txt" 2>"$TMP/s_client.err"
fi
RC_SCLIENT=$?
set -e

banner_rojo() {
  echo
  rojo "  ###############################################################"
  rojo "  #                   ROJO — NO VERIFICADO                      #"
  rojo "  ###############################################################"
  echo
  echo "  El certificado se instaló, pero la comprobación contra la pasarela falló."
  echo
  echo "    Etapa   : $1"
  echo "    Destino : ${VHOST}:${VPORT}"
  echo "    Detalle : $2"
  echo
}

if [ "$RC_SCLIENT" -ne 0 ] || ! grep -q 'BEGIN CERTIFICATE' "$TMP/s_client.txt"; then
  banner_rojo "conexión" "$(tail -n 3 "$TMP/s_client.err" | tr '\n' ' ')"
  echo "  Falló la CONEXIÓN, no la confianza. Esto NO es un problema del certificado:"
  echo "    1. Compruebe que la dirección sea la de la pasarela."
  echo "    2. Compruebe que el Mac llegue al servidor:  nc -vz $VHOST $VPORT"
  echo "    3. Compruebe que el cortafuegos de la red no bloquee el puerto $VPORT."
  echo
  echo "  Envíe esta salida completa a su soporte técnico."
  exit 1
fi

# Partir la cadena servida en ficheros sueltos, hoja primero: es el orden en que
# `security verify-cert` espera los -c.
awk -v dir="$TMP" '
  /-----BEGIN CERTIFICATE-----/ { n++; f = sprintf("%s/chain-%02d.pem", dir, n); dentro = 1 }
  dentro { print > f }
  /-----END CERTIFICATE-----/ { dentro = 0 }
' "$TMP/s_client.txt"

CADENA=()
for f in "$TMP"/chain-*.pem; do
  [ -f "$f" ] && CADENA+=(-c "$f")
done
if [ "${#CADENA[@]}" -eq 0 ]; then
  banner_rojo "handshake" "el servidor no envió ningún certificado"
  exit 1
fi

set +e
VERIFY_OUT="$(security verify-cert -p ssl -s "$VHOST" "${CADENA[@]}" 2>&1)"
RC_VERIFY=$?
# Segundo intento SIN nombre: distingue "no confío en la cadena" de "confío pero
# el nombre no coincide" — dos fallos con arreglos muy distintos.
RC_VERIFY_SIN_HOST=0
if [ "$RC_VERIFY" -ne 0 ]; then
  security verify-cert -p ssl "${CADENA[@]}" >/dev/null 2>&1
  RC_VERIFY_SIN_HOST=$?
fi
set -e

if [ "$RC_VERIFY" -ne 0 ] && [ "$RC_VERIFY_SIN_HOST" -eq 0 ]; then
  banner_rojo "nombre" "$(echo "$VERIFY_OUT" | tr '\n' ' ')"
  echo "  La CA SÍ es de confianza (la cadena valida), pero el certificado no está"
  echo "  emitido para «$VHOST»."
  echo "    1. Entre por el nombre o la IP exactos para los que se emitió el"
  echo "       certificado del servidor."
  echo "    2. Si hace falta otro nombre, hay que reemitir el certificado del"
  echo "       servidor: no se arregla en el equipo."
  echo
  echo "  Envíe esta salida completa a su soporte técnico."
  exit 1
fi

if [ "$RC_VERIFY" -ne 0 ]; then
  banner_rojo "validación" "$(echo "$VERIFY_OUT" | tr '\n' ' ')"
  echo "  Falló la VALIDACIÓN del certificado. Compruebe, en este orden:"
  echo "    1. Que la CA instalada sea la de ESTA instalación: coteje la huella"
  echo "       SHA-256 de arriba con la que le dio su proveedor."
  echo "    2. Que el servidor esté sirviendo la cadena completa."
  echo "    3. Que el certificado del servidor no haya caducado."
  echo
  echo "  Envíe esta salida completa a su soporte técnico."
  exit 1
fi

SRV_SUJETO="$(openssl x509 -in "$TMP/chain-01.pem" -noout -subject | sed 's/^subject= *//')"
SRV_EMISOR="$(openssl x509 -in "$TMP/chain-01.pem" -noout -issuer  | sed 's/^issuer= *//')"

echo
verde "  ###############################################################"
verde "  #                    VERDE — TODO CORRECTO                    #"
verde "  ###############################################################"
echo
verde "  El Mac confía en la pasarela: la cadena que sirve $VHOST valida contra el"
verde "  llavero del sistema (la misma evaluación que hacen Safari y Chrome)."
echo
echo "    Certificado del servidor : $SRV_SUJETO"
echo "    Emitido por              : $SRV_EMISOR"
echo "    CA instalada (SHA-256)   : $HUELLA"
echo
echo "  Siguiente paso: abrir $URL en el navegador. No debe aparecer ningún aviso"
echo "  de sitio no seguro. Si Firefox estaba abierto, ciérrelo y vuelva a abrirlo."
exit 0
