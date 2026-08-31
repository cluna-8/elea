# Implementation Plan: Product Documentation Site (Distribuidor & Operador)

**Branch**: `022-product-documentation-site` | **Date**: 2026-07-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/022-product-documentation-site/spec.md`

## Summary

Convertir la doc de producto (hoy una **página React hardcodeada**, `frontend/src/pages/DocsPage.tsx`, ~460
líneas, compliance-only, ES-only, que **no escala**) en un **sitio de documentación** propio: un **servicio
`docs`** más del stack — **estático y air-gap-first** — para las audiencias que **instalan, marca-blanquean,
administran e integran** Sentinel Guardian (**DISTRIBUIDOR + OPERADOR**). El sitio **no** es la doc interna de
Spec Kit (001–021): es contenido de producto, sembrado del **corpus markdown ya existente** en `docs/`
(`whitelabel-deployment.md`, `integration-surfaces.md`, `compliance-policies.md`).

La decisión de framework está **tomada** (ver `research.md`, build-vs-buy): **MkDocs + Material** primario,
**Astro Starlight + Pagefind** plan B documentado. La razón dominante: **air-gap de primera clase** (plugins
`offline`+`privacy` → **0 egress en runtime**, para clientes on-prem/VPN sin salida) y **cero toolchain nueva**
(Python-nativo, el mismo ecosistema del backend). La arquitectura se estructura en **cinco piezas**:

1. **Contenedor estático air-gapped** (US1): imagen **multi-stage** (build MkDocs → **nginx** estático), 0
   egress verificado por test; se enchufa al **docker-compose v1** y, como roadmap, al **k3s+Helm+Zarf v2** de
   la 020 (Zarf empaqueta la imagen `sentinel-docs:<brand>-<version>`).
2. **Contenido sembrado** (US2): 9 secciones técnicas, tres con **semilla fuerte** en `docs/`, conservando la
   leyenda de estado 🟢/🟡/🔵 (honestidad SDD).
3. **White-label por config, never fork** (US3): tokens de marca por overlay `INHERIT` / `envsubst`; contenido
   marca-neutro; imagen trazable por marca (Principio VII).
4. **Búsqueda offline anti-SaaS** (US4) + **API reference single-source** desde el OpenAPI de FastAPI (US5).
5. **Versionado (`mike`) + i18n ES/EN (`mkdocs-static-i18n`)** (US6); docset **end-user clínico** = roadmap
   (US7).

El enfoque técnico central: **empaquetar y publicar reusando la semilla** (`docs/*.md`) y el **OpenAPI** ya
existentes, **sin forkear** (Principio VII), extendiendo la **explicabilidad** del producto (Principio VIII) al
plano de la documentación. No introduce mecanismos de producto ni principios nuevos.

## Technical Context

**Language/Version**: **Python 3.12** (build del sitio con MkDocs + Material — el mismo runtime que el backend
FastAPI; **cero toolchain nueva**). El plan B (Starlight+Pagefind) introduciría **Node/JS**, coste consciente
documentado. Runtime del sitio: **HTML estático servido por nginx** (sin runtime dinámico).

**Primary Dependencies**: **MkDocs** + **Material for MkDocs** (tema); plugins **`search`/`offline`** (búsqueda
lunr offline), **`privacy`** (embebe assets remotos → 0 egress), **`mike`** (versionado), **`mkdocs-static-i18n`**
(ES/EN), y un plugin de render de **OpenAPI** (p.ej. `mkdocs-swagger-ui-tag`) para el API reference. **nginx**
(sirve estáticos). El **OpenAPI del backend FastAPI** (single-source del API reference) y el corpus `docs/*.md`
(semilla). Empaquetado: Docker (multi-stage, `docker save`/tarball; **Zarf** en v2, 020).

**Storage**: ninguno propio — el sitio es **estático** (sin DB, sin estado en runtime). Los artefactos
(imagen `sentinel-docs:<brand>-<version>`, índice de búsqueda precomputado, versiones `mike`) viven **dentro de la
imagen**. La única "fuente de verdad" externa es el **OpenAPI** (API reference) y `.env.example` (config
reference), leídos **en build-time**, no en runtime.

**Testing**: (a) **test de 0 egress** (SC-001): arrancar la imagen con la red saliente bloqueada y verificar
0 requests a hosts externos navegando + buscando; (b) `mkdocs build --strict` en CI (falla ante links rotos /
assets externos); (c) **test de white-label** (SC-004): 2 marcas difieren sólo en tokens de branding, 0 líneas
de contenido/tema cambian; (d) **check de naming neutro** (grep de nombres de motor/proveedor sobre el HTML
publicado); (e) **test de deriva del API reference** (SC-006): cambiar un endpoint → reconstruir → reference
refleja el cambio; (f) selectores de versión (`mike`) e idioma (ES/EN) funcionan y degradan con fallback.

**Target Platform**: Linux server en containers (servicio `docs` en el compose, Principio VII) + **air-gap**
(imagen sin egress; TLS por nginx/`auto_https off`, no ACME). Roadmap: k3s+Helm+Zarf (020, v2).

**Performance Goals**: sin objetivo de throughput (sitio estático). La meta es un **build reproducible** con
`--strict` que produce una imagen 0-egress; la búsqueda resuelve contra índice local sin backend.

**Constraints**: **0 egress en runtime** (Principio VII / postura air-gap del II); **never fork** (branding por
config-as-data, Principio VII); **naming neutro** (0 mención de motor/proveedor en el sitio publicado);
**API reference single-source** (OpenAPI, 0 deriva); **NO derivar las specs de Spec Kit** (fuga de contexto
interno); **búsqueda no-SaaS** (Algolia prohibido); TLS air-gap sin ACME.

**Scale/Scope**: un servicio `docs` (imagen multi-stage → nginx) + `mkdocs.yml` (config base) + overlays de
marca (`mkdocs.<brand>.yml`) + el árbol `docs/docs/**` (contenido, sembrado del corpus) + generación del API
reference desde OpenAPI + config `mike`/i18n + el servicio en `docker-compose.yml`. Sin código de producto
nuevo (no toca backend/frontend salvo retirar/redirigir `DocsPage.tsx`).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio / Constraint | Cómo lo cumple esta feature | Veredicto |
|---|---|---|
| **VII. Containerized & White-Label (config+seed, never fork)** | El sitio es un **container separado** (`sentinel-docs:<brand>-<version>`); el branding se aplica **sólo por config** (overlay `INHERIT`/`envsubst`, contenido marca-neutro); ningún motor/proveedor se nombra en el sitio publicado. | PASS by-design / a verificar (check de naming) |
| **VIII. Pipeline Transparency & Explainability** | El sitio **es** el artefacto de explicabilidad del producto: documenta el pipeline (masking→…→unmask), guardrails, integraciones y compliance para distribuidor/operador/auditor. Extiende la transparencia observable (VIII) al plano de producto. | PASS by-design |
| **II. Compliance & Governance FIRST** | El docset de compliance (GDPR Art.5/28/30, EU AI Act Art.50, retención, DPA, DSR) es contenido de primera clase, sembrado de `compliance-policies.md`; 0-egress es coherente con la postura de residencia/soberanía. | PASS by-design (relación de contenido) |
| **IV. Client Onboarding as Data** *(por analogía)* | White-labelear la doc es **config + seed** (tokens de marca), igual que onboardear un cliente; sumar una marca es config, no fork. | PASS by-design |
| **Constraint C5 Credenciales fuera de config en claro** | El sitio es estático: **no** maneja secretos en runtime. El único input build-time es OpenAPI + `.env.example` (plantilla, sin valores reales). | N/A (sin secretos en runtime) |
| **Dev Workflow — Reuse over Reinvent** | Reusa el **corpus `docs/*.md`** (semilla) y el **OpenAPI** ya existentes; no reescribe contenido ni reinventa un generador (MkDocs estándar). | PASS by-design |
| **Dev Workflow — Documentación viva** | El API reference es single-source (0 deriva); el contenido conserva la leyenda de estado 🟢/🟡/🔵. | PASS by-design |
| **Honestidad SDD** | Greenfield declarado; framework decidido con **contra** (Material en modo mantenimiento) y **plan B**; docset clínico = roadmap explícito. | PASS by-design |

**Sin violaciones nuevas**: esta feature **no** introduce mecanismos de producto ni proxy propio; es un
servicio de infraestructura estándar (sitio estático) que empaqueta contenido ya escrito. Ver Complexity
Tracking.

## Mapeo semilla → secciones del sitio

Traducción fiel de la evidencia existente (`docs/*.md` + el OpenAPI de FastAPI) a las secciones del sitio.
Columna "Fuente" = SEMILLA (corpus existente) vs AUTO (derivado) vs NUEVO (a redactar).

| Fuente existente (evidencia) | Sección del sitio (022) | Fuente |
|---|---|---|
| `docs/whitelabel-deployment.md` (runbook deploy: OpenTofu, secretos, estado-actual-vs-objetivo) | **Install/Deploy** | SEMILLA (relación 020) |
| `docs/whitelabel-deployment.md` §branding pack (config-as-data, never fork) | **White-label & branding** | SEMILLA |
| `docs/integration-surfaces.md` (superficies base_url/browser/mcp, matriz, gotchas) | **Integraciones & matriz** | SEMILLA (relación 019) |
| `docs/compliance-policies.md` (GDPR/AI-Act, DPA, DSR, retención, panel DPO) | **Compliance** | SEMILLA (relación 005/008, Principio II) |
| OpenAPI del backend FastAPI (`/openapi.json`) | **API reference** | AUTO (single-source, US5) |
| `.env.example` | **Config/env reference** (dentro de Install/Deploy o Administración) | AUTO (US5) |
| constitución v2.0.0 + `docker-compose.yml` (stack) | **Overview & arquitectura** | NUEVO (resumen marca-neutro) |
| 013 (multi-tenant/RBAC) + 021 (licencias/seats) + guardrails/budgets/SSO | **Administración** | NUEVO |
| gotchas de `integration-surfaces.md` + runbook operativo | **Operaciones & troubleshooting** | NUEVO (+ semilla parcial) |
| — (por `mike`, por versión) | **Release notes** | NUEVO (versionado US6) |
| — (otra audiencia/tono) | **End-user (clínico)** | ROADMAP P3 (US7, no v1) |

## Project Structure

### Documentation (this feature)

```text
specs/022-product-documentation-site/
├── plan.md              # This file
├── spec.md              # Feature spec (user stories, FR, SC, sitemap/IA)
├── tasks.md             # Task list (por user story)
├── research.md          # Phase 0: build-vs-buy (MkDocs Material vs Starlight vs resto) — decidido
├── content-map.md       # Phase 1 (a generar): IA detallada + mapeo semilla→página + estado por página
└── quickstart.md        # Phase 1 (a generar): build local, test de 0 egress, publicar una marca
```

### Source Code (repository root)

```text
docs/                                  # sitio de documentación (servicio `docs`)
├── mkdocs.yml                         # config base marca-neutra (nav/IA, tema Material, plugins)
├── mkdocs.<brand>.yml                 # overlay de marca por INHERIT (site_name/logo/favicon/palette)
├── Dockerfile                         # multi-stage: build MkDocs → nginx estático (0 egress)
├── nginx.conf                         # sirve estáticos; sin ACME (TLS lo termina el proxy del deploy)
├── requirements-docs.txt              # MkDocs + Material + plugins (offline/privacy/mike/i18n/openapi) pinneados
├── brand/                             # assets de marca por defecto (logo, favicon, extra.css) — marca-neutros
└── docs/                              # contenido markdown (sembrado de sentinel-guardian/docs/*.md)
    ├── overview/                       # Overview & arquitectura (NUEVO)
    ├── install-deploy/                 # Install/Deploy (semilla: whitelabel-deployment.md)
    ├── white-label/                    # White-label & branding (semilla)
    ├── administration/                 # Administración (NUEVO)
    ├── integrations/                   # Integraciones & matriz (semilla: integration-surfaces.md)
    ├── api-reference/                  # API reference (AUTO desde OpenAPI)
    ├── compliance/                     # Compliance (semilla: compliance-policies.md)
    ├── operations/                     # Operaciones & troubleshooting (NUEVO)
    └── release-notes/                  # Release notes (por mike)

docker-compose.yml                     # + servicio `docs` (sentinel-docs:<brand>-<version>) detrás del proxy
frontend/src/pages/DocsPage.tsx        # DEPRECAR: redirección/enlace al sitio o retiro (FR-009)
```

**Structure Decision**: sitio estático en un container separado (Principio VII). El sitio vive bajo `docs/`
(raíz del repo) para separarlo del bundle de la app (`frontend/`). El contenido markdown (`docs/docs/**`) se
**siembra** del corpus `sentinel-guardian/docs/*.md`, el API reference se **auto-genera** del OpenAPI, y el
branding es **config** (`mkdocs.yml` base + `mkdocs.<brand>.yml` overlay). No se crea código de producto:
backend/frontend sólo se tocan para **retirar/redirigir** `DocsPage.tsx`.

## Orden de implementación

1. **Fundacional — Phase 0 research + esqueleto MkDocs.** Confirmar la decisión de framework (`research.md`,
   ya hecha) y levantar el esqueleto **MkDocs + Material** con `mkdocs.yml` base, plugins `privacy`/`offline`,
   `--strict`, y el árbol `docs/docs/**` vacío. Bloquea todo lo demás.
2. **US1 Contenedor air-gapped (P1).** Dockerfile multi-stage → nginx; test de **0 egress** (red bloqueada);
   servicio `docs` en el compose. Es el MVP de empaquetado (sin él no hay entregable air-gap).
3. **US2 Contenido sembrado (P1).** Migrar `whitelabel-deployment.md`/`integration-surfaces.md`/
   `compliance-policies.md` a sus secciones + redactar las nuevas (overview/administration/operations/release);
   retirar/redirigir `DocsPage.tsx`. Es el **valor** del sitio.
4. **US3 White-label por config (P1).** Tokens de marca por overlay `INHERIT` + assets marca-neutros; check de
   naming neutro; imagen por marca. Va con US1 (imagen `sentinel-docs:<brand>-…`).
5. **US4 Búsqueda offline (P2).** Activar lunr `offline`; verificar 0-egress de la búsqueda; prohibir Algolia.
6. **US5 API reference single-source (P2).** Generar el API reference desde el OpenAPI en el build + config
   reference desde `.env.example`; test de deriva. Prohibir derivar las specs.
7. **US6 Versionado + i18n (P2).** `mike` (versiones) + `mkdocs-static-i18n` (ES/EN) con fallback explícito.
8. **US7 End-user clínico (P3).** Documentar el segundo docset como roadmap; NO entregar.
9. **Cierre.** Verificación E2E (build `--strict` → imagen → 0 egress → 2 marcas → selectores versión/idioma);
   validar `quickstart.md`; confirmar que white-labelear es config, no fork.

## Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| **Egress oculto por assets externos** (fuentes Google / CDN por defecto en el tema). | Rompe el air-gap 0-egress (US1). | Plugin **`privacy`** (embebe assets) + **`--strict`** (build) + **test de 0 egress** en runtime (SC-001). |
| **Material en modo mantenimiento** (fixes sí, features no). | Roadmap del tema estancado; no afecta runtime. | **Plan B Starlight+Pagefind** documentado con disparador (acabado visual + i18n); contenido markdown portable. |
| **Buscador SaaS por costumbre** (Algolia DocSearch). | Egress + dependencia externa → rompe air-gap. | **Prohibido** (FR-015): lunr/Pagefind offline; check de config sin claves SaaS (SC-005). |
| **Caddy auto-HTTPS → ACME/Let's Encrypt en air-gap.** | Egress en el arranque rompe el install air-gapped. | **nginx estático** o Caddy `auto_https off`; TLS por cert provisto (020), no ACME (FR-023). |
| **Deriva del API reference** (escrito a mano). | Reference desincronizado con el código. | **Single-source** desde el OpenAPI de FastAPI, regenerado en cada build (US5, SC-006). |
| **Fuga de contexto interno** (derivar el sitio de las specs de Spec Kit). | Deuda/evidencia interna publicada al cliente. | **Prohibido** (FR-018): contenido de producto **curado separado**; sólo API/config se auto-derivan. |
| **Nombre de motor/proveedor filtrado** (título/asset heredado del corpus). | Rompe naming neutro (Principio VII). | Check de branding en build (grep de nombres prohibidos sobre el HTML, FR-013, SC-004). |
| **White-label por swizzling/fork** (si se eligiera un tema React). | Deriva + coste por distribuidor. | MkDocs `INHERIT`/`envsubst` (config-as-data), contenido marca-neutro, imagen por marca (never fork). |
| **`mike` sin mantenimiento** (plugin de comunidad). | Riesgo del versionador. | Estándar de facto; produce directorios estáticos (lo publicado sobrevive); versión fijada. |
| **Traducción EN incompleta.** | 404 o navegación rota en EN. | Fallback explícito al idioma primario ES (`mkdocs-static-i18n`), no 404 (US6, SC-007). |
| **La doc de producto sigue en el bundle del frontend** (`DocsPage.tsx`). | Doble fuente, doc como código, mezcla con la app. | Retirar/redirigir `DocsPage.tsx` al entrar el sitio (FR-009). |

## Complexity Tracking

> Sin violaciones nuevas de principio en esta feature.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| *(ninguna nueva)* | Es un servicio de infraestructura estándar (sitio estático) que **empaqueta contenido ya escrito** y **auto-deriva** el API reference. No añade mecanismos de producto ni principios. | El plan B (Starlight+Pagefind) introduciría **toolchain Node/JS** — se **rechaza para v1** por el coste de doble toolchain; MkDocs es Python-nativo (cero toolchain nueva). Derivar las specs de Spec Kit se **rechaza** por fuga de contexto interno. Un buscador SaaS (Algolia) se **rechaza** por romper el air-gap. |
