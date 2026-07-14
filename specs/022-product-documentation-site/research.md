# Research T0 (Phase 0) — Build-vs-buy del sitio de documentación de producto (022 Product Documentation Site)

**Fecha**: 2026-07-14 · **Método**: revisión de prior-art público (docs oficiales de los generadores de
sitios estáticos de documentación, anuncios de licencia/mantenimiento, guías de air-gap/offline) cruzada con
el shape del negocio (Basa entrega una **imagen por marca** a un **distribuidor**; el cliente final la levanta
en su cuenta cloud u **on-prem/air-gap**; **una instancia por cliente**; VPN sin egress como caso duro). Cada
eje trae **veredicto v1/v2** y **fuentes**. Corrige la hipótesis fácil ("usamos Docusaurus/Mintlify porque son
populares") que no aguanta el requisito **air-gap 0-egress** ni el de **cero toolchain nueva**.

> ⚠️ Nota de alcance: este research **fija la decisión de framework y la arquitectura de empaquetado del
> sitio** (US1–US6). Lo marcado "plan B / v2" es roadmap explícito, no código entregado en esta feature. El
> principio rector: **estático, air-gap-first (0 egress), white-label por config sin fork, sin toolchain
> nueva, contenido single-source donde se pueda auto-derivar**.

## Resumen

- **Framework v1 = MkDocs + Material; plan B = Astro Starlight + Pagefind.** Material gana por **air-gap de
  primera clase** (plugins **`offline`** + **`privacy`** → 0 llamadas externas en runtime) y **cero toolchain
  nueva** (Python-nativo, el mismo ecosistema que el backend FastAPI). White-label por **YAML** (`INHERIT`
  overlay), versionado con **`mike`**, i18n con **`mkdocs-static-i18n`**, e **Insiders gratis desde v9.7.0**
  (nov-2025). Contra a declarar: **Material en modo mantenimiento** (fixes sí, features no) → riesgo de
  roadmap. Disparador para migrar a Starlight: si pesan el **acabado visual** y el **i18n de fábrica**.
- **Empaquetado = imagen estática multi-stage → nginx.** Build con MkDocs → HTML estático servido por nginx
  (o Caddy con `auto_https off`). Imagen **por marca** `basa-docs:<brand>-<version>`; en air-gap va por
  **tarball / Zarf** (020), sin pull de registry en runtime.
- **Búsqueda = offline, nunca SaaS.** lunr built-in de Material (plugin `offline`) para v1; **Pagefind** es el
  estándar offline del plan B (Starlight lo trae). **Algolia DocSearch = prohibido** (SaaS, rompe air-gap).
- **Single-source donde se pueda.** API reference **auto-generado desde el OpenAPI** de FastAPI; config
  reference desde `.env.example`. El resto es **corpus curado separado**; **NO** se derivan las specs de Spec
  Kit (audiencias distintas + fuga de contexto interno).
- **White-label = config-as-data, never fork.** Tokens de marca (site_name/logo/favicon/palette/extra.css) por
  overlay `INHERIT` o `envsubst`; contenido marca-neutro; una marca por instancia (coherente con la 020).

---

## Tabla de decisión por eje

| Eje | Descartado (y por qué) | v1 (MVP) | plan B / v2 (roadmap) |
|---|---|---|---|
| **Framework** | Docusaurus/Nextra/Fumadocs/VitePress/Docsify (ver tabla de frameworks); **Mintlify/GitBook/RTD** (SaaS/hosted, air-gap difícil) | **MkDocs + Material** (Python-nativo, `offline`+`privacy`) | **Astro Starlight + Pagefind** (si pesa acabado visual + i18n) |
| **Empaquetado** | pull de registry en runtime; SSR/servidor dinámico | **imagen multi-stage → nginx estático**, `basa-docs:<brand>-<version>` | igual; **Zarf** empaqueta la imagen (020 v2) |
| **Air-gap** | fuentes Google/CDN por defecto; hosting SaaS | **`privacy`+`offline` plugins + `--strict`** (0 egress) | igual |
| **Búsqueda** | **Algolia DocSearch** (SaaS, egress) | **lunr built-in** (Material `offline`) | **Pagefind** (Starlight) |
| **API reference** | reference escrito a mano (deriva) | **auto-gen desde OpenAPI** (FastAPI single-source) | igual |
| **White-label** | fork por distribuidor; build-time baking del contenido | **config-as-data** (YAML `INHERIT` / `envsubst`) | igual |
| **Versionado** | una sola versión; ramas git a mano | **`mike`** (`1.x`/`latest`/`dev`) | igual |
| **i18n** | ES-only (estado actual del corpus) | **`mkdocs-static-i18n`** (ES/EN) | i18n de fábrica en Starlight (si se migra) |
| **TLS air-gap** | Caddy auto-HTTPS (ACME → Let's Encrypt = egress) | **nginx estático** / Caddy `auto_https off` | Traefik (k3s, 020 v2) |

---

## Tabla comparativa de frameworks (por eje)

| Framework | Toolchain | Air-gap / 0-egress | Búsqueda offline | Versionado | i18n | White-label por config | Licencia / estado | Veredicto |
|---|---|---|---|---|---|---|---|---|
| **MkDocs + Material** | **Python** (el del backend) | **Primera clase** (`offline`+`privacy`) | **lunr built-in** | **`mike`** | **`mkdocs-static-i18n`** | **YAML `INHERIT` overlay** | MIT; **Insiders gratis desde v9.7.0** (nov-2025); **modo mantenimiento** | **v1 (elegido)** |
| **Astro Starlight** | **Node/JS** | Buena (estático; cuidar fuentes) | **Pagefind** (incluido) | Vía routing/manual | **De fábrica** (fuerte) | Config JS + CSS vars | MIT; activo | **Plan B** |
| **Docusaurus** | **Node/React** | Media (fuentes/analytics por defecto; MDX pesado) | Local plugin o **Algolia** (SaaS) | **Nativo** (fuerte) | Nativo | Swizzling React (≈ fork parcial) | MIT; Meta; activo | Descartado v1 (toolchain React + swizzle) |
| **Nextra 4** | **Next.js/React** | Baja/Media (Next runtime; estático posible) | Pagefind/FlexSearch | Manual | i18n de Next | Config + componentes React | MIT; activo | Descartado (peso Next para docs) |
| **Fumadocs** | **Next.js/React** | Media | Orama/otros | Manual | i18n de Next | Componentes React | MIT; activo/joven | Descartado (Next + joven) |
| **VitePress** | **Node/Vue** | Media | **Local built-in** (MiniSearch) | Manual/ramas | Nativo | Theme Vue + config | MIT; activo | Viable, pero toolchain Vue nueva |
| **Docsify** | **Node (runtime JS)** | **Mala** (renderiza en runtime en el navegador; no pre-render → SEO/offline débil) | Plugin runtime | Manual | Plugin | CSS/config | MIT; activo | Descartado (render en runtime) |
| **Mintlify** | SaaS/hosted | **N/A** (hosted; self-host limitado) | SaaS | Sí | Sí | Config (branding fuerte) | Comercial/SaaS | Descartado (air-gap) |
| **GitBook** | SaaS/hosted | **N/A** (hosted) | SaaS | Sí | Sí | Branding fuerte | Comercial/SaaS | Descartado (air-gap) |
| **Read the Docs** | Python (hosting) | Depende (self-host RTD es pesado) | Server-side | Nativo | Sabor propio | Limitado | MIT (build) + hosting | Descartado (el valor de RTD es el hosting, que no usamos) |

---

## (1) Framework — MkDocs+Material vs Starlight vs el resto → **MkDocs + Material (v1), Starlight+Pagefind (plan B)**

El requisito que **manda** es air-gap 0-egress + cero toolchain nueva. **MkDocs Material** lo resuelve de raíz:
el plugin **`privacy`** descarga y **embebe** los assets externos (fuentes Google, iconos) en el build, y el
plugin **`offline`** hace que el sitio (incluida la búsqueda **lunr**) funcione **desde `file://`** sin
servidor de búsqueda ni CDN. Es **Python** — el mismo ecosistema que el backend FastAPI —, así que **no** suma
Node/JS al pipeline de docs. El white-label es **YAML** (`INHERIT` superpone un `mkdocs.<brand>.yml` sobre la
base), el versionado es **`mike`** (directorios estáticos `1.x`/`latest`/`dev`), la i18n es
**`mkdocs-static-i18n`**, y desde **v9.7.0 (nov-2025)** el paquete **Insiders** pasó a ser **gratis** (más
features sin coste).

**Contra honesto**: Material está reportado en **modo mantenimiento** (el autor acepta **fixes** pero **no
features nuevas**). No afecta al runtime (un sitio construido sigue funcionando), pero sí al **roadmap**. Por
eso el **plan B** es **Astro Starlight + Pagefind**: mejor **acabado visual** e **i18n de fábrica**, a costa de
introducir **toolchain Node/JS**. **Disparador de migración**: si el acabado visual y el i18n multi-idioma se
vuelven prioridad de negocio. El contenido markdown es **portable** entre ambos (bajo coste de migración).

Los demás se descartan para v1 por toolchain o por air-gap: **Docusaurus/Nextra/Fumadocs** arrastran
**React/Next** y suelen tirar de fuentes/analytics por defecto (egress a vigilar) y su white-label real exige
**swizzling** (tocar componentes ≈ fork parcial); **VitePress** es viable pero introduce **Vue**; **Docsify**
renderiza **en runtime en el navegador** (no pre-render → offline/SEO débil); **Mintlify/GitBook/RTD** son
**SaaS/hosted** y el air-gap se vuelve una pelea cuesta arriba.

**Veredicto v1/planB**: **v1 = MkDocs + Material**; **plan B = Astro Starlight + Pagefind**. Se documenta el
porqué (air-gap + toolchain) para que ningún PR "vuelva a Docusaurus por popularidad".

**Fuentes**:
- https://squidfunk.github.io/mkdocs-material/plugins/privacy/
- https://squidfunk.github.io/mkdocs-material/setup/building-for-offline-usage/
- https://squidfunk.github.io/mkdocs-material/insiders/ (Insiders gratis desde v9.7.0, nov-2025)
- https://starlight.astro.build/
- https://pagefind.app/

## (2) Empaquetado Docker — ¿cómo se entrega el sitio? → **imagen multi-stage → nginx estático**

El sitio es **HTML estático**: no hay razón para un runtime dinámico. La imagen se construye **multi-stage**
(stage 1: Python + MkDocs Material construye el sitio con `mkdocs build --strict`; stage 2: copia el `site/` a
una imagen **nginx** mínima). Resultado: una imagen pequeña, sin toolchain en runtime, que sirve estáticos y
**no hace egress**. Se etiqueta **por marca**: `basa-docs:<brand>-<version>` (trazabilidad + una marca por
instancia). Se enchufa al **docker-compose v1** como un servicio `docs` detrás del mismo proxy/TLS; en el
mundo **k8s/air-gap v2**, **Zarf** (020) la empaqueta en el bundle (SBOM + firma cosign) junto al resto de
imágenes pinneadas — **sin pull de registry en runtime**.

**Veredicto v1/v2**: **v1 = imagen multi-stage → nginx** en el compose; **v2 = misma imagen empaquetada por
Zarf** (020). ACME/auto-HTTPS **off** en air-gap (ver eje 8).

**Fuentes**:
- https://www.mkdocs.org/user-guide/deploying-your-docs/
- https://hub.docker.com/_/nginx
- https://zarf.dev/

## (3) Air-gap / 0-egress — ¿cómo se garantiza? → **`privacy` + `offline` + `--strict` + test de 0 egress**

El enemigo silencioso del air-gap en docs son los **assets externos por defecto**: fuentes de Google, iconos
por CDN, analytics. La garantía se compone en **tres capas**: (a) el plugin **`privacy`** de Material
**materializa** (descarga y embebe) los assets remotos en el build; (b) **`mkdocs build --strict`** **falla**
el build ante links internos rotos o referencias no resueltas (red de seguridad en CI); (c) un **test de
runtime** arranca la imagen con la **red saliente bloqueada** y verifica **0 requests a hosts externos**
navegando y buscando (SC-001). El plugin **`offline`** cierra el círculo: la búsqueda lunr funciona **sin
servidor**.

**Veredicto**: air-gap **verificable**, no declarativo: `privacy` (build) + `--strict` (CI) + test 0-egress
(runtime).

**Fuentes**:
- https://squidfunk.github.io/mkdocs-material/plugins/privacy/
- https://www.mkdocs.org/user-guide/configuration/ (`strict: true`)

## (4) Búsqueda offline — lunr vs Pagefind vs Algolia → **lunr built-in (v1), Pagefind (plan B); Algolia = NO**

**Algolia DocSearch** es el default de la industria y está **descartado**: es **SaaS** (índice + consultas van
a Algolia) → rompe el air-gap y mete egress + dependencia externa. Para v1, **Material** trae **lunr** como
buscador built-in y, con el plugin **`offline`**, el índice se **precomputa** y viaja **dentro de la imagen**,
funcionando sin backend de búsqueda. En el **plan B (Starlight)**, el estándar offline es **Pagefind**:
genera un índice estático fragmentado, pensado para sitios grandes servidos estáticos, **sin servidor de
búsqueda**. Ambos caminos mantienen 0-egress.

**Veredicto v1/planB**: **v1 = lunr built-in** (Material `offline`); **plan B = Pagefind** (Starlight).
**Algolia DocSearch = NO** (SaaS, air-gap-incompatible).

**Fuentes**:
- https://squidfunk.github.io/mkdocs-material/setup/setting-up-site-search/
- https://pagefind.app/
- https://docsearch.algolia.com/ (descartado: SaaS)

## (5) API reference single-source — ¿a mano o auto-generado? → **auto-generado desde el OpenAPI (FastAPI)**

El backend **FastAPI** ya expone un **OpenAPI** completo (single-source-of-truth del contrato de la API). El
API reference del sitio se **auto-genera en el build** desde ese esquema (vía plugins tipo
`mkdocs-swagger-ui-tag` / `neoteroi-mkdocs` / render de OpenAPI, a fijar en implementación) — **nunca** se
escribe a mano. Beneficio: **0 deriva** (un cambio de endpoint/campo se refleja al reconstruir). El
**config/env reference** se deriva de **`.env.example`**. Regla de honestidad SDD: el **resto** del contenido
(guías, deploy, compliance) es **corpus curado separado** y **NO** se auto-deriva de las **specs de Spec Kit**
(`specs/001-021/`): son audiencias distintas (ingeniería interna vs distribuidor/operador) y auto-derivarlas
filtraría **contexto interno** (deuda técnica, evidencia del demo, decisiones descartadas) al sitio de
producto.

**Veredicto**: **API reference auto-generado desde OpenAPI**; config reference desde `.env.example`; contenido
de producto **curado**, **sin** derivar las specs.

**Fuentes**:
- https://fastapi.tiangolo.com/reference/openapi/ (OpenAPI de FastAPI)
- https://swagger.io/specification/
- https://github.com/blueswen/mkdocs-swagger-ui-tag (render de OpenAPI en MkDocs — opción de implementación)

## (6) Estructura de contenido — ¿qué secciones y con qué semilla? → **9 secciones, sembradas del corpus**

La IA (arquitectura de información) del sitio v1 es de **9 secciones** para **distribuidor + operador**:
**Overview & arquitectura · Install/Deploy · White-label & branding · Administración · Integraciones & matriz ·
API reference · Compliance · Operaciones & troubleshooting · Release notes**. Tres ya tienen **semilla fuerte**
en `docs/`: `whitelabel-deployment.md` → Install/Deploy + Branding; `integration-surfaces.md` → Integraciones &
matriz; `compliance-policies.md` → Compliance. El resto se redacta nuevo. Toda la doc conserva la **leyenda de
estado** 🟢 HOY / 🟡 PARCIAL / 🔵 OBJETIVO (honestidad SDD). El docset **end-user (clínico)** es **otra
audiencia** → roadmap P3 (segundo nav-tree bajo el mismo contenedor).

**Veredicto**: 9 secciones técnicas; 3 sembradas del corpus, 4 nuevas, 2 derivadas (API/config); clínico =
roadmap.

**Fuentes**:
- `basa-guardian/docs/whitelabel-deployment.md`, `.../integration-surfaces.md`, `.../compliance-policies.md`
- https://diataxis.fr/ (marco de estructura de documentación: tutoriales/how-to/reference/explanation)

## (7) White-label — build-time vs config runtime → **config-as-data (YAML `INHERIT` / `envsubst`), never fork**

El modelo es **una marca por instancia** (igual que la 020): no hace falta theming multi-tenant dinámico. El
branding del sitio se aplica **sólo por config**: tokens `site_name`, `logo`, `favicon`, `palette`,
`extra.css`. El mecanismo es **overlay por herencia** — MkDocs soporta **`INHERIT`** para que un
`mkdocs.<brand>.yml` **superponga** los tokens de marca sobre la config base sin duplicar contenido — **o**
`envsubst` sobre una plantilla de config en build-time. El **contenido markdown se mantiene marca-neutro** por
defecto; cambiar de marca = cambiar la config de branding y **reconstruir la imagen** (`basa-docs:<brand>-…`),
**sin forkear** contenido ni tema (Principio VII). Esto evita el **swizzling** que exigen los frameworks React
para brandear (que es tocar componentes ≈ fork parcial).

**Veredicto**: **config-as-data por overlay `INHERIT` / `envsubst`**, contenido marca-neutro, imagen por marca,
never fork.

**Fuentes**:
- https://www.mkdocs.org/user-guide/configuration/#configuration-inheritance (`INHERIT`)
- https://squidfunk.github.io/mkdocs-material/customization/ (colores/logo/extra.css)
- https://12factor.net/config

## (8) TLS en air-gap — Caddy auto-HTTPS vs nginx → **nginx estático / Caddy `auto_https off`**

Servir el sitio detrás de **Caddy con auto-HTTPS** dispararía **ACME contra Let's Encrypt** en el arranque →
**egress** que rompe el air-gap. En instalaciones air-gapped se sirve el estático con **nginx** (sin ACME) **o**
**Caddy con `auto_https off`** (TLS por certificado provisto por el cliente, no por ACME). El sitio es HTML
estático; el TLS lo termina la **capa de proxy** del deploy (020), no el contenedor de docs. En k8s v2, el
ingress **Traefik** (default de k3s, 020) cubre TLS.

**Veredicto v1/v2**: **v1 = nginx estático** (o Caddy `auto_https off`) en air-gap; **v2 = Traefik** (020).

**Fuentes**:
- https://caddyserver.com/docs/automatic-https#disabling-automatic-https
- https://docs.k3s.io/networking/networking-services (Traefik ingress)

---

## Recomendación integrada (v1 entregable / plan B / v2 roadmap)

- **v1 (MVP entregable)**: **MkDocs + Material** construye el sitio con **`privacy`+`offline`+`--strict`**
  (air-gap 0-egress verificado por test), empaquetado en una **imagen multi-stage → nginx** por marca
  (`basa-docs:<brand>-<version>`) que se enchufa al **docker-compose**; **búsqueda lunr offline**; **API
  reference auto-generado desde el OpenAPI** de FastAPI + **config reference desde `.env.example`**; **contenido
  sembrado** del corpus `docs/*.md` (9 secciones, leyenda de estado); **white-label por config** (`INHERIT`/
  `envsubst`, contenido marca-neutro); **versionado `mike`** + **i18n `mkdocs-static-i18n` ES/EN**. TLS por
  nginx/`auto_https off` en air-gap.
- **plan B (documentado)**: **Astro Starlight + Pagefind** si pesan el **acabado visual** y el **i18n de
  fábrica** — a costa de introducir **toolchain Node/JS**. Contenido markdown portable → coste de migración
  bajo.
- **v2 (roadmap)**: la imagen del sitio empaquetada por **Zarf** (020) en el bundle air-gapped k8s (SBOM +
  cosign), servida detrás de **Traefik** (ingress k3s); docset **end-user (clínico)** como segundo nav-tree
  (US7, P3).

## Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| **Material en modo mantenimiento** (fixes sí, features no). | Roadmap: sin features nuevas del tema. No afecta runtime. | Plan B **Starlight+Pagefind** documentado con disparador (acabado visual + i18n); contenido markdown portable. |
| **Fuentes Google / CDN por defecto** → egress oculto. | Rompe air-gap 0-egress. | Plugin **`privacy`** (embebe assets) + **`--strict`** (build) + **test 0-egress** (runtime, SC-001). |
| **Algolia DocSearch por costumbre** (buscador SaaS). | Rompe air-gap + dependencia externa. | **Prohibido** (FR-015): lunr built-in / Pagefind; check de config sin claves SaaS. |
| **`mike` no es first-party** (plugin de comunidad). | Riesgo de mantenimiento del versionador. | Estándar de facto; produce **directorios estáticos** (lo publicado sobrevive); versión fijada. |
| **Caddy auto-HTTPS → ACME/Let's Encrypt en air-gap.** | Egress en el arranque rompe el install air-gapped. | **nginx estático** o Caddy **`auto_https off`**; TLS por cert provisto (020), no ACME. |
| **Deriva del API reference** (si se escribe a mano). | Reference desincronizado con el código. | **Single-source** desde el OpenAPI de FastAPI, regenerado en cada build (US5). |
| **Fuga de contexto interno** (derivar el sitio de las specs de Spec Kit). | Deuda técnica/evidencia interna publicada al cliente. | **Prohibido** (FR-018): contenido de producto **curado separado**; sólo API/config se auto-derivan (OpenAPI/`.env.example`). |
| **Doble toolchain** si se migra a Starlight. | Node/JS entra al pipeline de docs. | v1 evita el coste (MkDocs Python-nativo); si se migra, es coste **consciente** documentado. |
| **Nombre de motor/proveedor filtrado** en un título/asset heredado del corpus. | Rompe naming neutro (Principio VII). | Check de branding en build (grep de nombres prohibidos sobre el HTML publicado, FR-013). |
| **Traducción EN incompleta.** | 404 o navegación rota en EN. | Fallback **explícito** al idioma primario ES (`mkdocs-static-i18n`), no 404 (US6). |

## Fuentes (consolidado)

- MkDocs: https://www.mkdocs.org/ · deploying: https://www.mkdocs.org/user-guide/deploying-your-docs/ ·
  `INHERIT`: https://www.mkdocs.org/user-guide/configuration/#configuration-inheritance
- Material for MkDocs: https://squidfunk.github.io/mkdocs-material/ · privacy plugin:
  https://squidfunk.github.io/mkdocs-material/plugins/privacy/ · offline:
  https://squidfunk.github.io/mkdocs-material/setup/building-for-offline-usage/ · search:
  https://squidfunk.github.io/mkdocs-material/setup/setting-up-site-search/ · insiders (gratis v9.7.0):
  https://squidfunk.github.io/mkdocs-material/insiders/
- Versionado `mike`: https://github.com/jimporter/mike
- i18n: https://github.com/ultrabug/mkdocs-static-i18n
- Astro Starlight: https://starlight.astro.build/ · Pagefind: https://pagefind.app/
- Docusaurus: https://docusaurus.io/ · Nextra: https://nextra.site/ · Fumadocs: https://fumadocs.dev/ ·
  VitePress: https://vitepress.dev/ · Docsify: https://docsify.js.org/
- SaaS descartados (air-gap): Mintlify https://mintlify.com/ · GitBook https://www.gitbook.com/ ·
  Read the Docs https://about.readthedocs.com/ · Algolia DocSearch https://docsearch.algolia.com/
- OpenAPI de FastAPI: https://fastapi.tiangolo.com/reference/openapi/ · OpenAPI spec:
  https://swagger.io/specification/ · render en MkDocs: https://github.com/blueswen/mkdocs-swagger-ui-tag
- Estructura: https://diataxis.fr/ · config-as-data: https://12factor.net/config
- Air-gap Zarf (020): https://zarf.dev/ · Caddy auto-HTTPS off:
  https://caddyserver.com/docs/automatic-https#disabling-automatic-https
