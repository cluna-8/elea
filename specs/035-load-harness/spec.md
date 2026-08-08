# Feature Specification: Harness de carga — «El examen existe»: gates 125/250/500 medidos, no declarados

**Feature Branch**: `035-load-harness`

**Created**: 2026-08-07

**Status**: Draft

**Input**: User description: "Kickoff La ITV (issue #95): banco de pruebas de carga que
simula usuarios reales (chat + extensión + coding tools SSE + admin) contra el stack de
producción para medir los gates 125/250/500 del tech tree (`ROADMAP-pisos.md`) con SLO de
pérdida de auditoría cero, corpus PII español con canarios, stub de proveedor y validación
smoke con modelos reales vía OpenRouter; reportes comparables entre runs. Aclaración JF
07-ago: preferencia por herramientas open-source auto-hosteadas en infra propia; pagar un
servicio solo si no hay alternativa razonable."

## Por qué existe esta spec (contexto y estado del conocimiento)

**El MVP de septiembre es «aguanta 500 usuarios simultáneos con pérdida de auditoría
cero», y hoy ese número es una opinión.** La Fase 0 del tech tree no se declara — se
examina: tres gates de carga (125/250/500) son su examen final. No existe hoy ningún
instrumento capaz de administrar ese examen. El primer entregable de esta spec no es
"pasar" ningún gate: es **saber con un número dónde estamos**, pasemos o no.

Qué sabemos y con qué grado de certeza (disciplina SDD — no mezclar):

1. **Configuración verificada** (dossier 04-ago, RE-verificado contra main el 07-ago con
   evidencia `file:line`): 2 workers de backend con I/O síncrono dentro de endpoints
   async, motor en 1 proceso, analizador NLP en 1 proceso con cliente fail-closed a 2 s
   en el camino del motor (el detector del panel del backend va a 5 s), pool de
   conexiones 10+20 por worker compartiendo un servidor Postgres sin tuning con el motor,
   sin límites de recursos ni backpressure en ningún plano, y un gap de timeouts en
   streaming (lectura 60 s < router 120 s del perfil de producción del cliente) que corta
   streams lentos en el camino byok→motor justo bajo carga (el plano chat ya corre con su
   timeout propio de 150 s). La lectura «esto aguanta ~10-15 usuarios» es una
   **estimación derivada**, no un hecho: medirla es exactamente el trabajo del gate 125.
2. **Único dato empírico de carga real**: el incidente de la sede (30-jul) — un puñado de
   peticiones largas concurrentes colgó el producto ~10 minutos. Nunca hubo más medición.
3. **Hipótesis de diseño** (papel del 04-ago, ratificadas como *punto de partida* por el
   issue #95 pero NO validadas por SDD): generador k6+xk6-sse, mezcla de tráfico
   60% chat / 25% extensión / 10% coding-SSE / 5% admin, ~40-80 requests en vuelo a 500
   usuarios activos (ley de Little). Estas hipótesis se validan o se tumban en la fase de
   plan (research); esta spec define el QUÉ sin casarse con ellas.

**Cambio de mundo en curso (08-ago, PR #97 — a mergear)**: el plano `/gw` — el del
tráfico de los gates — pasa de regex puro a llamar al analizador NLP **en cada request**
cuando está configurado (~50-200 ms extra + timeout 2 s **fail-closed por default**,
política `nlp_fail_mode` gobernable; bloque `nlp` nuevo en el health, cacheado 10 s y
gateado por rol). El examen DEBE medir el mundo post-#97: con él, casi todo el tráfico
del gate toca el sidecar spaCy monoproceso — exactamente el candidato nº 1 a cuello del
dossier del 04-ago. La definición versionada del gate fija `nlp_fail_mode` como parte de
la configuración exigida al stack, y los gates oficiales corren contra una imagen que
incluya el #97 (el fingerprint lo delata).

**Definición honesta de "usuario simultáneo"**: N usuarios = N sesiones ACTIVAS (personas
trabajando con la herramienta), no N requests en vuelo. Es la lectura comercial del número
— la licencia de la Cámara son 300 asientos, el MVP promete 500 — y la que evita
autoengaño: medir 500 requests en vuelo sería examinar otra cosa.

**Frontera del equipo (issue #95)**: La ITV **mide, no parchea**. Todo cuello que el
examen destape (pool anti-inanición, workers, backpressure…) se reporta como issue al
equipo core de Guardian; el harness nunca incluye fixes de producto.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Gate 125 con veredicto automático (paridad sede) (Priority: P1)

Un operador del equipo (o una sesión agéntica) lanza **el examen del gate 125** contra un
stack de producción completo desplegado en un entorno dedicado: 125 usuarios activos
sostenidos 30 minutos con mezcla realista de superficies (chat, extensión, coding con
streaming, administración) y tráfico que incluye el corpus PII en español a densidades
conocidas. Al terminar, obtiene **un reporte con veredicto pass/fail por cada SLO**, sin
análisis manual.

**Why this priority**: es la paridad con la sede real (~125 beta testers de la Cámara) y
el primer número que existe. El DoD del ciclo 1 exige este gate medido; todo lo demás
(250, 500, comparaciones) se construye encima de este camino completo.

**Independent Test**: desplegar el stack en el entorno de examen, ejecutar el gate 125 con
un comando y verificar que el reporte final contiene veredicto por SLO, métricas de
latencia como overhead y el fingerprint del stack examinado. El valor entregado: el
departamento sabe por primera vez si aguantamos la sede actual, con evidencia.

**Acceptance Scenarios**:

1. **Given** un stack de producción completo y sano en el entorno de examen, **When** se
   ejecuta el gate 125, **Then** el harness sostiene 125 sesiones activas durante 30
   minutos con la mezcla configurada y produce un reporte con veredicto por SLO.
2. **Given** un run completado, **When** se lee el reporte, **Then** cada SLO de oro
   aparece con su valor medido y su veredicto: Δ eventos de auditoría perdidos (bloque
   `audit.lost_events` del health detallado del sistema, spec 031) == 0, reconciliación
   de filas de auditoría emitidas vs persistidas, 0 entidades PII crudas recibidas por el
   proveedor simulado, y 100% de los bloqueos con su fila durable.
3. **Given** el contador de auditoría perdida devolviendo valor nulo/ausente, **When** se
   evalúa el SLO, **Then** el veredicto es FAIL (nulo NUNCA se interpreta como cero). El
   evaluador se autentica con un rol autorizado a leer el health detallado (el bloque de
   auditoría solo es visible para roles de administración/compliance): «ausente por
   credencial insuficiente» es un defecto del harness (run inválido), no un FAIL del
   sistema.
4. **Given** el sistema degradándose a mitad del examen (p. ej. el stack deja de
   responder), **When** el run termina o se aborta, **Then** el reporte existe igual,
   marcado como fallido/incompleto con la evidencia recolectada hasta ese punto — el
   harness jamás muere en silencio ni cuelga sin reporte.
5. **Given** latencias medidas durante el run, **When** se reportan, **Then** se expresan
   como **overhead sobre la latencia programada** del proveedor simulado (lo que agrega
   nuestro pipeline), no como latencia absoluta que mezcla al proveedor en la medición.

---

### User Story 2 - Gate 250 con tormenta de login «lunes 9:00» (Priority: P2)

El mismo examen a 250 usuarios activos, agregando el escenario de **tormenta de login**:
toda la población entra al sistema dentro de una ventana de 10 minutos (el lunes a las
9:00 de una empresa real), con la autenticación, carga de paneles y establecimiento de
sesión que eso implica, y después sostiene la carga normal.

**Why this priority**: es el segundo número del DoD del ciclo 1 y el primer escenario que
examina un patrón de ráfaga (no solo carga sostenida). La tormenta de login es el modo de
fallo más probable de un despliegue corporativo real.

**Independent Test**: ejecutar el gate 250 y verificar que el reporte separa la fase de
tormenta (ventana de 10 min) de la fase sostenida, con los SLO evaluados en ambas.

**Acceptance Scenarios**:

1. **Given** 250 cuentas de usuario aprovisionadas, **When** se ejecuta el gate 250,
   **Then** el harness concentra los logins de toda la población en una ventana de 10
   minutos y el reporte muestra las métricas de esa fase separadas de la fase sostenida.
2. **Given** el examen completo, **When** se evalúan los SLO de oro, **Then** aplican
   igual que en el gate 125 (la tormenta no relaja ningún SLO).

---

### User Story 3 - Dos runs comparables: el harness como instrumento del core (Priority: P2)

El equipo core aplica un fix (p. ej. el tope de concurrencia anti-inanición del pool) y
necesita saber si mejoró algo. Ejecuta el mismo gate dos veces — antes y después — y
compara los reportes **lado a lado**: mismas métricas, mismo corpus, misma mezcla, misma
semilla; cada reporte lleva el **fingerprint** de lo examinado (versión del producto,
configuración relevante del stack, hardware del entorno) para que la comparación sea
legítima o se detecte que no lo es.

**Why this priority**: «reporte comparable» es la mitad del DoD del ciclo 1. Un número
suelto sirve una vez; dos números comparables convierten el harness en el instrumento con
el que el departamento decide (¿el fix del pool alcanzó? ¿cuánto ganamos con N workers?).

**Independent Test**: correr el mismo gate dos veces sobre el mismo stack, verificar que
los reportes declaran fingerprint idéntico y métricas dentro de la tolerancia de
repetibilidad; cambiar una config del stack y verificar que el fingerprint delata la
diferencia.

**Acceptance Scenarios**:

1. **Given** dos runs del mismo gate sobre el mismo stack sin cambios, **When** se
   comparan los reportes, **Then** los veredictos coinciden y las métricas caen dentro de
   la tolerancia de repetibilidad declarada (SC-005).
2. **Given** dos runs con versiones o configuraciones distintas del stack, **When** se
   comparan, **Then** ambos fingerprints exponen la diferencia (la comparación nunca
   presenta como equivalentes dos exámenes de cosas distintas).
3. **Given** un run interrumpido o inválido, **When** se intenta compararlo, **Then** el
   reporte lo marca como no comparable (un examen a medias no es un punto de referencia).
4. **Given** un run completado en el pasado, **When** cualquier miembro del equipo
   consulta el histórico, **Then** el reporte y su evidencia siguen accesibles sin
   depender de la máquina de quien lo corrió (FR-013).

---

### User Story 4 - Gate 500: el número del MVP (Priority: P3)

El examen completo del MVP de septiembre: 500 usuarios activos, 1 hora sostenida, un pico
del doble de carga, y verificación de **recuperación** (el sistema vuelve a servicio normal
tras el pico sin intervención). Adicionalmente — fuera del pass/fail — el harness busca la
**rodilla** de la curva: a qué población empieza a degradar el sistema, subiendo carga por
escalones hasta encontrarla.

**Why this priority**: es el número que define el MVP, pero su ejecución con veredicto es
DoD del ciclo 3; el entregable del ciclo 1 para esta historia es la **definición
versionada del gate 500** (FR-006), validable en seco (SC-008). La búsqueda de rodilla
produce el dato de ingeniería más útil (dónde invertir), no condiciona el veredicto del
gate y es explícitamente diferible.

**Independent Test**: ejecutar el gate 500 en el entorno de examen y verificar que el
reporte contiene las tres fases (sostenida / pico ×2 / recuperación) con SLO por fase, y
opcionalmente el resultado de búsqueda de rodilla como sección informativa.

**Acceptance Scenarios**:

1. **Given** el stack de examen, **When** corre el gate 500, **Then** el reporte evalúa
   los SLO de oro en la hora sostenida Y durante el pico ×2 Y verifica la vuelta a niveles
   normales tras el pico (recuperación sin reinicio manual).
2. **Given** la búsqueda de rodilla habilitada, **When** el sistema degrada en un escalón
   de carga, **Then** el reporte informa el último escalón estable y el primero degradado,
   sin afectar el veredicto pass/fail del gate.

---

### User Story 5 - Smoke con modelos reales (el stub no se examina a sí mismo) (Priority: P3)

Un run reducido (población pequeña, duración corta, presupuesto explícito) contra un
**proveedor real de bajo coste** (decisión de negocio del weekly 05-ago: OpenRouter) y
contra el camino de **modelo local** del producto, para validar que el comportamiento
observado con el proveedor simulado no es un artefacto del simulador: streaming real,
latencias reales, errores reales de proveedor.

**Why this priority**: protege la credibilidad del examen (¿y si el stub nos miente?),
pero no bloquea el DoD del ciclo — los gates se corren contra el stub por diseño (coste
cero).

**Independent Test**: ejecutar el smoke con un presupuesto declarado (p. ej. ≤ N USD),
verificar que el gasto real no lo supera y que el reporte contrasta las métricas clave
(overhead, tasa de error, cortes de stream) contra el run equivalente con stub.

**Acceptance Scenarios**:

1. **Given** un presupuesto explícito por run de smoke, **When** el gasto acumulado lo
   alcanza, **Then** el harness corta el tráfico hacia el proveedor real (nunca gasto sin
   techo).
2. **Given** un smoke completado, **When** se lee el reporte, **Then** contrasta stub vs
   real en las métricas clave y señala divergencias que ameriten recalibrar el simulador.

---

### Edge Cases

- **Contador de auditoría nulo o endpoint de salud caído** durante la evaluación de SLO →
  FAIL explícito con causa («no se pudo verificar» ≠ «verificado en 0»).
- **El instrumento como cuello de botella**: si el generador de carga o el proveedor
  simulado saturan sus propios recursos, el run queda marcado inválido — el harness debe
  medir y reportar su propio headroom para que nunca se confundan sus límites con los del
  producto. El reporte evidencia además que el modelo de llegadas se mantuvo abierto
  (FR-002): la tasa de llegada efectiva acompañó a la programada aun con la latencia
  creciendo; si cayó por saturación del generador, run inválido.
- **Canario PII detectado en el proveedor simulado**: el run continúa (para medir el
  tamaño de la fuga) pero el veredicto del SLO de PII es FAIL con la evidencia (qué
  canario, en qué request, con qué configuración de masking).
- **Aprovisionamiento insuficiente**: si la licencia del stack no cubre la población del
  gate (500 seats), el harness falla ANTES de generar carga, con mensaje accionable — no
  a los 20 minutos de run.
- **Población a mitad de examen**: usuarios que expiran sesión o keys que agotan
  presupuesto durante el run — el harness distingue los errores esperables del guion
  (p. ej. 402 de presupuesto si el guion lo provoca) de los fallos del sistema.
- **Run interrumpido** (Ctrl-C, caída del runner): reporte parcial marcado inválido;
  nunca un directorio a medias que parezca un examen completo.
- **Drift de entorno**: el stack de examen quedó con config de un run anterior (p. ej.
  masking apagado por un experimento de inyección de fallo) → el fingerprint lo expone y
  el harness avisa antes de correr un gate oficial.
- **Reloj y duración**: pausas del runner (suspensión, throttling) que estiren el tiempo
  de pared → el reporte registra duración efectiva y la marca si difiere de la nominal.
- **Trampas conocidas del producto (radar 08-ago)**: el guion de admin NO incluye altas
  concurrentes de entidades custom hasta que el fix de la carrera del guard anti-ReDoS
  (PR #99) esté en la imagen examinada (422 espurios ensuciarían el run); y el corpus
  JAMÁS incluye patrones regex hostiles (DoS de threadpool documentado en #106) —
  cargar ese camino sería examinar otra cosa; solo deliberadamente y fuera de gates
  oficiales.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El harness DEBE simular N **sesiones de usuario activas** (no N requests en
  vuelo) con una mezcla configurable de las cuatro superficies del producto: chat de
  usuario (portal), extensión de navegador, herramientas de coding con respuestas en
  streaming, y operaciones de administración/consulta de paneles. La mezcla y la
  **cadencia de interacción** (ritmo de acciones y pausas de pensado por superficie) por
  defecto son las hipótesis documentadas en Assumptions hasta que el research de plan las
  valide; «sesión activa» queda anclada a esa cadencia declarada, y cada reporte registra
  la mezcla y cadencia usadas.
- **FR-002**: El modelo de llegadas DEBE ser **abierto**: la tasa de llegada de peticiones
  no puede depender de la velocidad a la que el sistema responde. Cuando el sistema se
  atasca, la carga sigue llegando y la latencia real queda medida — el instrumento no debe
  ocultar la degradación esperando a que el sistema se desocupe.
- **FR-003**: El harness DEBE incluir un **proveedor simulado (stub)** que reemplace a los
  proveedores de IA reales durante los gates: respuestas streaming y no-streaming, latencia
  y ritmo de tokens programables, tasa de error inyectable, coste cero, y **detección de
  canarios**: todo contenido que llegue al stub se inspecciona en busca de los canarios PII
  del corpus; un canario crudo recibido = fuga registrada con su evidencia.
- **FR-004**: El corpus de tráfico DEBE ser **sintético, en español, con PII fabricada**
  (jamás datos reales de clientes ni personas), con **densidades de PII configurables por
  escenario** (incluyendo 0 — tráfico limpio) y **canarios únicos por run** (valores
  imposibles de confundir con datos legítimos, distintos en cada ejecución para que una
  detección nunca sea residuo de un run anterior). *Enmienda 08-ago (issue #107,
  decidido con JF)*: el corpus es además un **artefacto compartido del departamento** —
  un dataset etiquetado versionado (spans por tipo de entidad, formato consumible por
  máquina) con dos consumidores: este harness (mezclas de tráfico y canarios) y el gate
  de calidad de detección NLP del core (precision/recall por entidad contra el
  analizador real). Semilla obligada: los casos reales del piloto (#63) como regresiones
  etiquetadas. Los canarios siguen siendo runtime-only por run; el dataset etiquetado es
  la capa estática compartida.
- **FR-005**: Un **seeder** DEBE aprovisionar de forma reproducible la población del
  examen sobre un stack recién desplegado: organización, usuarios con los roles canónicos
  del producto en una distribución declarada (consumidores tipo client — que son quienes
  ocupan seats — más administración y compliance para paneles y lectura de SLO), llaves
  por herramienta y presupuestos, hasta 500 seats. **Un seat = una llave/Connection
  activa, no un usuario**: los gates 125 y 250 corren con la licencia existente de 300
  seats; el gate 500 requiere la **licencia de test de 500 seats**, que se emite
  in-house con los scripts de licencias existentes (confirmación JF 07-ago — no es
  dependencia externa bloqueante). El seeder verifica la capacidad de seats disponible
  ANTES de aprovisionar.
- **FR-006**: Los **gates 125/250/500 DEBEN existir como definiciones versionadas** en el
  repositorio, ejecutables cada una con un solo comando, conforme al examen del tech tree:
  gate 125 = 30 min sostenidos, mezcla realista, corpus PII; gate 250 = + tormenta de
  login en ventana de 10 min; gate 500 = + 1 h sostenida, pico ×2, verificación de
  recuperación. La definición incluye la **configuración exigida al stack examinado** —
  como mínimo el estado del enmascarado por scope (default de gate oficial: enmascarado
  activo en todos los scopes del guion; por constitución apagarlo es un estado legítimo y
  configurable, así que sin fijarlo el SLO de canarios queda indefinido) — y el harness
  verifica esa precondición antes del run (fingerprint + aviso de drift). Cambiar la
  definición de un gate — incluida su tolerancia de repetibilidad — es un cambio
  versionado (los resultados citan la versión del gate que examinó).
- **FR-007**: El veredicto DEBE ser **automático y por SLO**, con los cuatro SLO de oro
  del tech tree evaluados en todos los gates: (a) Δ eventos de auditoría perdidos == 0,
  leído con credencial autorizada del contador que expone el sistema (spec 031), con
  nulo/ausente = FAIL y con validez condicionada a contador final ≥ inicial (un contador
  que retrocede delata un reinicio de su almacén → run inválido); (b) **reconciliación**:
  filas de auditoría persistidas == eventos auditables generados por el guion — existe
  precisamente porque (a) tiene un punto ciego documentado: una pérdida ocurrida con el
  almacén del contador caído no incrementa nada; (c) **0 canarios PII crudos** recibidos
  por el proveedor simulado; (d) **100% de los bloqueos** provocados por el guion con su
  fila durable de auditoría. Latencias y errores se reportan como contexto; los cuatro
  SLO deciden el pass/fail.
- **FR-008**: Las latencias DEBEN reportarse como **overhead del pipeline**: tiempo medido
  menos la latencia programada del proveedor simulado, por superficie y por percentil
  (mínimo p50/p95/p99 y máximo), y para las superficies con streaming: tiempo al primer
  token y cortes de stream.
- **FR-009**: Cada reporte DEBE incluir el **fingerprint de lo examinado**, con esta
  lista mínima (ampliable en plan): versión del producto (commit/imágenes), estado del
  enmascarado por scope, configuración del analizador NLP, número de workers/procesos por
  servicio, límites de recursos, definición y versión del gate, corpus y semilla,
  mezcla y cadencia usadas, hardware del entorno, y timestamp. Dos reportes DEBEN poder
  compararse lado a lado; la comparación DEBE señalar cuando los fingerprints difieren.
- **FR-010**: La observación del sistema examinado DEBE ser **out-of-band**: las métricas
  del stack (CPU, memoria, conexiones, colas, contadores internos) se recolectan por fuera
  del generador de carga, sin instrumentación dentro del producto que altere lo medido.
  Esas métricas y los logs del producto durante la ventana del run forman parte de la
  **evidencia persistida** del run y se referencian desde el reporte: son el insumo para
  diagnosticar un FAIL sin tener que reproducirlo, y la señal con la que la búsqueda de
  rodilla (US4) declara «degradado» un escalón (señal concreta a definir en plan).
  Durante el run, el estrés del stack DEBE ser observable **en vivo** por el equipo
  (tablero), no solo post-mortem (pedido JF 07-ago).
- **FR-011**: Los gates DEBEN correr contra un **stack de producción completo**
  (composición de producción, imágenes reales, analizador NLP real activo — no atajos de
  dev) desplegado en un **entorno dedicado**. La única sustitución permitida es la del
  proveedor de IA externo por el simulado (FR-003); todo componente del stack propio
  corre real. Queda PROHIBIDO ejecutar carga contra el VPS de producción o contra
  instalaciones de clientes.
- **FR-012**: Los gates oficiales DEBEN ejecutarse **exclusivamente contra el proveedor
  simulado**, a coste de API cero: el SLO de canarios (FR-007c) y el overhead (FR-008)
  solo son evaluables con el stub como centinela y referencia. Los modelos locales y los
  proveedores reales quedan confinados al smoke (US5), cuyo reporte declara esas
  limitaciones. Todo run contra proveedores reales DEBE declarar un presupuesto máximo
  explícito y cortarse al alcanzarlo.
- **FR-013**: Resultados, reportes y logs de todos los runs DEBEN quedar **persistidos y
  accesibles al equipo** (histórico consultable, no archivos sueltos en el laptop de
  nadie). La plataforma concreta es decisión del plan, con el sesgo declarado por JF:
  open-source auto-hosteado en infra propia; pagar solo si no hay alternativa razonable.
- **FR-014**: El harness DEBE poder **probar su propio detector** mediante inyección de
  fallo controlada: un modo de examen con el enmascarado deliberadamente desactivado (en
  el stack de examen, jamás en producción) DEBE producir canarios detectados > 0 y FAIL.
  Un detector que nunca detecta nada no es evidencia de nada.

### Key Entities

- **Gate**: definición versionada de un examen (población, duración, fases, mezcla,
  densidades PII, SLO); 125/250/500 son las tres instancias canónicas del tech tree.
- **Run**: una ejecución de un gate (o smoke) contra un stack concreto; tiene estado
  (completado/interrumpido/inválido), fingerprint, métricas, veredicto y evidencia.
- **Fingerprint**: la identidad de lo examinado — versión del producto, config del stack,
  versión del gate, corpus/semilla, hardware, timestamp. Hace legítima (o delata) una
  comparación.
- **Corpus PII**: el material de tráfico sintético en español con densidades conocidas de
  PII fabricada; versionado.
- **Canario**: valor PII sintético único por run, sembrado en el tráfico, cuya aparición
  cruda en el proveedor simulado constituye evidencia de fuga.
- **Proveedor simulado (stub)**: el reemplazo de los proveedores de IA durante el examen;
  programable en latencia/errores, centinela de canarios, coste cero.
- **Población / Seed**: el conjunto reproducible de organización, usuarios, roles, llaves
  y presupuestos que el seeder aprovisiona para un gate.
- **Reporte**: el documento comparable de un run — veredicto por SLO, métricas por fase y
  superficie, fingerprint, evidencia de fallos.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Los gates 125 y 250 quedan **ejecutados y reportados** (pasen o no) antes
  del cierre del ciclo 1 (21-ago), con reporte comparable — el DoD del ciclo.
- **SC-002**: El veredicto de cualquier run se obtiene **sin análisis manual**: el reporte
  final trae pass/fail por SLO; dos personas leyendo el mismo reporte llegan al mismo
  veredicto.
- **SC-003**: El coste de API de un run de gate es **0** (verificable en el reporte de
  gasto del run).
- **SC-004**: Prueba del detector (inyección de fallo): un run con enmascarado
  desactivado a propósito produce **canarios detectados > 0 y veredicto FAIL**; el mismo
  examen con el producto sano produce 0. Sin esta prueba en verde, ningún «0 fugas» de un
  gate cuenta como evidencia.
- **SC-005**: **Repetibilidad**: dos runs consecutivos del mismo gate sobre el mismo stack
  arrojan los mismos veredictos y métricas primarias dentro de **±10% en overhead p95**
  (criterio vinculante del ciclo 1). Recalibrar esa tolerancia es un cambio versionado de
  la definición del gate (FR-006), citado en los reportes — nunca una decisión silenciosa
  del run que la incumple.
- **SC-006**: Un operador (humano o agente) lanza un gate completo con **un comando** y
  ≤ 30 minutos de preparación, medidos desde un entorno ya provisto (stack desplegado y
  sano + licencia instalada) hasta el inicio de la generación de carga; la preparación
  incluye el seeding de la población, la generación/carga del corpus y la verificación de
  precondiciones del gate.
- **SC-007**: Si algún gate del ciclo 1 destapa un cuello o incumple un SLO, el issue al
  core con la evidencia de run adjunta existe antes del cierre del ciclo — el harness
  produce trabajo accionable para otros, no números decorativos. (Si ambos gates pasaran
  limpios, este SC se cumple vacuamente — y esa sería una noticia enorme por sí sola.)
- **SC-008**: La definición versionada del gate 500 existe y pasa una **validación en
  seco** (definición interpretable + precondiciones de aprovisionamiento computables)
  antes del cierre del ciclo 1; su ejecución con veredicto es DoD del ciclo 3.
- **SC-009**: Antes de dar por oficial el gate 500, existe al menos un smoke contra
  proveedor real (US5) completado con gasto ≤ su presupuesto declarado y con reporte de
  contraste stub-vs-real — un examen entero apoyado en un simulador jamás contrastado no
  sería evidencia.

## Assumptions

**Hipótesis de diseño (a validar o tumbar en plan/research — NO son decisiones):**

- Generador candidato: k6 + extensión SSE (Locust descartado en el análisis preliminar
  del 04-ago por coordinated omission; vegeta solo como cross-check). El plan DEBE
  confirmar o sustituir con evidencia.
- Mezcla de tráfico por defecto: 60% chat / 25% extensión / 10% coding-SSE / 5% admin —
  estimación sin datos reales de la sede detrás. Si puede obtenerse una distribución real
  (metadatos de auditoría de la Cámara), el plan la usa; si no, la hipótesis queda
  documentada en cada reporte. Dato verificado que condiciona el modelado: el chat del
  portal es hoy request/response **sin streaming** — tiempo-al-primer-token y cortes de
  stream solo aplican a la superficie coding.
- Cadencia de interacción por superficie (hipótesis inicial, a validar en plan): chat ≈
  una interacción por usuario cada 60-180 s; extensión ≈ una inspección cada 90-300 s;
  coding ≈ una request streaming cada 120-300 s; admin ≈ navegación esporádica de
  paneles. De cadencia + mezcla se deriva la tasa de llegada programada; el reporte
  declara la usada (ancla operativa de «sesión activa», FR-001).
- Dimensionamiento: 500 usuarios activos ≈ 40-80 requests en vuelo (~150 en pico), por
  ley de Little con los tiempos de interacción asumidos.
- Plataforma de resultados/observabilidad: sesgo explícito de JF (07-ago) por open-source
  auto-hosteado en el contenedor AWS propio (donde ya viven Plane, Bitwarden…); un
  servicio pago solo con justificación.

**Fronteras de alcance:**

- La ITV mide; **los fixes de producto quedan fuera** (pool, workers, backpressure,
  streams — issues al core con evidencia de run).
- El **panel de rendimiento** del weekly (nodo 🆕 sin spec) queda fuera: esta spec
  produce los datos que ese panel consumirá, no el panel.
- Integración con CI queda fuera del ciclo 1 (los gates corren on-demand; automatizarlos
  post-#82/#93 es evolución futura).
- El examen de Fase 0 es **API/BYOK**: la superficie "extensión" se simula por sus
  llamadas al gateway, no automatizando navegadores reales.

**Dependencias y supuestos de entorno:**

- **Licencia de test de 500 seats**: se emite in-house con los scripts de licencias
  existentes (confirmación JF 07-ago; gate de Cristian solo si toca custodia de claves).
  Un seat cuenta llaves/Connections ACTIVAS, no usuarios (semántica verificada de la
  spec 021): con la licencia existente de 300 el tope muerde al crear la llave 301 — los
  gates 125 y 250 corren con la de 300; para el 500 se emite la de test.
- **Entorno de examen**: Hetzner Cloud, project dedicado `guardian-itv` (decisión
  08-ago aprobada por JF vía DevOps — supersede la dirección AWS del 07-ago: la única
  cuenta AWS accesible hospeda producción legal de un cliente, radio de explosión
  inaceptable). Cajas de vCPU **dedicadas** (SUT CCX33 8 vCPU/32 GB, generador CCX23
  4 vCPU/16 GB) — mejor para la repetibilidad que la tenancy compartida del diseño
  original; el fingerprint registra server_type. Firewall cloud con bloqueo de egress
  (el candado del stub se mantiene); imágenes precargadas por docker save/load ANTES de
  cerrar el firewall. Nunca el VPS de producción (CPX32 compartido detrás de CDN:
  medirías al CDN, no al producto) — que además vive en otro project, invisible para el
  token de `guardian-itv`.
- **Keys de OpenRouter para el smoke**: acordadas en el weekly 05-ago como vía de
  validación con modelos reales; alta y presupuesto por definir en plan.
- El stack examinado incluye el analizador NLP real (constitución: regex-only no es
  producción) y la composición de producción sin límites de recursos *tal como se vende
  hoy* — examinar la configuración real, no una endurecida a mano para el examen.
- El harness vive como **módulo del monorepo** (propuesta #95: directorio propio con
  dueño en CODEOWNERS); si el plan encuentra razones para otra estructura, lo decide el
  proceso de decisiones estructurales del CONTRIBUTING.
- Los datos del corpus son 100% sintéticos; ninguna fila de auditoría generada en el
  examen contiene PII real — el harness respeta la constitución (auditoría metadata-only,
  no raw PII) también en su propio material de prueba.
