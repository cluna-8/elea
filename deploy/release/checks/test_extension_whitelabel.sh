#!/usr/bin/env bash
# 028 T009/T010 (US7): gate white-label del ENTREGABLE de la extensión. Descomprime
# extension-<slug>.zip y falla ante cualquier término de:
#   - prohibited_brand.txt  (marca del fabricante: basa / basa guard / poc / localhost)
#   - prohibited_names.txt  (motor: litellm / berriai / presidio — compartida con UI/docs)
# CON la allowlist de identificadores internos del cross-contract 028 (word-exact,
# mismo espíritu que la allowlist litellm_params/presidio de test_no_engine_name.sh):
# son wiring interno (claves de storage, header, canal del bridge), no texto visible.
#
# Además verifica que el render SUSTITUYÓ la marca: manifest.name/description/
# action.default_title NO son "Basa Guard" ni contienen "basa", y manifest.key existe.
#
# El escaneo corre en PYTHON (stdlib) — el gate se ejecuta en el HOST sobre archivos
# descomprimidos, y las implementaciones de grep del host varían (GNU grep en CI vs
# ugrep/BSD grep en dev): la tokenización con `grep -oE` NO es portable entre ellas.
# Python da tokenización exacta + reporte file:line determinista en cualquier host.
#
# Uso: test_extension_whitelabel.sh [slug]            (default: camara-comercio)
#      EXT_ZIP=/ruta/al/zip test_extension_whitelabel.sh <slug>   (override del zip)
set -euo pipefail
SLUG="${1:-camara-comercio}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ZIP="${EXT_ZIP:-$REPO_ROOT/deploy/clients/$SLUG/rendered/extension-$SLUG.zip}"

fail() { echo "❌ $1"; exit 1; }
command -v python3 >/dev/null || fail "necesita python3"
command -v unzip   >/dev/null || fail "necesita unzip"
[ -f "$ZIP" ] || fail "no existe el zip: $ZIP  (corré: deploy/release/render_extension_brand.sh $SLUG deploy/clients/$SLUG/brand.extension.json)"
[ -f "$HERE/prohibited_brand.txt" ] || fail "falta $HERE/prohibited_brand.txt"
[ -f "$HERE/prohibited_names.txt" ] || fail "falta $HERE/prohibited_names.txt"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
unzip -q "$ZIP" -d "$WORK" || fail "no pude descomprimir $ZIP"

python3 - "$WORK" "$HERE/prohibited_brand.txt" "$HERE/prohibited_names.txt" "$SLUG" <<'PY'
import json, pathlib, re, sys

work = pathlib.Path(sys.argv[1])
brand_list, engine_list, slug = sys.argv[2], sys.argv[3], sys.argv[4]

# Allowlist de identificadores internos (cross-contract 028), word-exact, ci.
# NO son texto visible: claves de chrome.storage, header de auth, símbolos del canal
# bridge↔MAIN. Renombrarlos rompe el wiring sin ganancia de marca blanca. Cualquier
# OTRO token que contenga la raíz de marca es fuga.
ALLOW = {s.lower() for s in (
    "__BASA_GUARD__", "BASA_CONFIG", "basa_key", "basa_gateway", "basa_connected",
    "basa_user", "basa_team", "X-Basa-Key", "__basa", "__basa_nonce",
)}

def read_terms(path):
    out = []
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out

# Solo archivos de texto viajan como código; los .png de icons se ignoran.
TEXT_SUFFIXES = {".js", ".json", ".html", ".htm", ".css", ".txt", ".md", ".map"}
files = []
for p in sorted(work.rglob("*")):
    if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES:
        try:
            files.append((p.relative_to(work).as_posix(), p.read_text(encoding="utf-8").splitlines()))
        except UnicodeDecodeError:
            pass  # binario disfrazado de texto: no es código legible → no aplica el gate textual

failed = False
def flag(msg, hits):
    global failed
    failed = True
    print(f"❌ {msg}")
    for rel, ln, text in hits[:12]:
        print(f"     {rel}:{ln}: {text.strip()}")
    if len(hits) > 12:
        print(f"     … (+{len(hits)-12} más)")

# ── 1) Sustitución de marca en el manifest (el render pisó los campos) ─────────────
mf = work / "manifest.json"
if not mf.exists():
    flag("el zip no tiene manifest.json en la raíz", [])
else:
    m = json.loads(mf.read_text(encoding="utf-8"))
    bad = []
    for field, val in (("name", m.get("name", "")),
                       ("description", m.get("description", "")),
                       ("action.default_title", m.get("action", {}).get("default_title", ""))):
        v = str(val)
        if v.strip().lower() == "basa guard" or "basa" in v.lower():
            bad.append((field, v))
    if not m.get("key"):
        bad.append(("key", "<falta manifest.key — ID de extensión NO estable>"))
    if bad:
        failed = True
        print("❌ el render NO sustituyó la marca en el manifest:")
        for k, v in bad:
            print(f"     • {k} = {v!r}")
    else:
        print(f"   manifest OK: name={m.get('name')!r} (marca sustituida, manifest.key presente)")

# localhost en forma de DIRECCIÓN (URL/host baked), NO la palabra suelta: el validador
# FR-010 de la extensión (Minion B) contiene LEGÍTIMAMENTE el token en una comparación
# de código —  host === "localhost" || host === "127.0.0.1"  — que permite http solo en
# local; eso NO es una dirección de desarrollo horneada. Disparamos solo ante:
#   //localhost   (p.ej. http://localhost…)   ·   localhost:<puerto>   ·   localhost/<path>
# y NUNCA ante "localhost" entre comillas en una comparación.
LOCALHOST_URL = re.compile(r"(//localhost|localhost[:/])", re.I)

for term in read_terms(brand_list) + read_terms(engine_list):
    tl = term.lower()

    if " " in term:  # frase visible (p.ej. "basa guard") — sin allowlist
        hits = [(rel, i + 1, line) for rel, lines in files
                for i, line in enumerate(lines) if tl in line.lower()]
        if hits:
            flag(f"frase de marca del fabricante en el zip: '{term}'", hits)
        continue

    if term == "localhost":  # host de infra en forma de URL; "https/localhost" NO lo es
        hits = [(rel, i + 1, line) for rel, lines in files
                for i, line in enumerate(lines) if LOCALHOST_URL.search(line)]
        if hits:
            flag("URL de infra horneada (localhost) en el zip", hits)
        continue

    # token-contains + allowlist (basa, poc, motor)
    tok_re = re.compile(r"[A-Za-z0-9_-]*" + re.escape(term) + r"[A-Za-z0-9_-]*", re.I)
    leaks = {}  # token -> [(rel, ln, line)]
    for rel, lines in files:
        for i, line in enumerate(lines):
            for tok in tok_re.findall(line):
                if tok.lower() in ALLOW:
                    continue
                leaks.setdefault(tok, []).append((rel, i + 1, line))
    if leaks:
        failed = True
        print(f"❌ identificadores prohibidos (raíz '{term}') NO allowlisteados en el zip:")
        for tok in sorted(leaks):
            print(f"     • {tok}")
            for rel, ln, line in leaks[tok][:3]:
                print(f"         {rel}:{ln}: {line.strip()}")

if failed:
    print(f"❌ gate white-label EXTENSIÓN ({slug}): hay fugas (ver arriba)")
    sys.exit(1)
print(f"✅ gate white-label EXTENSIÓN OK ({slug}): marca sustituida; "
      "sin fuga de fabricante/motor; allowlist interna respetada")
PY
