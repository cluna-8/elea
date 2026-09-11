# Resultados de investigación: generación de documentos (spec 045) y análisis exacto de datos (spec 046)

**Fecha**: 2026-09-10 · **Estado**: investigación cerrada, sin tocar código · **Alcance**: decidir QUÉ construir para las US2 de la spec 045 y la US1 de la spec 046.

**Método**: tres relevamientos en paralelo contra fuentes primarias (repos de GitHub y su API, npm/PyPI, Docker Hub, docs oficiales, advisories). Todos los números (estrellas, issues, fechas de release, precios) fueron leídos ese día. Cada dato tiene su URL en el detalle. Notas: el informe previo del laboratorio sobre DB-GPT referenciado en la tarea T050 de la spec 041 (`HARNES-PRUEBAS/reports/06_resumen_sesion_marketplace_punto4_y_puertos.md`) **ya no existe en disco**, así que esta evaluación arranca de cero.

---

> **Actualización 10-sep-2026 (misma fecha, más tarde)**: la Parte 1 se complementó con una segunda investigación dedicada a los enfoques agénticos (skills de documentos, CLIs de agentes de código en modo headless, servidores MCP de Office, sandboxes de ejecución de código y plataformas completas), en `RESULTADOS-INVESTIGACION-DOCGEN-AGENTICO.md`. Conclusión: la recomendación principal de abajo (motor de plantillas determinista) se mantiene como camino por defecto, y se agrega un "modo libre" agéntico opt-in (smolagents o Codex CLI sobre un contenedor efímero sin red). Ver ese documento para la arquitectura híbrida.

## Resumen ejecutivo (leer esto si no hay tiempo para más)

### Parte 1 — Generación de documentos desde plantillas

**Recomendación principal: motor de plantillas open source "por formato" dentro del backend, más Gotenberg para PDF.**

| Formato | Pieza | Licencia | Por qué |
|---|---|---|---|
| `.docx` | **docxtpl** (python-docx-template) | LGPL-2.1 | Única librería Python de plantillas Word madura y activa (Jinja2 dentro del .docx, loops, tablas, imágenes). Usada en producción legal por docassemble. |
| `.pptx` | **pptx-automizer** (Node, microservicio chico) | MIT | Única pieza OSS mantenida que toma el .pptx corporativo del cliente, clona la diapositiva tipo N veces y reemplaza texto/tablas/gráficos. Sin LibreOffice ni módulos pagos. |
| `.xlsx` | **openpyxl** | MIT | Abre el .xlsx plantilla y escribe celdas conservando estilos. |
| `.pdf` | **Gotenberg** (imagen `libreoffice-only`) | MIT | Convierte docx/pptx/xlsx a PDF/PDF-A por REST. 1 GB RAM por réplica. |

Contrato con el LLM: Azure OpenAI produce **JSON validado contra un schema derivado de la plantilla** (no XML ni código), el backend lo vuelca en la plantilla. Determinista, auditable, compatible con el enmascarado y presupuesto de 043/044. Costo: ~1,2 GB RAM extra, 0 en licencias.

**Alternativa: Carbone Community Edition en Docker (`carbone/carbone-ee` sin licencia).** Un solo servicio REST que cubre docx+pptx+xlsx+odt y PDF con un solo lenguaje de plantilla, LibreOffice adentro, offline declarado por el vendor. Condiciones: su licencia (Carbone Community License, v3+) **no es OSI** y prohíbe revender como "document-generation-as-a-service" (embebido en Eleia instalado en el cliente entra como "Value Added Product", pero que lo revise compliance); imágenes dinámicas/charts/HTML son Enterprise (1.500 a 2.940 US$/año).

**Lo que ya existe no alcanza**: el Document Generation Agent de AnythingLLM (motor actual del Hub) sí genera docx/pptx/pdf/xlsx desde la versión 1.12.0 (abril 2026) y funciona con Azure OpenAI y por API, pero **crea desde cero con tres temas de colores, sin plantillas**. Sirve como fallback para "documento genérico rápido", no para papelería/plantillas corporativas.

**"Open design"**: casi seguro se refería a **OpenDesign (nexu-io/open-design)**, "la alternativa open source a Claude Design" (Apache-2.0, 95k estrellas, releases diarios). Es una app de escritorio que usa un agente de código (Claude Code, Codex, etc.) para armar prototipos/slides en HTML y exportar a PPTX vía PptxGenJS. **No sirve como motor**: no parte de un .pptx del cliente, no tiene API de "generá desde este JSON", y es inestable (981 issues abiertas). Vale como inspiración de UX.

### Parte 2 — ¿DB-GPT para el análisis exacto de Excel/CSV?

**Recomendación: NO usar DB-GPT. Construir un módulo "Chat Tabular" propio en el backend Python con DuckDB in-process + Azure OpenAI, SQL solo-lectura.**

Razones, todas verificadas en código y advisories:

1. **No resuelve la queja de Tomás**: la escena Chat Excel de DB-GPT acepta **exactamente un archivo** (el endpoint rechaza más de uno con "Only one file is supported for Excel chat") y **solo la primera hoja**. Cruzar archivos exige forkear la escena y el endpoint.
2. **Es otra plataforma completa** (7 paquetes Python, front Next.js, MySQL/SQLite, Chroma, agentes, flows), no una librería. La API que sirve Chat Excel es la v1 interna no documentada, con respuestas en un formato "vis" pensado para su propio front.
3. **Historial de seguridad incompatible con un producto tipo Guardian**: CVE-2026-80104 crítica (RCE sin autenticación, agosto 2026), CVE-2025-51459 (RCE por upload de plugin), 8 advisories en 2025, issue abierta de ejecución de comandos sin auth.
4. **Privacidad**: manda 5 filas reales de muestra al LLM sin enmascarar y no valida que el SQL sea solo lectura.

Lo que DB-GPT hace por dentro es exactamente el patrón recomendado (cargar el archivo en DuckDB, mandar DDL + muestra al LLM, ejecutar el SQL). Hacerlo propio son unas 300 a 500 líneas en el FastAPI existente, sin contenedores ni bases nuevas, con joins entre archivos desde el día uno y reutilizando el enmascarado que ya tiene el Hub:

- Cada Excel/CSV subido se carga como tabla en una conexión DuckDB efímera por conversación (los tabulares **no** van al vector store: esa fue la causa raíz).
- Prompt: DDL de todas las tablas + 3 a 5 filas ya enmascaradas + "devolvé un único SELECT en dialecto DuckDB".
- Guardrails: validar con `sqlglot` que sea solo SELECT/WITH, DuckDB endurecido (`enable_external_access=false`, sin autoload de extensiones, `memory_limit`, `lock_configuration`), timeout, LIMIT por defecto, un reintento con el error.
- Respuesta: tabla + SQL ejecutado (auditable) + resumen corto.

**Plan B** (si SQL no alcanza para pivots complejos o gráficos): **PandasAI v3** (MIT salvo carpeta `ee/`, soporta múltiples dataframes y Azure vía LiteLLM) con su sandbox Docker obligatorio. Contras: ejecuta Python generado por el LLM, exige Python ≤3.11 y lleva más de 10 meses sin commits.

**Descartados**: Vanna.ai (repositorio archivado en marzo 2026), WrenAI (5 contenedores + modelado manual, sin subida de Excel en la versión OSS), Dataherald y sqlcoder (sin actividad desde 2024), Quadratic (cerró el código en 2026), Chat2DB/SQLChat (clientes SQL, no motores), LlamaIndex Pandas / open-interpreter / LibreChat Code Interpreter (código arbitrario).

---

## Tabla comparativa resumida — Parte 1

| Opción | Licencia | ¿OSI? | Air-gap | Plantilla real (.docx/.pptx del cliente) | Formatos | Mantenimiento (sep-2026) | Integración | Costo real |
|---|---|---|---|---|---|---|---|---|
| **docxtpl** | LGPL-2.1 | Sí | Sí | Sí, Jinja2 en docx | docx | 2,7k★, push jul-2026 | lib Python | $0 |
| **pptx-automizer** | MIT | Sí | Sí | Sí, clona slides del pptx del cliente | pptx | 240★, release ago-2026, 44k desc/sem | lib Node (microservicio) | $0; un mantenedor principal |
| **Gotenberg** | MIT | Sí | Sí | n/a (conversión) | office → pdf/pdf-a | 13k★, v8.36 ago-2026 | REST Docker | 512 MiB a 1 GB, 1 conversión concurrente por instancia |
| Carbone CE (npm v3 / docker v5 community) | CCL | **No** | Sí | Sí (loops y condiciones incluidos) | docx/pptx/xlsx/odt → pdf con LibreOffice | 2,1k★, push abr-2026 | REST Docker o lib Node | $0 CE; Enterprise 1.500 a 2.940 US$/año |
| AnythingLLM create-files (actual) | MIT | Sí | Sí | **No** (3 temas internos) | docx/pptx/pdf/xlsx/txt | v1.16.1 ago-2026 | ya desplegado; API con auto-aprobación de skill | $0 |
| docxtemplater core | MIT/GPLv3 | Sí | Sí | docx completo; pptx **solo sustitución de texto** | docx, pptx (xlsx pago) | 3,6k★, 5 issues, 557k desc/sem | lib Node | $0 docx; pptx útil 1.250 €/año (módulo Slides) |
| PptxGenJS | MIT | Sí | Sí | **No** abre pptx existente | pptx | 6,1k★, 296 issues, push nov-2025 | lib Node | $0 |
| python-pptx | MIT | Sí | Sí | Parcial, sin lenguaje de plantilla | pptx | **sin commits desde ago-2024** | lib Python | $0 + código propio |
| Templaters pptx en Python | MIT/Apache | Sí | Sí | Sí | pptx | **abandonados 2019 a 2021** | lib Python | riesgo alto |
| unoserver / LibreOffice headless | MIT / MPL | Sí | Sí | n/a | office → pdf | 932★, jun-2026 | daemon | ~1 GB RAM por instancia |
| ONLYOFFICE Document Builder | AGPL-3 / comercial | Sí | Sí | Por script JS, no placeholders | docx/pptx/xlsx/pdf | v9.4 may-2026 | SDK/CLI | AGPL viral; pesado |
| Collabora CODE | MPLv2 | Sí | Sí | No (editor + convertidor) | office → pdf | push sep-2026 | REST | pesado |
| Presenton | Apache-2.0 | Sí | Sí (Azure/Ollama, telemetría desactivable) | Re-crea el pptx como HTML/TSX usando un modelo con visión | pptx/pdf | 10,2k★, beta quincenal | Producto Docker + REST | Chromium+Next+FastAPI; requiere modelo con visión |
| PPTAgent | MIT | Sí | Parcial | Sí, edita slides de referencia con LLM+VLM | pptx | 5k★, v2.0 dic-2025 | Docker/CLI/MCP | GPU o VLM |
| OpenDesign ("open design") | Apache-2.0 | Sí | BYOK Azure | **No** | html/pdf/pptx | 95k★, 981 issues, release diario | App desktop, sin API de generación | inestable |
| Pandoc / Quarto | GPL-2+ / MIT | Sí | Sí | Solo estilos y 7 layouts fijos | md → docx/pptx | 46k★ / 6k★ | binario | $0; útil para informes largos "con la marca" |
| Marp / Slidev | MIT | Sí | Sí | No; el pptx son imágenes | pptx no editable | activos | CLI | descartado |

## Tabla comparativa resumida — Parte 2

| Criterio | DB-GPT Chat Excel | PandasAI v3 | Vanna.ai | WrenAI OSS | **DuckDB + Azure OpenAI (propio)** |
|---|---|---|---|---|---|
| Licencia | MIT | MIT + carpeta `ee/` propietaria | MIT (archivado) | Apache-2.0 core, AGPL posible en módulos futuros | MIT (duckdb) + código propio |
| Air-gapped | Sí, con trabajo (wheels, extensiones DuckDB, front) | Sí | Sí | Sí (5 contenedores) | Sí (pre-bundlear la extensión `excel`) |
| Múltiples archivos / joins | **No** ("Only one file is supported"); multi-hoja tampoco | Sí | Sí | Sí, con modelado MDL manual | **Sí, nativo** |
| Azure OpenAI | Sí (`proxy/openai` con `api_type=azure`; el TOML de ejemplo no existe) | Sí (LiteLLM) | Sí | Sí (LiteLLM) | Sí (ya está) |
| Qué ejecuta | SQL **sin validación solo-lectura** | **Python arbitrario** (sandbox Docker opcional) | SQL | SQL | SQL con allow-list SELECT + DuckDB endurecido |
| Enmascarado antes del LLM | No; manda 5 filas crudas | No | No | No | Reusa el pipeline de Eleia |
| Peso operativo | Plataforma de 7 paquetes + Next.js + BD + Chroma; imagen 552 MB | 1 lib + Docker; Python ≤3.11 | lib + vector store | 5 contenedores + modelado | 1 dependencia (`duckdb`, opcional `sqlglot`) |
| Actividad | 19,9k★, release cada 2 a 3 meses (v0.8.2 ago-2026) | 23,8k★, **sin commits desde oct-2025** | **archivado mar-2026** | 17,6k★, semanal | DuckDB muy activo |
| Seguridad | 8 GHSA 2025, CVE-2025-51459, **CVE-2026-80104 crítica (ago-2026)**, RCE abierta | riesgo de ejecución de código | n/a | sin CVEs conocidas | superficie mínima |
| Integración desde app externa | API v1 no documentada + parseo de formato "vis" | import Python | import | REST/MCP | endpoint propio en el FastAPI existente |
| Esfuerzo | Alto (desplegar + fork multi-archivo + interceptar prompt + endurecer) | Medio | n/a | Alto | **Bajo a medio: ~300 a 500 líneas** |

---

## Implicancias para las specs

- **Spec 045 US2**: el punto de integración queda como un servicio interno de "render" con contrato `{template_id, data_json} → archivo`. Fase 1: docxtpl + openpyxl en el backend Python y Gotenberg para PDF. Fase 2: microservicio Node con pptx-automizer para pptx. Mientras tanto, el create-files de AnythingLLM cubre el "documento genérico sin plantilla" por API (activar `AGENT_AUTO_APPROVED_SKILLS` y descargar por `/v1/document/generated-files/`). Hace falta la spec de backend anunciada en 045.
- **Spec 046 US1**: reemplazar la mención a DB-GPT por un módulo propio "Chat Tabular" (DuckDB + Azure OpenAI, SQL solo-lectura). Decisión de diseño pendiente en la spec (cruzar archivos o uno a la vez) se resuelve: **cruzar archivos sí, nativo**. El espacio de análisis exacto (US2) no indexa los tabulares en el vector store.
- **Riesgo común**: ninguna de las dos piezas necesita GPU, modelo nuevo ni contenedor pesado. La única dependencia nueva con estado es Gotenberg (stateless, 1 GB RAM).

---

# Detalle y fuentes

Lo que sigue son los tres relevamientos completos, con la URL de cada dato.


## Anexo A — Parte 1: Generación de documentos (docx/pptx/pdf/xlsx) desde el chat de Eleia Hub

Fecha de la investigación: 2026-09-10. Todos los números (stars, fechas, precios) fueron consultados ese día contra GitHub API, npm registry, PyPI y las páginas oficiales citadas.

Contexto de evaluación: gateway de IA on-premise / air-gapped, backend Python + cliente Node/Python, LLM = Azure OpenAI. Objetivo: el chat produce JSON/markdown y de ahí sale un `.pptx`/`.docx` (ideal `.pdf`/`.xlsx`) **a partir de una plantilla del cliente**, sin llamar a ningún SaaS.

---

### TAREA 1 — ¿Qué es "open design"?

**Veredicto: es casi seguro [nexu-io/open-design ("OpenDesign")](https://github.com/nexu-io/open-design).** Es el único proyecto con ese nombre exacto que hace generación de slides/documentos con IA, y es hoy uno de los repos más virales del rubro.

Datos verificados:

| Dato | Valor | Fuente |
|---|---|---|
| Licencia | Apache-2.0 | [GitHub API / repo](https://github.com/nexu-io/open-design) |
| Stars / issues abiertas | 95.384 stars, 981 issues abiertas | GitHub API (2026-09-10) |
| Último release | `open-design-v0.22.2`, 2026-09-10 (release casi diario) | [Releases](https://github.com/nexu-io/open-design/releases) |
| Qué es | "The open-source Claude Design alternative. Local-first desktop app. Your coding agent becomes the design engine: prototypes, landing pages, dashboards, slides, images & video — HTML/PDF/PPTX/MP4 export" | [README](https://github.com/nexu-io/open-design/blob/main/README.md) |
| Arquitectura | Daemon local (Express + SQLite) que orquesta un **CLI de agente de código** (Claude Code, Codex, Cursor, OpenCode, 26 CLIs) o un proxy BYOK `POST /api/proxy/{anthropic,openai,azure,google,ollama}/stream` con preset para **Azure OpenAI** | [README](https://github.com/nexu-io/open-design/blob/main/README.md) |
| Cómo hace slides | Genera decks en **HTML** con templates (`design-templates/html-ppt-*`, 15 templates × 36 temas) y exporta a HTML/PDF/PPTX/ZIP/MD. El PPTX sale de un skill `pptx-generator` que usa **PptxGenJS "from scratch"** | [skills/pptx-generator/SKILL.md](https://github.com/nexu-io/open-design/blob/main/skills/pptx-generator/SKILL.md) |
| Plantillas del cliente | **No.** Issue #1228 lo reconoce: "lacks native export to editable PPTX … users need to post-edit slides in PowerPoint to … embed corporate templates"; se discute un pipeline HTML→PDF→PPTX vía Playwright + LibreOffice | [Issue #1228](https://github.com/nexu-io/open-design/issues/1228) |
| Plataforma | App de escritorio macOS/Windows; Docker Compose (puerto 7456); "No prebuilt Linux artifact is currently published" | [README](https://github.com/nexu-io/open-design/blob/main/README.md), [install-guide](https://github.com/nexu-io/open-design/blob/main/docs/install-guide.md) |
| API programática | Expone `/api/skills`, `/api/design-templates`, `/api/plugins`, pero **no hay endpoint "generame un deck a partir de este JSON"**: el flujo es UI/chat + agente | [README](https://github.com/nexu-io/open-design/blob/main/README.md) |

Otros candidatos descartados con motivo:
- **OpenDocument / ODF** ([Wikipedia](https://en.wikipedia.org/wiki/OpenDocument)): es un formato de archivo, no una herramienta.
- **Presenton** ([repo](https://github.com/presenton/presenton)): se autodenomina "Open-Source AI Presentation Generator", no "open design"; lo evalúo abajo porque sí es candidato técnico.
- **Docxpresso, OnlyOffice DocSpace, Gamma, Plus AI, SlideSpeak**: nombres no relacionados; Gamma/Plus/SlideSpeak son SaaS cerrados (descartados por air-gap).
- **Marp / Slidev / reveal.js**: son frameworks markdown→slides HTML; no tienen "design" en el nombre.

**Por qué OpenDesign NO es la pieza que Eleia necesita** (aunque sea lo que el usuario recordaba): (1) está pensado como app de diseño interactiva para una persona con un CLI de agente instalado, no como servicio headless que reciba JSON; (2) no parte de un `.pptx` corporativo del cliente, crea desde cero con PptxGenJS o exporta HTML; (3) trae 95k stars pero 981 issues abiertas y versiones diarias = superficie enorme e inestable para embeber en un producto regulado. Sirve como **inspiración de UX** (deck HTML editable, previsualización) pero no como motor.

---

### TAREA 2 — Evaluación de opciones

Criterios por opción: (1) licencia, (2) air-gapped, (3) plantillas reales vs programático + formatos, (4) mantenimiento, (5) esfuerzo de integración, (6) costo real.

### 2.1 Carbone (carboneio/carbone)

1. **Licencia**: **NO es open source OSI.** `LICENSE.md` es la *Carbone Community License Agreement (CCL)*: permite uso interno, incorporarlo en "Value Added Products" y modificarlo, pero prohíbe ofrecer "document-generator-as-a-service, or … any form of software-as-a-service" salvo como parte de un producto propio; ley francesa. Enterprise Edition es closed-source ([LICENSE.md](https://github.com/carboneio/carbone/blob/master/LICENSE.md)). Historial: v1/v2 eran Apache 2.0; v3 (sept. 2021) pasó a CCL ([anuncio v3](https://help.carbone.io/en-us/article/carbone-v3-news-september-2021-mh4tc2/)). Ciclo de vida oficial: v5 y v4 "ready for production", v3 "maintained but not recommended for new projects", **v2 "not supported"** ([version lifecycle](https://carbone.io/documentation/design/overview/version-lifecycle.html)). El npm público es `carbone@3.8.2` (2026-04-07, `license: SEE LICENSE IN LICENSE.md`) y el README admite que la edición embebible "is always one major version behind" ([README](https://github.com/carboneio/carbone/blob/master/README.md), [npm](https://www.npmjs.com/package/carbone)). Para Eleia (producto propio instalado en el cliente) la CCL es usable, pero **no es OSS** y hay que asumirlo en el due-diligence de licencias.
2. **Air-gapped**: sí. Docker `carbone/carbone-ee` "you can launch Carbone without a license and enjoy all its Community Edition features free of charge and without limits", y la ayuda oficial dice "Run Carbone On-premise without the need for internet access" ([Docker Hub](https://hub.docker.com/r/carbone/carbone-ee), [help: on-premise](https://help.carbone.io/en-us/article/is-carbone-on-premise-available-2d3tay/)). La licencia Enterprise se pasa por env `CARBONE_EE_LICENSE`, sin validación online documentada.
3. **Plantillas**: sí, es su razón de ser: plantilla DOCX/PPTX/XLSX/ODT/ODS/ODP + JSON → mismo formato, y **PDF vía LibreOffice**; "without LibreOffice you can still generate docx, xlsx, pptx, odt, ods, odp, html" ([README](https://github.com/carboneio/carbone/blob/master/README.md)). Loops, condiciones (`:ifEQ`, bloques, smart conditions) y formatters son **COMMUNITY FEATURE** para Cloud, On-premise y JS v3+ ([conditions](https://carbone.io/documentation/design/conditions/overview.html)). Enterprise agrega imágenes dinámicas, charts, HTML, barcodes, aggregations, operaciones PDF ([pricing](https://carbone.io/pricing.html)).
4. **Mantenimiento**: 2.105 stars, 53 issues abiertas, último push 2026-04-07 (GitHub API). npm: ~10k descargas/semana (api.npmjs.org, semana 2026-09-03/09). El desarrollo real ocurre en la EE cerrada (v5); el repo público recibe backports.
5. **Integración**: dos vías: (a) librería Node `carbone` v3 (requiere LibreOffice local para PDF); (b) contenedor `carbone-ee` con API REST (`/render`, `/template`, puerto 4000), consumible desde Python o Node ([carbone-ee-docker](https://github.com/carboneio/carbone-ee-docker/blob/master/README.md)).
6. **Costo**: Community $0. On-premise Enterprise: **Fit $1.500/año, Unlimited $2.940/año** ([pricing](https://carbone.io/pricing.html)); precios "customized based on your company's income" según help. Imagen `full` 522 MB con LibreOffice 24.8; Docker Hub recomienda 1 CPU / 1024 MB ([Docker Hub](https://hub.docker.com/r/carbone/carbone-ee)).

### 2.2 docxtemplater (open-xml-templating/docxtemplater)

1. **Licencia**: core **dual MIT o GPLv3** ("You may use it under the MIT license or the GPLv3 license") ([LICENSE.md](https://github.com/open-xml-templating/docxtemplater/blob/master/LICENSE.md)). Módulos comerciales: 500 €/módulo/año; PRO (4 módulos) 1.250 €/año; ENTERPRISE (19 módulos) 3.000 €/año; PREMIUM 9.000 €/año; perpetua ENTERPRISE 12.250 € única vez ([pricing](https://docxtemplater.com/pricing/)). 19 módulos: Image, HTML, XLSX, Table, Slides, Chart, Subtemplate, Pptx-sub, HTML-PPTX, HTML-XLSX, Styling, Footnotes, QRCode, ODT, etc. ([modules](https://docxtemplater.com/modules/)).
2. **Air-gapped**: sí. Es una librería pura JS sin llamadas externas; los módulos pagos se entregan como URL secreta para `npm install`, no hay validación runtime documentada ([FAQ](https://docxtemplater.com/faq/)).
3. **Plantillas**: DOCX y PPTX en el core, XLSX solo con módulo pago. **Ojo con PPTX gratis**: el core hace "simple text substitution within slides"; repetir una slide por ítem de array (`{:companies}`) o mostrar/ocultar slides requiere el **módulo Slides (pago, dentro del plan PRO)**; imágenes requieren módulo Image; HTML en pptx requiere HTML-PPTX ([slides module](https://docxtemplater.com/modules/slides/), [FAQ](https://docxtemplater.com/faq/)). Sin PDF propio: hay que convertir aparte.
4. **Mantenimiento**: 3.624 stars, **5 issues abiertas**, push 2026-08-04; npm 3.69.3 del 2026-07-23; **~557k descargas/semana** (registry + api.npmjs.org). Es el estándar de facto en JS.
5. **Integración**: librería Node (también browser). Desde Python habría que exponerla en un microservicio Node.
6. **Costo**: $0 para docx con loops/condiciones/tablas básicas. Para pptx útil (slide loops + imágenes) hay que contar **1.250 €/año (PRO)**. Sin LibreOffice; PDF externo.

### 2.3 PptxGenJS (gitbrent/PptxGenJS)

1. **Licencia**: MIT ([repo](https://github.com/gitbrent/PptxGenJS)).
2. **Air-gapped**: sí, JS puro.
3. **Plantillas**: **no carga un pptx existente**. Crea desde cero con "Slide Masters" definidos por código; la pregunta se repite desde 2017 (issues [#27](https://github.com/gitbrent/PptxGenJS/issues/27), [#99](https://github.com/gitbrent/PptxGenJS/issues/99), [#712](https://github.com/gitbrent/PptxGenJS/issues/712)) y sigue sin soporte. Solo PPTX.
4. **Mantenimiento**: 6.142 stars, 296 issues abiertas, último push 2025-11-28, último release v4.0.1 2025-06-26; **1,67M descargas/semana** (muy usado por agentes de IA/skills). Ritmo lento pero vivo.
5. **Integración**: librería Node.
6. **Costo**: $0. Sin dependencias nativas.

### 2.4 pptx-automizer (singerla/pptx-automizer)

1. **Licencia**: MIT ([repo](https://github.com/singerla/pptx-automizer)).
2. **Air-gapped**: sí; "no requiere LibreOffice ni software externo" ([docs](https://singerla.github.io/pptx-automizer/)).
3. **Plantillas**: **es exactamente "usar el pptx del cliente como plantilla"**: importa una librería de `.pptx`, copia slides/layouts/masters, y modifica texto, tablas, charts e imágenes por callbacks (xmldom) o genera elementos nuevos con PptxGenJS ([README](https://github.com/singerla/pptx-automizer/blob/main/README.md)). Solo PPTX.
4. **Mantenimiento**: 240 stars, 10 issues abiertas, push 2026-09-09, release v0.9.2 2026-08-22, npm 0.9.3 2026-08-22, ~44k descargas/semana. Un mantenedor principal (riesgo bus-factor), pero activo.
5. **Integración**: librería Node.
6. **Costo**: $0.

### 2.5 Ecosistema Python: python-docx / python-pptx / docxtpl / templaters pptx

- **python-docx**: MIT, 5.713 stars, PyPI 1.2.0 (2025-06-16), push 2026-08-01 ([repo](https://github.com/python-openxml/python-docx), PyPI API). Programático.
- **python-pptx**: MIT, 3.525 stars, **536 issues abiertas, último push 2024-08-07**, PyPI 1.0.2 (2024-08-07) ([repo](https://github.com/scanny/python-pptx), [PyPI](https://pypi.org/project/python-pptx/)). Abre un pptx existente y usa sus layouts/placeholders; es estable y ubicuo pero **dos años sin commits**. Existe fork `python-pptx-ng` ([PyPI](https://pypi.org/project/python-pptx-ng/)).
- **docxtpl (python-docx-template)**: **LGPL-2.1-only**, 2.702 stars, push 2026-07-07, PyPI 0.20.2 (2025-11-13) ([repo](https://github.com/elapouya/python-docx-template), [PyPI](https://pypi.org/project/docxtpl/)). Jinja2 dentro del docx: `{%p%}`, `{%tr%}`, `{%tc%}`, `{%r%}`, RichText, InlineImage, subdocs, headers/footers, colspan ([docs](https://docxtpl.readthedocs.io/en/latest/)). LGPL = usable como dependencia sin abrir tu código, mientras no la modifiques/embebas estáticamente. Es lo que usa **docassemble** (MIT, 986 stars, push 2026-09-07) para su document assembly ([docassemble docs](https://docassemble.org/docs/documents.html)).
- **python-pptx-templater** (kwlo): MIT, 45 stars, **último commit 2021-03-20**, PyPI 1.1.15 de 2019 ([repo](https://github.com/kwlo/python-pptx-templater)). **pptx-template** (m3dev): Apache-2.0, PyPI 0.2.9 de 2019 ([PyPI](https://pypi.org/project/pptx-template/)). **template-pptx-jinja** (Thykof): similar. → **Todos abandonados**; no hay un "docxtpl para pptx" mantenido en Python. Lo viable en Python para pptx es escribir ~200 líneas propias sobre python-pptx (reemplazo de `{{tags}}` en text frames + clonado de slides por XML), que es lo que hace cualquiera de estos micro-proyectos.

Aire-gapped: sí, todo Python puro. PDF: externo.

### 2.6 Conversión a PDF: Gotenberg / unoserver / LibreOffice headless

- **Gotenberg**: MIT, **13.041 stars, 26 issues abiertas**, push 2026-09-09, v8.36.0 (2026-08-14); variantes de imagen `chromium-only` (~30% más chica) y `libreoffice-only` (~38% más chica) ([releases](https://github.com/gotenberg/gotenberg/releases)). API REST multipart: `/forms/libreoffice/convert` acepta DOCX/XLSX/PPTX y 100+ formatos → PDF/PDF-A ([repo](https://github.com/gotenberg/gotenberg)). Recursos: mínimo 512 MiB / 0,2 CPU; 1 GB recomendado; LibreOffice atiende **1 conversión concurrente por instancia** y tiene "memory drift", por eso el default es reiniciar LO cada 10 conversiones ([troubleshooting](https://gotenberg.dev/docs/troubleshooting), [instalación](https://gotenberg.dev/docs/getting-started/installation)). 100% offline.
- **unoserver** (reemplazo de unoconv): MIT, 932 stars, PyPI 3.7 (2026-06-10) ([repo](https://github.com/unoconv/unoserver)). Listener UNO + `unoconverter`; más liviano que Gotenberg si ya tenés Python y LibreOffice en el mismo host.
- **LibreOffice headless `soffice --convert-to pdf`**: opción cero-dependencias; en Docker se recomienda ~1 GB RAM y 1–1,5 CPU por instancia, es single-threaded, y hay que usar `-env:UserInstallation` por proceso para concurrencia ([guía](https://oneuptime.com/blog/post/2026-02-08-how-to-run-libreoffice-in-docker-for-document-conversion/view)).

### 2.7 ONLYOFFICE Document Server / Document Builder, Collabora Online

- **ONLYOFFICE Docs Community**: AGPL-3.0, límite "up to 20 recommended" conexiones simultáneas; Conversion Service disponible en Community; Document Builder listado en las tres ediciones ([compare editions](https://www.onlyoffice.com/compare-editions)). DocumentServer: 6.892 stars, **1.135 issues abiertas**, v9.4.0 (2026-05-19).
- **ONLYOFFICE Document Builder**: repo AGPL-3.0 (dual, comercial vía sales@), 141 stars, v9.4.0 (2026-05-20) ([repo](https://github.com/ONLYOFFICE/DocumentBuilder)). Es un SDK C++ con bindings Python/.NET/Java/COM y CLI `docbuilder script.js` que **abre DOCX/XLSX/PPTX existentes, los modifica por API JS y exporta a 25+ formatos incl. PDF** ([overview](https://api.onlyoffice.com/docs/document-builder/get-started/overview/)). **Watermark**: varias fuentes secundarias afirman que la versión gratuita mete marca de agua; el hilo oficial que encontré ([community 2022](https://community.onlyoffice.com/t/how-to-remove-documents-watermark-in-documentbuilder/1974)) trata sobre watermarks insertados por API, no de una limitación de licencia; no pude confirmar un watermark impuesto por la AGPL en 9.x. Igualmente: no es "motor de plantillas con placeholders", es "escribí un script JS que edite el documento"; el modelo tendría que generar código docbuilder (más frágil que JSON) y arrastrás un runtime de ~cientos de MB con historial de issues.
- **Collabora Online (CODE)**: código "mostly MPLv2" ([Collabora MPLv2](https://www.collaboraonline.com/terms/collabora-online-mplv2/)); repo `CollaboraOnline/online` 3.347 stars, push 2026-09-04. Staff: "There are no limitations of documents / connections in CODE anymore", recomiendan soporte pago para producción ([foro](https://forum.collaboraonline.com/t/code-docker-limitations/810)). Tiene endpoint de conversión `POST /cool/convert-to/pdf` con `PDFVer=PDF/A-2b` ([foro](https://forum.collaboraonline.com/t/document-conversion-with-collabora-rest-api/686)). **No es motor de generación desde plantilla**: es editor + convertidor. Solo tendría sentido si Eleia quisiera además *editar en el navegador* el documento generado.

### 2.8 Generadores "IA hace la presentación"

- **Presenton (presenton/presenton)**: Apache-2.0, **10.162 stars**, 50 issues abiertas, push 2026-09-09, release `electron-v0.9.10-beta` 2026-09-08 (versiones beta quincenales) ([repo](https://github.com/presenton/presenton), [releases](https://github.com/presenton/presenton/releases)). Docker `ghcr.io/presenton/presenton`, API REST self-hosted `POST /api/v1/presentations/generate` (+ `-async`) con `template`, `export_as` pptx/pdf, API key de admin ([API docs](https://docs.presenton.ai/user-guide/api-and-automation/overview)). Soporta **Azure OpenAI** con variables dedicadas, Ollama, cualquier endpoint OpenAI-compatible; imágenes por Pexels/Pixabay/DALL-E/Gemini/ComfyUI (externos, opcionales); telemetría Mixpanel desactivable con `DISABLE_ANONYMOUS_TRACKING` ([README](https://github.com/presenton/presenton)). **Plantillas**: las plantillas son **layouts HTML/Tailwind → TSX + schema Zod**; "Template Studio" convierte un PPTX del cliente enviando **screenshot + HTML de cada slide a un modelo con visión** ("Text-only models may produce poor results or fail"), y el PPTX de salida se reconstruye desde HTML ("high-fidelity PPTX with real, editable elements") ([custom-template](https://presenton.ai/custom-template), [docs templates](https://docs.presenton.ai/user-guide/branding-and-design/templates)). Es decir: **no rellena tu .pptx; lo re-crea "parecido"**. Issue #310 reporta que la creación de template custom falla incluso con gpt-5; #429 pide poder exportar/importar templates ([#310](https://github.com/presenton/presenton/issues/310), [#429](https://github.com/presenton/presenton/issues/429)). Es un producto completo (Next.js + FastAPI + Chromium para render), no una librería: pesa, tiene su propia UI/usuarios/DB, y duplicaría el rol de Eleia como orquestador de LLM.
- **PPTAgent / DeepPresenter (icip-cas/PPTAgent)**: MIT, 5.015 stars, 13 issues, push 2026-09-07, release v2.0.0 (2025-12-16); paper EMNLP 2025 + DeepPresenter ACL 2026 ([repo](https://github.com/icip-cas/PPTAgent), [releases](https://github.com/icip-cas/PPTAgent/releases), [arXiv](https://arxiv.org/abs/2501.03936)). Enfoque interesante y el más cercano a "usar la plantilla de referencia": analiza un pptx de referencia, extrae esquemas por slide y genera acciones de edición sobre esas slides. Pero: necesita **modelo de lenguaje + modelo de visión** (paper: GPT-4o / Qwen2.5-72B / Qwen2-VL-72B), recomienda su modelo fine-tuned DeepPresenter-9B, Playwright, Docker host + sandbox, MinerU opcional. Es investigación productizada a medias; costo de GPU/VLM alto para air-gap si Azure OpenAI no ofrece visión en el deployment del cliente.
- **Marp / marp-cli**: MIT. El PPTX exportado son **imágenes pre-renderizadas**; `--pptx-editable` es experimental, requiere browser + LibreOffice y "not recommended if maintaining the slide's appearance is important" ([discussion #82](https://github.com/orgs/marp-team/discussions/82)). Descartado para plantillas corporativas.
- **Slidev, reveal.js**: HTML-first, mismo problema que Marp. Descartados.
- **md2pptx (MartinPacker)**: Python sobre python-pptx, acepta un template `.pptx` en metadatos y usa layouts título/sección/viñetas ([repo](https://github.com/MartinPacker/md2pptx)). Útil como referencia de cómo mapear markdown → layouts de la plantilla, pero es una herramienta de una persona.
- **OpenSlides**: es software de asambleas/votación, no aplica. **Gamma, Plus AI, SlideSpeak, Apitemplate.io, Documentero, DeckRobot**: SaaS, descartados por air-gap.

### 2.9 Pandoc y Quarto (markdown → docx/pptx con `--reference-doc`)

- **Pandoc**: GPL-2.0-or-later (COPYRIGHT), 46.220 stars, v3.11 (2026-08-29) ([repo](https://github.com/jgm/pandoc)). `--reference-doc` para docx toma **solo estilos/márgenes/encabezados** del docx de referencia; para pptx busca **layouts con nombres fijos** ("Title Slide", "Title and Content", "Section Header", "Two Content", "Comparison", "Content with Caption", "Blank"); si faltan, avisa y usa el default ([MANUAL](https://pandoc.org/MANUAL.html)). No hay placeholders arbitrarios ni loops: el contenido lo dicta el markdown. GPL es aceptable si se invoca como binario externo (no se linkea).
- **Quarto**: MIT ([COPYRIGHT](https://github.com/quarto-dev/quarto-cli/blob/main/COPYRIGHT)), 5.990 stars, v1.10.18 (2026-07-24). Envuelve pandoc con el mismo mecanismo de `reference-doc` para docx y pptx (mismos 7 layouts) ([Quarto PowerPoint](https://quarto.org/docs/presentations/powerpoint.html), [Quarto Word](https://quarto.org/docs/output-formats/ms-word-templates.html)). Agrega runtime Deno + opcionalmente R/Python; más pesado que pandoc solo sin ganar nada para este caso.

**Lectura práctica**: pandoc es la vía más barata para "el LLM escribe markdown → docx/pptx con la *apariencia* del cliente", pero **no rellena plantillas con campos**; es "documento nuevo con el tema del cliente". Excelente para informes largos en docx (donde el cliente quiere tipografías y portada, no formularios) y aceptable para decks simples.

### 2.10 Otros JS docx-only y Java

- **docx-templates (guigrpa)**: MIT, 1.095 stars, v4.15.0 (2025-12-03), ~58k desc/sem. Plantillas docx con JS embebido (`+++FOR`, `+++IF`, `+++IMAGE`, HTML). Solo docx/docm ([repo](https://github.com/guigrpa/docx-templates)).
- **easy-template-x (alonrbar)**: MIT, 532 stars, npm 7.2.8 (2026-08-20), ~16k desc/sem. Loops, condiciones, imágenes, charts, raw XML, plugins. Solo docx ([repo](https://github.com/alonrbar/easy-template-x)).
- **docx4j**: Apache 2.0 (ASLv2), releases 17.0.4/17.0.5/17.1.0 el 2, 5 y 7 de septiembre 2026, soporta docx/pptx/xlsx ([docx4java.org](https://www.docx4java.org/trac/docx4j)). Muy potente pero JVM: no encaja con un stack Python+Node.
- **XLSX**: en Python, **openpyxl** MIT (PyPI 3.1.5, 2024-06-28); en Node, **exceljs** MIT (4.4.0, 2023-10-19). Ambos abren un `.xlsx` existente como plantilla y escriben celdas conservando estilos. Carbone lo cubre en Community; docxtemplater solo con módulo pago.

---

### Tabla comparativa

| Opción | Licencia | OSS (OSI) | Air-gap | Plantilla real | Formatos | Mantenimiento (2026-09) | Integración | Costo real |
|---|---|---|---|---|---|---|---|---|
| Carbone CE (npm v3 / docker v5 community) | CCL | **No** | Sí (offline declarado) | Sí (docx/pptx/xlsx/odt + loops + condiciones) | docx/pptx/xlsx/odt/ods/odp → pdf (LO) | 2.1k★, push abr-2026, npm 10k/sem | REST Docker o lib Node | $0 CE; EE 1.500–2.940 US$/año; LO 522 MB, 1 GB RAM |
| docxtemplater core | MIT/GPLv3 | Sí | Sí | docx completo; pptx **solo texto** | docx, pptx (xlsx pago) | 3.6k★, 5 issues, 557k/sem | lib Node | $0 docx; **1.250 €/año** para slides+images |
| pptx-automizer | MIT | Sí | Sí | Sí, copia slides del pptx del cliente | pptx | 240★, release ago-2026, 44k/sem | lib Node | $0 |
| PptxGenJS | MIT | Sí | Sí | **No** (desde cero) | pptx | 6.1k★, 296 issues, 1,67M/sem | lib Node | $0 |
| docxtpl | LGPL-2.1 | Sí | Sí | Sí, Jinja2 en docx | docx | 2.7k★, push jul-2026 | lib Python | $0 |
| python-pptx | MIT | Sí | Sí | Parcial (layouts/placeholders, sin lenguaje de plantilla) | pptx | 3.5k★, **sin commits desde ago-2024**, 536 issues | lib Python | $0 + código propio |
| python-pptx-templater / pptx-template | MIT / Apache | Sí | Sí | Sí | pptx | **abandonados (2019–2021)** | lib Python | riesgo |
| Gotenberg | MIT | Sí | Sí | n/a (conversión) | office → pdf/pdf-a | 13k★, v8.36 ago-2026 | REST Docker | 512 MiB–1 GB RAM, 1 conv. LO concurrente |
| unoserver | MIT | Sí | Sí | n/a | office → cualquier LO | 932★, jun-2026 | lib/daemon Python | LO local |
| ONLYOFFICE DocBuilder | AGPL-3 / comercial | Sí (AGPL) | Sí | Por script JS, no placeholders | docx/pptx/xlsx/pdf | 141★, v9.4 may-2026 | SDK C++/Py/.NET, CLI | AGPL viral; runtime pesado |
| Collabora CODE | MPLv2 | Sí | Sí | No (editor + convert-to) | office → pdf | 3.3k★, sep-2026 | REST | pesado; soporte pago recomendado |
| Presenton | Apache-2.0 | Sí | Sí con Ollama/Azure; imágenes externas opcionales; telemetría desactivable | Re-crea el pptx como HTML/TSX vía modelo de visión | pptx/pdf | 10.2k★, beta quincenal | Producto Docker + REST | Chromium + Next + FastAPI; necesita **modelo con visión** para templates |
| PPTAgent/DeepPresenter | MIT | Sí | Parcial (LM + VLM locales) | Sí, edita slides de referencia | pptx | 5k★, v2.0 dic-2025 | Docker + CLI + MCP | GPU/VLM; investigación |
| OpenDesign | Apache-2.0 | Sí | BYOK Azure OK | **No** (PptxGenJS desde cero / HTML) | html/pdf/pptx | 95k★, 981 issues, release diario | App desktop / Docker, sin API de generación | pesado, inestable para embeber |
| Pandoc | GPL-2+ | Sí | Sí | Solo estilos (`--reference-doc`), 7 layouts fijos | md → docx/pptx (pdf con LO/LaTeX) | 46k★, 3.11 ago-2026 | binario CLI | $0, ~100 MB |
| Quarto | MIT | Sí | Sí | Igual que pandoc | md → docx/pptx/pdf | 6k★, 1.10 jul-2026 | CLI (Deno) | $0, más pesado |
| Marp / Slidev | MIT | Sí | Sí | No; pptx = imágenes | pptx (no editable) | activos | CLI | descartado |

---

### RECOMENDACIÓN

### Opción principal: motor de plantillas OSS "por formato" dentro del backend + Gotenberg para PDF

Arquitectura concreta (todo MIT/LGPL/Apache, cero SaaS, cero licencias por año):

```
Azure OpenAI ──(JSON con schema fijo)──► Eleia backend (Python)
                                           │
                 ┌─────────────────────────┼──────────────────────────┐
                 ▼                         ▼                          ▼
        docxtpl (Jinja2 en .docx)   servicio Node "pptx-svc"     openpyxl (.xlsx)
        plantilla del cliente       pptx-automizer + PptxGenJS   plantilla del cliente
                 │                  plantilla .pptx del cliente         │
                 └──────────────► archivo Office ◄─────────────────────┘
                                           │ (opcional)
                                           ▼
                                  Gotenberg libreoffice-only ──► PDF / PDF-A
```

Por qué así y no de otra forma:

1. **DOCX → docxtpl.** Es la única librería de plantillas docx *en Python* madura (2.7k★, activa julio 2026), con loops de filas/columnas, imágenes inline, RichText y subdocumentos ([docs](https://docxtpl.readthedocs.io/en/latest/)). El cliente edita su `.docx` en Word y escribe `{{ titulo }}`, `{% for f in filas %}`: es el flujo que docassemble usa en producción legal hace años. LGPL-2.1 no contamina el código de Eleia si se usa como paquete pip sin modificar.
2. **PPTX → pptx-automizer (Node).** Es la única pieza OSS mantenida (release ago-2026) que hace lo que realmente se pide: **tomar el `.pptx` corporativo, clonar la slide-tipo N veces y reemplazar texto/tablas/gráficos/imágenes** sin LibreOffice y sin módulos pagos ([repo](https://github.com/singerla/pptx-automizer)). docxtemplater core no alcanza (solo sustitución de texto en pptx; los slide-loops cuestan 1.250 €/año) y PptxGenJS no abre plantillas. Como es Node, va en un microservicio chico (`pptx-svc`, ~50 MB de imagen) con un endpoint `POST /render {template_id, data}`; el backend Python lo llama igual que llama a Gotenberg. Mitigación del bus-factor: el paquete es pequeño y MIT; si muriera, se puede vendorizar. Alternativa Python-pura si querés evitar Node en el servidor: ~200 líneas sobre python-pptx (reemplazo de `{{tags}}` en text frames + clonado de slides por XML), aceptando que python-pptx está sin commits desde 2024 pero es estable.
3. **XLSX → openpyxl** (o exceljs si preferís todo en pptx-svc). Abre la plantilla, escribe celdas, mantiene estilos/fórmulas.
4. **PDF → Gotenberg `libreoffice-only`.** MIT, 13k★, imagen ~38% más chica, API multipart trivial desde Python (`requests.post(".../forms/libreoffice/convert", files=...)`), PDF/A-2b para archivo ([releases](https://github.com/gotenberg/gotenberg/releases)). Dimensionar 1 GB RAM por réplica y una cola, porque LibreOffice procesa 1 conversión a la vez ([troubleshooting](https://gotenberg.dev/docs/troubleshooting)).
5. **Contrato con el LLM**: el modelo no genera XML ni código; genera **JSON validado contra un schema derivado de la plantilla** (los nombres de tags de docxtpl / los placeholders declarados de la slide-tipo). Eso encaja con el "formato de respuesta" ya sellado en las specs 045/046 y hace el pipeline determinista y auditable. Para informes largos sin campos fijos, agregar la ruta **markdown → pandoc `--reference-doc` docx del cliente** como modo "documento libre con la marca del cliente" (pandoc como binario GPL externo, sin linkear).

Costo operativo: ~1,2 GB RAM extra (Gotenberg + pptx-svc), $0 en licencias, cuatro dependencias con release en los últimos 3 meses.

### Alternativa: Carbone Community en Docker (un solo motor para todo)

Si el equipo prefiere **un único servicio** que cubra docx+pptx+xlsx+odt y PDF con el mismo lenguaje de plantilla (`{d.campo}`, `{d.items[i].x}`, `:ifEQ`), **Carbone CE en `carbone/carbone-ee` sin licencia** es la opción más rápida de integrar (REST, un contenedor, loops y condiciones incluidos, LibreOffice adentro, funciona offline declarado por el vendor). Condiciones para elegirla:
- Aceptar en el registro de licencias que **CCL no es OSI** y que prohíbe revender Carbone como "document-generation-as-a-service" (Eleia lo embebe en un producto instalado en el cliente: permitido por la cláusula de Value Added Product, pero conviene que lo revise quien lleve compliance).
- Asumir que si más adelante se necesitan **imágenes dinámicas, charts o HTML en plantillas**, hay que pagar Enterprise (1.500–2.940 US$/año/proyecto).
- Asumir que la edición gratuita corre una major detrás y que la comunidad es 5× más chica que docxtemplater.

### Lo que NO recomiendo y por qué

- **Presenton / PPTAgent / OpenDesign como motor**: son *productos* de IA con su propia orquestación, UI y modelo de plantillas (HTML/TSX o edición vía VLM); no rellenan el `.pptx` del cliente, lo re-crean "parecido" y necesitan un modelo con visión. Eleia ya es el orquestador; sumar otro duplica LLM calls, superficie de ataque y RAM. Vale la pena mirar Presenton en 6 meses como *módulo opcional* de "deck creativo" si un cliente lo pide, nunca como base del flujo de plantillas.
- **ONLYOFFICE Document Builder / Collabora**: AGPL/MPL viral o pesados, y su modelo es "script que edita" o "editor", no plantillas con datos.
- **docxtemplater como única base**: excelente para docx, pero el pptx útil es pago.
- **Marp/Slidev/reveal**: pptx no editable.

---

### Fuentes (≥ 12 distintas)

1. https://github.com/nexu-io/open-design (README, licencia, stars)
2. https://github.com/nexu-io/open-design/issues/1228 (sin export a pptx editable con plantillas corporativas)
3. https://github.com/nexu-io/open-design/blob/main/skills/pptx-generator/SKILL.md (PptxGenJS "from scratch")
4. https://github.com/carboneio/carbone/blob/master/LICENSE.md (CCL, no OSI)
5. https://help.carbone.io/en-us/article/carbone-v3-news-september-2021-mh4tc2/ (cambio de licencia en v3)
6. https://carbone.io/documentation/design/overview/version-lifecycle.html (v2 no soportada, v3 no recomendada)
7. https://carbone.io/pricing.html (On-premise 1.500 / 2.940 US$/año; features Enterprise)
8. https://hub.docker.com/r/carbone/carbone-ee (community sin licencia, 522 MB, 1 CPU/1 GB)
9. https://help.carbone.io/en-us/article/is-carbone-on-premise-available-2d3tay/ (offline sin internet)
10. https://carbone.io/documentation/design/conditions/overview.html (condiciones = Community feature)
11. https://github.com/open-xml-templating/docxtemplater/blob/master/LICENSE.md (dual MIT/GPLv3)
12. https://docxtemplater.com/pricing/ (500 €/módulo/año, PRO 1.250 €, ENTERPRISE 3.000 €, perpetua 12.250 €)
13. https://docxtemplater.com/modules/slides/ (core pptx = solo sustitución de texto; slide loops pagos)
14. https://docxtemplater.com/faq/ (entrega de módulos por URL npm)
15. https://github.com/gitbrent/PptxGenJS + issues #27, #99, #712 (no carga pptx existente)
16. https://github.com/singerla/pptx-automizer y https://singerla.github.io/pptx-automizer/ (MIT, plantillas pptx, sin LibreOffice)
17. https://github.com/elapouya/python-docx-template y https://docxtpl.readthedocs.io/en/latest/ (LGPL-2.1, features)
18. https://pypi.org/project/docxtpl/ ; https://pypi.org/project/python-pptx/ ; https://pypi.org/project/unoserver/ (versiones y fechas)
19. https://github.com/scanny/python-pptx (MIT, último push 2024-08-07)
20. https://github.com/kwlo/python-pptx-templater ; https://pypi.org/project/pptx-template/ (abandonados)
21. https://github.com/gotenberg/gotenberg y https://github.com/gotenberg/gotenberg/releases (MIT, v8.36.0, variantes de imagen)
22. https://gotenberg.dev/docs/troubleshooting ; https://gotenberg.dev/docs/getting-started/installation (RAM, concurrencia LO)
23. https://github.com/unoconv/unoserver (MIT)
24. https://www.onlyoffice.com/compare-editions (AGPL, 20 conexiones, DocBuilder en todas las ediciones)
25. https://github.com/ONLYOFFICE/DocumentBuilder ; https://api.onlyoffice.com/docs/document-builder/get-started/overview/
26. https://community.onlyoffice.com/t/how-to-remove-documents-watermark-in-documentbuilder/1974
27. https://www.collaboraonline.com/terms/collabora-online-mplv2/ ; https://forum.collaboraonline.com/t/code-docker-limitations/810 ; https://forum.collaboraonline.com/t/document-conversion-with-collabora-rest-api/686
28. https://github.com/presenton/presenton ; https://github.com/presenton/presenton/releases ; https://docs.presenton.ai/user-guide/api-and-automation/overview ; https://docs.presenton.ai/user-guide/branding-and-design/templates ; https://presenton.ai/custom-template ; issues #310 y #429
29. https://github.com/icip-cas/PPTAgent ; https://github.com/icip-cas/PPTAgent/releases ; https://arxiv.org/abs/2501.03936
30. https://github.com/orgs/marp-team/discussions/82 (pptx de Marp = imágenes)
31. https://pandoc.org/MANUAL.html ; https://github.com/jgm/pandoc/blob/main/COPYRIGHT (GPL-2+, layouts fijos)
32. https://quarto.org/docs/presentations/powerpoint.html ; https://github.com/quarto-dev/quarto-cli/blob/main/COPYRIGHT (MIT)
33. https://github.com/guigrpa/docx-templates ; https://github.com/alonrbar/easy-template-x (MIT, docx-only)
34. https://www.docx4java.org/trac/docx4j (ASLv2, releases sept-2026)
35. https://github.com/MartinPacker/md2pptx
36. https://docassemble.org/docs/documents.html (usa docxtpl)
37. https://oneuptime.com/blog/post/2026-02-08-how-to-run-libreoffice-in-docker-for-document-conversion/view (RAM/CPU LibreOffice headless)
38. GitHub REST API (`api.github.com/repos/...`), npm registry (`registry.npmjs.org`, `api.npmjs.org/downloads`), PyPI JSON API — consultados 2026-09-10 para stars, issues, fechas de push/release, versiones y descargas semanales.

---

## Anexo B — Parte 1b: AnythingLLM: generación de documentos (docx/pptx/pdf/xlsx) y análisis tabular exacto

Fecha de relevamiento: 2026-09-10. Fuentes: docs.anythingllm.com, repo `Mintplex-Labs/anything-llm` (rama `master`), releases e issues de GitHub. Versión estable al día de hoy: **v1.16.1 (27-ago-2026)**.

---

### TL;DR

| Pregunta | Respuesta corta |
|---|---|
| ¿Genera .docx/.pptx/.pdf/.xlsx/.txt? | **Sí**, nativo desde v1.12.0 (abr-2026) vía skill `create-files-agent`. |
| ¿Desde plantilla (docx/pptx con placeholders)? | **No.** Genera desde cero con 3 "themes" de colores; no existe parámetro de plantilla. |
| ¿Funciona con Azure OpenAI como Agent LLM? | **Sí**, provider `azure.js` usa tool calling nativo del SDK de OpenAI. |
| ¿Se invoca por Developer API y devuelve el archivo? | **Sí**: `POST /v1/workspace/{slug}/chat` con `@agent`, la respuesta trae `outputs[]` y se descarga con `GET /v1/document/generated-files/{storageFilename}` (API key). **Pero** hay que auto-aprobar la skill (`AGENT_AUTO_APPROVED_SKILLS`) porque en contexto HTTP el pedido de aprobación se auto-deniega. |
| ¿Custom skill Node con docxtemplater/carbone? | **Posible pero hacky**: el handler solo puede devolver string, corre con `require()` directo (sin sandbox), y para devolver un archivo hay que usar internals no documentados (`this.super._pendingOutputs` + `storage/generated-files`). |
| ¿SQL agent con CSV/Excel subido o DuckDB? | **No.** Solo MySQL, PostgreSQL y SQL Server por conexión remota. |
| ¿Chat with CSV = chunks vectoriales? | **Sí.** `.csv` → `asTxt.js`; `.xlsx` → `asXlsx.js` que vuelca cada hoja a CSV-texto y lo embebe. No hay motor de cálculo exacto. |

---

### 1. Qué formatos genera hoy el Document Generation Agent

**Docs oficiales.** La página del Document Generation Agent dice que está disponible desde **v1.12.0+**, hay que habilitarlo en *Settings > Agent Skills*, y lista los tipos: *"Text files, PDFs, Excel files, Docx files, PowerPoint presentations"*. Recomienda modelos 8B+ para PPTX.
Fuente: https://docs.anythingllm.com/agent/usage/document-generation-agent

**Release v1.12.0 (2-abr-2026).** Introduce el agente: *"generate text files, PDFs, Excel files, Docx, and even entire PowerPoint presentations"*, además de Automatic Mode (tools sin `@agent`), Intelligent Tool Selection y Filesystem Agent. El changelog aclara que el agente *"pedirá confirmación antes de crear archivos"*.
Fuentes: https://github.com/Mintplex-Labs/anything-llm/releases/tag/v1.12.0 · https://docs.anythingllm.com/changelog/v1.12.0

**Código real (rama master).** El plugin vive en `server/utils/agents/aibitat/plugins/create-files/` con subcarpetas `docx/`, `pdf/`, `pptx/`, `text/`, `xlsx/`, `assets/`, más `index.js` y `lib.js`. `index.js` define `name: "create-files-agent"` y registra cinco sub-skills: `CreatePptxPresentation`, `CreateTextFile`, `CreatePdfFile`, `CreateExcelFile`, `CreateDocxFile`.
Fuente: https://github.com/Mintplex-Labs/anything-llm/tree/master/server/utils/agents/aibitat/plugins/create-files

Detalle por formato (leído del código):

| Skill (`name`) | Librería | Entrada | Salida registrada |
|---|---|---|---|
| `create-docx-file` (`docx/create-docx-file.js`) | `docx` + `marked` (markdown → docx) | `filename`, `title`, `subtitle`, `author`, `content` (markdown), `theme` enum `["neutral","blue","warm"]`, `margins` enum, `includeTitlePage` | `DocxFileDownload` |
| `create-presentation` (`pptx/create-presentation.js`) | `pptxgenjs` | `filename`, `title`, `sections[]`, `author`, `theme` (temas internos en `themes.js`) | `PptxFileDownload` |
| `create-pdf-file` (`pdf/create-pdf-file.js`) | `@mintplex-labs/mdpdf` + `pdf-lib` | markdown / texto plano | `PdfFileDownload` |
| `create-excel-file` (`xlsx/create-excel-file.js`) | `exceljs` | `sheets[] { name, csvData, options: {headerStyle, autoFit, freezeHeader, zebraStripes, delimiter} }` — sin fórmulas | `ExcelFileDownload` |
| `create-text-file` | fs | texto | `TextFileDownload` (análogo) |

Fuentes: https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/agents/aibitat/plugins/create-files/docx/create-docx-file.js · https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/agents/aibitat/plugins/create-files/pptx/create-presentation.js · https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/agents/aibitat/plugins/create-files/pdf/create-pdf-file.js · https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/agents/aibitat/plugins/create-files/xlsx/create-excel-file.js

**Dónde queda el archivo y cómo llega al usuario.** `lib.js` (`CreateFilesManager`) guarda el binario en `STORAGE_DIR/generated-files/` (`path.join(storageRoot, "generated-files")`) con un nombre interno (`storageFilename`) y registra el output en `aibitat._pendingOutputs.push({ type, payload })` para que se persista en el historial de chat y la UI muestre una tarjeta de descarga. El servidor sirve el archivo por `GET /agent-skills/generated-files/:filename` (sesión de usuario, `validatedRequest` + `flexUserRoleValid`, `Content-Disposition: attachment`).
Fuentes: https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/agents/aibitat/plugins/create-files/lib.js · https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/endpoints/agentFileServer.js

**Skills relacionadas (no confundir):**
- **Save Files** (`save-file-to-browser` en versiones viejas): guarda "cualquier información" como archivo en la máquina local, con diálogo de destino. Es texto plano; no es el generador de office. https://docs.anythingllm.com/agent/usage/save-files
- **Chart Generation** (`rechart.js`): no produce archivo; manda JSON por socket (`this.super.socket.send("rechartVisualize", { type, dataset, title })`) y la UI lo renderiza con Recharts. https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/agents/aibitat/plugins/rechart.js

**Nota Docker vs Desktop.** La doc habla de "v1.12.0+" (numeración Desktop). La imagen Docker sigue `master`, así que cualquier tag de imagen posterior a abril-2026 ya trae `create-files`. El changelog v1.12.1 agrega "abrir el documento en la app nativa" (solo Desktop). https://docs.anythingllm.com/changelog/v1.12.1

### 2. ¿Soporta plantillas (docx/pptx base con placeholders)?

**No.** Confirmado en el código:
- `create-docx-file.js`: el schema solo tiene `theme` enum `["neutral","blue","warm"]`, `margins`, `includeTitlePage`. No hay ninguna referencia a `template`, `templatePath` ni carga de un `.docx` existente; el documento se construye desde cero con la librería `docx` a partir de markdown.
- `create-presentation.js`: los "temas" son objetos internos en `themes.js` (`getAvailableThemes()` / `getTheme(themeName)`), no archivos `.pptx`/`.potx`.
- `create-excel-file.js`: recibe CSV por hoja; no abre un workbook base.

Tampoco la doc menciona plantillas. Es un generador "brand-agnostic" con estilos fijos; no sirve para papelería corporativa ni para completar contratos/informes con placeholders.
Fuentes: las mismas del punto 1 (create-docx-file.js, create-presentation.js) y https://docs.anythingllm.com/agent/usage/document-generation-agent

### 3. ¿Funciona en modo @agent con Azure OpenAI?

**Sí.**
- Existe un provider de agente dedicado: `server/utils/agents/aibitat/providers/azure.js` → `class AzureOpenAiProvider extends Provider`, usa `require("openai")` con `baseURL` de Azure y el helper compartido de tool calling nativo: *"Uses the shared native tool calling helper for OpenAI-compatible tool calling"* (`tooledStream`, `tooledComplete`). No usa inyección por prompt ("UnTooled").
  https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/agents/aibitat/providers/azure.js
- `providers/index.js` exporta `AzureOpenAiProvider` entre ~41 providers.
  https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/agents/aibitat/providers/index.js
- Release v1.10.0: *"Migrated Azure OpenAI to unified `v1` api with full agent support"* (PR #4744). Antes, el PR #3691 ya había reemplazado `@azure/openai` por el SDK `openai` para el provider de agente.
  https://github.com/Mintplex-Labs/anything-llm/releases/tag/v1.10.0 · https://github.com/Mintplex-Labs/anything-llm/pull/3691
- La doc de Azure OpenAI no menciona restricciones para agentes: https://docs.anythingllm.com/setup/llm-configuration/cloud/azure-openai

**Riesgos conocidos:**
- Modelos de razonamiento en Azure (o1 y sucesores) requerían `api-version` específica y no había campo para setearla (issue #3021, resuelto con la migración a v1 API). https://github.com/Mintplex-Labs/anything-llm/issues/3021
- GPT-5 no aceptaba `role: "function"` en el flujo agentic (issue #4385, sep-2025) — verificar con el deployment concreto. https://github.com/Mintplex-Labs/anything-llm/issues/4385
- Ojo: si en vez del provider "Azure OpenAI" se usa "Generic OpenAI compatible", el tool calling nativo no estaba soportado (issue #3753). https://github.com/Mintplex-Labs/anything-llm/issues/3753
- Doc general de por qué un agente no usa tools (modelos chicos/cuantizados): https://docs.anythingllm.com/agent-not-using-tools

Recomendación: configurar el **Agent LLM del workspace** explícitamente como Azure OpenAI con un deployment GPT-4o/4.1 (no reasoning), como indica https://docs.anythingllm.com/agent/setup.

### 4. ¿Se puede invocar por Developer API y recuperar el archivo?

**Sí, y es más completo de lo que parece desde la doc.**

- `server/utils/chats/apiChatHandler.js`: tanto `chatSync` (`POST /v1/workspace/:slug/chat`) como `streamChat` (`/stream-chat`) chequean `EphemeralAgentHandler.isAgentInvocation({ message, workspace, chatMode })`; en sync espera el cierre (*"we wait for close event since this is a synchronous call"*) y devuelve `{ textResponse, thoughts, outputs, citations, metrics }`. Comentario literal: *"Merge outputs from packMessages with outputs from aibitat (contains file download metadata)"*, y los outputs se mapean a URLs `/v1/document/generated-files/[storageFilename]`.
  https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/chats/apiChatHandler.js
- Endpoint de descarga para la Developer API: `GET /v1/document/generated-files/:filename` con middleware `[validApiKey]`, `Content-Disposition: attachment`. Swagger literal: *"Download a file generated by an agent skill (e.g., PDF, DOCX, XLSX, PPTX) or a generated image (img-*.png). The filename is returned in the `outputs` array of a chat response when an agent generates a file or image."*
  https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/endpoints/api/document/index.js
- El endpoint `/agent-skills/generated-files/:filename` (UI) usa `validatedRequest`, que **solo acepta JWT de sesión**, no API keys → por API usar el de `/v1/document/...`.
  https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/middleware/validatedRequest.js
- El endpoint OpenAI-compatible (`/v1/openai/chat/completions`) **no** dispara `@agent` (issue #2450, cerrado como feature request).
  https://github.com/Mintplex-Labs/anything-llm/issues/2450
- Issue #5060 (feb-2026): las interacciones `@agent` por `/v1/workspace/{slug}/thread/{threadSlug}/chat` no se persistían en el historial del thread — cerrado vía PR #6125.
  https://github.com/Mintplex-Labs/anything-llm/issues/5060

**Trampa crítica: la aprobación de tool.** Cada `create-*-file` llama a `requestToolApproval({ skillName: this.name })`. En contexto HTTP (`plugins/http-socket.js`) la lógica es: (1) si `skillIsAutoApproved` por env → aprueba; (2) si está en `AgentSkillWhitelist` (tabla `system_settings`, label `whitelisted_agent_skills` o `user_{id}_whitelisted_agent_skills`, la opción "Always allow" de la UI) → aprueba; (3) si no hay contexto Telegram → *"Tool approval requested for ${skillName} but no Telegram context available. Auto-denying for safety."* Es decir, **por API el agente se niega a crear el archivo** salvo que se configure:

```
# server/.env.example
# (optional) Comma-separated list of skills that are auto-approved.
# This will allow the skill to be invoked without user interaction.
# AGENT_AUTO_APPROVED_SKILLS=create-pdf-file,create-word-file
```

Ojo: el ejemplo del `.env.example` dice `create-word-file`, pero el `name` real de la skill en código es `create-docx-file` (y `create-presentation`, `create-excel-file`, `create-text-file`). Verificar contra la versión desplegada.
Fuentes: https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/agents/aibitat/plugins/http-socket.js · https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/models/agentSkillWhitelist.js · https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/.env.example · https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/agents/aibitat/plugins/websocket.js (en UI el timeout de aprobación es 120 s)

### 5. Custom agent skills en Node (docxtemplater / pptxgenjs / carbone)

Qué dicen docs y código:
- Son extensiones NodeJS que se cargan desde `STORAGE_LOCATION/plugins/agent-skills/<hubId>/` con `plugin.json` + `handler.js`. Disponibles en Docker y Desktop, **no** en Cloud. Hot-reload sin reiniciar (cerrar sesión de agente con `/exit`).
  https://docs.anythingllm.com/agent/custom/introduction · https://docs.anythingllm.com/agent/custom/developer-guide · https://docs.anythingllm.com/agent/custom/plugin-json
- **Retorno:** *"All functions must return a string value, anything else may break the agent invocation."* No hay contrato para devolver binarios.
  https://docs.anythingllm.com/agent/custom/handler-js
- **Dependencias:** *"You can bundle any NodeJS package you want within your custom agent skill, but it must be present in the folder structure"* — no hay `npm install` centralizado; hay que vendorizar `node_modules` dentro de la carpeta del skill (o bundlear con esbuild). Solo módulos stdlib o bundleados.
- **Sandbox:** ninguno. `server/utils/agents/imported.js` hace `this.handler = require(this.handlerLocation)` directo, y el contexto (`this`) que recibe el handler incluye `super: aibitat`, `config`, `runtimeArgs`, `logger`, `introspect`, `runtime: "docker"`, `webScraper`, `requestToolApproval` (protegido contra override). Al tener `this.super` (la instancia aibitat) el skill puede, de facto, acceder a `this.super.socket.send(...)` y a `this.super._pendingOutputs`.
  https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/agents/imported.js
- Advertencia oficial: *"Only run custom agent skills you trust."*

**Viabilidad de un skill "render desde plantilla":**
- Técnicamente sí: el handler puede `require("docxtemplater")`/`pizzip`/`pptxgenjs`/`carbone` vendorizados, leer una plantilla desde un volumen montado, renderizar y escribir el `.docx` en `STORAGE_DIR/generated-files/` con un nombre compatible, y luego llamar `this.super._pendingOutputs.push({ type: "DocxFileDownload", payload: { filename, storageFilename, fileSize } })` para que aparezca la tarjeta de descarga en UI y en `outputs[]` de la API.
- Limitaciones reales: (a) depende de **internals no documentados** (`_pendingOutputs`, tipos `*FileDownload`, layout de `generated-files`, `createFilesLib`) que pueden cambiar sin aviso; (b) sin sandbox → cualquier bug/vuln del skill corre con permisos del proceso servidor; (c) el LLM tiene que producir el JSON de datos para los placeholders — con plantillas complejas (tablas, loops) la calidad depende del modelo; (d) `carbone` necesita LibreOffice para PDF, lo cual implica engordar la imagen; (e) la doc avisa que la feature es nueva y puede tener bugs.
- Alternativa más limpia dentro de AnythingLLM: exponer el motor de plantillas como **servidor MCP** o como servicio HTTP propio y que el skill/MCP devuelva una URL de descarga servida por nuestro backend (no por AnythingLLM). Así no se toca `_pendingOutputs` y el contrato es un string (la URL).

### 6. Análisis exacto de CSV/Excel: SQL agent y "Chat with CSV"

**SQL agent.** `server/utils/agents/aibitat/plugins/sql-agent/SQLConnectors/` contiene solo `MySQL.js`, `Postgresql.js`, `MSSQL.js`; el `index.js` hace `switch (identifier) { case "mysql": case "postgresql": case "sql-server": ... }` y tira error para cualquier otro. **No hay SQLite, DuckDB ni carga de CSV.** Las operaciones son: listar conexiones, listar tablas, ver esquema, ejecutar SELECT. La doc recomienda usuario read-only porque nada impide que el LLM mande un `DELETE`. v1.16.0 sumó múltiples conexiones simultáneas y SSL.
Fuentes: https://github.com/Mintplex-Labs/anything-llm/tree/master/server/utils/agents/aibitat/plugins/sql-agent/SQLConnectors · https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/agents/aibitat/plugins/sql-agent/SQLConnectors/index.js · https://docs.anythingllm.com/agent/usage/sql-agent · https://docs.anythingllm.com/changelog/v1.16.0
Feature request abierta de ampliar el SQL agent: https://github.com/Mintplex-Labs/anything-llm/issues/2414

**Chat with CSV/XLSX = RAG vectorial, confirmado.** En el collector, `SUPPORTED_FILETYPE_CONVERTERS` mapea `".csv": "./convert/asTxt.js"` (se lee con `fs.readFileSync(fullFilePath, "utf8")` como texto plano, sin parsear columnas) y `".xlsx": "./convert/asXlsx.js"` (cada hoja → `convertToCSV(data)` → un documento de texto por hoja o combinado, con `token_count_estimate`), y luego `writeToServerDocuments` → chunking → embeddings → vector DB. **No se conserva estructura tabular ni hay motor de consulta.** `.xls` legacy no está soportado.
Fuentes: https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/collector/utils/constants.js · https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/collector/processSingleFile/convert/asXlsx.js · https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/collector/processSingleFile/convert/asTxt.js · https://docs.anythingllm.com/chatting-with-documents/introduction (RAG por similitud; "Document Pinning" mete el texto completo en contexto — mitiga pero no calcula).

Consecuencia: preguntas tipo "total de ventas por región en Q2" sobre un Excel subido se responden desde 4-6 chunks de CSV plano; el LLM suma "a ojo". Con pinning entra la hoja entera (si cabe en contexto) pero sigue sin haber ejecución determinista.

---

### Veredicto

1. **¿Alcanza el Document Generation Agent para docx/pptx desde plantilla? No.**
   Sí alcanza para "generá un informe en Word / una presentación / un Excel simple a partir de este chat" con look genérico (3 temas), incluso vía API (con `AGENT_AUTO_APPROVED_SKILLS` y descarga por `/v1/document/generated-files/`). **No** cubre plantillas corporativas con placeholders, papelería, contratos ni Excel con fórmulas. Para eso hace falta un motor aparte (docxtemplater/pptxgenjs/carbone o el propio backend del producto), integrado como MCP/servicio HTTP con URL de descarga propia, o —con más riesgo— como custom skill que escriba en `generated-files` y empuje a `_pendingOutputs` (internals no documentados, sin sandbox).

2. **¿Alcanza el sql-agent para análisis exacto de Excel subidos? No.**
   Solo habla con MySQL/PostgreSQL/SQL Server remotos; no ingesta CSV/XLSX ni tiene DuckDB/SQLite. El "Chat with CSV" es RAG vectorial sobre texto plano. Para análisis exacto hay que sumar un servicio propio (p. ej. DuckDB/pandas sobre el archivo subido) expuesto como MCP o skill, o cargar el archivo a un Postgres y apuntar el sql-agent ahí.

3. **Azure OpenAI como Agent LLM: OK** (tool calling nativo desde v1.10.0), con la salvedad de elegir deployments no-reasoning y probar el modelo concreto.

### Fuentes (resumen)
1. https://docs.anythingllm.com/agent/usage/document-generation-agent
2. https://github.com/Mintplex-Labs/anything-llm/releases/tag/v1.12.0
3. https://github.com/Mintplex-Labs/anything-llm/tree/master/server/utils/agents/aibitat/plugins/create-files
4. https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/agents/aibitat/plugins/create-files/docx/create-docx-file.js
5. https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/agents/aibitat/plugins/create-files/pptx/create-presentation.js
6. https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/agents/aibitat/plugins/create-files/lib.js
7. https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/agents/aibitat/providers/azure.js
8. https://github.com/Mintplex-Labs/anything-llm/releases/tag/v1.10.0
9. https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/chats/apiChatHandler.js
10. https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/endpoints/api/document/index.js
11. https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/agents/aibitat/plugins/http-socket.js
12. https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/.env.example
13. https://github.com/Mintplex-Labs/anything-llm/issues/2450
14. https://github.com/Mintplex-Labs/anything-llm/issues/5060
15. https://docs.anythingllm.com/agent/custom/handler-js
16. https://docs.anythingllm.com/agent/custom/developer-guide
17. https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/agents/imported.js
18. https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/server/utils/agents/aibitat/plugins/sql-agent/SQLConnectors/index.js
19. https://docs.anythingllm.com/agent/usage/sql-agent
20. https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/collector/utils/constants.js
21. https://raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/collector/processSingleFile/convert/asXlsx.js
22. https://docs.anythingllm.com/chatting-with-documents/introduction
23. https://docs.anythingllm.com/agent-not-using-tools
24. https://github.com/Mintplex-Labs/anything-llm/issues/4385

---

## Anexo C — Parte 2: DB-GPT y alternativas para "chat tabular exacto" sobre Excel/CSV en Eleia Hub

Fecha de relevamiento: 2026-09-10. Todos los números (stars, issues, fechas) fueron leídos ese día vía API de GitHub, Docker Hub y docs oficiales. Los datos que no pude verificar de primera mano están marcados como tales.

Contexto del problema (queja de Tomás): el CSV se metió en la base vectorial troceado en chunks, y por eso el RAG semántico no puede sumar, filtrar ni cruzar filas/columnas entre archivos. Lo que se necesita es **cómputo real** (SQL o pandas) sobre los archivos subidos, con resultado exacto, en un entorno on-premise/air-gapped cuyo único egreso permitido es Azure OpenAI, sin DBA, y con enmascarado de datos personales antes de que nada llegue al LLM.

---

### TAREA A — DB-GPT (eosphoros-ai/DB-GPT)

### 1. ¿Soporta chat en lenguaje natural sobre Excel/CSV subidos? Cómo lo hace

**Sí.** Tiene una "scene" nativa llamada **Chat Excel** (`chat_excel`). Verificado en docs y en código:

- Docs oficiales (Chat Excel): "Chat Excel means that you can interpret and analyze Excel data through natural language dialogue"; el flujo es: elegir la app Chat Excel → subir el archivo → chatear. La misma página aclara que "the Excel file format is converted to .csv format". Fuente: https://github.com/eosphoros-ai/DB-GPT/blob/main/docs/docs/application/apps/chat_excel.md (espejo de docs.dbgpt.cn/docs/application/apps/chat_excel/; el sitio docs.dbgpt.cn hoy sirve un certificado autofirmado y docs.dbgpt.site no respondió, ojo con eso).
- Código `excel_reader.py`: la clase `ExcelReader` abre una conexión **DuckDB** (`duckdb.connect()`), carga el archivo con los lectores nativos de DuckDB (`read_csv`, `read_xlsx`, `read_json_auto`, `read_parquet`) y, si falla, cae a pandas (`pd.read_excel` / `pd.read_csv` con detección de encoding vía chardet). Crea **una sola tabla**, por defecto `data_analysis_table`. Fuente: https://github.com/eosphoros-ai/DB-GPT/blob/main/packages/dbgpt-app/src/dbgpt_app/scene/chat_data/chat_excel/excel_reader.py
- Código `excel_analyze/chat.py`: por cada archivo crea un `.duckdb` persistente en `DATA_DIR/_chat_excel_tmp/_chat_excel_{filename}.duckdb`, corre una fase "ExcelLearning" (resumen + preguntas sugeridas) y luego, por cada pregunta, manda al LLM el DDL de la tabla (`get_create_table_sql`) más **una muestra de 5 filas** (`SELECT * FROM {table} USING SAMPLE 5`). El LLM devuelve DuckDB SQL dentro de `<api-call><name>[display]</name><args><sql>…</sql></args></api-call>` y DB-GPT lo ejecuta con `get_df_by_sql_ex`. Fuente: https://github.com/eosphoros-ai/DB-GPT/blob/main/packages/dbgpt-app/src/dbgpt_app/scene/chat_data/chat_excel/excel_analyze/chat.py y el prompt en https://github.com/eosphoros-ai/DB-GPT/blob/main/packages/dbgpt-app/src/dbgpt_app/scene/chat_data/chat_excel/excel_analyze/prompt.py
- Formatos aceptados por el endpoint de upload para `chat_excel`: `.xls, .xlsx, .csv, .json, .parquet` (línea `if file_extension.lower() in [...]` en `api_v1.py`).

Dos observaciones importantes para Eleia:

- **Privacidad:** DB-GPT manda al LLM 5 filas reales de muestra. Si el archivo tiene datos personales, esa muestra viaja a Azure OpenAI sin enmascarar salvo que ustedes intercepten el prompt.
- **Sin validación read-only del SQL:** el `out_parser.py` de Chat Excel solo parsea el bloque `<api-call>`; no hay allow-list de `SELECT` ni bloqueo de `DROP/DELETE/COPY`. El único límite es que la conexión DuckDB es un archivo temporal propio, pero DuckDB por defecto puede leer/escribir el filesystem local (`COPY … TO`, `read_csv('/etc/…')`) si no se configura `enable_external_access=false`.

### 2. ¿Permite joinear MÚLTIPLES archivos en la misma consulta?

**No.** Es la limitación central para el caso de Tomás:

- En `api_v1.py`, endpoint `POST /api/v1/resource/file/upload`, está explícito:
  `if chat_mode == ChatScene.ChatExcel.value(): if len(file_params) != 1: return Result.failed(msg="Only one file is supported for Excel chat.")`
  Fuente: https://github.com/eosphoros-ai/DB-GPT/blob/main/packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/api_v1.py
- El PR #3206 "feat: support multi-file upload and analysis" (commit del 2026-08-21, incluido en v0.8.2) agregó multi-upload al endpoint, pero el chequeo de "un solo archivo" para `chat_excel` sigue vigente en `main`; el multi-archivo aplica a los otros modos (agentes/chat normal), donde los archivos se tratan como recursos de agente, no como tablas SQL joinables. Fuente: https://github.com/eosphoros-ai/DB-GPT/releases/tag/v0.8.2
- **Multi-hoja tampoco:** el issue #1290 "[Bug][ChatExcel] excel multi sheet bug" (14-mar-2024) preguntó cómo manejar varias hojas; se cerró como "stale" sin respuesta. El lector usa la primera hoja (DuckDB `read_xlsx` por defecto lee la primera). Fuente: https://github.com/eosphoros-ai/DB-GPT/issues/1290
- Issues relacionados que muestran la fricción: #2285 y #2317 (ene-2025) piden que los agentes acepten subir Excel como lo hace Chat Excel: https://github.com/eosphoros-ai/DB-GPT/issues/2285 , https://github.com/eosphoros-ai/DB-GPT/issues/2317 ; #2437 (mar-2025) bug de `duckdb_tables()` vacío en Chat Excel: https://github.com/eosphoros-ai/DB-GPT/issues/2437

Conclusión: para "cruzá este archivo con este otro por la columna Z" habría que **forkear** `chat_excel` (cargar N archivos en el mismo `.duckdb`, exponer N DDLs en el prompt y quitar el check del endpoint). Es hacible, pero pasás a mantener un fork de una app de 7 paquetes.

### 3. ¿100% self-hosted / air-gapped? ¿Azure OpenAI? ¿Modelo específico? ¿Embeddings?

- **Self-hosted sí.** Todo corre local (FastAPI + SQLite/MySQL + Chroma). Docs: "DB-GPT can be deployed on servers with lower hardware requirements through proxy LLMs. DB-GPT supports many proxy LLMs, such as OpenAI, Azure, DeepSeek, Ollama, and more." Fuente: https://github.com/eosphoros-ai/DB-GPT/blob/main/docs/docs/installation/advanced_usage/More_proxyllms.md
- **Azure OpenAI sí**, vía el proveedor `proxy/openai` con `api_type = "azure"`. Config documentada:
  ```toml
  [[models.llms]]
  name = "gpt-35-turbo"            # nombre del deployment
  provider = "proxy/openai"
  api_base = "https://your-resource-name.openai.azure.com/"
  api_key = "..."
  api_version = "2023-05-15"
  api_type = "azure"
  ```
  Instalación: `uv sync --all-packages --extra "base" --extra "proxy_openai" --extra "rag" --extra "storage_chromadb" --extra "dbgpts"` y `uv run dbgpt start webserver --config configs/dbgpt-proxy-azure.toml`. Detalle molesto: el archivo `configs/dbgpt-proxy-azure.toml` que citan las docs **no existe** en `main` (404 en raw; el directorio `configs/` tiene openai, litellm, ollama, deepseek, siliconflow, etc.), hay que crearlo a mano. También existe `dbgpt-proxy-litellm.toml`, otra vía a Azure. Fuente: https://github.com/eosphoros-ai/DB-GPT/tree/main/configs
- **Modelo:** no exige uno específico; el prompt de Chat Excel está pensado para "modelos de pocos parámetros" pero funciona con cualquier chat model. Ellos mismos usan GPT-4o por defecto en `dbgpt-proxy-openai.toml` (`LLM_MODEL_NAME:-gpt-4o`).
- **Embeddings:** el config de proxy trae obligatoriamente un bloque `[[models.embeddings]]` (por defecto `proxy/openai` → `text-embedding-3-small`). Chat Excel en sí no usa embeddings (es DDL + muestra + SQL), pero el webserver espera un embedding model configurado para las scenes de conocimiento; se puede apuntar a un deployment de embeddings en Azure o a un modelo local (docs Docker GPU usan `bge-large-zh-v1.5`). Fuente: https://github.com/eosphoros-ai/DB-GPT/blob/main/configs/dbgpt-proxy-openai.toml
- **Air-gapped real:** además del LLM, hay que preparar offline: wheels de `uv sync`, el modelo de embeddings (si va local), las **extensiones DuckDB** (`chat_excel` tiene `duckdb_extensions_dir` y `force_install` justamente porque DuckDB baja extensiones de extensions.duckdb.org) y el front (Next.js precompilado dentro de la imagen). Es factible pero no trivial.

### 4. Peso de despliegue

- **Requisitos:** Python 3.10+, `uv` obligatorio desde 0.7.0 ("Starting from version 0.7.0, DB-GPT uses uv"), SQLite por defecto (MySQL opcional), Chroma por defecto (Milvus/Qdrant/Elasticsearch/Valkey opcionales). Modo proxy: "The API proxy model requires relatively few resources and can be deployed and started on a CPU machine"; no publican cifras de RAM. Fuente: https://github.com/eosphoros-ai/DB-GPT/blob/main/docs/docs/quickstart.md
- **Docker oficial:** `eosphorosai/dbgpt-openai:latest` — "A lightweight Docker image containing only the proxy model in DB-GPT (CPU)", 552,2 MB comprimida, 10K+ pulls, actualizada hace 15 días. Fuente: https://hub.docker.com/r/eosphorosai/dbgpt-openai . La imagen completa con GPU es `eosphorosai/dbgpt`: https://hub.docker.com/r/eosphorosai/dbgpt
- **docker-compose.yml** del repo: 2 servicios (`mysql/mysql-server` + `webserver` con `dbgpt-openai`), monta `/data`, `/data/models`, y está cableado a SiliconFlow (`SILICONFLOW_API_KEY`), hay que reescribir el TOML para Azure. Fuente: https://github.com/eosphoros-ai/DB-GPT/blob/main/docker-compose.yml
- **Complejidad real (issues):** 17 issues con "install" creados en 2026; ejemplos: cuelgue instalando `llama-cpp-python` (#2540), extensión Milvus faltante al construir imagen 0.8.0, spacy incompatible con Python 3.13, "Server can not up? who can help me?" (ene-2026). Fuente: https://github.com/eosphoros-ai/DB-GPT/issues?q=is%3Aissue+install+created%3A%3E2026-01-01
- **Arquitectura:** 7 paquetes (`dbgpt-core`, `dbgpt-app`, `dbgpt-serve`, `dbgpt-ext`, `dbgpt-client`, `dbgpt-sandbox`, `dbgpt-accelerator`) + front Next.js. Es una **plataforma** (multi-agente, AWEL flows, knowledge spaces, GraphRAG, MCP), no una librería. Para el caso "una pregunta sobre un CSV" es un elefante.

### 5. Madurez

- **Stars/forks:** 19.925 / 2.920 (API GitHub, 2026-09-10). **Licencia MIT.** Creado 2023-04-13. Último push 2026-09-08. Fuente: https://api.github.com/repos/eosphoros-ai/DB-GPT
- **Issues:** 371 abiertas vs 1.323 cerradas (search API, tipo issue). 
- **Releases 2025-2026:** v0.7.3 (2025-07-25), v0.7.4 (2025-10-24), v0.7.5 (2026-02-11), v0.8.0 (2026-03-27), v0.8.1 (2026-06-18), v0.8.2 (2026-08-26): ~1 release cada 2-3 meses. Fuente: https://github.com/eosphoros-ai/DB-GPT/releases
- **Quién lo mantiene:** nació en Ant Group (junio 2023) y lo mantiene la comunidad eosphoros-ai ("technology enthusiasts from AntGroup, JD, internet companies and NLP graduate students"). Fuente: https://github.com/eosphoros-ai/community
- **Idioma:** docs bilingües EN/ZH; en una muestra de las 9 issues más recientes, 2 estaban en chino. Los ejemplos del prompt de Chat Excel están en chino (`SELECT region AS 地区…`). La comunidad es mayormente china, pero la documentación en inglés es usable (aunque desactualizada en puntos como el TOML de Azure).
- **Producción:** el paper (arXiv 2312.17449) lo describe como "production-ready", pero **no encontré casos de uso en producción documentados con nombre de empresa** fuera de Ant/afiliados. Fuente: https://arxiv.org/pdf/2312.17449
- **Historial de seguridad (relevante para un producto que se llama "Guardian"):** GitHub registra 8 advisories publicados el 2025-03-20 (CVE-2024-10901 arbitrary file write, CVE-2024-10835 SQL injection no autenticada, CVE-2024-10902 upload con path traversal, etc.), CVE-2025-51459 (RCE por upload de plugin, parcheado en PR #2649), y **CVE-2026-80104 / GHSA-x75h-xjfp-qrh8, severidad critical, publicada 2026-08-25** (path traversal → RCE en `skill_upload`, sin autenticación). Además issues abiertas: #3167 "Unauthenticated command execution through ReAct shell_interpreter bypasses local-runtime opt-in" (2026-07-29, abierta), #3082 "Sandbox API silently falls back to LocalRuntime and executes code on host" (cerrada jun-2026), y una del 2026-09-10 "Incomplete fix for CVE-2026-73034". Fuentes: https://github.com/advisories?query=dbgpt , https://www.gecko.security/blog/cve-2025-51459 , https://github.com/eosphoros-ai/DB-GPT/issues/3167

### 6. Integración como servicio (sin su UI)

- **API v2 OpenAI-compatible:** `POST /api/v2/chat/completions` con `extra_body={"chat_mode": ...}`; los `chat_mode` documentados son `chat_normal`, `chat_app`, `chat_knowledge`, `chat_flow` (chat_param = app_id/space_id/flow_id). **`chat_excel` no está en la API v2 documentada.** Fuente: https://github.com/eosphoros-ai/DB-GPT/blob/main/docs/docs/api/chat.md
- **API v1 (la que usa la UI):** sí permite hacer todo el flujo Chat Excel por HTTP, aunque no está documentada como API pública:
  1. `POST /api/v1/resource/file/upload?chat_mode=chat_excel&conv_uid=<uuid>` con multipart `doc_files` → devuelve `file_param` `{is_oss, file_path, file_name, file_learning, bucket}` y dispara la fase de aprendizaje.
  2. `POST /api/v1/chat/completions` con `{"chat_mode":"chat_excel","conv_uid":…, "select_param": <file_param>, "user_input": "…"}` → stream SSE con el `<api-call>` renderizado (tabla/gráfico en formato "vis" para su front).
  Fuente: https://github.com/eosphoros-ai/DB-GPT/blob/main/packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/api_v1.py
- **SDK:** paquete `dbgpt-client` (Python) cubre chat/flow/app/knowledge; no cubre el upload de Chat Excel. Desde Node harían HTTP directo contra v1. El resultado vuelve como un blob "vis" (JSON envuelto en markdown) pensado para su UI; extraer la tabla limpia requiere parsearlo.
- **Licencia:** MIT (repo completo). 

---

### TAREA A.7 — Alternativas más chicas para "subir archivo → preguntas tabulares exactas"

### PandasAI (sinaptik-ai/pandas-ai)

- **Licencia:** MIT Expat, **excepto** todo lo que esté bajo `pandasai/ee/` (licencia enterprise propia). GitHub lo clasifica como "Other" por eso. No es ELv2. Fuente: https://docs.pandas-ai.com/v3/license y https://github.com/sinaptik-ai/pandas-ai/blob/main/LICENSE
- **Madurez:** 23.792 stars, 2.342 forks, 22 issues abiertas. **v3.0.0 estable el 2025-10-07**; último commit **2025-10-28** (más de 10 meses sin actividad al día de hoy, solo fixes de docs en octubre). Requiere `python >=3.8,<3.12`. Fuentes: https://api.github.com/repos/sinaptik-ai/pandas-ai , https://github.com/sinaptik-ai/pandas-ai/releases , https://github.com/sinaptik-ai/pandas-ai/blob/main/pyproject.toml
- **Múltiples archivos/joins:** sí, `pai.chat("Who gets paid the most?", employees_df, salaries_df)` (README) y ejemplo con 3 dataframes en docs. Fuente: https://github.com/sinaptik-ai/pandas-ai#multiple-dataframes
- **LLM:** vía `pandasai-litellm` → Azure OpenAI soportado por LiteLLM. Air-gapped: sí (no llama a casa salvo el LLM; la telemetría no está documentada en la página de seguridad, verificar `PANDASAI_TELEMETRY`).
- **Seguridad:** genera y **ejecuta código Python** (`pandasai/core/code_execution/code_executor.py`). La doc de seguridad admite "potential risk that malicious users might attempt to manipulate the LLM into generating harmful code" y recomienda el sandbox Docker (`pip install pandasai-docker`, `DockerSandbox()`) para "production environments", "sensitive data" y "multi-tenant environments". Fuente: https://docs.pandas-ai.com/v3/privacy-security
- **Peso:** librería pip + Docker daemon si usás sandbox (un contenedor por sesión).
- **Veredicto:** cumple funcionalmente, pero ejecuta Python arbitrario (con sandbox opcional), el proyecto está frenado desde octubre 2025 y te ata a Python ≤3.11.

### Vanna.ai (vanna-ai/vanna)

- **Licencia MIT.** 23.815 stars. **Repositorio ARCHIVADO el 2026-03-29 (read-only)**, sin explicación oficial; último release v2.0.2 (2026-02-02). Fuentes: https://github.com/vanna-ai/vanna , https://dev.to/ashish_sinha_5241c7673d93/vanna-is-archived-what-that-means-if-you-have-it-in-production-3jmk
- Técnicamente encajaba: text-to-SQL con RAG de DDL/doc/ejemplos, `vn.connect_to_duckdb(...)`, Azure OpenAI vía `AzureOpenAI` client, vector store local (Chroma/Qdrant). Los CSV hay que cargarlos primero a DuckDB. Fuente: https://ask.vanna.ai/docs/duckdb-openai-azure-qdrant/
- **Veredicto:** descartada por archivada (sin parches de seguridad ni dependencias).

### WrenAI (Canner/WrenAI)

- **Licencia:** multi-licencia: `core/`, `sdk/`, `skills/`, `examples/` y raíz **Apache-2.0**; `docs/` CC BY 4.0; el LICENSE avisa que futuros módulos pueden ser **AGPL-3.0-only**; marcas "Wren/WrenAI" no licenciadas. Modelo open-core (RLS/CLS y dashboards comerciales son Cloud/Enterprise). Fuente: https://github.com/Canner/WrenAI/blob/main/LICENSE
- **Madurez:** 17.567 stars, 2.000 forks, 316 issues abiertas, releases semanales (wren-v0.14.0 el 2026-09-08). Fuente: https://api.github.com/repos/Canner/WrenAI
- **Archivos:** DuckDB como fuente, pero se cargan con "Initial SQL Statements" (`CREATE TABLE AS SELECT * FROM read_csv(...)`) desde rutas locales/S3; formatos documentados CSV/JSON/Parquet, **Excel no documentado**; el "CSV Upload" por UI es de la versión Cloud (docs `cp/`). Fuente: https://docs.getwren.ai/oss/guide/connect/duckdb
- **LLM:** LiteLLM ("you can use any LLM supported by LiteLLM"), embeddings locales vía Ollama posibles. Fuente: https://docs.getwren.ai/oss/ai_service/guide/custom_llm
- **Peso:** docker compose con `wren-ai-service`, `wren-ui`, `wren-engine`, `ibis-server`, `qdrant` (5 contenedores, Rust+Python+Node), requiere modelar un MDL (semantic layer) por dataset: pensado para BI gobernado sobre un warehouse, no para "subí tu Excel y preguntá". Fuente: https://github.com/Canner/WrenAI/tree/main/docker
- **Seguridad:** solo SQL (bien). 
- **Veredicto:** demasiado pesado y con flujo de ingesta manual; over-kill para el caso.

### DuckDB + Azure OpenAI directo (text-to-SQL "casero")

- **DuckDB** es una librería in-process (pip `duckdb`, sin servidor, MIT). La **extensión `excel` es core y autoload**: `SELECT * FROM 'archivo.xlsx'` o `read_xlsx(file, sheet:='Hoja2', header:=true, range:='A1:F500', all_varchar:=…)`; **`.xls` no soportado** (convertir con pandas/openpyxl o exigir xlsx). Fuente: https://duckdb.org/docs/stable/core_extensions/excel
- **Air-gapped:** las extensiones se bajan de extensions.duckdb.org; hay que pre-descargar el `.duckdb_extension` de la versión exacta y setear `extension_directory`, o usar un build con extensiones estáticas. Fuente: https://medium.com/@kennykarnama/loading-duckdb-extensions-in-an-air-gapped-environment-1c09db6ae5be
- **Hardening documentado por DuckDB** para ejecutar SQL no confiable: `SET enable_external_access = false` (bloquea ATTACH/COPY/read_csv a paths), `SET disabled_filesystems = 'LocalFileSystem'`, `SET autoload_known_extensions = false; SET autoinstall_known_extensions = false`, `SET memory_limit`, `SET threads`, y `SET lock_configuration = true` al final. Fuente: https://duckdb.org/docs/current/operations_manual/securing_duckdb/overview.html
- **Patrón:** cargar cada archivo subido como tabla en una conexión DuckDB efímera por conversación → generar DDL (`DESCRIBE`) + muestra **enmascarada** por su pipeline actual → prompt a Azure OpenAI pidiendo un único `SELECT` DuckDB → validar con `sqlglot` (parsear, rechazar todo lo que no sea SELECT/CTE, sin funciones de archivo) → `EXPLAIN` → ejecutar con timeout (`conn.interrupt()` en un thread) y `LIMIT` → devolver tabla + SQL. Reintentar una vez con el error si falla. Hay decenas de ejemplos publicados de este patrón (p.ej. https://vegarag.com/blog/text-to-sql-duckdb-uploaded-csv-excel-files , https://motherduck.com/blog/langchain-sql-agent-duckdb-motherduck/ ).
- **Joins entre archivos:** nativos (cada archivo es una tabla; el LLM ve todos los DDL).
- **Modelos especializados (no necesarios con Azure OpenAI):** `motherduckdb/DuckDB-NSQL-7B-v0.1` (Llama-2-7B fine-tuned, repo Apache-2.0, 337 stars, GPU local) https://github.com/NumbersStationAI/DuckDB-NSQL ; `defog-ai/sqlcoder` (4.049 stars, código Apache-2.0, pesos CC BY-SA 4.0, último push 2024-05-23, dormido) https://github.com/defog-ai/sqlcoder ; `TableGPT2-7B` (Qwen2.5-7B, Apache-2.0, agente `tablegpt-agent` 636 stars, ejecuta Python) https://huggingface.co/tablegpt/TableGPT2-7B . Todos exigen GPU local y no superan a GPT-4o-class en este caso.

### Otros que pediste evaluar (más cortos, porque no aplican)

| Proyecto | Datos verificados | Por qué no |
|---|---|---|
| **Dataherald** | 3.647 stars, Apache-2.0, último push 2024-07-24, último release 1.0.3 (2024-04-30). No está marcado "archived" pero está muerto. https://api.github.com/repos/Dataherald/dataherald | Dormido 2 años; requiere MongoDB + BD relacional conectada, no archivos. |
| **Chat2DB** (ahora OtterMind/Chat2DB) | 28.103 stars; licencia "source-available basada en Apache-2.0 con condiciones adicionales" desde v5.3.0; Java 17; Docker "2+ CPU, 4+ GiB". https://github.com/CodePhiliaX/Chat2DB | Es un cliente SQL de escritorio/web para DBAs, no un backend embebible; licencia con restricciones. |
| **SQLChat** | 5.846 stars, MIT, último push 2026-04-21, Next.js, endpoint OpenAI configurable. https://github.com/sqlchat/sqlchat | Cliente de chat contra bases conectadas; no ingesta archivos; no es API. |
| **LlamaIndex PandasQueryEngine** | Doc oficial: "This tool provides the LLM access to the eval function. Arbitrary code execution is possible… not recommended to be used in a production setting without heavy sandboxing". Un solo dataframe. https://developers.llamaindex.ai/python/examples/query_engine/pandas_query_engine/ | Python arbitrario vía eval; sin multi-df. |
| **LangChain SQL agent + DuckDB** | Docs: las tools demo "are not intended to be secure or for production use"; recomiendan permisos mínimos, prohibir INSERT/UPDATE/DELETE/DROP y human-in-the-loop. https://docs.langchain.com/oss/python/langchain/sql-agent | Es el mismo patrón "casero" con una dependencia gorda encima; para una pregunta de negocio no hace falta un agente ReAct de N vueltas. |
| **Quadratic** | Cerró el código en marzo 2026 (repo `quadratichq/quadratic` ya no accesible: 404; queda `quadratic-selfhost`). https://www.quadratichq.com/blog/quadratic-announces-the-self-hosted-spreadsheet | Ya no es open source; es un producto de hoja de cálculo, no un componente. |
| **Semantic Kernel NL2SQL** | Template Azure-Samples `semantic-kernel-advanced-usage/templates/natural_language_to_SQL`. https://github.com/Azure-Samples/semantic-kernel-advanced-usage | Sirve como referencia de prompt/pipeline; no es un producto, y SK en Python es una capa innecesaria si ya tienen cliente Azure OpenAI. |
| **open-interpreter** | 68.293 stars, Apache-2.0, pero pivotó a "A coding agent for open models like Kimi K3 and GLM 5.3". https://github.com/openinterpreter/open-interpreter | Ejecuta shell/Python en el host; es un agente de coding, no un servicio. |
| **LibreChat Code Interpreter** | La API oficial es cerrada y paga; hay sandbox self-hosted `LibreChat-AI/code-interpreter` (Apache-2.0, 119 stars). https://www.librechat.ai/docs/features/code_interpreter | Otro chat UI completo + sandbox de código arbitrario; duplica Eleia Hub. |
| **Jupyter AI** | 4.401 stars, BSD-3. https://github.com/jupyterlab/jupyter-ai | Para notebooks, usuario técnico; no es "subí y preguntá". |

---

### Tabla comparativa

| Criterio | DB-GPT Chat Excel | PandasAI v3 | Vanna | WrenAI OSS | **DuckDB + Azure OpenAI (propio)** |
|---|---|---|---|---|---|
| Licencia | MIT | MIT + `ee/` propietario | MIT (archivado) | Apache-2.0 core, AGPL posible | MIT (duckdb) + código propio |
| Air-gapped | Sí, con trabajo (uv wheels, extensiones DuckDB, embeddings) | Sí | Sí | Sí (5 contenedores) | Sí (pre-bundlear extensión excel) |
| Múltiples archivos / joins | **No** ("Only one file is supported for Excel chat"); multi-hoja no | Sí | Sí (si cargás a DuckDB) | Sí (con MDL manual) | **Sí, nativo** |
| Excel `.xlsx` / `.xls` | xlsx/xls/csv/json/parquet | csv/parquet (xlsx vía pandas) | Lo que cargues | csv/json/parquet documentados | xlsx nativo; xls vía pandas |
| Azure OpenAI | Sí (`proxy/openai` + `api_type=azure`) | Sí (LiteLLM) | Sí | Sí (LiteLLM) | Sí (ya lo tienen) |
| Qué ejecuta | SQL DuckDB **sin validación read-only** | **Python arbitrario** (sandbox Docker opcional) | SQL | SQL | SQL **con allow-list SELECT + DuckDB hardened** |
| Enmascarado antes del LLM | No integrado; manda 5 filas crudas | No integrado | No integrado | No integrado | Reusa el pipeline actual de Eleia |
| Peso operativo | Plataforma: 7 paquetes, front Next.js, SQLite/MySQL, Chroma, imagen 552 MB | 1 lib + Docker sandbox; Python ≤3.11 | 1 lib + vector store | 5 contenedores + modelado | 1 dependencia (`duckdb`, opcional `sqlglot`) |
| Madurez / actividad | 19,9k★, release cada 2-3 meses, activo | 23,8k★, **sin commits desde 2025-10-28** | 23,8k★, **archivado 2026-03-29** | 17,6k★, releases semanales | DuckDB: proyecto maduro y muy activo |
| Historial seguridad | 8 GHSA (2025), CVE-2025-51459, **CVE-2026-80104 critical (ago-2026)**, issues abiertas de RCE | Riesgo inherente a exec de código | n/a | Sin CVEs conocidos | Superficie mínima, controlada por ustedes |
| Integración desde app Python/Node | API v1 no documentada + parseo de formato "vis"; SDK sin upload Excel | Import directo (Python) | Import directo | REST/MCP | Endpoint propio en el backend FastAPI existente |
| Esfuerzo estimado | Alto: desplegar + forkear chat_excel para multi-archivo + interceptar prompt para enmascarar + endurecer | Medio: integrar lib + sandbox + Python ≤3.11 | n/a | Alto | **Bajo-medio: ~300-500 líneas + tests** |

---

### RECOMENDACIÓN (no neutral)

**DB-GPT no es la pieza correcta para este caso.** Razones concretas, con evidencia:

1. **No resuelve la queja principal.** Tomás quiere cruzar archivos; Chat Excel acepta exactamente un archivo (`"Only one file is supported for Excel chat."`) y una sola hoja. Usarlo implica forkear la scene y el endpoint, y mantener ese fork sobre una plataforma que cambia cada 2-3 meses.
2. **Es una plataforma completa que duplica a Eleia Hub** (multi-agente, knowledge spaces, flows, UI propia, su propia BD y vector store). Ustedes ya tienen gateway, RAG, control de costos y enmascarado; DB-GPT no se enchufa como librería, se enchufa como *otro producto* al lado, con API v1 no documentada y respuestas en un formato "vis" pensado para su front.
3. **Historial de seguridad incompatible con un producto llamado Guardian**: CVE crítica de RCE no autenticada publicada hace dos semanas (CVE-2026-80104, 2026-08-25), issue abierta de ejecución de comandos no autenticada (#3167), 8 advisories en 2025. Aunque se aísle en red, es una superficie enorme para meter en un despliegue on-premise de un cliente.
4. **Privacidad:** Chat Excel manda 5 filas reales al LLM y no valida que el SQL sea solo lectura. Habría que interceptarlo por fuera.

**Lo que sí recomiendo: construir un módulo "Chat Tabular" dentro del backend Python de Eleia Hub, con DuckDB in-process + Azure OpenAI, SQL solo-lectura.** Es lo que DB-GPT hace por dentro para Chat Excel (DuckDB + DDL + muestra + prompt), pero sin la plataforma alrededor, con multi-archivo desde el día uno, y con el enmascarado que ya tienen aplicado a la muestra y a los resultados. Diseño mínimo:

- Ingesta: por conversación, una conexión DuckDB efímera (`:memory:` o archivo por sesión); cada Excel/CSV subido → una tabla (`read_xlsx` por hoja, `read_csv_auto`); normalizar nombres de columnas; guardar catálogo `{archivo, hoja, tabla, columnas, tipos, n_filas}`. Los archivos tabulares **no** van al vector store (eso fue la causa raíz).
- Prompt: DDL de todas las tablas + 3-5 filas de muestra **ya enmascaradas** por el pipeline actual + reglas DuckDB (podés copiar las del prompt de DB-GPT, que están bien) + "devolvé un único SELECT". Con GPT-4o/4.1 en Azure la precisión para sumas/filtros/joins por columna es muy alta; la fuente de verdad es el motor, no el modelo.
- Guardrails: parsear con `sqlglot` (dialecto duckdb), permitir solo `SELECT`/`WITH`, rechazar `COPY`, `ATTACH`, `INSTALL`, `LOAD`, funciones de archivo y `PRAGMA`; sesión DuckDB con `enable_external_access=false`, `autoload_known_extensions=false`, `memory_limit`, `threads`, `lock_configuration=true`; timeout con `interrupt()`; `LIMIT` por defecto; un reintento con el mensaje de error de DuckDB.
- Respuesta: tabla (JSON) + el SQL ejecutado (auditable, y Tomás como analista lo va a valorar) + resumen corto en lenguaje natural generado a partir del resultado, no al revés.
- Air-gapped: pre-bundlear la extensión `excel` para la versión exacta de DuckDB (o forzar xlsx→CSV con openpyxl en la ingesta y no depender de la extensión).
- Esfuerzo: un endpoint nuevo, un módulo de ~300-500 líneas, tests con 3-4 archivos de Finanzas. Sin nuevos contenedores, sin nueva BD, sin GPU, sin modelo especializado.

**Plan B**, solo si aparece la necesidad de cosas que SQL no cubre bien (pivots raros, regresiones, gráficos): PandasAI v3 con `DockerSandbox` obligatorio. Pero ojo: ejecuta Python generado por el LLM, exige Python ≤3.11, y el proyecto lleva 10 meses sin commits. No lo pondría en el core de Guardian.

**Descartados:** Vanna (archivado), WrenAI (5 contenedores + modelado MDL, sin upload de Excel en OSS), Dataherald/sqlcoder (dormidos), Quadratic (cerró el código), Chat2DB/SQLChat (clientes SQL, no backends), LlamaIndex Pandas / open-interpreter / LibreChat CI (código arbitrario).

---

### Fuentes (todas consultadas 2026-09-10)

1. https://github.com/eosphoros-ai/DB-GPT (README, stars, licencia)
2. https://api.github.com/repos/eosphoros-ai/DB-GPT (19.925★, 2.920 forks, MIT, push 2026-09-08)
3. https://github.com/eosphoros-ai/DB-GPT/releases (v0.7.3 → v0.8.2, fechas)
4. https://github.com/eosphoros-ai/DB-GPT/releases/tag/v0.8.2 (multi-file upload PR #3206)
5. https://github.com/eosphoros-ai/DB-GPT/blob/main/packages/dbgpt-app/src/dbgpt_app/scene/chat_data/chat_excel/excel_reader.py (DuckDB, read_xlsx, tabla única)
6. https://github.com/eosphoros-ai/DB-GPT/blob/main/packages/dbgpt-app/src/dbgpt_app/scene/chat_data/chat_excel/excel_analyze/chat.py (.duckdb por archivo, muestra 5 filas)
7. https://github.com/eosphoros-ai/DB-GPT/blob/main/packages/dbgpt-app/src/dbgpt_app/scene/chat_data/chat_excel/excel_analyze/prompt.py (prompt DuckDB, formato api-call)
8. https://github.com/eosphoros-ai/DB-GPT/blob/main/packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/api_v1.py ("Only one file is supported for Excel chat", endpoints v1)
9. https://github.com/eosphoros-ai/DB-GPT/blob/main/docs/docs/application/apps/chat_excel.md (docs Chat Excel)
10. https://github.com/eosphoros-ai/DB-GPT/blob/main/docs/docs/installation/advanced_usage/More_proxyllms.md (Azure OpenAI config)
11. https://github.com/eosphoros-ai/DB-GPT/blob/main/configs/dbgpt-proxy-openai.toml (embeddings obligatorios, SQLite, Chroma)
12. https://github.com/eosphoros-ai/DB-GPT/blob/main/docs/docs/quickstart.md (uv, CPU en modo proxy)
13. https://github.com/eosphoros-ai/DB-GPT/blob/main/docker-compose.yml (MySQL + dbgpt-openai)
14. https://hub.docker.com/r/eosphorosai/dbgpt-openai (552,2 MB, 10K+ pulls)
15. https://github.com/eosphoros-ai/DB-GPT/issues/1290 (multi-sheet, cerrado stale)
16. https://github.com/eosphoros-ai/DB-GPT/issues/2285 y https://github.com/eosphoros-ai/DB-GPT/issues/2317 (agentes sin upload)
17. https://github.com/eosphoros-ai/DB-GPT/issues/2437 (bug duckdb_tables en Chat Excel)
18. https://github.com/eosphoros-ai/DB-GPT/issues/3167 (command execution no autenticada, abierta)
19. https://github.com/advisories?query=dbgpt (8 GHSA 2025-03-20; GHSA-x75h-xjfp-qrh8 / CVE-2026-80104 critical 2026-08-25)
20. https://www.gecko.security/blog/cve-2025-51459 (RCE plugin upload)
21. https://github.com/eosphoros-ai/community (origen Ant Group, comunidad)
22. https://arxiv.org/pdf/2312.17449 (paper DB-GPT)
23. https://github.com/eosphoros-ai/DB-GPT/blob/main/docs/docs/api/chat.md (API v2, chat_mode)
24. https://github.com/sinaptik-ai/pandas-ai y https://api.github.com/repos/sinaptik-ai/pandas-ai (23.792★, v3.0.0 2025-10-07, push 2025-10-28)
25. https://docs.pandas-ai.com/v3/license (MIT + ee/)
26. https://docs.pandas-ai.com/v3/privacy-security (sandbox Docker recomendado)
27. https://github.com/sinaptik-ai/pandas-ai/blob/main/pyproject.toml (python >=3.8,<3.12)
28. https://github.com/vanna-ai/vanna y https://api.github.com/repos/vanna-ai/vanna (archivado 2026-03-29, MIT, 23.815★)
29. https://ask.vanna.ai/docs/duckdb-openai-azure-qdrant/ (DuckDB + Azure en Vanna)
30. https://dev.to/ashish_sinha_5241c7673d93/vanna-is-archived-what-that-means-if-you-have-it-in-production-3jmk
31. https://github.com/Canner/WrenAI/blob/main/LICENSE (Apache-2.0 / CC BY 4.0 / AGPL futuro)
32. https://api.github.com/repos/Canner/WrenAI (17.567★, 316 issues)
33. https://docs.getwren.ai/oss/guide/connect/duckdb (Initial SQL, CSV/JSON/Parquet)
34. https://docs.getwren.ai/oss/ai_service/guide/custom_llm (LiteLLM)
35. https://api.github.com/repos/Dataherald/dataherald (3.647★, push 2024-07-24)
36. https://github.com/defog-ai/sqlcoder (4.049★, push 2024-05-23)
37. https://github.com/NumbersStationAI/DuckDB-NSQL y https://huggingface.co/motherduckdb/DuckDB-NSQL-7B-v0.1
38. https://huggingface.co/tablegpt/TableGPT2-7B y https://github.com/tablegpt/tablegpt-agent
39. https://github.com/CodePhiliaX/Chat2DB (28.103★, licencia source-available)
40. https://github.com/sqlchat/sqlchat (5.846★, MIT)
41. https://www.quadratichq.com/blog/quadratic-announces-the-self-hosted-spreadsheet (Quadratic closed-source desde marzo 2026)
42. https://developers.llamaindex.ai/python/examples/query_engine/pandas_query_engine/ (warning eval)
43. https://docs.langchain.com/oss/python/langchain/sql-agent (warning seguridad SQL agent)
44. https://github.com/openinterpreter/open-interpreter (68.293★, pivot a coding agent)
45. https://www.librechat.ai/docs/features/code_interpreter y https://github.com/LibreChat-AI/code-interpreter
46. https://github.com/jupyterlab/jupyter-ai (4.401★, BSD-3)
47. https://duckdb.org/docs/stable/core_extensions/excel (read_xlsx, autoload, sin .xls)
48. https://duckdb.org/docs/current/operations_manual/securing_duckdb/overview.html (enable_external_access, lock_configuration, autoload)
49. https://medium.com/@kennykarnama/loading-duckdb-extensions-in-an-air-gapped-environment-1c09db6ae5be
50. https://vegarag.com/blog/text-to-sql-duckdb-uploaded-csv-excel-files y https://motherduck.com/blog/langchain-sql-agent-duckdb-motherduck/ (patrón casero)
51. https://github.com/Azure-Samples/semantic-kernel-advanced-usage (template NL2SQL)
