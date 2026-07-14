# Feature Specification: Product Documentation Site (Distribuidor & Operador)

**Feature Branch**: `022-product-documentation-site`

**Created**: 2026-07-14

**Status**: Draft

**Input**: User description: "Un SITIO de documentación de producto (no la doc interna de Spec Kit): la
doc para el DISTRIBUIDOR y el OPERADOR que instalan, marca-blanquean, administran e integran Basa Guardian.
Debe ser un CONTENEDOR propio, estático, air-gap-first (0 requests salientes en runtime), white-label por
CONFIG sin fork, con búsqueda offline, API reference single-source desde el OpenAPI, versionado por release
e i18n ES/EN. La semilla es el corpus markdown que ya existe en `basa-guardian/docs/`."

---

## Contexto y honestidad SDD *(léelo antes que nada)*

Esta feature es **GREENFIELD** — no hay un sitio de documentación que portar. La honestidad manda decir qué
existe hoy y qué no:

- **Lo único que hay hoy como "doc" es una página React hardcodeada**: `frontend/src/pages/DocsPage.tsx`
  (~460 líneas). Es un componente TSX con las secciones **clavadas en código** (un `type Section` de 8
  entradas: overview, projects, dpas, dsr, retention, dpo, pipeline, checklist), **sólo de compliance**,
  **sólo en español**, con tablas y badges reimplementados a mano en JSX. **No escala**: cada página nueva
  es código, cada cambio de copy es un deploy del frontend, no hay búsqueda, no hay versionado, no hay i18n,
  y **mezcla la doc de producto con el bundle de la app**. Es una vitrina, no un sistema de documentación.
- **Ya existe un corpus markdown separado y curado en `basa-guardian/docs/`** que es la **SEMILLA** real del
  sitio, escrito con la misma disciplina de honestidad SDD (leyenda 🟢 HOY / 🟡 PARCIAL / 🔵 OBJETIVO):
  - `docs/whitelabel-deployment.md` (~24 KB) — runbook de deploy del **distribuidor** (modelo de negocio,
    OpenTofu, branding pack, secretos, tabla estado-actual-vs-objetivo).
  - `docs/integration-surfaces.md` (~17 KB) — cheat-sheet de **integraciones** (superficies `base_url` /
    `browser` / `mcp`, matriz de compatibilidad, gotchas verificados en vivo).
  - `docs/compliance-policies.md` (~17 KB) — guía operativa de **compliance** (GDPR/AI-Act, DPA, DSR,
    retención, panel DPO).
- **El repo usa GitHub Spec Kit** (`.specify/`): las specs 001–021 son la doc **interna** de ingeniería.
  Esta feature **NO** las convierte en el sitio de producto — audiencias distintas y riesgo de fuga de
  contexto interno (ver US5 y Assumptions).

**Qué es esta spec, honestamente**: especifica un **servicio `docs`** más en el stack — un contenedor propio,
**estático y air-gap-first** — que toma el corpus markdown ya existente como semilla, lo formaliza como sitio
navegable (con búsqueda offline, versionado e i18n), lo **white-labelea por config sin fork**, y auto-genera
el **API reference desde el OpenAPI del backend**. El contenido objetivo NO es aspiracional: gran parte ya
está escrito en `docs/*.md`; esta feature lo **empaqueta y lo hace escalar**, no lo inventa.

**Alcance honesto:**
- **Lo que se ENTREGA (v1):** el sitio como contenedor estático air-gapped; el docset de **DISTRIBUIDOR +
  OPERADOR** (técnico) sembrado del corpus existente; el white-label por config; la búsqueda offline; el API
  reference single-source; versionado por release e i18n ES/EN.
- **Lo que es ROADMAP explícito (se documenta, NO se entrega en v1):** el docset de **END-USER (clínico)** —
  audiencia y tono distintos (US7, P3); la paridad plena de idiomas más allá de ES/EN; la integración k8s v2
  (Zarf empaqueta la imagen del sitio junto al resto — se especifica el enganche, se materializa con la 020).
- **Decisión de framework tomada como decidida** (ver `research.md`, build-vs-buy): **MkDocs + Material**
  como primario, **Astro Starlight + Pagefind** como plan B documentado. La razón dominante es **air-gap como
  feature de primera clase** en Material (plugins `offline` + `privacy` → **0 llamadas externas en runtime**,
  requisito duro para clientes on-prem/VPN sin egress) y **cero toolchain nueva** (Python-nativo, el mismo
  ecosistema que el backend). Contra a declarar sin maquillaje: Material está reportado en **modo
  mantenimiento** (acepta fixes, no features nuevas) → riesgo de roadmap; el **disparador** para migrar a
  Starlight es si pesan el acabado visual y el i18n de fábrica (ver Edge Cases y `research.md`).

**Mapeo a principios de la constitución (v2.0.0):**
- **VII. Containerized & White-Label (config + seed, never fork)** — *principio rector de esta feature*. El
  sitio es un **container separado** (como backend/motor/frontend) y su marca se aplica por **config-as-data**
  (tokens de branding en YAML/env + assets montados), **nunca un fork**. La imagen-por-marca
  `basa-docs:<brand>-<version>` es la materialización del "config+seed, never fork" para la doc. Ningún nombre
  de motor/proveedor (LiteLLM, Anthropic, Presidio…) aparece en el sitio publicado.
- **VIII. Pipeline Transparency & Explainability** — *el sitio ES el artefacto de transparencia legible por
  humanos*. La constitución hace la transparencia **observable por request** (`pipeline_metadata`, el
  Playground como vitrina); esta feature la extiende al **plano de producto**: la doc explica el pipeline
  (masking → optimización → compliance → routing → unmask), las guardrails, la matriz de integraciones y la
  compliance de forma que un distribuidor/operador/auditor pueda **entender y verificar** el sistema. La doc
  es la capa de explicabilidad que rodea la observabilidad técnica.
- **II. Compliance & Governance FIRST (GDPR + EU AI Act)** — *relación de contenido, no de mecanismo*. El
  docset de compliance (GDPR Art.5/28/30, EU AI Act Art.50, retención, DPA, DSR) es **contenido de primera
  clase** del sitio, sembrado de `compliance-policies.md`; ser air-gap-first (0 egress) es además coherente
  con la postura de residencia/soberanía de datos del Principio II.
- *(Nota honesta)* Esta feature **no inventa** principios ni mecanismos de producto: empaqueta contenido ya
  escrito, con un servicio de infraestructura estándar. El único cruce con **IV (Onboarding as Data)** es por
  analogía: white-labelear la doc es **config + seed**, igual que onboardear un cliente.

Depende, en contenido, del corpus `docs/*.md` (semilla) y del **OpenAPI del backend FastAPI** (API reference).
En empaquetado, se enchufa al **docker-compose** (v1) y, como roadmap, al **k3s+Helm+Zarf** de la **020** (v2,
donde Zarf empaqueta la imagen del sitio junto al resto del bundle air-gapped).

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - El sitio como contenedor propio, estático y air-gapped (Priority: P1)

Un **operador** despliega Basa Guardian en un cliente **on-prem sin egress** (VPN sin salida a internet, caso
air-gap). El sitio de documentación corre como un **servicio `docs`** más del stack: una imagen construida en
**multi-stage** (build con MkDocs+Material → HTML estático servido por **nginx**), sin ningún runtime dinámico.
La garantía dura: **cero requests salientes en runtime** — ni fuentes de Google, ni CDNs de JS/CSS, ni
telemetría, ni buscador SaaS. Todo asset (fuentes, iconos, JS del buscador) va **embebido en la imagen**. El
sitio se integra al **docker-compose v1** como un servicio detrás del mismo proxy/TLS, y como roadmap al
**k3s+Helm+Zarf v2** de la 020 (donde **Zarf empaqueta la imagen** `basa-docs:<brand>-<version>` en el bundle
air-gapped, con SBOM y firma).

**Why this priority**: Es la razón de ser de la decisión de framework y el requisito que descalifica a la
mayoría de alternativas SaaS (Mintlify, GitBook, Algolia): un cliente air-gapped **no puede** depender de un
servicio externo para leer su documentación. Sin el contenedor estático 0-egress, no hay doc entregable a un
cliente on-prem. Materializa el Principio VII (container separado, white-label) desde el empaquetado.

**Independent Test**: Construir la imagen del sitio, arrancarla con la **red saliente bloqueada** (sin
resolución DNS / sin ruta a internet), navegar todas las secciones y ejecutar la búsqueda. Verificar: (a) el
sitio carga y funciona **completo** offline; (b) el monitor de red registra **0 requests a hosts externos**
(sólo a sí mismo); (c) `mkdocs build --strict` pasó en el build (falla ante links rotos / assets externos no
resueltos); (d) el servicio levanta en el compose detrás del proxy sin puertos nuevos hacia fuera.

**Acceptance Scenarios**:

1. **Given** la imagen del sitio construida (multi-stage → nginx), **When** se arranca con la red saliente
   **bloqueada**, **Then** todas las páginas y assets (fuentes, iconos, JS de búsqueda) cargan desde la propia
   imagen y **0** requests salen a hosts externos.
2. **Given** el build del sitio, **When** corre en CI/local, **Then** usa `mkdocs build --strict` (falla ante
   links internos rotos o referencias a assets externos no embebidos) y los plugins `privacy`/`offline` de
   Material materializan los assets remotos localmente.
3. **Given** el docker-compose v1, **When** se añade el servicio `docs`, **Then** queda como un contenedor
   separado (Principio VII) servido detrás del mismo proxy/TLS, sin exponer egress nuevo.
4. **Given** el roadmap k8s v2 (020), **When** se empaqueta el release, **Then** la imagen
   `basa-docs:<brand>-<version>` entra en el bundle **Zarf** (air-gap-native, SBOM + firma) igual que el resto
   de imágenes pinneadas — documentado como enganche, materializado por la 020.

---

### User Story 2 - Contenido de Distribuidor + Operador sembrado del corpus existente (Priority: P1)

Un **distribuidor** (que instala, marca-blanquea y da soporte) y un **operador** (que administra el día a día)
necesitan una documentación **técnica, navegable y completa**, no una página hardcodeada de compliance. El
sitio organiza el contenido en secciones de primera clase, **sembradas del corpus `docs/*.md` ya existente** y
completadas con esta IA (arquitectura de información): **Overview & arquitectura** · **Install/Deploy** (v1
VM+compose, v2 k3s+Zarf; AWS/Azure/GCP/on-prem/air-gapped; OpenTofu; secretos) · **White-label & branding** ·
**Administración** (multi-tenant, RBAC, guardrails, budgets, SSO, licencias/seats) · **Integraciones & matriz
de compatibilidad** · **API reference** · **Compliance** (GDPR/AI-Act, Art.30, retención) · **Operaciones &
troubleshooting** · **Release notes**. La audiencia es **DISTRIBUIDOR + OPERADOR** (técnica); el docset clínico
de end-user queda para US7 (P3).

**Why this priority**: Es el **valor** del sitio: sin contenido curado para las audiencias que instalan y
operan, el contenedor de US1 está vacío. Gran parte ya está escrita (`whitelabel-deployment.md`,
`integration-surfaces.md`, `compliance-policies.md`); esta story la **estructura y la hace escalar** fuera del
TSX hardcodeado. Materializa el Principio VIII (la doc como explicabilidad del producto).

**Independent Test**: Verificar que el sitio publica las 9 secciones con contenido real (no placeholders), que
las tres piezas del corpus (`whitelabel-deployment.md`, `integration-surfaces.md`, `compliance-policies.md`)
están migradas a sus secciones (Install/Deploy + Branding, Integraciones, Compliance respectivamente) sin
pérdida de la leyenda de estado 🟢/🟡/🔵, y que la navegación lateral refleja la IA acordada.

**Acceptance Scenarios**:

1. **Given** el sitio construido, **When** se navega, **Then** existen las secciones **Overview &
   arquitectura**, **Install/Deploy**, **White-label & branding**, **Administración**, **Integraciones &
   matriz**, **API reference**, **Compliance**, **Operaciones & troubleshooting** y **Release notes**.
2. **Given** el corpus existente, **When** se siembra el sitio, **Then** `whitelabel-deployment.md` alimenta
   **Install/Deploy** + **White-label & branding**, `integration-surfaces.md` alimenta **Integraciones &
   matriz** y `compliance-policies.md` alimenta **Compliance**, conservando la **leyenda de estado**
   (🟢 HOY / 🟡 PARCIAL / 🔵 OBJETIVO) que da honestidad SDD.
3. **Given** la sección **Administración**, **When** se consulta, **Then** cubre multi-tenant, RBAC (super/
   tenant-admin, compliance_officer, client), guardrails, budgets, SSO y licencias/seats (relación con la 021).
4. **Given** el TSX hardcodeado actual (`DocsPage.tsx`), **When** el sitio entra en servicio, **Then** la doc
   de producto **deja de vivir** en el bundle del frontend (queda como redirección/enlace al sitio, o se
   retira) — la doc ya no es código de la app.

---

### User Story 3 - White-label del sitio por config, sin fork (Priority: P1)

El **distribuidor** revende Basa Guardian bajo **su propia marca**. El sitio de documentación debe
white-labelearse **por configuración, nunca por fork**: un conjunto acotado de **tokens de marca** —
`site_name`, `logo`, `favicon`, `palette` (colores primarios/acento), `extra.css` (overrides finos) — que se
aplican **sin tocar el contenido ni el código del tema**. El mecanismo es **overlay por herencia** (`INHERIT`
de MkDocs para superponer un `mkdocs.<brand>.yml` sobre la config base) **o** `envsubst` en build-time sobre
una plantilla de config; el contenido markdown se mantiene **marca-neutro** por defecto. Cada marca produce
una **imagen propia trazable** `basa-docs:<brand>-<version>` (una marca por instancia, coherente con el modelo
1-instancia-por-cliente y con la trazabilidad air-gap).

**Why this priority**: Es el Principio **VII** aplicado a la doc: *config + seed, never fork*. Sin white-label
por config, cada distribuidor forzaría un **fork del sitio** (deriva, coste, el error que hundió al producto
original). Es P1 porque el sitio es un **entregable comercial del distribuidor**, no un blog interno.

**Independent Test**: Construir el sitio con dos brand-packs distintos (marca A y marca B) cambiando **sólo**
la config de branding (site_name/logo/favicon/palette/extra.css), **sin** editar contenido ni tema. Verificar:
(a) ambos sitios difieren en nombre/logo/favicon/paleta y comparten el mismo contenido; (b) 0 líneas de
contenido o de código de tema cambiaron entre marcas; (c) cada build produce una imagen etiquetada
`basa-docs:<brand>-<version>`; (d) el sitio publicado **no** menciona ningún motor/proveedor externo.

**Acceptance Scenarios**:

1. **Given** un brand-pack (site_name, logo, favicon, palette, extra.css), **When** se construye el sitio,
   **Then** la marca se aplica **sólo** por config (overlay `INHERIT` o `envsubst`), sin tocar contenido ni
   código del tema (Principio VII, never fork).
2. **Given** dos marcas distintas, **When** se construyen, **Then** producen dos imágenes trazables
   `basa-docs:<brand>-<version>` que comparten el mismo contenido y difieren sólo en los tokens de marca.
3. **Given** el sitio publicado bajo cualquier marca, **When** se inspecciona, **Then** **no** aparece ningún
   nombre de motor/proveedor (LiteLLM, Anthropic, OpenAI, Presidio…) en páginas, títulos, footer ni assets
   (naming neutro, Principio VII).
4. **Given** el modelo 1-marca-por-instancia, **When** se despliega, **Then** el branding es **config-as-data**
   (env + assets), sin theming multi-tenant dinámico ni build por-cada-request.

---

### User Story 4 - Búsqueda offline, nunca SaaS (Priority: P2)

Un operador busca "retención" o "air-gap" en el sitio y obtiene resultados **sin que salga un solo byte hacia
un servicio externo**. La búsqueda es **offline**: el buscador **built-in de Material** (índice `lunr`
empaquetado, activado por el plugin `search`/`offline` para que funcione desde `file://` y sin servidor de
búsqueda) **o**, si el plan B (Starlight) se activa, **Pagefind** (índice estático generado en build). Queda
**explícitamente prohibido** cualquier buscador **SaaS** (Algolia DocSearch y equivalentes): rompen el
air-gap y meten egress + dependencia externa.

**Why this priority**: La búsqueda es esperada en cualquier docset serio, pero es P2 porque el contenido (US2)
y el contenedor (US1) ya entregan valor navegable. La restricción **anti-SaaS** es load-bearing para no
romper el 0-egress de US1; por eso se fija como requisito y no como detalle de implementación.

**Independent Test**: Con la red saliente **bloqueada**, ejecutar varias búsquedas y verificar que devuelven
resultados relevantes **sin** ningún request externo (el índice se sirve desde la propia imagen). Confirmar
que **no** hay ninguna clave/endpoint de Algolia u otro buscador SaaS en la config ni en el HTML publicado.

**Acceptance Scenarios**:

1. **Given** el sitio air-gapped, **When** el usuario busca un término, **Then** el buscador resuelve contra
   un **índice local** (lunr built-in de Material / Pagefind en el plan B) sin egress.
2. **Given** la config del sitio, **When** se audita, **Then** **no** existe integración con un buscador
   **SaaS** (Algolia DocSearch prohibido); el índice se genera en build y viaja dentro de la imagen.
3. **Given** el plugin `offline` de Material, **When** el sitio se sirve sin servidor (o desde nginx estático),
   **Then** la búsqueda sigue funcionando (índice precomputado, sin backend de búsqueda).

---

### User Story 5 - API reference single-source desde el OpenAPI (Priority: P2)

El **API reference** del sitio NO se escribe a mano: se **auto-genera en el build** desde el **OpenAPI que ya
expone el backend FastAPI** (single-source-of-truth). El **config/env reference** se genera desde
`.env.example`. El **resto del contenido** (guías, deploy, compliance) es **corpus separado curado** — y aquí
está la regla de honestidad: **NO se deriva de las specs de Spec Kit** (001–021). Son audiencias distintas
(ingeniería interna vs distribuidor/operador) y derivar automáticamente filtraría **contexto interno** (deuda
técnica, decisiones descartadas, evidencia del demo) al sitio de producto.

**Why this priority**: El single-source del API reference elimina la **deriva** (el reference a mano se
desincroniza con el código en la primera semana). Es P2 porque el sitio ya es útil con el contenido curado;
el API reference auto-generado lo hace **confiable**. La regla "no derivar de las specs" evita una fuga de
contexto que sería difícil de revertir una vez publicada.

**Independent Test**: Cambiar un endpoint o un campo en el backend, reconstruir el sitio, y verificar que el
API reference publicado **refleja el cambio** sin edición manual. Verificar que **ninguna** página del sitio se
genera automáticamente desde `specs/0XX-*/` (Spec Kit), y que el config reference sale de `.env.example`.

**Acceptance Scenarios**:

1. **Given** el OpenAPI del backend FastAPI, **When** se construye el sitio, **Then** el **API reference** se
   genera desde ese esquema (single-source), sin páginas de endpoints escritas a mano.
2. **Given** un cambio en un endpoint/campo del backend, **When** se reconstruye, **Then** el API reference
   publicado refleja el cambio automáticamente (0 deriva).
3. **Given** `.env.example`, **When** se construye el sitio, **Then** el **config/env reference** se deriva de
   ese archivo (una fuente de verdad para las variables).
4. **Given** las specs de Spec Kit (`specs/001-021/`), **When** se construye el sitio, **Then** **ninguna**
   página se auto-deriva de ellas (audiencias distintas; se evita la fuga de contexto interno); el contenido
   de producto es corpus **curado** separado.

---

### User Story 6 - Versionado por release e i18n ES/EN (Priority: P2)

Un operador de una instalación en la versión `1.4` necesita leer la doc **de su versión**, no la del último
release. El sitio se **versiona por release** con **`mike`** (el versionador de MkDocs: publica `1.x`, `latest`,
`dev` como directorios versionados con un selector). Y el contenido se ofrece en **ES/EN** con
**`mkdocs-static-i18n`** (una carpeta/sufijo por idioma, con selector de idioma). ES es el idioma primario del
corpus actual; EN es el segundo idioma objetivo. La paridad plena de más idiomas es roadmap.

**Why this priority**: Versionado e i18n son necesarios para un producto **distribuido a terceros** con
releases múltiples y clientes en distintas regiones, pero son P2 porque un docset **single-version en ES** ya
es entregable (US1–US3). Se especifica ahora para no clavar decisiones (mike/i18n) que serían costosas de
retro-encajar después.

**Independent Test**: Publicar dos versiones (`1.x` y `latest`) con `mike` y verificar que el selector cambia
entre ellas y que cada una sirve su contenido. Cambiar el idioma ES↔EN con el selector y verificar que la
misma página existe en ambos (o degrada explícitamente al idioma primario si falta traducción).

**Acceptance Scenarios**:

1. **Given** dos releases del producto, **When** se publican con `mike`, **Then** el sitio ofrece un selector
   de versión (`1.x` / `latest` / `dev`) y cada versión sirve su propia doc.
2. **Given** el contenido en ES y EN, **When** se construye con `mkdocs-static-i18n`, **Then** el sitio ofrece
   un selector de idioma ES/EN y sirve la variante correcta por página.
3. **Given** una página sin traducción EN, **When** se navega en EN, **Then** degrada de forma **explícita**
   (fallback al idioma primario ES marcado), sin romper la navegación.

---

### User Story 7 - Docset de end-user (clínico) como roadmap futuro (Priority: P3)

El equipo quiere, a futuro, un **docset de end-user (clínico)**: la persona no técnica que usa la IA
gobernada dentro de un centro sanitario. Hoy **NO** entra en v1: audiencia, tono y contenido son distintos del
docset técnico (distribuidor/operador). Esta story **documenta** que el sitio está preparado para alojar un
segundo docset (otra sección/nav-tree, mismo contenedor y mecanismo de white-label/i18n) como **roadmap
explícito**, sin entregarlo.

**Why this priority**: Es aditivo y de otra audiencia; venderlo como hecho rompería la honestidad SDD. P3
porque el sitio técnico (US1–US6) cubre a quien instala/opera/integra; el docset clínico es una extensión de
audiencia, no un mecanismo nuevo.

**Independent Test**: Verificar que la spec/arquitectura del sitio contempla un **segundo docset** (nav-tree
separado bajo el mismo contenedor) y lo marca **NO implementado / roadmap**, sin exigir contenido clínico en
esta feature.

**Acceptance Scenarios**:

1. **Given** la arquitectura del sitio, **When** se documenta el roadmap, **Then** el docset **end-user
   (clínico)** figura como **futuro (P3)**, con la nota de que reusa contenedor + white-label + i18n pero con
   audiencia/tono propios.
2. **Given** v1, **When** se entrega, **Then** **no** se publica contenido clínico (se evita prometer lo que
   no existe); la sección queda reservada en la IA.

---

### Edge Cases

- **Material en "modo mantenimiento"**: MkDocs Material está reportado aceptando **fixes pero no features
  nuevas**. Riesgo de roadmap (no de runtime): el sitio construido sigue funcionando. Mitigación: el plan B
  **Astro Starlight + Pagefind** queda documentado con su **disparador de migración** — si pesan el acabado
  visual y el i18n de fábrica, se migra (contenido markdown es portable; ver `research.md`).
- **Versionado no first-party**: `mike` **no** es parte del core de MkDocs (es un plugin de comunidad). Riesgo
  de mantenimiento. Mitigación: `mike` es el estándar de facto y produce **directorios estáticos versionados**
  (si `mike` desapareciera, los artefactos ya publicados siguen sirviéndose). Se fija la versión de `mike`.
- **Assets externos ocultos (fuentes Google / CDN)**: los temas de doc suelen tirar de **Google Fonts** o CDNs
  por defecto → egress silencioso que rompe el air-gap. Mitigación **triple**: plugin `privacy` de Material
  (materializa/embebe los assets remotos en el build), `mkdocs build --strict` (falla el build si algo no
  resuelve local) y el **test de 0 egress** de US1 (red bloqueada en runtime).
- **Caddy + ACME sale a Let's Encrypt en air-gap**: si el sitio se sirviera detrás de **Caddy** con auto-HTTPS,
  Caddy intentaría **ACME contra Let's Encrypt** → egress que rompe el air-gap. Mitigación: servir el sitio con
  **nginx** estático (sin ACME) **o** `auto_https off` en Caddy en instalaciones air-gapped (TLS por cert
  provisto, no por ACME). El sitio en sí es HTML estático; el TLS lo termina la capa de proxy.
- **Doble toolchain (JS)**: MkDocs+Material **no** agrega toolchain nueva (Python, el mismo del backend). El
  plan B (Starlight/Astro/Pagefind) **sí** introduce **Node/JS** en el pipeline de docs. La decisión de v1
  (MkDocs) evita ese coste; si se migra a Starlight, la doble toolchain es un coste **consciente** documentado.
- **Deriva del API reference**: un API reference escrito a mano se **desincroniza** del código. Mitigado por
  US5 (single-source desde el OpenAPI, regenerado en cada build). Riesgo residual: si el OpenAPI del backend
  está incompleto (endpoints sin schema), el reference hereda esos huecos — se marca como calidad del OpenAPI,
  no del sitio.
- **Fuga de contexto interno si se derivan las specs**: derivar el sitio de `specs/0XX-*` (Spec Kit) filtraría
  deuda técnica, evidencia del demo y decisiones descartadas al sitio **de producto**. Prohibido por US5: el
  contenido de producto es corpus **curado separado**; sólo el API/config reference se auto-deriva (de OpenAPI/
  `.env.example`, no de specs).
- **Título/copy con nombre de motor**: si un asset o un título heredado del corpus menciona un proveedor
  (LiteLLM/Anthropic…), rompe el naming neutro (Principio VII). Mitigación: check de branding en build (grep
  de nombres prohibidos sobre el HTML publicado) — falla si aparece.
- **Traducción EN incompleta**: si una página existe en ES pero no en EN, el sitio **no** debe romper: degrada
  con fallback explícito al idioma primario (US6), no con un 404.

## Requirements *(mandatory)*

### Functional Requirements

**Contenedor estático air-gap-first (US1)**
- **FR-001**: El sistema MUST construir el sitio como una imagen **multi-stage** (build MkDocs+Material → HTML
  estático servido por **nginx**), sin runtime dinámico, como un **servicio `docs`** separado (Principio VII).
- **FR-002**: El sitio MUST funcionar **completo offline**: **0 requests salientes en runtime** (fuentes,
  iconos, JS de búsqueda, todo embebido en la imagen); ningún host externo se contacta al navegar/buscar.
- **FR-003**: El build MUST usar `mkdocs build --strict` (falla ante links internos rotos o assets externos no
  embebidos) y los plugins **`privacy`** (materializa assets remotos) y **`offline`** de Material.
- **FR-004**: El servicio `docs` MUST integrarse al **docker-compose v1** detrás del proxy/TLS existente, sin
  exponer egress nuevo; y MUST documentar el enganche al **k3s+Helm+Zarf v2** de la 020 (Zarf empaqueta la
  imagen `basa-docs:<brand>-<version>` con SBOM+firma en el bundle air-gapped).

**Contenido Distribuidor + Operador (US2)**
- **FR-005**: El sitio MUST publicar las secciones: **Overview & arquitectura**, **Install/Deploy**,
  **White-label & branding**, **Administración**, **Integraciones & matriz de compatibilidad**, **API
  reference**, **Compliance**, **Operaciones & troubleshooting** y **Release notes**.
- **FR-006**: El contenido MUST sembrarse del corpus existente: `whitelabel-deployment.md` → **Install/Deploy**
  + **White-label & branding**; `integration-surfaces.md` → **Integraciones & matriz**; `compliance-policies.md`
  → **Compliance** — conservando la **leyenda de estado** 🟢 HOY / 🟡 PARCIAL / 🔵 OBJETIVO (honestidad SDD).
- **FR-007**: La sección **Administración** MUST cubrir multi-tenant, RBAC (super/tenant-admin,
  compliance_officer, client), guardrails, budgets, SSO y licencias/seats (relación con la 021).
- **FR-008**: La audiencia de v1 MUST ser **distribuidor + operador** (técnica); el docset **end-user
  (clínico)** MUST quedar como roadmap (US7), no publicado en v1.
- **FR-009**: Una vez en servicio el sitio, la doc de producto MUST dejar de vivir en el bundle del frontend
  (`DocsPage.tsx` queda como redirección/enlace al sitio o se retira): la doc ya **no** es código de la app.

**White-label por config, never fork (US3)**
- **FR-010**: El sistema MUST white-labelear el sitio **sólo por config** — tokens de marca `site_name`,
  `logo`, `favicon`, `palette`, `extra.css` — **sin** tocar contenido ni código del tema (Principio VII).
- **FR-011**: El mecanismo de branding MUST ser **overlay por herencia** (`INHERIT` sobre un
  `mkdocs.<brand>.yml`) **o** `envsubst` build-time sobre una plantilla de config; el contenido markdown MUST
  mantenerse **marca-neutro** por defecto.
- **FR-012**: Cada marca MUST producir una imagen **trazable** `basa-docs:<brand>-<version>` (una marca por
  instancia; config-as-data en runtime, sin theming multi-tenant dinámico).
- **FR-013**: El sitio publicado MUST NOT mencionar ningún nombre de motor/proveedor (LiteLLM, Anthropic,
  OpenAI, Azure, Presidio…) en páginas, títulos, footer ni assets; el build MUST verificarlo (check de naming
  neutro sobre el HTML publicado).

**Búsqueda offline, anti-SaaS (US4)**
- **FR-014**: El sistema MUST proveer **búsqueda offline** contra un **índice local** (lunr built-in de Material
  vía plugin `search`/`offline`; **Pagefind** en el plan B Starlight), servida desde la propia imagen.
- **FR-015**: El sistema MUST NOT integrar ningún buscador **SaaS** (Algolia DocSearch prohibido) — rompería el
  air-gap; el build MUST NOT contener claves/endpoints de un buscador externo.

**API reference single-source (US5)**
- **FR-016**: El **API reference** MUST auto-generarse en el build desde el **OpenAPI del backend FastAPI**
  (single-source-of-truth), sin páginas de endpoints escritas a mano.
- **FR-017**: El **config/env reference** MUST derivarse de `.env.example` (una fuente de verdad para las
  variables de configuración).
- **FR-018**: El contenido de producto MUST ser corpus **curado separado**; el sitio MUST NOT auto-derivar
  páginas de las specs de Spec Kit (`specs/0XX-*/`) — audiencias distintas + evita fuga de contexto interno.

**Versionado e i18n (US6)**
- **FR-019**: El sitio MUST versionarse por release con **`mike`** (selector `1.x`/`latest`/`dev`; cada versión
  sirve su propia doc; versión de `mike` fijada).
- **FR-020**: El sitio MUST ofrecer **i18n ES/EN** con **`mkdocs-static-i18n`** (selector de idioma; ES
  primario, EN segundo idioma); una página sin traducción EN MUST degradar con **fallback explícito** al
  idioma primario, sin 404.

**Roadmap end-user (US7)**
- **FR-021**: El sistema MUST documentar el **docset end-user (clínico)** como **roadmap (P3)** — reusa
  contenedor + white-label + i18n con audiencia/tono propios — y MUST NOT publicarlo en v1.

**Transversal**
- **FR-022**: La decisión de framework MUST quedar documentada: **MkDocs + Material** primario, **Astro
  Starlight + Pagefind** plan B, con el **disparador de migración** (acabado visual + i18n de fábrica) y el
  contra de Material en modo mantenimiento (ver `research.md`).
- **FR-023**: El sitio MUST servirse con **nginx estático** (o Caddy con `auto_https off`) en instalaciones
  air-gapped, para no disparar ACME/Let's Encrypt (egress) — el TLS lo termina la capa de proxy con cert
  provisto, no ACME.

### Key Entities *(include if feature involves data)*

- **Servicio `docs`** — *artefacto NUEVO (infra)*. Contenedor separado (imagen `basa-docs:<brand>-<version>`),
  multi-stage build → nginx estático; se enchufa al compose v1 y al bundle Zarf v2 (020). 0 egress en runtime.
- **Corpus de contenido (semilla + curado)** — *SEMILLA existente + NUEVO*. Markdown en `docs/` como fuente:
  `whitelabel-deployment.md`, `integration-surfaces.md`, `compliance-policies.md`; más el contenido nuevo por
  sección. Marca-neutro, con leyenda de estado 🟢/🟡/🔵.
- **Brand-pack (tokens de marca)** — *config NUEVO*. `site_name`, `logo`, `favicon`, `palette`, `extra.css`.
  Aplicado por overlay `INHERIT` o `envsubst`. Una marca por instancia (config-as-data, Principio VII).
- **`mkdocs.yml` (config base)** — *config NUEVO*. Nav-tree (IA), tema Material, plugins (`search`/`offline`,
  `privacy`, i18n, mike, API-gen). Config base marca-neutra; overlays por marca la superponen.
- **API reference (auto-generado)** — *derivado NUEVO*. Generado en build desde el **OpenAPI** del backend
  FastAPI (single-source). NO se escribe a mano.
- **Config/env reference (auto-generado)** — *derivado NUEVO*. Generado desde `.env.example`.
- **Índice de búsqueda offline** — *derivado NUEVO*. lunr (Material) / Pagefind (plan B), precomputado en build,
  embebido en la imagen. Sin buscador SaaS.
- **Versión/idioma** — *config NUEVO*. `mike` (versión: `1.x`/`latest`/`dev`) + `mkdocs-static-i18n` (ES/EN).
- **`DocsPage.tsx` (legacy a retirar)** — *existente a deprecar*. La página React hardcodeada (~460 líneas,
  compliance-only, ES-only) que el sitio reemplaza; queda como redirección o se retira (FR-009).

### Arquitectura de contenido (sitemap) *(artefacto central de US2 — FR-005/006)*

| Sección | Audiencia | Semilla (corpus existente) | Estado del contenido | Notas |
|---|---|---|---|---|
| **Overview & arquitectura** | Distribuidor + Operador | — (nuevo, resume constitución/stack) | 🟡 a redactar | Qué es el producto, stack en containers, pipeline (masking→…→unmask). |
| **Install/Deploy** | Distribuidor + Operador | `whitelabel-deployment.md` | 🟢 semilla fuerte | v1 VM+compose / v2 k3s+Zarf; AWS/Azure/GCP/on-prem/air-gap; OpenTofu; secretos (SOPS+age / OpenBao). Relación 020. |
| **White-label & branding** | Distribuidor | `whitelabel-deployment.md` (§branding pack) | 🟡 semilla parcial | Brand-pack, config-as-data runtime, never fork. |
| **Administración** | Operador | — (nuevo) | 🟡 a redactar | Multi-tenant, RBAC, guardrails, budgets, SSO, licencias/seats. Relación 013/021. |
| **Integraciones & matriz** | Distribuidor + Operador | `integration-surfaces.md` | 🟢 semilla fuerte | Superficies base_url/browser/mcp; matriz FUNCIONA/PARCIAL/NO/MCP-ONLY. Relación 019. |
| **API reference** | Operador (técnico) | — (auto-generado) | 🔵 auto-gen (US5) | Single-source desde OpenAPI FastAPI. Nunca a mano. |
| **Compliance** | Operador + DPO | `compliance-policies.md` | 🟢 semilla fuerte | GDPR (Art.5/28/30), EU AI Act (Art.50), DPA, DSR, retención, panel DPO. Relación 005/008 y Principio II. |
| **Operaciones & troubleshooting** | Operador | — (nuevo, + gotchas de `integration-surfaces.md`) | 🟡 a redactar | Runbook operativo, gotchas verificados, diagnóstico. |
| **Release notes** | Distribuidor + Operador | — (nuevo, por `mike`) | 🔵 por versión | Cambios por release; base del versionado (US6). |
| *(Roadmap)* **End-user (clínico)** | End-user | — | 🔵 P3 futuro (US7) | Otra audiencia/tono; reusa contenedor + white-label + i18n. NO en v1. |

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001 (0 egress air-gap)**: Con la red saliente **bloqueada**, el 100% del sitio (todas las páginas +
  búsqueda) funciona y se registran **0 requests a hosts externos** en runtime; `mkdocs build --strict` pasó
  en el build.
- **SC-002 (contenedor separado)**: El sitio corre como **servicio `docs`** propio en el compose v1 (imagen
  `basa-docs:<brand>-<version>`), servido estático por nginx, sin exponer egress nuevo; documentado el enganche
  Zarf v2.
- **SC-003 (contenido sembrado)**: Las 9 secciones existen con contenido real; las 3 piezas del corpus
  (`whitelabel-deployment.md`, `integration-surfaces.md`, `compliance-policies.md`) están migradas a sus
  secciones **conservando la leyenda de estado** 🟢/🟡/🔵; la doc de producto ya **no** vive en `DocsPage.tsx`.
- **SC-004 (white-label sin fork)**: Construir el sitio con 2 marcas distintas cambia **sólo** los tokens de
  branding: **0** líneas de contenido y **0** de código de tema difieren entre marcas; cada build produce su
  imagen `basa-docs:<brand>-<version>`; **0** menciones de motor/proveedor en el HTML publicado.
- **SC-005 (búsqueda offline)**: El 100% de las búsquedas resuelven contra el índice **local** con la red
  bloqueada; **0** integraciones con buscador SaaS (Algolia u otro) en config y HTML.
- **SC-006 (API reference sin deriva)**: Un cambio de endpoint/campo en el backend se refleja en el API
  reference publicado tras reconstruir, **sin edición manual**; **0** páginas del sitio auto-derivadas de
  `specs/0XX-*/` (Spec Kit).
- **SC-007 (versionado + i18n)**: El sitio ofrece selector de **versión** (≥2 versiones con `mike`) y selector
  de **idioma** ES/EN (`mkdocs-static-i18n`); una página sin traducción EN degrada con fallback explícito, no
  con 404.
- **SC-008 (roadmap honesto)**: El docset **end-user (clínico)** figura como **P3 roadmap** (no publicado en
  v1); la decisión de framework (MkDocs primario / Starlight plan B) y su disparador de migración están
  documentados en `research.md` (0 claims de que el plan B esté implementado).

## Assumptions

- **Es greenfield, con semilla real**: no hay sitio previo que portar, pero **sí** hay corpus markdown curado
  en `docs/` (`whitelabel-deployment.md`, `integration-surfaces.md`, `compliance-policies.md`) que es la
  semilla. La única "doc" en la app hoy es `frontend/src/pages/DocsPage.tsx` (~460 líneas, compliance-only,
  ES-only, hardcodeada) — se reemplaza, no se extiende.
- **Framework decidido**: **MkDocs + Material** es el primario y **Astro Starlight + Pagefind** el plan B
  documentado (ver `research.md`, build-vs-buy). El plan lo toma como **decidido**, no re-abre el trade-off;
  la razón dominante es air-gap de primera clase (`offline`+`privacy` → 0 egress) y cero toolchain nueva
  (Python-nativo). Contra asumido y declarado: Material en **modo mantenimiento** (riesgo de roadmap, no de
  runtime); disparador de migración = acabado visual + i18n de fábrica.
- **Air-gap es requisito duro, no nice-to-have**: hay clientes on-prem/VPN sin egress; el sitio **debe**
  funcionar 0-egress. Esto descalifica buscadores/hostings SaaS (Algolia, Mintlify, GitBook) como base y
  obliga al `privacy` plugin + `--strict` + test de 0 egress.
- **Audiencia v1 = distribuidor + operador (técnica)**: el docset clínico de end-user es **otra audiencia** y
  queda como roadmap P3 (US7). No se mezcla en v1 para no diluir el tono técnico.
- **El API reference sale del OpenAPI, no de las specs**: FastAPI ya expone OpenAPI (single-source). Las specs
  de Spec Kit (001–021) son doc **interna** de ingeniería: **no** se derivan al sitio de producto (audiencias
  distintas + fuga de contexto interno). El resto del contenido es corpus curado separado.
- **Enganche de deploy reusa 020, no lo re-diseña**: el sitio se integra al compose v1 y, como roadmap, al
  **k3s+Helm+Zarf v2** de la 020 (Zarf empaqueta la imagen). Esta spec **consume** el empaquetado de la 020; no
  re-especifica OpenTofu/secretos/TLS (los referencia). El TLS air-gap se sirve con nginx/`auto_https off`, no
  ACME (evita egress a Let's Encrypt).
- **Una marca por instancia (config-as-data)**: el white-label del sitio sigue el modelo 1-instancia-por-cliente
  de la 020 — branding por env+assets en runtime, imagen trazable por marca, **never fork**; sin theming
  multi-tenant dinámico.
- **`mike` e i18n son plugins de comunidad**: se asume `mike` (versionado) y `mkdocs-static-i18n` (ES/EN) con
  versión fijada; ambos producen artefactos estáticos (si el plugin quedara sin mantenimiento, lo ya publicado
  sigue sirviéndose). La paridad plena de más idiomas más allá de ES/EN es roadmap.
- **La doc es artefacto de transparencia, no de mecanismo**: esta feature **no** cambia el pipeline de producto
  ni añade principios; extiende la explicabilidad (Principio VIII) al plano de producto y empaqueta contenido
  ya escrito. El único cruce con IV (onboarding as data) es por analogía (white-label = config+seed).
