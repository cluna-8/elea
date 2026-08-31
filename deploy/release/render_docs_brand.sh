#!/usr/bin/env bash
# 022 T023 (US3, FR-010/FR-011 — delta F3): deriva el brand-pack del SITIO DE DOCS desde
# el brand-pack de la 020 (deploy/branding/brand.<x>.json) — UNA sola fuente de marca por
# cliente, jamás dos definiciones que derivan.
#
# Genera: docs/mkdocs.<slug>.yml (overlay INHERIT: site_name/tagline/logo)
#         docs/brand/<slug>/extra.css (paleta desde colors.*)
#         docs/brand/<slug>/<logo>    (si el pack lo trae en deploy/branding/assets/)
#
# Uso: deploy/release/render_docs_brand.sh <slug> <ruta-al-brand.json>
#      deploy/release/render_docs_brand.sh aegis deploy/branding/brand.example.json
set -euo pipefail
SLUG="${1:?uso: render_docs_brand.sh <slug> <brand.json>}"
BRAND_JSON="${2:?uso: render_docs_brand.sh <slug> <brand.json>}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

command -v python3 >/dev/null || { echo "❌ necesita python3"; exit 1; }

python3 - "$SLUG" "$BRAND_JSON" "$REPO_ROOT" <<'EOF'
import json, pathlib, shutil, sys

slug, brand_path, repo = sys.argv[1], sys.argv[2], pathlib.Path(sys.argv[3])
pack = json.load(open(brand_path))
name = pack["name"]
tagline = pack.get("tagline", "")
colors = pack.get("colors") or {}
logo = pack.get("logo")

brand_dir = repo / "docs" / "brand" / slug
brand_dir.mkdir(parents=True, exist_ok=True)

# 1) Overlay INHERIT — SOLO tokens de marca; contenido y tema intactos (never fork).
overlay = [
    f"# Overlay de marca '{slug}' — GENERADO por render_docs_brand.sh desde {pathlib.Path(brand_path).name}",
    "# (una sola fuente de marca: el brand-pack de la 020). No editar a mano.",
    "INHERIT: mkdocs.yml",
    f"site_name: {json.dumps(name, ensure_ascii=False)}",
]
if tagline:
    overlay.append(f"site_description: {json.dumps(tagline, ensure_ascii=False)}")
logo_dest = None
if logo:
    src = repo / "deploy" / "branding" / "assets" / logo
    if src.exists():
        logo_dest = brand_dir / logo
        shutil.copyfile(src, logo_dest)
        overlay += ["theme:", "  name: material", f"  logo: assets/brand/{logo}"]
(repo / "docs" / f"mkdocs.{slug}.yml").write_text("\n".join(overlay) + "\n")

# 2) Paleta → CSS vars de Material (mismo contrato que la app: hex del pack).
def _shade(hex_color, factor):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
    mix = (lambda c: min(255, int(c + (255 - c) * factor))) if factor > 0 else (lambda c: max(0, int(c * (1 + factor))))
    return "#%02x%02x%02x" % (mix(r), mix(g), mix(b))

primary = colors.get("primary", "#0b7285")
css = [
    f"/* Paleta de la marca '{slug}' — GENERADA desde el brand-pack (no editar a mano). */",
    ":root {",
    f"  --md-primary-fg-color: {primary};",
    f"  --md-primary-fg-color--light: {_shade(primary, 0.25)};",
    f"  --md-primary-fg-color--dark: {_shade(primary, -0.25)};",
    f"  --md-accent-fg-color: {colors.get('accent', _shade(primary, 0.25))};",
    "}",
]
(brand_dir / "extra.css").write_text("\n".join(css) + "\n")

print(f"✅ brand '{slug}': overlay docs/mkdocs.{slug}.yml + docs/brand/{slug}/extra.css"
      + (f" + {logo}" if logo_dest else ""))
print(f"   build: docker build --build-arg BRAND={slug} -t sentinel-docs:{slug}-<version> docs/")
EOF
