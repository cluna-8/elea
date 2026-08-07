# Tech Tree Guardian — Fase 0 → 1 → 2

**Departamento**: Guardian App Ecosystem (JF) · **Fecha**: 2026-08-05 · **Estado**: propuesta para la reunión de departamentos (betting del ciclo 1)
**Presentación**: artifact «Tech Tree Guardian» (mismo contenido que este archivo; este markdown es la fuente de verdad).
**Companion de**: `specs/ROADMAP-guardian.md` (estado por spec) · ArquitectOverview (mapa técnico, **HISTÓRICO** pre-mudanza — el vigente es EcosystemOverview) · ManosALaObra v4 (metodología).

---

## La lógica (tech tree)

Como en un juego: cada **nodo** es una capacidad concreta del producto, cada **fase** se gana completando sus nodos, y para pasar de fase hay que aprobar un **examen**. No se avanza declarando — se avanza demostrando.

**MVP de septiembre = Fase 0 completa y examinada**: un partner instala Guardian, da de alta a su cliente y configura todo solo — modelos, precios, roles, SSO, niveles de compliance — y el producto aguanta **500 usuarios simultáneos con pérdida de auditoría cero**. Todo por API/BYOK: la extensión de navegador no hace falta para cumplir la promesa.

Leyenda: ✅ hecho (funciona en `main`) · 🔨 por construir · 🆕 nuevo (sin spec) · ⚖️ decisión (charla, no código) · 🔒 bloqueado (se abre pasando gates).

---

## FASE 0 — La promesa · «¿hace lo que dice que hace?»

La razón por la que un cliente paga: «controlo los costos, veo todo lo que hacen mis empleados con la IA, y cumplo RGPD — sin frenarlos». Alcance: **API/BYOK, sin extensión**. Cuatro ramas; la fase se completa cuando TODOS los nodos están en verde **y** los tres gates del examen pasaron.

### 🛡️ Rama: Compliance & auditoría

- ✅ **Registro durable de todo** — cada petición y cada bloqueo queda en base de datos: quién, qué modelo, qué capa bloqueó y por qué; sobrevive reinicios. *(spec 031)*
- 🔨 **Masking que avisa cuando se degrada** — hoy, si el analizador NLP se cae, el sistema pasa a regex EN SILENCIO, y el regex etiqueta mal (un IBAN troceado sale como "teléfono"); el cliente cree que tiene NLP y nadie se entera. Avisar en voz alta + arreglar etiquetas. *(#63, #64 — P1 seguridad, encargo Cristian)*
- 🔨 **Export de datos RGPD (DSAR)** — «dame todo lo que tienen sobre mí» (Art. 15/20); el botón existe pero devuelve error 500 a todos los roles. *(#62)*
- 🔨 **Retención que borra de verdad** — hoy se puede configurar «guardar 90 días»… y nada borra al día 91; la purga tiene que existir para que la promesa RGPD sea cierta. *(spec 018)*
- ⚖️ **¿Qué hace el firewall si NO puede auditar?** — hoy el default es fail-open (`BASA_AUDIT_FAIL`). **Dirección acordada en el weekly 05-ago: política por nivel de riesgo/rol del usuario** (alta prioridad corta, baja prioridad sirve) — falta especificarla (spec corta, encaja con las capas de la 027). Pendiente conexo: ¿se auditan también los errores?

### 💰 Rama: Control de costos

- ✅ **Presupuestos que cortan** — al agotar el presupuesto de una key, el corte es ANTES de llamar al proveedor (402). *(#76)*
- ✅ **Costo por petición y por usuario** — cada request registra su costo; el panel agrega por usuario/key/modelo; el modelo local computa 0. *(spec 030)*
- 🔨 **Tarifario centralizado** — el alcance creció en el weekly: además de los precios que faltan (gpt-5.5, gpt-4.1-mini…), conectar una **fuente pública de precios de modelos** para actualización sin mantenimiento manual por proveedor + visualización en el panel. *(#73 ampliado)*
- 🆕 **Presupuestos con alertas y flexibilidad** — niveles de alerta estilo AWS + presupuesto variable (hasta +10%) para roles de alto consumo, como política básica de control; prioridad del gasto personal antes que el grupal. *(weekly 05-ago, sin spec)*

### 🧑‍💼 Rama: El partner configura TODO solo

- ✅ **Alta de cliente, usuarios y keys por UI** — verificado en el piloto de la Cámara, sin tocar consola.
- 🔨 **Alta de modelos sin reiniciar (y completa)** — hoy dar de alta un modelo pide reiniciar el motor a mano (la Cámara lo sufrió); el motor debe recargar solo, y el modelo nuevo (GPT-5, Fable, lo que venga) entrar a su **cadena de fallback y al tarifario** sin ediciones a mano. *(spec 033 + #73)*
- ✅ **Fallback por modelo** — cada modelo tiene su cadena de respaldo configurable por UI: si el proveedor falla, la request se sirve por el siguiente; verificado en el test integral del piloto. **La promesa de Fase 0 rutea con esto** — el ruteo semántico es mejora de Fase 1 (decisión JF 05-ago). *(spec 010 · panel Modelos)*
- 🔨 **Rol Auditor (honesto)** — el panel ya gatea por rol (admin, developer, compliance_officer, usuario final), pero la ficha del auditor promete una red que no cubre costos/consumo/reportes; la 034 lo hace verdad: VE todo lo de compliance, no toca nada. Rama quickwin arrancada (3 commits). *(spec 034)*
- 🆕 **Rol Lectura** — solo-lectura general del panel; nombrado hoy, sin spec; se especifica junto a la 034.
- 🔨 **Login con Microsoft y Google (SSO escalón 1)** — para clientes que viven en Microsoft 365 / Google Workspace: entrar con la cuenta corporativa (OIDC). Hoy el SSO es vitrina mock. **Escalonado**: Entra + Google ahora; escalón 2 (post-Fase 0): SAML, otros IdP y **Active Directory + segmentación por roles/grupos** — consulta crítica de cliente identificada en el weekly. *(017 parcial)*
- 🆕 **Carga masiva de usuarios + invitaciones** — alta por lotes (hoy es una por una, no escala a 125+) y envío de correos de activación de cuenta. *(weekly 05-ago, sin spec)*
- 🆕 **Reinicio de contenedores desde la UI** — botón para reiniciar servicios sin scripts externos: alivio inmediato del dolor que la 033 elimina de raíz; se especifica junto a la 033. *(weekly 05-ago)*
- 🔨 **Los huecos que revele Evidenze** — las preguntas de Cristian al wizard en el ensayo dicen qué configuración aún NO se puede hacer solo; cada hueco se vuelve nodo.

### 💪 Rama: Aguanta gente

- 🔨 **El instrumento de medir (harness)** — banco de pruebas de carga que simula usuarios reales (chat + extensión + coding tools) contra el stack de producción; diseño en papel (k6+xk6-sse), hay que construirlo. Complemento acordado en el weekly: validación con modelos básicos reales vía **API keys de OpenRouter** además del stub. Sin esto, los gates son opiniones. *(spec nueva vía speckit)*
- 🔨 **Fix del pool que se cuelga** — en la sede, un puñado de peticiones largas simultáneas colgó el producto ~10 min (incidente 30-jul); falta tope de concurrencia + timeout anti-inanición.
- 🔨 **Streams largos que no se cortan** — si el modelo local "piensa" >60 s sin emitir texto, la respuesta corta con error, justo cuando hay carga (gap read 60s < router 120s). Conexo del weekly: **política de aviso al usuario** cuando un mensaje muere por demora excesiva (la define Cristian; el mecanismo es nuestro).
- 🆕 **Panel de rendimiento** — tablero de métricas de rendimiento del sistema y medias de los modelos locales (latencias, throughput); se alimenta de lo que el harness ya mide. *(weekly 05-ago, sin spec)*
- 🔨 **Perillas de escala** — hoy todo es instancia única dimensionada para 10-15 usuarios: 1 proceso NLP, 1 motor, 2 workers backend, sin límites de recursos. Réplicas/workers/backpressure/límites, ajustados con datos del harness. *(dossier de capacidad 04-ago)*
- 🔨 **Colas de la gobernanza (027)** — la gobernanza configurable funciona; quedan T024/T025 (plano motor), T034 (quickstart e2e) y T036 para cerrarla sin asteriscos.

### 🎓 El examen de la Fase 0 — gates de carga

La Fase 0 **no se declara lista sin pasar los tres**. Hoy no pasaríamos ni el primero — saberlo con un número es el primer entregable.

| Gate | Qué prueba |
|---|---|
| **125** | Paridad con la sede real (~125 beta testers Cámara): 30 min sostenido, mezcla realista, corpus PII en español. |
| **250** | + login storm «lunes 9:00»: todos entran en una ventana de 10 minutos. |
| **500** | + 1 hora sostenida, pico del doble, recuperación. **El número del MVP.** |

**SLO de oro en los tres**: Δ pérdida de auditoría = 0 (contador 031 en `/health`) · reconciliación de filas · 0 entidades PII crudas al proveedor · 100% de bloqueos con su fila durable. *Un producto de compliance que pierde registros a 400 usuarios no está degradado — está mintiendo.*

---

## 🔒 FASE 1 — Integraciones · «¿me sigue a donde ya trabajo?» *(se desbloquea con gates verdes por delante de plan)*

- **Extensión multi-browser**: 🔒 Firefox (#65, hoy solo Chromium) · 🔒 Edge (Chromium: casi gratis) · 🔒 superficie ChatGPT web (hoy validado: Claude.ai) · ✖ Safari descartado por ahora (App Store, packaging propio; se reevalúa con demanda).
- **IDEs y CLIs**: 🔒 cerrar los parciales de la matriz 019 (Claude Code ✔ · Aider ✔ · VS Code/Cursor parcial · Codex CLI ✗). La matriz es la fuente de verdad.
- **Más proveedores**: 🔒 Gemini (#58, único grande que necesita adapter propio) · 🔒 Kimi/DeepSeek/Grok —confirmado Grok de xAI en el weekly— (OpenAI-compatibles: config + precios + fila en matriz, costo bajo por proveedor) · 🔒 **OpenRouter como agregador** (candidato del weekly: centraliza contratos legales y acceso a N modelos con una key).
- **Ruteo inteligente**: 🔒 **auto-router semántico, garantizado** — ya existe y funciona (030: panel «Ruteo inteligente» + modo Automático del portal); lo que va aquí es su **garantía con modelos nuevos** (un modelo recién instalado entra a las categorías del router y queda bien evaluado, opt-in por cliente). **Decisión JF 05-ago: la promesa de Fase 0 rutea con fallback; lo semántico se garantiza en Fase 1.**

## 🔒 FASE 2 — UI de cliente propia · «¿puedo vivir dentro de Guardian?»

**El chat que damos nosotros — y la v0 YA EXISTE**: hoy un usuario normal (rol usuario final) que entra a Guardian ve un **portal de chat limpio** (`UserPortal`: selector de modelo + modo Automático de la 030), jamás la consola de administración. Fase 2 = hacerlo crecer: branding por partner, historial, lo que el mercado pida. Efecto estratégico: para el cliente que acepte chatear dentro de Guardian, **la extensión pasa a ser opcional**.

## Coherencia: los 14 módulos ↔ el árbol

Qué ES cada módulo (stack, soporte, frontera con Factory) está en `tech-team/EcosystemOverview-BasaGuardian.html`; este árbol dice dónde está SU trabajo: Gateway (✅ · F0 streams/perillas) · Motor (F0 033 · ✅ fallback) · PII (F0 #63/#64) · Extensión (F1 multi-browser) · 3rd-party (F1 matriz) · Panel (✅ 11 páginas con roles · F0 huecos wizard) · Playground/monitor (✅) · Auto-router (✅ existe · F1 garantía) · Auditoría (F0: DSAR/018/⚖️ fail-open) · Presupuestos (✅ · F0 #73) · Gobernanza (✅ · F0 colas 027) · Multi-tenant (✅) · Licensing runtime (✅; emisión=Factory) · Docs contenido (✅; build=Factory).

---

## Los 3 ciclos — validados en el weekly 05-ago (se recorta alcance, nunca la fecha)

| Ciclo | Fechas | Apuestas |
|---|---|---|
| **1** | 11–21 ago | «El masking no miente» (#63/#64, + reglas regex por región del incidente VPN) · «El examen existe» (harness + fix del pool + gates 125 y 250 **medidos**, pasen o no) |
| **2** | 24 ago–4 sep | «Opera solo» (033 + botón restart UI + streams sin cortes + colas 027) · «Aguanta 250→500» (perillas con datos del gate 125) · DSAR #62 |
| **3** | 7–18 sep | «Roles y puertas» (034 + rol Lectura + SSO Microsoft/Google) · «RGPD completo» (018 — verificar purga real al día 91) · **gate 500 verde** + margen |

Nodos de Fase 1/2 solo entran a un ciclo si los gates van verdes por delante de plan.
**Modo de ejecución**: JF de vacaciones desde el 06-ago — el ciclo 1 lo ejecuta Claude (Fable 5) en autonomía sobre este roadmap, con JF monitoreando y aprobando desde el móvil. El trabajo no para.

## Decisiones del weekly 05-ago (cerradas)

- **Política de auditoría**: por nivel de riesgo/rol del usuario (falta spec corta) — deja de ser pregunta abierta.
- **Licencias y firmas**: se mantienen SIMPLES en esta fase (estándar clave pública + grace + bloqueos, como está); la complejidad extra se delega a capas externas.
- **Flujo de trabajo**: main + tags por ciclo de 2 semanas; ramas cortas por PR; posibilidad de repos satélite (navegador/asistente) solo si hace falta.
- **Soporte**: primera línea = rol Operaciones (personas intercambiables, se documenta el rol, no el nombre) → triage instalación vs producto → issue por depto.
- **Evidenze**: preparar el entorno + documentar para install autónoma + pruebas internas antes del despliegue real.

## Preguntas abiertas

- **La frontera de los Dockerfiles prod** (audit 07-ago): viven en `deploy/` (Falime) pero hornean código Guardian con contexto en la raíz del repo (`deploy/docker/backend.prod.Dockerfile` COPY backend/src…). Antes de la mudanza hay que decidir: (a) Guardian publica imágenes versionadas y Factory solo consume tags, o (b) Factory consume un artefacto de release con fuentes. Decisión JF+Falime, documentar en `deploy/ROADMAP-factory.md`.

1. **Licencia de test de 500 seats** para el harness (la de Cámara es de 300): emisión Falime, gate Cristian si toca custodia.
2. **Costura secrets.env**: los secretos del stack viajan en claro en el bundle; el fix (generarlos en sede) toca bundle (Falime) y puede necesitar código de producto — coordinar.
3. **Especificación de la política de auditoría por riesgo/rol** (la dirección ya está decidida): dónde vive — ¿capa de la 027 o spec propia? + ¿se auditan errores?

## Fuentes

Fact-check nocturno 04→05-ago (95 claims verificados sobre ArquitectOverview + dossier de capacidad con evidencia `file:line`) · incidente pool sede 30-jul · encargo de Cristian (Slack 05-ago) · decisiones JF 05-ago (SSO escalonado, 018 in, UI = chat de usuario, Safari out, tech tree como formato).
