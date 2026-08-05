# Guardian App Ecosystem — datos

- Departamento: Guardian App Ecosystem · Jefe técnico: JF
- Fecha: 2026-08-05 · Alcance: solo este departamento (Install & Factory: ver ManosALaObra)

## Stack por capa

| Capa | Componente | Tecnología | Función |
|---|---|---|---|
| Usuario (JS) | Extensión de navegador | JavaScript, MV3, service worker + content scripts | masking de PII en ChatGPT/Claude.ai antes de enviar |
| Usuario (JS) | Panel de administración | React, TypeScript, Vite | usuarios, keys, modelos, presupuestos, auditoría, playground |
| Usuario | Coding tools 3rd-party | — | Claude Code, VS Code, Cursor, Aider vía base_url al gateway |
| Usuario | Apps del cliente | REST, SSE | BYOK; rutas compatibles Anthropic/OpenAI |
| Ingress | Caddy | TLS, CA propia del cliente | terminación TLS + ruteo interno |
| Ingress | Docs de producto | MkDocs | manual del cliente, air-gapped |
| Producto (Python) | Backend API | Python, FastAPI, SQLAlchemy, uvicorn | identidad, keys, presupuestos, auditoría, gobernanza, licencias runtime, gateway |
| Producto (Python) | Motor firewall | Python, LiteLLM 1.92.0 pinneado + extensiones propias | auth, guardrails, masking, ruteo a 100+ proveedores y Ollama local |
| Producto (Python) | Sidecar NLP | Python, Presidio, spaCy es_core_news_md | detección PII en español; regex como fallback |
| Datos | PostgreSQL | postgres:16 | identidad, auditoría durable, presupuestos, gobernanza |
| Datos | Redis | redis:7-alpine | rate limiting, monitor en vivo, contadores de pérdida de auditoría |
| Runtime | Docker | compose, 8 contenedores | self-hosted en la sede del cliente |

## Dos stacks

| Stack | Componentes | Característica |
|---|---|---|
| Python | backend, motor, NLP | código propio en runtime propio; tests y release unificados |
| JavaScript | extensión, panel | la extensión corre en el browser del cliente sobre DOM de terceros; tooling y release separados |

## Extensión de navegador

- Stack: JavaScript MV3 (service worker + content scripts), build con Node
- Función: intercepción del prompt pre-envío · detección vía `/gw/inspect` · masking en página · aviso de bloqueos al usuario
- Superficies: Claude.ai (validado) · ChatGPT web (roadmap)
- Factores de complejidad: stack distinto al resto del producto · DOM de terceros que cambia sin aviso (una guerra de mantenimiento por proveedor) · compatibilidad de browsers elegidos por el cliente · distribución por tiendas (CWS, AMO, App Store)
- Estrategia: Fase 0 se cumple sin extensión (API/BYOK); el portal de chat propio (Fase 2) la vuelve opcional

## Matriz de navegadores

| Browser | Estado | Nota |
|---|---|---|
| Chrome | funciona | Chromium MV3; canónica; instalada en piloto |
| Edge | cerca | Chromium; empaquetar y probar; relevante para clientes Microsoft |
| Brave | cerca | Chromium; validar shields sobre content scripts |
| Firefox | por portar | #65; MV3 con service_worker distinto; dispara AMO |
| Safari | descartado por ahora | App Store + packaging propio; reevaluar con demanda (clientes Apple) |
| Agénticos (Comet, Atlas, Dia…) | futuro | superficie nueva por definir |

Registro oficial por herramienta: `compatibility.md` en el repo (regla: sin probar ≠ sí).

## Soporte: flujo de bugs

| Paso | Responsable | Detalle |
|---|---|---|
| 1. Instalación | Falime | bundle + install en sede del cliente |
| 2. Canal + primera línea | rol Operaciones | canal interno por cliente (Teams/Slack); primera instancia la atiende Operaciones (rol, no persona); vigente hoy con la Cámara |
| 3. Triage | JF | instalación/update/stack → Factory · comportamiento del software → Guardian |
| 4. Issue | Guardian | GitHub con label `depto:guardian` + prioridad; sin issue no hay fix |
| 5. Fix → release → drop | ambos | Guardian corrige y define contenido; Factory fabrica bundle y entrega |

- Regla: problema de instalación ≠ bug de producto; Guardian no toca instalaciones, Factory no parchea producto
- Evolución: sistema de ticketing cuando haya más clientes; el canal queda para conversación, no registro

## Panel: páginas y roles (main, 05-ago)

| Página | Roles |
|---|---|
| Panel Principal | todos |
| Playground | todos |
| Modelos & Ollama | admin, developer |
| Costos | admin, compliance_officer |
| Usuarios & Presupuestos | admin |
| Gobernanza | admin |
| Seguridad y Guardianes | admin |
| Políticas de Cumplimiento | admin, compliance_officer |
| Logs de Auditoría | admin, compliance_officer |
| Conexiones en vivo | admin, compliance_officer |
| Documentación | todos |
| Portal de usuario final (chat + selector + modo Automático) | usuario final (nunca ve la consola) |

## Módulos (14)

| Módulo | Vive en | Estado | Pendiente |
|---|---|---|---|
| Gateway & API backend | backend | funciona (passthrough + BYOK) | — |
| Motor firewall & guardrails | motor | funciona | alta de modelo pide restart (033) |
| Detección PII: NLP + regex | sidecar NLP | funciona | degradación silenciosa (#63/#64) |
| Extensión de navegador (app) | JS·MV3 | funciona en Chromium | Firefox (#65) |
| Integraciones 3rd-party | gateway | matriz 019 con evidencia | parciales VS Code/Cursor |
| UI interna de cliente (panel) | React | funciona: 11 páginas con roles + portal usuario final | huecos wizard (Evidenze) |
| Playground & monitor | React + Redis | funciona | — |
| Auto-router semántico | motor | funciona (030) + modo Automático en portal | garantía con modelos nuevos = Fase 1 (decisión 05-ago); Fase 0 rutea con fallback |
| Auditoría & compliance | backend + DB | funciona (031) | DSAR 500 (#62) · retención sin purga (018) · política fail-open |
| Presupuestos & cost tracking | backend + motor | funciona (corte 402, #76) | tarifario (#73) |
| Gobernanza & políticas | backend | funciona (027) | 4 tareas de cierre |
| Multi-tenant & migraciones | backend + DB | funciona (013) | — |
| Lib de licensing (runtime) | backend | funciona (021, Ed25519 offline, fail-closed) | emisión = Factory |
| Docs de producto (contenido) | MkDocs | funciona (9/9 checks) | build brandeado = Factory |

## Frontera (NO es de este departamento)

bundles y white-label · instalaciones · updates · emisión de licencias · CLI basa-admin · CI/CD · TLS de onboarding · distribución de la extensión · VPS demo → Install & Factory (Falime). Contratos: en ambos roadmaps.

## Fuentes

- Fact-check 04→05-ago sobre main 7071498 · pase por panel real (App.tsx, UserPortal.tsx, ModelsPage.tsx)
- Versión visual: `EcosystemOverview-BasaGuardian.html` · Tech tree: `TechTree-BasaGuardian.{html,md}`
