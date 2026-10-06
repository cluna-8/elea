#!/usr/bin/env bash
# Test (sin Docker) del skip de `make check-extension-whitelabel` cuando extension/ no existe.
# Corre el target del Makefile REAL contra una raíz de repo falsa (REPO_ROOT=…) con scripts-stub:
#   1. sin extension/                  → rc 0 y mensaje SALTADO (los stubs NO se ejecutan).
#   2. con extension/, render falla    → rc != 0 (el gate no se relaja: el skip es sólo por ausencia).
#   3. con extension/, render ok y test falla → rc != 0.
#   4. con extension/, todo ok         → rc 0 y SIN mensaje SALTADO.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
FAKE="$WORK/repo"; mkdir -p "$FAKE/deploy/release/checks"
fallos=0
stub() { printf '#!/usr/bin/env bash\necho "stub %s ejecutado"\nexit %s\n' "$1" "$2" > "$3"; chmod +x "$3"; }
correr() { make --no-print-directory -C "$REPO_ROOT/deploy" -f "$REPO_ROOT/deploy/Makefile" REPO_ROOT="$FAKE" check-extension-whitelabel 2>&1; }
esperar() { # nombre, "0"|"!0", rc, salida, [presente|ausente], [fragmento]
    local n="$1" e="$2" rc="$3" out="$4" modo="${5:-}" frag="${6:-}" ok=1
    { [ "$e" = 0 ] && [ "$rc" != 0 ]; } && ok=0
    { [ "$e" != 0 ] && [ "$rc" = 0 ]; } && ok=0
    [ "$modo" = presente ] && ! grep -qF -- "$frag" <<<"$out" && ok=0
    [ "$modo" = ausente ] && grep -qF -- "$frag" <<<"$out" && ok=0
    if [ "$ok" = 1 ]; then echo "  ✔ $n (rc=$rc)"; else echo "  ✘ $n (rc=$rc)"; sed 's/^/      | /' <<<"$out"; fallos=1; fi
}
echo "test_extension_check_skip"
stub render 1 "$FAKE/deploy/release/render_extension_brand.sh"
stub test 1 "$FAKE/deploy/release/checks/test_extension_whitelabel.sh"
out="$(correr)"; rc=$?
esperar "1. sin extension/ → SALTADO, rc 0" 0 $rc "$out" presente "SALTADO"
grep -q "stub" <<<"$out" && { echo "  ✘ 1b. se ejecutó un stub pese a no haber extension/"; fallos=1; }

mkdir "$FAKE/extension"
out="$(correr)"; rc=$?; esperar "2. con extension/, render falla → falla" '!0' $rc "$out" ausente "SALTADO"
stub render 0 "$FAKE/deploy/release/render_extension_brand.sh"
out="$(correr)"; rc=$?; esperar "3. con extension/, test falla → falla" '!0' $rc "$out" presente "stub test ejecutado"
stub test 0 "$FAKE/deploy/release/checks/test_extension_whitelabel.sh"
out="$(correr)"; rc=$?; esperar "4. con extension/, todo ok → corre sin skip" 0 $rc "$out" ausente "SALTADO"

if [ "$fallos" = 0 ]; then echo "✅ test_extension_check_skip OK"; else echo "❌ test_extension_check_skip FALLÓ"; fi
exit $fallos
