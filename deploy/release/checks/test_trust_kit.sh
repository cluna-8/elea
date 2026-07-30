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
docker run --rm -v "$KIT":/mnt "$SHELLCHECK_IMG" --shell=bash --severity=style \
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

# ── 5. El bundle se lo lleva ─────────────────────────────────────────────────
grep -q 'trust-kit' "$REPO_ROOT/deploy/release/bundle.sh" \
    || fail "bundle.sh no empaqueta el trust-kit (en la sede no hay repo del que sacarlo)"

echo "✅ trust-kit OK: kit completo, .ps1 parsea y con BOM, .bat ASCII, .sh limpios, va en el bundle"
