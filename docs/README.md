# docs/ — Sitio de documentación de producto (spec 022)

Sitio **estático, air-gap-first** para distribuidor + operador. MkDocs + Material,
servido por nginx non-root en la imagen `basa-docs:<brand>-<version>`. **0 egress en
runtime**: fuentes/iconos/búsqueda embebidos en build (plugins `privacy` + `offline`).

## Build local

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-docs.txt
.venv/bin/mkdocs serve            # preview con live-reload
.venv/bin/mkdocs build --strict   # el build de verdad: un link roto = build roto
```

Imagen + checks (desde la raíz del repo):

```bash
make -C deploy build-docs   # imagen marca-neutra basa-docs:prod
make -C deploy check-docs   # 0-egress, strict, contenido, naming, white-label, búsqueda
```

## White-label (US3 — never fork)

La marca del sitio se DERIVA del brand-pack de la 020 (una sola fuente de marca):

```bash
# perfil de cliente real: render_profile.sh primero (produce rendered/brand.json)
deploy/release/render_profile.sh <slug>
deploy/release/render_docs_brand.sh <slug> deploy/clients/<slug>/rendered/brand.json
# ejemplo sin perfil:
deploy/release/render_docs_brand.sh aegis deploy/branding/brand.example.json
make -C deploy build-docs-brand BRAND=aegis VERSION=1.0
```

Genera `mkdocs.<brand>.yml` (overlay `INHERIT`: site_name/tagline/logo) y
`brand/<brand>/extra.css` (paleta). El contenido markdown es **marca-neutro** y jamás
cambia entre marcas (lo verifica `test_docs_whitelabel.sh`).

## Búsqueda: offline, nunca SaaS (US4)

La búsqueda es el **lunr built-in** de Material con el plugin `offline`: índice
precomputado en build, embebido en la imagen, funciona con la red bloqueada e incluso
desde `file://`. **Prohibido** cualquier buscador SaaS (Algolia DocSearch, Typesense
Cloud y equivalentes): meten egress y una dependencia externa que rompe el air-gap —
`test_docs_search_offline.sh` lo verifica en cada release.

Plan B documentado (si se migrara a Astro Starlight): **Pagefind**, el equivalente
offline del ecosistema JS (índice estático en build). Ver `specs/022-.../research.md`.

## Estructura OBLIGATORIA por tipo de página (Diátaxis adaptado)

Esta doc **se vende**: la estructura no es una convención, es un contrato que
`test_docs_structure.sh` hace cumplir en el gate del release. Tipos:

**GUÍA** (overview, install-deploy/*, white-label, administration, integrations/index,
compliance/*): H1 → resumen de 2-4 líneas → línea `**Para quién**:` → sección
conceptual con **≥1 diagrama Mermaid** → secciones del tema → límites con leyenda
🟢/🟡/🔵 donde aplique → `## Relacionado` final (≥2 links internos con 1 línea de
contexto). Mínimo 3 links internos en la página.

**RUNBOOK** (operations, integrations/gotchas): H1 → objetivo → prerrequisitos →
pasos/gotchas en formato síntoma → causa → fix (todo VERIFICADO en vivo, jamás
teórico) → `## Relacionado`. Diagrama opcional (árboles de triage bienvenidos).

**REFERENCIA** (api-reference/*): generada por `make -C deploy docs-refs`. Exenta
del template — jamás se edita a mano.

Los diagramas son **Mermaid como código** (fence ```` ```mermaid ````): versionables,
marca-neutros, y renderizan offline (el plugin `privacy` embebe mermaid.js en build —
verificado por el check de 0 egress). Cero PNGs de diagramas.

Ninguna página huérfana: toda página recibe al menos un link entrante (el linter lo
cuenta). La variante EN existe como fallback (`*.en.md`); la paridad completa es
roadmap — el linter aplica sobre las fuentes ES.

## Qué NO publica este sitio

- Las specs internas de ingeniería (`specs/0XX-*`) — audiencia distinta, jamás se derivan.
- Los internos de `docs/` fuera de `docs/docs/` (`COORDINATION-*.md`, `retros/`).
- Nombres de motor/internals del pipeline (lista compartida `prohibited_names.txt`).
