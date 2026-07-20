# Overview & arquitectura

El producto es un **gateway seguro de IA para entornos regulados** — sanidad primero, y cualquier
sector con obligaciones GDPR / EU AI Act después. Es la **puerta única** por la que pasan todos los
prompts de una organización hacia los proveedores LLM: antes de que un prompt salga, el gateway
**detecta y enmascara PII/PHI**, aplica las **políticas de compliance**, gobierna **costes y
presupuestos**, y deja **evidencia auditable** de cada paso.

La idea central: **des-enmascarar en vez de bloquear**. El proveedor LLM recibe placeholders
(`[PERSON_0]`, `[DNI_0]`); el usuario ve la respuesta con los valores reales restaurados. La
experiencia de uso no se rompe — y el dato sensible nunca sale de la plataforma.

!!! note "Leyenda de estado"
    Esta página usa la leyenda de honestidad del sitio: 🟢 **HOY** (funciona y está verificado),
    🟡 **PARCIAL** (existe con límites documentados), 🔵 **OBJETIVO** (roadmap explícito, no
    implementado). Nada marcado 🔵 se describe como si existiera.

## Qué es el producto

- **Enmascaramiento reversible de PII/PHI** 🟢 — la detección y el enmascaramiento ocurren en la
  plataforma **antes** de que el prompt salga hacia el proveedor. Un mapa reversible reconstruye los
  valores reales en la respuesta; ese mapa nunca abandona la plataforma.
- **Detección con motor NLP** 🟡 — la detección por patrones es el default actual (apta para pilotos
  y entornos sin PHI real); un despliegue productivo con PHI exige activar el **motor NLP** de
  detección, y esa activación es una precondición documentada de producción.
- **Compliance GDPR + EU AI Act** 🟢 — en dos niveles que el producto no confunde: *enforcement duro*
  que bloquea en runtime (prácticas prohibidas del AI Act Art. 5, entidades marcadas `BLOCK`,
  secretos/credenciales, residencia de datos EU en el flujo proxy) y *evidencia auditada* que no
  bloquea pero queda registrada (base legal, DPA, Data Subject Requests Art. 15-22, consentimiento
  versionado, retención, DPIA, reporting RoPA Art. 30). La auditoría es **metadata-only**: jamás se
  persiste texto de prompt ni PII cruda.
- **Gobernanza de costes** 🟢 — ninguna request pasa sin una key válida (fail-closed). Presupuestos
  en USD con corte **HTTP 402 pre-request** y contabilidad post-request, en doble capa
  persona → grupo, con techo duro y límites rpm/tpm como red de seguridad. El enforcement es
  **post-hoc, no "tiempo real"**: una request en curso puede sobrepasar el límite antes del corte.
  El enforcement de presupuesto sobre respuestas en streaming es 🔵 roadmap.
- **Optimización de contexto** 🟢 — compresión determinista de prompts que reduce tokens sin
  corromper URLs, código ni placeholders; el ahorro es medible y se netea del presupuesto.
- **Multi-tenant** 🟢 — aislamiento por tenant desde el esquema de datos, reforzado con Row-Level
  Security en PostgreSQL. Jerarquía: **Tenant (empresa) → Grupo → Cliente (persona) → Conexión
  (key por herramienta)**. El mismo código corre single-tenant on-premise y multi-tenant cloud.
- **White-label** 🟢 — el producto se revende bajo la marca del distribuidor. Cada instalación es
  **configuración + seed** sobre el mismo código base, nunca un fork. La verificación de licencia es
  **100 % offline**: el producto jamás "llama a casa", apto para air-gap.

Las herramientas cliente (CLIs y editores con base URL configurable, extensión de navegador para
asistentes web) se conectan como **superficies de integración** — el detalle por herramienta y la
matriz de compatibilidad viven en [Integraciones](../integrations/index.md).

## El pipeline por request

Cada request atraviesa cinco capas, siempre en el mismo orden:

```text
 herramienta                                                        usuario
     │                                                                 ▲
     ▼                                                                 │
┌──────────┐  ┌──────────────┐  ┌────────────┐  ┌───────────────┐  ┌────────┐
│ 1 MASKING│─►│ 2 OPTIMIZACIÓN│─►│ 3 COMPLIANCE│─►│ 4 ROUTING/LLM │─►│ 5 UNMASK│
└──────────┘  └──────────────┘  └────────────┘  └───────────────┘  └────────┘
  PII → placeholders   menos tokens    bloquea/registra   proveedor LLM    valores reales
```

**1. Masking** 🟢 — se detecta la PII/PHI del prompt y se sustituye por placeholders atómicos
(`[PERSON_0]`, `[DNI_0]`…), con un mapa reversible que queda dentro de la plataforma.
*Garantiza*: el motor del gateway y el proveedor LLM solo ven placeholders, nunca el dato real.
Es la capa más fuerte del producto y por eso corre **primero**.

**2. Optimización** 🟢 — compresión determinista del contexto (consciente de tokens) con caché en
Redis y guardia de reversión. Corre **después** del masking porque los placeholders son tokens
intocables: la compresión jamás los corrompe, ni a URLs ni a bloques de código. No existe compresión
asistida por LLM — no se gastan tokens para ahorrar tokens.
*Garantiza*: menos coste por request sin pérdida de integridad del prompt.

**3. Compliance** 🟢 — el gate duro: prácticas prohibidas del AI Act Art. 5 → **HTTP 400**;
entidades configuradas como `BLOCK` y secretos/credenciales → bloqueo; violación de residencia EU en
el flujo proxy → **HTTP 503**; presupuesto agotado → **HTTP 402**. Lo que no bloquea, queda
registrado como evidencia auditada (metadata-only). La política se resuelve de forma **jerárquica**:
tenant → grupo → cliente → conexión.
*Garantiza*: lo prohibido no sale; lo permitido deja rastro auditable.

**4. Routing / LLM** 🟢 — el **motor del gateway** resuelve la identidad de la request (virtual key
→ tenant/cliente/herramienta, fail-closed: sin key válida no hay request), y rutea al proveedor LLM
configurado por el operador (**BYOK**: OpenAI, Anthropic, Azure OpenAI, Google Gemini, modelos
locales tipo Ollama/vLLM, y decenas más — agregar un proveedor es configuración, no código). La
residencia EU es el default del flujo proxy; techo de gasto y rpm/tpm actúan como backstop.
*Garantiza*: cada request viaja con identidad, límites y destino controlados.

**5. Unmask** 🟢 — la respuesta del proveedor vuelve con los placeholders, y la plataforma restaura
los valores reales usando el mapa reversible — incluido el camino de streaming (SSE) en la
superficie de passthrough.
*Garantiza*: el usuario ve datos reales que el proveedor nunca vio; la UX no se rompe.

### Observabilidad capa a capa

Cada request emite su **`pipeline_metadata`**: qué detectó el masking (tipos de entidad y scores,
nunca el contenido), cuánto ahorró la optimización, qué veredicto dio compliance, a qué modelo se
ruteó y cuánto costó, y el timing de cada capa. Son **datos reales por request**, no una animación:
alimentan la auditoría, el monitor en vivo y el **Playground** del panel (la vitrina interactiva
donde se ve el pipeline actuar paso a paso). El detalle operativo está en
[Operaciones](../operations/index.md).

## Arquitectura en containers

El producto se despliega como un conjunto de **containers separados** — mismo código y mismas
imágenes en cloud y on-prem; lo que cambia es dónde viven los servicios de datos:

| Container | Rol | Cloud (SaaS multi-tenant) | On-prem / air-gapped (single-tenant) |
|---|---|---|---|
| **Backend API** | La puerta única (`/api/v1/gw` y `/gw/*`), políticas, compliance, presupuestos, auditoría, licencia | Container | Container |
| **Motor del gateway** | Identidad fail-closed, guardrails, routing a proveedores LLM, límites rpm/tpm | Container | Container |
| **Frontend** | Panel de administración, Playground, monitor en vivo | Container | Container |
| **Sitio de docs** | Esta documentación — imagen `basa-docs:<marca>-<versión>`, 100 % estática, cero egress | Container | Container (viaja dentro del bundle) |
| **PostgreSQL** | Estado: tenants, políticas, presupuestos, auditoría (con Row-Level Security) | Servicio gestionado (región EU por defecto) o container | Container con volumen durable |
| **Redis** | Caché de optimización y contadores | Servicio gestionado o container | Container |

Puntos clave del modelo de despliegue:

- **Un solo codebase, dos perfiles**: el perfil de desarrollo (bind-mounts, recarga en caliente,
  secretos de juguete) jamás sale a un cliente; lo único que se entrega son las **imágenes de
  producción** (código horneado, non-root, sin toolchain).
- **On-prem / air-gapped**: la instalación viaja como un bundle (tarball con las imágenes, perfil y
  branding). El único egress necesario es hacia los proveedores LLM; con un **modelo local**
  (Ollama/vLLM) el egress es **cero**. La licencia se verifica offline.
- **Cloud**: el módulo de infraestructura como código incluido provisiona red, base de datos, caché,
  cómputo, secretos e ingress, con **EU como región por defecto**.

El paso a paso de instalación (cloud, on-prem y air-gap) está en
[Install / Deploy](../install-deploy/index.md).

## Audiencias de esta documentación

| Audiencia | Qué necesitás | Empezá por |
|---|---|---|
| **Distribuidor** | Instalar el producto con tu marca y entregarlo a tus clientes | [Install / Deploy](../install-deploy/index.md) |
| **Operador** | Administrar tenants, personas, políticas y presupuestos del día a día | [Administración](../administration/index.md) y [Operaciones](../operations/index.md) |
| **Integrador** | Conectar herramientas de IA al gateway y conocer la matriz de compatibilidad | [Integraciones](../integrations/index.md) |
| **DPO / Compliance** | Evidencia GDPR / EU AI Act, auditoría y derechos de los interesados | [Compliance](../compliance/index.md) |
