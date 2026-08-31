# Quickstart — Sitio de documentación de producto (022, T040)

## 1. Build y preview local

```bash
cd docs
python3 -m venv .venv && .venv/bin/pip install -r requirements-docs.txt
.venv/bin/mkdocs serve                 # http://127.0.0.1:8000, live-reload
.venv/bin/mkdocs build --strict        # gate real: un link roto = build roto
```

## 2. Imagen de producción (versionada con mike)

```bash
make -C deploy build-docs              # sentinel-docs:prod — marca neutra, versión 1.0+latest+dev
make -C deploy check-docs              # los 8 checks del sitio (ver §5)
```

El build usa un repo git **efímero** dentro del stage (mike jamás toca el repo real) y
publica `/<version>/`, `/latest/` (alias copia), `/dev/` y `versions.json` (selector).
Versión: `--build-arg DOCS_VERSION=1.1`.

## 3. Marca de un distribuidor (never fork)

```bash
# 1) derivar el brand-pack del sitio desde el brand-pack de la 020 (UNA fuente de marca).
#    Con un perfil de cliente real, primero renderizarlo (produce rendered/brand.json):
deploy/release/render_profile.sh acme
deploy/release/render_docs_brand.sh acme deploy/clients/acme/rendered/brand.json
#    (para probar sin perfil: deploy/release/render_docs_brand.sh aegis deploy/branding/brand.example.json)
# 2) imagen trazable por marca (VERSION se cablea al versionado mike del sitio):
make -C deploy build-docs-brand BRAND=acme VERSION=1.0   # → sentinel-docs:acme-1.0
```

Cambia SOLO `site_name`/tagline/paleta/logo. `test_docs_whitelabel.sh` verifica que dos
marcas comparten contenido byte-a-byte (tras normalizar tokens de marca).

## 4. Regenerar los references single-source (tras cambiar la API o .env.example)

```bash
make -C deploy docs-refs   # openapi.json (del backend real) + configuration.md (.env.example)
```

Si te olvidás, `test_docs_apiref.sh` pone el release en rojo (check de deriva).

## 5. Verificación (los 8 checks = SC-001..SC-007)

`make -C deploy check-docs` corre, contra la imagen y con `--network none`:

| Check | Verifica |
|---|---|
| `test_docs_image.sh` | 14 rutas sirven sin red; 0 refs externas load-bearing; non-root; sin toolchain |
| `test_docs_strict_build.sh` | un link roto ROMPE el build (fixture negativo) |
| `test_docs_content.sh` | 9 secciones reales; leyenda 🟢/🟡/🔵 preservada |
| `test_docs_neutral_naming.sh` | 0 motor/internals (lista compartida con la UI) |
| `test_docs_whitelabel.sh` | 2 marcas → contenido idéntico, solo tokens difieren |
| `test_docs_search_offline.sh` | búsqueda lunr local; 0 SaaS (Algolia prohibido) |
| `test_docs_apiref.sh` | references sin deriva; 0 fuga de specs/internos |
| `test_docs_versioning.sh` | ≥2 versiones + latest; EN con fallback ES sin 404 |

## 6. Deploy

- **Compose prod**: servicio `docs` en `deploy/docker/compose.prod.yml` (env `DOCS_IMAGE`).
  El ingress lo publica bajo `/docs/` o `docs.<dominio>`; la app enlaza via `brand.json`
  (`docsUrl`). Escucha en :8080, jamás en 80/443 ni habla ACME.
- **Air-gap**: la imagen viaja en `images.tar` del bundle (`DOCS_IMAGE=` en `bundle.sh`).
- **k8s v2 (roadmap 020)**: la imagen entra al paquete Zarf como el resto.

## Limitaciones conocidas (T043 — honestidad)

- **Material en modo mantenimiento** (fixes sí, features no): riesgo de roadmap, no de
  runtime. Plan B **Starlight+Pagefind** documentado en `research.md` con su disparador.
- **`mike` no es first-party**: produce directorios estáticos — lo publicado sobrevive
  aunque el plugin muera. Versión pinneada.
- **El API reference hereda los huecos del OpenAPI**: endpoints sin schema quedan pobres
  en el explorador — es calidad del OpenAPI del backend, no del sitio.
- **EN parcial**: la landing está traducida; el resto degrada a ES (fallback explícito,
  sin 404). La paridad EN completa es trabajo editorial pendiente, no mecánico.
- **Identificadores wire visibles**: `litellm_params` (OpenAPI) y `LITELLM_MASTER_KEY`
  (config) — allowlisted como contrato; el rename de fondo es el issue #24.
