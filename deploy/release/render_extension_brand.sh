#!/usr/bin/env bash
# 028 T004/T005/T008 (US1 + US3 render): produce el entregable white-label de la
# EXTENSIÓN de navegador para un partner, a partir del brand-pack de la extensión.
#
# Mismo estilo python-in-bash que render_docs_brand.sh, UNA sola fuente de marca
# por cliente (deploy/clients/<slug>/brand.extension.json).
#
# Qué hace:
#   1. Copia SOLO el runtime de extension/ (manifest.json, *.js, config.js, popup.html,
#      icons/) a deploy/clients/<slug>/rendered/extension/. EXCLUYE README.md y *.md
#      y cualquier dev-only (jamás viajan en el zip del partner).
#   2. Sustituye en el manifest de la COPIA: name, description, action.default_title
#      (= name), icons, action.default_icon (= icons) desde el brand-pack.
#      NO hornea NINGUNA URL de gateway (host_permissions/config.js quedan intactos:
#      la URL la pone el usuario en runtime — decisión JF, US2).
#   3. Embebe manifest.key (clave PÚBLICA base64 del par RSA del partner) para un ID
#      de extensión ESTABLE entre carpetas/re-renders. La PRIVADA se escribe FUERA de
#      git en deploy/clients/<slug>/secrets/extension_key.pem (gitignore: clients/*/secrets*)
#      y se REUSA si ya existe (ID estable). Custodia: mismo tratamiento que las claves
#      de licencia (021) — sacarla del disco de build a la bóveda del partner.
#   4. Emite deploy/clients/<slug>/rendered/extension-<slug>.zip (manifest.json en la raíz
#      del zip, como exige Chrome).
#
# Versión (T008): FUENTE ÚNICA = manifest.version. El render NO duplica ni reescribe la
# versión en ningún otro lado.
#
# Uso: deploy/release/render_extension_brand.sh <slug> <ruta-brand.extension.json>
#      deploy/release/render_extension_brand.sh camara-comercio deploy/clients/camara-comercio/brand.extension.json
set -euo pipefail
SLUG="${1:?uso: render_extension_brand.sh <slug> <brand.extension.json>}"
BRAND_JSON="${2:?uso: render_extension_brand.sh <slug> <brand.extension.json>}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

command -v python3 >/dev/null || { echo "❌ necesita python3"; exit 1; }
command -v openssl >/dev/null || { echo "❌ necesita openssl (par RSA para manifest.key)"; exit 1; }
command -v zip     >/dev/null || { echo "❌ necesita zip"; exit 1; }
[ -f "$BRAND_JSON" ] || { echo "❌ no existe el brand-pack: $BRAND_JSON"; exit 1; }
[ -d "$REPO_ROOT/extension" ] || { echo "❌ no existe extension/ en $REPO_ROOT"; exit 1; }

CLIENT_DIR="$REPO_ROOT/deploy/clients/$SLUG"
SECRETS_DIR="$CLIENT_DIR/secrets"
KEY_PEM="$SECRETS_DIR/extension_key.pem"
RENDER_DIR="$CLIENT_DIR/rendered/extension"
ZIP_OUT="$CLIENT_DIR/rendered/extension-$SLUG.zip"

mkdir -p "$SECRETS_DIR" "$CLIENT_DIR/rendered"

# ── 1) Par RSA por partner (privada FUERA del repo, reusada si ya existe) ──────────
KEY_REUSED=0
if [ -f "$KEY_PEM" ]; then
  KEY_REUSED=1
else
  # 2048 bits: suficiente para el ID estable de una extensión MV3.
  openssl genrsa -out "$KEY_PEM" 2048 >/dev/null 2>&1 \
    || { echo "❌ openssl genrsa falló"; exit 1; }
  chmod 600 "$KEY_PEM"
fi
# Clave pública en DER (SubjectPublicKeyInfo) base64 = valor exacto de manifest.key.
MANIFEST_KEY_B64="$(openssl rsa -in "$KEY_PEM" -pubout -outform DER 2>/dev/null | openssl base64 -A)"
[ -n "$MANIFEST_KEY_B64" ] || { echo "❌ no pude derivar la clave pública"; exit 1; }

# ── 2) Render (copia runtime + sustitución de marca + manifest.key + zip) ──────────
python3 - "$SLUG" "$BRAND_JSON" "$REPO_ROOT" "$RENDER_DIR" "$MANIFEST_KEY_B64" <<'EOF'
import base64, hashlib, json, pathlib, shutil, sys

slug, brand_path, repo, render_dir, manifest_key = sys.argv[1:6]
repo = pathlib.Path(repo)
render_dir = pathlib.Path(render_dir)
src = repo / "extension"

pack = json.load(open(brand_path))
for req in ("name", "description", "icons"):
    if req not in pack:
        sys.exit(f"❌ brand-pack sin campo obligatorio: {req}")
name = pack["name"]
description = pack["description"]
icons = pack["icons"]

# Copia SOLO runtime: todo extension/ MENOS *.md y ocultos/dev. copytree con ignore
# es robusto a renombres de scripts (no hardcodea la lista de .js).
# Dev-only (no forma parte del runtime MV3): harness e2e, deps de node, tsconfig.
_NON_RUNTIME = {"e2e", "node_modules", "package.json", "package-lock.json", "tsconfig.json"}
def _ignore(_dir, entries):
    drop = []
    for e in entries:
        if e.startswith(".") or e.lower().endswith(".md") or e in _NON_RUNTIME:
            drop.append(e)
    return drop

if render_dir.exists():
    shutil.rmtree(render_dir)
render_dir.parent.mkdir(parents=True, exist_ok=True)
shutil.copytree(src, render_dir, ignore=_ignore)

# Sustitución de marca en el manifest de la COPIA (NO se toca el source).
mpath = render_dir / "manifest.json"
m = json.loads(mpath.read_text(encoding="utf-8"))
m["name"] = name
m["description"] = description
m["icons"] = icons
action = m.setdefault("action", {})
action["default_title"] = name          # T-contract: default_title = name
action["default_icon"] = icons
m["key"] = manifest_key                  # T005: ID de extensión estable
# NO se toca: version (fuente única), host_permissions/optional_host_permissions,
# permissions, background, content_scripts (nada de URL horneada — US2).
mpath.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# ID de extensión derivado de la clave pública (los primeros 16 bytes del sha256 del
# DER, nibble->'a'..'p'). Solo para el reporte: verifica ESTABILIDAD del ID.
der = base64.b64decode(manifest_key)
digest = hashlib.sha256(der).hexdigest()[:32]
ext_id = "".join(chr(ord("a") + int(c, 16)) for c in digest)

# Persistí datos para el bash (versión + id) sin duplicar la versión en el manifest.
(render_dir.parent / ".render-info").write_text(
    json.dumps({"version": m.get("version", ""), "ext_id": ext_id, "name": name}) + "\n",
    encoding="utf-8",
)
print(f"   name={name!r}  version={m.get('version','?')}  ext_id={ext_id}")
EOF

# ── 3) Zip (manifest.json en la raíz del zip) ─────────────────────────────────────
rm -f "$ZIP_OUT"
( cd "$RENDER_DIR" && zip -q -r -X "$ZIP_OUT" . -x '*.DS_Store' )

VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$CLIENT_DIR/rendered/.render-info" 2>/dev/null || echo '?')"
EXT_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["ext_id"])' "$CLIENT_DIR/rendered/.render-info" 2>/dev/null || echo '?')"

echo "✅ extensión white-label '$SLUG': $ZIP_OUT"
echo "   render:  $RENDER_DIR  (runtime only; README.md/*.md excluidos)"
echo "   versión: $VERSION  (fuente única = manifest.version)"
echo "   ext_id:  $EXT_ID  (estable mientras se conserve la clave)"
if [ "$KEY_REUSED" -eq 1 ]; then
  echo "   clave:   REUSADA $KEY_PEM (ID estable)"
else
  echo "   clave:   GENERADA $KEY_PEM"
fi
echo "   ⚠️  CUSTODIA: $KEY_PEM es la privada RSA del partner. Está fuera de git"
echo "       (gitignore: clients/*/secrets*). Muévela a la bóveda de secretos del"
echo "       partner (mismo tratamiento que las claves de licencia 021). NO la borres:"
echo "       sin ella el ID de la extensión cambia en el próximo render."
