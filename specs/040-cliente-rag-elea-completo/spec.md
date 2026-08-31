# Feature Specification: Cliente RAG de Elea — login real, selector automático, workspace completo, presupuesto y enmascaramiento

**Feature Branch**: `040-cliente-rag-elea-completo`

**Created**: 2026-08-31

**Status**: Borrador — a revisar antes de construir. Depende de
[039-white-label-motor-marketplace](../039-white-label-motor-marketplace/spec.md) (naming
neutro del motor).

**Input**: Pedido directo del usuario tras revisión de código: "revisemos que esté todo el
cliente: login real, selector de modelos automático de elea en el chat simple, workspace con
todas las opciones de AnythingLLM (con ayuda contextual de qué hace cada una), branding,
enmascaramiento correcto, asignación de presupuestos, conexión robusta con el motor para
selección de modelos. Documentemos todo lo que tenemos que tener." Restricción operativa
del usuario: máquina con memoria limitada — no se puede asumir que todos los contenedores
(elea completo + AnythingLLM + el cliente) corren a la vez sin cuidado.

## El problema, con evidencia (31-ago, código real revisado)

El cliente (`client/`, ex `installations/11_elea_standalone_chat` de `HARNES-PRUEBAS`) es
una **maqueta funcional sin integraciones reales**. Verificado línea por línea en
`server.js` (versión previa a esta spec):

1. **El login no autentica**: `POST /api/auth/login` solo comprueba que el `userId`
   exista en un objeto en memoria de 2 usuarios demo (`ana.gomez`, `luis.fierro`) —
   **nunca valida contraseña**. `elea` sí tiene login real
   (`backend/src/api/users.py:171` — JWT vía bcrypt) que este cliente ignora.
2. **El chat no llama a ningún motor**: `POST /api/chat` no hace una sola petición HTTP
   saliente. Arma la respuesta a mano: extrae las primeras 5 líneas del documento
   (`extractText()`), la devuelve como "resumen", inventa una cita fija (`"Pág. 1"`) y
   calcula un costo con una fórmula fija (`400 tokens × tarifa`). Los campos
   `config.anythingLlmUrl/anythingLlmApiKey/anythingLlmWorkspace` existen pero **no se usan
   en ningún `fetch`/`http` del archivo** — grep confirma cero llamadas salientes.
3. **El selector de modelo es una lista fija sin motor detrás**: 4 opciones hardcodeadas
   en `public/index.html` (`basa-auto-router`, `demo-gpt-4o`, `azure-gpt-4o-mini`,
   `deepseek-r1-distill`) con precios inventados — no reflejan el catálogo real de
   `litellm/config.yaml` (hoy: `azure-gpt-4o-mini`, `gemini-2.5-flash`,
   `gemini-2.5-flash-lite`, `claude-3-5-sonnet`, `router-embeddings`, ninguno de los 4 de
   la lista existe salvo `azure-gpt-4o-mini`).
4. **El presupuesto es un contador en memoria** (`user.usedUsd`), no lee ni escribe contra
   `Budget`/`APIKey` de `elea` (`backend/src/models/budget.py`).
5. **La creación de workspace solo pide nombre/descripción**: no expone ninguna de las
   opciones reales de AnythingLLM (modo de chat estricto/conversacional, temperatura,
   prompt de sistema, umbral de similitud, ventana de historial, top-N de fragmentos) —
   son un JSON local (`ragMode`, `temperature`, `systemPrompt`) que tampoco viaja a ningún
   lado.
6. **AnythingLLM está corriendo y responde** (`http://localhost:3001`, verificado
   `GET /api/v1/workspaces` → `401` con mensaje `"No valid api key found"`, o sea la API
   real existe y exige key) pero **nunca se le habla**.
7. **El enmascaramiento NER de `elea` nunca puede aplicarse a este flujo hoy**: como el
   chat no pasa por el motor de `elea`, ningún dato del cliente (nombre, DNI, contenido de
   documentos subidos) pasa por Presidio/`SentinelGuardrail`. Esto es un vacío real de
   compliance, no solo de UX — hay que decidir en qué capa se enmascara (ver US4).
8. **"Presupuesto por rol" (punto 6 original del cliente Elea) no es un concepto nativo de
   `elea`**: `Budget` solo tiene `user_id` o `group_id` (`budget.py:15-16`). `Group`
   (`user.py:37`) sí puede representar un rol (Analista/Coordinador/Supervisor) — la
   cobertura es real pero es una **convención operativa** (crear un Group por rol y
   asignarle budget), no una columna `role` en `Budget`. Hay que documentarlo así para no
   prometer algo que no existe.

## Restricción no funcional: memoria de la máquina de desarrollo

El usuario no tiene memoria suficiente para correr sostenidamente el stack completo de
`elea` (6 contenedores) **más** AnythingLLM **más** el cliente Node a la vez, en una sesión
larga de desarrollo. El plan (`plan.md`) tiene que dejar explícito qué subconjunto de
servicios hace falta prendido para desarrollar/probar cada User Story, y usar perfiles de
Docker Compose (`--profile`) para no levantar todo por defecto.

## User Scenarios & Testing

### User Story 1 - Login real contra `elea` (Priority: P1)

Un usuario de Elea (por ejemplo `ana.gomez`, ya creada en `elea` vía
`POST /api/v1/users`) abre el cliente RAG, ingresa usuario y contraseña reales, y entra
solo si `elea` los valida. Sin sesión no se ve ningún workspace ni historial ajeno.

**Criterios de aceptación**:
1. `POST /api/auth/login` del cliente reenvía a `POST {ELEA_BACKEND_URL}/users/login`;
   credenciales inválidas devuelven 401 idéntico al de `elea`, no un mensaje propio.
2. El JWT recibido se guarda solo en el proceso Node (nunca en `localStorage` del
   navegador ni en `db_state.json` en claro) y viaja en cada llamada subsiguiente del
   cliente hacia `elea`.
3. El selector de "cambio rápido de usuario" (`user-selector`, hoy sin password) se
   elimina; cerrar sesión limpia el JWT en memoria.

### User Story 2 - Selector de modelo automático real en el chat simple (Priority: P1)

En el chat que no es RAG documental (sin documentos en el workspace activo), el usuario ve
el selector con las opciones **reales** que expone `elea` (auto-router + catálogo vigente
de `litellm/config.yaml`, vía el endpoint que ya existe:
`GET/PUT /api/v1/.../router` en `backend/src/api/router_config.py`), nunca una lista
hardcodeada. Al elegir "Automático", el mensaje viaja a `elea` con `model="auto"` y el
`AutoRouterService` decide.

**Criterios de aceptación**:
1. El combo de modelos se llena en el arranque de sesión desde `elea` (catálogo real +
   auto-router), no desde un array fijo en `index.html`.
2. La respuesta del chat simple muestra qué modelo respondió realmente (transparencia,
   igual que hace el portal nativo de `elea` — "decisión de Elea" documentada en
   `HANDOFF-FALIME-2026-08-14.md §3.4`), sin exponer el nombre del motor subyacente
   (ver spec 039).
3. Ningún nombre de proveedor de motor ("litellm") aparece en la UI ni en las respuestas
   de la API del cliente — solo nombres de modelo (`azure-gpt-4o-mini`, etc.) y
   "Automático".

### User Story 3 - Creación de workspace con las opciones reales de AnythingLLM, con ayuda contextual (Priority: P2)

Al crear o editar un workspace, el usuario ve **las opciones reales** que soporta
AnythingLLM (no las 3 inventadas de hoy), cada una con un texto breve de qué hace, para
que alguien sin experiencia técnica entienda qué está eligiendo:

| Opción real de AnythingLLM | Qué controla | Texto de ayuda sugerido |
|---|---|---|
| `chatMode` (`chat` \| `query`) | Modo conversacional vs. estrictamente documental | "Conversacional: combina lo que sabe el modelo con tus documentos. Estricto: solo responde si está en los documentos — 0% de invención." |
| `openAiTemp` (temperatura) | Creatividad vs. precisión | "Más bajo = respuestas más literales y repetibles. Más alto = respuestas más variadas." |
| `openAiHistory` (ventana de historial) | Cuántos mensajes previos recuerda el hilo | "Cuántas vueltas de la conversación tiene en cuenta antes de responder." |
| `openAiPrompt` (system prompt del workspace) | Instrucciones fijas para ese espacio | "Reglas que aplican a TODAS las respuestas de este espacio (tono, formato, alcance)." |
| `similarityThreshold` | Qué tan parecido tiene que ser un fragmento para citarse | "Más alto = solo usa fragmentos muy relevantes (más estricto, puede omitir contexto útil)." |
| `topN` | Cuántos fragmentos trae por consulta | "Cuántos trozos de documento se le pasan al modelo por pregunta." |
| `queryRefusalResponse` | Qué responde en modo estricto sin match | "El mensaje exacto que ve el usuario cuando no hay nada relevante en los documentos." |

**Criterios de aceptación**:
1. El formulario de creación/edición de workspace expone las 7 opciones de la tabla (no
   solo nombre/descripción), con su texto de ayuda visible (tooltip o texto bajo el campo).
2. Al guardar, el cliente llama a la API real de AnythingLLM (`POST /api/v1/workspace/new`
   y `POST /api/v1/workspace/{slug}/update`) — deja de ser JSON local sin efecto.
3. Los textos de ayuda se redactan en español simple, sin jerga de AnythingLLM sin
   explicar (ej. no decir "vectorSearchMode" a secas).

### User Story 4 - Enmascaramiento NER correcto en todo el flujo (Priority: P1)

Cualquier texto que el usuario escribe o sube (mensaje de chat, documento) pasa por el
enmascaramiento de `elea` antes de llegar a un modelo, con el mismo criterio (`latam_ar`:
DNI/CUIL/CBU) que el resto del producto — no hay un camino paralelo sin protección.

**Decisión de arquitectura a tomar (bloquea el plan)**: AnythingLLM habla con un LLM
"proveedor" configurado en su propio panel de administración. Si ese proveedor apunta al
motor de `elea` (`http://engine:4000/v1`, como ya define spec 037), el **chat** de
AnythingLLM queda enmascarado gratis (pasa por `SentinelGuardrail`). Pero la **ingesta de
documentos** (embeddings al subir un archivo) es un camino separado dentro de AnythingLLM
que no pasa por el motor de chat — un documento con datos personales podría vectorizarse
sin enmascarar. Hay que decidir: (a) enmascarar el texto en el cliente Node antes de
subirlo a AnythingLLM (llamando al analyzer de `elea`,
`backend/src/services/presidio_service.py`, reutilizable), o (b) aceptar el riesgo
documentado para el piloto y resolverlo en una spec de continuación.

**Criterios de aceptación**:
1. AnythingLLM está configurado con el motor de `elea` como proveedor LLM interno
   (`ANYTHINGLLM_LLM_PROVIDER=http://engine:4000/v1` + virtual key propia).
2. Queda explícito en `plan.md` cuál de las dos opciones (a/b) se implementa para el
   piloto y por qué.

### User Story 5 - Asignación de presupuestos real (Priority: P1)

El presupuesto que se ve en el cliente (badge de cabecera) es el real de `elea`
(`Budget.max_spend_usd` / `current_spend_usd` del usuario logueado), no un contador
inventado. Un admin puede asignar presupuesto por usuario o por rol (vía `Group`, ver
hallazgo 8) desde el panel de `elea` existente (`UsersPage.tsx`), no desde este cliente.

**Criterios de aceptación**:
1. El cliente lee el presupuesto real vía el backend de `elea` (endpoint a definir en
   `plan.md` — hoy no existe un `/me/budget` de autoservicio, ver hallazgo del backend).
2. Se documenta explícitamente que "presupuesto por rol" = crear un `Group` con el nombre
   del rol y asignarle un `Budget` con `group_id` — no es una feature nueva a construir,
   es una convención a usar con lo que `elea` ya tiene.
3. Si el usuario se queda sin presupuesto, el cliente muestra el mismo 402 que devuelve
   `elea`, no un mensaje inventado.

### User Story 6 - Branding consistente (Priority: P2)

Extiende [spec 039](../039-white-label-motor-marketplace/spec.md) a las piezas nuevas de
esta spec: pantalla de login, panel de configuración de workspace, textos de ayuda. Ninguna
menciona "litellm". Sí puede mencionar "AnythingLLM" (herramienta open source visible, no
es el motor propietario) y "Elea"/"GuardIAn" (nombre de cara al cliente).

**Criterios de aceptación**:
1. `grep -ril litellm client/` sigue devolviendo vacío tras esta spec.
2. La API key de ejemplo hardcodeada (`ANT-KEY-ELEA-PROD-2026`) se reemplaza por una key
   real generada en AnythingLLM, provista por `.env`, nunca commiteada.

## Fuera de alcance (por ahora)

- DB-GPT (cruces CSV/Excel) y Presenton (generación de pptx/pdf) — explícitamente
  descartados por el usuario en esta ronda ("por el momento solo el RAG con AnythingLLM").
- Un endpoint nuevo `/me/budget` en el backend de `elea` — si `plan.md` concluye que hace
  falta, es un cambio al repo compartido y se spec-ea aparte, no se improvisa acá.
