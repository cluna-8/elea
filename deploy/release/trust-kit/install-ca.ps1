#Requires -Version 5.1
<#
.SYNOPSIS
    Instala la CA raíz interna de la pasarela en el almacén de MÁQUINA de Windows
    y VERIFICA el resultado con un handshake TLS real.

.DESCRIPTION
    Nace del piloto del 30-jul-2026 (issue #51): el IT del cliente hizo doble-click
    sobre el .crt y el asistente de Windows lo instaló, por defecto, en el almacén
    del USUARIO ACTUAL — no en «Entidades de certificación raíz de confianza» de la
    MÁQUINA LOCAL. El navegador siguió mostrando el aviso de sitio no seguro y no
    hubo ni un mensaje de error que lo explicara.

    Este script hace lo que el asistente no hace:
      1. Se auto-eleva a administrador (el almacén de máquina lo exige).
      2. Importa la CA en Cert:\LocalMachine\Root — equivalente exacto de
         `certutil -addstore -f Root <fichero>`.
      3. Opcionalmente (-EnterpriseStore) la importa también en el almacén
         «Enterprise» (HKLM\...\EnterpriseCertificates\Root).
      4. Habilita en Firefox la directiva ImportEnterpriseRoots, porque Firefox NO
         usa el almacén de Windows salvo que esa directiva esté puesta.
      5. VERIFICA de verdad: abre una conexión TLS contra la URL de la pasarela y
         valida la cadena con el almacén del sistema. VERDE o ROJO, sin ambigüedad.

    Es idempotente: correrlo dos veces no duplica el certificado ni rompe nada.

.PARAMETER CertPath
    Fichero de la CA raíz (.crt/.cer/.pem). Si se omite, se busca un único
    fichero de certificado junto al script.

.PARAMETER Url
    URL https de la pasarela contra la que se verifica el handshake, por ejemplo
    https://192.168.1.50 o https://pasarela.miorganizacion.local
    Si se omite, se lee de `gateway-url.txt` junto al script; si tampoco existe,
    se pregunta por pantalla.

.PARAMETER EnterpriseStore
    Además del almacén Root de la máquina, importa en el almacén Enterprise.
    APAGADO por defecto: en un dominio, ese almacén es territorio de las
    directivas de grupo y un certificado puesto a mano ahí confunde a quien
    audite el dominio. Úselo sólo si su navegador/aplicación lo exige.

.PARAMETER SkipFirefox
    No toca la directiva de Firefox.

.PARAMETER NoPause
    No espera una tecla al terminar (para despliegue desatendido / GPO).

.PARAMETER Elevated
    Uso interno: marca la re-ejecución ya elevada. No lo use a mano.

.EXAMPLE
    .\install-ca.ps1 -CertPath .\root.crt -Url https://192.168.1.50

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\install-ca.ps1 -NoPause

.NOTES
    Este fichero se guarda en UTF-8 CON BOM a propósito: Windows PowerShell 5.1
    interpreta un .ps1 sin BOM con la codificación ANSI del sistema y destroza
    los acentos de los mensajes.
    Códigos de salida: 0 = verde · 1 = la verificación TLS falló ·
    2 = error de entrada (falta el certificado / URL) · 3 = no se pudo elevar.
#>
[CmdletBinding()]
param(
    [string]$CertPath,
    [string]$Url,
    [switch]$EnterpriseStore,
    [switch]$SkipFirefox,
    [switch]$NoPause,
    [switch]$Elevated
)

$ErrorActionPreference = 'Stop'

# ── Utilidades de salida ──────────────────────────────────────────────────────
function Write-Step  { param([string]$m) Write-Host "── $m" -ForegroundColor Cyan }
function Write-Ok    { param([string]$m) Write-Host "   OK  $m" -ForegroundColor Green }
function Write-Warn2 { param([string]$m) Write-Host "   !!  $m" -ForegroundColor Yellow }
function Write-Bad   { param([string]$m) Write-Host "   XX  $m" -ForegroundColor Red }

function Exit-Script {
    param([int]$Code)
    if (-not $NoPause) {
        Write-Host ""
        Write-Host "Pulse INTRO para cerrar esta ventana..." -ForegroundColor DarkGray
        try { [void](Read-Host) } catch { }
    }
    exit $Code
}

$ScriptPath = $PSCommandPath
if (-not $ScriptPath) { $ScriptPath = $MyInvocation.MyCommand.Definition }
$ScriptDir = Split-Path -Parent $ScriptPath

# La ruta se resuelve ANTES de elevar: el proceso elevado arranca en System32 y una
# ruta relativa dejaría de existir para él.
if ($CertPath -and (Test-Path -LiteralPath $CertPath)) {
    $CertPath = (Resolve-Path -LiteralPath $CertPath).ProviderPath
}

Write-Host ""
Write-Host "  Confianza del certificado de la pasarela — instalación y verificación" -ForegroundColor White
Write-Host "  ---------------------------------------------------------------------" -ForegroundColor DarkGray
Write-Host ""

# ── 1. Auto-elevación ─────────────────────────────────────────────────────────
function Test-IsAdministrator {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator)) {
    if ($Elevated) {
        Write-Bad "la re-ejecución sigue sin permisos de administrador."
        Write-Host "     Inicie sesión con una cuenta administradora del equipo y repita." -ForegroundColor DarkGray
        Exit-Script 3
    }
    Write-Step "sin permisos de administrador: pidiendo elevación (aparecerá el aviso de Windows)"

    # El host actual puede ser powershell.exe (5.1) o pwsh.exe (7+): reusamos el mismo.
    $hostExe = $null
    try { $hostExe = (Get-Process -Id $PID).Path } catch { }
    if (-not $hostExe) { $hostExe = Join-Path $PSHOME 'powershell.exe' }

    # Start-Process NO entrecomilla por su cuenta: las rutas se citan a mano.
    $argLine = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', ('"{0}"' -f $ScriptPath),
        '-Elevated'
    )
    if ($CertPath)        { $argLine += @('-CertPath', ('"{0}"' -f $CertPath)) }
    if ($Url)             { $argLine += @('-Url',      ('"{0}"' -f $Url)) }
    if ($EnterpriseStore) { $argLine += '-EnterpriseStore' }
    if ($SkipFirefox)     { $argLine += '-SkipFirefox' }
    if ($NoPause)         { $argLine += '-NoPause' }

    try {
        $proc = Start-Process -FilePath $hostExe -ArgumentList ($argLine -join ' ') `
                              -Verb RunAs -Wait -PassThru
    } catch {
        Write-Bad "elevación cancelada o denegada: $($_.Exception.Message)"
        Write-Host "     El almacén de la MÁQUINA sólo se puede modificar como administrador." -ForegroundColor DarkGray
        Write-Host "     Pida a un administrador del equipo que ejecute este mismo fichero." -ForegroundColor DarkGray
        Exit-Script 3
    }
    Write-Host ""
    Write-Host "  (la instalación se ejecutó en la ventana de administrador)" -ForegroundColor DarkGray
    exit $proc.ExitCode
}
Write-Ok "ejecutando como administrador"

# ── 2. Localizar el certificado ───────────────────────────────────────────────
if (-not $CertPath) {
    # -Include sólo filtra si la ruta termina en comodín (gotcha clásico de Get-ChildItem).
    $candidatos = @(Get-ChildItem -Path (Join-Path $ScriptDir '*') -File `
                                  -Include '*.crt', '*.cer', '*.pem' -ErrorAction SilentlyContinue)
    if ($candidatos.Count -eq 1) {
        $CertPath = $candidatos[0].FullName
        Write-Step "certificado detectado junto al script: $($candidatos[0].Name)"
    } elseif ($candidatos.Count -eq 0) {
        Write-Bad "no encuentro ningún .crt/.cer/.pem junto al script."
        Write-Host "     Copie aquí el fichero de la CA raíz que le entregó su proveedor," -ForegroundColor DarkGray
        Write-Host "     o indíquelo con:  -CertPath C:\ruta\root.crt" -ForegroundColor DarkGray
        Exit-Script 2
    } else {
        Write-Bad "hay varios certificados junto al script; indique cuál con -CertPath:"
        $candidatos | ForEach-Object { Write-Host "       $($_.Name)" -ForegroundColor DarkGray }
        Exit-Script 2
    }
}

if (-not (Test-Path -LiteralPath $CertPath)) {
    Write-Bad "no existe el fichero de certificado: $CertPath"
    Exit-Script 2
}
$CertFull = (Resolve-Path -LiteralPath $CertPath).ProviderPath

# Constructor, NO $cert.Import(): X509Certificate2.Import() está marcado obsoleto y
# lanza "X509Certificate is immutable on this platform" en .NET moderno (PowerShell 7.5+).
# El constructor funciona igual en Windows PowerShell 5.1 y en PowerShell 7.
try {
    $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($CertFull)
} catch {
    Write-Bad "el fichero no es un certificado válido (.crt/.cer/.pem): $($_.Exception.Message)"
    Exit-Script 2
}

# Huella SHA-256 en el formato que muestran los navegadores, para cotejar por teléfono.
$sha256 = [System.Security.Cryptography.SHA256]::Create()
$huella = (($sha256.ComputeHash($cert.RawData)) | ForEach-Object { $_.ToString('X2') }) -join ':'

Write-Host ""
Write-Host "  Certificado a instalar" -ForegroundColor White
Write-Host "    Emitido para : $($cert.Subject)"
Write-Host "    Emitido por  : $($cert.Issuer)"
Write-Host "    Validez      : $($cert.NotBefore.ToString('yyyy-MM-dd')) → $($cert.NotAfter.ToString('yyyy-MM-dd'))"
Write-Host "    SHA-256      : $huella" -ForegroundColor Yellow
Write-Host ""
Write-Host "    ^ Coteje esa huella con la que le dio su proveedor ANTES de continuar." -ForegroundColor DarkGray
Write-Host ""

# Cordura: que sea de verdad una CA raíz y que no esté caducada.
$esRaiz = ($cert.Subject -eq $cert.Issuer)
$esCa = $false
$bcExt = $cert.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.19' } | Select-Object -First 1
if ($bcExt) {
    $bc = $bcExt -as [System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]
    if ($bc) { $esCa = $bc.CertificateAuthority }
}
if (-not $esCa)  { Write-Warn2 "el certificado no se declara autoridad de certificación (¿es el fichero correcto?)" }
if (-not $esRaiz) { Write-Warn2 "el certificado no es auto-firmado: parece intermedio, no raíz" }
if ($cert.NotAfter -lt (Get-Date)) {
    Write-Bad "el certificado CADUCÓ el $($cert.NotAfter.ToString('yyyy-MM-dd')): instalarlo no va a servir de nada."
    Write-Host "     Pida a su proveedor la CA vigente." -ForegroundColor DarkGray
    Exit-Script 2
}

# ── 3. Almacén de MÁQUINA (el paso que el doble-click no hace) ────────────────
Write-Step "instalando en «Entidades de certificación raíz de confianza» de la MÁQUINA LOCAL"
try {
    $store = New-Object System.Security.Cryptography.X509Certificates.X509Store('Root', 'LocalMachine')
    $store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
    $yaEsta = $store.Certificates.Find(
        [System.Security.Cryptography.X509Certificates.X509FindType]::FindByThumbprint,
        $cert.Thumbprint, $false)
    if ($yaEsta.Count -gt 0) {
        Write-Ok "ya estaba instalado (no se duplica) — Cert:\LocalMachine\Root"
    } else {
        $store.Add($cert)
        Write-Ok "instalado — Cert:\LocalMachine\Root"
    }
    $store.Close()
} catch {
    Write-Bad "no se pudo escribir en el almacén de la máquina: $($_.Exception.Message)"
    Exit-Script 1
}

# ── 3b. Almacén Enterprise (opcional) ─────────────────────────────────────────
if ($EnterpriseStore) {
    Write-Step "instalando también en el almacén Enterprise (-EnterpriseStore)"
    # certutil está en todo Windows; -f hace la operación idempotente (sobrescribe).
    # EAP en 'Continue' a propósito: con 'Stop', el stderr de un comando nativo
    # redirigido con 2>&1 se convierte en NativeCommandError y aborta el script.
    $eapPrevio = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $salida = & certutil.exe -addstore -enterprise -f Root "$CertFull" 2>&1
    $rcCertutil = $LASTEXITCODE
    $ErrorActionPreference = $eapPrevio
    if ($rcCertutil -eq 0) {
        Write-Ok "instalado — almacén Enterprise\Root"
    } else {
        Write-Warn2 "certutil devolvió $rcCertutil en el almacén Enterprise (no es bloqueante):"
        $salida | Select-Object -Last 3 | ForEach-Object { Write-Host "       $_" -ForegroundColor DarkGray }
    }
}

# ── 4. Firefox: su propio almacén ─────────────────────────────────────────────
# Firefox NO usa el almacén de Windows: trae su base NSS propia. La única forma
# soportada de que lea las raíces del equipo es la directiva empresarial
# ImportEnterpriseRoots. La ponemos siempre (es una clave de registro, idempotente
# y reversible) en lugar de sólo documentarla: si no, el equipo queda "arreglado"
# en Edge/Chrome y roto en Firefox, que es exactamente el fallo silencioso que
# este script existe para eliminar.
if (-not $SkipFirefox) {
    Write-Step "habilitando en Firefox la lectura de las raíces del equipo (ImportEnterpriseRoots)"
    try {
        $fxKey = 'HKLM:\SOFTWARE\Policies\Mozilla\Firefox\Certificates'
        if (-not (Test-Path $fxKey)) { New-Item -Path $fxKey -Force | Out-Null }
        $actual = (Get-ItemProperty -Path $fxKey -Name 'ImportEnterpriseRoots' -ErrorAction SilentlyContinue).ImportEnterpriseRoots
        if ($actual -eq 1) {
            Write-Ok "ya estaba habilitado"
        } else {
            New-ItemProperty -Path $fxKey -Name 'ImportEnterpriseRoots' -Value 1 -PropertyType DWord -Force | Out-Null
            Write-Ok "habilitado (Firefox debe reiniciarse para tomarlo)"
        }
    } catch {
        Write-Warn2 "no se pudo escribir la directiva de Firefox: $($_.Exception.Message)"
        Write-Warn2 "Edge y Chrome funcionarán igual; en Firefox habrá que importar la CA a mano."
    }
} else {
    Write-Warn2 "Firefox omitido (-SkipFirefox): allí el certificado NO será de confianza."
}

# ── 5. URL de verificación ────────────────────────────────────────────────────
if (-not $Url) {
    $urlFile = Join-Path $ScriptDir 'gateway-url.txt'
    if (Test-Path -LiteralPath $urlFile) {
        $Url = (Get-Content -LiteralPath $urlFile -TotalCount 1).Trim()
        if ($Url) { Write-Step "URL de la pasarela leída de gateway-url.txt: $Url" }
    }
}
if (-not $Url) {
    Write-Host ""
    Write-Host "  Falta la dirección de la pasarela para poder VERIFICAR la instalación." -ForegroundColor Yellow
    $Url = (Read-Host "  Dirección https de la pasarela (ej. https://192.168.1.50)").Trim()
}
if (-not $Url) {
    Write-Bad "sin dirección no puedo verificar: el certificado quedó instalado, pero SIN COMPROBAR."
    Write-Host "     Vuelva a ejecutar con:  -Url https://<direccion-de-la-pasarela>" -ForegroundColor DarkGray
    Exit-Script 2
}
if ($Url -notmatch '^[a-zA-Z][a-zA-Z0-9+.-]*://') { $Url = "https://$Url" }

try {
    $uri = [System.Uri]$Url
} catch {
    Write-Bad "la dirección no es válida: $Url"
    Exit-Script 2
}
if ($uri.Scheme -ne 'https') {
    Write-Bad "la dirección debe ser https:// (recibí '$($uri.Scheme)://')."
    Write-Host "     Sobre http no hay certificado que verificar, y la extensión del navegador" -ForegroundColor DarkGray
    Write-Host "     exige https para cualquier dirección que no sea localhost." -ForegroundColor DarkGray
    Exit-Script 2
}
$vHost = $uri.Host
$vPort = if ($uri.IsDefaultPort) { 443 } else { $uri.Port }

# ── 6. VERIFICACIÓN: handshake TLS real contra la pasarela ───────────────────
Write-Step "verificando con un handshake TLS real contra ${vHost}:${vPort}"

# TLS 1.2 como mínimo (el default de .NET Framework antiguo todavía ofrece SSL3/TLS1.0
# y el servidor los rechaza, dando un rojo que NO es un problema de confianza).
$protocolos = [System.Security.Authentication.SslProtocols]::Tls12
$tls13 = [Enum]::GetValues([System.Security.Authentication.SslProtocols]) |
         Where-Object { $_.ToString() -eq 'Tls13' } | Select-Object -First 1
if ($tls13) { $protocolos = $protocolos -bor $tls13 }

$resultado = [pscustomobject]@{
    Etapa   = 'conexion'
    Ok      = $false
    Mensaje = ''
    Sujeto  = ''
    Emisor  = ''
}

$tcp = $null; $ssl = $null
try {
    $tcp = New-Object System.Net.Sockets.TcpClient
    $conectar = $tcp.BeginConnect($vHost, $vPort, $null, $null)
    if (-not $conectar.AsyncWaitHandle.WaitOne(10000, $false)) {
        throw "sin respuesta en 10 s"
    }
    $tcp.EndConnect($conectar)

    $resultado.Etapa = 'handshake'
    # Sin callback de validación: se usa el almacén del sistema, que es justo lo
    # que queremos comprobar (mismo camino que Edge y Chrome).
    $ssl = New-Object System.Net.Security.SslStream($tcp.GetStream(), $false)
    $ssl.AuthenticateAsClient($vHost, $null, $protocolos, $false)   # sin chequeo de revocación: una CA interna no publica CRL/OCSP

    $remoto = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($ssl.RemoteCertificate)
    $resultado.Etapa   = 'ok'
    $resultado.Ok      = $true
    $resultado.Sujeto  = $remoto.Subject
    $resultado.Emisor  = $remoto.Issuer
} catch {
    $msg = $_.Exception.Message
    $inner = $_.Exception.InnerException
    while ($inner) { $msg = "$msg :: $($inner.Message)"; $inner = $inner.InnerException }
    $resultado.Mensaje = $msg
} finally {
    if ($ssl) { $ssl.Dispose() }
    if ($tcp) { $tcp.Close() }
}

Write-Host ""
if ($resultado.Ok) {
    Write-Host "  ###############################################################" -ForegroundColor Green
    Write-Host "  #                    VERDE - TODO CORRECTO                    #" -ForegroundColor Green
    Write-Host "  ###############################################################" -ForegroundColor Green
    Write-Host ""
    Write-Host "  El equipo confía en la pasarela: la conexión TLS con $vHost se" -ForegroundColor Green
    Write-Host "  validó contra el almacén de certificados del sistema." -ForegroundColor Green
    Write-Host ""
    Write-Host "    Certificado del servidor : $($resultado.Sujeto)"
    Write-Host "    Emitido por              : $($resultado.Emisor)"
    Write-Host "    CA instalada (SHA-256)   : $huella"
    Write-Host ""
    Write-Host "  Siguiente paso: abrir $Url en el navegador. No debe aparecer" -ForegroundColor DarkGray
    Write-Host "  ningún aviso de sitio no seguro. Si Firefox estaba abierto, ciérrelo" -ForegroundColor DarkGray
    Write-Host "  y vuelva a abrirlo para que tome la directiva." -ForegroundColor DarkGray
    Exit-Script 0
}

Write-Host "  ###############################################################" -ForegroundColor Red
Write-Host "  #                   ROJO - NO VERIFICADO                      #" -ForegroundColor Red
Write-Host "  ###############################################################" -ForegroundColor Red
Write-Host ""
Write-Host "  El certificado se instaló, pero la comprobación contra la pasarela falló." -ForegroundColor Red
Write-Host ""
Write-Host "    Etapa   : $($resultado.Etapa)"
Write-Host "    Destino : ${vHost}:${vPort}"
Write-Host "    Detalle : $($resultado.Mensaje)"
Write-Host ""
if ($resultado.Etapa -eq 'conexion') {
    Write-Host "  Falló la CONEXIÓN, no la confianza. Esto NO es un problema del" -ForegroundColor Yellow
    Write-Host "  certificado. Compruebe, en este orden:" -ForegroundColor Yellow
    Write-Host "    1. Que la dirección sea la correcta (¿es ésta la de la pasarela?)."
    Write-Host "    2. Que el equipo llegue al servidor:  Test-NetConnection $vHost -Port $vPort"
    Write-Host "    3. Que el cortafuegos de la red no bloquee el puerto $vPort."
} else {
    Write-Host "  Falló la VALIDACIÓN del certificado. Compruebe, en este orden:" -ForegroundColor Yellow
    Write-Host "    1. Que la CA instalada sea la de ESTA instalación: coteje la huella"
    Write-Host "       SHA-256 de arriba con la que le dio su proveedor."
    Write-Host "    2. Que la dirección coincida con el nombre del certificado del"
    Write-Host "       servidor: si el certificado se emitió para una IP, hay que entrar"
    Write-Host "       por esa IP; si se emitió para un nombre, por ese nombre."
    Write-Host "    3. Que el certificado del servidor no haya caducado."
    Write-Host ""
    Write-Host "  Para ver qué presenta el servidor:"
    Write-Host "    Test-NetConnection $vHost -Port $vPort"
    Write-Host "    (y en el navegador, candado -> ver certificado)"
}
Write-Host ""
Write-Host "  Envíe esta pantalla completa a su soporte técnico." -ForegroundColor DarkGray
Exit-Script 1
