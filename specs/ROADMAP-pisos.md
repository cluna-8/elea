# Tech Tree Guardian — Fase 0 → 1 → 2

**Departamento**: Guardian App Ecosystem (JF) · **Fecha**: 2026-08-15 · **Estado**: vigente — actualizado con los resultados del **examen 125** (gate PASS), el re-corte de ciclos al 5-SEP sellado por JF y los **2 nodos nuevos sellados el 12-ago** (región de compliance · compresión 023)
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

**Conteo del avance** (el denominador vivo lo lleva `tech-team/progress.html`): hoy **26 nodos + 3 gates = 29 unidades** (24→26 el 12-ago al entrar región de compliance y compresión 023, decisión JF). No todo bullet de este árbol suma al denominador: los 🩺 hallazgos remiten a nodos ya contados, y el módulo 036 computa a través de sus nodos (región #174/#137 · content filter #178).

### 🛡️ Rama: Compliance & auditoría

- ✅ **Registro durable de todo** — cada petición y cada bloqueo queda en base de datos: quién, qué modelo, qué capa bloqueó y por qué; sobrevive reinicios. **Verificado bajo carga real el 12-ago**: 30 min sostenidos, paridad exacta 1506 eventos = 1506 filas, Δ pérdida = 0. *(spec 031 · evidencia `tech-team/examenes/20260812/`)*
- ✅ **Masking que avisa cuando se degrada** — hecho y endurecido: paridad NLP en `/gw` + `nlp_fail_mode` gobernable (#63, PR #97) + paracaídas regex honesto con etiquetas correctas (#64, PR #111) + cadena de hardening #98/#104/#105/#106/#119/#124. **Verificado bajo carga**: 0 canarios PII crudos al proveedor sobre corpus de 64 en el gate 125. *(constitución 2.2.0, D10)*
- 🔧 **Políticas por cliente/país (036)** — módulo de Cristian en PRs (#141 spec → #137 region por tenant → #143 content filter → #147 API+pantalla+docs); freeze del examen levantado, pasan por gate adversarial en orden. Decisiones de superficie ya selladas por JF (12-ago): superficie aprobada tal cual, solo admins aprueban políticas, en paralelo best-effort.
- ✅ **Export de datos RGPD (DSAR)** — «dame todo lo que tienen sobre mí» (Art. 15/20): el export dejó de devolver 500 a todos los roles (faltaba `cast(User.id, String)`), verificado con test e2e de marca única contra Postgres real. *(#62 · PR #217, `a0023bd`)*
- ✅ **Retención que borra de verdad** — la purga real existe: al día 91 el contenido clasificado `prompt_content` se borra solo (job + tiers estricto/estándar + scheduler APAGADO por default vía `BASA_PURGE_ENABLED`), con rastro auditable metadata-only. *(spec 018 · PR #214, `61089b1`)*
- ⚖️ **¿Qué hace el firewall si NO puede auditar?** — hoy el default es fail-open (`BASA_AUDIT_FAIL`). **Dirección acordada en el weekly 05-ago: política por nivel de riesgo/rol del usuario** (alta prioridad corta, baja prioridad sirve) — falta especificarla (spec corta, encaja con las capas de la 027). Pendiente conexo: ¿se auditan también los errores?

### 💰 Rama: Control de costos

- ✅ **Presupuestos que cortan** — al agotar el presupuesto de una key, el corte es ANTES de llamar al proveedor (402). *(#76)*
- ✅ **Costo por petición y por usuario** — cada request registra su costo; el panel agrega por usuario/key/modelo; el modelo local computa 0. *(spec 030)*
- 🔨 **Tarifario centralizado** — el alcance creció en el weekly: además de los precios que faltan (gpt-5.5, gpt-4.1-mini…), conectar una **fuente pública de precios de modelos** para actualización sin mantenimiento manual por proveedor + visualización en el panel. *(#73 ampliado)*
- 🆕 **Presupuestos con alertas y flexibilidad** — niveles de alerta estilo AWS + presupuesto variable (hasta +10%) para roles de alto consumo, como política básica de control; prioridad del gasto personal antes que el grupal. *(weekly 05-ago, sin spec)*
- 🔨 **Compresión de tokens en el plano real (023)** — la cascada `compression_mode` por fin consume en el plano firewall. **Entra a Fase 0 por decisión de JF (12-ago)**: se construye en C2 y se mide en el examen de features de La ITV (#170). *(spec 023 · #16)*

### 🧑‍💼 Rama: El partner configura TODO solo

- ✅ **Alta de cliente, usuarios y keys por UI** — verificado en el piloto de la Cámara, sin tocar consola.
- 🔨 **Alta de modelos sin reiniciar (y completa)** — hoy dar de alta un modelo pide reiniciar el motor a mano (la Cámara lo sufrió); el motor debe recargar solo, y el modelo nuevo (GPT-5, Fable, lo que venga) entrar a su **cadena de fallback y al tarifario** sin ediciones a mano. *(spec 033 + #73)*
- ✅ **Fallback por modelo** — cada modelo tiene su cadena de respaldo configurable por UI: si el proveedor falla, la request se sirve por el siguiente; verificado en el test integral del piloto. **La promesa de Fase 0 rutea con esto** — el ruteo semántico es mejora de Fase 1 (decisión JF 05-ago). *(spec 010 · panel Modelos)*
- 🔨 **Rol Auditor (honesto)** — el panel ya gatea por rol (admin, developer, compliance_officer, usuario final), pero la ficha del auditor promete una red que no cubre costos/consumo/reportes; la 034 lo hace verdad: VE todo lo de compliance, no toca nada. Rama quickwin arrancada (3 commits). *(spec 034)*
- 🆕 **Rol Lectura** — solo-lectura general del panel; nombrado hoy, sin spec; se especifica junto a la 034.
- 🔨 **Login con Microsoft y Google (SSO escalón 1)** — para clientes que viven en Microsoft 365 / Google Workspace: entrar con la cuenta corporativa (OIDC). Hoy el SSO es vitrina mock. **Escalonado**: Entra + Google ahora; escalón 2 (post-Fase 0): SAML, otros IdP y **Active Directory + segmentación por roles/grupos** — consulta crítica de cliente identificada en el weekly. *(017 parcial)*
- 🆕 **Carga masiva de usuarios + invitaciones** — alta por lotes (hoy es una por una, no escala a 125+) y envío de correos de activación de cuenta. *(weekly 05-ago, sin spec)*
- 🆕 **Reinicio de contenedores desde la UI** — botón para reiniciar servicios sin scripts externos: alivio inmediato del dolor que la 033 elimina de raíz; se especifica junto a la 033. *(weekly 05-ago)*
- 🔨 **Región de compliance elegida por el partner** — la región vive en el **TENANT** (canon de almacenamiento) y el wizard es la capa UX que la escribe al instalar; se activan solo los recognizers de esa región para que el NLP tenga menos ruido. **Nodo nuevo sellado por JF el 12-ago.** *(#174 + #137)*
- 🔨 **Los huecos que revele Evidenze** — las preguntas de Cristian al wizard en el ensayo dicen qué configuración aún NO se puede hacer solo; cada hueco se vuelve nodo.

### 💪 Rama: Aguanta gente

- ✅ **El instrumento de medir (harness)** — construido, en `main` y **estrenado en examen real** (spec 035, PR #122 + corridas reales #163/#164): k6 + stub proveedor con detector de canarios, población sembrada por las APIs del producto, reconcile fail-closed, fingerprint firmado, prueba de humo pre-carga. Se invalidó a sí mismo dos veces el 12-ago antes que certificar en falso — el estándar funcionando. Deuda propia del instrumento consolidada en #168 (ciclo 250).
- ✅ **Fix del pool que se cuelga** — tope de concurrencia + queue-timeout → 503 rápido auditado (`X-Basa-Rejected`, PR #135) + perillas cabladas en compose/bundle + límites del deployment ollama (`max_parallel_requests: 20`, `num_retries: 0`, PR #159, ADR-0003). **Verificado bajo overload real** (rampa 12-ago): 193 rechazos ordenados, sin cuelgue, el incidente 30-jul no se repitió ni a 50× la carga de sede. Refinamiento a C2: rechaza lento (p50 6 s hasta el 503, espera toda la cola) — evaluar load shedding temprano (#169).
- 🔧 **Streams largos que no se cortan** — gap read 60s<router 120s cerrado en #135/#159 (`BASA_GW_BYOK_READ_TIMEOUT_SECONDS`); queda la fuga de turno en cancelación temprana + acloses (**PR #162, ronda final de fixes en curso, equipo Jeff**; cerrar ANTES de gates 250/500 — #150). El gate 125 midió 0 cortes de stream sobre 112 streams. Conexo: política de aviso al usuario (Cristian) sigue pendiente.
- 🆕 **Panel de rendimiento** — tablero de métricas de rendimiento del sistema y medias de los modelos locales (latencias, throughput); se alimenta de lo que el harness ya mide. *(weekly 05-ago, sin spec)*
- 🔨 **Perillas de escala** — las de **admisión** ya están cabladas y medidas (#135/#159); quedan réplicas NLP/motor/workers + límites de recursos. **El examen bajó el riesgo**: la rodilla de una ccx33 está entre 10× y 25× la carga de sede — 250/500 caen holgados; el dimensionamiento fino puede BAJAR de instancia (encargo a La ITV: instancia por tier, sellado por JF 12-ago). *(dossier 04-ago + rampa `20260812-rampa-03-diagnostico`)*
- 🔨 **Colas de la gobernanza (027)** — la gobernanza configurable funciona; quedan T024/T025 (plano motor), T034 (quickstart e2e) y T036 para cerrarla sin asteriscos.
- 🩺 **Hallazgos del examen sobre esta rama** (con evidencia de run): #167 fail-closed del NLP bloquea tráfico legítimo en **arranque-en-frío + ráfaga de logins** (el "lunes 9am" post-despliegue; confirmar mecanismo ANTES del gate 250, equipo Jeff) · #157 el 402 de presupuesto responde sin fila durable (en curso, equipo Jeff) · #165/#166 rastro y marcador machine-readable de bloqueos (C2).

### 🎓 El examen de la Fase 0 — gates de carga · **1/3 ✅**

La Fase 0 **no se declara lista sin pasar los tres**. Canon sellado (08-ago): correr el examen ≠ Fase 0 concluida — los gates son el pilar de ESCALA del DoD, necesarios no suficientes.

| Gate | Qué prueba | Estado |
|---|---|---|
| **125** | Paridad con la sede real (~125 beta testers Cámara): 30 min sostenido, mezcla realista, corpus PII en español. | ✅ **PASS 12-ago** (run `20260812-g125-02`, main `52e694b`): 4/4 SLOs de oro · chat p95 **151 ms** punta a punta · coding TTFT 650 ms (overhead ~50 ms), 0 cortes · evidencia firmada en `tech-team/examenes/20260812/` |
| **250** | + login storm «lunes 9:00»: todos entran en una ventana de 10 minutos. | 🔓 C2 — **des-riesgado** (2× cae en zona sana de la rodilla medida); corre sobre instancia right-sized + #167 confirmado antes |
| **500** | + 1 hora sostenida, pico del doble, recuperación. **El número del MVP.** | 🔓 C2 — des-riesgado (4× ídem) |

**SLO de oro en los tres**: Δ pérdida de auditoría = 0 (contador 031 en `/health`) · reconciliación de filas · 0 entidades PII crudas al proveedor · 100% de bloqueos con su fila durable. *Un producto de compliance que pierde registros a 400 usuarios no está degradado — está mintiendo.* **Los cuatro se midieron por primera vez el 12-ago y los cuatro dieron verde.**

**Lo que el examen enseñó** (12-ago, tres runs + rampa diagnóstica, costo total <3€ en infra efímera destruida y verificada):
- **Capacidad**: rodilla de la ccx33 entre **10× y 25×** la carga de sede; saturación plena a 50×. El drill de saturación cerró INVALID *a propósito* (la carga ×3 no inmutó al SUT: 0 rechazos) — la guarda que se niega a certificar sin ejercitar la defensa. **Encargo sellado por JF**: La ITV deriva la instancia por tier del baseline medido y provisiona acorde al test; espejo de sede solo como validación. Es además entregable de producto: "qué hardware para N usuarios", medido.
- **La defensa de admisión C1 funciona bajo fuego real** (rechazos ordenados, sin cuelgue) pero rechaza lento → #169 (load shedding temprano, C2).
- **Hallazgos de producto con evidencia de run**: #167 (NLP frío+ráfaga) · #157 (402 sin fila) · #165 (422 sin rastro) · #166 (marcador machine-readable de bloqueo).
- **Lo que el examen NO midió a propósito** → #170 (roadmapear en C2): presupuestos en DINERO real, compresor de tokens bajo carga, routing/fallback con caída forzada de proveedor (prerrequisito: #160, hoy un fallback sustituye en silencio).
- **Deuda del propio instrumento** → #168 (ciclo 250; incluye archivar métricas de recursos del SUT en el paquete de evidencia).

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

## Los ciclos — RE-CORTE SELLADO por JF el 12-ago: **TODO Fase 0 listo el 5-SEP** («por las dudas», decisión 09-ago; las fechas de C3 del plan original quedan obsoletas)

| Ciclo | Fechas | Apuestas | Estado |
|---|---|---|---|
| **1** | 11–21 ago | «El masking no miente» (#63/#64) · «El examen existe» (harness + fix del pool + **gate 125 medido**) | ✅ **Alcance cerrado el 12-ago** (día 2 de 9): todo en `main` y el gate 125 PASS. Los días restantes absorben el arranque de C2. |
| **1→2** | 13–21 ago | Colchón ganado: cola técnica de Jeff (#162 streams → #157 402-durable → #167 NLP-frío) · gates del stack 036 de Cristian · **specs de identidad y retención** (017 SSO + 034+Lectura + 018 + DSAR #62, por SDD) para que C2 construya con planos | 🔄 en curso |
| **2** | 24 ago–4 sep | «Opera solo» (033 + botón restart UI + colas 027) · «Roles y puertas» (034 + rol Lectura + SSO Microsoft/Google) · «RGPD completo» (018 purga real + DSAR #62) · **gates 250 y 500 verdes** sobre instancia right-sized · refinamientos del examen (#169, #166, #165) · examen de features #170 | absorbe TODO el alcance del viejo C3 |

Nodos de Fase 1/2 solo entran a un ciclo si los gates van verdes por delante de plan.
**Camino crítico al 5-SEP** (lectura del 12-ago): la capacidad dejó de ser el riesgo (medida y sobrada) — el riesgo es que **identidad y ciclo de vida del dato (SSO, roles, 018, DSAR) tienen 0 líneas escritas** y deben caber enteros en C2. Por eso las specs se escriben YA, en el colchón de C1.
**Modo de ejecución**: JF dirige (decisiones selladas al día, cola vacía al 12-ago); el manager (Fable 5) orquesta equipos — Jeff (código de producto), La ITV (examen/capacidad), Cristian (seguridad/036), DevOps (plataformas) — bajo la política de merge del tren autónomo (CI verde por-job + gate adversarial APTO + decisiones de producto selladas ⇒ merge).

## Decisiones del weekly 05-ago (cerradas)

- **Política de auditoría**: por nivel de riesgo/rol del usuario (falta spec corta) — deja de ser pregunta abierta.
- **Licencias y firmas**: se mantienen SIMPLES en esta fase (estándar clave pública + grace + bloqueos, como está); la complejidad extra se delega a capas externas.
- **Flujo de trabajo**: main + tags por ciclo de 2 semanas; ramas cortas por PR; posibilidad de repos satélite (navegador/asistente) solo si hace falta.
- **Soporte**: primera línea = rol Operaciones (personas intercambiables, se documenta el rol, no el nombre) → triage instalación vs producto → issue por depto.
- **Evidenze**: preparar el entorno + documentar para install autónoma + pruebas internas antes del despliegue real.

## Preguntas abiertas

- **La frontera de los Dockerfiles prod** (audit 07-ago): viven en `deploy/` (Falime) pero hornean código Guardian con contexto en la raíz del repo (`deploy/docker/backend.prod.Dockerfile` COPY backend/src…). Antes de la mudanza hay que decidir: (a) Guardian publica imágenes versionadas y Factory solo consume tags, o (b) Factory consume un artefacto de release con fuentes. Decisión JF+Falime, documentar en `deploy/ROADMAP-factory.md`.

1. ~~**Licencia de test de 500 seats** para el harness~~ — **RESUELTO (11-ago)**: keypair descartable generado al provisionar el SUT + licencia efímera propia (muere con la infra); la privada `basa-dev-2026b` queda SOLO para installs de cliente. Verificado en el examen 125 (fingerprint firmado con licencia real de test de 130 seats).
2. **Costura secrets.env**: los secretos del stack viajan en claro en el bundle; el fix (generarlos en sede) toca bundle (Falime) y puede necesitar código de producto — coordinar.
3. **Especificación de la política de auditoría por riesgo/rol** (la dirección ya está decidida): dónde vive — ¿capa de la 027 o spec propia? + ¿se auditan errores?

## Fuentes

Fact-check nocturno 04→05-ago (95 claims verificados sobre ArquitectOverview + dossier de capacidad con evidencia `file:line`) · incidente pool sede 30-jul · encargo de Cristian (Slack 05-ago) · decisiones JF 05-ago (SSO escalonado, 018 in, UI = chat de usuario, Safari out, tech tree como formato).
