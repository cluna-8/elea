#!/usr/bin/env bash
# Kit de confianza del certificado (issue #51): gate del artefacto que se entrega al IT
# del cliente. No podemos correr Windows en el gate, así que verificamos lo que SÍ es
# verificable desde aquí y que, si se rompe, rompe en silencio en la sede del cliente:
#
#   1. El .ps1 PARSEA (parser real de PowerShell, en contenedor). Un error de sintaxis
#      cierra la ventana del usuario sin decir nada.
#   2. El .ps1 tiene BOM UTF-8. Sin BOM, Windows PowerShell 5.1 lee el fichero con la
#      codificación ANSI del sistema y los acentos salen como basura.
#   3. El .bat es ASCII puro. cmd.exe usa la página de códigos OEM: cualquier acento en
#      el .bat sale ilegible en la ventana del usuario.
#   4. Los .sh pasan shellcheck y `bash -n`.
#   5. El kit está completo y bundle.sh lo empaqueta.
#   6. EL PUNTO DE PARADA DE LA HUELLA FUNCIONA, ejecutando los instaladores de verdad
#      contra una CA de prueba. Es la única salvaguarda del kit —cotejar la huella por
#      un canal distinto del que trajo el fichero— y hasta el 2026-07-30 se imprimía
#      pero no se aplicaba: el script decía «coteje ANTES de continuar» y continuaba
#      solo. Un aviso que no detiene nada no es una salvaguarda, así que aquí se
#      comprueba el COMPORTAMIENTO, no que el mensaje esté escrito.
#
# Lo que este check NO cubre (hay que probarlo en una VM Windows real): la elevación UAC,
# la escritura en Cert:\LocalMachine\Root y en el almacén Enterprise, y la directiva de
# Firefox en el registro.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
KIT="$REPO_ROOT/deploy/release/trust-kit"
PWSH_IMG="${PWSH_IMG:-mcr.microsoft.com/powershell:7.4-ubuntu-22.04}"
SHELLCHECK_IMG="${SHELLCHECK_IMG:-koalaman/shellcheck:stable}"

fail() { echo "❌ trust-kit: $1"; exit 1; }

# ── Imágenes de terceros: esto es un GATE, no un "si acaso" ──────────────────
# Hasta 2026-07-30 los pasos con contenedor se OMITÍAN con un warning cuando la
# imagen no estaba en local, y el check daba verde igual: en un host fresco de
# CI/release el gate pasaba sin haber parseado NUNCA el install-ca.ps1, que es
# exactamente lo que este check existe para impedir. Un gate que se auto-desactiva
# no es un gate.
# Este check corre en el host de build (con red), no en la caja air-gapped del
# cliente: si la imagen falta se trae, y si no se puede traer, ROJO.
#   $1 = imagen, $2 = plataforma (opcional; vacío = la nativa del host)
ensure_image() {
    local img="$1" platform="${2:-}"
    docker image inspect "$img" >/dev/null 2>&1 && return 0
    local args
    args=(pull)
    [ -n "$platform" ] && args+=(--platform "$platform")
    args+=("$img")
    echo "   $img no está en local — docker ${args[*]}"
    docker "${args[@]}" --quiet >/dev/null && return 0
    fail "no se pudo traer $img (¿sin red? ¿rate limit del registry?) y sin ella la
   validación no se ejecuta — este check NO da verde sin correrla.
   Traerla a mano en un host con red y reintentar:  docker ${args[*]}
   (o apuntar a un mirror interno exportando PWSH_IMG / SHELLCHECK_IMG)"
}

# ── 1. Completitud ───────────────────────────────────────────────────────────
for f in install-ca.ps1 install-ca.bat install-ca-macos.sh export-ca.sh; do
    [ -f "$KIT/$f" ] || fail "falta $f"
done
for f in install-ca-macos.sh export-ca.sh; do
    [ -x "$KIT/$f" ] || fail "$f no es ejecutable"
done

# ── 2. Codificación (los dos fallos silenciosos de Windows) ──────────────────
head -c 3 "$KIT/install-ca.ps1" | cmp -s - <(printf '\xef\xbb\xbf') \
    || fail "install-ca.ps1 sin BOM UTF-8 (PowerShell 5.1 destroza los acentos)"
# `grep -P` no existe en el grep de BSD/macOS y ahí el check pasaría en falso: con tr
# es portable — cuenta los bytes que NO son ASCII.
NO_ASCII="$(LC_ALL=C tr -d '\000-\177' < "$KIT/install-ca.bat" | wc -c | tr -d ' ')"
[ "$NO_ASCII" -eq 0 ] \
    || fail "install-ca.bat tiene $NO_ASCII bytes no-ASCII (cmd.exe los muestra ilegibles)"

# ── 3. Sintaxis de los .sh ───────────────────────────────────────────────────
bash -n "$KIT/install-ca-macos.sh" || fail "install-ca-macos.sh no parsea"
bash -n "$KIT/export-ca.sh"        || fail "export-ca.sh no parsea"

ensure_image "$SHELLCHECK_IMG"
docker run --rm -v "$KIT":/mnt:ro "$SHELLCHECK_IMG" --shell=bash --severity=style \
    install-ca-macos.sh export-ca.sh || fail "shellcheck encontró hallazgos"
echo "   shellcheck: limpio"

# ── 4. Parseo real del .ps1 ──────────────────────────────────────────────────
ensure_image "$PWSH_IMG" linux/amd64
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/parse.ps1" <<'PS'
$errores = $null; $tokens = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    '/kit/install-ca.ps1', [ref]$tokens, [ref]$errores)
if ($errores.Count -gt 0) {
    foreach ($e in $errores) { Write-Host ("  linea {0}: {1}" -f $e.Extent.StartLineNumber, $e.Message) }
    exit 1
}
Write-Host "   parser de PowerShell: 0 errores de sintaxis"
PS
docker run --rm --platform linux/amd64 -v "$KIT":/kit:ro -v "$tmp":/t:ro \
    "$PWSH_IMG" pwsh -NoProfile -File /t/parse.ps1 || fail "install-ca.ps1 NO parsea"

# ── 5. Punto de parada de la huella: COMPORTAMIENTO, no mensajes ─────────────
# Se ejecutan los dos instaladores de verdad contra una CA de prueba generada aquí.
command -v openssl >/dev/null \
    || fail "falta openssl, y sin él no hay CA de prueba con la que ejercitar el punto de parada"

fixture="$tmp/fixture"; mkdir -p "$fixture"
openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$fixture/ca.key" -out "$fixture/root.crt" -days 30 \
    -subj "/CN=Trust Kit Gate Test CA" \
    -addext "basicConstraints=critical,CA:TRUE" >/dev/null 2>&1 \
    || fail "no se pudo generar la CA de prueba con openssl"
HUELLA_OK="$(openssl x509 -in "$fixture/root.crt" -noout -fingerprint -sha256 \
             | sed 's/^.*=//' | tr -d ':' | tr '[:lower:]' '[:upper:]')"
HUELLA_MALA="$(printf '%064d' 0)"

# ── 5a. install-ca.ps1, en el contenedor de PowerShell ───────────────────────
# UN solo retoque sobre la copia que se ejecuta: Test-IsAdministrator llama a
# WindowsIdentity::GetCurrent(), que en Linux lanza PlatformNotSupportedException y
# tumbaría el script antes de llegar a nada. Se fuerza a $true. Todo lo demás —enlace
# de parámetros, normalización de la huella, comparación, pregunta, códigos de salida
# y el ORDEN respecto de la escritura en el almacén— es el fichero que se entrega.
tr -d '\r' < "$KIT/install-ca.ps1" \
    | sed 's/^function Test-IsAdministrator {/function Test-IsAdministrator {\n    return $true  # SHIM DEL GATE: en Linux no hay WindowsIdentity/' \
    > "$fixture/install-ca.ps1"
grep -q 'SHIM DEL GATE' "$fixture/install-ca.ps1" \
    || fail "el shim de Test-IsAdministrator no se aplicó: ¿cambió la firma de la función en install-ca.ps1?"

# En Linux, Cert:\LocalMachine\Root es de sólo lectura ("Unix LocalMachine X509Stores
# are read-only"), así que el intento de escritura falla SIEMPRE con código 1 y un
# mensaje que menciona LocalMachine. Eso lo convierte en un marcador exacto y sin
# acentos de "el script llegó a tocar el almacén":
#   rc=1 + 'LocalMachine' en la salida  →  pasó el punto de parada
#   rc=4 y ni rastro de 'LocalMachine'  →  se plantó antes, que es lo que se exige
cat > "$tmp/comportamiento.ps1" <<'PS'
$ErrorActionPreference = 'Continue'
$instalador = '/fix/install-ca.ps1'
$cert       = '/fix/root.crt'
$global:fallos = 0

function Invoke-Caso {
    param([string]$Titulo, [string]$Entrada, [string[]]$Argumentos,
          [bool]$DebeTocarAlmacen, [int]$Codigo)

    if ($Entrada) {
        $salida = ($Entrada | & pwsh -NoProfile -File $instalador @Argumentos 2>&1 | Out-String)
    } else {
        $salida = (& pwsh -NoProfile -File $instalador @Argumentos 2>&1 | Out-String)
    }
    $rc = $LASTEXITCODE
    $tocoAlmacen = [bool]($salida -match 'LocalMachine')

    if (($rc -eq $Codigo) -and ($tocoAlmacen -eq $DebeTocarAlmacen)) {
        Write-Host ("   OK  {0}" -f $Titulo)
        return
    }
    Write-Host ("   XX  {0}" -f $Titulo)
    Write-Host ("       esperaba rc={0} y tocarAlmacen={1}; obtuve rc={2} y tocarAlmacen={3}" -f
        $Codigo, $DebeTocarAlmacen, $rc, $tocoAlmacen)
    $salida -split "`n" | Select-Object -Last 12 | ForEach-Object { Write-Host "       | $_" }
    $global:fallos++
}

$buena = $env:HUELLA_OK
$mala  = $env:HUELLA_MALA
$comu  = @('-CertPath', $cert, '-SkipFirefox', '-Url', 'https://127.0.0.1:1')

# (a) desatendido con la huella correcta: procede sin preguntar nada — la vía GPO.
Invoke-Caso 'huella correcta por -Fingerprint (desatendido): instala' `
    '' ($comu + @('-NoPause', '-Fingerprint', $buena)) $true 1

# (b) desatendido con huella equivocada: se planta, y no por casualidad.
Invoke-Caso 'huella EQUIVOCADA por -Fingerprint: aborta sin tocar el almacén' `
    '' ($comu + @('-NoPause', '-Fingerprint', $mala)) $false 4

# (c) interactivo contestando que no: el caso del hallazgo.
Invoke-Caso 'interactivo respondiendo "no": aborta sin tocar el almacén' `
    "no`n" $comu $false 4

# (d) todo lo que no sea un sí explícito cancela: el default es No.
Invoke-Caso 'interactivo respondiendo INTRO a secas: aborta (default = No)' `
    "`n" $comu $false 4

# (e) el agujero de raíz: desatendido sin huella NO puede instalar a ciegas.
#     -NoPause era el switch documentado para GPO; si dejara pasar, el modo que más
#     máquinas toca sería justo el que no comprueba nada.
Invoke-Caso '-NoPause sin huella: aborta y NO se cuela como bypass' `
    '' ($comu + @('-NoPause')) $false 4

# (f) la salida explícita sigue existiendo, o el operador acabaría buscando otra peor.
Invoke-Caso '-AcceptFingerprint: instala a propósito, sin preguntar' `
    '' ($comu + @('-NoPause', '-AcceptFingerprint')) $true 1

# (g) el IT pega la huella como se la dieron: minúsculas, con ':' y con espacios.
$comoLaPegan = ' ' + ((([regex]::Matches($buena, '..') | ForEach-Object { $_.Value }) -join ':').ToLowerInvariant()) + ' '
Invoke-Caso 'huella en minúsculas y con ":" (como la pega el IT): instala' `
    '' ($comu + @('-NoPause', '-Fingerprint', $comoLaPegan)) $true 1

# (h) una huella que no es un SHA-256 es un error de entrada, no un "pues instalo".
Invoke-Caso 'huella truncada al copiarla: error de entrada, no instala' `
    '' ($comu + @('-NoPause', '-Fingerprint', 'AB:CD:EF')) $false 2

# (i) interactivo contestando que sí: la confirmación no está clavada en "no".
Invoke-Caso 'interactivo respondiendo "si": instala' `
    "si`n" $comu $true 1

if ($global:fallos -gt 0) {
    Write-Host ("   {0} caso(s) del punto de parada fallaron" -f $global:fallos)
    exit 1
}
Write-Host '   punto de parada de la huella (install-ca.ps1): 9/9 casos'
PS
docker run --rm --platform linux/amd64 \
    -e HUELLA_OK="$HUELLA_OK" -e HUELLA_MALA="$HUELLA_MALA" \
    -v "$fixture":/fix:ro -v "$tmp":/t:ro \
    "$PWSH_IMG" pwsh -NoProfile -File /t/comportamiento.ps1 \
    || fail "install-ca.ps1 instala la CA sin la huella verificada — el punto de parada NO protege"

# ── 5b. install-ca-macos.sh, aquí mismo ──────────────────────────────────────
# Corre en el host, sin contenedor y sin root, con dos programas falsos por delante en
# el PATH: `uname` (para que el script se crea en un Mac también cuando el gate corre
# en Linux) y `sudo` (que sólo deja constancia de que lo llamaron, en vez de escalar de
# verdad). El punto de parada está ANTES de la elevación justamente para esto: si el
# script llega a invocar sudo, es que decidió instalar.
command -v python3 >/dev/null \
    || fail "falta python3, y sin él no se puede simular la terminal del operador"

fake="$tmp/fakebin"; mkdir -p "$fake"
UNAME_REAL="$(command -v uname)"
printf '#!/bin/sh\nif [ "$1" = "-s" ]; then echo Darwin; else exec %s "$@"; fi\n' "$UNAME_REAL" > "$fake/uname"
printf '#!/bin/sh\necho "SUDO-INVOCADO $*" >> "$SUDO_TESTIGO"\nexit 0\n' > "$fake/sudo"
chmod +x "$fake/uname" "$fake/sudo"

# El script distingue «hay una persona delante» con `[ -t 0 ]`, así que las respuestas
# del operador no se pueden simular con una tubería: haría falso el caso interactivo y
# probaríamos la rama equivocada. Este ayudante le da una terminal de verdad (pty) y
# escribe la respuesta en ella. El alarm(60) es para que un cuelgue rompa el gate en
# vez de dejarlo colgado.
cat > "$tmp/con_terminal.py" <<'PY'
import os, pty, signal, sys
signal.alarm(60)
respuesta = (sys.argv[1] + "\n").encode()
enviado = [False]
def del_hijo(fd):
    return os.read(fd, 4096)
def hacia_el_hijo(fd):
    if enviado[0]:
        return b""
    enviado[0] = True
    return respuesta
sys.exit(os.waitstatus_to_exitcode(pty.spawn(sys.argv[2:], del_hijo, hacia_el_hijo)))
PY

macos_caso() {
    # $1 titulo · $2 eleva? (si/no) · $3 código esperado · $4 respuesta en terminal
    # ('-' = sin terminal, stdin desde /dev/null) · resto: argumentos del instalador
    local titulo="$1" espera="$2" codigo="$3" respuesta="$4"; shift 4
    local testigo="$tmp/testigo.txt"
    : > "$testigo"
    local salida rc
    set +e
    if [ "$respuesta" = "-" ]; then
        salida="$(PATH="$fake:$PATH" SUDO_TESTIGO="$testigo" \
            "$KIT/install-ca-macos.sh" --cert "$fixture/root.crt" "$@" </dev/null 2>&1)"
    else
        salida="$(PATH="$fake:$PATH" SUDO_TESTIGO="$testigo" \
            python3 "$tmp/con_terminal.py" "$respuesta" \
            "$KIT/install-ca-macos.sh" --cert "$fixture/root.crt" "$@" </dev/null 2>&1)"
    fi
    rc=$?
    set -e
    local elevo="no"
    grep -q 'SUDO-INVOCADO' "$testigo" && elevo="si"
    if [ "$rc" = "$codigo" ] && [ "$elevo" = "$espera" ]; then
        echo "   OK  $titulo"
    else
        echo "   XX  $titulo"
        echo "       esperaba rc=$codigo y elevar=$espera; obtuve rc=$rc y elevar=$elevo"
        printf '       | %s\n' "$(echo "$salida" | tail -n 8)"
        MACOS_FALLOS=$((MACOS_FALLOS + 1))
    fi
}

MACOS_FALLOS=0
HUELLA_MINUS="$(echo "$HUELLA_OK" | tr '[:upper:]' '[:lower:]')"
macos_caso 'huella correcta por --fingerprint: procede a instalar' si 0 - \
    --fingerprint "$HUELLA_OK"
macos_caso 'huella en minúsculas (como la pega el IT): procede' si 0 - \
    --fingerprint "$HUELLA_MINUS"
macos_caso 'huella EQUIVOCADA: aborta sin elevar ni instalar' no 4 - \
    --fingerprint "$HUELLA_MALA"
macos_caso 'huella truncada al copiarla: error de entrada' no 2 - \
    --fingerprint 'AB:CD:EF'
macos_caso 'sin terminal y sin --fingerprint: aborta, no instala a ciegas' no 4 -
macos_caso '--accept-fingerprint: procede a propósito' si 0 - --accept-fingerprint
macos_caso 'interactivo respondiendo "no": aborta sin elevar' no 4 'no'
macos_caso 'interactivo respondiendo INTRO a secas: aborta (default = No)' no 4 ''
macos_caso 'interactivo respondiendo "si": procede a instalar' si 0 'si'
[ "$MACOS_FALLOS" -eq 0 ] \
    || fail "install-ca-macos.sh instala la CA sin la huella verificada ($MACOS_FALLOS caso/s)"
echo "   punto de parada de la huella (install-ca-macos.sh): 9/9 casos"

# ── 6. El bundle se lo lleva ─────────────────────────────────────────────────
grep -q 'trust-kit' "$REPO_ROOT/deploy/release/bundle.sh" \
    || fail "bundle.sh no empaqueta el trust-kit (en la sede no hay repo del que sacarlo)"

echo "✅ trust-kit OK: kit completo, .ps1 parsea y con BOM, .bat ASCII, .sh limpios, va en el bundle"
