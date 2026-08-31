# Tech Tree Guardian — datos

- Departamento: Guardian App Ecosystem · Jefe técnico: JF
- Fecha: 2026-08-05 · Estado: propuesta para betting ciclo 1
- MVP septiembre: Fase 0 completa + 3 gates de carga aprobados
- Alcance Fase 0: API/BYOK, sin extensión de navegador
- Estados: `hecho` (en main) · `por-construir` · `nuevo` (sin spec) · `decision` (charla, no código) · `bloqueado` (se abre con gates)

## Fase 0 — rama Compliance & auditoría

| Nodo | Estado | Detalle | Refs |
|---|---|---|---|
| Registro durable de todo | hecho | cada petición y bloqueo en DB: quién, modelo, capa, motivo; sobrevive reinicios | spec 031 |
| Masking que avisa al degradar | por-construir | caída del NLP degrada a regex en silencio; regex etiqueta mal (IBAN→PHONE) | #63, #64, P1 seguridad |
| Export datos RGPD (DSAR) | por-construir | Art. 15/20; endpoint devuelve 500 a todos los roles | #62 |
| Retención con purga real | por-construir | retención configurable pero sin borrado al vencer (verificar purga al día 91) | spec 018 |
| Política si no se puede auditar | decision | dirección cerrada (weekly 05-ago): por nivel de riesgo/rol del usuario; default actual fail-open para todos; falta spec corta + ¿auditar errores? | SENTINEL_AUDIT_FAIL, weekly |

## Fase 0 — rama Control de costos

| Nodo | Estado | Detalle | Refs |
|---|---|---|---|
| Presupuestos con corte | hecho | 402 antes de llamar al proveedor | #76 |
| Costo por petición/usuario | hecho | registro por request; agregado por usuario, key, modelo; local=0 | spec 030 |
| Tarifario centralizado | por-construir | precios faltantes (gpt-5.5, gpt-4.1-mini) + conectar fuente pública de precios (sin mantenimiento manual) + visualización en panel | #73 ampliado |
| Presupuestos con alertas y flexibilidad | nuevo | niveles de alerta estilo AWS + presupuesto variable hasta +10% para roles de alto consumo; gasto personal antes que grupal | weekly 05-ago |

## Fase 0 — rama Configuración autónoma del partner

| Nodo | Estado | Detalle | Refs |
|---|---|---|---|
| Alta cliente/usuarios/keys por UI | hecho | verificado en piloto Cámara | — |
| Alta de modelos sin reiniciar y completa | por-construir | hoy: restart manual del motor; objetivo: reload automático + modelo nuevo entra a fallback y tarifario sin edición manual | spec 033, #73 |
| Fallback por modelo | hecho | cadena de respaldo por modelo, configurable por UI; verificado en test integral del piloto; el ruteo de Fase 0 es este | spec 010 |
| Rol Auditor honesto | por-construir | roles actuales: admin, developer, compliance_officer, usuario final; ficha del auditor no cubre costos/consumo/reportes; 034 lo completa (ve todo compliance, no toca nada) | spec 034, rama quickwin 3 commits |
| Rol Lectura | nuevo | solo-lectura general del panel; se especifica junto a 034 | — |
| SSO escalón 1: Microsoft + Google | por-construir | OIDC con Entra y Google Workspace; SSO actual = mock; escalón 2 post-Fase 0: SAML, otros IdP, Active Directory + segmentación por roles/grupos (consulta crítica de cliente) | 017 parcial |
| Carga masiva de usuarios + invitaciones | nuevo | alta por lotes (hoy una por una, no escala a 125+) + correos de activación | weekly 05-ago |
| Reinicio de contenedores desde la UI | nuevo | botón de restart sin scripts; alivio inmediato, se especifica junto a 033 | weekly 05-ago |
| Huecos del wizard (Evidenze) | por-construir | preguntas de Cristian en el ensayo revelan configuración no autónoma; cada hueco → nodo | ensayo Evidenze |

## Fase 0 — rama Capacidad

| Nodo | Estado | Detalle | Refs |
|---|---|---|---|
| Harness de carga | por-construir | banco de pruebas con mezcla realista (chat/extensión/coding) contra stack prod; diseño en papel: k6 + xk6-sse; complemento weekly: validación con modelos reales vía API keys OpenRouter | spec nueva |
| Fix pool anti-starvation | por-construir | incidente sede 30-jul: cuelgue ~10 min con pocas requests largas sobre 2 workers; falta tope de concurrencia + timeout | incidente sede |
| Streams largos sin corte | por-construir | read inter-chunk 60s < timeout router 120s → 502 si primer token tarda >60s; conexo: política de aviso al usuario por mensaje muerto por demora (define Cristian) | gap 60/120 |
| Panel de rendimiento | nuevo | tablero de métricas del sistema + medias de modelos locales; se alimenta del harness | weekly 05-ago |
| Perillas de escala | por-construir | hoy: 1 proceso NLP, 1 motor, 2 workers backend, sin límites de recursos; dimensionado 10-15 usuarios | dossier capacidad 04-ago |
| Cierre gobernanza 027 | por-construir | tareas restantes: T024, T025 (plano motor), T034 (quickstart e2e), T036 | spec 027 |

## Examen de Fase 0 — gates de carga

| Gate | Contenido |
|---|---|
| 125 | paridad sede (~125 beta testers Cámara); 30 min sostenido; corpus PII español |
| 250 | + login storm: 250 logins en ventana de 10 min |
| 500 | + soak 60 min + pico 2× + recuperación; número del MVP |

SLO en los tres gates:
- Δ pérdida de auditoría = 0 (contador 031 en /health; None = FAIL)
- reconciliación: filas audit_logs == requests auditables emitidas
- 0 entidades PII crudas llegadas al proveedor (canarios en stub)
- 100% de bloqueos con fila durable

## Fase 1 (bloqueada: se abre con gates verdes por delante de plan)

| Rama | Nodo | Estado | Detalle | Refs |
|---|---|---|---|---|
| Extensión multi-browser | Firefox | bloqueado | MV3 con service_worker distinto; dispara AMO | #65 |
| Extensión multi-browser | Edge | bloqueado | Chromium; empaquetar y probar | — |
| Extensión multi-browser | Superficie ChatGPT web | bloqueado | validado hoy: Claude.ai | — |
| Extensión multi-browser | Safari | descartado | App Store + packaging propio; reevaluar con demanda | — |
| IDEs y CLIs | Cerrar parciales matriz 019 | bloqueado | Claude Code ✔ · Aider ✔ · VS Code/Cursor parcial · Codex CLI ✗ | matriz 019 |
| Proveedores | Gemini | bloqueado | único grande sin adapter | #58 |
| Proveedores | Kimi, DeepSeek, Grok (xAI) | bloqueado | OpenAI-compatibles vía LiteLLM: config + precios + fila matriz | — |
| Proveedores | OpenRouter (agregador) | bloqueado | candidato weekly: centraliza contratos legales y acceso a N modelos con una key | weekly 05-ago |
| Ruteo inteligente | Auto-router semántico garantizado | bloqueado | 030 ya en main (panel Ruteo inteligente + modo Automático del portal); Fase 1 = garantía con modelos nuevos (categorías, evaluación, opt-in por cliente). Decisión JF 05-ago: Fase 0 rutea con fallback | spec 030 |

## Fase 2 (bloqueada)

| Nodo | Estado | Detalle | Refs |
|---|---|---|---|
| Portal de chat del usuario final | v0 hecha | UserPortal en main: rol usuario final → chat con selector de modelo + modo Automático; nunca la consola | UserPortal, 030 |
| Evolución del portal | bloqueado | branding por partner, historial, mejoras según demanda; vuelve la extensión opcional | — |

## Módulos ↔ árbol

| Módulo | Ubicación en el árbol |
|---|---|
| Gateway & API backend | hecho · F0: streams sin corte, perillas |
| Motor firewall & guardrails | F0: 033 · hecho: fallback por modelo |
| Detección PII NLP+regex | F0: #63/#64 |
| Extensión navegador (app) | F1: multi-browser |
| Integraciones 3rd-party | F1: matriz 019 |
| UI interna cliente (panel) | hecho: 11 páginas con roles · F0: huecos wizard |
| Playground & monitor | hecho |
| Auto-router semántico | hecho (030) · F1: garantía modelos nuevos |
| Auditoría & compliance | F0: #62, 018, decisión fail-open |
| Presupuestos & cost tracking | hecho · F0: #73 |
| Gobernanza & políticas | hecho · F0: colas 027 |
| Multi-tenant & migraciones | hecho |
| Lib licensing (runtime) | hecho; emisión = Factory |
| Docs de producto (contenido) | hecho; build = Factory |

## Ciclos (propuesta betting; fecha fija, alcance recortable)

| Ciclo | Fechas | Apuestas |
|---|---|---|
| 1 | 11–21 ago | #63/#64 (+ reglas regex por región) · harness + fix pool + gates 125 y 250 medidos |
| 2 | 24 ago–4 sep | 033 + streams + colas 027 · perillas 250→500 · #62 |
| 3 | 7–18 sep | 034 + rol Lectura + SSO Microsoft/Google · 018 · gate 500 verde |

Regla: nodos de Fase 1/2 entran a un ciclo solo con gates verdes por delante de plan.

## Decisiones del weekly 05-ago (cerradas)

- Política de auditoría: por nivel de riesgo/rol del usuario (falta spec corta)
- Licencias y firmas: SIMPLES en esta fase (clave pública + grace + bloqueos; complejidad a capas externas)
- Flujo: main + tags por ciclo de 2 semanas; ramas cortas por PR
- Soporte: primera línea = rol Operaciones → triage instalación vs producto → issue por depto
- Modo de ejecución: JF de vacaciones desde 06-ago; ciclo 1 lo ejecuta Claude (Fable 5) en autonomía, JF monitorea desde el móvil

## Preguntas abiertas

| # | Tema | Decisores |
|---|---|---|
| 1 | Licencia de test 500 seats para el harness (la de Cámara: 300) | Falime (emisión), Cristian (gate custodia) |
| 2 | Costura secrets.env: generación en sede vs fábrica; reparto de trabajo | JF + Falime |
| 3 | Spec de política de auditoría por riesgo/rol: ¿capa 027 o spec propia? ¿auditar errores? | JF + Cristian |

## Fuentes

- Fact-check 04→05-ago: 95 afirmaciones verificadas sobre main 7071498 + dossier de capacidad con evidencia archivo:línea
- Pase por panel real 05-ago: App.tsx (11 páginas, gating por rol), UserPortal.tsx, ModelsPage.tsx (fallbacks, panel Ruteo inteligente, pricing)
- Incidente pool sede 30-jul · encargo Cristian (Slack 05-ago) · decisiones JF 05-ago
- Fuente de verdad en repo: `sentinel-guardian/specs/ROADMAP-pisos.md` · Versión visual: `TechTree-SentinelGuardian.html`
