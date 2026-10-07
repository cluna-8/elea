# Feature Specification: Porte de la política de redireccionamiento de modelos (Sentinel 068) a Eleia

**Feature Branch**: `057-porte-sentinel-068-redireccion-modelos`

**Created**: 2026-10-06

**Status**: Draft (especificada y clarificada; plan y tareas escritos; enmendada por `speckit-clarify` con las decisiones legales del owner y con las correcciones del QA crítico del plan, ambas del 2026-10-06)

**Spec de origen**: Sentinel `specs/068-politica-redireccionamiento-modelos/` (`origin/main`
6a70855): `spec.md`, `contracts/cara-claude.md`, `contracts/cara-generica.md`,
`data-model.md`, `research.md` (D13–D22), `plan.md`, `tasks.md`; y el código ya hecho en
`sentinel/redirect/`, `sentinel/common/` y `sentinel/catalog/`.

**HANDOFF de Sentinel** (recibido durante el clarify, 2026-10-06): Sentinel
`specs/HANDOFF-068-sentinel-a-elea.md`, rama `docs/handoff-068-elea` (PR #110 de Sentinel).
Fija el orden de los 16 commits de costuras, la copia del paquete de la extensión desde
6a70855, el subconjunto mínimo de la 069 (catálogo, acceso, común) y la cadena de migraciones de
la extensión. Donde esta spec dice «HANDOFF §x», se refiere a ese documento.

**Input**: pedido del owner por el coordinador: *"Que Claude Desktop (Chat, Cowork, Code) y
Claude Code se conecten a la pasarela de Eleia creyendo que hablan con el modelo que piden,
mientras el administrador decide en el panel qué modelo real los sirve (en Eleia, el catálogo de
Azure y otros destinos configurables). Que sea una política ON/OFF por empresa, grupo o
conexión, con residencia para América (perfil Argentina, Ley 25.326/AAIP): solo modelos de la
región, o de otra región con enmascarado forzado. Primero las costuras de base que la extensión
necesita."*

## Cómo leer esta spec

- **Trazabilidad**: cada requisito cita de dónde viene con la forma
  `ELEIA-057 ← SENTINEL-068 <FR/SC/contrato/decisión>`. Un requisito sin origen en la 068 lo dice.
- **Etiqueta de origen** en cada requisito:
  - **[BASE]** = base compartida Guardian: se porta **tal cual** desde Sentinel, se escribe
    genérico, sin strings de Elea/Eleia, y cualquier diferencia vuelve a Sentinel por `HANDOFF`.
  - **[ELEIA]** = propio de Eleia (adaptación para América): perfil Argentina, datos de
    jurisdicción, textos, catálogo de destinos de la instalación, documentación de producto.
- **Normativa**: en este repo no rigen GDPR ni la EU AI Act. Eleia es la base de la línea
  América (Sentinel lo es de Europa). Donde la 068 dice «UE» como ejemplo, aquí rige el **perfil
  de país** de la instalación: Argentina, Ley 25.326 de Protección de Datos Personales y criterios
  de la AAIP, con la región `AMERICAS` (continente americano completo, FR-030) como «mi región».
  El mecanismo es el mismo (jurisdicciones como dato, 068 FR-013); cambian los datos.

## Contexto y vocabulario

Se hereda el vocabulario de la 068 (§Contexto y vocabulario) sin cambios:

- **Política de redireccionamiento** (*la política*): capa de gobernanza nueva, apagada por
  defecto, que se resuelve por alcance (empresa → grupo → usuario → conexión).
- **Cara**: el «idioma» con el que la pasarela se presenta ante una herramienta. En el MVP de
  Eleia hay **dos**: la **cara Claude** (la que esperan Claude Desktop, Cowork y Claude Code) y
  la **cara OpenAI genérica** (la que entienden la mayoría de CLIs y harness open-source).
- **Id público**: el nombre de modelo que ve y pide la herramienta (p. ej. el de un tier
  opus / sonnet / haiku).
- **Destino**: el modelo real, en un proveedor concreto, que responde el pedido.
- **Regla de mapeo**: id público (o tier) → destino principal + fallbacks ordenados.
- **Fidelidad**: *Nativo* (cara y destino de la misma familia de protocolo) o *Traducido*.
- **Jurisdicción**: región legal donde se procesa la inferencia de un destino, tratada como dato.
- **Postura de residencia**: sub-política que restringe los destinos según la jurisdicción.
- **Costura**: punto de enganche genérico y marca-neutro en la base que permite que una
  extensión agregue comportamiento sin bifurcar la base; sin extensión, la base se comporta
  igual que hoy.

## Diagnóstico verificado en código (2026-10-06)

| # | Qué asume la 068 | Qué hay hoy en Eleia |
|---|---|---|
| 1 | Pasarela con cara Claude en `/gw/v1/messages`, `count_tokens` y `models` | Existe como **middleware sin redirección**: `gw_messages` (`backend/src/api/gateway.py:1636`), `gw_count_tokens` (`:2031`) y `gw_models` (`:2039`). `count_tokens` y `models` son reenvío verbatim por `_plain_passthrough` (`:1989`): en modo con llave del producto, `models` devuelve la lista entera del motor (`:2014`); en modo suscripción, la del proveedor original (`:2017`). |
| 2 | Costura S1 (routers de extensión) | No existe: los routers se montan fijos (`backend/src/main.py:105`, `:113`, `:120`). |
| 3 | Costura S2 (enganches de pasarela `pre_request`, `pre_engine`, `wrap_stream`, `models_filter`, `map_error`) | No existe: ninguna referencia en `backend/src/`. |
| 4 | Costura S3 (páginas del panel por registro) | No existe: agregar una página son tres ediciones en `frontend/src/App.tsx` (comentario `:25-28`). |
| 5 | Costura S4 (migraciones adicionales con `upgrade heads`) | No existe: `upgrade head` fijo en `backend/src/main.py:38`, `backend/Dockerfile:19`, `backend/Dockerfile.standalone:35` (la imagen que publica `deploy/release/publish-elea.sh:25` y baja el instalador), `deploy/docker/entrypoint/backend.sh:30`, `.github/workflows/ci.yml:50`, `deploy/release/checks/test_profile_renders.sh:26`; `backend/alembic/env.py` sin ubicaciones extra; `backend/src/main.py:40-43` registra el fallo de migración sin abortar el arranque. |
| 6 | Costura S5 (respuestas + informe de enmascarado) | No existe: el guardrail declara que `/v1/responses` no se inspecciona (`litellm/extensions/sentinel_guardrail.py:20`) y no deja informe de enmascarado en la metadata interna (`:467-495`). |
| 7 | Costura S6 (entradas ocultas del motor) | No existe: sin `plugin_owner` en `backend/` ni `litellm/`. |
| 8 | Costura S7 (decisión de ruteo confiable desde el motor) | Parcial: la columna `audit_logs.routing_decision` existe (`backend/src/models/audit.py:47`, escritor en `backend/src/services/audit_service.py:422`) pero solo la usa el chat de la consola; el logger del motor (`litellm/extensions/sentinel_audit_logger.py`) y la ingesta interna (`backend/src/api/internal.py`) no la transportan. |
| 9 | Costura S9 (extensiones extra del motor) | No existe: solo se copian `litellm/extensions/*.py` (`deploy/release/populate_volumes.sh:45-46`, `deploy/release/bundle.sh:98-99`, `:186-187`). |
| 10 | Costura S11 (fragmentos de perfil) | No existe: `deploy/release/render_profile.sh:29` renderiza solo el template del perfil. |
| 11 | Costura S12 (entorno extra opcional) | No existe en `deploy/docker/compose.prod.yml`. |
| 12 | S10 (lista de modelos por autorización interna) | Descartada en Sentinel por el spike R13: **no se porta**. |
| 13 | Catálogo de destinos multi-proveedor | El catálogo de dev es **solo Azure**: cuatro entradas `azure/*` (`litellm/config.yaml:35-74`) y el guardrail de política (`:12`). La caché de respuestas del motor está activa en Redis (`:19-25`). |
| 14 | Perfil regional de la instalación | Existe: `SENTINEL_ENTITY_REGION=latam_ar` (`.env.example:194`), región `latam_ar` con patrones propios (`litellm/extensions/sentinel_guardian_policy.py:141`), resolución tenant > instalación en `resolve_region` (`:510`); el default de código sigue siendo `eu` (`:154`). |
| 15 | Motor fijado (spike D14 sobre 1.92.0) | El motor de Eleia es una imagen fijada por digest (`litellm/Dockerfile:6`), no necesariamente la versión del spike: hay que repetir la verificación del spike D14 sobre esta versión. |
| 16 | Marca neutra en lo visible (068 FR-035) | La pantalla de descubrimiento de la pasarela (`backend/src/api/gateway.py:2047-2069`) devuelve al cliente el nombre del motor interno, que está en `deploy/release/checks/prohibited_names.txt`. |
| 17 | Chat de la consola fuera de alcance (068 FR-001) | El chat de la consola rechaza por residencia con un texto que dice «exige procesamiento en la UE» (`backend/src/api/chat.py:1402`), lo que no corresponde a una instalación con perfil Argentina. Queda **fuera de esta spec** y se anota como hallazgo. |
| 18 | Roles de la 068 (FR-014b) | Existen: `super_admin`, `tenant_admin`, `compliance_officer`, `client`, `lectura` (`backend/src/models/user.py:9`). |
| 19 | Cara OpenAI genérica sobre la puerta de chat estándar (068 contrato `cara-generica.md`) | En Eleia **no existe** la puerta `/gw/v1/chat/completions`: no hay `backend/src/api/gateway_openai.py` y la pasarela solo publica `/gw/v1/messages`, `count_tokens` y `models` (`backend/src/api/gateway.py:2053`). En Sentinel esa puerta es de su spec 045 (archivo propio del fork, ADAPT-017) y su cableado de enganches es el commit `efb2c94`; el Anexo A del HANDOFF la agrega: commits `9c17500` (la puerta) y `efb2c94` (enganches), después de los 16 de costuras; **no** se traen `9fe188f` (Eleia ya tiene su equivalente `f8118e7` de la spec 050) ni `fd515ff` (modelo «auto», va después). Sin migraciones ni variables nuevas; hay que regenerar la referencia de la API. **No está verificada en vivo en Sentinel**: la prueba de Eleia sería la primera. |
| 20 | Claude Code contra la pasarela (068 US3) | Evidencia del 6-oct, sin redirección (HANDOFF §2.4): `?beta=true` → 404 con un modelo de Azure; el respaldo falla con «Unrecognized request argument supplied: safeguards»; Claude Code rechaza en el cliente ids que no conoce. En Sentinel faltan el filtro de campos desconocidos hacia traducidos (su T139), la lista permitida de cabeceras beta (su T094) y `count_tokens` para traducidos (su T093). |
| 21 | Destinos de la redirección | Desde la 069 de Sentinel, **los destinos son las entradas del catálogo** (`sentinel/catalog`); `sentinel.access` es necesario por import y `sentinel.common` por la versión de instantánea (HANDOFF §1(b)). El semáforo y la ficha del catálogo están escritos para «admisible UE» y en Eleia mostrarían todo como «fuera de UE» (HANDOFF §4.2). |
| 22 | Residencia para América en Sentinel | **No está hecha** (068 Phase 4: 2/12 tareas). El código ya resuelve `latam_ar` a `{LATAM, AR}`; sin postura, el redirigido solo alcanza destinos LATAM/AR (HANDOFF §4.2). |
| 23 | Migraciones | Del backend de Sentinel no se porta ninguna (los ids `019`/`020` coinciden con los de Eleia con otro contenido). La extensión trae su propia rama con etiqueta, colgada de `010`: sin la variable, una sola cabeza (`199fe429762a`); con ella, dos (`199fe429762a` + `f7a3c1d9e508`) y arranque con `upgrade heads` (HANDOFF §1(c)). |
| 24 | Costuras S9 y S11 | Siguen **sin hacer también en Sentinel** (sus T008, T010); allí las reemplaza su propio script de despliegue (HANDOFF §1(a)). |

## Alcance

**MVP (esta spec)**:

1. **Costuras de base** que la extensión necesita (Phase 0 de la 068, en el orden del HANDOFF
   §1(a)): S1, S2 (con sus agregados), S3, S4, S5b, S6, S7, S12, las adaptaciones de cifrado
   (ADAPT-024) y de reemplazo de menú (ADAPT-026), y el equivalente de S9/S11 en el camino de
   despliegue de Eleia, más las costuras nuevas S13 (marcadores estables por conversación, para la
   caché del proveedor) y S14 (alcance completo del enmascarado forzado); S15 (origen del canal
   interno) es una dependencia que entrega el arreglo de separación de bases (tabla C-1). S5a (política sobre `/v1/responses`) queda para la cara Codex.
2. **Política de redirección ON/OFF** por empresa, grupo, usuario o conexión, con catálogo de
   destinos, ids públicos por tier o alias, reglas con fallbacks y auditoría.
3. **Cara Claude**: Claude Desktop (Chat, Cowork, Code) y Claude Code contra
   `/gw/v1/messages`, creyendo que hablan con el modelo que piden, con el destino que elige el
   administrador (en Eleia, el catálogo de Azure y otros destinos configurables).
4. **Cara OpenAI genérica** (decisión del owner en el clarify): CLIs y harness open-source contra
   `/gw/v1/chat/completions` con alias propios. Exige portar también la puerta de chat estándar
   de Sentinel y su cableado de enganches, que agrega el Anexo A del HANDOFF (Diagnóstico #19).
5. **Caché del proveedor** (decisión del owner en el clarify): afinidad de sesión, marcas de
   caché, determinismo del enmascarado por conversación y precio y registro de tokens de caché.
6. **Residencia para América** (región `AMERICAS`, entidades de datos personales del perfil
   `latam_ar`): *solo jurisdicciones permitidas* o *fuera de región con enmascarado forzado*, más la
   postura por defecto de la región (en Eleia, enmascarado forzado en todo destino) y sus
   relajaciones explícitas de cumplimiento. Sentinel no la terminó (Diagnóstico #22): lo que Eleia
   construya en el mecanismo se escribe genérico y vuelve por `HANDOFF`.

**Fases siguientes (fuera del MVP, anotadas para no perderlas)**:

| Fase | Qué | Origen en la 068 |
|---|---|---|
| F2 | Cara Codex (`/gw/v1/responses`, gobernada aun con política apagada) | US4, FR-027–FR-029, contrato `cara-codex.md` |
| F3 | Kits de cliente por herramienta y alcance | US5, FR-030, contrato `kits.md` |
| F4 | Prueba de fidelidad con conversaciones grabadas | US5, FR-031 |
| F5 | Comparador de costos (costo real vs. hipotético) | US5, FR-032 (parte del costo hipotético) |
| F6 | Modo sombra | FR-003, FR-004b, US1 escenario 5 |
| F7 | Ruteo por clase de pedido (subagente, compactación, auxiliar) | FR-008, US3 escenario 7 |

## Clarifications

### Session 2026-10-06

<!-- Las preguntas de clarify se hicieron al coordinador por `orca orchestration ask`. -->

- Q: ¿La cara OpenAI genérica con alias propios (068 US1, FR-020, contrato `cara-generica.md`)
  entra en el MVP? → A: Sí, decisión del owner: entra junto con la cara Claude. Como Eleia no
  tiene la puerta de chat estándar, se porta también la de Sentinel (su spec 045) con su
  cableado de enganches (`9c17500` y `efb2c94`, HANDOFF Anexo A) (Alcance punto 4, US5,
  FR-053–FR-056).
- Q: En la línea América, ¿qué jurisdicciones cuentan como «mi región»? → A: El continente
  americano completo (Argentina, Colombia, EE. UU., Brasil, México y el resto de América),
  sembrado como lista de jurisdicciones editable bajo un nombre genérico (`AMERICAS`) que sirve a
  cualquier instalación de la línea América. Los destinos en esos países se usan sin enmascarado
  forzado; la UE y el resto quedan fuera de la región. El mecanismo de Sentinel no cambia, solo
  lo que Eleia siembra (corrección del owner, que reemplaza la respuesta inicial «Argentina +
  países adecuados AAIP») (FR-030). *Enmendada por D2 y D3 (Session 2026-10-06, decisiones
  legales): por defecto el redirigido sale enmascarado también dentro de `AMERICAS`, que es
  criterio de riesgo y no de legalidad.*
- Q: Sin postura explícita, ¿a qué destinos va un pedido redirigido? → A: A los de la región del
  perfil (`AMERICAS`); fuera de ella, enmascarado forzado o rechazo según la postura. La
  correspondencia región → jurisdicciones pasa a ser un dato del perfil de país, genérico, y
  vuelve a Sentinel por `HANDOFF` (cierra su D19 punto 2) (FR-031). *Enmendada por D2 (Session
  2026-10-06, decisiones legales): en Eleia la postura por defecto es enmascarado forzado en todo
  destino; la correspondencia región → jurisdicciones como dato se mantiene.*
- Q: ¿La caché del proveedor (068 FR-038–FR-042) entra en el MVP? → A: Sí, completa, decisión
  del owner («el cache es para ahorro, sí o sí va, y el enmascarado es de seguridad»): afinidad
  de sesión, marcas de caché, determinismo del enmascarado por conversación con la costura S13 y
  precio y registro de tokens de caché; el determinismo no puede relajar la protección del
  enmascarado; S13 es nueva, genérica para las dos líneas y vuelve por `HANDOFF` (FR-043–FR-046,
  SC-011, SC-012).
- Q: ¿Con qué destinos se acepta el MVP? → A: Solo con Azure, el catálogo de la instalación
  (traducido para la cara Claude, nativo para la genérica). La parte nativa de SC-004 y los
  demás proveedores portados quedan 🟡 en la documentación hasta tener credencial (FR-011,
  SC-004).

### Session 2026-10-06 (decisiones legales)

<!-- Decisiones del owner del 6-oct-2026 sobre `specs/ANALISIS-TRANSFERENCIAS-AMERICA-2026-10.md`
     §5 (rama `cluna-8/spike-transferencias-america`, a5a88e2). Preguntas al coordinador por
     `orca orchestration ask`; reemplazan solo el texto que contradecían. -->

- Q: ¿Se bloquean por defecto las APIs de primera mano de proveedores chinos (D1)? → A: No. El
  mecanismo de bloqueo por datos se mantiene (proveedor, host, jurisdicción), pero Eleia siembra
  las listas **vacías**: ningún destino nace bloqueado y todo es configurable desde el panel
  (FR-029).
- Q: ¿Cuál es la postura por defecto del tráfico redirigido sin postura explícita (D2)? → A:
  **Enmascarado forzado con analizador fail-closed para todo destino**, dentro y fuera de
  `AMERICAS`. Cumplimiento lo relaja de forma explícita y registrada por destino o por región; se
  rechaza solo lo que no tiene jurisdicción de inferencia registrada. Ningún override del cliente
  lo relaja, y mientras el forzado rija no se relaja el fail-closed (FR-027, FR-031, FR-031a).
- Q: ¿Cómo se tratan los modelos chinos de pesos abiertos alojados en América (D5)? → A: En
  alojadores nombrados y con retención cero, cumplimiento **puede** configurarlos sin enmascarado
  forzado con una relajación explícita por destino; nunca es el default (FR-031a).
- Q: ¿Qué registra el catálogo para que una nube de una entidad de otra jurisdicción, con
  servidores en América, no pase como «en región» (D12)? → A: Por destino, además de la
  jurisdicción de inferencia: la **entidad responsable**, la **jurisdicción de la entidad** y la
  **jurisdicción de control** (la de quien posee ≥ 50 % o controla la entidad), todo como dato y
  genérico. Un destino cuenta como en región solo si las tres jurisdicciones están dentro; con el
  control sin cargar no cuenta como en región, pero sigue usable con el enmascarado por defecto.
  Las jurisdicciones de preocupación son dato (reglas de FR-029) y en Eleia se siembran vacías
  (FR-028a).
- Q: ¿Cómo se nombra el enmascarado y la región en panel y documentación (D3, D10)? → A:
  «Seudonimización reversible de identificadores detectados», nunca «anonimización» ni «cumple
  con X»; `AMERICAS` es criterio de riesgo, no de legalidad; leyenda 🟡 en lo de residencia hasta
  la revisión legal (FR-030, Assumptions «Base legal»).

### Session 2026-10-06 (QA del plan)

<!-- Correcciones de seguridad y entrega que pidió el QA crítico del plan (`qa-plan.md`, 3537847:
     B1–B3, A6–A8, A10). Preguntas al coordinador por `orca orchestration ask`, respondidas por él
     con el owner. No reabren P1–P5, D1–D4, D1/D2/D5/D12 legales ni la enmienda del 403. -->

- Q: ¿Cómo llega la extensión a lo que Eleia publica y al instalador (B1)? → A: Imágenes
  **derivadas** del backend, del panel y del motor (variantes con tag propio, sin mover el de las
  imágenes base), publicadas por el mismo camino de release; las imágenes base no cambian salvo
  que el backend publicado aplica las migraciones adicionales cuando la variable está y **no
  arranca** si esa migración falla. El instalador gana una variable opt-in que elige las
  variantes, escribe el entorno de la extensión (modo 600) y siembra; sin ella, todo idéntico. Hay
  una prueba local con el mismo instalador antes del runbook del servidor, y el runbook incluye la
  vuelta atrás (FR-004c, FR-004d).
- Q: ¿Qué pasa con lo redirigido si falta el seed de la región o la región no se resuelve (B2)? →
  A: Respaldo **en código**: sin fila de región, enmascarado forzado en todo destino con
  analizador fail-closed y alcance limitado a la región del perfil si se conoce; sin región
  resuelta, se rechaza todo lo redirigido y el estado de la extensión lo informa; la región de la
  instalación no cae a un valor de otra línea; el seed se carga al arrancar cuando la extensión
  está activa. Con el seed rige `masked_all` (D2) sin cambios (FR-031).
- Q: ¿Qué cubre el enmascarado forzado y qué es «no analizable» (B3)? → A: Bajo forzado se
  analiza y enmascara **todo**: instrucciones de sistema (texto y bloques), todos los turnos
  (usuario y asistente: texto, entradas y resultados de herramientas, razonamiento) y las
  descripciones de herramientas. Los PDF se convierten a texto, se enmascaran y viajan al
  destino como texto enmascarado; un PDF sin texto extraíble (escaneado, protegido o corrupto),
  los tipos desconocidos son no analizables y se bloquean; las imágenes, según `MASKING_IMAGES` (Clarifications 2026-10-07, R43; sin OCR en el MVP: fase
  siguiente). Un razonamiento firmado con detecciones hacia un destino nativo se bloquea
  (FR-027, SC-006).
- Q: ¿Puede el administrador de la empresa, con filas de postura o con la ficha del destino,
  quitar el piso de la postura por defecto (A6, A7, A8)? → A: No. Sus filas solo restringen (rige
  la más estricta; una fila suya menos estricta se rechaza); un destino sin jurisdicción de
  inferencia se rechaza con **cualquier** fila; regiones, postura por defecto y relajaciones
  exigen el rol real de cumplimiento o super-admin (no una autoridad derivada de una variable de
  entorno, que Eleia no define); los campos de residencia y retención de la ficha los escriben
  solo cumplimiento y super-admin (FR-023, FR-028, FR-031).
- Q: ¿Desde dónde puede alcanzarse el canal interno por el que el motor pide identidad,
  catálogo y credenciales (A10)? → A: Solo desde la red interna de la instalación, en tres capas:
  la ruta que entrega credenciales descifradas responde «no encontrado» salvo que la ruta directa
  del catálogo esté encendida; el backend exige, además del secreto compartido, que el origen sea
  la red interna; y el instalador pone delante del backend un proxy que niega el canal interno y
  deja pasar la pasarela, el panel y el Hub, que siguen alcanzables desde la LAN (FR-013).
  *Precisión del coordinador (re-análisis, mismo día): el proxy y el chequeo de origen se aplican a
  **toda** instalación, con o sin la extensión, y los entrega el arreglo de separación de bases del
  instalador (`cluna-8/fix-separar-bases-motor`, que verificó la exposición de `/api/v1/internal/*`
  por el puerto publicado y va antes que esta feature); esta spec depende de él y solo agrega el
  cierre de la ruta de credenciales.*

### Session 2026-10-06 (QA v2)

<!-- Segunda vuelta del QA crítico del plan (`qa-plan-v2.md`, N1). Pregunta al coordinador por
     `orca orchestration ask`. No reabre ninguna decisión anterior. -->

- Q: ¿Cómo se carga el seed «al arrancar» si la base monta las rutas de la extensión pero no le da
  un punto de arranque y la app usa `lifespan` (N1)? → A: Con una costura nueva de base, **S16**:
  al arrancar, antes de servir, la base corre el enganche de arranque opcional de cada extensión
  declarada; sin extensión, nada cambia; si el enganche falla, se registra y la app arranca igual;
  cuando la siembra es condición del fail-closed de la postura por defecto, el estado de la
  extensión lo informa (FR-031). Vuelve a Sentinel por `HANDOFF`.

### Session 2026-10-06 (gate: vocabulario estructural con el NER real)

<!-- Hallazgo del gate con el analizador real (no el simulado). Decisión del owner; enmienda N8 (QA v2) y no reabre ninguna
     otra. Pregunta resuelta por el coordinador a partir de la decisión del owner. -->

- Q: Con el NER real, `assistant`, `tool_use`, `Read`, `file_path` o un id `toolu_…` salen como PERSON/LOCATION y, como una
  posición estructural no se reescribe, TODO pedido con un mensaje `assistant` o con herramientas se bloquea con
  `structural_entity` (un Claude Code de 60 herramientas y 24 turnos: 206). ¿Qué se hace con las posiciones estructurales (N8)?
  → A: Dos reglas, solo bajo el enmascarado forzado y solo en las posiciones estructurales de la tabla de S14. (A) Los valores
  del **vocabulario cerrado del protocolo** (roles, `type` de bloque, `tool_choice.type`, `thinking.type`, `source.type` y
  `media_type`) no se analizan si están dentro del conjunto; uno fuera del conjunto se analiza como siempre. (B) En las posiciones
  de **vocabulario abierto** (nombres de herramienta, claves y nombres del esquema, ids y nombres de `tool_use`/`tool_result`) se
  ignoran solo los tipos de NER **semántico** (`PERSON`, `LOCATION`, `ORGANIZATION`, `NRP`, `URL`, `DATE_TIME`); los de patrón (DNI,
  CUIT, CBU, email, teléfono, tarjeta, IBAN…) y los propios de la empresa siguen bloqueando. Mensajes, `tool_result`, `thinking`,
  `system` y los subárboles libres no cambian. Vuelve a Sentinel por `HANDOFF` (costura S14, retrocompatible).

### Session 2026-10-07 (Cowork, etiqueta, OpenRouter y grupos)

<!-- Decisiones del owner por el coordinador Atlas tras la prueba de Claude Desktop/Cowork contra la guía y los arreglos
     de Sentinel. No reabren ninguna decisión anterior. Pregunta resuelta por el coordinador. -->

- Q: Bajo enmascarado forzado una imagen no es analizable y bloqueaba con `masking_required`: Cowork, que verifica su
  resultado con capturas devueltas dentro de un `tool_result`, se cortaba. ¿Qué se hace (R39)? → A: La alternativa más
  restrictiva que no rompe Cowork: las imágenes, los audios y los adjuntos binarios no analizables **dentro de un
  `tool_result`** (Anthropic; en OpenAI, el contenido de un mensaje `tool`) se reemplazan por una nota de texto neutra y el
  binario nunca sale hacia el proveedor; la auditoría lo registra como `unanalyzable_replaced` (conteo y nombres de tipo, sin
  contenido), que no suma a `unanalyzable`. Un PDF con texto devuelto por una herramienta sigue como texto enmascarado. Lo que
  adjunta la persona en su mensaje sigue bloqueando como hoy. Vuelve a Sentinel por `HANDOFF` (costura S14, retrocompatible).
- Q: ¿Qué etiqueta ve la persona por defecto en el selector de Claude Desktop (R40)? → A: El **id pedido** (`label_mode =
  requested`): nunca el destino. Cambia el default de la columna y del formulario del panel (migración que solo toca el
  default; las filas con `destination` o `custom` no se tocan) y ni `/v1/models` ni las respuestas filtran el nombre ni el
  modelo real del destino. Mostrar el destino o una etiqueta propia sigue siendo una elección por id.
- Q: ¿Se puede dar de alta Kimi K3 por OpenRouter desde «Dar de alta modelos» y moverle un id de Claude con una regla (R40)? → A:
  Sí, con el id real de la lista pública de OpenRouter, `moonshotai/kimi-k3`. El alta guiada tenía un hueco: OpenRouter exige
  los proveedores permitidos (FR-032) y el formulario no podía mandarlos; ahora los pide y los envía como
  `provider_options.providers_allowlist`. La ficha lleva la jurisdicción del proveedor final de esa lista, no la del agregador.
  Una regla mueve `claude-sonnet-…` de Azure a Kimi sin tocar el cliente.
- Q: No siempre son tres modelos: ¿cómo ven y usan modelos distintos los grupos de personas (R40)? → A: Con lo que ya existe, como
  dato: ids publicados y reglas con alcance de grupo, más el perfil de acceso por proveedor. Un grupo «Todos» ve los tres ids más
  uno extra que va a Kimi; un grupo «Solo Azure» solo ve los que van a Azure; `/v1/models` de cada llave lista solo lo suyo, un
  pedido al id de otro grupo da el error neutro sin nombrar destinos y un grupo restringido a Azure nunca llega a Kimi. No exige
  UI nueva ni modelo de datos nuevo.
- Q: Bajo el forzado, ¿qué pasa con las imágenes (R43)? Con R39 la que adjunta la persona bloqueaba y la de una herramienta se
  reemplazaba por una nota; cada instalación quiere decidirlo → A: Un ajuste de la instalación con dos valores, `MASKING_IMAGES`:
  **`pass`** (el **default de Eleia**) deja salir las imágenes tal cual —adjuntas y dentro de un `tool_result`—: no cuentan como no
  analizables, no bloquean y no se reemplazan; se auditan como `images_unmasked` (conteo y nombre de tipo, jamás contenido); el texto
  se sigue enmascarando completo y el contenido de la imagen **no** se enmascara (se documenta sin matices). **`filter`** es el
  comportamiento de R39. Un valor desconocido se trata como `filter`. El audio y los documentos no extraíbles siguen como hoy. La
  capacidad del destino se respeta: si no declara `images`, la adjunta sigue dando `400 capability_rejected: images` y la de una
  herramienta se cambia por la nota de capacidad, con cualquiera de los dos valores. Se configura **solo por instalación** (variable
  de entorno del motor, `.env.example`); por grupo o desde el panel **no** (exigiría un campo nuevo en la autorización firmada, el
  esquema y una migración: no es simple, queda como mejora). Vuelve a Sentinel por `HANDOFF` (costura S14, retrocompatible; allá
  el default lo decide Sentinel).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Claude Desktop y Claude Code con el modelo que elige la empresa (Priority: P1)

Un administrador de una empresa enciende la política para el grupo «Desarrollo», registra como
destinos dos modelos del catálogo de la instalación (por ejemplo dos modelos de Azure) con su
jurisdicción, y decide qué destino sirve cada tier (opus, sonnet, haiku). Un miembro del grupo
configura Claude Desktop (o Claude Code) contra la pasarela con su llave, ve los tiers con la
etiqueta que eligió el administrador, elige uno y trabaja con normalidad: conversa, usa
herramientas, recibe la respuesta en streaming. La herramienta cree que habla con el modelo
que pidió. El administrador ve en la auditoría qué id se pidió y qué destino respondió, sin
contenido.

**Why this priority**: es el pedido. Ejercita en una sola pasada las costuras, el interruptor,
el catálogo, el mapeo, la cara Claude y la auditoría; sin esto no hay nada que mostrar.

**Independent Test**: con la política encendida en un grupo, Claude Desktop y Claude Code
listan los tiers y completan una conversación con herramientas y streaming contra al menos un
destino Azure del catálogo; la auditoría registra id pedido y destino real. (Claude Desktop es
lo único verificado en vivo en Sentinel, el 4-oct; Claude Code no: HANDOFF §2.4.)

**Acceptance Scenarios**:

1. **Given** la política encendida para «Desarrollo» con el tier sonnet → destino A, **When**
   un miembro del grupo pide la lista de modelos con Claude Desktop o Claude Code, **Then** ve un modelo por
   tier configurado, con la etiqueta por defecto «Sonnet · servido por <destino>» y la ventana
   de contexto real del destino (ELEIA-057 ← SENTINEL-068 US3 esc. 1, FR-010, FR-012).
2. **Given** el mismo mapeo, **When** el miembro conversa con el id del tier sonnet, **Then**
   responde el destino A, la respuesta informa el id público pedido como modelo y la auditoría
   registra id pedido, destino real, cara y fidelidad (← 068 US1 esc. 3, FR-033, contrato
   cara-claude §POST paso 5).
3. **Given** el administrador cambia el destino del tier sonnet a B, **When** el miembro sigue
   trabajando sin tocar su equipo, **Then** los pedidos siguientes los responde B en menos de un
   minuto (← 068 US1 esc. 4, SC-009).
4. **Given** un id que no está publicado para su alcance (por ejemplo, un modelo nuevo que su
   versión de Claude Code trae de fábrica), **When** lo pide, **Then** se aplica la regla por
   tier si existe; si no, recibe «Modelo no disponible para tu organización» con la categoría
   de error que la herramienta entiende (← 068 Edge Cases, FR-011, contrato cara-claude §Errores).
5. **Given** un destino sin credencial válida o dado de baja, **When** un tier apunta a él,
   **Then** se usa el fallback configurado o el pedido falla con error claro; nunca se sirve en
   silencio con otro modelo (← 068 US1 esc. 7, FR-011).
6. **Given** cualquier llave, con la política encendida o apagada, **When** alguien intenta
   pedir un destino por su nombre interno o mandar su propia dirección de proveedor o
   credencial, **Then** el pedido se rechaza o esos datos se ignoran (← 068 FR-006a, D15).
7. **Given** Claude Code manda campos o cabeceras beta que un destino traducido no conoce
   (p. ej. `safeguards`, Diagnóstico #20), **When** el pedido va a ese destino, **Then** esos
   campos no llegan al destino y la conversación funciona; hacia un destino nativo, las
   cabeceras beta pasan por lista permitida (← 068 FR-022, FR-026; tasks de Sentinel T139, T094).
8. **Given** Claude Desktop abre con su sondeo de un token de salida, **When** el destino exige
   un mínimo mayor o un nombre de parámetro distinto (modelos recientes de Azure), **Then** el
   sondeo responde bien y la auditoría anota el ajuste (← 068 FR-022; 069 de Sentinel T183,
   T192; HANDOFF §2.2 pasos 7–8).

---

### User Story 2 - En otra empresa, la pasarela sigue siendo el middleware de hoy (Priority: P1)

En la misma instalación, otra empresa (o un grupo de la misma empresa) no tiene la política
encendida ni postura de residencia. Sus empleados usan Claude Code y Claude Desktop contra la
pasarela exactamente como hoy: mismo modo con llave del producto, mismo reenvío de suscripción,
misma lista de modelos, mismas respuestas, misma auditoría. Las costuras nuevas de la base no
cambian nada cuando no hay extensión registrada.

**Why this priority**: la base de Eleia se vende por su estabilidad; un porte que cambie el
comportamiento de quien no lo pidió es una regresión. Es la condición para poder mergear las
costuras antes que la extensión.

**Independent Test**: una batería de pedidos grabados hoy contra `/gw/v1/messages`,
`count_tokens` y `models` (con llave del producto y con suscripción) produce respuestas y filas
de auditoría idénticas con la extensión montada y la política apagada, y también sin extensión.

**Acceptance Scenarios**:

1. **Given** la política apagada (default de fábrica) y sin postura, **When** cualquier
   herramienta usa la pasarela, **Then** el comportamiento es idéntico al actual, incluida la
   lista de modelos (← 068 US1 esc. 1, FR-002, SC-001).
2. **Given** la base con las costuras y **sin** extensión registrada, **When** corre la suite de
   la base, **Then** queda verde sin cambios de tests existentes (← 068 D13 «sin plugin ⇒
   comportamiento idéntico», tasks de Sentinel T001–T011).
3. **Given** destinos registrados por otra empresa, **When** un usuario de esta empresa lista
   modelos, **Then** no aparecen (← 068 FR-002, FR-006a).
4. **Given** un usuario de un grupo sin la política, **When** pide un id publicado solo para
   «Desarrollo», **Then** el id no existe para él: recibe el mismo error de modelo inexistente
   que recibiría hoy (← 068 US1 esc. 6).

---

### User Story 3 - Residencia para América (Priority: P2)

El responsable de cumplimiento de una empresa de la línea América (por ejemplo, argentina)
define, para cada grupo o usuario, una
postura de residencia: **«solo jurisdicciones permitidas»** (una lista de jurisdicciones) o
**«fuera de región con enmascarado forzado»**. Con la primera, los empleados solo alcanzan
destinos cuya inferencia ocurre en las jurisdicciones permitidas; si el destino de un tier no
cumple, responde el primer fallback que cumpla o el pedido se rechaza sin salir; por defecto, la
lista pre-completada es la región `AMERICAS` (el continente americano). Con la
segunda, pueden usar destinos de otras jurisdicciones, pero los datos personales salen siempre
enmascarados y, si el analizador no está disponible, el pedido se bloquea. El administrador de
la empresa puede endurecer una postura, nunca relajarla.

**Why this priority**: sin esta capa, el sistema no puede decidir si un pedido que sale de la
región del perfil (en la línea América, el continente americano: FR-030) debe salir enmascarado
o no salir; con ella la redirección es vendible a clientes regulados de la región. La base
legal de cada transferencia la cubre el cliente por fuera del sistema (Assumptions).

**Independent Test**: dos usuarios de la misma empresa con posturas distintas piden el mismo
tier cuyo destino principal es de otra jurisdicción: el de *solo jurisdicciones permitidas* es
servido por el fallback que cumple (o rechazado si no hay); el de *fuera de región* es servido
por el principal con enmascarado verificado; con el analizador caído, el segundo se bloquea.

**Acceptance Scenarios**:

1. **Given** un usuario con *solo jurisdicciones permitidas* y un tier cuyo destino principal es
   de una jurisdicción no permitida con fallback permitido, **When** pide ese tier, **Then**
   responde el fallback y la auditoría registra la sustitución y su motivo (← 068 US2 esc. 1,
   FR-015).
2. **Given** el mismo usuario y ningún destino que cumpla, **When** pide el tier, **Then**
   recibe «Modelo no disponible para tu región» con categoría de permiso, sin nombrar destinos,
   y el pedido no sale (← 068 US2 esc. 2, contrato cara-claude §Errores, D19 punto 1).
3. **Given** un usuario con *fuera de región con enmascarado forzado*, **When** pide un destino
   de otra jurisdicción, **Then** los datos personales detectados salen enmascarados y vuelven
   restaurados en la respuesta, incluidos resultados de herramientas y adjuntos analizables
   (← 068 US2 esc. 3, FR-016, FR-016a).
4. **Given** ese mismo usuario y el analizador caído, **When** pide un destino de otra
   jurisdicción, **Then** el pedido se bloquea aunque la instalación diga «degradar»
   (← 068 US2 esc. 4, FR-016; constitución [D10]).
5. **Given** un intento de relajar el enmascarado por cualquier override (conexión, cabecera,
   configuración de la llave), **When** el pedido va a un destino con enmascarado forzado,
   **Then** sale enmascarado o se bloquea; nunca sale sin enmascarar. Solo una relajación
   explícita y registrada de cumplimiento, por destino o por región, quita el forzado (← 068 US2
   esc. 5, FR-016; Clarifications D2, FR-031a).
6. **Given** un usuario que entra con su suscripción personal (reenvío tal cual al proveedor
   original), **When** tiene postura, **Then** la redirección no aplica pero la postura sí, con
   la jurisdicción de ese proveedor (← 068 FR-001b).
7. **Given** el administrador de la empresa (no el de cumplimiento), **When** intenta borrar o
   relajar una postura fijada por cumplimiento, **Then** no puede; sí puede agregar una más
   estricta (← 068 FR-014a, data-model §1b).
8. **Given** una empresa de Eleia sin postura explícita y la redirección encendida, **When** un
   tier apunta a un destino Azure en una región de EE. UU. o de Brasil, o a uno en una región de
   la UE, **Then** en los dos casos se sirve con enmascarado forzado y, con el analizador caído,
   se bloquea (postura por defecto); **When** apunta a un destino sin jurisdicción de inferencia
   registrada, **Then** se rechaza con «Modelo no disponible para tu región» sin nombrar destinos
   (← 068 FR-014; Clarifications P2, P3, D2).
9. **Given** la misma empresa con la redirección apagada y sin postura, **When** usa la pasarela,
   **Then** nada cambia respecto de hoy (← 068 FR-002, FR-014).
10. **Given** un modelo de pesos abiertos alojado en EE. UU. por un alojador nombrado, con
    jurisdicciones de inferencia, entidad y control cargadas y retención cero declarada, **When**
    cumplimiento registra una relajación con motivo para ese destino, **Then** sus pedidos salen
    sin enmascarado forzado; **When** falta alguno de esos datos, **Then** la relajación se
    rechaza y el destino sigue con el enmascarado por defecto (Clarifications D5; FR-031a).
11. **Given** un destino con inferencia en EE. UU. operado por una entidad cuya jurisdicción de
    control está fuera de `AMERICAS` (o sin cargar), **When** cumplimiento relajó el forzado por
    la región `AMERICAS` o fijó *solo jurisdicciones permitidas* = `AMERICAS`, **Then** ese
    destino no cuenta como en región: con la relajación por región sigue enmascarado; con la lista
    no se alcanza, salvo aceptación registrada de cumplimiento (Clarifications D12; FR-028,
    FR-028a).

---

### User Story 4 - Claude Desktop y Cowork en sesiones largas y agénticas (Priority: P3)

Un empleado usa Claude Desktop (Chat, Cowork y la pestaña Code) configurado contra la pasarela,
con un destino de otra familia (por ejemplo un modelo GPT en Azure) detrás del tier que eligió.
La herramienta funciona sin errores de protocolo durante sesiones largas: usa herramientas
locales y archivos durante varios turnos, recibe respuestas largas sin cortes por inactividad,
se recupera de errores transitorios, compacta el contexto a tiempo y, en tareas agénticas de
muchos pasos, aprovecha la caché del proveedor para que el costo sea razonable.

**Why this priority**: es el caso de mayor visibilidad, pero depende de US1 y conviene que la
residencia (US3) exista antes de llevar tráfico corporativo a destinos de otra familia.

**Independent Test**: una batería de conversaciones grabadas de Claude Desktop, Cowork y Claude
Code (herramientas, archivos, sesiones largas, errores transitorios simulados) se completa sin
errores visibles contra al menos un destino traducido del catálogo de Azure (el nativo, cuando
haya credencial: Clarifications P5).

**Acceptance Scenarios**:

1. **Given** el tier sonnet → destino traducido, **When** el empleado usa Cowork con
   herramientas locales y varios turnos, **Then** las llamadas a herramientas y sus resultados
   funcionan y la conversación continúa sin errores de formato (← 068 US3 esc. 2, FR-022,
   FR-023).
2. **Given** una respuesta larga en la que el destino tarda en emitir contenido, **When** pasa
   el tiempo, **Then** la herramienta no corta la conexión por inactividad (← 068 US3 esc. 3,
   FR-024).
3. **Given** el destino devuelve saturación o límite de tasa, **When** la herramienta recibe la
   respuesta, **Then** la reconoce como reintentable y reintenta según su política (← 068 US3
   esc. 4, FR-025).
4. **Given** una función que el destino no soporta (por ejemplo, documentos PDF en un destino
   sin visión), **When** llega el pedido, **Then** la herramienta recibe un rechazo explícito y
   comprensible, no un fallo opaco (← 068 US3 esc. 5, FR-022).
5. **Given** un destino con ventana de contexto menor que la que la herramienta asume para ese
   nombre, **When** la sesión crece, **Then** la herramienta compacta a tiempo porque la lista de
   modelos informa la ventana real, sin errores de «prompt demasiado largo» visibles (← 068 US3
   esc. 6, FR-010).
6. **Given** el tier → destino nativo (misma familia de protocolo), **When** se usa cualquier
   función de la herramienta, **Then** el comportamiento es equivalente al del proveedor
   original, incluida la caché de prompts (← 068 US3 esc. 8, FR-026).
7. **Given** una tarea de Cowork de 10 o más pasos con datos personales enmascarados, **When**
   el destino tiene caché implícita, **Then** el historial enmascarado sale idéntico en cada paso
   y la mayor parte de la entrada se sirve desde la caché (← 068 FR-038–FR-040, SC-012).

---

### User Story 5 - Una CLI genérica con alias propios de la empresa (Priority: P3)

El administrador publica, para el grupo «Desarrollo», alias neutros propios («rápido», «pro»)
en la cara OpenAI genérica y decide qué destino del catálogo hay detrás de cada uno. Los
desarrolladores configuran su CLI o harness open-source apuntando a la pasarela como si fuera
una API OpenAI estándar (dirección, llave y modelo), ven la lista de alias y trabajan sin saber
qué proveedor responde. La auditoría registra alias pedido y destino real.

**Why this priority**: decisión del owner (Clarifications): entra en el MVP. Queda después de
la cara Claude porque Eleia no tiene la puerta de chat estándar y hay que portarla primero
(Diagnóstico #19).

**Independent Test**: con la política encendida en un grupo, una CLI genérica lista los alias y
completa una conversación con streaming y herramientas contra al menos un destino Azure del
catálogo; un usuario de otro grupo no ve los alias.

**Acceptance Scenarios**:

1. **Given** la política encendida para «Desarrollo» con el alias «pro» → destino A, **When** un
   miembro pide la lista de modelos con un cliente OpenAI, **Then** ve «pro» (y los demás alias
   de su alcance) y ningún nombre de proveedor (← 068 US1 esc. 2, contrato cara-generica §GET).
2. **Given** el mismo alias, **When** el miembro conversa con «pro», **Then** responde el destino
   A, la respuesta informa «pro» como modelo y la auditoría registra alias y destino (← 068 US1
   esc. 3, FR-020).
3. **Given** el administrador cambia el destino de «pro» a B, **When** el miembro sigue
   trabajando, **Then** los pedidos siguientes los responde B sin tocar su configuración
   (← 068 US1 esc. 4).
4. **Given** un alias que no existe para su alcance, **When** lo pide, **Then** recibe el error de
   modelo inexistente del formato OpenAI con código `model_not_found`; con postura sin destino
   que cumpla, `region_not_allowed` (← 068 contrato cara-generica §POST).
5. **Given** la puerta de chat estándar portada y la política apagada, **When** una herramienta la
   usa con su llave, **Then** se aplica la misma política de seguridad base que en
   `/gw/v1/messages` (bloqueos, secretos, enmascarado reversible, auditoría) y se sirve el modelo
   pedido sin redirección (← Sentinel spec 045, US3).

---

### Edge Cases

- Un id público publicado sin destino activo: la publicación se rechaza o el id queda inactivo
  con aviso; nunca se sirve con un destino implícito (← 068 Edge Cases).
- Un id publicado en dos alcances con destinos distintos: gana el más específico; la
  resolución es la misma en todos los planos (← 068 Edge Cases, FR-007).
- El destino principal y todos los fallbacks fallan o no cumplen la postura: error explícito de
  la cara, el pedido no sale (← 068 Edge Cases).
- El destino responde con formato inesperado a mitad del streaming: la herramienta recibe un
  error de la cara, nunca una respuesta truncada presentada como completa (← 068 Edge Cases,
  contrato cara-claude §Errores).
- La política cambia en medio de una sesión larga: los pedidos siguientes usan la configuración
  nueva y no se mandan a un destino rastros de razonamiento de otro (← 068 Edge Cases, FR-023).
- La caché de respuestas del motor (activa en Eleia, `litellm/config.yaml:19-25`) devolvería
  una respuesta de otro destino o con marcadores de otro pedido: no puede cruzar destinos ni
  mapas de enmascarado (← 068 FR-034).
- Una herramienta envía una función exclusiva del proveedor original (búsqueda web del
  proveedor, ejecución remota de código): se rechaza de forma explícita; nunca se ignora de un
  modo que la herramienta interprete como éxito (← 068 Edge Cases).
- Credenciales de la suscripción personal del empleado llegan con la política encendida: no se
  usan para destinos de otro proveedor (← 068 Edge Cases, contrato cara-claude §Errores 401).
- La herramienta no manda identificador de sesión: el pedido sale sin él y la caché depende solo
  del prefijo estable (← 068 FR-038).
- Dos conversaciones distintas (de la misma o de otra persona) con los mismos datos personales:
  sus marcadores no coinciden; solo son estables dentro de cada conversación (← 068 FR-040;
  Clarifications P4).
- Un destino sin jurisdicción de inferencia cargada: no satisface ninguna postura *solo
  jurisdicciones permitidas* y, con la postura por defecto, se rechaza; ninguna relajación lo
  habilita (← 068 FR-019a; Clarifications D2).
- Una nube operada por una entidad cuya jurisdicción de control está fuera de la región, con
  servidores en la región: no cuenta como en región para una lista ni para una relajación por
  región (FR-028a; Clarifications D12).
- El administrador de la empresa agrega una postura explícita (p. ej. *solo jurisdicciones
  permitidas*) mientras rige el enmascarado forzado en todo destino: la postura restringe a qué
  destinos se llega, pero no quita el forzado; solo una relajación de cumplimiento lo quita
  (FR-023, FR-031, FR-031a).
- El administrador de la empresa crea una postura *apagada* o *fuera de región con enmascarado
  forzado* menos estricta que la vigente: se rechaza y, si existiera, no amplía el alcance ni
  quita el forzado (FR-023).
- Bajo enmascarado forzado llega un PDF escaneado sin texto, una imagen o un bloque de tipo
  desconocido: el pedido se bloquea como no analizable; un PDF con texto sale convertido a texto
  enmascarado (FR-027).
- En el segundo turno la herramienta reenvía la respuesta del asistente ya restaurada (con los
  datos personales en claro): bajo forzado, ese turno se vuelve a enmascarar antes de salir
  (FR-027).
- La instalación arranca con la extensión activa sin la región sembrada o sin región del
  perfil: lo redirigido sale con enmascarado forzado o se rechaza, nunca en claro (FR-031).
- Alguien en la red local intenta alcanzar el canal interno del backend saltándose la pasarela:
  no responde (FR-013).
- Una empresa con perfil Argentina y otra con otro perfil en la misma instalación: cada una
  resuelve con sus jurisdicciones sin afectar a la otra (← 068 Edge Cases).
- Una costura de base que no se puede portar tal cual porque la base de Eleia difiere de la de
  Sentinel: se registra como adaptación con plan de salida y se informa por `HANDOFF`; no se
  bifurca en silencio (← 068 tasks de Sentinel T012).

## Requirements *(mandatory)*

### Functional Requirements

**A. Costuras de base y paquete de la extensión (Phase 0 de la 068 + HANDOFF §1)**

- **FR-001** [BASE]: La base DEBE incorporar las costuras genéricas de la tabla C-1, portadas
  desde los commits de Sentinel en el orden del HANDOFF §1(a), cada una sin marca ni nombres de
  Eleia y retrocompatible: sin extensión registrada y sin la variable que la activa, el
  comportamiento DEBE ser idéntico al actual, demostrado por un test de no-regresión por
  costura. (ELEIA-057 ← SENTINEL-068 research D13; tasks de Sentinel T001–T007, T011; HANDOFF §1(a) filas 1–17)
- **FR-002** [BASE]: La costura S10 NO DEBE portarse; la lista de modelos permitidos de la llave
  se resuelve en la pasarela (FR-016). S5a (política sobre `/v1/responses`) NO entra en el MVP:
  es de la cara Codex y choca con el arreglo propio de Eleia de la spec 050. (← 068 research
  R13, tasks de Sentinel T009; HANDOFF §1(a) «No hacen falta para el mínimo»)
- **FR-003** [BASE]: Toda costura o adaptación que no pueda portarse tal cual DEBE quedar
  registrada en el registro de cambios propio de Eleia (el de Sentinel no existe aquí) con plan
  de salida, y lo que Eleia escriba de nuevo en la base compartida (S9/S11, S13, filtro de campos de
  Claude Code, residencia América, región → jurisdicciones como dato, semáforo por perfil, alcance
  completo del enmascarado forzado y bloqueo de lo no analizable, respaldo en código de la postura
  por defecto, permisos de filas y ficha, cierre del canal interno) DEBE entregarse a Sentinel en
  `HANDOFF-elea-a-sentinel.md`; ningún archivo del repositorio de Sentinel se edita desde Eleia.
  (← 068 tasks de Sentinel T012; HANDOFF §4.3)
- **FR-004** [BASE]: Las respuestas de la pasarela que esta feature toca, incluida su pantalla
  de descubrimiento, NO DEBEN nombrar componentes internos (Diagnóstico #16). (← 068 FR-035)
- **FR-004a** [BASE]: El paquete de la extensión DEBE portarse **tal cual** desde Sentinel
  6a70855 (redirección, motor, catálogo, acceso, común, páginas del panel y entrega), sin el
  asistente de alta de Sentinel ni su migración, y conservando nombres internos, ids de
  migración y nombres de tabla para que las dos líneas sigan sincronizables; esos nombres no son
  visibles al cliente. (← HANDOFF §1(b), §4.5)
- **FR-004b** [BASE]: Las migraciones de la extensión DEBEN vivir en su propia rama con etiqueta
  y aplicarse solo con la variable que la habilita; sin ella la cadena de la base conserva una
  sola cabeza. No se porta ninguna migración del backend de Sentinel. Volver a una versión sin la
  extensión después de aplicarla no está soportado y la documentación de operación lo advierte.
  (← 068 tasks de Sentinel T004, T028; HANDOFF §1(c), riesgo de rollback)
- **FR-004c** [BASE]: El camino de despliegue de Eleia DEBE entregar las extensiones del motor y
  fusionar el fragmento de perfil de la extensión (equivalente de S9 y S11, que Sentinel tampoco
  hizo y reemplaza con su script propio), con el contrato de fusión de la 068 (agregar al final;
  duplicados ⇒ error); sin la extensión activada, el render y el paquete quedan idénticos.
  (← 068 research D13 S9/S11, tasks de Sentinel T008, T010, T015, T019; HANDOFF §2.1)
- **FR-004d** [BASE + ELEIA]: Lo que Eleia publica DEBE poder llevar la extensión a una
  instalación hecha con su instalador: variantes derivadas de las imágenes del backend, del panel
  y del motor, con tag propio y sin cambiar las imágenes base; el backend publicado DEBE aplicar
  las migraciones adicionales cuando la variable que las habilita está definida y NO DEBE
  arrancar si esa migración falla (sin la variable, igual que hoy). [ELEIA] El instalador DEBE
  ofrecer una activación opt-in que elija las variantes, escriba el entorno de la extensión sin
  secretos versionados y con permisos restringidos, y cargue los datos sembrados; sin la
  activación, la instalación queda idéntica (el proxy delante del backend y el chequeo de origen
  del canal interno, que rigen para toda instalación, no son parte de la activación: FR-013). La entrega se valida primero en local con el mismo
  instalador y después en el servidor, con un procedimiento de vuelta atrás escrito
  (Clarifications, QA del plan, B1).

**Tabla C-1 — Costuras requeridas** (todas [BASE]; contrato genérico de la 068 research D13;
commits de Sentinel según HANDOFF §1(a))

| Costura | Qué permite a una extensión | Hoy en Eleia | Commits de Sentinel |
|---|---|---|---|
| S1 | Montar sus propias rutas de API | Diagnóstico #2 | `6161bf0` |
| S2 | Intervenir la pasarela antes del pedido (puede responder), antes del motor, sobre el stream, sobre la respuesta no-stream, sobre la lista de modelos (siempre activo), sobre los errores, sobre las cabeceras reenviadas, y en el camino de suscripción forzar enmascarado y verificar su resultado; resolver la identidad de la llave también en `models` y `count_tokens`; pasar su decisión de ruteo a la auditoría | Diagnóstico #3 | `e3a5297`, `faf94de`, `5a2d1aa`, `66dfa61`, `0669e03` |
| S2-OpenAI | La puerta de chat estándar (cara genérica) con el mismo cableado de enganches | Diagnóstico #19 | `9c17500`, `efb2c94` (HANDOFF Anexo A) |
| S3 | Agregar páginas y entradas de menú del panel, y reemplazar un ítem del menú base | Diagnóstico #4 | `f63144d`, `adb53d9`, `1d8a3b7` (ADAPT-026) |
| S4 | Agregar sus migraciones sin romper la cadena única de la base | Diagnóstico #5 | `1021c8e` |
| S5b | Que el guardrail deje siempre un informe de enmascarado {completado, degradado, detectadas, enmascaradas} | Diagnóstico #6 | `1a454ed` |
| S6 | Declarar entradas del motor ocultas: no se listan, no se borran, no entran al catálogo del ruteo automático | Diagnóstico #7 | `7a4f65c` |
| S7 | Persistir la decisión de ruteo escrita solo por guardrails del motor (descarta la del cliente), con un espacio acotado para extensiones | Diagnóstico #8 | `9c7bf08`, `8ceab22` |
| S9 / S11 | Entregar extensiones extra del motor y fusionar fragmentos de perfil | Diagnóstico #9, #10, #24 | sin commit en Sentinel (FR-004c) |
| S12 | Pasar variables de entorno propias a backend y motor sin listarlas en la base | Diagnóstico #11 | `933c513`, `891d4d0` (doc) |
| Cifrado | Cifrado con rotación de claves y descifrado estricto, que usa el catálogo para las credenciales | — | `14edbc7`, solo dos archivos (ADAPT-024) |
| S13 | Que el sufijo de los marcadores de enmascarado sea estable dentro de una conversación (por un identificador de conversación que provee la extensión) sin dejar de ser impredecible | No existe | sin commit en Sentinel (068 research D22, Phase 9); nueva, vuelve por `HANDOFF` (FR-045) |
| S14 | Que, cuando una extensión pide enmascarado forzado, el guardrail cubra todo el pedido (sistema, todos los turnos, herramientas, PDF convertidos a texto) e informe lo no analizable | Solo turnos del usuario (`litellm/extensions/sentinel_guardian_policy.py:880-892`) | sin commit en Sentinel (068 tasks de Sentinel T074 abierta); nueva, vuelve por `HANDOFF` (FR-027) |
| S15 | Que el canal interno del backend exija, además del secreto, un origen de la red interna | Solo el secreto (`backend/src/api/internal.py:120-127`) | **dependencia**: la entrega el arreglo de separación de bases (para toda instalación); vuelve por `HANDOFF` (FR-013) |
| S16 | Correr un enganche propio al arrancar, antes de servir el primer pedido (p. ej., cargar sus datos sembrados) | No existe: S1 solo monta rutas y la app arranca con `lifespan` (`backend/src/main.py:80-101`) | sin commit en Sentinel; nueva, vuelve por `HANDOFF` (FR-031; Clarifications, QA v2) |

**B. Interruptor y alcance**

- **FR-005** [BASE]: La política DEBE estar apagada por defecto y poder encenderse por empresa,
  grupo, usuario y conexión (llave); gana el alcance más específico; una única función de
  resolución sirve a todos los planos; se administra en una página propia del panel enlazada
  junto a Gobernanza. (← 068 FR-001)
- **FR-006** [BASE]: La política aplica solo a la pasarela; el chat de la consola queda fuera y
  conserva su control de residencia actual. [ELEIA] El Hub de usuarios también queda fuera.
  (← 068 FR-001)
- **FR-007** [BASE]: Con la redirección apagada y sin postura para un pedido, el sistema DEBE
  comportarse de forma idéntica a la versión anterior en todas las superficies existentes,
  incluida la lista de modelos. (← 068 FR-002)
- **FR-008** [BASE]: Todo cambio de estado de la política, del catálogo, de las reglas o de las
  posturas DEBE quedar registrado con autor, rol, momento, alcance, motivo y antes/después sin
  secretos. (← 068 FR-004, data-model §6b)
- **FR-009** [BASE]: Si la resolución de la política o del catálogo falla con la política
  encendida, el pedido DEBE rechazarse con error de la cara (reintentable), nunca servirse sin
  política. (← 068 FR-004a, contrato cara-claude §Errores 503)
- **FR-010** [BASE]: Los estados de la política en el MVP son *apagada* y *encendida*; el estado
  *sombra* queda reservado para la fase F6 y no se ofrece en el panel. (← 068 FR-003; recorte
  propio del MVP)

**C. Catálogo, destinos y mapeo**

- **FR-011** [BASE]: El administrador DEBE poder dar de alta destinos sin reiniciar la
  instalación, solo por el catálogo de la extensión: desde la 069 de Sentinel, los destinos de
  la redirección son las entradas de ese catálogo (Diagnóstico #21). Si el panel usa la pantalla
  única de modelos de la extensión, esta reemplaza el ítem de menú de modelos de la base por la
  costura S3; si no, se publican como páginas propias (se decide en el plan). El mecanismo se
  porta con la lista completa de proveedores de la 068.
  [ELEIA] La aceptación del MVP se verifica **solo con destinos del catálogo de Azure** de la
  instalación (traducidos para la cara Claude, nativos para la genérica); los demás proveedores
  portados, y los destinos nativos de la cara Claude, se documentan 🟡 hasta tener credencial
  y verificación (Clarifications P5). (← 068 FR-005, data-model §2; HANDOFF §1(b) `sentinel/catalog`, ADAPT-026)
- **FR-012** [BASE]: Los destinos DEBEN poder darse de alta a nivel instalación (super-admin,
  ofrecibles a una, varias o todas las empresas) y a nivel empresa (administrador de la
  empresa, con credenciales propias, visibles solo en esa empresa); retirar una oferta pasa los
  mapeos a su fallback o los deja inactivos con aviso. (← 068 FR-005a, FR-005b)
- **FR-013** [BASE]: Las credenciales de destino DEBEN guardarse cifradas, no aparecer en claro en
  la configuración del motor, logs, respuestas de API ni pantallas después de cargadas, y poder
  rotarse o revocarse con efecto inmediato. El canal interno por el que el motor pide identidad,
  catálogo o credenciales al backend DEBE ser alcanzable solo desde la red interna de la
  instalación y con el secreto compartido; la ruta que entrega una credencial descifrada DEBE
  responder «no encontrado» salvo que la ruta directa del catálogo esté encendida, y ningún
  despliegue publica ese canal fuera de la red interna (Clarifications, QA del plan, A10). El
  chequeo de origen y el proxy del instalador son una **dependencia** (los entrega el arreglo de
  separación de bases para toda instalación); esta feature agrega el cierre de la ruta de
  credenciales y verifica que la variante con la extensión no salte esas capas.
  (← 068 FR-005c, FR-006)
- **FR-014** [BASE]: Un destino NO DEBE ser alcanzable nombrándolo directamente con ninguna
  llave, también con la política apagada; ningún dato del cliente (dirección de proveedor,
  credenciales, cabeceras de autenticación) puede cambiar a dónde ni con qué credencial sale un
  pedido redirigido; los destinos no aparecen en ninguna lista de modelos. (← 068 FR-006a, D15)
- **FR-015** [BASE]: El administrador DEBE poder publicar, por cara y por alcance, ids públicos
  (nombres con tier en la cara Claude; alias neutros propios en la cara genérica) y mapear cada
  uno a un destino principal con fallbacks ordenados; los ids de distintos alcances se unen y
  para un mismo id gana el más específico; en la cara Claude, un id no publicado cae a la regla
  por tier si existe. (← 068 FR-007, data-model §4–§5)
- **FR-016** [BASE]: Si la llave del empleado tiene lista de modelos permitidos, esa lista DEBE
  evaluarse sobre el id público; el destino interno queda autorizado solo por la resolución de
  la política de ese pedido. (← 068 FR-010a)
- **FR-017** [BASE]: El sistema DEBE clasificar cada mapeo como *Nativo* o *Traducido* y mostrar,
  para los traducidos, qué funciones de la cara no soporta el destino. (← 068 FR-009,
  data-model §3)
- **FR-018** [BASE]: Un pedido a un id no publicado para el alcance, o cuyo destino y fallbacks
  no están disponibles, DEBE fallar con error de la cara, sin sustitución silenciosa.
  (← 068 FR-011)
- **FR-019** [BASE]: La etiqueta visible de cada id DEBE ser configurable; por defecto indica el
  destino real («<Tier> · servido por <destino>») sin tocar el id que la herramienta necesita; el
  cambio queda registrado. (← 068 FR-012)
- **FR-020** [ELEIA]: Los modelos de Azure del catálogo de la instalación DEBEN poder registrarse
  como destinos (con su jurisdicción de inferencia cargada y con el modelo real igual a un
  despliegue existente del recurso de Azure) sin duplicar credenciales ni editar el perfil del
  motor, y la instalación de demo DEBE traerlos como dato de ejemplo editable, nunca como código.
  Un destino cuyo modelo real no corresponde a un despliegue DEBE detectarse al registrarlo o
  fallar con error claro, no con el «recurso no encontrado» opaco de hoy. (Sin FR directo en la
  068; deriva de 068 FR-005, FR-019, de la 069 de Sentinel T178, HANDOFF §4.1, y del Principio IV
  de la constitución, onboarding como datos)

**D. Residencia (línea América)**

- **FR-021** [BASE]: El sistema DEBE tratar la jurisdicción de inferencia de cada destino como
  dato (zonas y países), sin reglas de región fijas en el comportamiento; un país satisface a su
  zona, una zona no satisface a un país. (← 068 FR-013, `sentinel/redirect/residency.py`)
- **FR-022** [BASE]: El responsable de cumplimiento DEBE poder asignar por empresa, grupo,
  usuario o conexión una postura: *apagada*, *solo jurisdicciones permitidas* (lista) o *fuera
  de región con enmascarado forzado*. (← 068 FR-014)
- **FR-023** [BASE]: Solo el responsable de cumplimiento o el super-admin DEBEN poder fijar o
  relajar una postura; el administrador de la empresa solo puede endurecerla (agregar filas);
  todo cambio lleva autor y motivo. Permisos por acción según 068 FR-014b. Una fila del
  administrador de la empresa solo restringe: la postura efectiva es la más estricta entre la
  que fijan cumplimiento o el super-admin (o la postura por defecto, si no fijaron ninguna) y las
  filas del administrador, y una fila suya menos estricta que la efectiva de ese alcance se
  rechaza; tampoco quita el enmascarado forzado que impone la postura de cumplimiento o del
  super-admin (restringe el alcance, nunca el forzado). Regiones, postura por defecto y relajaciones exigen el rol real de cumplimiento o de
  super-admin, nunca una autoridad de instalación derivada de una variable de entorno; la
  entidad responsable, las jurisdicciones de inferencia, de entidad y de control y la retención
  cero de la ficha del destino solo las escriben cumplimiento y el super-admin
  (Clarifications, QA del plan, A6–A8). (← 068 FR-014a, FR-014b)
- **FR-024** [BASE]: La postura DEBE aplicarse a todo el tráfico de pasarela del alcance, con la
  redirección encendida o apagada; si varios alcances definen postura, rige la más restrictiva
  (apagada < fuera de región con enmascarado forzado < solo jurisdicciones permitidas; entre
  listas, la intersección); con *solo jurisdicciones permitidas*, los modelos no registrados como
  destino con jurisdicción quedan inalcanzables. (← 068 FR-001a)
- **FR-025** [BASE]: En el camino de suscripción personal, la redirección NO aplica y la postura
  SÍ, con la jurisdicción del proveedor original; el enmascarado forzado exige enmascarado con
  analizador real o el bloqueo. (← 068 FR-001b)
- **FR-026** [BASE]: Con *solo jurisdicciones permitidas*, ningún pedido DEBE llegar a un
  destino de otra jurisdicción; se usa el primer fallback que cumpla o se rechaza con categoría
  de permiso sin nombrar destinos. (← 068 FR-015, contrato cara-claude §Errores 403, D19 punto 1)
- **FR-027** [BASE]: Siempre que el enmascarado sea forzado (postura *fuera de región con
  enmascarado forzado* para todo pedido a otra jurisdicción, o la postura por defecto de FR-031),
  el enmascarado DEBE estar activo y en modo bloqueo ante caída del analizador, sin que ningún
  override del cliente, de la conexión, de las cabeceras ni de la llave pueda relajarlo; solo
  cumplimiento puede quitar el forzado, de forma explícita y registrada, por destino o por
  región (FR-031a), y mientras el forzado rija el fail-closed no se relaja. La garantía se
  verifica donde ocurre el enmascarado y cubre **todo lo que sale hacia el destino** (todo valor de
  texto del pedido, salvo una lista cerrada de campos estructurales como el modelo, los roles, los
  tipos, los identificadores y los nombres de herramientas): las
  instrucciones de sistema (texto y bloques), todos los turnos de la conversación (del usuario y
  del asistente, incluido lo que la herramienta reenvía ya restaurado), las entradas y los
  resultados de herramientas, el razonamiento, las descripciones de herramientas y los
  adjuntos. Los PDF se convierten a texto, se enmascaran y salen como texto enmascarado; lo no
  analizable (PDF sin texto extraíble, imágenes con el ajuste `filter` —con `pass`, el default, salen tal cual—, tipos desconocidos, o un razonamiento firmado
  con identificadores hacia un destino nativo, que no se puede enmascarar sin invalidar la firma)
  bloquea el pedido (Clarifications, QA del plan, B3; el reconocimiento de texto en imágenes es
  una fase siguiente). **Excepción** (Clarifications 2026-10-07, R39): una imagen, un audio o un
  documento ilegible que **devuelve una herramienta dentro de un `tool_result`** (la captura con la que
  Cowork revisa su resultado) NO bloquea: se reemplaza por una nota de texto neutra —el binario nunca
  sale hacia el destino— y la auditoría registra `unanalyzable_replaced` (conteo y nombres de tipo, sin
  contenido), que no suma a lo no analizable; lo que **adjunta la persona** en su mensaje sigue
  bloqueando. **Ajuste de imágenes** (Clarifications 2026-10-07, R43): `MASKING_IMAGES` = `pass` (default de Eleia) o `filter`. Con
  `pass`, las imágenes —adjuntas y dentro de un `tool_result`— salen tal cual: no son no analizables, no bloquean ni se
  reemplazan, y la auditoría registra `images_unmasked` (conteo y tipo, sin contenido); el texto se sigue enmascarando completo.
  Con `filter` rige lo anterior (la que adjunta la persona bloquea, la de una herramienta se reemplaza). Lo decide la
  instalación, no el pedido; la capacidad `images` del destino se respeta con los dos valores. (← 068 FR-016, FR-016a, D16; Clarifications D2)
- **FR-028** [BASE]: Cada destino DEBE registrar su jurisdicción de inferencia y la de su entidad
  responsable; sin jurisdicción de inferencia, no satisface ninguna lista y, con la postura por
  defecto, se rechaza; la categoría «procesado en región, entidad de otra jurisdicción» no
  satisface una lista salvo aceptación registrada de cumplimiento, y no cuenta como en región
  para una relajación por región. Un pedido redirigido a un destino sin jurisdicción de
  inferencia se rechaza con cualquier postura, fila o relajación (Clarifications, QA del plan,
  A8). (← 068 FR-018, FR-019, FR-019a; Clarifications D2)
- **FR-028a** [BASE]: Cada destino DEBE registrar, como dato, su **entidad responsable** (quien
  opera la inferencia), la **jurisdicción de esa entidad** y su **jurisdicción de control** (la de
  quien posee el 50 % o más de la entidad o la controla), además de la jurisdicción de inferencia.
  Un destino cuenta como «en región» solo si las jurisdicciones de inferencia, de entidad y de
  control están dentro de la región; si la de inferencia está dentro pero la de entidad o la de
  control está fuera, o la de control no está cargada, cae en la categoría «procesado en región,
  entidad de otra jurisdicción» de FR-028 y sigue usable con la postura por defecto. Ningún código fija una jurisdicción de preocupación: son dato (reglas de
  FR-029). (Sin FR en la 068; decisión del owner D12, Clarifications 2026-10-06; vuelve a
  Sentinel por `HANDOFF`)
- **FR-029** [BASE]: Los destinos de proveedores que procesan sin garantías equivalentes DEBEN
  poder quedar bloqueados por defecto mediante reglas por datos (proveedor, host de la API o
  jurisdicción de inferencia, de entidad o de control) y requerir habilitación explícita y
  registrada con motivo; la paridad con Sentinel es la regla `provider: deepseek`. [ELEIA] En
  Eleia las reglas se siembran **vacías**: ningún destino nace bloqueado y todo es configurable
  desde el panel; a todo destino redirigido le rige la postura por defecto (FR-031). (← 068
  FR-017; Clarifications D1)
- **FR-030** [ELEIA]: En la línea América, «mi región» DEBE ser el **continente americano
  completo** (Norte, Centro, Caribe y Sur: Argentina, Colombia, EE. UU., Brasil, México y el
  resto de América), sembrado como **lista de jurisdicciones editable** (dato, no código) bajo un
  nombre genérico, `AMERICAS`, que sirve a cualquier instalación de la línea y no solo a
  Argentina. El panel usa esa lista para pre-completar las posturas *solo jurisdicciones
  permitidas*, y es la región de la relajación por región (FR-031a); por defecto, el tráfico
  redirigido sale enmascarado también hacia destinos de la región (FR-031). `AMERICAS` es un **criterio de
  riesgo, no de legalidad**: el panel y la documentación no la presentan como cobertura legal ni
  dicen «cumple con X», llaman al enmascarado «seudonimización reversible de identificadores
  detectados» (nunca «anonimización») y marcan la residencia 🟡 hasta la revisión legal. Las
  entidades de datos personales siguen siendo las del perfil `latam_ar` (Diagnóstico #14). El
  mecanismo de Sentinel no cambia (listas de jurisdicciones como dato, FR-021). El marco
  normativo mostrado en el panel y en la documentación es la Ley 25.326/AAIP. (← 068 FR-013,
  FR-014, data-model §0; Clarifications P2, D3, D10)
- **FR-030a** [BASE]: El indicador de admisibilidad del catálogo (semáforo y ficha del destino)
  DEBE evaluarse contra la residencia del perfil de país de la instalación o de la empresa, no
  contra una regla fija «admisible UE» (Diagnóstico #21). [ELEIA] En Eleia se evalúa contra la
  región `AMERICAS`. (← 068 FR-013; HANDOFF §4.2; el cambio al mecanismo vuelve por `HANDOFF`)
- **FR-031** [BASE + ELEIA]: Sin postura explícita, el tráfico no redirigido queda *apagado*
  (FR-007) y los pedidos redirigidos se rigen por la **postura por defecto** de la región de la
  empresa (si no tiene, la de la instalación). [BASE] La postura por defecto es un dato
  configurable de la región: *rechazo fuera de región* (solo la jurisdicción de la región; el
  valor de fábrica, paridad con Sentinel), *enmascarado forzado fuera de región*, *enmascarado
  forzado en todo destino* o *permitido*; la fija y cambia solo cumplimiento o el super-admin, con
  registro (FR-008, FR-023). Una postura explícita de cumplimiento o del super-admin la reemplaza
  en a qué destinos se llega (una del administrador de la empresa solo restringe, FR-023), pero
  **no quita el enmascarado forzado** que la postura por defecto impone: ese forzado es un piso que
  solo quita una relajación (FR-031a); así, agregar una postura explícita nunca relaja. Con
  cualquier valor, un destino sin jurisdicción de inferencia registrada se rechaza. **Respaldo en
  código** [BASE]: si para un pedido redirigido no hay región del perfil cargada que lo resuelva
  (sin datos sembrados o con la fila borrada), rige enmascarado forzado en todo destino, con
  analizador fail-closed y el alcance limitado a las jurisdicciones que el código asocia a la región
  del perfil (p. ej., `latam_ar` ⇒ LATAM y AR) si la región se conoce; si la región del perfil no se resuelve, todo lo redirigido se rechaza y el estado de la
  extensión lo informa; nunca sale en claro por falta de datos; mientras rige el respaldo, ninguna
  postura explícita, de ningún rol, quita el forzado ni amplía ese alcance (Clarifications, QA del
  plan, B2). Con la extensión activa, el seed de la región se carga al arrancar por la costura S16;
  si falla, rige el respaldo y el estado de la extensión lo informa (Clarifications, QA v2).
  La correspondencia región →
  jurisdicciones DEBE leerse de un dato del perfil de país, no de una tabla fija en el código (hoy
  `latam_ar` → `{AR, LATAM}`, Diagnóstico #22); el cambio es genérico y vuelve a Sentinel por
  `HANDOFF`, donde cierra el D19 punto 2 que quedó diferido a su 069. [ELEIA] En Eleia, la región
  del perfil resuelve a la lista `AMERICAS` de FR-030 y su postura por defecto es **enmascarado
  forzado en todo destino**, con analizador fail-closed, dentro y fuera de `AMERICAS`. (← 068
  FR-014, D19 punto 2, data-model §0; Clarifications P3, D2)
- **FR-031a** [BASE]: Cumplimiento o el super-admin DEBEN poder relajar el enmascarado forzado
  (el de la postura por defecto y, por destino, también el de una postura explícita) de forma
  explícita, con motivo y registrada (FR-008): **por región** (cambiar la postura por defecto de
  la región, de la instalación o de una empresa, de *enmascarado forzado en todo destino* a
  *enmascarado forzado fuera de región*: los destinos en región según FR-028a salen sin forzado) o
  **por destino** (una relajación sobre una entrada del catálogo). La relajación por destino DEBE
  exigir jurisdicciones de inferencia, de entidad y de control cargadas, retención cero declarada en la ficha y, en
  destinos agregadores, una lista de proveedores permitidos no vacía; nunca es un default. Ninguna
  relajación habilita un destino sin jurisdicción de inferencia, relaja el fail-closed mientras el
  forzado rija, ni vuelve alcanzable un destino fuera de una postura *solo jurisdicciones
  permitidas*. El administrador de la empresa no puede relajar (FR-023). [ELEIA] El caso típico en
  Eleia son los modelos de pesos abiertos alojados en América por alojadores nombrados con
  retención cero. (Sin FR en la 068; Clarifications D2, D5; vuelve a Sentinel por `HANDOFF`)
- **FR-032** [BASE]: Para destinos vía OpenRouter, el sistema DEBE exigir en cada pedido cero
  retención de datos y la lista de proveedores permitidos del administrador. (← 068 FR-018)

**E. Cara Claude**

- **FR-033** [BASE]: La cara Claude DEBE permitir que Claude Desktop (Chat, Cowork, Code) y
  Claude Code descubran y usen los ids publicados por tier con el destino elegido; DEBE aceptar
  la llave por `Authorization: Bearer` y por `x-api-key`, el sufijo `?beta=true` y el sondeo de
  calentamiento de Claude Desktop. (← 068 FR-021, contrato cara-claude §Rutas auxiliares)
- **FR-034** [BASE]: La lista de modelos de la cara Claude DEBE contener solo los ids publicados
  para el alcance del que pide, en el formato que la herramienta espera, con tier, etiqueta y
  ventana real del destino; nunca redirige; responde en menos de 1 s. (← 068 FR-010, contrato
  cara-claude §GET models)
- **FR-035** [BASE]: Para destinos traducidos, el sistema DEBE adaptar o rechazar explícitamente
  las funciones que la herramienta manda asumiendo el proveedor original (razonamiento, gestión
  de contexto, marcas de caché, mensajes de sistema intermedios, límites de salida, documentos);
  el destino nunca recibe un pedido inválido por esa causa. Esto incluye no reenviar a un destino
  traducido campos que no conoce (p. ej. `safeguards`, Diagnóstico #20), subir el mínimo de
  tokens de salida cuando el destino lo exige y usar el nombre de parámetro de límite de salida
  que el destino espera, dejando el ajuste en la auditoría. (← 068 FR-022; tasks de Sentinel T089, T139; 069
  de Sentinel T183, T192; HANDOFF §2.2, §2.4. T139 no está hecha en Sentinel: se escribe genérica
  y vuelve por `HANDOFF`)
- **FR-036** [BASE]: El sistema DEBE mantener la continuidad de la conversación entre turnos
  aunque el destino no produzca los mismos artefactos que el proveedor original (rastros de
  razonamiento con firma) y devolverle al destino lo que necesite. (← 068 FR-023, D7)
- **FR-037** [BASE]: El sistema DEBE mantener viva la conexión de streaming mientras el destino
  no emite contenido (señal de vida cada 15 s como máximo). (← 068 FR-024, D4)
- **FR-038** [BASE]: Los errores DEBEN llegar con la forma y la categoría que la herramienta usa
  para decidir reintentos (saturación, límite de tasa con espera sugerida de 60 s como máximo,
  pedido inválido, función no soportada); un error después del inicio del stream se emite como
  evento de error y cierra el stream. (← 068 FR-025, contrato cara-claude §Errores)
- **FR-039** [BASE]: La respuesta DEBE informar como modelo el id público pedido, con el uso de
  tokens completo (entrada, salida, caché leída y escrita; 0 si el destino no informa) y el
  orden de eventos garantizado del contrato. (← 068 contrato cara-claude §POST pasos 5–6)
- **FR-040** [BASE]: Para destinos nativos, el sistema NO DEBE degradar funciones que el destino
  soporta, incluida la caché de prompts, y DEBE reenviar las cabeceras beta por lista permitida;
  hacia traducidos, las cabeceras beta se descartan. (← 068 FR-026, contrato cara-claude §Rutas
  auxiliares; tasks de Sentinel T094, no hecha en Sentinel)
- **FR-041** [BASE]: El conteo de tokens DEBE reenviarse para destinos nativos y, para
  traducidos, estimarse localmente o responder «no encontrado» para que la herramienta estime.
  Mientras rige el enmascarado forzado, el conteo **nunca** se reenvía (tampoco a nativos ni en el
  camino de suscripción): se estima localmente o responde «no encontrado», porque su cuerpo es la
  conversación entera (FR-027; QA re-análisis U2).
  (← 068 contrato cara-claude §count_tokens; tasks de Sentinel T093, no hecha en Sentinel)
- **FR-042** [BASE]: Con la política encendida, una credencial de suscripción personal hacia un
  destino de otro proveedor DEBE rechazarse como error de autenticación. (← 068 contrato
  cara-claude §Errores 401)

**E2. Cara OpenAI genérica (decisión del owner en el clarify)**

- **FR-053** [BASE]: Eleia DEBE incorporar la puerta de chat estándar de la pasarela
  (`/gw/v1/chat/completions`, con streaming y herramientas) portada tal cual desde Sentinel: solo
  con llave del producto, sin traducir formatos y sin segunda política (la política de seguridad
  base del motor se aplica igual que en `/gw/v1/messages`), con el cableado de enganches de S2.
  No se trae el des-enmascarado de chunks de Sentinel (`9fe188f`): rige el equivalente que Eleia
  ya tiene (`f8118e7`, spec 050). Al agregar la ruta, la referencia publicada de la API DEBE
  regenerarse. (← Sentinel spec 045 US3 y su `gateway_openai.py`; 068 research D13 S2, tasks
  T016–T017; HANDOFF Anexo A, A.1–A.3)
- **FR-054** [BASE]: La cara genérica DEBE funcionar con los harness de referencia de la 068
  (opencode, Aider en modo OpenAI, Continue, Cline/Roo, Zed) sin configuración especial más allá
  de dirección, llave y modelo; el modelo informado en la respuesta DEBE ser el alias pedido.
  (← 068 FR-020, contrato cara-generica §Harness de referencia, §POST)
- **FR-055** [BASE]: La lista de modelos para un cliente OpenAI DEBE contener solo los alias de la
  cara genérica publicados para el alcance, con propietario fijo y neutro; la vista (Claude u
  OpenAI) se elige por las cabeceras del pedido. (← 068 contrato cara-generica §GET, FR-010)
- **FR-056** [BASE]: Los errores de la cara genérica DEBEN usar el formato de error OpenAI
  existente, con los códigos nuevos `model_not_found` (404) y `region_not_allowed` (403) y textos
  neutros; en streaming, un comentario de señal de vida cada 15 s como máximo de silencio.
  (← 068 contrato cara-generica §POST)

**F. Caché del proveedor (enmienda 2026-10-01 de la 068; dentro del MVP por decisión del owner)**

- **FR-043** [BASE]: Para destinos que agrupan por sesión, el sistema DEBE mandar un
  identificador estable por conversación derivado del que manda la herramienta con una clave
  del servidor, nunca el original ni datos de la persona. (← 068 FR-038)
- **FR-044** [BASE]: Para destinos que declaran soporte de marcas de caché, DEBEN reenviarse sin
  cambios. (← 068 FR-039)
- **FR-045** [BASE]: Las transformaciones de la pasarela sobre el pedido (enmascarado,
  normalización, omisiones) DEBEN ser deterministas dentro de una conversación: el mismo
  contenido de turnos anteriores produce los mismos bytes; el sufijo aleatorio de los marcadores
  de enmascarado pasa a ser por conversación. El determinismo NO DEBE bajar la protección: el
  marcador sigue siendo impredecible para el usuario, no se comparte entre conversaciones ni entre
  personas, y lo que el destino ve sigue siendo solo marcadores. Lo habilita una costura nueva en
  la base (S13, tabla C-1) que Sentinel tampoco hizo: se diseña genérica para las dos líneas y
  vuelve a Sentinel por `HANDOFF`. (← 068 FR-040, research D22, tasks Phase 9; Clarifications P4)
- **FR-046** [BASE]: El precio del destino DEBE admitir lectura y escritura de caché; el costo
  registrado y el descuento de presupuesto usan los tokens informados; sin precio de caché, se
  cobra al precio de entrada completo y la auditoría lo marca; la auditoría registra los tokens
  de caché y el panel muestra el aprovechamiento por destino. (← 068 FR-041, FR-042)

**G. Auditoría, costos, seguridad, marca y documentación**

- **FR-047** [BASE]: Cada pedido con la política encendida DEBE registrar id público pedido,
  destino real, cara, fidelidad, regla aplicada, postura de residencia, jurisdicción servida y
  motivo de cualquier sustitución, sin contenido del pedido, PII, tokens de credencial ni
  secretos. (← 068 FR-033, data-model §6; constitución, auditoría metadata-only)
- **FR-048** [BASE]: La caché de respuestas NO DEBE servir una respuesta generada por otro
  destino ni con un mapa de enmascarado de otro pedido. (← 068 FR-034)
- **FR-049** [BASE]: Los presupuestos DEBEN descontar el costo del destino real con una única
  fuente de precios. (← 068 FR-032, parte de presupuesto; el costo hipotético es F5)
- **FR-050** [BASE]: Ningún mensaje, error, lista o pantalla generada DEBE exponer nombres de
  componentes internos ni nombres de `deploy/release/checks/prohibited_names.txt`; los nombres de
  proveedor solo aparecen como datos cargados por el administrador o donde el protocolo de la
  herramienta los exige literalmente. [ELEIA] La marca visible sale de la configuración de
  marca de la instalación. (← 068 FR-035, D19 punto 3)
- **FR-051** [BASE]: Todos los datos nuevos (destinos, credenciales, ids, reglas, posturas,
  eventos, registro de cambios) DEBEN estar aislados por empresa con el mismo mecanismo que las
  tablas multi-tenant existentes; los datos de nivel instalación solo son legibles por una
  empresa a través de una oferta vigente. (← 068 FR-037)
- **FR-052** [ELEIA]: La documentación de producto (`docs/docs/**`) DEBE describir la política,
  la cara Claude y las posturas con su estado real (🟢/🟡/🔵), marca neutra, matriz de
  compatibilidad por herramienta y proveedor sin declarar compatibilidad no verificada, en el
  template GUÍA/RUNBOOK; y la verificación de documentación del release DEBE quedar verde.
  (← 068 FR-036; Definition of Done de `AGENTS.md`)
- **FR-057** [BASE]: La etiqueta de un id publicado DEBE ser, por defecto, el **id pedido** (`label_mode =
  requested`): ni `/v1/models` ni las respuestas (cuerpo, `model` y eventos de *streaming*) DEBEN exponer el nombre ni el
  modelo real del destino salvo que el administrador elija mostrarlo por id (`destination`) o ponga una etiqueta propia
  (`custom`); cambiar el default NO DEBE alterar las filas existentes. (Clarifications 2026-10-07, R40)
- **FR-058** [BASE]: El alta guiada de modelos («Dar de alta modelos») DEBE poder dar de alta un destino de un agregador
  (OpenRouter) pidiendo y enviando los proveedores permitidos (FR-032); la ficha de ese destino DEBE llevar la jurisdicción de
  inferencia, de entidad y de control del proveedor final, no las del agregador; y una regla DEBE poder mover un id publicado
  de un destino a otro sin cambios en el cliente. Los ids publicados y las reglas con alcance de grupo, junto con el perfil de
  acceso por proveedor, DEBEN permitir que cada grupo vea y use modelos distintos sin código nuevo (Clarifications 2026-10-07,
  R40).

### Key Entities

Se heredan de la 068 (§Key Entities y `data-model.md`) sin cambios de forma [BASE]:

- **Política de redireccionamiento**: estado (apagada / encendida; sombra reservada) por alcance.
- **Destino**: modelo real en un proveedor; nivel (instalación o empresa) y empresas a las que
  se ofrece; credencial (referencia cifrada), jurisdicción de inferencia, entidad responsable y
  jurisdicciones de entidad y de control (FR-028a), familia de protocolo, capacidades declaradas, ventana de contexto, precio (incluido
  el de caché).
- **Oferta**: un destino de instalación ofrecido a una o todas las empresas.
- **Id público**: nombre visible por cara (en la cara Claude, con tier; en la genérica, alias
  neutro); etiqueta y modo de etiqueta, alcance.
- **Regla de mapeo**: id público o tier → destino principal + fallbacks, por alcance.
- **Perfil de capacidades**: qué funciones de la cara soporta un destino (base de la fidelidad).
- **Postura de residencia**: modo y lista de jurisdicciones, por alcance, con autor, rol y motivo.
- **Regla de habilitación explícita**: proveedor, host de la API o jurisdicción que hace nacer
  bloqueado a un destino (FR-029); vacías en Eleia.
- **Relajación del enmascarado forzado**: por empresa o instalación y por destino, con autor, rol
  y motivo (FR-031a).
- **Registro de cambios de configuración**: antes/después sin secretos, autor, rol, momento.
- **Evento de redirección**: metadata de auditoría del pedido redirigido.

- **Región del perfil** [BASE]: dato del perfil de país que dice qué jurisdicciones forman «mi
  región» y cuál es su postura por defecto (FR-031); reemplaza la tabla fija región → código.

[ELEIA] Datos propios, sin entidades nuevas: la lista de jurisdicciones `AMERICAS` (FR-030), la
región del perfil de Eleia apuntando a ella y los destinos de ejemplo del catálogo de Azure de la
instalación de demo (FR-020).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001** [BASE]: Con la política apagada y sin postura, el 100 % de una batería de pedidos
  grabados de Claude Code y Claude Desktop contra la pasarela produce respuestas y filas de
  auditoría idénticas a la versión anterior, con y sin la extensión montada. (← 068 SC-001)
- **SC-002** [BASE]: Con las costuras y sin extensión, el 100 % de la suite existente de la base
  queda verde sin modificar tests existentes, y cada costura tiene su test «sin extensión ⇒
  idéntico». (← 068 D13)
- **SC-003** [BASE]: Un administrador enciende la política para un grupo, registra dos destinos
  del catálogo y mapea los tres tiers en menos de 15 minutos sin ayuda técnica. (← 068 SC-002)
- **SC-004** [BASE]: Con un destino traducido del catálogo de Azure, al menos el 95 % de las
  conversaciones grabadas de Claude Code, Claude Desktop Chat, Cowork y Code se completa sin
  errores visibles, y el 100 % de los fallos restantes llega como rechazo explícito, nunca como
  respuesta incorrecta presentada como válida. Con un destino nativo, el 100 % se completa sin
  errores visibles; [ELEIA] esta parte no entra en la aceptación del MVP (no hay credencial
  nativa) y queda 🟡 hasta poder medirla (Clarifications P5). (← 068 SC-003, SC-004)
- **SC-005** [BASE]: El 0 % de los pedidos de usuarios con *solo jurisdicciones permitidas*
  llega a un destino fuera de esas jurisdicciones (verificable en auditoría). (← 068 SC-005)
- **SC-006** [BASE]: El 100 % de los pedidos con enmascarado forzado (hacia otra jurisdicción
  con postura explícita, o hacia cualquier destino con la postura por defecto *enmascarado
  forzado en todo destino*) sale sin los datos personales detectables de la batería de prueba
  (incluidos los del perfil Argentina: DNI, CUIT/CUIL, CBU, en los formatos que la batería fija)
  en ninguna de sus partes (sistema, turnos del usuario y del asistente, herramientas, adjuntos
  PDF), el 100 % de los pedidos con contenido no analizable se bloquea (las imágenes quedan fuera de este conteo con `MASKING_IMAGES=pass`, el
  default de Eleia: salen tal cual y se auditan como `images_unmasked`; R43) y el 100 % se bloquea con
  el analizador caído. (← 068 SC-006;
  [ELEIA] la batería incluye los identificadores del perfil `latam_ar`)
- **SC-007** [BASE]: Ninguna sesión de streaming de la batería se corta por inactividad mientras
  el destino sigue procesando. (← 068 SC-007)
- **SC-008** [BASE]: El 100 % de los pedidos redirigidos tiene en auditoría id pedido y destino
  real, y el 0 % contiene texto del pedido, PII o secretos. (← 068 SC-008)
- **SC-009** [BASE]: Cambiar el destino de un tier surte efecto para todos los usuarios del
  alcance sin tocar ningún equipo, en menos de un minuto. (← 068 SC-009)
- **SC-010** [BASE]: Con la política encendida, la demora añadida por la pasarela hasta el primer
  contenido (sin contar el tiempo del destino ni el del análisis del enmascarado forzado, que se mide
  aparte de forma informativa) es de 50 ms o menos en el percentil 95. (← 068
  SC-011)
- **SC-011** [BASE]: En una tarea de Cowork de al menos 10 pasos contra un destino con caché
  implícita, al menos el 60 % de los tokens de entrada desde el segundo paso sale de la caché,
  también con datos personales enmascarados. (← 068 SC-012)
- **SC-012** [BASE]: El costo registrado para el tráfico redirigido difiere en no más del 5 % del
  que informa el proveedor para los mismos pedidos. (← 068 SC-013)
- **SC-014** [BASE]: Con un destino Azure del catálogo, al menos dos de los harness de referencia
  de la cara genérica listan los alias de su alcance y completan conversaciones con streaming y
  herramientas en el 100 % de una batería grabada, con el alias pedido como modelo de la
  respuesta; el 0 % de los usuarios de otro alcance ve esos alias. (← 068 FR-020, contrato
  cara-generica; HANDOFF Anexo A: primera verificación en vivo)
- **SC-013** [ELEIA]: El 0 % de las respuestas, listas, errores y pantallas nuevas contiene un
  nombre de la lista de nombres prohibidos, y la verificación de documentación del release queda
  verde con la documentación de la feature publicada. (← 068 FR-035, FR-036; DoD de `AGENTS.md`)

## Assumptions

- **HANDOFF de Sentinel**: recibido el 2026-10-06 (rama `docs/handoff-068-elea`, con el Anexo A
  de la cara genérica, commit 8c525db) e incorporado a esta spec. Si una revisión posterior del
  handoff cambia un contrato, la spec se enmienda antes del plan.
- **Base legal de las transferencias**: la base legal de las transferencias internacionales de
  datos personales (Ley 25.326 art. 12: cláusulas contractuales o consentimiento) la cubre Elea
  por fuera del sistema. El sistema solo decide, según la postura, si un pedido sale, si sale
  enmascarado o si se rechaza (Clarifications P2/P3, D2). El enmascarado es **seudonimización
  reversible** de los identificadores detectados, no anonimización: para quien guarda la
  correspondencia el dato sigue siendo personal, así que reduce el riesgo pero no reemplaza la
  base legal ni el instrumento de transferencia. `AMERICAS` es criterio de riesgo, no de
  legalidad, y nada de lo visible dice «cumple con X»; la documentación de residencia queda 🟡
  hasta la revisión legal (Clarifications D3, D10; `specs/ANALISIS-TRANSFERENCIAS-AMERICA-2026-10.md`
  §2.3 y §5, rama `cluna-8/spike-transferencias-america`).
- **Riesgo — cara genérica sin verificación en vivo**: está implementada y con tests en Sentinel
  pero nunca se probó en vivo (HANDOFF Anexo A); la prueba de Eleia será la primera. En el ensayo
  de Sentinel sobre un clon de Eleia, el e2e de la redirección dio 26/27: el fallo es el listado
  con el modelo «auto», que trae `fd515ff` y queda fuera del MVP.
- **Riesgo — base de datos compartida en desarrollo**: en el entorno de desarrollo el motor y el
  backend usan la misma base; en una base nueva, si el backend migra antes del primer arranque
  del motor, el motor puede borrar tablas del backend (HANDOFF §4.4). Es deuda de las dos líneas
  con fix corto sin spec; esta feature no la empeora y la prueba en vivo debe hacerse sobre una
  base existente o con las bases separadas.
- **Nombres internos**: el paquete de la extensión, sus tablas, la etiqueta de su rama de
  migraciones y sus rutas internas conservan los nombres de Sentinel para mantener la paridad
  (HANDOFF §4.5); no son visibles al cliente. Neutralizarlos sería una decisión aparte y
  coordinada con Sentinel.
- **Dónde vive la lógica**: como en la 068 (research D1, plan §Structure Decision), la lógica vive
  en una capa de extensión separada de la base y portada tal cual; la base (`backend/`,
  `frontend/`) solo recibe las costuras, mínimas y retrocompatibles. El paquete se copia con su
  estructura y nombre de Sentinel (HANDOFF §1(b); ver «Nombres internos»); el detalle de entrega
  (imágenes, montaje en desarrollo, activación por variables) se decide en el plan, dentro de lo
  que fija FR-004d (variantes derivadas de las imágenes publicadas y activación opt-in en el
  instalador).
- **Constitución**: la de Eleia (2.2.0) es la heredada; su Principio II se lee como la normativa
  del perfil de país (Ley 25.326/AAIP). Los puntos de la enmienda D19 de la 068 que Sentinel ya
  aplicó (403 para rechazos de residencia de esta política; aclaración de §VII) y el default de
  residencia por región (FR-031) se sincronizan en el plan con `speckit-constitution`, no en
  esta spec.
- **Versión del motor**: no se cambia la versión fijada (`litellm/Dockerfile:6`); el spike D14 de
  la 068 (ruteo por familias comodín y credencial por pedido) se repite sobre esta versión antes
  de implementar las caras; si falla, es gate de re-plan.
- **Topología**: el motor no es alcanzable directamente por los clientes, solo a través de la
  pasarela (068 Assumptions); la postura depende de eso.
- **Instalación de Elea**: hoy es una sola empresa on-premise, pero el porte conserva el
  multi-tenant completo de la 068 (niveles, ofertas, aislamiento) porque es base compartida.
- **Jurisdicción del catálogo de Azure**: la región de Azure de cada modelo la carga el
  administrador como dato al registrar el destino; esta spec no supone en qué región están los
  modelos de la instalación.
- **Licencia**: la feature no agrega un permiso de licencia nuevo (la 068 no lo tiene).
- **Herramientas**: las herramientas se configuran contra la pasarela (dirección y llave); la
  pasarela no intercepta herramientas que no permiten cambiar su dirección. Los fabricantes no
  garantizan su funcionamiento con modelos de otras familias, por eso la batería grabada es parte
  de la aceptación.
- **Docker**: toda verificación que use Docker (suite del backend en contenedor, checks del
  release que construyen imágenes) se corre solo con aviso previo al owner, que prepara la PC.
- **Fuera de alcance explícito**: el chat de la consola, el Hub de usuarios, el texto de
  residencia del chat de la consola que hoy nombra la UE (Diagnóstico #17, anotado como
  hallazgo), el modelo «auto» por la puerta de chat estándar (`fd515ff`) y las fases F2–F7 de la
  tabla de Alcance.
