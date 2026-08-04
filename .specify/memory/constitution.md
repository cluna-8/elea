<!--
SYNC IMPACT REPORT — Basa Guardian Constitution
Version change: 2.0.0 -> 2.1.0 (MINOR: cambio de texto de un principio core, per Governance)
Enmienda "D8 de la 027" (decision sellada por el owner el 2026-07-22 en
  specs/027-governance-configurable-enforcement/research.md §D8; ejecutada el 2026-08-04 con OK
  explicito de JF). OJO: no confundir con el default interno [D8] de esta constitucion (compresion).

- I. Privacy & PII/PHI Masking-First ....... MODIFICADO (titulo y MUST). El mandato se parte en dos:
    PISO no-negociable = interceptar + detectar PII + evaluar + registrar (constante de codigo,
    ningun perfil/toggle lo apaga) y TRANSFORMAR (enmascarar) = gobernable como decision de la capa
    pii_masking (absorbe redact_enabled de la 013), jamas silencioso: con enmascarado off el pedido
    queda registrado como "PII detectada, no enmascarada por configuracion".
    Motivo: la letra anterior ("todo prompt DEBE enmascararse") derogaba FR-014 de la 013 ya
    entregado y contradecia la semantica real de los dos planos (basa_guardrail.py / gateway.py).
- Actualizacion factual de paso (sin cambio normativo): Presidio ya no es scaffolding inactivo —
    la 016 esta implementada en main; su deuda de señalizacion de degradacion vive en #63/#64.
- Secciones agregadas/quitadas: ninguna. Los 8 principios se conservan.
- Templates revisados: plan/spec/tasks-template y AGENTS.md sin referencias al texto viejo
    (grep "enmascar|Masking-First" = 0 hits) — ✅ nada que propagar.
- Informe anterior (1.0.0 -> 2.0.0, reconciliacion y ratificacion 2026-07-10): en la historia git.
-->

# Basa Guardian — Constitución

**Basa Guardian** es un gateway/firewall de **compliance y gobernanza multi-tenant** para el uso
de IA en una organización. Se forkeó de `gatelite-salud-eu` feature/012 como base técnica
(FastAPI + motor LiteLLM white-label + PostgreSQL + Redis + React/Vite, SDD con specs 001-012).
El producto **ES la compliance y la gobernanza**, no un proxy LLM con features de compliance encima.
Los despliegues por cliente (Elea, Cámara de Comercio…) son **configuración + seed**, nunca forks.

> Nota de honestidad SDD: esta constitución distingue explícitamente lo **implementado hoy** de lo
> **forward-looking (a construir)**. No declara como hecho lo aspiracional — ese error hundió a las
> versiones previas. Cada principio marca qué es real y qué es meta.

## Core Principles

### I. Privacy & PII/PHI Masking-First (piso: detectar/evaluar/registrar · transformar: gobernable)
Todo prompt DEBE pasar por el **piso no-negociable** del firewall: interceptar, **detectar** PII/PHI,
evaluar (AI-Act, secretos) y **registrar** el pedido con su atribución. El piso es **constante de
código**: ningún perfil, toggle ni configuración puede apagarlo.
El **transformar** (enmascarar antes de salir hacia el motor/LLM) es la decisión de la capa
`pii_masking` y SÍ es gobernable por configuración (absorbe el `redact_enabled` de la 013 como
decisión de capa — D8 de la 027, sellada 2026-07-22): apagarlo es una elección legítima y scopeable
(p. ej. herramientas de código donde el enmascarado rompe el código), pero **JAMÁS silenciosa** — con
el enmascarado desactivado el pedido queda registrado como *"PII detectada, no enmascarada por
configuración"*, visible en gobernanza, atribuible y auditable. El enmascarado es el **default** y
sigue siendo el control más fuerte del producto.
Reglas duras cuando el enmascarado actúa: (a) opera con **mapa reversible** (`placeholder_map`) que
reconstruye los valores en la respuesta (incluido streaming) — el motor y el LLM **solo ven
placeholders**, nunca PII cruda; (b) ocurre **ANTES** de la compresión — los placeholders son tokens
atómicos intocables; (c) el mapa reversible vive donde exista el estado (backend/guardrail del motor),
jamás se delega a un tercero que rompa la reversibilidad; (d) **nunca solo regex en producción** con
PHI: el despliegue productivo exige NLP real (Presidio o equivalente — real desde la 016; la
señalización de su degradación se trackea en #63/#64). La política de enmascaramiento
(`entity_configs`) DEBE ser **scopeable por grupo con override por cliente** (reemplazando el
singleton global actual).

### II. Compliance & Governance FIRST (GDPR + EU AI Act)
La compliance es la **propuesta de valor central** y opera en **dos niveles que la constitución no debe
confundir**:
1. **Enforcement duro (bloquea en runtime, real hoy):** prácticas prohibidas del EU AI Act Art.5 (→ HTTP 400),
   entidades PII marcadas `BLOCK`, secretos/keys, y violación de residencia EU en el flujo proxy (→ 503).
2. **Evidencia/accountability auditada (GDPR Art.5(2), NO bloquea en runtime, real como registro):**
   base legal, `ComplianceProject`, DPA registry, Data Subject Requests (Art.15-22), consent versionado,
   retention policy, DPIA, human-review ex-post, disclosure Art.50, panel DPO, reporting RoPA Art.30.
   La auditoría es **metadata-only**: jamás se persiste texto de prompt ni PII cruda.
La resolución de compliance es **jerárquica** (tenant → grupo → cliente → conexión), reutilizando el
patrón per-cliente de `ComplianceProject`. **Residencia de datos EU** es el default del flujo proxy.
**Excepción acotada — módulo `base_url` clients (firewall de coding tools):** en modo interceptación el
usuario opera *dentro* de su cliente (Claude Code, Copilot…) y nosotros interceptamos sin re-inyectar, por
lo que el **GDPR-routing es N/A** (forzar un endpoint EU rompería el flujo). Esto **no deroga** el principio
de residencia: es una excepción documentada donde la garantía se traslada a otras capas (masking, audit,
allowlist de herramientas/modelos permitidos). Endurecer los gates hoy "evidencia" es roadmap explícito [D3].

### III. Multi-Tenant by Design (forward-looking)
**Requisito a construir, NO estado actual** (hoy el esquema es single-tenant: cero `tenant_id`, sin RLS).
Objetivo: aislamiento de tenant desde el esquema — toda entidad lleva `tenant_id`, toda query se scopea,
y el aislamiento duro se refuerza con **Row-Level Security de Postgres**. El **mismo código** corre
**single-tenant on-premise** (un tenant por instalación, apto para modelos locales Ollama/vLLM) y
**multi-tenant cloud** (SaaS). Jerarquía: **Tenant (empresa) → Group/Team → Client (persona) →
Connection (APIKey por herramienta)**.
**Modelo de acceso reconciliado** (integra los 4 roles legacy con lo nuevo): dos ejes —
(a) *tier administrativo scopeado por tenant*: **super-admin** (Basa, cross-tenant, sobre todo cloud) y
**tenant-admin** (gestiona SOLO su tenant: grupos, personas, políticas); (b) *roles de usuario dentro del
tenant*: **compliance_officer/DPO** (gobernanza) y **client** (la persona/seat que consume IA vía
herramientas, sujeto de la gobernanza legal). Los labels sectoriales heredados (`clinician`, `developer`)
se **degradan a etiquetas de display configurables**, no a roles hardcodeados; `role` pasa a tener
constraint (enum/CHECK). Migración implicada: `tenant_id` en User/Group/APIKey/Budget/AuditLog/
SecurityPolicy/Guardian/ComplianceProject + backfill + índices + RLS.

### IV. Client Onboarding as Data
Un "client" (Claude Code, Copilot, Claude Desktop, ChatGPT client, o nuestro chat UI propio) es un usuario
de primera clase: **`User role="client"` + `client_type`** (base_url / desktop / chat_ui), onboardeado como
**dato** — crear cliente, asignar grupo/policy/proyecto, emitir **virtual key(s) por herramienta**
(cada `Connection`/`APIKey` con su `tool_type`). La gobernanza legal vive a nivel **persona**; los toggles
por-herramienta viven a nivel **key**. Sumar un cliente o un demo **NUNCA** requiere tocar código.
Herramientas sin base URL o con red hostil (pinning) se documentan como no compatibles.

### V. Cost Governance & Optimization (honest)
Dos capacidades reales fusionadas, con **texto honesto** (sin promesas que el sistema no cumple):
1. **Budget & Resource Enforcement:** ninguna request sin **key válida** user/group (hay que **cerrar el
   fallback a admin por defecto** que hoy viola esto — ver SC). Presupuesto en **USD** con gate **402
   pre-request + accounting post-request** (doble capa secuencial personal→grupo), reforzado por
   **hard-ceiling y rpm/tpm delegados a LiteLLM** como backstop. Es **post-hoc, no "tiempo real"**: un
   request puede sobrepasar el límite antes del corte. **No se promete streaming** (el gateway no hace
   streaming hoy; enforcement en streaming es roadmap [D4]).
2. **Optimización de contexto ("Ahorro de Costes IA", ex-Headroom, white-labeled):** compresor determinista
   **seguro** (tiktoken; nunca corrompe URLs, código ni placeholders de PII) + SmartCrusher local
   (headroom-ai, Rust, 100% local, sin torch). El ahorro es **medible y neteado** del presupuesto; cache
   Redis + guardia de reversión. La compresión **LLM-asistida está descartada** ("no gastar tokens para
   ahorrar tokens"). Orden del pipeline: masking (I) **antes** de compresión.

### VI. LiteLLM-Native, No Patching
El motor es LiteLLM (white-label). Se reutilizan sus **puntos de extensión documentados** (custom guardrails,
custom auth, custom callbacks/loggers, `/v1/messages` nativo, `router_settings.fallbacks`) — **NO se parchea
ni se reimplementa** lo que el motor ya hace (routing, guardrails de motor, cost ceiling, rpm/tpm, protocolo,
streaming). Se **fija la versión** del motor y se cubren las firmas de los hooks con **tests de contrato**;
actualizar el motor = correr tests, no reescribir. **Única excepción de proxy propio:** el passthrough OAuth
de **suscripción** (que el motor no soporta) del módulo firewall — vive en el backend.

### VII. Containerized & White-Label (config + seed, never fork)
Backend, motor y frontend corren en **containers separados** (Docker Compose es la base de la verificación
local). Ningún nombre de motor ni proveedor externo (LiteLLM, Anthropic, OpenAI, Azure, Meta, Presidio…)
aparece en la API pública, mensajes de error, logs ni UI (naming neutro `AIEngineClient`/`engine_*`; strip de
prefijos `litellm.*` → "Basa Gateway"). Cada demo/cliente = **configuración + seed** sobre el mismo código
base, **nunca un fork** (el propio Basa Guardian nació de un fork que no debe repetirse).

### VIII. Pipeline Transparency & Explainability
Cada request DEBE ser **observable capa a capa** vía `pipeline_metadata` real por request
(masking → optimización → compliance → routing/LLM → unmask). Esta observabilidad regulatoria es el
principio durable; el **Playground** (visualización animada de las capas + Debugger con JSON crudo) es su
**vitrina interactiva**, no una feature aislada. La animación es cosmética; los **datos deben ser reales**.

## Security & Compliance Constraints

1. **No Raw PII/PHI Storage**: ni en DB, ni archivos, ni logging externo. La auditoría guarda solo
   metadatos (tipos de entidad, scores, timing, verdicto, propósito), nunca el contenido.
2. **NLP real en prod**: regex de PII es aceptable solo en demo/dev; el despliegue productivo con PHI
   **exige** Presidio NLP (o equivalente) activo — el scaffolding inactivo actual debe activarse.
3. **Cerrar el fallback de auth**: ninguna request sin key/token válido debe caer a un usuario admin por
   defecto (agujero actual). Fail-closed en identidad; fail-open solo donde esté justificado y documentado.
4. **Tenant Isolation**: ninguna query cruza `tenant_id`; **RLS activo** en cloud (precondición de gobernanza SaaS).
5. **Encryption**: TLS en tránsito; **Fernet** para secretos/service keys en reposo; credenciales fuera de
   `config.yaml` en claro (env vars / gestor de secretos).
6. **Auditoría metadata-only** y export GDPR Art.30 (RoPA/RAT) sin PII cruda.

## Development Workflow

1. **Spec-Driven Development**: toda feature se **especifica, planea y revisa** antes de codear
   (spec.md → plan.md → tasks.md), alineada a esta constitución.
2. **Reuse over Reinvent**: primero se verifica si LiteLLM (o el core existente) ya lo resuelve (sesgo
   USE-LITE/KEEP-WITH-REASON heredado de spec 012).
3. **Tested & Verified**: todo cambio con lógica no trivial lleva **tests automatizados** (se hereda la
   suite Pytest 20/20); la reversibilidad del masking y los hooks de LiteLLM llevan **tests de contrato**
   contra la versión fijada. Verificación local con **Docker Compose** antes de mergear.
4. **Documentación viva**: mantener sincronizados `spec/plan/tasks/changelog` (saldar la deuda documental
   observada en specs 011/012).

## Governance

Esta constitución **gobierna todas las decisiones de arquitectura** de Basa Guardian. Ningún despliegue por
cliente (config/seed) puede violar estos principios.
**Enmiendas:** cambiar el *texto* de un principio o una constraint = bump **MINOR**; **agregar/quitar/derogar**
un principio core = bump **MAJOR**; correcciones de redacción sin cambio semántico = **PATCH**. Toda enmienda
se registra en el Sync Impact Report (encabezado) con su justificación. Los **defaults [D#]** de la sección
siguiente son enmendables de una línea (MINOR o menos) mientras no se haya empezado a codear la feature que
los materializa.

## Decisiones (defaults revisables)

Defaults tomados sobre las open-questions de la reconciliación, para no bloquear. Si alguno no te cierra,
es una enmienda de una línea:
- **[D1] Playground → principio de Transparencia (VIII), Playground como vitrina.** (vs. mantenerlo como
  principio propio "debe existir UI Playground animada"). Elegido: más durable y no pierde la capacidad.
- **[D2] Versionado = 2.0.0 (MAJOR).** Rename + multi-tenant + principios nuevos lo justifican; se deja
  constancia explícita de que **no** deroga los heredados. Resuelve el mismatch git (HEAD tenía draft 2.0.0,
  working tree tenía revert a 1.0.0): esta versión reconciliada los supersede.
- **[D3] Postura de compliance = dos niveles honestos** (enforcement duro vs evidencia auditada), ratificando
  el fail-open actual como stance **explícito y auditado**, con "endurecer gates X" como roadmap — NO se
  declara que consent/DPA/retención bloqueen si no lo hacen.
- **[D4] Budget: se elimina "tiempo real / streaming" del texto** (no existe hoy); streaming enforcement =
  roadmap. Se manda **cerrar el fallback admin** como constraint de seguridad.
- **[D5] Masking: Presidio NLP real = constraint de prod** (SC-2), regex solo demo/dev.
- **[D6] 8 principios** (no se sobre-consolidó por fidelidad). Multi-Tenant y Client-as-Data quedan separados;
  el firewall `base_url` es **excepción documentada** del Principio II, no principio propio.
- **[D7] Multi-Tenant/RLS ratificado como forward-looking** (requisito a construir), explícito para no repetir
  el error de declarar como hecho lo aspiracional.
- **[D8] Compresión** obtiene hogar en Principio V (Cost Governance & Optimization), fusionada con budget.
- **[D9] RBAC reconciliado**: super-admin/tenant-admin (tiers por tenant) + compliance_officer + client;
  clinician/developer → labels de display configurables.

**Versión**: 2.1.0 | **Ratificada**: 2026-07-10 | **Basada en**: gatelite "Basa Secure AI Gateway" v1.0.0
(2026-06-29) + feature/012 | **Última enmienda**: 2026-08-04 (D8 de la 027: piso vs transformar)
