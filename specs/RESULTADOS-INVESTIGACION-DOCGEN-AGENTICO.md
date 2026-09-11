# Generación de documentos desde el chat: enfoques agénticos (skills, CLIs de agentes, MCP, code interpreter) — investigación complementaria a la spec 045

**Fecha**: 2026-09-10 · **Estado**: investigación cerrada, sin tocar código · **Complementa** a `RESULTADOS-INVESTIGACION-DOCGEN-DBGPT.md` (Parte 1), que cubrió librerías y motores de plantillas. Este documento cubre la familia que faltaba: el modelo escribe y ejecuta código, skills de documentos, CLIs de agentes de código en modo headless, servidores MCP de Office, sandboxes y plataformas completas.

**Método**: tres relevamientos en paralelo contra fuentes primarias (repos y API de GitHub, docs oficiales, licencias, releases, issues, un paper con mediciones). Más de 150 URLs citadas en los anexos. Los datos numéricos son del 10-sep-2026.

---

## Respuesta corta a la duda planteada

**Sí, se puede generar documentos desde el chat, y hay muchas formas de hacerlo.** El informe anterior nunca dijo lo contrario: AnythingLLM ya genera docx/pptx/xlsx/pdf hoy, y hay decenas de librerías. Lo que el informe anterior marcó como hueco es un punto más fino: **rellenar la plantilla corporativa del cliente** de forma determinista. Esta investigación confirma que la familia agéntica que viste (Claude Code, Codex, skills, MCP, "el modelo escribe Python") existe, funciona, y **es viable air-gapped con Azure OpenAI**, con tres condiciones que hay que tener claras:

1. **Las skills de documentos de Anthropic (docx, pptx, xlsx, pdf) no se pueden reutilizar.** Su licencia es propietaria: prohíbe extraer, copiar, derivar y distribuir. Claude Code no acepta Azure OpenAI como proveedor, y la Skills API de Anthropic es SaaS sin variante air-gapped (la variante de Claude alojada en Azure no soporta ni skills ni ejecución de código). Lo que sí es abierto es el **estándar Agent Skills** (Apache-2.0), que soportan Codex CLI, OpenCode, Goose, OpenHands, Gemini CLI, Cursor, Copilot y muchos más. Hay que escribir skills propias.
2. **Todo enfoque agéntico necesita un sandbox sin red** porque el modelo ejecuta código arbitrario. Los sandboxes de moda no sirven on-prem: E2B solo se auto-hostea en GCP/AWS, Daytona congeló su repo público en junio 2026, los basados en Pyodide fueron archivados en enero 2026 por inseguros. Los que sí sirven: Docker/Podman con imagen propia (vía la librería `llm-sandbox`, MIT) endurecido con gVisor, OpenSandbox de Alibaba (Apache-2.0) como plataforma, o microsandbox (microVM, requiere KVM).
3. **Cuesta entre 3 y 10 veces más que una plantilla determinista** en tokens y latencia, y la salida no es reproducible. Es el precio de la flexibilidad.

**Recomendación final: arquitectura híbrida con router.** Motor de plantillas determinista por defecto (lo ya recomendado: docxtpl + pptx-automizer + openpyxl + Gotenberg), y un "modo libre" agéntico opt-in para pedidos sin plantilla, decks creativos o edición de documentos subidos. Las dos vías comparten los mismos scripts, la misma imagen Docker con LibreOffice y el mismo endpoint de descarga firmada. El detalle está en la sección "Arquitectura recomendada".

---

## Los cinco enfoques, comparados

| Enfoque | Cómo funciona | Plantillas del cliente | Determinismo | Costo por documento (tokens, latencia) | Air-gap con Azure OpenAI | Riesgo principal | Veredicto para Eleia |
|---|---|---|---|---|---|---|---|
| **1. Motor de plantillas determinista** (docxtpl, pptx-automizer, openpyxl, Carbone, Gotenberg) | El LLM produce JSON validado contra un schema; el backend lo vuelca en la plantilla | **Sí, es su razón de ser** | Total: misma entrada, mismo archivo | 0,8 a 2,5k tokens; 5 a 15 s | Sí, trivial | Hay que preparar plantilla + schema por tipo de documento | **Camino principal** |
| **2. Skills de documentos + CLI de agente headless** (Codex CLI, OpenCode, Goose, OpenHands) | Un CLI de agente corre como subproceso con skills en Markdown + scripts, escribe código y lo ejecuta en su sandbox | Sí: puede abrir el .pptx del cliente, duplicar diapositivas, editar XML | Bajo: cada documento nace de un script distinto | 100 a 250k tokens por deck de 15 slides según mediciones publicadas; minutos | Sí con **Codex CLI** (Apache-2.0, Azure nativo, sandbox bubblewrap) u OpenHands (Docker). Claude Code no | Código arbitrario, prompt injection desde RAG, licencia de skills de terceros | **Modo libre**, opt-in |
| **3. Code interpreter propio** (el backend manda código generado a un sandbox) | Mismo principio que 2 pero sin CLI de terceros: smolagents CodeAgent o `llm-sandbox` + imagen Docker propia con LibreOffice | Sí, igual que 2 | Bajo-medio: se puede acotar con scripts deterministas expuestos como funciones | 3 a 8k tokens de salida por documento; 15 a 60 s (extrapolación de un paper de 2025) | Sí, total | Igual que 2, pero con control fino del sandbox y del conteo de tokens | **Modo libre, opción preferida** sobre el enfoque 2 |
| **4. Servidores MCP de Office** (Word/PowerPoint/Excel MCP de terceros) | El agente arma el documento a golpes de tool calls (`add_paragraph`, `add_slide`...) | Parcial: abren archivos existentes, pero sin clonar slides ni placeholders con nombre | Bajo: depende de que el modelo ordene 20 a 30 llamadas | Un round-trip a Azure por llamada; timeouts de 60 s del SDK | Sí | Los dos MCP más populares (GongRzhe Word y PowerPoint) están **archivados**; AnythingLLM no entrega al usuario archivos generados por un MCP | **No como motor.** Sí como **contrato** para exponer el motor propio al agente (2 a 4 tools de alto nivel) |
| **5. Plataforma completa** (Open WebUI, LibreChat, Dify, Onyx, DeerFlow, Suna, Presenton) | Adoptar un producto que ya trae code interpreter o generación de Office | No (salvo el plugin md_exporter de Dify y Presenton, parciales) | Variable | Variable | Casi todas sí, con licencias con cláusulas (Open WebUI branding, Dify multi-tenant, Suna pasó a Elastic 2.0, n8n Sustainable Use) | Reemplazar el backend de Eleia por otro producto | **No.** Sí robar piezas: imagen Docker de Open Terminal (MIT, trae LibreOffice), md_exporter (Apache-2.0) |

### Harnesses y sandboxes: los que sirven y los que no

| Pieza | Licencia | Azure OpenAI | Sandbox propio | Estado (sep-2026) | Veredicto |
|---|---|---|---|---|---|
| **Codex CLI** (`codex exec`) | Apache-2.0 | Sí, nativo (Responses API v1, sin Entra ID) | Sí (bubblewrap en Linux, red apagada por defecto) | v0.154 | **Primer CLI candidato** |
| **smolagents CodeAgent** | Apache-2.0 | Sí | Docker / AST allowlist | v1.26 | **Primera librería candidata** |
| **llm-sandbox** | MIT | n/a (es el ejecutor) | Docker, Podman rootless, K8s; runtime gVisor configurable | v0.3.44, commits diarios, un mantenedor | **Ejecutor recomendado** |
| **OpenSandbox** (Alibaba) | Apache-2.0 | n/a | runc / gVisor / Kata / Firecracker, SDK Python | v0.2.3, 15k estrellas | Alternativa "plataforma de sandboxes" |
| **microsandbox** | Apache-2.0 | n/a | microVM libkrun, requiere KVM | v0.6.18, beta | Alternativa microVM; tiene ejemplo oficial LibreOffice a PDF offline |
| OpenHands | MIT | Sí (LiteLLM) | Docker | v1.17 | Funciona, pesado |
| OpenCode / Goose | MIT / Apache-2.0 | Sí | **No** nativo (envolver con Docker o sandbox-runtime) | activos | Posibles, con trabajo extra |
| Claude Code / Agent SDK / Skills API | Propietaria (SDK MIT) | **No** (solo Anthropic, Bedrock, Vertex, Foundry) | Sí | activo | **Descartado** por proveedor y licencia de skills |
| Aider | Apache-2.0 | Sí | No | último release ago-2025 | Descartado |
| E2B self-host | Apache-2.0 | n/a | Firecracker | Solo GCP/AWS, Azure y Linux genérico "pendientes" | Descartado |
| Daytona | AGPL-3.0 | n/a | Docker/Kata | Repo público congelado jun-2026 | Descartado |
| Pyodide (mcp-run-python, langchain-sandbox) | MIT | n/a | WASM | Archivados ene-2026 con aviso de seguridad | Descartado |
| Piston, Jupyter Gateway, dify-sandbox | MIT / BSD / Apache | n/a | débil o sin salida de archivos | varios | Descartados |

### MCP: qué existe y qué no

| Servidor MCP | Licencia | Formatos | Abre plantilla | Estado | Uso posible |
|---|---|---|---|---|---|
| GongRzhe Office-Word / Office-PowerPoint | MIT | docx / pptx | Sí, sin clonar slide | **Archivados** dic-2025 | Referencia; vendorizar funciones sueltas |
| haris-musa/excel-mcp-server | MIT | xlsx | Sí | 4,2k estrellas, abr-2026 | Editar xlsx existentes |
| vivekVells/mcp-pandoc | MIT | md a docx/pptx | `reference_doc` (estilos, no placeholders) | ago-2026 | Informes libres con marca |
| ForLegalAI/mcp-ms-office-documents | MIT | docx/pptx/xlsx | Placeholders `{{ }}`, URLs firmadas, MinIO | 38 estrellas, sep-2026 | Referencia de diseño |
| jongalloway/pptx-tools | MIT (.NET) | pptx | **Duplica slides y reemplaza** | 9 estrellas, joven | Modelo a imitar |
| carboneio/carbone-mcp | Apache-2.0 | todos | Motor de plantillas real | Requiere Carbone Cloud u on-prem pago | Solo con licencia |
| ONLYOFFICE docspace-mcp, Microsoft 365 MCP | varias | — | — | No generan / cloud | Descartados |

Hallazgo clave sobre AnythingLLM: convierte el resultado de cualquier tool MCP a un string JSON para el modelo y **no genera tarjeta de descarga**. Solo su skill nativa `create-files` entrega archivos. Para que un MCP externo entregue un archivo hace falta un endpoint de descarga propio en el gateway (el MCP devuelve la URL firmada), o un parche de pocas líneas en `returnMCPResult`, o una custom skill que reuse `saveGeneratedFile`.

---

## Arquitectura recomendada (híbrida, con router)

```
Usuario ──chat──▶ Eleia Hub / AnythingLLM (@agent, Azure OpenAI)
                          │
                    router por pedido
          ┌───────────────┴─────────────────┐
          ▼                                 ▼
  MODO PLANTILLA (default, 80-90 %)   MODO LIBRE (opt-in por rol/presupuesto)
  LLM → JSON validado por schema      LLM → código Python/Node + skills propias
  docxtpl / pptx-automizer / openpyxl smolagents CodeAgent (o `codex exec`)
          │                                 │
          └──────────┬──────────────────────┘
                     ▼
   "DocRunner": contenedor efímero sin red (llm-sandbox + imagen propia:
   python-pptx, python-docx, openpyxl, docxtpl, Node + pptxgenjs + docx,
   LibreOffice headless, fuentes del cliente, poppler; runtime gVisor si hay)
   plantilla en /in (solo lectura) → archivo en /out → validación OOXML + render
                     ▼
   Gateway Eleia: GET /files/<uuid>?sig=…  (auth, ownership, expiración)
   → el agente muestra el link; opcional: exposición como MCP propio "eleia-docgen"
     con 2 a 4 tools (list_templates, render_document, markdown_to_document, convert_to_pdf)
```

Reglas que salen del relevamiento:

- **El LLM produce datos, no layout**, en el modo plantilla. Un solo tool call a Azure por documento. Reproducible y auditable.
- **Skills propias bajo el estándar Agent Skills** (Apache-2.0), nunca las de Anthropic ni copias derivadas como `tfriedel/claude-office-skills` (sin licencia). Las skills `$slides`, `$doc`, `$spreadsheet` de OpenAI sirven de referencia de diseño, verificando la licencia por skill en `openai/plugins`.
- **Ambos modos comparten los scripts deterministas** (duplicar slide, reemplazar placeholder, validar, recalcular fórmulas, render a PDF). En modo libre el modelo los invoca en vez de reinventarlos.
- **Guardrails del modo libre**: red apagada, sin secretos, filesystem de solo lectura salvo `/out`, límites de CPU/RAM/tiempo, tope de turnos y tokens (~150k), filtro AST de imports, validación del MIME real y round-trip con python-pptx/docx para descartar macros y OLE, log del script ejecutado, contenido del RAG nunca tratado como instrucción.
- **Presupuesto por rol (spec 047)**: el modo libre cuesta 3 a 10 veces más; se activa por rol y descuenta del mismo presupuesto.
- **Entrega siempre por URL firmada del gateway**, nunca base64 en el resultado de una tool (entraría al contexto del modelo).

### Mediciones de costo encontradas

| Fuente | Qué mide | Resultado |
|---|---|---|
| Paper "Talk to Your Slides" (arXiv 2505.11604, 2025) | Por instrucción sobre PPTX, Gemini 2.5 Flash | Generación directa de código: 1,2k tokens entrada, 1,5k salida, 0,001 US$; agente por UI: 97k entrada, 0,016 US$. Éxito 96,8 % vs 74,4 % |
| Calculadora Deck Burn y blog auxi.ai | Deck de 15 slides con Claude Code + skills, ciclos de edición | ~244k tokens por deck (~1,6 US$ con Sonnet), 5 a 10 US$ con Opus |
| Extrapolación propia | Documento completo | Modo libre: 3 a 8k tokens de salida, 15 a 60 s, 0,03 a 0,10 US$. Modo plantilla: 0,8 a 2,5k tokens, 5 a 15 s, 0,01 a 0,03 US$ |

---

## Implicancias para la spec 045 (actualiza lo dicho el 10-sep en el informe anterior)

- La recomendación principal (docxtpl + pptx-automizer + openpyxl + Gotenberg) **se mantiene** como camino por defecto.
- Se **agrega** un segundo camino, "modo libre", basado en smolagents CodeAgent (o Codex CLI como subproceso) sobre un contenedor efímero sin red construido con `llm-sandbox`, con skills propias. Es una feature de alcance propio dentro de la spec de backend de generación de documentos, no un ajuste.
- Gotenberg puede quedar, o reemplazarse por el LibreOffice que ya vive dentro de la imagen DocRunner (un contenedor menos). Decisión de plan.
- La exposición al agente de AnythingLLM se hace con un MCP propio de pocas tools o una custom skill, más un endpoint de descarga firmada en el gateway. No con MCPs de terceros.
- Nada de esto requiere GPU ni un modelo distinto de Azure OpenAI. Sí requiere que el host del cliente permita contenedores (idealmente con gVisor o KVM para microVM; en Podman rootless quedan las restricciones de runc).

---

# Detalle y fuentes

Lo que sigue son los tres relevamientos completos, con la URL de cada dato.


## Anexo: Enfoque "agéntico" para generar documentos (skills + CLI de agentes + sandbox) — Informe A

**Fecha:** 2026-09-10 · **Contexto:** Eleia Hub (gateway IA on-prem/air-gapped, único egreso Azure OpenAI, backend Python + Node, RAG con AnythingLLM). Objetivo: que el chat genere .docx/.pptx/.xlsx/.pdf a partir de plantillas corporativas.
**Alcance:** Tarea A (Agent Skills de documentos, el estándar abierto, Skills API/code execution de Anthropic) y Tarea B (CLIs de agentes usados headless como "motor de documentos"). Cierra con tabla comparativa y veredicto.

> Todos los números de stars/fechas se tomaron de la API de GitHub el 2026-09-10 (`gh api repos/<owner>/<repo>`), salvo que se indique otra fuente.

---

### TAREA A — Agent Skills de documentos

### A.1 El repo `anthropics/skills`

**Datos del repo** (GitHub API, 2026-09-10): 175.628 stars; creado 2025-09-22; último push 2026-09-03; el campo `license` del repo es `null` porque **no hay un LICENSE en la raíz**: la licencia se declara por skill. El README dice que la mayoría de las skills son Apache-2.0 pero que las de documentos (docx, pdf, pptx, xlsx) son *"source-available, not open source"* y se publican como referencia de producción. Fuente: https://github.com/anthropics/skills (README) y https://raw.githubusercontent.com/anthropics/skills/main/README.md

**Último cambio relevante en las 4 skills de documentos:** commit del 2026-07-17 (PR #1447 "Update docx, pptx, and xlsx skills"): agrega soporte de formatos plantilla (`.dotx`, `.potx`, `.xltx`), consolida helpers de office, reemplaza pack/unpack por zip/unzip explícitos, rechaza symlinks/path-traversal al extraer, y **"Provision a LibreOffice user profile per invocation so conversions work in sandboxed environments"**. La skill `pdf` tuvo su último cambio el 2026-02-06 (#350). Fuente: `gh api repos/anthropics/skills/commits?path=skills/<skill>`.

**Licencia exacta de las 4 skills de documentos** (`skills/pptx/LICENSE.txt`, idéntica en docx/xlsx/pdf; el frontmatter de cada SKILL.md dice `license: Proprietary. LICENSE.txt has complete terms`):

> "© 2025 Anthropic, PBC. All rights reserved. LICENSE: Use of these materials … is governed by your agreement with Anthropic regarding use of Anthropic's services … ADDITIONAL RESTRICTIONS: … users may not: Extract these materials from the Services or retain copies of these materials outside the Services; Reproduce or copy these materials …; Create derivative works based on these materials; Distribute, sublicense, or transfer these materials to any third party; … Reverse engineer …"

Fuente: https://github.com/anthropics/skills/blob/main/skills/pptx/LICENSE.txt (leída vía API). Interpretación práctica: **no se pueden copiar a un producto propio, ni adaptarlas, ni usarlas fuera de los "Services" de Anthropic**. Un issue abierto desde 2026-06-03 (#1254, "Can we use the skills in any coding assistant like Github Copilot chat?") pregunta exactamente eso y **no tiene respuesta oficial de Anthropic** (solo un análisis de un tercero). Fuente: https://github.com/anthropics/skills/issues/1254

**Qué hay adentro de cada skill (leído de los SKILL.md, rama main):**

| Skill | Librerías / binarios que usa | ¿Edita plantillas existentes? | Dependencias de sistema | Scripts helper |
|---|---|---|---|---|
| **docx** | `docx` npm (docx-js) para crear; `unzip → editar word/document.xml → zip` para editar ("docx-js cannot open existing files"); `pandoc -t markdown` para leer; LibreOffice `soffice` (wrapper `scripts/office/soffice.py --headless --convert-to pdf`); `pdftoppm` (Poppler) para render | Sí: edición XML directa, `.dotx` soportado, **tracked changes** (`<w:ins>/<w:del>`, validación con `--author`), comentarios (`comment.py`), `accept_changes.py` (usa LibreOffice), `validate.py` con XSD | Node.js, Python 3, LibreOffice, Poppler, pandoc | `merge_runs.py`, `accept_changes.py`, `comment.py`, `office/validate.py`, `office/soffice.py` |
| **pptx** | `pptxgenjs` (Node) para crear desde cero; `unzip → editar ppt/slides/slideN.xml → zip` para editar/plantillas; `python-pptx` mencionado con 3 limitaciones explícitas (no duplica slides, `text_frame.text=` pierde formato, no lee SVG/EMF); `markitdown` para extraer texto; LibreOffice + `pdftoppm` para thumbnails/QA visual; Pillow, defusedxml, lxml | Sí: `.potx` "unpack and pack identically"; `scripts/add_slide.py` **duplica un slide o layout con todo el bookkeeping** (rels, content types, `<p:sldIdLst>`); `thumbnail.py` genera grilla para elegir layouts; guía de "template slots ≠ source items"; `validate.py --original template.pptx` | Node.js, Python 3, LibreOffice, Poppler. **No usa Playwright/Chromium**: el render es LibreOffice → PDF → pdftoppm | `thumbnail.py`, `add_slide.py`, `clean.py`, `office/validate.py`, `office/soffice.py` |
| **xlsx** | `openpyxl` (fórmulas/celdas), `pandas` (I/O masivo), `markitdown` (preview), LibreOffice vía `scripts/recalc.py` para recalcular fórmulas | Sí: "Editing an existing file: match its conventions exactly", escribir solo en celdas de input; `.xltx` soportado desde #1447 | Python 3, LibreOffice | `recalc.py` (obligatorio si hay fórmulas; reporta errores en JSON; evita XLOOKUP/FILTER/SORT, prefijo `_xlfn.`) |
| **pdf** | `pypdf`, `pdfplumber`, `reportlab`, `pdf2image`, `pytesseract`; CLI `qpdf`, `pdftotext`, `pdfimages` (poppler) | Sí para formularios (FORMS.md, `extract_form_structure.py`), merge/split/watermark/OCR | Python 3, poppler-utils, qpdf, tesseract (opcional) | `extract_form_structure.py` y otros |

Fuentes: https://raw.githubusercontent.com/anthropics/skills/main/skills/docx/SKILL.md · https://raw.githubusercontent.com/anthropics/skills/main/skills/pptx/SKILL.md · https://raw.githubusercontent.com/anthropics/skills/main/skills/xlsx/SKILL.md · https://raw.githubusercontent.com/anthropics/skills/main/skills/pdf/SKILL.md

**Observación clave para Eleia:** el "motor" real de estas skills es una combinación de (a) instrucciones en Markdown con *footguns* de pptxgenjs/docx-js/OOXML, (b) scripts Python deterministas (duplicar slide, validar, recalcular, renderizar), y (c) LibreOffice headless como render/convert. Nada de eso es mágico: el modelo escribe un script Node/Python por documento y lo ejecuta. Lo que está protegido por licencia es el *texto* de las instrucciones y los scripts; las librerías subyacentes son todas OSS (python-pptx MIT, python-docx MIT, docx npm MIT, openpyxl MIT, pptxgenjs MIT, LibreOffice MPL-2.0).

### A.2 El estándar abierto "Agent Skills" (agentskills.io)

- **Qué es:** un formato de carpeta con `SKILL.md` (frontmatter YAML `name`, `description` obligatorios; opcionales `license`, `compatibility`, `metadata`, `allowed-tools`) + `scripts/`, `references/`, `assets/`. Carga por *progressive disclosure*: metadata (~100 tokens) siempre; cuerpo (<5k tokens recomendado) al activarse; recursos bajo demanda. Fuente: https://agentskills.io/specification
- **Gobernanza:** "originally developed by Anthropic, released as an open standard" (anunciado 2025-12-18 según el post de ingeniería de Anthropic). Repo `agentskills/agentskills`: **Apache-2.0**, 25.199 stars, creado 2025-12-16, último push 2026-08-09. Incluye `skills-ref` (librería de referencia/validador). Fuentes: https://agentskills.io/ · https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills · GitHub API.
- **Harnesses que lo soportan (lista oficial en agentskills.io, con link a docs de cada uno):** Claude Code, Claude.ai, **ChatGPT & Codex**, **OpenCode**, **OpenHands**, **Goose**, **Gemini CLI**, **GitHub Copilot / VS Code**, **Cursor**, **Roo Code**, Cline (docs propias), Kiro, Amp, Factory, JetBrains Junie, Mistral Vibe, Letta, Hermes Agent, OpenClaw, nanobot, fast-agent, Spring AI, Databricks Genie Code, Snowflake Cortex Code, Tabnine, Qodo, Pulumi Neo, Laravel Boost, Mux, Emdash, pi, ZeroClaw, etc. Fuente: https://agentskills.io/ (sección "Where can I use Agent Skills?").
- **Rutas de descubrimiento (verificadas en docs):**
  - Codex: `.agents/skills` (repo/padres), `~/.agents/skills`, `/etc/codex/skills`, skills de sistema. Invocación explícita con `$skill` o implícita por descripción. https://learn.chatgpt.com/docs/build-skills
  - OpenCode: `.opencode/skills`, `~/.config/opencode/skills`, **`.claude/skills` y `~/.claude/skills`**, `.agents/skills`. https://opencode.ai/docs/skills/
  - Goose: `~/.agents/skills`, `.agents/skills`, plugins; compat con `.goose/skills`, `.claude/skills`. https://goose-docs.ai/docs/guides/context-engineering/using-skills/
  - OpenHands: `.agents/skills` (preferido), `~/.agents/skills`, legacy `.openhands/skills`; añade triggers por keyword/path. https://docs.openhands.dev/overview/skills
  - Gemini CLI: `~/.gemini/skills`, `.gemini/skills`, alias interoperable `.agents/skills`. https://geminicli.com/docs/cli/skills/
  - Roo Code: `.roo/skills`, `.agents/skills`. https://roocodeinc.github.io/Roo-Code/features/skills
  - Cline: `.cline/skills`, `.clinerules/skills`, **`.claude/skills`**. https://docs.cline.bot/features/skills

**¿Se pueden usar las skills con un modelo NO-Claude (Azure OpenAI GPT) en otro harness?**

- **Técnicamente, sí, sin fricción:** el formato es Markdown + scripts; todos los harnesses de arriba las leen desde `.agents/skills` o `.claude/skills` y dejan que el modelo ejecute los scripts con su tool de shell. OpenAI incluso dice que sus skills siguen "the open agent skills standard" y son compatibles con agentskills.io. Fuente: https://learn.chatgpt.com/docs/build-skills
- **Legalmente, no para las 4 skills de documentos de Anthropic:** la LICENSE.txt prohíbe extraerlas, copiarlas, derivar y distribuir (ver A.1). El issue #1254 sigue sin respuesta. Para un producto comercial on-prem (Eleia Hub) eso es un no-go: hay que **escribir skills propias** (el spec es Apache-2.0) o usar skills de terceros con licencia clara.
- **Evidencia de gente usándolas cruzadas:** el ecosistema de "PPT skills for Claude Code & Codex" (comparativas de 30+ skills) muestra que las skills comunitarias se usan indistintamente en ambos harnesses; ejemplos con licencia MIT: `siril9/presentation-skill` (PPTX editable con QA), y proyectos como BrandDocs ("learn existing Word, PowerPoint and Excel templates … built for Claude Code, Codex and compatible AI agents"). Fuentes: https://agentskillshub.top/best/ppt-presentation/ · https://2slides.com/blog/best-ppt-skills-claude-code-codex-2026 · https://github.com/siril9/presentation-skill . `tfriedel/claude-office-skills` (823 stars) es una copia "verbatim" de scripts generados por Claude previa a la publicación oficial; el propio autor remite ahora al repo de Anthropic y **no declara licencia** → tampoco es base segura. Fuente: https://github.com/tfriedel/claude-office-skills
- **OpenAI tiene su propio set de skills de documentos, gratis y "de sistema":** `$slides` (PptxGenJS + helpers de layout + validación de overflow/overlap/fuentes), `$doc`, `$spreadsheet`, `$jupyter-notebook`, `$imagegen`. Vienen dentro del binario de Codex. El catálogo `openai/skills` (26.846 stars) está **deprecado desde 2026** a favor de `openai/plugins` (6.373 stars, sin licencia declarada a nivel repo; cada skill trae su LICENSE.txt). Fuentes: https://github.com/openai/skills (README) · https://codex.danielvaughan.com/2026/05/13/codex-cli-knowledge-work-data-analysis-reports-slides-beyond-code/ · GitHub API.

### A.3 "Code execution + Skills" en la API de Claude — y sus equivalentes self-host

**Cómo funciona (SaaS de Anthropic):**
- Se pasa `skill_id` (`pptx`, `xlsx`, `docx`, `pdf` o custom subida vía `/v1/skills`) en el parámetro `container` junto con el **code execution tool**. El sandbox es un contenedor Linux de Anthropic **sin acceso a internet ni instalación de paquetes**, con librerías preinstaladas: `python-pptx, python-docx, openpyxl, xlsxwriter, pypdf, pdfplumber, reportlab, pdf2image…`. Los archivos entran por Files API (`container_upload`) y salen como `file_id` desde `$OUTPUT_DIR`. Contenedores reutilizables por ID, checkpoint a los ~5 min de inactividad, **expiran a los 30 días**. Fuentes: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview · https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool
- **Precio de la ejecución:** 1.550 horas-contenedor gratis por organización/mes; después **USD 0,05 por hora por contenedor**, mínimo 5 minutos por request; se factura aunque no se ejecute código si hay archivos adjuntos (se precargan). Gratis si el request incluye web_search/web_fetch (irrelevante para air-gap). Fuente: code-execution-tool (sección "Usage and pricing").
- **Plataformas:** Claude API, "Claude Platform on AWS" y **Microsoft Foundry solo con deployment "Hosted on Anthropic"**; **no disponible en Amazon Bedrock ni Google Cloud**. Agent Skills **no está cubierto por ZDR** (zero data retention). Fuente: ídem, sección "Compatibility" y "Data retention".
- **Claude en Microsoft Foundry ("Azure" para el cliente):** dos hosting options. *Hosted on Azure*: "Anthropic-operated service running on Azure infrastructure … prompts and completions remain within Azure", pero **no soporta Code execution, Agent Skills, Files API ni programmatic tool calling** (devuelve `400 Bad Request` por diseño). *Hosted on Anthropic*: inferencia en infraestructura de Anthropic (sale de Azure) y ahí sí hay skills/code-exec. Endpoint `https://{resource}.services.ai.azure.com/anthropic/v1/*`, auth por API key o Entra ID, facturación por Azure Marketplace. Fuente: https://platform.claude.com/docs/en/build-with-claude/claude-in-microsoft-foundry
- **Conclusión air-gap:** ninguna variante es air-gap-compatible (siempre hay inferencia en nube). La única que mantiene la misma postura de egreso que Azure OpenAI es *Foundry Hosted on Azure*, y justamente esa **no tiene Skills API ni code execution**: ahí hay que traer sandbox propio.

**Equivalente self-host: Claude Agent SDK + sandbox propio**
- El Agent SDK (Python `claude-agent-sdk-python`: **MIT**, 8.076 stars, v0.2.152 del 2026-09-02; TypeScript v0.3.267 del 2026-09-09) corre el mismo loop que Claude Code en tu proceso, carga skills de `.claude/skills`, y su uso "is governed by Anthropic's Commercial Terms of Service". Fuente: https://code.claude.com/docs/en/agent-sdk/overview · GitHub API.
- **Proveedores:** Anthropic API, Amazon Bedrock, Google Vertex/Agent Platform y **Microsoft Foundry** (`CLAUDE_CODE_USE_FOUNDRY=1`, `ANTHROPIC_FOUNDRY_RESOURCE`, API key / Entra ID / bearer). "Claude Code detects deployments hosted on Azure and automatically adapts its feature set". **No** soporta OpenAI ni Azure OpenAI. Fuentes: https://code.claude.com/docs/en/microsoft-foundry · https://platform.claude.com/docs/en/build-with-claude/claude-in-microsoft-foundry
- **Headless:** `claude -p "..." --output-format json --allowedTools "Bash,Read,Edit" --permission-mode acceptEdits --bare` (`--bare` será default para `-p`). Fuente: https://code.claude.com/docs/en/headless
- **Sandbox propio de Claude Code:** en Linux usa **bubblewrap + socat** (proxy de red con allowlist de dominios), seccomp opcional vía `@anthropic-ai/sandbox-runtime`. Ese runtime (`anthropic-experimental/sandbox-runtime`, **Apache-2.0**, 5.197 stars, v0.0.75 del 2026-09-01) es reutilizable como `srt --settings x.json <comando>` para **cualquier** proceso (Codex, OpenCode, tu propio script). Fuentes: https://code.claude.com/docs/en/sandboxing · https://github.com/anthropic-experimental/sandbox-runtime
- **Licencia de Claude Code CLI:** propietaria ("© Anthropic PBC. All rights reserved. Use is subject to Anthropic's Commercial Terms of Service"), 144.654 stars, v2.1.267 del 2026-09-09. Fuente: https://github.com/anthropics/claude-code/blob/main/LICENSE.md

---

### TAREA B — CLIs de agentes de código como "motor de documentos" headless

Criterios: licencia, ¿apunta a Azure OpenAI o endpoint OpenAI-compatible interno?, modo headless, skills/MCP, sandbox propio, último release, stars, madurez.

### B.1 OpenAI Codex CLI (`openai/codex`)
- **Licencia:** Apache-2.0. **Stars:** 123.084. **Release:** `rust-v0.154.0` (2026-09-09). Push diario.
- **Azure OpenAI:** sí, nativo y documentado por Microsoft (doc del 2026-09-03):
  ```toml
  model = "gpt-5-codex"          # nombre del deployment
  model_provider = "azure"
  [model_providers.azure]
  name = "Azure OpenAI"
  base_url = "https://YOUR_RESOURCE_NAME.openai.azure.com/openai/v1"
  env_key = "AZURE_OPENAI_API_KEY"
  wire_api = "responses"
  ```
  Requiere **Responses API v1** (`/openai/v1`, sin `api-version`); `wire_api = "responses"` es el único protocolo soportado en la referencia actual; "Entra ID support is currently not available for Codex" (solo API key). También sirve para cualquier endpoint OpenAI-compatible interno (`base_url`, `http_headers`, `query_params`). Fuentes: https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/codex · https://learn.chatgpt.com/docs/config-file/config-reference
- **Headless:** `codex exec "<prompt>" --json --sandbox workspace-write -o out.md --output-schema schema.json --ephemeral --skip-git-repo-check`; `codex exec resume`; stdin como prompt (`codex exec -`). `--full-auto` está deprecado a favor de `--sandbox`. Fuente: https://learn.chatgpt.com/docs/non-interactive-mode
- **Skills/MCP:** skills nativas (`.agents/skills`, `/etc/codex/skills`, `skills.max_context_tokens` = 2% del contexto, tope 10k); MCP soportado; skills de sistema `$slides` (PptxGenJS), `$doc`, `$spreadsheet`. Fuentes: https://learn.chatgpt.com/docs/build-skills · https://learn.chatgpt.com/docs/config-file/config-reference
- **Sandbox propio:** sí. `sandbox_mode = read-only | workspace-write | danger-full-access`; `sandbox_workspace_write.network_access` (bool, off por defecto), exclusión de `/tmp`. Mecanismo: macOS Seatbelt; **Linux/WSL2 bubblewrap con user namespaces** (la doc actual ya no menciona Landlock/seccomp; en Ubuntu 24.04+ hay que habilitar AppArmor para bwrap); Windows nativo en PowerShell. Fuente: https://learn.chatgpt.com/docs/sandboxing
- **Madurez:** alta (binario Rust único, CI oficial, GitHub Action). Riesgo: cambios frecuentes de flags/docs (los docs migraron de developers.openai.com a learn.chatgpt.com).

### B.2 OpenCode (`sst/opencode` = `anomalyco/opencode`, mismo repo)
- **Licencia:** MIT. **Stars:** 206.404. **Release:** v1.18.30 (2026-09-09).
- **Azure OpenAI:** sí (`AZURE_RESOURCE_NAME`, API key o Entra ID vía Azure CLI; el deployment debe llamarse como el modelo). Endpoint OpenAI-compatible interno: `"npm": "@ai-sdk/openai-compatible"` + `baseURL`. Catálogo de modelos vía models.dev (75+ proveedores). Fuente: https://opencode.ai/docs/providers/
- **Headless:** `opencode run "<prompt>" --format json --model provider/model --agent x --file f --auto` (auto-aprueba permisos no denegados). Fuente: https://opencode.ai/docs/cli/
- **Skills/MCP:** sí; lee `.claude/skills`, `.agents/skills`, `.opencode/skills`; permisos `allow/deny/ask` por skill. Fuente: https://opencode.ai/docs/skills/
- **Sandbox propio:** **no**. El PR #21538 (sandbox Seatbelt macOS, abril 2026) se cerró sin mergear el 2026-05-15; el issue #21733 (sandbox de filesystem para bash) está cerrado. Solución práctica: envolverlo con `srt`/bubblewrap (blog 2026-07-21: `srt --settings ~/.srt/srt-opencode.json opencode`) o correrlo en Docker. Fuentes: https://github.com/anomalyco/opencode/pull/21538 · https://blog.guillaumea.fr/post/sandboxing-opencode-ai-agents-bubblewrap-srt/
- **Madurez:** muy alta en adopción, pero sin aislamiento nativo.

### B.3 Goose (`block/goose`)
- **Licencia:** Apache-2.0. **Stars:** 54.093. **Release:** v1.50.0 (2026-09-08).
- **Azure OpenAI:** sí (`AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT_NAME`, `AZURE_OPENAI_API_KEY` o cadena de credenciales Azure/`AZURE_OPENAI_AD_TOKEN`). Fuente: https://goose-docs.ai/docs/getting-started/providers/ (y docs providers.md del repo)
- **Headless:** `goose run -t "..."` / `-i archivo` / `--recipe x.yaml --params k=v` / `--no-session` / `--output-format json`; `GOOSE_MODE=auto`, `GOOSE_MAX_TURNS`. Fuente: https://goose-docs.ai/docs/tutorials/headless-goose/
- **Skills/MCP:** Agent Skills nativas (extensión "Skills" activa por defecto) + extensiones MCP. Fuente: https://goose-docs.ai/docs/guides/context-engineering/using-skills/
- **Sandbox propio:** no documentado; la doc sugiere Docker aparte.

### B.4 Claude Code / Agent SDK
- Ver A.3. Licencia CLI propietaria; SDK Python MIT pero bajo Commercial ToS. Proveedores: Anthropic/Bedrock/Vertex/**Foundry**; **no Azure OpenAI**. Headless `claude -p`. Skills nativas. Sandbox bubblewrap+socat (+ seccomp opcional).
- Para Eleia: solo tendría sentido si el cliente acepta Claude vía Foundry "Hosted on Azure" como segundo egreso permitido. Aun así las skills de documentos oficiales **no están disponibles en Claude Code** ("The pre-built document Skills … are not available in Claude Code"). Fuente: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview

### B.5 Aider (`Aider-AI/aider`)
- **Licencia:** Apache-2.0. **Stars:** 48.882. **Último release:** v0.86.0 (**2025-08-09**); último push 2026-05-22 → **proyecto estancado** más de un año sin release.
- **Azure:** sí, vía LiteLLM (`--model azure/<deployment>`, `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION`). Fuente: https://aider.chat/docs/llms/azure.html
- **Headless:** `aider --message "..." --yes`; API Python `Coder.create()` "not officially supported". Fuente: https://aider.chat/docs/scripting.html
- **Skills/MCP:** no. **Sandbox:** no. Orientado a editar repos, no a generar artefactos. **Descartable.**

### B.6 Gemini CLI (`google-gemini/gemini-cli`)
- Apache-2.0; 106.902 stars; v0.59.0 (2026-09-08). Soporta Agent Skills (`.gemini/skills`, `.agents/skills`). **Solo modelos Google** (la doc no contempla otros proveedores). Fuente: https://geminicli.com/docs/cli/skills/ · GitHub API. **Descartable para Azure OpenAI.**

### B.7 Cline / Roo Code / Kilo
- **Cline** (`cline/cline`): Apache-2.0; 67.797 stars; ahora "SDK, IDE extension, or CLI". CLI headless: `cline --json "task"`, `cline --auto-approve true`, stdin; `CLINE_COMMAND_PERMISSIONS` con allow/deny. Skills sí (`.cline/skills`, `.claude/skills`). Sin sandbox nativo. Fuente: https://docs.cline.bot/cline-cli/overview
- **Roo Code** (`RooCodeInc/Roo-Code`): Apache-2.0; 24.304 stars; **repo archivado** (último push 2026-05-15, v3.54.0). Solo extensión VS Code, sin CLI. **Descartable.**
- **Kilo Code** (`Kilo-Org/kilocode`): MIT; 27.247 stars; v7.6.2 (2026-09-10). Tiene CLI con modo no interactivo (`--auto`), BYOK/500+ modelos incl. OpenAI-compatible. Fuente: https://kilo.ai/docs/code-with-ai/platforms/cli . Menos maduro que Codex/OpenCode para este uso.

### B.8 OpenHands (`OpenHands/OpenHands`, ex All-Hands-AI) — el más relevante como "agente con sandbox Docker"
- **Licencia:** MIT. **Stars:** 87.246. **Release:** v1.17.0 (2026-09-09).
- **LLM:** cualquier proveedor de LiteLLM; Azure con `azure/<deployment>` + `LLM_BASE_URL` + `LLM_API_VERSION`; también endpoints OpenAI-compatibles (vLLM, etc.). Fuentes: https://docs.openhands.dev/openhands/usage/llms/azure-llms · https://docs.openhands.dev/openhands/usage/llms/llms
- **Headless (V1):** `openhands --headless -t "tarea"` o `-f archivo`; "Headless mode always runs in `always-approve` mode"; `--json` emite JSONL de eventos. Fuente: https://docs.openhands.dev/openhands/usage/how-to/headless-mode
- **Sandbox:** Docker por defecto; "the sandbox container **is** the OpenHands agent-server". Imagen custom: `FROM nikolaik/python-nodejs:...` + `apt-get install libreoffice` + `pip install python-pptx docxtpl` → build con `--build-arg BASE_IMAGE` y variables `AGENT_SERVER_IMAGE_REPOSITORY/TAG`. Ideal para air-gap: se pre-construye la imagen con todo adentro. Fuentes: https://docs.openhands.dev/openhands/usage/how-to/custom-sandbox-guide · https://docs.openhands.dev/openhands/usage/runtimes/docker
- **Skills:** implementa el spec de Agent Skills (`.agents/skills`) con extensiones (triggers por keyword/path). Fuente: https://docs.openhands.dev/overview/skills
- **Riesgos observados:** bugs de config de proveedor custom en headless (issue #11632, nov-2025, cerrado sin workaround documentado); el producto está orientado a "coding agents en la nube", más pesado que un CLI. Fuente: https://github.com/OpenHands/OpenHands/issues/11632

### B.9 SWE-agent / mini-swe-agent / smolagents (librerías Python livianas)
- **SWE-agent**: MIT, 20.297 stars, último release v1.1.0 (2025-05-22) — más académico. **mini-swe-agent**: MIT, 7.333 stars, v2.4.6 (2026-07-23); ~100 líneas; cada acción es un `subprocess.run` en Local/Docker/Podman/Singularity/**Bubblewrap**/Modal; modelos vía LiteLLM (incluye Azure); uso programático `DefaultAgent(LitellmModel(...), LocalEnvironment())`. Fuente: https://mini-swe-agent.com/latest/
- **smolagents** (`huggingface/smolagents`): **Apache-2.0**, 29.275 stars, v1.26.0 (2026-05-29). `CodeAgent`: el LLM escribe Python y lo ejecuta en `LocalPythonExecutor` (intérprete AST con allowlist de imports y tope de operaciones) o en `executor_type="docker" | "e2b" | "modal" | "blaxel"`. Modelos: `LiteLLMModel`, `OpenAIServerModel`, `AzureOpenAIServerModel`. La propia doc advierte: "no local python sandbox can ever be completely secure … The only way to run LLM-generated code with truly robust security isolation is to use remote execution options like E2B or Docker". Fuente: https://huggingface.co/docs/smolagents/en/tutorials/secure_code_execution
- **Para Eleia:** smolagents + `executor_type="docker"` (imagen propia con python-pptx/docxtpl/LibreOffice) es la forma **más liviana y controlable** de reproducir "modelo escribe código → sandbox → archivo", sin depender de un CLI de terceros ni de su ciclo de releases.

### B.10 Evaluación de la arquitectura "agente headless + skills de office + sandbox" para un backend on-prem

| Dimensión | Evaluación | Evidencia |
|---|---|---|
| **Reproducibilidad / determinismo** | Baja-media. Cada documento sale de un script distinto escrito por el modelo; misma consigna → layouts distintos. Las skills mitigan con scripts deterministas (duplicar slide, validar, recalcular) y QA visual (render → imagen → el modelo mira), pero el resultado sigue siendo estocástico. Anthropic mismo argumenta que "code is deterministic" y por eso empuja lógica a scripts. | SKILL.md pptx (add_slide.py, validate.py, thumbnail.py); post de ingeniería de Anthropic |
| **Costo en tokens** | Alto. Calculadora "Deck Burn" (workflow típico Claude Code, 15 slides, 6 imágenes, 3 gráficos, 1 revisión): **~244k tokens/deck (171k input, 73k output)** → a precios Sonnet 4.6 ($3/$15 por M) ≈ **USD 1,6 por deck**; con ciclos de edición y Opus, auxi.ai reporta **USD 5–10+ por deck**. Un solo slide en OOXML son "6.000+ caracteres"; reestructurar una tabla "12.000+ input / 4.500+ output chars". Prompt caching baja 25–30%; enrutar tareas deterministas fuera del LLM baja 80–90% (auxi.ai estima 80–85% de las operaciones son deterministas). | https://deck-token-decoder.lovable.app/ · https://www.auxi.ai/blog/cut-claude-token-cost |
| **Latencia** | Minutos, no segundos: un deck de 10 slides "roughly 3 minutes total" (Felo); el flujo típico de skill incluye escribir script → ejecutar → render LibreOffice → mirar thumbnails → corregir (2–6 vueltas de tool-use). Un motor de plantillas tarda <2 s. | https://felo.ai/blog/10-best-ai-ppt-skills-claude-code-cli-2026/ |
| **Riesgos** | Ejecución de código arbitrario (obligatorio sandbox: bubblewrap/srt, Docker, o intérprete restringido); prompt injection desde el contenido RAG que termina en el script; skills maliciosas ("Treat like installing software"); LibreOffice headless colgándose (la skill pptx lo dice: "bare `soffice` hangs in this sandbox" → wrapper con perfil por invocación). Licencia de las skills de Anthropic. | docs Skills overview (Security considerations); SKILL.md pptx |
| **Plantillas corporativas** | Sí, es la fortaleza del enfoque: el modelo abre el .pptx/.potx del cliente, mira la grilla de thumbnails, duplica el layout correcto (`add_slide.py` o equivalente propio con python-pptx/lxml), reemplaza textos/imágenes por XML y valida contra el original. En docx: edita `document.xml` de un .dotx, mantiene estilos, puede dejar tracked changes. En xlsx: escribe solo celdas de input y recalcula con LibreOffice. | SKILL.md pptx/docx/xlsx |
| **Air-gap con Azure OpenAI** | Viable: Codex CLI (Rust, binario único, `base_url` a Azure v1 Responses, sandbox bubblewrap, skills locales, sin telemetría obligatoria) u OpenHands/smolagents con Docker. Todo lo necesario (LibreOffice, node, python-pptx, fuentes corporativas) se hornea en una imagen. Único egreso: el endpoint Azure. | docs Codex + MS Learn; docs OpenHands custom sandbox |

---

### Tabla comparativa (harnesses)

| Harness | Licencia | Azure OpenAI / OpenAI-compat interno | Headless | Skills (agentskills) | MCP | Sandbox propio | Último release | Stars | Apto Eleia air-gap |
|---|---|---|---|---|---|---|---|---|---|
| **Codex CLI** | Apache-2.0 | ✅ nativo (`model_providers.azure`, Responses v1; sin Entra ID) | ✅ `codex exec --json --sandbox` | ✅ (+ `$slides/$doc/$spreadsheet` de sistema) | ✅ | ✅ Seatbelt / bubblewrap / Windows | rust-v0.154.0 (2026-09-09) | 123k | **Sí (1ª opción CLI)** |
| **OpenHands** | MIT | ✅ LiteLLM `azure/` | ✅ `--headless --json` (always-approve) | ✅ | ✅ | ✅ Docker (imagen custom) | v1.17.0 (2026-09-09) | 87k | **Sí (pesado)** |
| **smolagents CodeAgent** | Apache-2.0 | ✅ `AzureOpenAIServerModel` | ✅ librería | ⚠️ manual (cargar SKILL.md como prompt) | ⚠️ vía tools | ✅ Docker/E2B/Modal o intérprete AST | v1.26.0 (2026-05-29) | 29k | **Sí (1ª opción librería)** |
| **mini-swe-agent** | MIT | ✅ LiteLLM | ✅ Python | ❌ | ❌ | ✅ Docker/Bubblewrap/Podman | v2.4.6 (2026-07-23) | 7k | Sí (muy simple) |
| **OpenCode** | MIT | ✅ Azure + openai-compatible | ✅ `opencode run --format json --auto` | ✅ (lee `.claude/skills`) | ✅ | ❌ (PR cerrado; usar srt/bwrap externo) | v1.18.30 (2026-09-09) | 206k | Sí con srt/Docker |
| **Goose** | Apache-2.0 | ✅ Azure nativo | ✅ `goose run -t` | ✅ | ✅ | ❌ | v1.50.0 (2026-09-08) | 54k | Sí con Docker |
| **Cline CLI** | Apache-2.0 | ✅ (BYOK) | ✅ `cline --json` | ✅ | ✅ | ❌ (solo allow/deny de comandos) | 2026-09-10 | 68k | Posible, menos maduro |
| **Kilo CLI** | MIT | ✅ | ✅ `--auto` | ✅ | ✅ | ❌ | v7.6.2 (2026-09-10) | 27k | Posible |
| **Claude Code / Agent SDK** | Propietaria (SDK Py MIT + ToS) | ❌ Azure OpenAI; ✅ Foundry (Claude) | ✅ `claude -p` | ✅ (doc skills oficiales NO en CC) | ✅ | ✅ bubblewrap+socat+seccomp (srt Apache-2.0) | v2.1.267 (2026-09-09) | 145k | No (modelo no permitido) |
| **Aider** | Apache-2.0 | ✅ LiteLLM | ✅ `--message --yes` | ❌ | ❌ | ❌ | v0.86.0 (2025-08-09) ⚠️ | 49k | No (estancado, sin skills) |
| **Gemini CLI** | Apache-2.0 | ❌ solo Google | ✅ | ✅ | ✅ | ⚠️ | v0.59.0 (2026-09-08) | 107k | No |
| **Roo Code** | Apache-2.0 | ✅ | ❌ (solo VS Code) | ✅ | ✅ | ❌ | archivado 2026-05-15 | 24k | No |
| **Skills API + code exec (Anthropic SaaS)** | SaaS | ❌ | API | ✅ oficiales | — | ✅ (de Anthropic, sin red) | — | — | No (cloud, no ZDR; Foundry-on-Azure no lo soporta) |

Motores deterministas de referencia (para la comparación del veredicto): **docxtpl** LGPL-2.1 (2.702 stars, push 2026-07-07); **pptx-automizer** MIT (240 stars, v0.9.2 2026-08-22); **Carbone** Community License (source-available, prohíbe ofrecerlo como DGaaS hosteado; 2.105 stars); **python-pptx** MIT (3.525 stars, **último push 2024-08-07**); **python-docx** MIT (5.713); **docx** npm MIT (5.902, v9.7.1). Fuentes: GitHub API · https://github.com/carboneio/carbone/blob/master/LICENSE.md

---

### Veredicto

### (1) ¿Es viable "skills + sandbox de código" air-gapped con Azure OpenAI? ¿Con qué harness?

**Sí, es viable**, con dos condiciones duras:

1. **No usar las skills docx/pptx/xlsx/pdf de Anthropic.** Su LICENSE.txt prohíbe extraerlas, copiarlas, derivarlas y distribuirlas fuera de los Services de Anthropic; el pedido de aclaración (#1254) lleva tres meses sin respuesta. Lo que sí es libre es el **formato** (spec Apache-2.0) y las **librerías** (python-pptx, python-docx, openpyxl, docx-js, pptxgenjs, LibreOffice). Hay que escribir skills propias de Eleia (`.agents/skills/eleia-pptx`, `eleia-docx`, `eleia-xlsx`) que empaqueten *nuestros* scripts deterministas: duplicar slide de plantilla, reemplazar placeholders, validar OOXML, recalcular, renderizar.
2. **Sandbox obligatorio y sin red**, con toda la toolchain horneada en imagen (LibreOffice + perfil por invocación, Node + pptxgenjs/docx, Python + python-pptx/python-docx/openpyxl/docxtpl, fuentes corporativas del cliente, poppler).

**Harness concreto recomendado:**
- **Opción A (CLI): OpenAI Codex CLI en modo `codex exec`.** Es el único CLI grande que combina Apache-2.0 + Azure OpenAI nativo (Responses v1) + sandbox propio en Linux (bubblewrap) + skills del estándar + salida JSON/`--output-schema` + skills de documentos propias de OpenAI (`$slides` con PptxGenJS) que podemos usar como referencia de calidad. Se invoca desde el backend Node/Python como subproceso con `--sandbox workspace-write`, `network_access=false`, `--ephemeral`, cwd = carpeta de trabajo con la plantilla del cliente. Requiere: deployment Azure con Responses API v1, auth por API key (Entra ID no soportado hoy), y que el host permita user namespaces para bwrap (o correr el CLI dentro de un contenedor Docker sin bwrap y usar `danger-full-access` confiando en el contenedor).
- **Opción B (librería, más control): smolagents `CodeAgent` con `AzureOpenAIServerModel` y `executor_type="docker"`.** Sin dependencia de un CLI externo, loop de 200 líneas que vive en nuestro backend Python, sandbox Docker con imagen propia, tools = nuestros scripts de plantillas. Es la que mejor encaja con el stack Python de Eleia y con presupuestos por rol (podemos contar tokens por paso y cortar).
- **OpenHands** funciona (MIT, Docker, LiteLLM/Azure, headless) pero es una plataforma completa de coding agents: más superficie, más peso, y con antecedentes de bugs de config custom en headless. Solo si además se quiere un "agente de desarrollo" general.
- **OpenCode/Goose** son buenos harnesses interactivos pero sin sandbox nativo; habría que envolverlos con `srt` (Apache-2.0) o Docker. No aportan nada sobre Codex para este caso.
- **Claude Code/Agent SDK y Skills API:** descartados por el requisito de proveedor (solo Anthropic/Bedrock/Vertex/Foundry) y porque incluso en Foundry "Hosted on Azure" no hay skills ni code execution.

### (2) Qué gana y qué pierde frente a un motor de plantillas determinista (docxtpl / pptx-automizer / Carbone)

| | Agéntico (LLM escribe código + skills + sandbox) | Determinista (docxtpl / pptx-automizer / Carbone / Gotenberg) |
|---|---|---|
| **Gana** | Cubre pedidos abiertos ("armame un deck de 12 slides con la plantilla X a partir de estos 3 informes"); elige layouts según contenido; puede editar documentos existentes, redlinear docx, hacer QA visual y auto-corregirse; una sola pieza cubre docx/pptx/xlsx/pdf. | Salida idéntica para la misma entrada; latencia < 2 s; costo de tokens solo para el *contenido* (JSON), no para el *layout*; sin ejecución de código arbitrario; auditable; se prueba con tests de snapshot; los diseñadores del cliente mantienen la plantilla en PowerPoint/Word con etiquetas Jinja/placeholders. |
| **Pierde** | 100–250k tokens y varios minutos por documento; no determinista (dos corridas ≠ mismo deck); riesgo de código arbitrario y de prompt injection desde el RAG; LibreOffice headless frágil; validación de OOXML necesaria (archivos "corruptos" para PowerPoint son un fallo típico documentado en la skill pptx); depende del ciclo de releases de un CLI de terceros. | No improvisa: si el pedido no encaja en una plantilla/esquema, no hay documento; necesita trabajo previo por plantilla (definir placeholders, esquemas JSON); Carbone Community tiene licencia source-available con restricción DGaaS; docxtpl es LGPL (ok como dependencia). |

### (3) Recomendación concreta de combinación

1. **Camino principal (80–90% de los pedidos): motor determinista**, en línea con lo ya sellado en las specs 045/046 (docxtpl + pptx-automizer + Gotenberg/LibreOffice para PDF). El LLM (Azure OpenAI) solo produce **JSON validado por esquema** (título, secciones, bullets, tablas, referencias RAG); el backend rellena la plantilla del cliente y renderiza. Costo ≈ 2–10k tokens, latencia de segundos, salida reproducible y auditable — coherente con la regla de presupuesto por rol.
2. **Camino secundario ("modo libre", opt-in por rol/presupuesto): agente con sandbox**, para pedidos que no encajan en plantilla o para *editar* un documento subido (redline en docx, reordenar/duplicar slides de un deck existente, completar un xlsx con fórmulas). Implementación sugerida: **smolagents CodeAgent + Docker executor** dentro del backend Python (o `codex exec` como subproceso si se prefiere no mantener el loop), con skills propias de Eleia bajo el spec Agent Skills (`.agents/skills/eleia-*`) que expongan **los mismos scripts deterministas del camino 1** (duplicar slide, reemplazar placeholder, validar, recalcular, render). Así el agente "programa" contra nuestra API estable en vez de improvisar OOXML a mano, y bajamos tokens/errores.
3. **Guardrails obligatorios del camino 2:** sandbox sin red (Docker `--network none` o bwrap/srt con allowlist vacía), límites CPU/RAM/tiempo, tope de turnos y tokens por documento (p. ej. 150k), validación OOXML y render de control antes de entregar, cuarentena del archivo generado (escaneo), registro del script ejecutado para auditoría, y prohibición de usar contenido RAG como instrucciones (system prompt + filtro).
4. **No adoptar** las skills de documentos de Anthropic ni copias derivadas (tfriedel/claude-office-skills) por licencia; usar como referencia de *diseño* la estructura pública (thumbnails → elegir layout → duplicar → reemplazar → validar) y las skills `$slides/$doc/$spreadsheet` de OpenAI (verificar LICENSE.txt de cada una en `openai/plugins` antes de reutilizar código).
5. **Vigilar:** (a) python-pptx no recibe commits desde 2024-08 (usar lxml directo para duplicar slides, como hacen ambas skills); (b) Codex exige Responses API v1 en Azure y no soporta Entra ID; (c) bubblewrap en Ubuntu 24.04+ requiere ajustar AppArmor; (d) si el cliente algún día habilita Claude en Foundry "Hosted on Azure", igual no habrá Skills API ni code execution — el sandbox sigue siendo nuestro.

---

### Fuentes (URL citadas)

1. https://github.com/anthropics/skills — README, licencias por skill (stars/fechas vía GitHub API 2026-09-10)
2. https://raw.githubusercontent.com/anthropics/skills/main/skills/pptx/SKILL.md
3. https://raw.githubusercontent.com/anthropics/skills/main/skills/docx/SKILL.md
4. https://raw.githubusercontent.com/anthropics/skills/main/skills/xlsx/SKILL.md
5. https://raw.githubusercontent.com/anthropics/skills/main/skills/pdf/SKILL.md
6. https://github.com/anthropics/skills/blob/main/skills/pptx/LICENSE.txt (texto de la licencia propietaria)
7. https://github.com/anthropics/skills/issues/1254 (licencia con otros asistentes, sin respuesta oficial)
8. https://agentskills.io/ y https://agentskills.io/specification (estándar, clientes soportados)
9. https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
10. https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview (Skills API, plataformas, ZDR, Claude Code sin doc skills)
11. https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool (sandbox sin red, librerías, precio USD 0,05/h, 1.550 h gratis, 30 días)
12. https://platform.claude.com/docs/en/build-with-claude/claude-in-microsoft-foundry (Hosted on Azure vs Anthropic; features no soportadas)
13. https://code.claude.com/docs/en/microsoft-foundry (CLAUDE_CODE_USE_FOUNDRY)
14. https://code.claude.com/docs/en/agent-sdk/overview (proveedores, ToS)
15. https://code.claude.com/docs/en/headless (`claude -p`, `--bare`)
16. https://code.claude.com/docs/en/sandboxing (bubblewrap, socat, seccomp)
17. https://github.com/anthropic-experimental/sandbox-runtime (srt, Apache-2.0)
18. https://github.com/anthropics/claude-code/blob/main/LICENSE.md
19. https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/codex (config.toml Azure, sin Entra ID; 2026-09-03)
20. https://learn.chatgpt.com/docs/config-file/config-reference (model_providers, sandbox_mode, skills.*)
21. https://learn.chatgpt.com/docs/non-interactive-mode (`codex exec`)
22. https://learn.chatgpt.com/docs/build-skills (skills Codex, `.agents/skills`, openai/skills)
23. https://learn.chatgpt.com/docs/sandboxing (Seatbelt / bubblewrap / Windows)
24. https://github.com/openai/skills (deprecado → openai/plugins) y https://github.com/openai/plugins
25. https://codex.danielvaughan.com/2026/05/13/codex-cli-knowledge-work-data-analysis-reports-slides-beyond-code/ (`$slides`, `$doc`, `$spreadsheet`)
26. https://opencode.ai/docs/providers/ · https://opencode.ai/docs/cli/ · https://opencode.ai/docs/skills/
27. https://github.com/anomalyco/opencode/pull/21538 (sandbox macOS, cerrado sin merge 2026-05-15)
28. https://blog.guillaumea.fr/post/sandboxing-opencode-ai-agents-bubblewrap-srt/ (2026-07-21)
29. https://goose-docs.ai/docs/getting-started/providers/ · https://goose-docs.ai/docs/tutorials/headless-goose/ · https://goose-docs.ai/docs/guides/context-engineering/using-skills/
30. https://aider.chat/docs/llms/azure.html · https://aider.chat/docs/scripting.html
31. https://geminicli.com/docs/cli/skills/
32. https://docs.cline.bot/cline-cli/overview · https://docs.cline.bot/features/skills
33. https://roocodeinc.github.io/Roo-Code/features/skills (repo archivado según GitHub API)
34. https://kilo.ai/docs/code-with-ai/platforms/cli
35. https://docs.openhands.dev/openhands/usage/how-to/headless-mode · https://docs.openhands.dev/openhands/usage/llms/azure-llms · https://docs.openhands.dev/openhands/usage/llms/llms · https://docs.openhands.dev/openhands/usage/how-to/custom-sandbox-guide · https://docs.openhands.dev/openhands/usage/runtimes/docker · https://docs.openhands.dev/overview/skills
36. https://github.com/OpenHands/OpenHands/issues/11632
37. https://huggingface.co/docs/smolagents/en/tutorials/secure_code_execution
38. https://mini-swe-agent.com/latest/
39. https://deck-token-decoder.lovable.app/ (≈244k tokens por deck de 15 slides)
40. https://www.auxi.ai/blog/cut-claude-token-cost (USD 5–10+/deck con Opus; caching −25–30%)
41. https://felo.ai/blog/10-best-ai-ppt-skills-claude-code-cli-2026/ (≈3 min por deck de 10 slides)
42. https://agentskillshub.top/best/ppt-presentation/ · https://2slides.com/blog/best-ppt-skills-claude-code-codex-2026 · https://github.com/siril9/presentation-skill
43. https://github.com/tfriedel/claude-office-skills
44. https://github.com/carboneio/carbone/blob/master/LICENSE.md (Carbone Community License)
45. GitHub API (`gh api repos/...`, 2026-09-10) para stars, licencia SPDX, `pushed_at` y último release de: anthropics/skills, agentskills/agentskills, openai/codex, sst/opencode, block/goose, anthropics/claude-code, Aider-AI/aider, google-gemini/gemini-cli, cline/cline, RooCodeInc/Roo-Code, Kilo-Org/kilocode, OpenHands/OpenHands, SWE-agent/SWE-agent, SWE-agent/mini-swe-agent, huggingface/smolagents, anthropic-experimental/sandbox-runtime, openai/skills, openai/plugins, anthropics/claude-agent-sdk-python, anthropics/claude-agent-sdk-typescript, elapouya/python-docx-template, singerla/pptx-automizer, carboneio/carbone, scanny/python-pptx, python-openxml/python-docx, dolanmiu/docx.

---

## Anexo: Informe B — Generación de documentos Office vía MCP para Eleia Hub

**Fecha:** 2026-09-10 · **Contexto:** Eleia Hub (gateway IA + RAG, on-prem/air-gapped, único egreso Azure OpenAI, backend Python + Node, motor RAG AnythingLLM). Objetivo: que el chat genere `.docx/.pptx/.xlsx/.pdf` a pedido, idealmente desde plantillas corporativas del cliente.

> Metodología: metadatos de repos tomados de la API de GitHub (`gh api repos/...`) el 10-sep-2026; licencias leídas del campo `license.spdx_id` o del archivo LICENSE; READMEs descargados crudos. Todo dato numérico o de fecha lleva URL.

---

### 0. TL;DR

- **Sí existen** servidores MCP open source que crean/editan docx, pptx y xlsx. Los más conocidos (GongRzhe Word/PowerPoint) están **archivados** desde fines de 2025/inicios de 2026; los vivos y con criterio de producto son pocos: **haris-musa/excel-mcp-server** (xlsx), **ForLegalAI/mcp-ms-office-documents** (docx/pptx/xlsx con plantillas y almacenamiento), **SecurityRonin/docx-mcp** y **UseJunior/safe-docx** (edición quirúrgica de docx con tracked changes), **vivekVells/mcp-pandoc** (md→docx/pptx con `reference_doc`), **carboneio/carbone-mcp** (motor de plantillas real, pero requiere Carbone Cloud o Carbone on-premise comercial).
- **La arquitectura "chat + MCP de documentos" es viable, pero MCP no resuelve el problema de fondo**: en todos los casos el MCP escribe un archivo en disco (o devuelve base64/URL) y **el host tiene que servirlo al usuario**. AnythingLLM **no** hace eso para resultados de MCP: convierte el resultado de la tool a string JSON y se lo pasa al LLM; el único camino nativo de descarga es el skill built-in `create-files` (`/agent-skills/generated-files/:filename`), que no acepta plantillas del cliente.
- **Veredicto:** MCP es una buena **capa de exposición de herramientas** (contrato estándar, stdio o streamable-HTTP, fácil de aislar en contenedor), pero para "plantillas corporativas + salida determinista + air-gapped" lo serio es **un motor de plantillas propio** (docxtpl / docxtemplater / pptx-automizer + Gotenberg o LibreOffice headless, como ya se selló en la investigación docgen del 10-sep) **expuesto opcionalmente como MCP server propio** y con un endpoint de descarga en el gateway. Los MCP de terceros "que dibujan slides desde cero" (python-pptx a golpes de 30 tool-calls) son demos: no son deterministas, gastan tokens, y con Azure OpenAI vía agente de AnythingLLM son frágiles.

---

### 1. Cómo funciona MCP en AnythingLLM (lo que condiciona todo)

| Punto | Qué encontré | Fuente |
|---|---|---|
| Registro | Archivo `plugins/anythingllm_mcp_servers.json` dentro de `STORAGE_LOCATION`; se crea al abrir "Agent Skills"; botón "Refresh" recarga sin reiniciar. | https://docs.anythingllm.com/mcp-compatibility/docker |
| Transportes | `stdio` (campo `command`), `sse` y `streamable` (campo `url`, `type: "sse"` / `"streamable"`, headers opcionales). En el código: `StdioClientTransport`, `SSEClientTransport`, `StreamableHTTPClientTransport`. | https://docs.anythingllm.com/mcp-compatibility/overview · https://github.com/Mintplex-Labs/anything-llm/blob/master/server/utils/MCP/hypervisor/index.js |
| Qué soporta | **Solo Tools.** "We do not support Resources, Prompts, or Sampling". | https://docs.anythingllm.com/mcp-compatibility/docker |
| Docker | Contenedor Ubuntu con `npx`, `uv/uvx`, `node`, `bash`; los MCP no arrancan al boot (arrancan al abrir Agent Skills o al invocar `@agent`); paquetes instalados a mano se pierden si el contenedor se recrea; para acceder a archivos usar `/app/server/storage/...`. | https://docs.anythingllm.com/mcp-compatibility/docker |
| Resultado de la tool | `returnMCPResult(result)` hace `JSON.stringify` de **todo** el objeto `callTool` y lo devuelve como string al LLM. No interpreta `content[].type === "image"`/`resource`, no genera tarjeta de descarga. Si el MCP devolviera base64, ese base64 entra al contexto del modelo. | https://github.com/Mintplex-Labs/anything-llm/blob/master/server/utils/MCP/index.js (función `returnMCPResult`) |
| Timeouts | Conexión al MCP con timeout de 30 s (`Promise.race` en hypervisor). El `callTool` no pasa timeout propio → aplica el default del SDK TS (60 s). Hay issue de usuarios con timeouts ("Timeout when call MCP server", #4090, cerrado 2025-07-02). | https://github.com/Mintplex-Labs/anything-llm/blob/master/server/utils/MCP/hypervisor/index.js · https://github.com/Mintplex-Labs/anything-llm/issues/4090 |
| Azure OpenAI + agente | Issue #4169 (jul-2025): `400 Invalid 'functions[6].name'` — Azure/OpenAI exigen nombres de tool `^[a-zA-Z0-9_.-]+$`; si el MCP expone nombres con espacios, el agente entero falla. Se cerró como "problema del MCP server". Regla práctica: elegir MCPs con nombres de tool "limpios" (los servers Python/FastMCP cumplen). | https://github.com/Mintplex-Labs/anything-llm/issues/4169 |
| Agente que no llama tools | Doc oficial: depende de la calidad del modelo; recomienda modelos cloud sin cuantizar y **desactivar tools no usadas** para reducir el prompt (relevante: GongRzhe PPTX expone 34 tools, ForLegalAI ~5). | https://docs.anythingllm.com/agent-not-using-tools |
| Issue MCP vía API | #3718: "Custom Agent Works, but MCP Tool Call Fails via AnythingLLM API" (uso por API REST, no por UI). | https://github.com/Mintplex-Labs/anything-llm/issues/3718 |

### 1.1 Cómo entrega archivos hoy AnythingLLM (skill `create-files`)

- Skill built-in "Document Generation" (v1.12.0+, hay que habilitarlo en Settings > Agent Skills). Genera "Text files, PDFs, Excel files, Docx files, PowerPoint presentations"; recomienda modelos 8B+ para PPTX. https://docs.anythingllm.com/agent/usage/document-generation-agent
- Implementación: `server/utils/agents/aibitat/plugins/create-files/{docx,pptx,xlsx,pdf,text}`; librerías Node `docx@9.6.1`, `pptxgenjs@4.0.1`, `exceljs@4.4.0`, `pdf-lib@1.17.1` (server/package.json). Genera **desde cero** a partir de Markdown + tema/márgenes; **no acepta una plantilla `.docx/.pptx` del cliente**. https://github.com/Mintplex-Labs/anything-llm/blob/master/server/package.json
- Flujo de entrega (create-docx-file.js): `Packer.toBuffer` → `createFilesLib.saveGeneratedFile()` a `storage/generated-files/{tipo}-{uuid}.{ext}` → `socket.send("fileDownloadCard", {...})` al frontend → `registerOutput(..., "DocxFileDownload")` para persistirlo en el historial. https://github.com/Mintplex-Labs/anything-llm/blob/master/server/utils/agents/aibitat/plugins/create-files/docx/create-docx-file.js
- Endpoint de descarga autenticado: `GET /agent-skills/generated-files/:filename` valida que exista un chat o scheduled-job del usuario que referencie el archivo, y responde `Content-Disposition: attachment`. https://github.com/Mintplex-Labs/anything-llm/blob/master/server/endpoints/agentFileServer.js
- **Gating**: `isToolAvailable()` devuelve true solo si `NODE_ENV=development` o `ANYTHING_LLM_RUNTIME === "docker"` (lib.js). https://github.com/Mintplex-Labs/anything-llm/blob/master/server/utils/agents/aibitat/plugins/create-files/lib.js
- Issue de memoria reciente con este skill: #6151 "Backend helper crashes … on the turn after create-pdf-file; ~830 MB leaked per agent exchange" (cerrado 2026-08-19). https://github.com/Mintplex-Labs/anything-llm/issues/6151
- Versión actual: v1.16.1 (2026-08-27). https://github.com/Mintplex-Labs/anything-llm/releases/latest

**Consecuencia para Eleia:** si un MCP externo escribe `informe.docx` en `/app/server/storage/generated-files/`, el usuario **no** ve tarjeta de descarga: el agente solo recibe un string tipo `{"content":[{"type":"text","text":"Saved to /app/server/storage/..."}]}`. Hay tres salidas:
1. **Endpoint de descarga propio en el gateway Eleia** (Python/Node) que sirva un directorio compartido `generated-files/` con auth + ownership; el MCP devuelve en su texto un link `https://hub/…/download/<uuid>` y el modelo lo repite en Markdown. Es lo que hacen ForLegalAI (S3/MinIO signed URL o carpeta local) y GlisseManTV para Open WebUI (file server en :9003).
2. **Fork/parche mínimo de `returnMCPResult`** para detectar un `content[].type === "resource"` con `uri: file://…` y emitir `fileDownloadCard` reutilizando `agentFileServer.js` (unas decenas de líneas; hay que mantener el fork).
3. **Custom Agent Skill** (JS, `plugin.json` + `handler.js`) que llame a un servicio HTTP de docgen y use el mismo `saveGeneratedFile`/`fileDownloadCard` que el skill nativo. https://docs.anythingllm.com/agent/custom/developer-guide

---

### 2. Relevamiento de servidores MCP (fichas)

Leyenda: ★ = estrellas GitHub; "push" = último push (API GitHub, 10-sep-2026); "plantilla" = abre un archivo existente y lo modifica preservando master/estilos.

### 2.1 GongRzhe/Office-Word-MCP-Server
- **Licencia** MIT · **Python** (python-docx, FastMCP; `docx2pdf` como dependencia) · ★2 105 · 66 issues abiertos · push **2025-12-31** · **ARCHIVADO** (read-only; PulseMCP/GitHub lo muestran archivado el 3-mar-2026). https://api.github.com/repos/GongRzhe/Office-Word-MCP-Server · https://github.com/GongRzhe/Office-Word-MCP-Server · https://pypi.org/project/office-word-mcp-server/ (v1.1.11, 2025-12-31)
- **Tools**: `create_document`, `copy_document`, `get_document_text/outline`, `add_heading/paragraph/table/picture/page_break`, `insert_*_near_text`, `format_text`, `search_and_replace`, `delete_paragraph`, `create_custom_style`, tablas (merge, shading, widths), notas al pie, comentarios, protección, `convert_to_pdf`. (README, sección API Reference)
- **Plantilla**: sí, de forma rudimentaria: `copy_document(source, destination)` + `search_and_replace` + inserciones relativas a texto existente. No hay bucles/condicionales ni "rellenar placeholder por nombre"; el README recomienda "use templates with standard Word styles".
- **PDF**: intenta `soffice`/`libreoffice` primero y cae a `docx2pdf` (requiere MS Word) → en Linux necesita LibreOffice. https://github.com/GongRzhe/Office-Word-MCP-Server/blob/main/word_document_server/tools/extended_document_tools.py
- **Transporte**: `MCP_TRANSPORT=stdio|sse|streamable-http` (main.py). **Entrega**: path en disco (todas las tools reciben `filename`).
- **Air-gapped**: sí (pip + opcional LibreOffice). **Madurez**: usable pero **huérfano**; el autor archivó todos sus repos (Gmail-MCP, PPT, etc.). Hay ~50 forks sin estrellas. Riesgo de mantenimiento alto.

### 2.2 GongRzhe/Office-PowerPoint-MCP-Server
- **Licencia** MIT · **Python** (python-pptx ≥0.6.21, Pillow) · ★1 851 · 27 issues · push **2025-12-31** · **ARCHIVADO**. https://api.github.com/repos/GongRzhe/Office-PowerPoint-MCP-Server · https://pypi.org/project/office-powerpoint-mcp-server/ (v2.0.7, 2025-12-31)
- **Tools (34)**: `create_presentation`, `create_presentation_from_template`, `open_presentation`, `save_presentation`, `get_template_file_info`, `add_slide` (por `layout_index` del master), `populate_placeholder`, `add_bullet_points`, `manage_text`, `manage_image` (path o base64), `add_table/shape/chart`, `update_chart_data`, `manage_slide_masters`, 25 "slide templates" internos, `auto_generate_presentation`, etc. (README, "Available Tools")
- **Plantilla**: **sí, es su punto fuerte**: `.pptx/.potx` con `PPT_TEMPLATE_PATH`, preserva tema/layouts, "Templates can contain existing slides (preserved during creation)". **No** tiene `duplicate_slide` ni `find_and_replace` global (grep del README: 0 resultados) — para clonar una slide modelo hay que hacerlo con `add_slide(layout)` + `populate_placeholder`.
- **Transporte**: stdio y `--transport http --port 8000` (streamable-http), Dockerfile incluido. **Entrega**: path en disco vía `save_presentation`. **PDF**: no.
- **Air-gapped**: sí. **Madurez**: el más completo en pptx open source, pero archivado; 34 tools hinchan el prompt del agente (ver doc "agent not using tools").

### 2.3 GongRzhe/Office-Visio-MCP-Server
- MIT · Python · ★86 · push 2025-05-14 · archivado. Visio (`.vsdx`), fuera de alcance. https://api.github.com/repos/GongRzhe/Office-Visio-MCP-Server

### 2.4 haris-musa/excel-mcp-server
- **Licencia** MIT · **Python** (openpyxl ≥3.1.5) · ★4 175 · 71 issues · push **2026-04-12** · activo · PyPI `excel-mcp-server` 0.1.8 (2026-04-12). https://api.github.com/repos/haris-musa/excel-mcp-server · https://pypi.org/project/excel-mcp-server/
- **Tools** (TOOLS.md): `create_workbook/worksheet`, `get_workbook_metadata`, `write_data_to_excel`, `read_data_from_excel`, `format_range`, `merge_cells`, `apply_formula`, `validate_formula_syntax`, `create_chart`, `create_pivot_table`, `create_table`, `copy/delete/rename_worksheet`, `copy_range`, `delete_range`, `insert_rows/columns`, etc. https://github.com/haris-musa/excel-mcp-server/blob/main/TOOLS.md
- **Plantilla**: sí (abre xlsx existente y escribe rangos/hojas; openpyxl preserva estilos pero **no** recalcula fórmulas ni preserva todo — gráficos existentes se pueden perder, limitación conocida de openpyxl).
- **Transporte**: stdio, SSE (deprecated), streamable-http (`/mcp`, puerto `FASTMCP_PORT`, default 8017). En HTTP los paths son **relativos a `EXCEL_FILES_PATH`** (rechaza absolutos y traversal) — buen diseño para contenedor. **Entrega**: path en disco.
- **Air-gapped**: sí, sin dependencias externas. **Madurez**: **el más maduro del lote** (4k★, activo, sandboxing de paths).

### 2.5 negokaz/excel-mcp-server
- **Licencia** MIT · **Go** (excelize v2.9.x; se distribuye como binario vía npm `@negokaz/excel-mcp-server`, requiere Node 20+) · ★1 022 · 32 issues · push **2025-07-19**. https://api.github.com/repos/negokaz/excel-mcp-server · https://github.com/negokaz/excel-mcp-server/blob/main/go.mod
- **Tools**: `excel_describe_sheets`, `excel_read_sheet` (paginado), `excel_write_to_sheet`, `excel_create_table`, `excel_copy_sheet`, `excel_format_range`; `excel_screen_capture` y live editing **solo Windows**.
- **Plantilla**: sí (xlsx/xlsm/xltx/xltm existentes, escribe rangos). **Transporte**: solo stdio. **Entrega**: path absoluto. Air-gapped sí. Madurez: sólido pero menos tools que haris-musa y sin push hace 14 meses.

### 2.6 vivekVells/mcp-pandoc
- **Licencia** MIT · **Python** (pypandoc; requiere binario **pandoc** instalado; PDF requiere **TeX Live**) · ★580 · 19 issues · push **2026-08-15** · PyPI 0.11.1 (2026-08-15). "Officially included in the Model Context Protocol servers project". https://api.github.com/repos/vivekVells/mcp-pandoc · https://pypi.org/project/mcp-pandoc/
- **Tool**: una sola, `convert-contents` con `contents|input_file`, `output_format`, `output_file`, **`reference_doc`** (docx/odt/pptx: "the file must match the output format"), `defaults_file`, `filters`.
- **Plantilla**: **sí, vía `reference_doc`** = la forma canónica de pandoc de heredar estilos/master de un docx/pptx corporativo. No rellena placeholders; genera el documento nuevo a partir de Markdown usando los estilos y layouts (pptx: title/section/content/two-content/comparison del reference).
- **Transporte**: stdio. **Entrega**: path (`output_file` obligatorio para docx/pptx/pdf). PDF vía LaTeX (pesado; alternativa: docx→pdf con LibreOffice/Gotenberg).
- **Air-gapped**: sí (pandoc es un binario estático; TeX Live ~4 GB si se quiere PDF). **Madurez**: chico pero prolijo y activo; determinista (mismo md + mismo reference = mismo docx). Limitación: pandoc no lee pptx sin 3.8.3+ (issue #54).

### 2.7 microsoft/markitdown-mcp
- **Licencia** MIT · Python · repo markitdown ★182 396 · push 2026-09-10 · PyPI `markitdown-mcp` 0.0.1a4 (2025-05-23). https://api.github.com/repos/microsoft/markitdown · https://pypi.org/project/markitdown-mcp/
- **Confirmado: solo lectura.** Expone una única tool `convert_to_markdown(uri)` (http/https/file/data). Transportes stdio y HTTP/SSE bind a localhost. https://github.com/microsoft/markitdown/blob/main/packages/markitdown-mcp/README.md
- Útil para el lado RAG/ingesta, no para generar.

### 2.8 ONLYOFFICE/docspace-mcp
- **Licencia** MIT · **TypeScript** · ★29 · 1 issue · push **2026-08-27**. https://api.github.com/repos/ONLYOFFICE/docspace-mcp
- Es un MCP para **la API de DocSpace** (rooms, carpetas, subir/descargar/copiar/mover archivos, permisos, "download files as text"). **No genera contenido** de documentos; necesita una instancia DocSpace (`DOCSPACE_BASE_URL` + API key) o el hosted `https://mcp.onlyoffice.com/mcp`. Transportes stdio/SSE/streamable-http. https://github.com/ONLYOFFICE/docspace-mcp
- DocSpace 3.7 (jun-2026) sí "genera DOCX, PDF forms y PPTX desde el chat del agente IA", pero **en server builds requiere la "Automation API", disponible a pedido comercial**. https://www.onlyoffice.com/blog/2026/06/onlyoffice-docspace-3-7
- No existe `ONLYOFFICE/onlyoffice-mcp` oficial (404). Hay repos comunitarios ínfimos (`s-b-repo/onlyoffice-mcp-server` ★1, `camilin7483/mcp-onlyoffice` ★0). Descartado salvo que el cliente ya tenga DocSpace Enterprise.

### 2.9 LibreOffice MCP servers
- **patrup/mcp-libre** — MIT · Python 3.12+ · LibreOffice 24.2+ · ★102 · 16 issues · push **2025-06-28** (14 meses sin actividad). Tools: crear/leer/editar/`convert_document`/`batch_convert_documents` (50+ formatos), variante como extensión de LibreOffice con HTTP en :8765. https://api.github.com/repos/patrup/mcp-libre · https://github.com/patrup/mcp-libre
- **jwingnut/mcp-libre** — MIT · ★11 · push 2025-12-12 (fork/extensión, 1 día de historia). https://api.github.com/repos/jwingnut/mcp-libre
- **krondor-corp/libre-mcp** — sin licencia declarada · ★1 · push 2026-08-31 · UNO sobre Writer/Calc, macOS/Linux. https://api.github.com/repos/krondor-corp/libre-mcp
- **chfle/word-to-pdf-mcp** — sin licencia · ★1 · push 2026-03-24 · docx→pdf con unoserver persistente en Docker (patrón correcto, proyecto de una persona). https://api.github.com/repos/chfle/word-to-pdf-mcp
- **harshithb3304/libre-office-mcp** — MIT · ★14 · push 2025-05-27. https://api.github.com/repos/harshithb3304/libre-office-mcp
- **Veredicto**: ninguno pasa de prototipo; todos requieren LibreOffice instalado (300–500 MB, fine en air-gapped). Para conversión a PDF conviene usar **unoserver/Gotenberg directo** desde el backend, sin MCP.

### 2.10 Otros servidores relevantes encontrados

| Repo | Lic. | Lenguaje / lib | ★ | push | Qué hace / plantillas | Transporte / entrega |
|---|---|---|---|---|---|---|
| **ForLegalAI/mcp-ms-office-documents** https://api.github.com/repos/ForLegalAI/mcp-ms-office-documents | MIT | Python (python-docx/pptx/openpyxl), Docker | 38 | 2026-09-09 | `create_word_document`, `create_powerpoint_presentation` (schema tipado de 14 tipos de slide, temas, charts nativos), `create_excel`, emails. **Custom templates** en `custom_templates/` (docx/pptx/xlsx), **"Reusable Word Templates": cada `.docx` con `{{placeholders}}` se vuelve una tool propia**; estilos por nombre (`<!-- style: Callout -->`). | streamable-http `:8958/mcp`, API key; `UPLOAD_STRATEGY=LOCAL|S3|GCS|AZURE|MINIO` con **signed URL** de descarga; integración LibreChat vía `/api/service/files`; health probes k8s; nota sobre clientes que no soportan `oneOf`. |
| **SecurityRonin/docx-mcp** https://api.github.com/repos/SecurityRonin/docx-mcp | MIT | Python (PyPI `docx-mcp-server`), 100 % cobertura | 48 | 2026-08-05 | Crear desde blanco, **desde `.dotx`** o desde Markdown; **tracked changes**, comentarios, footnotes, find/replace regex, `generate_change_summary`, diff de dos docx. Caso de uso "build proposals and SOWs from templates". | stdio; path en disco. |
| **UseJunior/safe-docx** https://api.github.com/repos/UseJunior/safe-docx | Apache-2.0 | TypeScript (npm `@usejunior/safe-docx`) | 41 | 2026-09-10 | Edición "quirúrgica" de docx/odt preservando estructura, salida limpia o con tracked changes, conformance explorer ECMA-376. `.dotx` hay que convertirlo a `.docx`. Está en registry.modelcontextprotocol.io (`io.github.UseJunior/safe-docx`). | stdio; path. |
| **hongkongkiwi/docx-mcp** https://api.github.com/repos/hongkongkiwi/docx-mcp | MIT | Rust | 32 | 2025-08-12 | Crear/editar docx, find&replace, PDF interno sin LibreOffice (LibreOffice opcional para calidad), `--readonly`, `--blacklist`. Sin actividad hace 13 meses. | stdio; path. |
| **jongalloway/pptx-tools** https://api.github.com/repos/jongalloway/pptx-tools | MIT | C# / OpenXML SDK, **.NET 10** | 9 | 2026-08-24 | `pptx_manage_slides` con **`AddFromLayout` (plantilla + placeholders por nombre `Title`, `Body:1`) y `Duplicate` (clona slide con overrides)**, `pptx_replace_image`, `pptx_chart_data` (actualiza datos sin tocar estilo), resources `pptx://{file}/shape-map`, prompt `replace-kpi-placeholders`. Es el único que modela bien "clonar slide modelo y reemplazar". | stdio (`dotnet`); path. |
| **Baronco/GenFilesMCP** https://api.github.com/repos/Baronco/GenFilesMCP | MIT | Python | 85 | 2026-08-18 | Para **Open WebUI**: genera pptx/xlsx/docx/md ejecutando "Python templates", **sube el archivo al endpoint de OWUI** y opcionalmente a una knowledge collection; `review_docx` con comentarios. | streamable-http o stdio (vía MCPO); entrega = upload a OWUI. |
| **GlisseManTV/MCPO-File-Generation-Tool** https://github.com/GlisseManTV/MCPO-File-Generation-Tool | MIT | Python (openpyxl, reportlab, fastapi) | 170 | 2026-08-23 | Para Open WebUI: xlsx/pdf/csv/pptx/docx/zip; plantillas default docx/pptx/xlsx. | SSE/streamable; **file server propio en :9003** con URLs de descarga y borrado post-descarga. |
| **carboneio/carbone-mcp** https://api.github.com/repos/carboneio/carbone-mcp | Apache-2.0 | TypeScript (npm `carbone-mcp`), en registry oficial `io.carbone/carbone-mcp` | 4 | 2026-08-19 | 11 tools: `render_document` (plantilla docx/pptx/xlsx/odt + JSON con tags `{d.field}`, loops, condicionales), `convert_document` (100+ combos, → PDF), `upload/list/download_template`, versionado. **Motor de plantillas real.** | stdio o `MCP_TRANSPORT=http`; Docker; salida: path temporal, `asAttachment` (bytes) o `returnLink` (URL one-time). **Requiere Carbone Cloud (API key) o Carbone on-premise (`CARBONE_BASE_URL`)** — la on-prem es producto comercial; Carbone Community Edition (repo `carboneio/carbone`, "Carbone Community License", ★2 105) no trae el server HTTP que este MCP espera. https://github.com/carboneio/carbone-mcp/blob/master/docs/API.md · https://github.com/carboneio/carbone/blob/master/LICENSE.md |
| **ykarapazar/word-mcp-live** https://api.github.com/repos/ykarapazar/word-mcp-live | MIT | Python | 208 | 2026-05-29 | 124 tools, edita Word **abierto** (COM en Windows; macOS/Linux con modo limitado). Orientado a escritorio, no a servidor. | stdio. |
| **sbroenne/mcp-server-powerpoint**, **trsdn/mcp-server-ppt**, **ykuwai/ppt-mcp** | MIT / MIT / — | C# / C# / Python | 19 / 37 / 67 | 2026-09 | Automatizan PowerPoint real vía **COM → solo Windows con Office instalado**. Descartados para servidor Linux air-gapped. https://api.github.com/repos/sbroenne/mcp-server-powerpoint · https://api.github.com/repos/trsdn/mcp-server-ppt · https://api.github.com/repos/ykuwai/ppt-mcp |
| **samos123/pptx-mcp** | Apache-2.0 | Python (python-pptx) | 35 | 2025-05-20 | Mínimo; sin actividad 16 meses. https://api.github.com/repos/samos123/pptx-mcp |
| **Bajahaw/ooxml-mcp-server** | MIT | Go | 2 | 2026-07-22 | Crear/inspeccionar/validar OOXML; 1 commit. https://api.github.com/repos/Bajahaw/ooxml-mcp-server |
| **chrisryugj/kordoc** | MIT | TypeScript | 1 812 | 2026-09-06 | Parser coreano (HWP/HWPX/PDF/Office→Markdown) con `fill_form`/`generate_document`; orientado a HWP; no es solución Office genérica. https://api.github.com/repos/chrisryugj/kordoc |
| **ranuts/document** | AGPL-3.0 | HTML/WASM | 1 930 | 2026-09-07 | Editor docx/xlsx/pptx en navegador (OnlyOffice WASM). No es MCP. https://api.github.com/repos/ranuts/document |

Búsqueda en el registry oficial (`registry.modelcontextprotocol.io/v0/servers?search=`): "pptx", "pandoc", "libreoffice" → 0 resultados; "docx" → solo `safe-docx`; "powerpoint" → `sbroenne` (Windows), `dosev-ai/mcp-office-powerpoint` (Windows-first, repo 404), `powerpointengine` (hosted OAuth); "office" → `ONLYOFFICE/docspace`, `ai.waystation/office` (SaaS). Es decir: **el registry oficial casi no tiene generadores Office self-hosted**; el ecosistema está en GitHub/Smithery/Glama y es de proyectos individuales.

### 2.11 Servidores oficiales de Microsoft (descartar, pero mencionar)
- `microsoft/mcp` (MIT, ★3 659, push 2026-09-10) es el catálogo oficial: Azure MCP, Microsoft Learn, M365 Agents Toolkit, etc. **No hay MCP oficial de Word/PowerPoint local**; lo que existe opera sobre Graph/M365 cloud. https://api.github.com/repos/microsoft/mcp
- `Softeria/ms-365-mcp-server` (MIT, ★964, push 2026-09-09): Graph API (mail, calendario, OneDrive, Excel workbooks vía Graph). Requiere tenant M365 + OAuth → **incompatible con air-gapped** (egreso solo a Azure OpenAI). https://api.github.com/repos/Softeria/ms-365-mcp-server

### 2.12 Servidores MCP de ejecución de código (que el modelo escriba python-pptx)
- **pydantic/mcp-run-python** — MIT · ★194 · **ARCHIVADO** (push 2026-01-30). NOTICE del README: "there's just no safe way to run Python within pyodide safely with reasonable latency… Python code running in pyodide can run arbitrary javascript… deno has no good way limit memory usage". Reemplazo: **pydantic/monty** (MIT, Rust, ★8 193, push 2026-09-10): intérprete Python mínimo **sin filesystem, sin red, sin env** dentro del sandbox — o sea, no puede `import pptx` ni escribir archivos; sirve para lógica, no para docgen. https://github.com/pydantic/mcp-run-python · https://api.github.com/repos/pydantic/monty
- **e2b-dev/mcp-server** — Apache-2.0 · ★394 · **ARCHIVADO** (push 2026-04-16) · sandbox **cloud** de E2B → egreso a internet, descartado. https://api.github.com/repos/e2b-dev/mcp-server
- **formulahendry/mcp-server-code-runner** — MIT · TypeScript · ★245 · push 2026-02-05 · ejecuta código en el host **sin sandbox** (Docker opcional); soporta stdio y `--transport http`. Usable solo dentro de un contenedor desechable con python-docx/pptx/openpyxl preinstalados y volumen de salida. https://api.github.com/repos/formulahendry/mcp-server-code-runner
- Referencia de cómo lo hace Anthropic: `anthropics/skills` (docx/pptx/xlsx) **no usa MCP**: el modelo escribe scripts `pptxgenjs`/`docx` (crear) o hace `unzip → editar XML → zip` (editar plantilla) con `soffice` para PDF y `validate.py` para OOXML. Licencia propietaria ("© 2025 Anthropic, PBC. All rights reserved"). https://github.com/anthropics/skills/blob/main/skills/pptx/SKILL.md · https://github.com/anthropics/skills/blob/main/skills/docx/SKILL.md
- **Lectura**: "modelo escribe código en sandbox" produce los mejores documentos ad-hoc (es lo que hacen Claude/ChatGPT), pero exige sandbox real (contenedor por ejecución con límites de CPU/mem, sin red), no es determinista, y cada corrida gasta 3–10 k tokens de código. En Eleia (Azure OpenAI con presupuesto por rol) es caro y difícil de auditar.

---

### 3. Cómo lo resuelven otros hosts (breve)

| Host | Mecanismo | Entrega del archivo | Fuente |
|---|---|---|---|
| **Open WebUI** | MCP nativo **solo streamable-HTTP** (admin-only); stdio/SSE vía proxy **MCPO** (MIT, ★4 369, push 2026-05-17) que convierte MCP en OpenAPI. | No hay contrato de "archivo de tool → descarga": los proyectos (GenFilesMCP, MCPO-File-Generation-Tool) **suben el archivo a la Files API de OWUI** o levantan un **file server aparte** y devuelven la URL. | https://docs.openwebui.com/features/extensibility/mcp/ · https://api.github.com/repos/open-webui/mcpo |
| **LibreChat** | MCP stdio (10 MB/mensaje), SSE, streamable-HTTP (recomendado). v0.8.6 (31-may-2026): artefactos DOCX/XLSX/PPTX renderizados inline/side panel, MCP tools ruteables por el Code Interpreter sandbox, límites de tamaño de respuesta MCP, "background tool calls" para tools largas. ForLegalAI se integra vía `/api/service/files` (fork). | Archivos vía Files API/artefactos; el patrón sigue siendo "MCP sube al host". | https://www.librechat.ai/docs/features/mcp · https://www.librechat.ai/changelog/v0.8.6 · https://github.com/ForLegalAI/mcp-ms-office-documents |
| **Dify** | Plugins de marketplace, no MCP: `stvlynn/doc` (md→docx, v0.0.1), `stvlynn/ppt` (md→pptx), `oy_plat/oy-gen-pptx` (acepta `pptx_demo` como plantilla, v0.0.1, security rating C, 256 MB RAM), `bowenliang123/md_exporter` (Apache-2.0, ★268, v4.0.0: pandoc + python-docx + md2pptx + typst; **plantillas docx/pptx custom**; disponible como plugin Dify, Agent Skill y CLI, **no como MCP**). | El plugin devuelve un `blob` que Dify muestra como archivo descargable. | https://marketplace.dify.ai/plugin/stvlynn/doc · https://marketplace.dify.ai/plugin/oy_plat/oy-gen-pptx · https://github.com/bowenliang123/markdown-exporter |
| **n8n** | Sin nodo nativo docx/pptx. Community node `jreyesr/n8n-nodes-docxtemplater` (MIT, ★45, push 2025-12-12): docx/pptx/xlsx + JSON context con tags `{ }` y Jexl → binario de salida; PDF si hay LibreOffice. | Binario n8n → siguiente nodo (HTTP, S3, email). | https://api.github.com/repos/jreyesr/n8n-nodes-docxtemplater |

Patrón común: **ningún host trata el archivo generado por un MCP como ciudadano de primera**; siempre hay un endpoint de archivos del host o un file server lateral. AnythingLLM es el que menos ayuda (stringify del resultado).

---

### 4. Tabla comparativa (candidatos viables para Eleia)

| Servidor | Lic. | Lang/lib | Formatos | Abre plantilla existente | Clonar slide / placeholders con nombre | PDF | Transporte | Entrega | ★ / push | Deps externas | Air-gap | Madurez |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GongRzhe Word | MIT | Py/python-docx | docx (+pdf) | Sí (copy + search/replace) | No | LibreOffice o Word | stdio/sse/streamable | path | 2 105 / 2025-12-31 **archivado** | LibreOffice opc. | Sí | Usable, huérfano |
| GongRzhe PowerPoint | MIT | Py/python-pptx | pptx | Sí (.pptx/.potx, preserva master) | Parcial (add_slide por layout + populate_placeholder; sin duplicate) | No | stdio/streamable | path | 1 851 / 2025-12-31 **archivado** | — | Sí | Usable, huérfano, 34 tools |
| haris-musa excel | MIT | Py/openpyxl | xlsx | Sí | n/a | No | stdio/sse/streamable | path (sandbox `EXCEL_FILES_PATH`) | 4 175 / 2026-04-12 | — | Sí | **Producción** |
| negokaz excel | MIT | Go/excelize | xlsx/xlsm/xltx | Sí | n/a | No | stdio | path | 1 022 / 2025-07-19 | Node 20 | Sí | Sólido, quieto |
| mcp-pandoc | MIT | Py/pandoc | md→docx/pptx/odt/pdf | **Sí (`reference_doc`)** | No (estilos, no placeholders) | TeX Live | stdio | path | 580 / 2026-08-15 | pandoc, TeX | Sí | Determinista, chico |
| ForLegalAI office-docs | MIT | Py/docx+pptx+openpyxl | docx/pptx/xlsx/eml | Sí (custom_templates + docx `{{placeholders}}` → tools) | Placeholders sí; sin clonado de slide | No | streamable-http, API key | LOCAL dir o **signed URL** (S3/MinIO/Azure) | 38 / 2026-09-09 | MinIO opc. | Sí | **Diseñado para servidor** (k8s probes, thread pool) |
| SecurityRonin docx-mcp | MIT | Py | docx | Sí (.dotx, tracked changes) | find/replace regex | No | stdio | path | 48 / 2026-08-05 | (spaCy opc.) | Sí | Buena ingeniería, chico |
| safe-docx | Apache-2.0 | TS | docx/odt | Sí (edición preservando) | find/replace | No | stdio | path | 41 / 2026-09-10 | — | Sí | Activo, orientado legal |
| pptx-tools | MIT | C#/OpenXML | pptx | Sí | **Sí (AddFromLayout, Duplicate, replace_image, chart_data)** | No | stdio | path | 9 / 2026-08-24 | .NET 10 | Sí | Joven, buen modelo |
| carbone-mcp | Apache-2.0 | TS | docx/pptx/xlsx/odt/pdf… | **Sí (motor de plantillas con loops/condiciones)** | Sí (tags) | Sí | stdio/http | path / bytes / URL one-time | 4 / 2026-08-19 | **Carbone Cloud o on-prem comercial** | Solo con on-prem pago | Producto comercial |
| patrup mcp-libre | MIT | Py/UNO | 50+ | Sí | No | Sí | stdio/http | path | 102 / 2025-06-28 | LibreOffice | Sí | Prototipo quieto |
| markitdown-mcp | MIT | Py | → md | (solo lectura) | — | — | stdio/http | texto | 182 k / 2026-09-10 | — | Sí | Producción (lectura) |
| mcp-run-python | MIT | Py/Pyodide | cualquiera | — | — | — | stdio/http | — | 194 / **archivado** | Deno | Sí | Retirado por seguridad |

---

### 5. Veredicto

### 5.1 ¿MCP es una vía seria o son demos?

**Mitad y mitad, y depende de qué se le pida al MCP.**

- Como **transporte/contrato de herramienta** MCP es serio: stdio o streamable-HTTP, JSON-schema por tool, aislable en un contenedor sin red, y AnythingLLM lo consume de fábrica. Que Eleia exponga su propio docgen como MCP server es razonable y barato (FastMCP en Python, ~200 líneas).
- Como **estrategia "el agente arma el documento a golpes de tools"** (GongRzhe Word/PPT, 30–120 tools, `add_paragraph` × N) es una demo: no es determinista, la calidad depende de que el modelo ordene bien 20 llamadas, cada llamada es un round-trip a Azure OpenAI (costo + latencia + timeouts de 60 s del SDK), y con el gating de AnythingLLM (stringify del resultado, sin tarjeta de descarga) el usuario ni siquiera recibe el archivo sin trabajo extra. Además los dos servidores más populares están archivados.
- Lo que sí funciona en producción (evidencia: ForLegalAI, GenFilesMCP, Dify md_exporter, n8n docxtemplater, y el propio skill `create-files` de AnythingLLM) es **una sola tool de alto nivel** ("generá un informe con estas secciones / este JSON, con la plantilla X") que **internamente** usa un motor determinista, y un **endpoint de descarga del host**.

### 5.2 Qué usaría concretamente (y con qué límites)

1. **Núcleo (no-MCP): motor de plantillas propio en el backend Python de Eleia**, tal como se selló el 10-sep: `docxtpl` (Jinja2 sobre docx, loops/condicionales/imágenes), `pptx-automizer` (Node; clona slides de un master corporativo y reemplaza placeholders/tablas/gráficos) u `openpyxl` para xlsx, y **Gotenberg** (LibreOffice headless en contenedor) para PDF. Plantillas del cliente versionadas en el hub, con esquema JSON por plantilla.
2. **Exposición al agente: un MCP server propio "eleia-docgen"** (Python FastMCP, streamable-HTTP dentro de la red Docker de AnythingLLM, o stdio) con 2–4 tools de alto nivel: `list_templates()`, `render_document(template_id, data_json, output_format)`, `markdown_to_document(md, reference_template, format)`, `convert_to_pdf(file_id)`. Nombres de tool `^[a-zA-Z0-9_.-]+$` (issue #4169). Salida: el MCP guarda en `storage/generated-files/` y devuelve texto con `download_url` firmado del gateway Eleia (endpoint propio con auth/ownership, idéntico en espíritu a `agentFileServer.js`). Esto elimina el problema de que AnythingLLM no interprete archivos de MCP.
3. **Piezas de terceros que sí reutilizaría**, con límites:
   - **vivekVells/mcp-pandoc** como tool "markdown → docx/pptx con estilos corporativos" (`reference_doc`) para informes libres donde no hay placeholders. Límite: sin PDF (evitar TeX; convertir con Gotenberg), sin bucles/tablas complejas de plantilla.
   - **haris-musa/excel-mcp-server** si se necesita que el agente **edite** xlsx existentes (rellenar rangos en un cuadro del cliente). Límite: openpyxl no recalcula fórmulas ni preserva todo (gráficos/macros); montar con `EXCEL_FILES_PATH` acotado.
   - **ForLegalAI/mcp-ms-office-documents** como referencia de diseño (y opcionalmente como servidor): plantillas docx `{{placeholders}}` → una tool por plantilla, signed URLs vía MinIO on-prem, health probes. Límite: 38★, un mantenedor, el schema pptx "plano" por incompatibilidades de `oneOf` en algunos hosts; auditar antes de adoptar.
   - **jongalloway/pptx-tools** solo si hace falta "duplicar slide modelo y reemplazar" vía MCP genérico; límite: .NET 10 en el contenedor, 9★, joven. Preferible reproducir esa API (`AddFromLayout`/`Duplicate`) en el MCP propio con pptx-automizer.
4. **Descartaría**: GongRzhe Word/PPT (archivados; en todo caso vendorizar `word_document_server` solo para `search_and_replace`/`copy_document`), servidores COM (Windows), Carbone MCP (requiere Carbone on-prem comercial — reevaluar solo si el cliente compra licencia: es el único motor de plantillas "real" con MCP oficial), DocSpace MCP (no genera; Automation API a pedido), M365/Graph (cloud), mcp-run-python/e2b (archivados / cloud), code-runner sin sandbox.

### 5.3 Cómo combinarlo con el motor determinista (arquitectura propuesta)

```
Usuario ──chat──▶ AnythingLLM (@agent, Azure OpenAI)
                     │  tool call: eleia-docgen.render_document(template_id, data_json)
                     ▼
              eleia-docgen MCP (FastMCP, streamable-http, sin red)
                     │  valida data_json contra el schema de la plantilla
                     ▼
        motor determinista (docxtpl / pptx-automizer / openpyxl)
                     │  → generated-files/<uuid>.docx|pptx|xlsx
                     ├──▶ Gotenberg (LibreOffice) → .pdf   [opcional]
                     ▼
        Gateway Eleia: GET /files/<uuid>?sig=…  (auth + ownership + expiración)
                     ▲
      el MCP devuelve {"download_url": …, "warnings": […]} → el LLM lo muestra en Markdown
```

Reglas de diseño que salen del relevamiento:
- **El LLM produce datos, no layout**: JSON estructurado (o Markdown con secciones) validado contra el schema de la plantilla; la plantilla y el motor fijan tipografía, master, logos, numeración. Así la salida es reproducible y auditable (misma entrada → mismo archivo), y el gasto en Azure OpenAI es un solo tool-call.
- **Pocas tools, nombres limpios, timeouts cortos**: máximo 4–6 tools visibles al agente (AnythingLLM permite suprimir tools por servidor: `anythingllm.suppressedTools`), render < 30 s, PDF asíncrono si es pesado.
- **Entrega siempre por URL firmada del gateway**, nunca base64 en el resultado de la tool (con `returnMCPResult` entraría al contexto del modelo).
- **Contenedor del MCP sin egreso**, solo puertos internos hacia Gotenberg y el volumen `generated-files`; LibreOffice/pandoc empaquetados en la imagen (air-gapped OK).
- **Fase 2 opcional**: modo "documento libre" con pandoc + `reference_doc` corporativo para pedidos sin plantilla; y evaluar "modelo escribe pptxgenjs/python-pptx en sandbox" solo si aparece demanda de decks creativos, con contenedor efímero (no mcp-run-python, retirado por su autor por inseguro).

---

### 6. Fuentes (URLs citadas)

1. https://docs.anythingllm.com/mcp-compatibility/overview
2. https://docs.anythingllm.com/mcp-compatibility/docker
3. https://docs.anythingllm.com/agent/usage/document-generation-agent
4. https://docs.anythingllm.com/agent-not-using-tools
5. https://docs.anythingllm.com/agent/custom/developer-guide
6. https://github.com/Mintplex-Labs/anything-llm/blob/master/server/utils/MCP/index.js
7. https://github.com/Mintplex-Labs/anything-llm/blob/master/server/utils/MCP/hypervisor/index.js
8. https://github.com/Mintplex-Labs/anything-llm/blob/master/server/endpoints/agentFileServer.js
9. https://github.com/Mintplex-Labs/anything-llm/blob/master/server/utils/agents/aibitat/plugins/create-files/lib.js
10. https://github.com/Mintplex-Labs/anything-llm/blob/master/server/utils/agents/aibitat/plugins/create-files/docx/create-docx-file.js
11. https://github.com/Mintplex-Labs/anything-llm/blob/master/server/package.json
12. https://github.com/Mintplex-Labs/anything-llm/issues/4169
13. https://github.com/Mintplex-Labs/anything-llm/issues/4090
14. https://github.com/Mintplex-Labs/anything-llm/issues/3718
15. https://github.com/Mintplex-Labs/anything-llm/issues/6151
16. https://github.com/Mintplex-Labs/anything-llm/releases/latest
17. https://github.com/GongRzhe/Office-Word-MCP-Server · https://api.github.com/repos/GongRzhe/Office-Word-MCP-Server
18. https://github.com/GongRzhe/Office-Word-MCP-Server/blob/main/word_document_server/tools/extended_document_tools.py
19. https://pypi.org/project/office-word-mcp-server/
20. https://github.com/GongRzhe/Office-PowerPoint-MCP-Server · https://api.github.com/repos/GongRzhe/Office-PowerPoint-MCP-Server
21. https://pypi.org/project/office-powerpoint-mcp-server/
22. https://api.github.com/repos/GongRzhe/Office-Visio-MCP-Server
23. https://github.com/haris-musa/excel-mcp-server · https://github.com/haris-musa/excel-mcp-server/blob/main/TOOLS.md · https://pypi.org/project/excel-mcp-server/
24. https://github.com/negokaz/excel-mcp-server · https://github.com/negokaz/excel-mcp-server/blob/main/go.mod
25. https://github.com/vivekVells/mcp-pandoc · https://pypi.org/project/mcp-pandoc/
26. https://github.com/microsoft/markitdown/blob/main/packages/markitdown-mcp/README.md · https://pypi.org/project/markitdown-mcp/
27. https://github.com/ONLYOFFICE/docspace-mcp · https://www.onlyoffice.com/blog/2026/06/onlyoffice-docspace-3-7
28. https://github.com/patrup/mcp-libre · https://github.com/jwingnut/mcp-libre · https://github.com/krondor-corp/libre-mcp · https://github.com/chfle/word-to-pdf-mcp · https://github.com/harshithb3304/libre-office-mcp
29. https://github.com/ForLegalAI/mcp-ms-office-documents
30. https://github.com/SecurityRonin/docx-mcp
31. https://github.com/UseJunior/safe-docx
32. https://github.com/hongkongkiwi/docx-mcp
33. https://github.com/jongalloway/pptx-tools
34. https://github.com/carboneio/carbone-mcp · https://github.com/carboneio/carbone-mcp/blob/master/docs/API.md · https://github.com/carboneio/carbone/blob/master/LICENSE.md
35. https://github.com/open-xml-templating/docxtemplater/blob/master/LICENSE.md
36. https://github.com/Baronco/GenFilesMCP · https://github.com/GlisseManTV/MCPO-File-Generation-Tool
37. https://docs.openwebui.com/features/extensibility/mcp/ · https://github.com/open-webui/mcpo
38. https://www.librechat.ai/docs/features/mcp · https://www.librechat.ai/changelog/v0.8.6
39. https://marketplace.dify.ai/plugin/stvlynn/doc · https://marketplace.dify.ai/plugin/oy_plat/oy-gen-pptx · https://github.com/bowenliang123/markdown-exporter
40. https://github.com/jreyesr/n8n-nodes-docxtemplater
41. https://github.com/microsoft/mcp · https://github.com/softeria/ms-365-mcp-server
42. https://github.com/pydantic/mcp-run-python · https://github.com/pydantic/monty · https://github.com/e2b-dev/mcp-server · https://github.com/formulahendry/mcp-server-code-runner
43. https://github.com/anthropics/skills/blob/main/skills/pptx/SKILL.md · https://github.com/anthropics/skills/blob/main/skills/docx/SKILL.md
44. https://registry.modelcontextprotocol.io/v0/servers?search=docx (y `powerpoint`, `office`, `pptx`, `pandoc`, `libreoffice`)
45. https://github.com/ykarapazar/word-mcp-live · https://github.com/sbroenne/mcp-server-powerpoint · https://github.com/trsdn/mcp-server-ppt · https://github.com/ykuwai/ppt-mcp · https://github.com/samos123/pptx-mcp · https://github.com/Bajahaw/ooxml-mcp-server · https://github.com/chrisryugj/kordoc · https://github.com/ranuts/document

---

## Anexo: Enfoque C — "Code interpreter de documentos": sandboxes self-hosted y plataformas que ya generan Office

**Producto:** Eleia Hub (gateway IA + RAG, on-prem/air-gapped, único egreso Azure OpenAI; backend Python + Node; RAG actual AnythingLLM).
**Pregunta:** ¿conviene que el modelo escriba código (python-pptx / python-docx / openpyxl / docx-js / pptxgenjs) y lo ejecute en un sandbox aislado que devuelva el archivo, al estilo ChatGPT Code Interpreter / Claude Skills? ¿Qué sandbox concreto? ¿Hay alguna plataforma open source que ya lo traiga y valga la pena adoptar?
**Fecha de corte:** 2026-09-10. Todo dato de licencia/fecha/número lleva URL. Stars y fechas de release vienen de la API pública de GitHub vía shields.io (consultadas 2026-09-10); los tomá como orden de magnitud.

---

### 0. Resumen ejecutivo (para leer en 2 minutos)

1. **El enfoque "el LLM escribe código y lo ejecuta" es viable on-prem**, pero el sandbox tiene que cumplir cuatro cosas que muchos productos de moda NO cumplen: (a) correr 100 % sin internet, (b) aceptar una imagen propia con `python-pptx`/`python-docx`/`openpyxl` **y LibreOffice** (para PDF y para "reparar" archivos), (c) tener API de entrada/salida de archivos binarios (la plantilla del cliente entra, el .pptx sale), (d) aislar por request, no por usuario persistente.
2. **Descartes rápidos y por qué:**
   - **E2B self-host**: sólo GCP (prod) y AWS (beta); "General linux machine" y Azure figuran como pendientes en el README; requiere Terraform + Nomad + Packer + Postgres + DNS en Cloudflare → no es on-prem hoy. [e2b-infra-readme]
   - **Daytona**: el repo público quedó **congelado en junio 2026** ("This repository is no longer maintained… core development has moved to a private codebase"), licencia AGPL-3.0. [daytona-readme]
   - **Pyodide/WASM (mcp-run-python, langchain-sandbox, smolagents `wasm`)**: `python-pptx` técnicamente se puede instalar (es wheel puro y `lxml`/`Pillow` están compilados en Pyodide), pero **no hay LibreOffice posible, los archivos no salen del sandbox en langchain-sandbox, y ambos proyectos fueron archivados en enero 2026** con aviso de seguridad explícito. [mcp-run-python] [langchain-sandbox] [pyodide-pkgs]
   - **Piston**: devuelve sólo stdout (tope 1024 chars por defecto), 3 s de runtime por defecto, sin `pip install` arbitrario → no sirve para producir binarios. [piston]
   - **Jupyter Kernel/Enterprise Gateway**: kernel compartido, sin aislamiento por usuario (Open WebUI lo marca "legacy" y desaconseja en multiusuario). [owui-code-exec]
3. **Candidatos reales para Eleia Hub (orden de preferencia):**
   1. **Ejecutor propio en Docker/Podman con `llm-sandbox` (MIT)** como capa Python + imagen propia con LibreOffice + runtime **gVisor `runsc`** cuando el host lo permita. Es lo más liviano, 100 % air-gapped, y encaja con un backend Python. [llm-sandbox] [gvisor-install]
   2. **OpenSandbox (Alibaba, Apache-2.0)** si querés un *servicio* de sandboxes con API, SDK Python, runtimes Docker/K8s y `secure_runtime = gvisor | kata | firecracker` configurable por el admin. Más pesado, pero es "plataforma" y está muy activo. [opensandbox] [opensandbox-secure]
   3. **microsandbox (Apache-2.0)** cuando el hardware del cliente exponga KVM y quieras microVM real con `--no-net`; tiene ejemplo oficial de LibreOffice→PDF en worker offline. Todavía "beta software". [microsandbox] [microsandbox-libreoffice]
   4. **LibreChat code-interpreter (Apache-2.0)** u **Onyx code-interpreter (MIT)** si preferís copiar la arquitectura de un code interpreter ya hecho (API + workers + file server) en vez de escribirla. [librechat-ci-repo] [onyx-ci]
4. **Ninguna plataforma completa justifica reemplazar el backend de Eleia**: todas producen Office "desde cero" (sin plantilla corporativa), casi todas con licencias con cláusulas (Open WebUI branding, Dify multi-tenant, Suna pasó a Elastic 2.0, n8n Sustainable Use) y ninguna expone un "API de generar documento con plantilla X" que puedas invocar desde tu app. Sí vale la pena **robar piezas**: la imagen Docker de Open Terminal (MIT, trae LibreOffice) y el plugin `md_exporter` (Apache-2.0, plantillas DOCX/PPTX vía pandoc) como camino determinista.
5. **Costo/latencia**: la única medición comparable que encontré (paper *Talk to Your Slides*, 2025) da **~1.2k tokens in / ~1.5k out / US$0.001 por instrucción** para "generación directa de código" sobre PPTX vs. US$0.0159 para un agente por UI. Extrapolando, una deck de 10 slides por código son 3–8k tokens de salida (estimación mía) y 2–10 s de ejecución; el camino plantilla determinista (JSON → docxtpl/pptx-automizer) cuesta la mitad o menos de tokens y cero riesgo de ejecución. Recomiendo **las dos vías** con router: plantilla determinista por defecto, code interpreter como "modo libre".

---

### 1. TAREA A — Sandboxes de ejecución de código self-hosted

Criterios: licencia, air-gapped, mecanismo de aislamiento, cómo entra/sale un archivo, peso de despliegue, madurez, y si se puede meter `python-pptx`/`python-docx`/`openpyxl` + LibreOffice adentro.

### A.1 E2B (`e2b-dev/infra`)

- **Licencia:** Apache-2.0. Stars ~1.4k; último release `v2026.30` (2026-09-10) — muy activo. [shields]
- **Self-host:** el README es explícito: "Supported cloud providers: 🟢 GCP, 🟢 AWS (Beta), [ ] Azure, [ ] General linux machine". La infra se despliega con Terraform. [e2b-infra-readme]
- **Componentes:** Terraform (≥1.5 GCP / ≥1.0 AWS), Nomad, Packer, PostgreSQL, Docker/Buildx, y **Cloudflare para DNS/SSL**; en AWS exige instancias bare-metal para Firecracker. Flujo Makefile de 4 etapas (init, build artifacts, provisioning, cluster prep). [e2b-deepwiki]
- **Aislamiento:** Firecracker microVM (kernel propio por sandbox). Requiere KVM real. [beam-selfhost]
- **Archivos:** SDK con `sandbox.files.write/read` y `run_code` (cloud y self-host usan el mismo SDK). [smolagents-secure]
- **Air-gapped:** **No** hoy: depende de Cloudflare DNS, de un cloud soportado y de imágenes remotas. Bare-metal Linux "planned". [e2b-infra-readme]
- **Peso:** alto ("this is not a helm install"). [beam-selfhost]
- **Veredicto:** el mejor SDK de la categoría, pero **no es on-prem** en 2026-09. Mirarlo de nuevo cuando marquen "General linux machine".

### A.2 microsandbox (`zerocore-ai/microsandbox`, ahora "Super Rad Company")

- **Licencia:** Apache-2.0. Stars ~8.2k; release `v0.6.18` (2026-09-09); primer release público v0.1.0 el 2025-05-20. [microsandbox] [shields] [microsandbox-blog]
- **Aislamiento:** microVM con **libkrun** (KVM en Linux; Apple Silicon en macOS; WHP en Windows). "Sandbox.builder(...).create() boots a microVM as a child process. No infrastructure required." [microsandbox]
- **Imágenes:** corre imágenes OCI estándar de Docker Hub/GHCR o **cualquier registry OCI** → podés apuntar a un registry interno air-gapped. Volúmenes tipo Docker; SDKs Python/TypeScript/Rust/Go/Ruby; CLI `msb`; MCP server. [microsandbox]
- **Archivos:** `msb cp ./input.docx worker:/input/input.docx`, volúmenes, y copia desde `/out` al detener el worker. Hay ejemplo oficial **"Documents to PDF"** que instala LibreOffice + Poppler, snapshotea el toolchain y convierte con `--no-net --security restricted` y rlimits. Es exactamente el patrón que necesitamos. [microsandbox-libreoffice]
- **Air-gapped:** sí (si el registry OCI es interno). Red por sandbox con allowlist de hosts/puertos o `--no-net`.
- **Peso:** bajo-medio (un binario + KVM). **Riesgo:** "still beta software. Expect breaking changes"; la empresa se rebrandeó en marzo 2026 y abrió waitlist de cloud cerrado, o sea el foco comercial se está moviendo. [microsandbox] [microsandbox-blog]
- **¿python-pptx + LibreOffice adentro?** Sí, imagen OCI propia.

### A.3 Daytona (`daytonaio/daytona`)

- **Licencia:** AGPL-3.0 (copyleft de red). Stars ~72k; último release `v0.190.0` (junio 2026). [shields] [awesome-sandbox]
- **Estado:** el README abre con: "**This repository is no longer maintained.** As of June 2026, Daytona's core development has moved to a private codebase. This repository will receive no further updates, fixes, or releases." [daytona-readme]
- **Aislamiento:** contenedores Docker por defecto, con opción Kata/Sysbox. [beam-selfhost]
- **Veredicto:** **descartar** (fork congelado + AGPL). Ojo: Suna/Kortix dependía de Daytona y por eso migró a su propio provider.

### A.4 OpenSandbox (`alibaba/OpenSandbox`)

- **Licencia:** Apache-2.0. Open-sourced el 2026-03-01; ~15k stars; release `server/v0.2.3` (agosto 2026); 2.8k commits. [opensandbox] [byteiota-opensandbox] [shields]
- **Arquitectura:** servidor de sandboxes con **runtimes Docker y Kubernetes**, daemon `execd` dentro de cada sandbox, SDKs Python/JS/TS/Java-Kotlin/C#/Go, CLI `osb`, MCP server. "Built-in Command, Filesystem, and Code Interpreter implementations." [opensandbox]
- **Aislamiento configurable por admin** (`~/.sandbox.toml`): `secure_runtime.type = "" | "gvisor" | "kata" | "firecracker"`; tabla oficial de overhead: runc ~0 ms; gVisor ~10–50 ms/~50 MB; Kata-QEMU ~500 ms; Kata-Firecracker ~125 ms/~5 MB; Cloud Hypervisor ~200 ms. "SDK users and API callers require no code changes." [opensandbox-secure]
- **Archivos:** `sandbox.files.write_files([...])` / `sandbox.files.read_file(path)`; volúmenes Docker/K8s PVC; imagen custom por sandbox (`osb sandbox create --image python:3.12 --timeout 30m`). Egress por sandbox y Credential Vault. [opensandbox]
- **Air-gapped:** sí en principio: imágenes publicadas en Docker Hub/GHCR (firmadas con Cosign) que podés espejar en un registry interno; el servidor corre local con Docker. [opensandbox]
- **Peso:** medio (servidor + execd + Docker; K8s opcional). Python 3.10+.
- **¿python-pptx + LibreOffice adentro?** Sí, imagen propia.
- **Veredicto:** la opción "plataforma de sandboxes" más completa y activa que corre on-prem hoy. Origen Alibaba puede ser un tema de gobernanza para algún cliente; la licencia es limpia.

### A.5 Piston (`engineer-man/piston`)

- **Licencia:** MIT. ~2.8k stars; último commit julio 2026; sin releases semánticos (tag `pkgs` 2021). [piston] [shields]
- **Aislamiento:** Isolate dentro de Docker (namespaces, chroot, usuarios sin privilegio, cgroups). Límites por defecto: 3 s de CPU/wall-time, 256 procesos, **1024 chars de stdout**. [piston]
- **Archivos:** `POST /api/v2/execute` acepta `files[]` de entrada; **la salida es stdout/stderr**, no archivos. Los runtimes se instalan con `ppman`, no hay `pip install` libre. [piston]
- **Veredicto:** hecho para juzgar snippets de código (tipo LeetCode), **no para producir .pptx**. Descartar.

### A.6 Jupyter Kernel Gateway / Enterprise Gateway

- **Licencia:** BSD-3-Clause (proyecto Jupyter). Kernel Gateway: ~563 stars, último commit marzo 2024 (v3.0.1). Enterprise Gateway: ~668 stars, `v3.3.0` (junio 2026), mantenimiento mínimo. [shields] [jeg-docs]
- **Uso en plataformas:** Open WebUI lo soporta pero lo etiqueta "legacy": "all users share the same Python runtime and filesystem… Jupyter support may be deprecated in a future release." [owui-code-exec]
- **Aislamiento:** ninguno por request; un kernel = un proceso Python con el filesystem del contenedor. Se puede envolver en Docker, pero seguís compartiendo estado entre usuarios.
- **Veredicto:** útil sólo como prototipo. Para multiusuario con archivos de clientes, no.

### A.7 LibreChat code-interpreter (`LibreChat-AI/code-interpreter`)

- **Licencia:** Apache-2.0. ~119 stars (repo abierto en 2026; el README referencia `v2.0.0`). [librechat-ci-repo] [shields]
- **Arquitectura:** 5 componentes escalables vía **Redis** y **S3-compatible** (MinIO vendored en Helm): API gateway, Worker Sandbox (**NsJail**, o **libkrun microVM** con `kvmEnabled: true`, NsJail dentro del guest), File Server, Tool Call Server, Package Delivery (Python, Node y Bun "baked" en la imagen block-root). "NsJail-only mode shares the host kernel and provides meaningfully weaker isolation: it is appropriate for local development." [librechat-ci-repo]
- **Archivos:** el código escribe en `/mnt/data`; la respuesta incluye referencias de archivo descargables desde el File Server; **máximo 10 archivos generados por ejecución**. Previews de `.pptx/.potx`, CSV, PDF, imágenes en LibreChat. [librechat-ci-docs]
- **Despliegue:** Docker Compose (variantes local-dev/Mac/scalable) y Helm (`codeapi-0.3.0.tgz`). Necesita KVM para modo microVM. [librechat-ci-repo]
- **Air-gapped:** factible (Redis + MinIO locales, imágenes construidas localmente), pero hay que compilar la imagen "baked" con runtimes.
- **¿python-pptx + LibreOffice?** Python sí (se hornean paquetes en la imagen); LibreOffice habría que agregarlo a la imagen guest, no está documentado.
- **Veredicto:** el diseño más "ChatGPT-like" que hay abierto, pero pensado para LibreChat (auth JWT, sesiones); para reutilizarlo desde tu backend Python hay que hablar su API HTTP. Repo muy joven (119 stars).

### A.8 Onyx code-interpreter (`onyx-dot-app/code-interpreter`)

- **Licencia:** MIT (copyright DanswerAI, Inc.). ~28 stars; release `code-interpreter-0.4.7` (2026-09-10). [onyx-ci] [shields]
- **Aislamiento:** un contenedor Docker efímero por ejecución, con **Docker-out-of-Docker** (socket del host, recomendado) o **Docker-in-Docker**. Límites por env: `MAX_EXEC_TIMEOUT_MS`, `CPU_TIME_LIMIT_SEC`, `MEMORY_LIMIT_MB`, `MAX_FILE_SIZE_MB`. [onyx-ci]
- **Archivos:** REST simple: `POST /v1/files` (upload), `GET /v1/files/{id}` (download), `GET /v1/files`, `DELETE`. Las ejecuciones referencian `file_id`. [onyx-ci]
- **Air-gapped:** contemplado explícitamente: `PYTHON_EXECUTOR_DOCKER_IMAGE_WATCHDOG_INTERVAL_SEC … 0 disables, for air-gapped hosts that cannot pull`. [onyx-ci]
- **Paquetes:** "pre-packaged with a list of common Python libraries" (numpy, pandas, scipy, matplotlib según docs de Onyx); python-pptx/docx no documentados → habría que rebuildear la imagen `onyxdotapp/code-interpreter`. [onyx-code-exec]
- **Veredicto:** el más simple de todos los "code interpreters" con API de archivos; aislamiento sólo Docker; ideal como referencia de diseño (140 commits, MIT).

### A.9 Open Terminal (`open-webui/open-terminal`)

- **Licencia:** MIT. ~3.1k stars; release `v0.12.5` (2026-09-09). [open-terminal] [shields]
- **Qué es:** "A computer you can curl": API REST para ejecutar comandos y manejar archivos en un contenedor Docker. La imagen `latest` trae **Python, Node.js, gcc, ffmpeg, LibreOffice, LaTeX, Docker CLI y libs de data science**; `slim/alpine/openshift` no traen LibreOffice. "The default `latest` image includes LibreOffice for Word, Excel, and PowerPoint to PDF conversions." [open-terminal]
- **Archivos:** endpoints de upload/download/`GET /files/view?path=…&preview=true` (DOCX/PPTX → PDF vía LibreOffice). [open-terminal]
- **Aislamiento:** contenedor persistente, no por request. Multi-user en un contenedor = cuentas Linux separadas, "**not designed for production multi-user deployments**"; para container-per-user está **Terminals** (orquestador). Modo bare-metal = sin sandbox. [open-terminal]
- **Air-gapped:** sí (imagen GHCR espejada). `OPEN_TERMINAL_PIP_PACKAGES` para agregar `python-pptx` en arranque, o extender el Dockerfile.
- **Veredicto:** **la imagen Docker más lista para nuestro caso** (LibreOffice + Python) con licencia MIT; como *sandbox* es débil (contenedor compartido de larga vida). Usarla como base de imagen, no como ejecutor.

### A.10 dify-sandbox (`langgenius/dify-sandbox`)

- **Licencia:** Apache-2.0. ~1.3k stars; `v0.2.15` (abril 2026). Linux only, Go 1.20.6+, libseccomp. [dify-sandbox] [shields]
- **Aislamiento:** proceso con **seccomp whitelist + chroot** a `/var/sandbox/sandbox-python/`; descubre stdlib/site-packages desde `python_path`. Si un paquete C necesita syscalls no listados hay que agregarlos (`ALLOWED_SYSCALLS=…`) o recompilar; el FAQ documenta el procedimiento con `strace`. [dify-sandbox-faq]
- **Archivos:** pensado para devolver strings al nodo Code de Dify; los binarios se sacan por plugins (blob base64). No tiene API de archivos general.
- **Veredicto:** liviano y multi-tenant, pero **acoplado a Dify** y con fricción para libs nativas (lxml/Pillow/LibreOffice imposible). No como sandbox general.

### A.11 Pydantic `mcp-run-python`, LangChain `langchain-sandbox`, smolagents `wasm` (Pyodide en Deno)

- **mcp-run-python:** MIT, ~194 stars, **archivado enero 2026** con aviso: "Python code running in pyodide can run arbitrary javascript… Pyodide and Deno weren't designed to sandbox untrusted code." [mcp-run-python] [shields]
- **langchain-sandbox:** MIT, ~242 stars, **archivado 2026-01-14**: "This package is no longer maintained… We do not recommend using `langchain-sandbox` for any production use cases." Además: "Users cannot access files written by the sandbox." [langchain-sandbox]
- **¿Corre python-pptx en Pyodide?** Técnicamente **sí**: `python-pptx 1.0.2` es wheel puro (`py3-none-any`) que requiere `Pillow`, `XlsxWriter`, `lxml`, `typing-extensions` [pypi-pptx]; `lxml`, `Pillow` y `pandas` están en la lista de paquetes compilados de Pyodide [pyodide-pkgs]. Pero: (a) sin LibreOffice (no hay WASM de LO utilizable), (b) micropip necesita un índice de wheels → hay que espejarlo, (c) los mantenedores abandonaron la vía.
- **Veredicto:** descartar para producción. Sólo útil para ejecutar cálculos triviales en el navegador (Open WebUI lo usa así).

### A.12 smolagents executors (`huggingface/smolagents`)

- **Licencia:** Apache-2.0. ~29k stars; `v1.26.0` (mayo 2026). [shields]
- **Executors:** `local` (intérprete AST propio con imports en allowlist), `docker`, `e2b`, `modal`, `blaxel`, `wasm`. La doc advierte: "no local python sandbox can ever be completely secure… The only way to run LLM-generated code with truly robust security isolation is to use remote execution options like E2B or Docker." [smolagents-secure]
- **Veredicto:** framework de agente, no sandbox. Su `DockerExecutor` es un patrón válido (cap_drop ALL, pids_limit, mem_limit, `USER nobody`) que podés copiar.

### A.13 `llm-sandbox` (`vndee/llm-sandbox`)

- **Licencia:** MIT. ~1.1k stars; `v0.3.44` (agosto 2026), commits diarios. [llm-sandbox] [shields]
- **Backends:** Docker, **Podman (rootless)**, Kubernetes, Micromamba. Imagen custom (`image=` o `dockerfile=`), pool de contenedores, timeouts, políticas de seguridad (`is_safe()` es sólo advisory), `ArtifactSandboxSession` captura plots, y **MCP server**. [llm-sandbox]
- **Archivos:** `copy_to_runtime()` / `copy_from_runtime()` — exactamente "entra plantilla, sale .pptx". [llm-sandbox]
- **Air-gapped:** total (es una librería Python sobre el daemon local).
- **Aislamiento:** el del runtime que le des: runc por defecto; se puede pasar `runtime="runsc"` (gVisor) o Kata en K8s vía `RuntimeClass`.
- **Veredicto:** **la pieza que encaja natural en un backend Python** que ya tiene Docker/Podman. Riesgo: proyecto de un mantenedor (bus factor), pero el código es chico y MIT.

### A.14 AgentRun, CodeBox, otros

- **AgentRun (`tjmlabs/AgentRun`)**: Apache-2.0, ~378 stars, **último commit noviembre 2024** → estancado. Docker SDK + RestrictedPython. [shields]
- **CodeBox-AI (`tomconte/codebox-ai`)**: FastAPI + IPython kernels, MCP; alternativa self-hosted chica. `codebox-api` (shroominic) es la infra cloud de `codeinterpreter-api`. [codebox-ai]
- **OpenHands agent-server (`DockerWorkspace`)**: MIT; imagen `ghcr.io/openhands/agent-server:latest-python`; "functions with pre-pulled images without internet access"; archivos vía `workspace.working_dir`. Es un sandbox de *agente de código* completo, más pesado que lo que necesitamos, pero opción real si querés un "agente que itera hasta que el pptx abre". [openhands-docker-sdk]

### A.15 Base "casera": Docker + seccomp, gVisor, Firecracker/Kata, Docker Sandboxes

- **Docker runc + seccomp/cap_drop/no-new-privileges/pids/mem/`--network none`**: piso mínimo. Comparte kernel del host. [northflank-sandbox]
- **gVisor (`google/gvisor`)**: Apache-2.0, ~19k stars, release `20260831.0`. `runsc install` lo registra como runtime Docker; plataformas KVM (kernel ≥4.14) o systrap/ptrace sin KVM; no funciona en Docker rootless. Overhead 10–30 % en I/O. **Es el upgrade de menor fricción**: misma imagen, `--runtime=runsc`. [gvisor-install] [northflank-sandbox]
- **Firecracker (`firecracker-microvm/firecracker`)**: Apache-2.0, ~37k stars, `v1.17.0`; boot ~125 ms, <5 MiB overhead, ~50k líneas Rust; **exige KVM en bare-metal** (o nested virt). Casi nadie lo usa a pelo: se usa vía Kata Containers, E2B, microsandbox/libkrun. [gvisor-vs-fc] [shields]
- **Docker Sandboxes (marzo 2026)**: microVMs con VMM propietario de Docker, CLI `sbx`, gratis para uso individual/comercial, gobernanza paga; **macOS/Windows**; en Linux "usa un enfoque más débil basado en contenedores" (o VM KVM opcional). Orientado a *coding agents* (Claude Code, Codex), no a API de ejecución. [docker-sandboxes-docs] [docker-sandboxes-hn]

### A.16 Cloud (descartar, sólo para referencia)

Cloudflare Sandbox (contenedor en VM propia, efímero), Modal (gVisor), Vercel Sandbox (Firecracker, snapshot FS), E2B cloud, Daytona cloud, Blaxel. Todos requieren egreso a internet y datos afuera → incompatibles con el requisito "único egreso Azure OpenAI". [devdigest-sandboxes]

---

### 2. TAREA B — Plataformas open source de chat/agentes que YA generan Office

### B.1 Open WebUI

- **Licencia:** "Open WebUI License" desde **v0.6.6 (2025-04-19)**; BSD-3 hasta v0.6.5. Cláusula: "You may NOT alter, remove, or obscure any 'Open WebUI' branding… in any deployment or distribution", salvo ≤50 usuarios en 30 días, contribuidor con permiso escrito, o licencia enterprise. **No OSI**. Prohíbe co-branding. Para Eleia Hub (marca propia, clientes >50 usuarios) → licencia enterprise obligatoria. [owui-license]
- **Madurez:** ~152k stars, `v0.11.3` (agosto 2026). [shields]
- **Azure OpenAI:** sí, como conexión OpenAI-compatible; Entra ID desde 0.6.30. [owui-azure]
- **Ejecución de código:** 4 motores: **Pyodide en el navegador** (default legacy), **Jupyter** (legacy, "all users share the same Python runtime"), **Open Terminal** (recomendado) y **Terminals** (container-per-user, enterprise). [owui-code-exec]
- **Genera docx/pptx?** No hay feature nativa "exportar a Office". Con Open Terminal el modelo escribe código y usa la imagen con LibreOffice; los archivos se descargan desde el file browser. Sin plantillas. [open-terminal]
- **API externa:** Open WebUI expone API OpenAI-compatible para chat; el generador de archivos sería Open Terminal, que sí tiene API REST propia.
- **Peso:** medio (Open WebUI + Open Terminal en Docker).

### B.2 LibreChat

- **Licencia:** MIT. ~43k stars, releases frecuentes (`v0.8.6-rc1` en changelog 2026). [shields] [librechat-changelog]
- **Azure OpenAI:** nativo en `librechat.yaml` (endpoint → groups → models); agents requieren deployment con function calling. [librechat-azure]
- **Code Interpreter:** self-host con `LIBRECHAT_CODE_BASEURL` apuntando al servicio A.7; lenguajes Python, Node (JS/TS), Go, C/C++, Java, PHP, Rust, Fortran, R; upload/download de archivos, máx. 10 archivos por run; sesiones stateful experimentales (por usuario / agente+usuario / conversación) que "may reset at any time". [librechat-ci-docs]
- **Genera docx/pptx?** Sí, si el modelo escribe python-pptx/docx-js en el sandbox; hay preview inline de DOCX/XLSX/PPTX/`.potx`. Sin plantillas ni skill de documentos. [librechat-search]
- **API externa:** no hay API pública estable para invocar un agente desde otra app (es UI-first); el servicio code-interpreter sí es invocable por HTTP.
- **Peso:** medio-alto (Mongo + Meili + Redis + MinIO + workers KVM).

### B.3 Dify

- **Licencia:** Apache-2.0 **modificada**: prohíbe multi-tenant sin autorización escrita ("a workspace equals one tenant") y quitar LOGO/copyright del frontend `web/`. Backend/API sin restricción. [dify-license]
- **Madurez:** ~155k stars, `v1.17.1` (2026-09-10). [shields]
- **Azure OpenAI:** plugin oficial `langgenius/azure_openai` y Azure AI Foundry en marketplace. [dify-azure]
- **Sandbox:** dify-sandbox (A.10).
- **Plugins de documentos (verificados):**
  - **`bowenliang123/md_exporter`** ("Markdown Exporter"): Apache-2.0, ~268 stars, `v4.0.0` (agosto 2026); DOCX/PPTX/XLSX/PDF/PNG/SVG/HTML/CSV/JSON/XML/LaTeX/ipynb; **pandoc** para DOCX/PPTX y **typst** para PDF; **acepta plantilla DOCX (reference doc) y PPTX (slide masters)** "to match brand visual identity"; también funciona como Agent Skill (Claude Code, DeepAgents, AgentScope). [md-exporter] [dify-md-exporter-mkt]
  - **`stvlynn/doc`** (Markdown → DOCX con python-docx) y **`stvlynn/ppt`** (Markdown → PPTX); **`green/md_word`** (python-docx). Sin plantillas. [dify-doc-plugin] [dify-ppt-plugin]
  - Mecanismo de salida: el plugin devuelve `create_file_message(file_name, file_content=base64, mime_type)` y el chat muestra el archivo descargable. [dify-md-exporter-guide]
- **API externa:** sí, cada app/workflow de Dify expone REST (`/v1/chat-messages`, `/v1/workflows/run`) con archivos en la respuesta. Es la única plataforma de la lista con un "endpoint de generar documento" invocable limpio.
- **Peso:** alto (API + worker + web + Postgres + Redis + Weaviate/Qdrant + sandbox + plugin daemon).

### B.4 n8n

- **Licencia:** **Sustainable Use License** (no OSS): uso interno permitido; prohibido vender producto cuyo valor derive sustancialmente de n8n; crear nodos/integraciones está permitido. [n8n-license]
- **Documentos:** community node **`n8n-nodes-docxtemplater`** (jreyesr): "generates DOCX, PPTX and XLSX documents from templates" con tags Jexl; también `n8n-nodes-carbonejs`. [n8n-docxtemplater] Es plantilla determinista, no code interpreter.
- **Air-gapped:** sí (Docker). **Azure:** nodo OpenAI/Azure OpenAI.
- **Veredicto:** útil como orquestador de plantillas, no como chat; licencia a revisar si Eleia se comercializa "sobre" n8n.

### B.5 DeerFlow (`bytedance/deer-flow`)

- **Licencia:** MIT. ~82k stars; `v2.0.0` (junio 2026), 3.2k commits; "#1 GitHub Trending feb-2026". [shields] [deerflow-readme] [deerflow-review]
- **Sandbox:** tres modos: Local (host), **Docker** (contenedores aislados) y **Kubernetes** (provisioner + pods) con "AIO sandbox". Requisitos: 4 vCPU/8 GB dev, **16 vCPU/32 GB** recomendados en prod. Builds usan índice `uv` upstream → en air-gapped hay que espejar PyPI/npm (`UV_INDEX_URL`, `NPM_REGISTRY`). [deerflow-readme]
- **Documentos:** skills integradas de "report generation" (md/docx/pdf) y **`ppt-generation`**: "Creates visually rich slides by generating images for each slide and composing them into a PowerPoint file" — es decir, **PPTX de imágenes**, no editable ni con plantilla; también Marp para Markdown→slides. [deerflow-ppt-skill] [deerflow-review]
- **Azure OpenAI:** sí (LangChain, config OpenAI-compatible). [deerflow-readme]
- **API externa:** gateway LangGraph/REST (`gateway:8001/api`) — invocable pero es un harness de agente completo.
- **Veredicto:** impresionante como "super agente", pero para nuestro caso genera decks de imágenes y pesa 16 vCPU. No.

### B.6 Suna / Kortix (`kortix-ai/suna`)

- **Licencia:** el `LICENSE` actual del repo es **Elastic License 2.0** (no OSS; prohíbe ofrecerlo como servicio gestionado). Fuentes de 2025 lo citan como Apache-2.0: cambió. ~20k stars; `v0.13.12` (sept 2026). [suna-license] [shields]
- **Self-host:** "`self-host start` pulls its images from Docker Hub, so this is a self-hosted install rather than a disconnected one"; requiere Supabase; "Isolation is per provider: the Platinum provider runs microVMs, the default runs containers". [suna-readme]
- **Documentos:** promete "reports, decks" como entregables de agente (código en sandbox), sin plantillas. **Azure:** vía LiteLLM. [suna-search]
- **Veredicto:** no air-gapped por diseño, licencia Elastic → descartar.

### B.7 OpenManus, II-Agent, AgenticSeek y "alternativas a Manus"

- **OpenManus (`FoundationAgents/OpenManus`)**: MIT, ~58k stars, último release `v0.3.0` (abril 2025), commits hasta agosto 2026; soporta **Azure OpenAI** y sandbox Docker; **no trae generación de pptx**. [shields] [openmanus-search]
- **II-Agent (`Intelligent-Internet/ii-agent`)**: Apache-2.0, ~3.4k stars, `v0.4` (julio 2025); runtimes Local/Docker/E2B; produce sitios/slides HTML, no PPTX nativo. [ii-agent-search] [shields]
- **PPTAgent (`icip-cas/PPTAgent`)**: MIT, ~5k stars, `v2.0.0` (dic 2025): genera PPTX **editando una presentación de referencia** (extrae layouts y esquema de contenido, luego acciones de edición). Es lo más cercano a "usar la plantilla del cliente" en el mundo académico. [pptagent]
- **Presenton (`presenton/presenton`)**: Apache-2.0, ~10k stars; PPTX editable + PDF; plantillas en HTML/Tailwind y "AI Template Generation — Create presentation templates from existing Powerpoint documents"; Azure OpenAI, Ollama, API propia, Docker one-command. Sólo presentaciones. [presenton]
- **OpenClaw, Kova, Marp CLI**: generadores Markdown→slides, no agentes. [manus-alts]

### B.8 OpenHands (`OpenHands/OpenHands`)

- **Licencia:** MIT. ~87k stars, `v1.17.0` (2026-09-09). [shields]
- **Modo headless:** `openhands --headless -t "..."` (siempre "always-approve"); SDK Python (`DockerWorkspace`, `APIRemoteWorkspace`) y agent-server REST/WebSocket. Azure vía LiteLLM (`LLM_API_VERSION`, base URL). [openhands-headless] [openhands-docker-sdk] [openhands-azure]
- **Documentos:** no tiene skill de Office; el agente puede escribir python-pptx y verificar abriendo el archivo. Sobredimensionado para "generar un docx".

### B.9 Onyx (ex Danswer)

- **Licencia:** MIT (Community Edition) + carpeta `ee/` Enterprise. ~32k stars, `v4.7.1` (sept 2026). [onyx-search] [shields]
- **Code Interpreter:** parte del deploy por defecto desde **v3.0.0 (2026-03-09)**: "Sessions stream output as they run, accept file inputs… rich preview modals for CSV, PDF, and DOCX outputs"; v4.0.0 (2026-05-26) lo reintroduce como "sandboxed agent with file download and bash tool access". Servicio separado (A.8). [onyx-changelog]
- **Azure:** sí (LiteLLM en backend). **Plantillas:** no. **API:** Onyx tiene API de chat, pero la generación depende del modelo escribiendo código.

### B.10 AnythingLLM (referencia, ya evaluado)

- MIT, ~66k stars, `v1.16.1` (agosto 2026). "Document Generation" agent (v1.12.0+): "Text files, PDFs, Excel files, Docx files, PowerPoint presentations", sin plantillas; recomienda modelos ≥8B para pptx. [anythingllm-docgen] [shields]

### B.11 Referencia de diseño: Anthropic Skills `pptx`/`docx`

Las skills oficiales de Anthropic generan PPTX con **PptxGenJS** (Node) o flujo **html2pptx** (HTML por slide → pptx), y editan presentaciones existentes **desempaquetando el OOXML** (unzip → editar XML → rezip). Esto es lo que hace Claude cuando le pedís "usá esta plantilla": no python-pptx sobre `.potx`, sino manipulación OOXML guiada. Es el patrón que un "code interpreter de documentos" propio debería imitar. [anthropic-pptx-skill]

---

### 3. Tablas comparativas

### 3.1 Sandboxes

| Sandbox | Licencia | Air-gapped | Aislamiento | Archivos in/out | Imagen propia (pptx/docx/LibreOffice) | Peso | Madurez (stars / último release) | Apto Eleia |
|---|---|---|---|---|---|---|---|---|
| E2B infra | Apache-2.0 | **No** (GCP/AWS, Cloudflare DNS) | Firecracker microVM | SDK files | Sí (templates E2B) | Muy alto (Terraform+Nomad+Packer) | 1.4k / v2026.30 (2026-09) | No hoy |
| microsandbox | Apache-2.0 | Sí (registry OCI interno) | libkrun microVM (KVM) | `msb cp`, volúmenes | Sí, OCI; ejemplo LibreOffice oficial | Bajo-medio | 8.2k / v0.6.18 (2026-09), beta | **Sí (si hay KVM)** |
| Daytona OSS | AGPL-3.0 | Sí | Docker (Kata/Sysbox opc.) | SDK | Sí | Medio | 72k / v0.190.0, **congelado jun-2026** | No |
| OpenSandbox | Apache-2.0 | Sí (imágenes espejadas) | runc / gVisor / Kata / Firecracker (config admin) | `files.write_files/read_file`, volúmenes | Sí, `--image` | Medio (server + execd; K8s opc.) | 15k / v0.2.3 (2026-08) | **Sí** |
| Piston | MIT | Sí | Isolate en Docker | files in; **sólo stdout** | No (ppman) | Bajo | 2.8k / sin releases | No |
| Jupyter KG/EG | BSD-3 | Sí | Ninguno por request | FS del kernel | Sí | Bajo | 563 / 668; EG v3.3.0 (2026-06) | No (multiusuario) |
| LibreChat code-interpreter | Apache-2.0 | Factible (Redis+MinIO) | NsJail o libkrun microVM + NsJail | `/mnt/data` → file server S3; máx 10 archivos | Python/Node/Bun horneados; LO no doc. | Alto (5 servicios) | 119 / v2.0.0 | Como referencia |
| Onyx code-interpreter | MIT | Sí (watchdog=0 documentado) | Docker efímero (DooD/DinD) | `POST/GET /v1/files` | Rebuild imagen | Bajo | 28 / 0.4.7 (2026-09) | Como referencia |
| Open Terminal | MIT | Sí | Contenedor persistente (multi-user no prod) | upload/download, `/files/view?preview` | **Ya trae LibreOffice + Python** | Bajo | 3.1k / v0.12.5 (2026-09) | Como imagen base |
| dify-sandbox | Apache-2.0 | Sí | seccomp + chroot | strings (blob vía plugin) | Fricción syscalls; sin LO | Bajo | 1.3k / v0.2.15 (2026-04) | No |
| mcp-run-python / langchain-sandbox / smolagents wasm | MIT | Parcial (índice wheels) | Pyodide en Deno (no diseñado para untrusted) | No salen archivos | Sin LibreOffice | Bajo | archivados ene-2026 | No |
| llm-sandbox | MIT | Sí | Docker/Podman/K8s (runtime a elección) | `copy_to_runtime` / `copy_from_runtime` | Sí (`image`/`dockerfile`) | Muy bajo (lib Python) | 1.1k / v0.3.44 (2026-08) | **Sí (capa Python)** |
| gVisor runsc | Apache-2.0 | Sí | Kernel user-space (KVM o systrap) | vía Docker | Misma imagen | Bajo (`runsc install`) | 19k / 2026-08-31 | **Sí (hardening)** |
| Firecracker/Kata | Apache-2.0 | Sí | microVM (KVM bare-metal) | vía Kata/containerd | Sí | Alto a pelo; medio vía Kata | 37k / v1.17.0 | Vía OpenSandbox/Kata |
| Docker Sandboxes | Propietario (CLI gratis) | Sí | microVM en macOS/Win; contenedor en Linux | CLI | Kits | Bajo | Lanzado mar-2026 | No (dev tool) |
| Cloudflare / Modal / Vercel / E2B cloud | SaaS | **No** | VM/gVisor/Firecracker | SDK | Sí | — | — | No |

### 3.2 Plataformas

| Plataforma | Licencia exacta | Air-gapped | Azure OpenAI | Formatos que genera y con qué | ¿Plantilla? | API para invocar desde app externa | Peso | Madurez |
|---|---|---|---|---|---|---|---|---|
| Open WebUI | Open WebUI License (branding; ≤50 users exento) | Sí | Sí (OpenAI-compat, Entra ID) | Lo que el modelo programe en Open Terminal (LibreOffice en imagen) | No | Chat OpenAI-compat; Open Terminal REST | Medio | 152k / v0.11.3 |
| LibreChat | MIT | Sí (con esfuerzo) | Sí nativo | Cualquiera vía code interpreter (Python/Node…); previews docx/xlsx/pptx | No | Sólo el servicio code-interpreter | Medio-alto | 43k / activo |
| Dify | Apache-2.0 modificada (no multi-tenant, no quitar logo) | Sí | Sí (plugin oficial) | DOCX/PPTX/XLSX/PDF vía `md_exporter` (pandoc+typst), `stvlynn/doc`, `ppt` (python-docx/pptx) | **Sí** (md_exporter: reference DOCX y PPTX slide master) | **Sí** (REST de app/workflow, archivos en respuesta) | Alto | 155k / v1.17.1 |
| n8n | Sustainable Use License (no OSS) | Sí | Sí | DOCX/PPTX/XLSX por `n8n-nodes-docxtemplater` (docxtemplater) | **Sí** (determinista) | Sí (webhooks) | Medio | — |
| DeerFlow | MIT | Sí con espejos PyPI/npm | Sí | Report md/docx/pdf; `ppt-generation` = PPTX de imágenes; Marp | No | Gateway LangGraph | Alto (16 vCPU/32 GB prod) | 82k / v2.0.0 |
| Suna/Kortix | **Elastic 2.0** | No ("not a disconnected one") | Vía LiteLLM | "reports, decks" por código en sandbox | No | Sí (propia) | Alto (Supabase…) | 20k / v0.13.12 |
| OpenManus | MIT | Sí | Sí | Nada específico de Office | No | Lib Python | Bajo | 58k / v0.3.0 (2025-04) |
| II-Agent | Apache-2.0 | Sí (Docker) | Vía LiteLLM | Slides HTML, no PPTX | No | WebSocket | Medio | 3.4k / v0.4 (2025-07) |
| OpenHands | MIT | Sí (imágenes pre-pulled) | Sí (LiteLLM) | Lo que programe el agente | No | SDK + agent-server REST | Alto | 87k / v1.17.0 |
| Onyx CE | MIT (+ee) | Sí | Sí | Archivos por code interpreter; previews CSV/PDF/DOCX | No | API chat | Alto | 32k / v4.7.1 |
| AnythingLLM | MIT | Sí | Sí | txt/pdf/xlsx/docx/pptx (Document Generation agent) | No | API | Bajo | 66k / v1.16.1 |
| Presenton | Apache-2.0 | Sí (Ollama) | Sí | Sólo PPTX/PDF; plantillas HTML/Tailwind + "template from existing PPTX" | **Sí** (parcial) | **Sí** | Bajo | 10k |
| PPTAgent | MIT | Sí | OpenAI-compat | PPTX editando presentación de referencia | **Sí** (referencia) | Lib/CLI | Medio | 5k / v2.0.0 |

---

### 4. Veredicto

### 4.1 ¿Qué sandbox concreto usaría para un backend Python on-prem?

**Recomendación principal: ejecutor propio "DocRunner" = `llm-sandbox` (MIT) + imagen Docker propia + runtime gVisor cuando el host lo permita.**

Por qué esta combinación y no otra:

1. **Encaja en el stack**: es una librería Python; se llama desde el backend con `SandboxSession(image="eleia/docrunner:1.0", runtime="runsc")`, `copy_to_runtime(plantilla)`, `run(codigo)`, `copy_from_runtime("/out/informe.pptx")`. Cero servicios nuevos. [llm-sandbox]
2. **Air-gapped real**: la imagen se construye en CI y se entrega con el instalador; no hay registry externo, no hay DNS, no hay pip en runtime (todo pre-instalado: `python-pptx 1.0.2`, `python-docx 1.2.0`, `openpyxl`, `docxtpl`, `reportlab`, Node + `pptxgenjs` + `docx`, y **LibreOffice headless** para PDF/normalización). Podés partir del Dockerfile de Open Terminal (MIT) que ya integra LibreOffice + Python + Node. [open-terminal] [pypi-pptx]
3. **Aislamiento escalonado**: piso = runc con `--network none`, `cap_drop ALL`, `no-new-privileges`, `pids_limit`, `mem_limit`, `read_only` + tmpfs, usuario sin privilegios, timeout duro (patrón idéntico al `DockerExecutor` de smolagents) [smolagents-secure]; upgrade = `--runtime=runsc` (gVisor, misma imagen, `runsc install`) en hosts con KVM o systrap [gvisor-install]; techo = Kata/Firecracker vía OpenSandbox o microsandbox si un cliente exige microVM. Si el host es Podman rootless (típico en RHEL de bancos), `llm-sandbox` lo soporta y gVisor no → ahí el piso son las restricciones de runc.
4. **Por request, no por usuario**: cada generación crea y destruye el contenedor (o toma uno del pool pre-calentado de `llm-sandbox`). Nada persiste entre clientes; la plantilla entra en `/in` read-only y el resultado sale de `/out`. Esto resuelve el problema de aislamiento de tenant de la spec 043.
5. **Validación post-ejecución fuera del sandbox**: el backend re-abre el archivo con python-pptx/docx (o `soffice --convert-to pdf` en el mismo sandbox) para confirmar que abre, y devuelve al chat sólo si pasa. Anthropic hace exactamente esto en sus skills. [anthropic-pptx-skill]

**Alternativa "plataforma" si se prevé K8s y varios consumidores del sandbox (no sólo documentos): OpenSandbox.** Servidor con API, SDK Python, egress por sandbox, y `secure_runtime` conmutable entre gVisor/Kata/Firecracker sin tocar código de cliente. Costo: un servicio más (server + execd), imágenes a espejar, y dependencia de un proyecto de Alibaba de 6 meses de vida pública (aunque con 15k stars y releases mensuales). [opensandbox] [opensandbox-secure]

**Alternativa microVM sin K8s: microsandbox.** Único que da kernel propio con un binario y KVM, con ejemplo oficial de LibreOffice offline; contras: beta y foco comercial migrando a cloud. [microsandbox] [microsandbox-libreoffice]

**No usar:** E2B self-host (no on-prem), Daytona (congelado/AGPL), Pyodide (archivado, sin LO, sin salida de archivos), Piston (stdout), Jupyter Gateway (compartido), dify-sandbox (acoplado), Docker Sandboxes (herramienta de dev en Mac/Win).

### 4.2 ¿Alguna plataforma completa vale la pena adoptar en vez de construirlo?

**No para reemplazar Eleia Hub.** Razones verificadas:

- **Licencias**: Open WebUI exige licencia enterprise para marca propia con >50 usuarios [owui-license]; Dify prohíbe multi-tenant y quitar logo sin acuerdo [dify-license]; Suna es Elastic 2.0 [suna-license]; n8n es Sustainable Use [n8n-license]. Sólo LibreChat, Onyx CE, OpenHands, DeerFlow, AnythingLLM, OpenManus son MIT/Apache limpios.
- **Ninguna trabaja "desde la plantilla corporativa del cliente"** como feature de producto. La más cercana es el plugin `md_exporter` de Dify (reference DOCX / slide master PPTX con pandoc) [md-exporter], y en presentaciones Presenton/PPTAgent con "template desde PPTX existente" [presenton] [pptagent]. Todo lo demás es "el modelo escribe python-pptx desde cero".
- **API**: sólo Dify (REST de workflow) y Presenton (API de presentaciones) exponen un endpoint invocable limpio desde una app externa; LibreChat/Open WebUI/Onyx son UI-first.

**Sí vale la pena adoptar piezas:**

| Pieza | Licencia | Para qué |
|---|---|---|
| Imagen Docker de Open Terminal | MIT | Base del contenedor DocRunner (LibreOffice + Python + Node ya resueltos) [open-terminal] |
| `md_exporter` (pandoc + typst) | Apache-2.0 | Camino determinista Markdown→DOCX/PPTX con plantilla de marca; corre como Agent Skill fuera de Dify [md-exporter] |
| Onyx code-interpreter | MIT | Referencia de API mínima (`/v1/files`, `/v1/execute`) si se quiere exponer DocRunner como microservicio [onyx-ci] |
| LibreChat code-interpreter | Apache-2.0 | Referencia de arquitectura hardened (NsJail dentro de libkrun) y de "máx N archivos por run" [librechat-ci-repo] |
| Anthropic skills `pptx`/`docx` | Apache-2.0 (repo `anthropics/skills`) | Prompts y scripts (html2pptx, OOXML unpack/edit/pack) para que el modelo respete plantillas [anthropic-pptx-skill] |
| PPTAgent | MIT | Idea de "extraer layouts + esquema de la plantilla y generar por edición", si se quiere algo más que reemplazo de placeholders [pptagent] |

### 4.3 Costos en tokens / latencia: "código generado" vs plantilla determinista

Medición publicada (paper *Talk to Your Slides*, arXiv 2505.11604, tabla 1, Gemini 2.5 Flash, por instrucción de edición de slide):

| Enfoque | Tokens in | Tokens out | Costo |
|---|---|---|---|
| Generación directa de código (LLM escribe código sobre el PPTX) | 1.24k | 1.48k | US$0.001 |
| Talk-to-Your-Slides (parseo estructurado + código) | 4.26k | 2.53k | US$0.002 |
| Agente por UI (screenshots) | 97.29k | 2.23k | US$0.0159 |

Conclusión del paper: manipular el modelo de objetos (código) es 87 % más barato que agentes visuales y con 96.8 % vs 74.4 % de éxito. [ttys-paper]

Extrapolación para Eleia (estimación propia, no medida):

- **Code interpreter (docx/pptx completo, 8–12 slides o 3–5 páginas)**: 2–4k tokens de prompt (instrucciones + esquema de la plantilla + datos RAG) y **3–8k tokens de salida** de código; con reintento por error de ejecución (frecuente en python-pptx con layouts de plantilla) sumá otra vuelta de 1–3k. A precios Azure GPT-4.1-class (≈US$2/M in, US$8/M out) son **US$0.03–0.10 por documento**, latencia **15–60 s** (generación de código + arranque de contenedor 0.5–2 s runc / ~50 ms gVisor / ~125 ms Firecracker + ejecución + LibreOffice 2–5 s). [opensandbox-secure]
- **Plantilla determinista (docxtpl / pptx-automizer con JSON del modelo)**: el modelo sólo emite el **contenido estructurado** (JSON de 0.8–2.5k tokens), sin código ni reintentos de ejecución; **US$0.01–0.03 por documento**, latencia **5–15 s**, resultado 100 % conforme a la plantilla y auditable. Coincide con la decisión sellada el 10-sep en la investigación docgen (docxtpl + pptx-automizer + Gotenberg).
- **Tokens de contexto ocultos**: en el enfoque código, describirle al modelo la plantilla (layouts, placeholders, estilos) cuesta 1–3k tokens por request, salvo que se cachee un "manifest" de la plantilla; en el determinista ese manifest vive en el backend y el modelo sólo ve el esquema JSON.

**Router recomendado:** default = plantilla determinista (spec 045/046); "modo libre / code interpreter" sólo cuando el pedido no mapea a ninguna plantilla o el usuario pide explícitamente gráficos/tablas ad-hoc; en ambos casos el archivo pasa por el DocRunner para validar/convertir a PDF. Presupuesto por rol (spec 047) debería tarifar el modo libre 3–4× más caro que el determinista.

### 4.4 Riesgos y mitigaciones específicas del enfoque código

- **Inyección vía RAG**: contenido recuperado puede contener instrucciones que el modelo convierta en código malicioso → sandbox sin red, sin secretos, FS read-only salvo `/out`, y lista de imports permitidos verificada por AST antes de ejecutar (idea del `LocalPythonExecutor` de smolagents, usada como pre-filtro, no como única defensa). [smolagents-secure]
- **Exfiltración por archivo**: el único canal de salida es `/out`; validar tipo MIME real (zip OOXML), tamaño máximo, y re-guardar el archivo desde el backend (round-trip con python-pptx) para descartar payloads ocultos (macros, OLE, external links).
- **Bus factor de `llm-sandbox`**: es MIT y ~2k líneas; presupuestar fork interno. Si preocupa, OpenSandbox es la alternativa con más respaldo.
- **KVM no disponible** (VMs sin nested virt en el cliente): gVisor en modo systrap sigue funcionando sin KVM; microVMs no. [gvisor-install]

---

### 5. Fuentes

- [e2b-infra-readme] https://github.com/e2b-dev/infra (README: "Supported cloud providers: GCP, AWS (Beta), [ ] Azure, [ ] General linux machine")
- [e2b-deepwiki] https://deepwiki.com/e2b-dev/infra/9-self-hosting-guide
- [beam-selfhost] https://www.beam.cloud/blog/how-to-self-host-code-sandbox
- [microsandbox] https://github.com/zerocore-ai/microsandbox
- [microsandbox-libreoffice] https://docs.microsandbox.dev/examples/file-processing/libreoffice-pdf
- [microsandbox-blog] https://www.prompts.brightcoding.dev/blog/microsandbox-hardware-isolated-sandboxes-for-ai-agents
- [daytona-readme] https://github.com/daytonaio/daytona (aviso "no longer maintained… June 2026")
- [awesome-sandbox] https://github.com/restyler/awesome-sandbox
- [opensandbox] https://github.com/alibaba/OpenSandbox
- [opensandbox-secure] https://github.com/alibaba/OpenSandbox/blob/main/docs/guides/secure-container.md
- [byteiota-opensandbox] https://byteiota.com/opensandbox-alibabas-free-ai-agent-sandbox-2026/
- [piston] https://github.com/engineer-man/piston
- [jeg-docs] https://jupyter-enterprise-gateway.readthedocs.io/en/latest/
- [owui-code-exec] https://docs.openwebui.com/features/chat-conversations/chat-features/code-execution/
- [owui-license] https://docs.openwebui.com/license/
- [owui-azure] https://docs.openwebui.com/tutorials/integrations/llm-providers/azure-openai/
- [open-terminal] https://github.com/open-webui/open-terminal
- [librechat-ci-repo] https://github.com/LibreChat-AI/code-interpreter
- [librechat-ci-docs] https://www.librechat.ai/docs/features/code_interpreter
- [librechat-azure] https://www.librechat.ai/docs/configuration/azure
- [librechat-changelog] https://www.librechat.ai/changelog/v0.8.6-rc1
- [librechat-search] https://github.com/danny-avila/LibreChat/discussions/9445
- [onyx-ci] https://github.com/onyx-dot-app/code-interpreter
- [onyx-code-exec] https://docs.onyx.app/overview/core_features/code_interpreter
- [onyx-changelog] https://docs.onyx.app/changelog
- [onyx-search] https://github.com/onyx-dot-app/onyx
- [dify-sandbox] https://github.com/langgenius/dify-sandbox
- [dify-sandbox-faq] https://github.com/langgenius/dify-sandbox/blob/main/FAQ.md
- [dify-license] https://github.com/langgenius/dify/blob/main/LICENSE
- [dify-azure] https://marketplace.dify.ai/plugin/langgenius/azure_openai
- [md-exporter] https://github.com/bowenliang123/md_exporter
- [dify-md-exporter-mkt] https://marketplace.dify.ai/plugin/bowenliang123/md_exporter
- [dify-md-exporter-guide] https://docs.dify.ai/en/develop-plugin/dev-guides-and-walkthroughs/develop-md-exporter
- [dify-doc-plugin] https://marketplace.dify.ai/plugin/stvlynn/doc
- [dify-ppt-plugin] https://marketplace.dify.ai/plugin/stvlynn/ppt
- [mcp-run-python] https://github.com/pydantic/mcp-run-python
- [langchain-sandbox] https://github.com/langchain-ai/langchain-sandbox
- [pyodide-pkgs] https://pyodide.org/en/stable/usage/packages-in-pyodide.html (lista incluye lxml, Pillow, pandas)
- [pypi-pptx] https://pypi.org/project/python-pptx/ (1.0.2, wheel py3-none-any; requiere Pillow, XlsxWriter, lxml)
- [smolagents-secure] https://huggingface.co/docs/smolagents/en/tutorials/secure_code_execution
- [llm-sandbox] https://github.com/vndee/llm-sandbox
- [codebox-ai] https://github.com/tomconte/codebox-ai
- [openhands-headless] https://docs.openhands.dev/openhands/usage/run-openhands/headless-mode
- [openhands-docker-sdk] https://docs.openhands.dev/sdk/guides/agent-server/docker-sandbox
- [openhands-azure] https://docs.openhands.dev/openhands/usage/llms/azure-llms
- [gvisor-install] https://gvisor.dev/docs/user_guide/install/
- [gvisor-vs-fc] https://dev.to/chunxiaoxx/mcp-security-patterns-2026-gvisor-vs-firecracker-for-ai-agent-sandboxing-3hp7
- [northflank-sandbox] https://northflank.com/blog/how-to-sandbox-ai-agents
- [docker-sandboxes-docs] https://docs.docker.com/ai/sandboxes/
- [docker-sandboxes-hn] https://news.ycombinator.com/item?id=48225932
- [devdigest-sandboxes] https://www.developersdigest.tech/blog/ai-agent-code-sandbox-comparison-2026
- [n8n-license] https://docs.n8n.io/sustainable-use-license/
- [n8n-docxtemplater] https://github.com/jreyesr/n8n-nodes-docxtemplater
- [deerflow-readme] https://github.com/bytedance/deer-flow
- [deerflow-ppt-skill] https://explainx.ai/skills/bytedance/deer-flow/ppt-generation
- [deerflow-review] https://www.openaitoolshub.org/en/blog/deerflow-bytedance-ai-agent-review
- [suna-readme] https://github.com/kortix-ai/suna
- [suna-license] https://github.com/kortix-ai/suna/blob/main/LICENSE (Elastic License 2.0)
- [suna-search] https://apidog.com/blog/suna-ai-open-source-general-ai-agent/
- [openmanus-search] https://github.com/FoundationAgents/OpenManus
- [ii-agent-search] https://github.com/Intelligent-Internet/ii-agent
- [pptagent] https://github.com/icip-cas/PPTAgent
- [presenton] https://github.com/presenton/presenton
- [manus-alts] https://www.pickyourtech.com/alternatives/manus
- [anythingllm-docgen] https://docs.anythingllm.com/agent/usage/document-generation-agent
- [anthropic-pptx-skill] https://github.com/anthropics/skills/blob/main/skills/pptx/SKILL.md
- [ttys-paper] https://arxiv.org/html/2505.11604v4 (Tabla 1: tokens y costo por instrucción)
- [shields] https://img.shields.io/github/stars/<owner>/<repo>.json, …/license/…, …/v/release/…, …/release-date/… (consultados 2026-09-10 para todos los repos citados)
