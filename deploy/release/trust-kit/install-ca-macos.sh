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
# Antes de tocar el llavero SE DETIENE a que la huella SHA-256 de la CA quede
# verificada. Instalar una raíz en el llavero del sistema hace que ese Mac acepte
# cualquier certificado que ella firme, para todas las apps; si el fichero que
# llegó no es el de esta instalación, no hay ningún síntoma visible. Cotejar la
# huella por un canal distinto del que trajo el fichero es la única salvaguarda
# del kit, así que no se puede saltar por descuido.
#
# Uso:
#   ./install-ca-macos.sh --cert root.crt --url https://192.168.1.50
#   ./install-ca-macos.sh                    # autodetecta el .crt y lee gateway-url.txt
#
# Opciones:
#   --cert <fichero>       CA raíz (.crt/.cer/.pem). Default: el único que haya al lado.
#   --url  <url>           URL https de la pasarela para verificar. Default: gateway-url.txt.
#   --fingerprint <huella> Huella SHA-256 ESPERADA. Si no coincide, aborta (4) sin
#                          preguntar ni instalar. Es la forma correcta de desplegar
#                          desatendido (MDM, script de flota). Se acepta con ':' o
#                          sin él, en mayúsculas o minúsculas.
#   --accept-fingerprint   Salta la confirmación a propósito. SÓLO si ya cotejó la
#                          huella por otro medio.
#   --skip-firefox         No toca la directiva de Firefox.
#   -h | --help            Esta ayuda.
#
# Salidas: 0 = verde · 1 = la verificación falló · 2 = error de entrada ·
#          4 = huella no verificada (no coincide, cancelada, o sin terminal donde
#              preguntar y sin --fingerprint): NO se instaló nada.
#
# Compatible con el bash 3.2 que trae macOS de fábrica (nada de mapfile ni de
# ${arr[@]} sobre arrays vacíos con `set -u`).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT=""
URL=""
SKIP_FIREFOX=0
HUELLA_ESPERADA=""
ACEPTAR_HUELLA=0

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
    --cert)               CERT="${2:?--cert necesita un fichero}"; shift 2 ;;
    --url)                URL="${2:?--url necesita una dirección}"; shift 2 ;;
    --fingerprint)        HUELLA_ESPERADA="${2:?--fingerprint necesita una huella}"; shift 2 ;;
    --accept-fingerprint) ACEPTAR_HUELLA=1; shift ;;
    --skip-firefox)       SKIP_FIREFOX=1; shift ;;
    -h|--help)            uso 0 ;;
    *) rojo "❌ opción desconocida: $1"; uso 2 ;;
  esac
done

# El IT pega la huella tal como se la dieron: del navegador con ':', de openssl en
# mayúsculas, de un correo a veces en minúsculas. Comparar en crudo haría fallar una
# huella correcta, y una comparación que falla por formato acaba en alguien usando
# --accept-fingerprint «porque no funciona». Se normaliza a hex en mayúsculas.
normalizar_huella() {
  printf '%s' "$1" | tr -d '\n' | tr -cd '0-9A-Fa-f' | tr '[:lower:]' '[:upper:]'
}

if [ -n "$HUELLA_ESPERADA" ]; then
  HUELLA_ESPERADA="$(normalizar_huella "$HUELLA_ESPERADA")"
  if [ "${#HUELLA_ESPERADA}" -ne 64 ]; then
    rojo "❌ --fingerprint no es un SHA-256: leí ${#HUELLA_ESPERADA} dígitos hexadecimales, hacen falta 64."
    echo "   Se acepta con ':' o sin él, en mayúsculas o minúsculas; lo que no vale es una"
    echo "   huella SHA-1 (40 dígitos) ni una huella cortada al copiarla."
    exit 2
  fi
fi

[ "$(uname -s)" = "Darwin" ] || { rojo "❌ este script es para macOS; en Windows use install-ca.ps1"; exit 2; }

echo
echo "  Confianza del certificado de la pasarela — instalación y verificación"
echo "  ---------------------------------------------------------------------"
echo

# ── 1. Localizar el certificado ──────────────────────────────────────────────
# Leer el fichero y sacarle la huella NO necesita root, así que va antes de pedir
# la contraseña: el operador coteja la huella —y cancela si no cuadra— en su
# propia terminal, sin haber escalado privilegios para nada.
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
echo

if ! openssl x509 -in "$CERT" -noout -checkend 0 >/dev/null 2>&1; then
  rojo "❌ el certificado ya CADUCÓ ($HASTA): instalarlo no serviría de nada."
  echo "   Pida a su proveedor la CA vigente."
  exit 2
fi

# ── 2. PUNTO DE PARADA: la huella se verifica ANTES de escalar y de instalar ──
# Nada de lo que hay debajo ocurre sin una de estas tres cosas: huella esperada
# que coincide, confirmación de una persona, o renuncia explícita.
HUELLA_REAL="$(normalizar_huella "$HUELLA")"

if [ -n "$HUELLA_ESPERADA" ]; then
  if [ "$HUELLA_ESPERADA" != "$HUELLA_REAL" ]; then
    rojo "❌ LA HUELLA NO COINCIDE. No se ha instalado nada."
    echo
    echo "   Esperada    : $HUELLA_ESPERADA"
    echo "   Del fichero : $HUELLA_REAL"
    echo
    ambar "   El fichero que hay en este Mac NO es la CA que usted espera. Puede ser el"
    ambar "   certificado de otra instalación, una copia vieja, o un fichero alterado por"
    ambar "   el camino. No lo instale: pida a su proveedor que le reenvíe la CA y vuelva"
    ambar "   a cotejar la huella por teléfono."
    exit 4
  fi
  verde "   OK  huella verificada: coincide con la esperada (--fingerprint)"
elif [ "$ACEPTAR_HUELLA" -eq 1 ]; then
  ambar "   !!  confirmación omitida a propósito (--accept-fingerprint): se instala sin cotejar la huella."
elif [ ! -t 0 ]; then
  # Sin terminal no hay a quién preguntar (MDM, cron, `| bash`): la respuesta
  # segura es NO. Quien despliega desatendido tiene --fingerprint para eso.
  rojo "❌ no hay terminal donde confirmar la huella y no se pasó --fingerprint: no se instala nada."
  echo
  echo "   Instalar una CA en el llavero del sistema hace que este Mac acepte cualquier"
  echo "   certificado que ella firme. Sin nadie delante que coteje la huella, la única"
  echo "   forma de que eso sea seguro es decirle al script cuál espera:"
  echo
  echo "     --fingerprint <huella SHA-256 que le dio su proveedor>"
  echo
  echo "   Si ya la cotejó por otro medio y asume la responsabilidad, --accept-fingerprint."
  exit 4
else
  echo "  ¿Coincide esa huella, carácter a carácter, con la que le dio su proveedor por"
  echo "  teléfono (o por el canal que sea, distinto del que trajo el fichero)?"
  echo
  echo "  Si NO coincide, o no tiene con qué compararla, conteste que no: instalar esta"
  echo "  CA hace que el Mac acepte todo lo que ella firme."
  echo
  printf '  Escriba SI para instalar (cualquier otra cosa cancela) [s/N]: '
  RESPUESTA=""
  read -r RESPUESTA || RESPUESTA=""
  case "$(printf '%s' "$RESPUESTA" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')" in
    s|si|sí|y|yes) verde "   OK  huella confirmada por el operador" ;;
    *)
      rojo "❌ cancelado: NO se ha instalado nada, el llavero queda como estaba."
      echo "   Si la huella no coincidía, avise a su proveedor antes de repetir."
      exit 4
      ;;
  esac
fi

# ── 3. Elevación ─────────────────────────────────────────────────────────────
# El llavero del SISTEMA (a diferencia del llavero de inicio de sesión) exige root.
# Es exactamente el mismo error que en Windows: instalarlo "sólo para mí" no sirve.
if [ "$(id -u)" -ne 0 ]; then
  paso "el llavero del sistema exige privilegios: re-lanzando con sudo"
  # La huella REAL viaja a la instancia con privilegios, que la vuelve a comparar
  # contra el fichero. Así el proceso que escribe en el llavero tiene su propia
  # comprobación —no hereda una confirmación de palabra— y un cambio del fichero
  # entre las dos lecturas se cazaría en la segunda.
  REARGS=(--cert "$CERT" --fingerprint "$HUELLA_REAL")
  if [ -n "$URL" ]; then REARGS+=(--url "$URL"); fi
  if [ "$SKIP_FIREFOX" -eq 1 ]; then REARGS+=(--skip-firefox); fi
  exec sudo "$0" "${REARGS[@]}"
fi

# ── 4. Llavero del SISTEMA (idempotente) ─────────────────────────────────────
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

# ── 5. Firefox ───────────────────────────────────────────────────────────────
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

# ── 6. URL de verificación ───────────────────────────────────────────────────
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

# ── 7. VERIFICACIÓN de verdad ────────────────────────────────────────────────
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
