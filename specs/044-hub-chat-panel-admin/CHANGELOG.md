# 044 — Eleia Hub (client/) + Eleia Guardian (frontend/), consumiendo los contratos de la 043

**Fecha**: 08-sep-2026
**Estado**: 🟢 **54/63 tareas hechas y verificadas** (US1-US5 completas, US6 y Polish
completos salvo lo que requiere una instalación real desplegada). Las 9 restantes están
**todas** bloqueadas por infraestructura real que este entorno no tiene (credenciales de
proveedor LLM, acceso a la instalación real de Elea, credenciales de publicación de
imágenes) — mismo criterio y misma disciplina que la 043 (ver su CHANGELOG). Ninguna se
marcó hecha sin estarlo.
**Depende de**: [043-aislamiento-atribucion-motor](../043-aislamiento-atribucion-motor/spec.md)
(contratos 1-6, todos consumidos).

Este doc sigue el mismo criterio que
[042-rediseno-ui-boveda-pii-hilos/CHANGELOG.md](../042-rediseno-ui-boveda-pii-hilos/CHANGELOG.md):
registro de lo que se hizo, por qué, y cómo quedó verificado — no solo lo que se escribió.

---

## 1. Tooling de tests bootstrapeado en ambos repos

- `client/`: `node:test` (nativo, Node 22) + `supertest`, contra el `Express` real de
  `server.js` sin levantar un puerto (`module.exports = app` + guard
  `if (require.main === module)`). Dobles HTTP reales del backend Guardian y del motor de
  documentos con `node:http` (`client/tests/mock-servers.js`) — no mocks de módulo, porque
  `server.js` habla con ambos por `fetch()` real.
- `frontend/`: Vitest 2.x (pinneado — `vitest@latest` trae `vitest@5` con un peer conflict
  contra `@vitest/browser-playwright@5.0.0` incompatible con Vite 5.2.11 del proyecto) +
  React Testing Library + jsdom. Smoke test en verde; sin componentes propios todavía.

## 2. US1 — Cada persona ve solo sus espacios y sus hilos (implementado y probado)

**Bug reportado por Tomás Mc Nally**: el Hub mostraba los espacios/documentos de otras
personas porque hablaba directo con AnythingLLM sin verificar pertenencia contra el backend.

**Fix**: `client/server.js` reescrito — cada endpoint de espacios/hilos/documentos exige
sesión (`requireSession`, 401 uniforme "iniciá sesión" sin sesión), y antes de proxyar
cualquier operación sobre un `workspace_id`/`slug` conocido verifica pertenencia contra el
backend (`GET /workspaces` y `GET /workspaces/{id}` del contrato 1 de la 043) — 403 uniforme
"No tenés acceso a este espacio" si no hay membresía, sin revelar si el espacio existe.

**UI (`public/index.html`)**:
- Se quitó el auto-select de `workspaces[0]` (violaba FR-002: podía auto-seleccionar un
  espacio ajeno si el shape cambiaba) — ahora la persona elige explícitamente.
- Estado vacío ("Todavía no tenés espacios. Creá uno o pedile a tu administrador que te
  agregue") cuando la lista de espacios propios está vacía.
- **Bug real encontrado y corregido en este mismo pase**: `renderWorkspaceList()` leía
  `ws.slug`/`ws.name`, campos que NO existen en la respuesta del backend (que usa
  `engine_slug`/`display_name`, contrato 1) — la lista de espacios se habría renderizado
  vacía o con "undefined" pese a que el backend devolvía datos correctos. Corregido antes de
  llegar a producción, no en un hotfix posterior.
- Panel "Miembros" (modal): ver la lista con rol, agregar por nombre de usuario, quitar y
  transferir propiedad — visible con acciones para el dueño o un admin; solo lectura para un
  miembro no dueño. El backend vuelve a exigir la autorización del lado suyo en cada llamada
  (nunca se confía en lo que decide mostrar la UI).
- 403 de un espacio ajeno por URL directa: "No tenés acceso a este espacio", sin cargar nada
  del espacio anterior.
- Vista "Sin asignar" (modal, botón visible solo para roles `super_admin`/`tenant_admin`):
  lista los espacios heredados de una migración sin dueño y permite asignarles un dueño por
  nombre de usuario.
  - **Segundo bug real encontrado y corregido**: el endpoint `GET /api/workspaces/unassigned`
    llamaba al backend con `?status=unassigned`, pero el backend espera el parámetro
    `status_filter` (`backend/src/api/workspaces.py:70`) — con el nombre equivocado, el
    backend simplemente ignoraba el filtro y devolvía la lista de espacios propios del admin
    en lugar de los sin asignar. No lanzaba error: fallaba en silencio. Encontrado leyendo el
    código del endpoint real antes de darlo por probado, no por un fallo en producción.
  - Se agregó `POST /api/workspaces/unassigned/:workspaceId/members` en `client/server.js`:
    a diferencia del proxy de miembros normal, acá quien llama no es miembro del espacio
    (por definición, un espacio sin asignar no tiene dueño), así que no hay membresía local
    que verificar — se pasa el `workspace_id` directo y es el backend quien exige rol admin
    server-side (`add_member(..., is_admin=...)` en `workspaces.py`).

**Verificado con pruebas automatizadas** (contra dobles HTTP reales, `npm test` en `client/`,
8/8 en verde):
- `client/tests/contract/test_workspaces.test.js` — `GET /api/workspaces` sin sesión responde
  401; con sesión, devuelve únicamente los espacios propios (Ana no ve el espacio de nadie
  más al listar).
- `client/tests/integration/test_workspace_isolation.test.js` — acceso cruzado a un espacio
  ajeno por slug conocido responde 403 sin filtrar ningún dato (`display_name` no viaja en
  el 403); tras agregar a la otra persona como miembro, el acceso se habilita.
- `client/tests/integration/aislamiento.test.js` — guion de extremo a extremo: Ana crea un
  espacio, Luis no lo ve ni accede, sin sesión da 401, Ana agrega a Luis, Luis lo ve, cada
  uno crea su propio hilo sin cruzarse.
- `client/tests/integration/unassigned.test.js` — regresión específica del bug
  `status`/`status_filter`: un admin ve la lista real de espacios sin asignar (no una lista
  vacía disfrazada de "no hay"); una persona no-admin recibe 403 real del backend; asignar
  un dueño saca al espacio de la lista de "sin asignar".

## 3. Pendiente (no cerrado en este pase)

## 4. US2 — Presupuesto autoservicio + costos por persona (completo)

- `frontend/src/services/api.ts`: tipos (`UserPatch`, `WorkspaceUnassigned`,
  `MaskingEntityBreakdown`) y funciones (`getUsers({includeService})`, `patchUser`,
  `deleteUser`, `getUnassignedWorkspaces`, `assignWorkspaceMember`) — T006/T007.
- `client/public/index.html`: mismo mensaje neutro ("Alcanzaste tu presupuesto...") tanto si
  el bloqueo lo decide la pantalla localmente (con el `currentBudget` ya cargado, antes de
  llamar) como si llega como 402 real del backend — T024.
- `backend/src/api/costs.py`: nuevo desglose `masking_by_user` en `GET /costs/summary` —
  cuenta DOCUMENTOS distintos (`document_group_id`) por persona para el tráfico de
  enmascarado, separado de `by_user` (que sigue siendo gasto real con modelo). Sin esto, el
  enmascarado (siempre costo 0) inflaba el conteo de "peticiones" de `by_user` sin ninguna
  forma de distinguirlo de preguntas reales — bug real encontrado en este pase, no
  reportado antes. Probado en `backend/tests/integration/test_costs_masking_by_user_044.py`
  (2/2 verde).
- `frontend/src/pages/CostsPage.tsx`: tabla nueva "Protección de documentos por persona".
- Verificado: sin ningún filtro local de `license`/`chat-ui` en `DashboardPage.tsx` ni
  `CostsPage.tsx` (T026) — el backend ya resuelve `event_type`/`surface`.

## 5. US3 — Enmascarado coherente por documento (completo)

- **Bug real encontrado y corregido**: `maskChunk` en `client/server.js` no tenía NINGÚN
  reintento — un fallo de red transitorio en un solo chunk abortaba toda la subida. Se
  agregó reintento acotado (3 intentos, solo ante fallo de RED, nunca ante 4xx/402 reales)
  reusando el mismo `document_id` del cierre — T029.
- `public/index.html`: modal "Resumen de protección" con el conteo agregado por tipo de
  dato tras cada subida (T033); aviso "esquema anterior. Reenviá el documento..." cuando
  `MASKING_DETERMINISM_SINCE` está configurada y el documento trae `meta.published`
  anterior a esa fecha — sin ninguna de las dos cosas, no se marca nada (T034).
- Probado: `client/tests/contract/test_document_id.test.js` (mismo `document_id` en los 3+
  chunks de un documento grande) y `client/tests/integration/test_upload_retry.test.js`
  (recuperación del reintento).

## 6. US4 — Panel de usuarios completo (completo)

- `UsersPage.tsx`: edición parcial de rol/email (`patchUser`, solo lo tocado — T040),
  desactivar/reactivar (T041), baja definitiva con modal de confirmación escribiendo el
  username exacto y las mismas dos guardas que el backend (auto-baja, último admin activo)
  repetidas del lado de la UI antes de llamar (T041), sección plegada "Cuentas de servicio
  (N)" de solo lectura con `purpose` (T042), acciones destructivas/de edición ocultas para
  el rol `lectura` (T043).
- `frontend/src/pages/WorkspacesUnassignedPage.tsx` (nueva) + ruta registrada en `App.tsx`,
  mismo grupo de superficie que Usuarios (`gestion_iam`) — T044.
- Verificado (no un mapeo nuevo, uno YA correcto): `SecurityPage.tsx` muestra el nombre del
  guardián NLP directo del backend (`g.name`), sin ningún mapeo local a "Presidio" — T045.
- Probado con Vitest + React Testing Library (6 tests, `frontend/tests/contract/UsersPage.*`):
  cuentas de servicio plegadas y fuera de la tabla principal, PATCH parcial de verdad (no
  reenvía campos no tocados), y las dos guardas de baja bloqueando ANTES de llamar al
  backend.

## 7. US5 — Ningún nombre de motor/proveedor visible (completo)

- **2 fugas reales encontradas y corregidas**: 10 comentarios de `client/public/index.html`
  nombraban "AnythingLLM" — ese HTML se sirve tal cual al navegador, así que "ver código
  fuente" los exponía (T049); el placeholder de ejemplo de email en `UsersPage.tsx` decía
  "sentinel.com.ar".
- `frontend/index.html`: `<title>` estático cambiado de "Sentinel Secure AI Gateway" a un
  placeholder neutro ("Guardian"), sobreescrito por `loadBranding()` antes del primer
  render — T050. (El default de fábrica de `branding.ts`, spec 020 pre-existente, es un
  debate de branding del producto base completo, fuera del alcance de esta feature.)
- `frontend/src/services/api.ts`: `updateModelCredential` manda `engine_params`, no
  `litellm_params` — T051.
- **Nuevo**: `tools/check-branding-neutral.js` (T047) — recorre `client/public/**`, los
  mensajes de error de `client/server.js` y el build de `frontend/` buscando
  `litellm`/`anythingllm`/`presidio`/`sentinel`, con la misma disciplina de excepciones
  explícitas y documentadas que ya usa `backend/tests/contract/test_branding_neutral_043.py`.
  Agregado al job `harness-tests` de `.github/workflows/ci.yml` — T052. **Gap real
  encontrado**: ni `client/` ni `frontend/` corrían sus tests en CI todavía; se agregaron
  ambos (`npm test`) en el mismo pase.
- 0 hallazgos verificados en `client/public/**`, mensajes de error de `client/server.js`, y
  el build de producción real de `frontend/` (`npx vite build` + `grep` sobre `dist/`).

## 8. US6 — Verificación de integración (completo salvo despliegue real)

- `specs/044-hub-chat-panel-admin/CHANGELOG.md` (este archivo) — T054.
- `frontend/tests/contract/backend-contracts.test.ts` (nuevo, 6 tests): contratos 4
  (`include_service`/`purpose`), 5 (`PATCH` parcial, `DELETE` con 409 propagado) y 6
  (`engine_params` nunca `litellm_params`) de la 043, del lado de `api.ts` — T057.
- T055/T056/T058 (corridas en vivo contra un despliegue real y las imágenes taggeadas):
  bloqueadas por credenciales de proveedor LLM y acceso a la instalación real de Elea, no
  disponibles en este entorno — diferido al pase de "testeo de calidad" pedido por el
  usuario después de que 043+044 estén completas.

## 9. Polish (completo salvo lo bloqueado por despliegue real)

- Sitio de docs: página nueva `docs/docs/administration/eleia-hub-workspaces.md`,
  registrada en `mkdocs.yml` — T059. `make -C deploy check-docs` da 1 fallo preexistente
  sin relación con la 043/044 (`test_env_incluye_helpers_tipados_y_el_plano_motor`, drift
  de `OPENAI_API_KEY` en `docs/tools/drift_gate.py`); los 4 checks reales del sitio (build,
  imagen, contenido, naming neutro) pasan en verde por separado, verificado corriéndolos uno
  por uno.
- `client/tests/unit/session-expired-upload.test.js` y
  `frontend/tests/unit/UsersPage.concurrent-edit.test.tsx` (T061): sesión vencida a mitad de
  subida responde 401/403/502 limpio, nunca 500; un 409 real del backend (conflicto de dos
  ediciones concurrentes) se muestra sin romper la pantalla.
- Revisión de accesibilidad/responsive (T062): las secciones nuevas siguen exactamente la
  misma convención que el resto de cada archivo (focus-visible en React, `.modal-box` en el
  Hub) — no se corrigió el déficit preexistente de breakpoints móviles ni `<label for>`
  explícito en los modales del Hub (afecta a TODOS los modales del archivo, no algo que esta
  feature introdujo), queda anotado como deuda fuera de alcance.
- T063 (corrida final + nota de cierre): bloqueada por T055/T056, mismo motivo.

## 10. Regresión completa verificada

- **Backend**: `pytest` completo contra Postgres real y aislado (contenedor descartable,
  separado del incidente documentado abajo) — corrida DOS veces en este pase: **2732
  passed** justo después de agregar `masking_by_user` a `costs.py`, y **2734 passed, 9
  failed, 21 skipped** en la corrida final (los 2 de más son los tests nuevos de
  `test_costs_masking_by_user_044.py`) — los mismos 9 fallos preexistentes de siempre
  (`test_catalogo_motor_paralelismo`, `test_chat_auto_router` ×7, `test_policy_unit`),
  documentados también en el `CHANGELOG.md` de la 043. **0 regresiones** en ninguna de las
  dos corridas.
- **`client/`**: 15/15 tests (`node --test`) en verde.
- **`frontend/`**: `tsc --noEmit` limpio, `npx vite build` exitoso, 13/13 tests (Vitest) en
  verde.

## 11. Incidente operativo (transparencia, no relacionado con el código de la feature)

Al levantar Postgres+Redis de este repo (`docker compose up -d db redis`) para correr la
suite del backend, `docker compose` recreó dos contenedores (`sentinel-db`/`sentinel-redis`)
que ya existían y pertenecían a un proyecto AJENO ("Basa", en
`GuardIAn-Master/GuardIAn-secure`), porque ambos proyectos definen el mismo `container_name`
por default y comparten el mismo nombre de red Docker. Detectado de inmediato: se restauraron
esos contenedores contra su volumen original (`basa_postgres_data`, intacto — Postgres no
reformatea un volumen ya inicializado) y se confirmó con una consulta real que sus datos
sobrevivieron sin pérdida. Las pruebas de esta feature se corrieron después contra un
Postgres descartable y completamente aislado (`elea-pytest-db`, puerto 5434, sin volumen
compartido con ningún otro proyecto).

## 12. Revisión de código del PR (09-sep) — 8 hallazgos, 7 corregidos

Revisión con 7 ángulos de búsqueda en paralelo (correctness ×3, reuse, simplificación,
eficiencia, altitud) sobre el diff completo del PR, cada candidato verificado por un
segundo agente antes de reportarlo. 6 de los 8 hallazgos tenían relación directa con lo
que 043/044 prometieron arreglar (aislamiento, atribución, enmascarado determinista) —
ninguno era una regresión introducida por la revisión misma, todos preexistían en el
código ya mergeado a esta rama.

**Corregidos (7), cada uno con test nuevo, verificados contra Postgres real:**

1. **"Desactivar" en el panel no revocaba las API keys** — el toggle usa `PATCH
   is_active=false`, no `DELETE`; solo este último revocaba llaves. Ahora `patch_user`
   también las revoca (nunca las reactiva automáticamente al volver a activar — evita
   restaurar en silencio la capacidad de una llave potencialmente comprometida).
   `backend/src/api/users.py`.
2. **El placeholder determinista podía colisionar** entre dos valores distintos del
   mismo tipo dentro de un chunk (HMAC mod 10.000 — ~50% de probabilidad de colisión ya a
   los ~118 valores, paradoja del cumpleaños). Ensanchado a mod 100.000.000 (~11.700
   valores para el mismo 50%, físicamente imposible en un chunk de 4000 caracteres) +
   reintento determinista (`probe`) como respaldo que garantiza que dos valores distintos
   NUNCA terminan con el mismo placeholder, aunque colisionen.
   `litellm/extensions/sentinel_guardian_policy.py`.
3. **Asignar un dueño en "Espacios sin asignar" no funcionaba de verdad** —
   `add_member()` nunca seteaba `owner_user_id` ni cambiaba `status`, así que el espacio
   seguía apareciendo en la lista para siempre y la persona asignada quedaba como
   "member". Ahora el primer miembro de un espacio sin dueño pasa a ser el dueño.
   `backend/src/services/workspace_service.py`.
4. **Un `document_id` no-UUID perdía la fila de auditoría entera**, no solo ese campo —
   `_audit()` parseaba el UUID dentro del mismo `try` que escribe toda la fila. Ahora se
   parsea antes, aparte, y se degrada solo ese campo a `NULL` si no es válido.
   `backend/src/api/gateway.py`.
5. **Un bloqueo por guardrail no atribuía a la persona real** — `_auditar_bloqueo` nunca
   leía `acted_for_user_id` (que `custom_auth.py` ya calculaba), y el modelo/INSERT del
   endpoint interno de auditoría ni siquiera tenía esa columna. Agregada en los tres
   lugares: `sentinel_guardrail.py`, `backend/src/api/internal.py` (`AuditEntry` + SQL).
6. **El sanitizador de errores podía truncar texto legítimo** — cortaba en el primer
   `:` de todo el mensaje si "litellm." aparecía en cualquier posición, no solo como
   prefijo real de módulo. Anclado con regex al inicio del string.
   `backend/src/services/error_sanitizer.py`.
7. **El tipo `account_type` del frontend declaraba `"human"`**, un valor que el backend
   nunca manda (manda `"person"`) — trampa silenciosa sin error de TypeScript. Corregido
   a `"person" | "service"`. `frontend/src/services/api.ts`.

**Investigado y descartado (1)**: la lista de términos prohibidos del test de branding
del backend no incluye "sentinel" — no es un bug: "Sentinel Gateway" es el nombre neutro
real del producto base compartido (usado deliberadamente por `error_sanitizer.py` y como
nombre del logger), la regla "nunca Sentinel" aplica solo a las superficies de cara a
Eleia, ya cubiertas por `tools/check-branding-neutral.js`.

**Regresión**: suite completa corrida de nuevo tras los 7 fixes — **2746 passed, 9 failed
(los mismos de siempre), 21 skipped, 0 regresiones** (los 12 tests nuevos de esta revisión
están dentro del total: +12 respecto de la corrida anterior).

## 13. Corrida real de punta a punta (09-sep) — Parte A del plan de verificación

Primera corrida EN VIVO contra un despliegue real completo (no dobles de prueba) —
`elea/docker-compose.yml` con **credenciales reales de Azure OpenAI** ya presentes en
`.env` de este entorno (`AZURE_OPENAI_ENDPOINT=elea-openai-dev.openai.azure.com`, no
inventadas). Los 7 servicios (`db`, `redis`, `nlp-analyzer`, `engine`, `backend`,
`anythingllm`, `client`, `frontend`) se buildearon desde el código de ESTA rama y se
aprovisionaron de cero (admin, llaves de servicio con `tool_type=servicio`, conexión
motor↔AnythingLLM) replicando exactamente lo que hace `elea-installer/install.sh`.
Stack aislado (`STACK_PREFIX=eleae2e`, sin tocar ningún contenedor de otro proyecto),
apagado y volúmenes descartados al terminar.

### Verificado en verde (real, no simulado)

- **P1 (aislamiento)**: usuaria nueva sin espacios → `workspaces: []`; acceso directo a un
  espacio ajeno por slug conocido → **403**; sin sesión → **401**; tras agregarla como
  miembro, lo ve. Los 4 pasos, contra el backend/DB reales.
- **P2 (enmascarado determinista) — EL bug original de Tomás, verificado resuelto de
  punta a punta**: documento de 9600 caracteres (3 chunks) con "Julián Fernández"
  repetido 60 veces. Los 8 fragmentos que el RAG devolvió comparten el MISMO placeholder
  (`[PERSON_36717395_6b95]`) en los tres chunks — y la pregunta "¿Qué datos tiene Julián?"
  contra Azure GPT-4o-mini real respondió con el DNI/email/teléfono REALES (bóveda de PII
  desenmascarando correctamente con el nuevo índice HMAC ensanchado de la revisión §12).
- **Chat directo (sin RAG)**: costo atribuido correctamente a la persona real (`ana`,
  no a ninguna cuenta de servicio).
- **Branding del Hub**: título/logo/tagline neutros por default en un compose sin
  `HUB_BRAND_*` configuradas — confirma el fix de la sesión anterior funcionando en un
  despliegue real, no solo en tests.
- **Panel (Eleia Guardian)**: login, dashboard, costos por modelo, "Espacios sin
  asignar" — sin ningún nombre de motor/proveedor visible.

### 2 bugs reales encontrados y corregidos EN esta corrida

1. **Las cuentas de servicio nuevas no quedaban marcadas — el bug original de Tomás
   reaparecía en cualquier instalación fresca.** La migración 018 solo hace backfill de
   `account_type='service'` para usuarios `svc.%` que YA EXISTÍAN al migrar. Cualquier
   cuenta creada DESPUÉS (exactamente lo que `install.sh` hace en el primer arranque de
   cada instalación nueva) quedaba con `account_type='person'` — reaparecía en la tabla
   principal de personas del panel, tal cual el reclamo original ("aparece
   anythingllm-provider y rag-masking como usuarios"). Encontrado en vivo creando las 2
   llaves de servicio del stack de prueba y viéndolas en la tabla principal del panel.
   **Corregido**: `POST /users` ahora detecta el prefijo `svc.` en la creación
   (`backend/src/api/users.py`), verificado con un usuario nuevo real (quedó
   `account_type='service'` en la base y fuera de la tabla principal) y con test nuevo
   (`test_crear_usuario_svc_via_api_queda_marcado_como_cuenta_de_servicio`).
2. **`public/index.html` tenía dos strings más con "elea" en minúscula** que el chequeo
   automatizado no había atrapado (el selector de modelo decía "Automático (**elea**
   decide)"; un mensaje de error decía "No se pudo contactar a **elea**") — corregidos a
   "Guardian decide" / mensaje neutro sin nombre de cliente. El logo por default también
   seguía siendo el archivo real de Eleia (`/eleia-logo.png`) aunque el texto ya fuera
   neutro — se agregó `guardian-logo.svg` (ícono genérico) como default, con
   `HUB_BRAND_LOGO_URL` fijado explícitamente en `elea-installer` para no perder el logo
   real de Eleia en la instalación real.

### 1 limitación arquitectónica real encontrada (no un bug de código, no se "arregla" con un parche)

**El costo de una pregunta RAG (a través del motor de documentos) queda atribuido a la
cuenta de servicio, no a la persona real que preguntó** — a diferencia del chat directo
y del enmascarado, que sí atribuyen bien. Causa: la llamada real al modelo en el camino
RAG la hace el motor de documentos (AnythingLLM) con SU PROPIA credencial de proveedor
fija (`svc.anythingllm-provider`, `can_act_on_behalf=false` a propósito — nunca actúa en
nombre de nadie, "habla con el motor por su cuenta"), no el Hub — el Hub nunca tiene la
oportunidad de inyectar `X-Guardian-Acting-User` en ESA llamada específica, porque no es
él quien la hace. Verificado en vivo: la misma pregunta hecha por chat directo atribuye
bien a la persona ($0.000016 → "ana"); hecha con `slug` (RAG) atribuye a la cuenta de
servicio ($0.000496 → "svc.anythingllm-provider2"). Esto es un límite real del diseño
actual (AnythingLLM es de terceros, sin ningún mecanismo para pasar "en nombre de quién"
en su llamada saliente al motor) — no un descuido corregible con un cambio chico; queda
documentado acá como hallazgo real para decidir si amerita trabajo futuro (por ejemplo,
resolver el usuario real desde la membership del espacio al momento de auditar en el
motor, en vez de depender de un header que AnythingLLM nunca va a reenviar).
