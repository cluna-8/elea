# Verificación 043+044 — qué falta y cómo probar que se solucionó todo

**Fecha**: 08-sep-2026
**Alcance**: [043-aislamiento-atribucion-motor](043-aislamiento-atribucion-motor/spec.md) (motor/backend) +
[044-hub-chat-panel-admin](044-hub-chat-panel-admin/spec.md) (Eleia Hub + Eleia Guardian).
**Para quién**: quien vaya a dar por cerrado el trabajo frente a Tomás Mc Nally (Elea) — un plan
de pruebas en dos partes: **funcional** (¿se solucionó lo que él reportó?) y **técnica** (¿el
código que lo soluciona está sano?).

---

## 1. Qué falta (12 tareas, todas bloqueadas por infraestructura real)

Nada de esto es código sin escribir — es **verificación en vivo** que este entorno de desarrollo
no puede hacer porque no tiene acceso a lo que hace falta. Se resuelve corriendo la Parte A de
este documento contra un despliegue real.

| # | Tarea | Spec | Bloqueada por |
|---|---|---|---|
| 1 | T064 — sitio de docs con los endpoints/conceptos nuevos | 043 | Nada en realidad — **esta sí se puede hacer ahora** si nadie la hizo (ver §6) |
| 2 | T068 — `quickstart.md` completo (043) contra `docker compose up` desde cero | 043 | Credenciales reales de proveedor LLM (Azure OpenAI u otro) |
| 3 | T069 — reconstruir/taggear imágenes `elea-guardian-backend`/`elea-guardian-engine` | 043 | Depende de T068 |
| 4 | T019 — `quickstart.md` §1/§6 (044): migración de los 3 espacios reales | 044 | Acceso a la instalación real de Elea |
| 5 | T027 — `quickstart.md` §2 (044): presupuesto en vivo | 044 | Despliegue real |
| 6 | T035 — `quickstart.md` §3 (044): CSV real del cliente | 044 | El CSV real de Elea + despliegue real |
| 7 | T046 — `quickstart.md` §4 (044): panel de usuarios en vivo | 044 | Despliegue real |
| 8 | T053 — `quickstart.md` §5 (044): branding en vivo | 044 | Despliegue real |
| 9 | T055 — `quickstart.md` completo, instalación limpia | 044 | Credenciales reales de proveedor LLM |
| 10 | T056 — `quickstart.md` completo, instalación real/copia | 044 | Acceso a la instalación real de Elea |
| 11 | T058 — reconstruir/taggear imágenes `elea-rag-client`/`elea-guardian-frontend` | 044 | Depende de T055/T056 |
| 12 | T063 — corrida final + nota de cierre firmada | 044 | Depende de T055/T056 |

**En una frase**: todo lo que falta es "prenderlo con datos reales y mirar la pantalla" — el
código, su lógica y su cobertura automatizada ya están hechos y verificados (ver Parte B).

---

## 2. Parte A — Plan de pruebas FUNCIONAL

Verifica que lo que Tomás reportó (mails del 03-sep y 07-sep) esté realmente resuelto, no solo
que el código exista. Cada prueba mapea 1:1 a una frase textual de sus mails.

**🟢 Corrida en vivo (09-sep)**: P1, P2 y P3 ya se corrieron contra un despliegue real completo
(`elea/docker-compose.yml`, credenciales reales de Azure OpenAI, `STACK_PREFIX=eleae2e`
aislado) — resultado completo y los 2 bugs reales que encontró y corrigió esa corrida en
`specs/044-hub-chat-panel-admin/CHANGELOG.md` §13. P4-P7 y la corrida contra la instalación
real de Elea (con sus 3 espacios reales) siguen pendientes — ver el detalle marcado abajo.

### Prerrequisitos

- `docker compose up` de 043+044 (o la instalación real de Elea) con credenciales reales de
  proveedor LLM.
- Dos usuarios de prueba con roles distintos (uno cliente, uno admin) y sesiones separadas
  (dos navegadores o uno en incógnito).
- El CSV real del cliente con un nombre repetido en varias filas (para P2).

### P1 — "La memoria de chats es compartida... veo el historial de usuarios previos" (07-sep, prioritario)

| Paso | Acción | Resultado esperado |
|---|---|---|
| 1 | Usuario A crea un espacio, sube un documento, hace una pregunta | El espacio y la respuesta quedan visibles para A |
| 2 | Usuario B (recién registrado) entra al Hub | Ve el estado vacío ("Todavía no tenés espacios...") — **NO** el historial de A |
| 3 | B intenta abrir el espacio de A por una URL/id copiado a mano | "No tenés acceso a este espacio", sin datos |
| 4 | A agrega a B como miembro desde el panel "Miembros" | B ve el espacio en su lista al recargar |
| 5 | B abre el espacio, crea su propio hilo | El hilo de B y el hilo de A no se cruzan; cada uno ve solo el suyo |
| 6 | Cualquier llamada del Hub sin sesión (ventana privada, sin login) | Pide iniciar sesión, nunca devuelve datos |

**Falla si**: en cualquier paso 2-6 aparece un dato de la otra persona.

**🟢 Corrido en vivo (09-sep)**: los pasos 2, 3, 4 y 6 pasaron contra el stack real (usuaria
nueva sin espacios, 403 en acceso directo, 401 sin sesión, visible tras agregarla). Pasos 1 y
5 (crear espacio+pregunta, hilos que no se cruzan) no se ejecutaron por API en esta corrida —
quedan para la próxima pasada, junto con P4-P7.

### P2 — "El enmascaramiento no parece ser determinista... Julián se enmascara distinto" (03-sep)

| Paso | Acción | Resultado esperado |
|---|---|---|
| 1 | Subir el CSV real con el nombre repetido en filas separadas por más de un trozo de 4000 caracteres | El resumen de protección post-subida cuenta ese nombre **una sola vez** (no una entrada por trozo) |
| 2 | Preguntar "¿qué registros tiene [el nombre]?" contra ese espacio | La respuesta lista **todas** sus filas, con el nombre real (no un placeholder distinto por fila) |
| 3 | Subir el mismo CSV una segunda vez (documento nuevo) | El resumen es coherente; el placeholder interno (verificable en logs/backend, no en la UI) es **distinto** al de la primera subida — sin seudónimo estable entre documentos |

**Falla si**: el mismo dato recibe placeholders distintos dentro de un mismo documento.

**🟢 Corrido en vivo (09-sep) — resuelto, confirmado con Azure OpenAI real**: documento de
9600 caracteres (3 chunks), mismo placeholder en los 8 fragmentos que cruzan los 3 chunks; la
pregunta al RAG devolvió el DNI/email/teléfono REALES (bóveda de PII desenmascarando bien).
Paso 3 (segunda subida, documento distinto) no se corrió esta vez — el resto del guion sí,
con el CSV/documento de prueba de esta sesión (no el CSV real del cliente todavía).

**⚠️ Segundo reclamo del mismo mail (03-sep), NO cubierto por P2 — fuera de alcance de 043/044**:
"el almacenamiento del csv parece haberse hecho dentro de una Base Vectorial con Chunks
definidos, lo que hace que no se pueda aplicar un análisis cruzando filas/columnas o incluso
otros archivos como el que se suele aplicar en áreas como Finanzas/BI." No es un bug de
enmascarado — es una limitación arquitectónica real: el motor de documentos hace búsqueda
semántica sobre chunks, no consultas tabulares/SQL. Ya trackeado como
[spec 046](_retiradas/046-analisis-exacto-datos-eleia-hub/spec.md) ("Análisis exacto de datos
Excel/CSV en Eleia Hub", cita esta misma frase del mail como input), que a su vez depende de
un motor nuevo (DB-GPT o equivalente, texto→SQL/DuckDB) especificado aparte en backend —
decisión ya tomada el 31-ago: queda fuera del piloto, AnythingLLM alcanza para eso. Sigue en
`Draft`, bloqueada en investigación. No forma parte del cierre de 043/044.

### P3 — "Aparece en modelos: license y chat-ui" / "en usuarios: anythingllm-provider y rag-masking"

| Paso | Acción | Resultado esperado |
|---|---|---|
| 1 | Panel → Costos → Top modelos | Ninguna fila dice `license` ni `chat-ui` — solo modelos reales |
| 2 | Panel → Usuarios & Presupuestos, tabla principal | Ninguna fila dice `svc.anythingllm-provider` ni `svc.rag-masking` |
| 3 | Desplegar "Cuentas de servicio" en esa misma página | Ahí sí aparecen, con su propósito, de solo lectura |

**Falla si**: `license`/`chat-ui`/`svc.*` aparecen en la tabla principal de modelos o usuarios.

**🟡 Corrido en vivo (09-sep) — encontró y corrigió un bug real**: `top_models` sin
`license`/`chat-ui`, confirmado. Pero las cuentas de servicio SÍ aparecían en la tabla
principal — la migración 018 solo marca `account_type='service'` a cuentas ya existentes al
migrar, no a las que crea `install.sh` en una instalación nueva. Corregido en
`backend/src/api/users.py` (`POST /users` detecta el prefijo `svc.` al crear) y verificado con
una cuenta nueva real — ver CHANGELOG §13. Falta re-correr este paso completo con el fix ya
adentro contra una instalación fresca (esta corrida lo verificó a nivel API/DB, no
recorriendo la UI del paso 2/3 de nuevo tras el fix).

### P4 — "No aparece nada asociado a mi usuario... no puedo evaluar costos"

| Paso | Acción | Resultado esperado |
|---|---|---|
| 1 | El usuario de prueba hace 2-3 preguntas (con y sin espacio/RAG) y sube un documento | Cada pregunta tiene costo y modelo real |
| 2 | Panel → Costos → filtrar por ese usuario | Aparece con costo real acumulado de sus preguntas |
| 3 | Misma vista, tabla "Protección de documentos por persona" | Aparece con la subida contada como documento, sin costo |
| 4 | Badge de presupuesto en el Hub, tras cada respuesta | Sube en menos de 5s |
| 5 | Agotar el presupuesto de prueba y volver a preguntar | Bloqueo antes de enviar (o inmediatamente si lo decide el backend), mismo mensaje neutro en ambos casos |

**Falla si**: el usuario sigue "invisible" en Costos, o el presupuesto se muestra pero no se aplica.

**🔴 Corrido en vivo (09-sep) — encontró una limitación arquitectónica real, sin resolver**:
el paso 1 con "sin espacio/RAG" (chat directo) atribuye bien — verificado, el costo aparece a
nombre de la persona real. El paso 1 CON espacio/RAG **NO atribuye bien**: el costo de la
pregunta queda a nombre de la cuenta de servicio del motor de documentos, no de la persona. El
enmascarado (subida de documentos) SÍ atribuye bien. Detalle completo, causa raíz y por qué no
es un fix chico en el CHANGELOG de la 044 §13 — esto es lo más importante que dejó esta
corrida para decidir antes de cerrar la 044 como "lista": ¿se acepta esta limitación en el
camino RAG, o hace falta una spec nueva para resolverla?

### P5 — "No se puede editar roles ni eliminar usuarios, ni editar mails"

| Paso | Acción | Resultado esperado |
|---|---|---|
| 1 | Editar solo el rol de un usuario | Cambia el rol, el resto de sus datos queda igual |
| 2 | Editar solo el email del mismo usuario | Cambia el email, nada más |
| 3 | Desactivar al usuario → intenta loguear | No puede loguear; reactivar → puede loguear de nuevo |
| 4 | Dar de baja a otro usuario (con la confirmación escribiendo su username) | No puede loguear; su consumo histórico sigue visible en Costos bajo su nombre |
| 5 | Intentar darse de baja a uno mismo | La UI lo impide con una explicación, sin llamar al backend |
| 6 | Intentar dar de baja al último admin activo | Lo mismo — bloqueado con explicación |

**Falla si**: cualquier paso no tiene efecto, o rompe la pantalla.

**🔴 Corrido en vivo (09-sep) — encontró y corrigió un bug crítico real**: pasos 1-4 OK.
Los pasos 5-6 destaparon que las guardas de auto-baja/último-admin SOLO vivían en
`DELETE`, no en `PATCH` (el endpoint que realmente usa el toggle "Desactivar" del
panel) — un `PATCH` directo dejó a la instancia sin ningún admin activo, recuperado
solo por `UPDATE` manual en Postgres. Corregido en `backend/src/api/users.py`
(`_bloquear_baja_insegura`, compartida por `PATCH` y `DELETE`), reverificado en vivo y
con 3 tests nuevos — ver CHANGELOG §14.

### P6 — Branding (mencionado indirectamente: nombres de motor no deben aparecer)

| Paso | Acción | Resultado esperado |
|---|---|---|
| 1 | Detener el motor de documentos a propósito, preguntar en un espacio | "El servicio de documentos no está disponible...", sin nombres técnicos |
| 2 | Ver código fuente del Hub (`Ctrl+U` / "Ver código fuente") | Sin "AnythingLLM"/"LiteLLM"/"Presidio" en ningún lado, ni en comentarios |
| 3 | Panel → Seguridad, tarjeta de detección NLP | Nombre neutro |
| 4 | Título de la pestaña del navegador (ambas UIs) | El de la marca configurada de Eleia |
| 5 | `node tools/check-branding-neutral.js` contra el despliegue real (`client/public`, build de `frontend/`) | 0 hallazgos |

**Falla si**: aparece cualquier nombre de motor/proveedor en una superficie que la persona ve.

**🔴 Corrido en vivo (09-sep) — encontró y corrigió un segundo bug real**: paso 1 con el
motor de documentos completamente caído (no un error HTTP, un `fetch()` que lanza)
devolvía `{"error":"fetch failed"}` crudo — corregido, ahora mensaje neutro igual que el
caso ya manejado de error HTTP. Pasos 2-5: verificados en vivo — título de pestaña con
marca real de Eleia confirmado con `document.title` en el navegador real para ambas UIs
(panel: "Eleia Guardian", Hub: "Eleia Hub"). De paso se limpiaron 4 comentarios de
desarrollo en `public/index.html` que mencionaban "Elea" por nombre (no nombres de
motor, pero sí una fuga de identidad del cliente original hacia cualquier OTRO cliente
que corra este mismo código con marca neutra) — ver CHANGELOG §14.

### P7 — Continuidad de la instalación existente (los 3 espacios reales del cliente)

| Paso | Acción | Resultado esperado |
|---|---|---|
| 1 | Tras desplegar 043+044 sobre la instalación (o una copia) con los 3 espacios reales (`Area 1`, `Contabilidad`, `Análisis NDA`) | El admin los ve en "Sin asignar" (panel o Hub) |
| 2 | Asignarles miembros | Los usuarios correspondientes empiezan a verlos |
| 3 | Abrir documentos/hilos previos a la migración | Siguen consultables; los subidos antes de esta feature muestran el aviso de "esquema anterior" al preguntar por un dato protegido |

**Falla si**: se pierde algún espacio/documento/hilo existente, o queda inaccesible para siempre.

**🟡 No ejecutable tal como está escrito, en esta sesión (09-sep)**: requiere los 3
espacios reales del cliente con su contenido — no existen en este entorno de
desarrollo. Verificación parcial como proxy: un espacio de la corrida anterior
(§13 del CHANGELOG) siguió accesible con dueño/membresía intactos tras bajar y volver a
levantar el stack completo. El mecanismo de aviso "esquema anterior"
(`MASKING_DETERMINISM_SINCE`) se confirmó presente en el código, fail-closed por
default, pero no se ejecutó en vivo contra un documento real pre-fecha-de-corte. Sigue
pendiente una corrida contra la instalación real o una copia de sus datos — ver
CHANGELOG §14.

---

## 3. Parte C — Independencia del CLI (Eleia Hub funciona con cualquier Guardian)

**Pedido explícito del dueño del producto (09-sep-2026)**: confirmar en la práctica que
**Eleia Guardian es el firewall/protector** y **Eleia Hub es un cliente más** — sin ningún
acoplamiento especial entre los dos. El mismo Hub, sin tocar código, debe poder apuntar a
CUALQUIER instancia de Guardian (la propia de Elea, la base genérica, o la de otro cliente
como Sentinel/Evidenze) solo cambiando su configuración de entorno — exactamente como
apuntaría Claude Code, Copilot o Cursor a cualquier Connection.

**Instancias disponibles para esta prueba** (ya existen en esta máquina, no hace falta
crear nada nuevo):

| Instancia | Marca | Repo |
|---|---|---|
| Eleia Guardian | Eleia | `LLMADMIN-Elea/elea` (esta) |
| Guardian (base) | Guardian / hoy configurado como "Basa" | `GuardIAn-Master/GuardIAn-secure` |
| Sentinel | Evidenze | `EVIDENZE/SENTINEL` |

### Guion

| Paso | Acción | Resultado esperado |
|---|---|---|
| 1 | Levantar las 3 instancias (`docker compose up`, cada una con sus propias credenciales de proveedor LLM) | Las 3 responden en sus puertos propios, sin pisarse entre sí (mismo cuidado que el incidente documentado en el `CHANGELOG.md` de la 044 — `STACK_PREFIX` distinto por instancia si comparten red Docker) |
| 2 | Crear una llave/Connection de servicio para el Hub en la instancia A (Eleia Guardian) | El Hub, apuntado con `ELEA_BACKEND_URL`/`ANYTHINGLLM_*`/`MASKING_VIRTUAL_KEY` de la instancia A, funciona: login, crear espacio, subir documento, preguntar |
| 3 | Sin tocar código del Hub — solo cambiar las variables de entorno para apuntar a la instancia B (Guardian base) | El Hub funciona igual: login, espacios, presupuesto — con los datos y usuarios de la instancia B, sin ningún rastro de la instancia A |
| 4 | Repetir apuntando a la instancia C (Sentinel) | Mismo resultado — el Hub no tiene ninguna referencia hardcodeada a "Eleia" en su lógica, solo en textos de marca (que si Sentinel tiene su propio `brand.json`, deberían reflejar la marca de Sentinel, no la de Eleia) |
| 5 | Verificar branding neutro en los 3 casos | El Hub muestra la marca de CADA instancia (título de pestaña, logo, tagline, tag del tenant, label de gobernanza) — nunca la de Eleia salvo cuando apunta a la instancia de Eleia |

**Falla si**: el Hub necesita algún cambio de CÓDIGO (no solo de configuración) para
funcionar contra una instancia distinta de la de Elea, o si arrastra datos/sesión de una
instancia a otra.

**Resuelto (09-sep)**: el candidato que este documento marcaba como pendiente — el Hub
tenía "Elea"/"Eleia"/"Laboratorios ELEA" fijos en `client/public/index.html` (título, logo,
tag del tenant, tagline, label de gobernanza, nombre de archivo de transcripción) y en
`client/server.js` (log de arranque, el `tool` que viaja a `/gw/inspect`, un mensaje de
error) — ya se corrigió: nuevo endpoint `GET /api/branding` + `HUB_BRAND_*` por env
(mismo patrón runtime que `frontend/src/services/branding.ts`), default NEUTRO sin
ninguna de esas variables configuradas, verificado con
`client/tests/contract/test_branding.test.js` (incluye un caso simulando una marca de
OTRO cliente, sin ningún rastro de "Elea"). `elea-installer/docker-compose.yml` ya fija
las `HUB_BRAND_*` con los valores reales de Eleia, así que la instalación real de Elea no
pierde su marca actual.

**Nota honesta**: el guion en sí (levantar las 3 instancias y probar en vivo) no se
ejecutó en esta sesión — requiere levantar 3 stacks completos con credenciales reales de
proveedor LLM cada uno, que no están disponibles en este entorno. Lo que sí quedó resuelto
es el bloqueo de código que habría hecho fallar el paso 5 del guion.

---

## 4. Parte B — Plan de pruebas TÉCNICO

Verifica que el código que resuelve lo de arriba esté sano — esto **sí se puede correr ahora**,
sin despliegue real, y ya se corrió durante la implementación (ver los `CHANGELOG.md` de cada
spec para el detalle exacto). Repetirlo sirve como confirmación final antes de mergear.

### T1 — Regresión completa del backend

```bash
cd elea/backend
python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
docker run -d --name verif-db -p 5555:5432 \
  -e POSTGRES_DB=sentinel_gateway -e POSTGRES_USER=sentinel_admin -e POSTGRES_PASSWORD=sentinelsecurepass123 \
  postgres:16-alpine
export POSTGRES_HOST=localhost POSTGRES_PORT=5555 POSTGRES_USER=sentinel_admin \
       POSTGRES_PASSWORD=sentinelsecurepass123 POSTGRES_DB=sentinel_gateway
.venv/bin/python -m pytest -q
```
**Esperado**: `2734 passed`, exactamente estos 9 fallos preexistentes y ninguno más —
`test_catalogo_motor_paralelismo`, `test_chat_auto_router` (×7), `test_policy_unit` — documentados
como sin relación con 043/044 en ambos `CHANGELOG.md`. Cualquier fallo FUERA de esta lista es una
regresión real.

### T2 — Suite del Hub (`client/`)

```bash
cd elea/client && npm ci && npm test
```
**Esperado**: 15/15 en verde (aislamiento, presupuesto, `document_id`, reintento, "sin asignar",
sesión vencida).

### T3 — Suite del panel (`frontend/`)

```bash
cd elea/frontend && npm ci
npx tsc --noEmit
npx vite build
npm test
```
**Esperado**: `tsc` sin errores, build exitoso, 13/13 tests en verde (edición parcial, guardas de
baja, cuentas de servicio, contratos 4/5/6, edición concurrente).

### T4 — Branding neutro automatizado

```bash
cd elea
node tools/check-branding-neutral.js
```
**Esperado**: `0 términos prohibidos`. (Cubre `client/public/**`, errores de `client/server.js`, y
el build de `frontend/` si `frontend/dist` existe — correr T3 antes para incluirlo.)

### T5 — Sitio de docs

```bash
cd elea && make -C deploy check-docs
```
**Esperado**: los 4 checks reales del sitio (`test_docs_image`, `test_docs_strict_build`,
`test_docs_content`, `test_docs_neutral_naming`) en verde. El único fallo conocido
(`test_env_incluye_helpers_tipados_y_el_plano_motor`, en `docs/tools/drift_gate.py`) es
preexistente y sin relación — verificar que sigue siendo el ÚNICO fallo.

### T6 — CI de GitHub

```bash
gh pr checks <numero-de-PR>
```
**Esperado (al momento de escribir esto)**: el job `harness-tests` (tsc + vitest + node --test +
branding-neutral) debería pasar — no se corrió en CI todavía dentro de esta sesión, correrlo es
parte de cerrar el PR. El job `backend-tests` va a fallar en el paso `check_stack_prefix.sh`
("Render de container_name") — **esto es preexistente en `main`** (las últimas 5 corridas de CI en
`main` también fallan), no una regresión de este trabajo; no bloquea el merge por ese motivo, pero
sí conviene abrir un issue aparte para arreglarlo (`scripts/check_stack_prefix.sh` tiene una lista
de servicios desactualizada — le falta contemplar `profiles: ["full"]` en `frontend`).

### T7 — Revisión de seguridad (rápida, manual)

- [ ] Ningún endpoint nuevo de `workspaces.py`/`inspect.py`/`users.py` confía en un dato que
  manda el cliente para decidir autorización (siempre re-consulta `workspace_memberships` o el
  rol real del actor) — ver `diagnostico.md` §1 de la 043.
- [ ] El header `X-Guardian-Acting-User` se valida contra `can_act_on_behalf` + tenant antes de
  usarse — nunca se confía a ciegas.
- [ ] Ningún mensaje de error nuevo (`client/server.js`, `chat.py`, `gateway.py`) filtra un
  detalle interno (stack trace, nombre de motor, ruta de archivo).
- [ ] Las 403 de `workspaces.py` son uniformes (nunca revelan si un espacio existe) — confirmado
  en `_denied()`.

---

## 5. Checklist final de aceptación

Cerrar como "solucionado para Tomás" requiere Parte A y Parte B en verde; Parte C cierra el
pedido explícito de arquitectura (09-sep) — Guardian como firewall, Hub como cliente
intercambiable:

- [ ] Parte A (§2, P1-P7) corrida contra un despliegue real o una copia de la instalación de
  Elea, sin ningún "Falla si" disparado.
- [ ] Parte C (§3) corrida contra las 3 instancias (Eleia Guardian, Guardian base, Sentinel) —
  el Hub funciona contra las 3 sin cambios de código.
- [ ] Parte B (§4, T1-T7) corrida en este repo, sin regresiones nuevas.
- [ ] Las 12 tareas de §1 quedan marcadas `[X]` en `tasks.md` de cada spec, con el resultado
  registrado en su `CHANGELOG.md` (no antes — mismo criterio usado en todo este trabajo: nunca
  marcar hecho lo que no se verificó).

## 6. Nota — T64 (sitio de docs) es la única tarea de §1 sin bloqueo real

A diferencia de las otras 11, T064 (043 — actualizar `docs/docs/**` con los endpoints/conceptos
de la 043: `workspaces`, `X-Guardian-Acting-User`, `document_id`, `PATCH/DELETE /users`) no
requiere despliegue real. Este pase ya agregó una página nueva
(`docs/docs/administration/eleia-hub-workspaces.md`, del lado de la 044/Hub) pero **no** la
página específica de conceptos de motor/backend que pide T064 (contratos 1-6 de cara al
operador). Queda como el ítem más barato de sacar de la lista de pendientes sin esperar a nada.
