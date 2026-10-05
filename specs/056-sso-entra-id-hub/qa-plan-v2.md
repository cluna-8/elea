# QA crítico v2 — Spec 056 (re-revisión de la enmienda F1–F10)

**Rol**: qa-critico (segundo nivel, lectura lógica; seguridad, datos sensibles, permisos).
**Fecha**: 2026-10-05 · **Rama**: `cluna-8/056-sso-entra-id-hub-plan-v2` (HEAD `bad90e4`, enmienda
sobre `001f6c3`).
**Alcance (acotado)**: la tabla de resolución de `research.md:384-404` y los artefactos que cita
(`spec.md`, `plan.md`, `data-model.md`, `contracts/*`, `tasks.md`, `quickstart.md`), contra
[qa-plan.md](qa-plan.md), la constitución (`.specify/memory/constitution.md`) y el código real
(`backend/src/sso/api.py`, `entra.py`, `backend/src/services/auth_events.py`, `client/server.js`,
`client/public/index.html`, `client/Dockerfile`, `deploy/Makefile`, `deploy/release/publish-elea.sh`).
**No se reabre el diseño central** (D1–D8, F1 y la elección del tope son del owner). **No se editó
ningún artefacto del plan ni código de producto**: solo este archivo.

**Convención de evidencia**: **[V]** verificado leyendo el código citado (o ejecutando algo, si se
dice). **[I]** inferido de la lectura: hay que confirmarlo con un test antes de darlo por cierto.
Marco normativo: Principio II como normativa del perfil de país (Ley 25.326 / AAIP); no se reporta
la ausencia de GDPR ni de EU AI Act.

## Veredicto

**F1 a F10 están cerrados** en los artefactos de la spec. **F1, F2 y F3 (los bloqueantes) cierran con
la evidencia de abajo**, y **no hay hallazgos altos nuevos**. Encontré **2 hallazgos medios nuevos** (N1
y N2) y **6 bajos** (N3 a N8). Ninguno bloquea `/speckit-implement`: N1 y N2 conviene absorberlos en
la spec y en las tareas (por los skills `speckit-*`) antes de que el tramo correspondiente arranque;
los bajos se absorben dentro de los tests de cada tarea.

| # | Estado | Cierra en | Residual |
|---|---|---|---|
| F1 | **Cerrado** | research.md:148-177; spec.md:66-71, :298-309; guardian-sso-api.md:75, :83-114; data-model.md:82; tasks.md:93-98, :111-115 | N1 (efecto del tope, ya aceptado, mal descripto), N4 (concurrencia) |
| F2 | **Cerrado** | research.md:296-306; hub-sso.md:128-150, :181-191; tasks.md:163-167, :204-210 | N5 (validación del origen), el cableado solo se prueba por lectura estática |
| F3 | **Cerrado** | research.md:308-329; hub-sso.md:193-201; instalador-y-release.md:87-98; tasks.md:168-172, :258, :368 | N6 (huecos acotados) |
| F4 | **Cerrado** | spec.md:258-262, :317-326; guardian-sso-api.md:30-35; hub-sso.md:35-36, :137; tasks.md:142, :164 | N3 (borde del helper) |
| F5 | **Cerrado** | research.md:264-277; hub-sso.md:40-55; data-model.md:37-53; tasks.md:135-138, :146 | N1 (el límite de ritmo también es un interruptor) |
| F6 | **Cerrado** | research.md:279-294; hub-sso.md:47-63, :71-87; spec.md:327-333; tasks.md:144-145, :155-162, :183, :189-198 | N7 (clase vecina, preexistente), N8 |
| F7 | **Cerrado** | spec.md:7-8, :38-96, :291-309, :317-333, :401-404; plan.md:6-15 | — |
| F8 | **Cerrado** | spec.md:77-80; guardian-sso-api.md:61-64, :72, :74; tasks.md:93, :106-108 | — |
| F9 | **Cerrado** | research.md:323-327; instalador-y-release.md:87-98; tasks.md:48, :297-298, :368, :408-410 | — |
| F10 | **Cerrado** | research.md:331-344; spec.md:92-96, :248-252; hub-sso.md:106, :112-113; quickstart.md:117-121; tasks.md:204, :345 | — |

---

## Detalle de F1 a F10

### F1 — Cerrado (alta)

**Qué verifiqué en el código** [V]:

- La premisa falsa estaba en la versión anterior de research.md; ahora la corrección está escrita en
  research.md:148-172 y reproduce el recorrido real: `GET /auth/sso/login` público entrega una cookie
  de estado válida (`api.py:203-247`); con ella y su `state`, un `code` inventado pasa
  `_leer_estado` (`api.py:260`), la comparación (`:264`) y el chequeo de `code` (`:269`); el
  `POST` a `token_endpoint` es `entra.py:280`; el rechazo cae en `except Exception` y escribe una
  fila (`api.py:297-302`). La cookie de estado es reutilizable durante 10 min: el backend solo la borra
  del navegador (`api.py:335`) y vence por `exp` (`api.py:59`, `:95`).
- El discovery está cacheado una hora (`entra.py:52`, `:201-206`), así que `/login` no amplifica
  llamadas salientes después de la primera. El único camino de amplificación pre-auth es el canje, y es el
  que el plan ahora acota.

**Por qué cierra**: la decisión extiende el tope al canje fallido con **contador propio** (misma
constante y ventana), y el chequeo va **antes** de `provider.exchange_code` (guardian-sso-api.md:89-92;
tasks.md:111-115), así que pasado el tope no hay fila **ni** llamada al directorio. `entra.py` no
cambia. Los rechazos que exigen identidad real (`api.py:313`, `:379`) siguen sin tope, y es correcto:
requieren un `id_token` firmado por el directorio. El test que pedía el QA v1 está tal cual en T005
(tasks.md:95): cookie válida + `code` basura, `tope + 5` veces → `tope` eventos y `tope` llamadas al
proveedor, 401 intacto. También están los contadores independientes y la ventana siguiente
(tasks.md:96-97; guardian-sso-api.md:111-114). La spec lo refleja (spec.md:66-71, FR-012 en
:298-309) y la auditoría sigue metadata-only: `emit_auth_event` guarda solo ids, rol y `ts`
(`auth_events.py:46-53`); no hay columna donde caiga `state` o `code`.

Nota de trazabilidad menor: research.md:386 cita la frase corregida como `research.md:149-151`; el
texto real está en `:148-151`. No afecta nada.

### F2 — Cerrado (alta)

Cada requisito que el QA v1 dejaba sin test tiene ahora una tarea con test:

| Requisito | Test que lo cubre |
|---|---|
| FR-001, US2 AS3 (sin botón sin SSO) | T014 `destinoBoton`: `enabled:false` y `return_origin:null` → sin botón (tasks.md:164; hub-sso.md:183-185) |
| FR-006, US2 AS2 (texto entendible) | T014 `mensajeError`: todo texto recuerda la contraseña (tasks.md:165; hub-sso.md:186-187) |
| FR-008, US1 AS5 | T014 `ofrecerCambioContrasena` (tasks.md:166) + T012 409 en `change-password` (tasks.md:154) |
| `sso_error` desconocido o con HTML | T014: desconocido, vacío y `<img onerror>` → genérico sin eco del valor (hub-sso.md:186-187) |
| Cableado de `index.html` | T014, última viñeta: lectura estática, carga `/sso-ui.js`, usa las tres funciones, sin `innerHTML` en el error (tasks.md:167; hub-sso.md:189-191) |

Verifiqué que las citas de `index.html` que usa el plan siguen coincidiendo con HEAD: botón
"Contraseña" `:542`, modal `:1067`, `boot()` `:1051`, formulario `:444-455`, `<script>` `:976`,
comentario con el motor de presentaciones `:2258` [V]. El Hub sirve `client/public` con
`express.static` (`client/server.js:107`), así que `/sso-ui.js` se entrega sin ruta nueva. Los tests
nuevos entran en el glob de `npm test` (`client/package.json:8`, `tests/**/*.test.js`).

**Residual honesto** (no reabre F2): el cableado se prueba por **lectura estática**. Que
`boot()` consulte `available`, dibuje el botón o llame a `history.replaceState` solo lo verifican
quickstart §3 casos 1 y 13 a mano. Es lo que da D13 sin `jsdom` y es una decisión explícita.

### F3 — Cerrado (alta)

- **Gate FR-013/FR-014 del Hub**: `client/tests/unit/whitelabel-hub-056.test.js` (T015,
  tasks.md:168-172; D14, research.md:308-329; contrato hub-sso.md:193-201). Corre en `npm test` y,
  desde T042 (tasks.md:368), en `make -C deploy check` con target propio y sin Docker.
- **Panel**: el bundle ya lo cubre `test_no_engine_name.sh:19-31` y los textos nuevos del formulario los
  verifica T024 (tasks.md:258).
- **Verifiqué** que el test no nace en rojo por contenido ya existente: `grep -i -E
  "litellm|berriai|presidio" client/server.js client/public/index.html` no devuelve nada [V]
  (`prohibited_names.txt:9-11`), así que "`index.html` y `server.js` contra la lista compartida" pasa de
  entrada, y el comentario de `index.html:2258` queda correctamente fuera.
- **Residual**: N6.

### F4 — Cerrado (media)

El Hub trata `return_origin: null` como "sin botón" (hub-sso.md:35-36, :137; tasks.md:142, :164).
La spec lo escribe en FR-001 (spec.md:258-262) y FR-015 (spec.md:317-326); el panel conserva la regla
retrocompatible (guardian-sso-api.md:30-31; tasks.md:266). Coincide con el hecho del código: sin la
variable, `/login` corta con `500 sso_redirect_uri_no_configurado` (`api.py:143-154`) y `/available` no
mira la variable (`api.py:193-200`). El rollback de nivel 1 ("vaciar la URI") ahora oculta el botón, y
está en DESPLIEGUE vía T041 (tasks.md:360) y en el quickstart §4.6 (quickstart.md:126-128). Residual: N3.

### F5 — Cerrado (media)

Almacén lleno → rechaza al que llega, no expulsa (hub-sso.md:52-55; data-model.md:37-43); límite de
ritmo global `120/min` sin llamar al backend (hub-sso.md:40-43; data-model.md:44-53). Tests T010 y T011
(tasks.md:137-138, :146), incluido "un pendiente previo sigue consumible". Verifiqué la aritmética:
con 120 pedidos por minuto y TTL de 10 min, un atacante limitado por el ritmo llega a ~1 200 pendientes
vivos como máximo, bajo el tope de 5 000; el tope de memoria queda como segunda barrera, no como la
primera. Residual: N1 (el mismo límite es un interruptor).

### F6 — Cerrado (media)

El diseño D12-C se sostiene en el código:

- El `sid` se acepta sin que el servidor lo haya emitido y sin `Secure` ni prefijo
  (`client/server.js:88-97`), que es justo la premisa del ataque de F6.
- La cookie `__Host-sso_flow` no se puede escribir desde `http://` ni con `Domain`, así que el atacante
  no puede plantarla junto con su `sid` (hub-sso.md:47-51, :71-78; test 8, hub-sso.md:170-171).
- La rotación del `sid` solo en el camino SSO y con `Secure` si hubo atadura (hub-sso.md:83-87).
- El detalle fino que el QA v1 no había visto también está resuelto: en una primera visita el
  middleware ya dejó un `Set-Cookie` (`server.js:93`) y la atadura se **agrega**, no lo pisa
  (hub-sso.md:58-63; test 3, hub-sso.md:160-163; T011, tasks.md:145).
- Está en la spec (FR-016, spec.md:327-333; Edge Case, spec.md:229-231) y en la verificación en vivo
  (quickstart.md §3b, `:90-111`; DESPLIEGUE vía T041, tasks.md:355).

Residuales: N7 (misma clase en el login con contraseña, preexistente) y N8 (detalle de pruebas).

### F7 — Cerrado (media)

La spec ya no contradice al plan: cabecera enmendada (spec.md:7-8), Clarifications con D1 a D8, F1,
F5, F6, F8 y F10 (spec.md:38-96), FR-010 reformulado como "documentar y verificar el proxy"
(spec.md:291-295), FR-012 con la excepción del tope (spec.md:298-309), FR-015 y FR-016 nuevos
(spec.md:317-333), alcance de fase 1 y estimación re-hechos (spec.md:381-416). `plan.md:6-15` apunta a
la spec enmendada. Verifiqué por `grep` que no quedan frases viejas en ningún artefacto de la spec
("no se pueden fabricar en masa", "el más viejo", servicio TLS/nginx, `trust proxy`, `jsdom` como
dependencia): solo aparecen en contexto de lo descartado. No hay marcadores `TODO`/`NEEDS CLARIFICATION`
ni restos del commit `5e6a4dc` (el worker interrumpido).

Una observación de proceso, no un hallazgo: AGENTS.md pide los skills `speckit-*` y no ediciones
manuales. Los mensajes de commit dicen "clarify, plan, tasks, analyze", pero desde los artefactos no se
puede comprobar qué skill escribió qué. Lo anoto para que el owner lo confirme.

### F8 — Cerrado (media)

El `404 sso_no_configurado` de `_cargar_config` (`api.py:171-175`, invocado en `:275` fuera de todo
`try`) y el `500 sso_redirect_uri_no_configurado` (`api.py:143-154`, invocado en `:293` dentro del
`try` que re-lanza `HTTPException` en `:295-296`) están ahora en la tabla de auditoría con categoría
"flujo" (guardian-sso-api.md:61-64, :72, :74), en T005 (tasks.md:93) y en T007, que además resuelve
`_redirect_uri` **antes** del `try` (tasks.md:106-108). La spec lo recoge (spec.md:77-80, FR-012).

### F9 — Cerrado (media)

`deploy/Makefile:42` sigue siendo una lista explícita [V]. El plan hace dueño de `deploy/Makefile` al
tramo D (T031, tasks.md:298; propiedad en tasks.md:48) con `check-release-publish`, y al tramo E
(T042, tasks.md:368) con `check-hub-whitelabel`, **en ese orden y nunca en paralelo**
(tasks.md:408-410). Ninguno usa Docker real (el de `LATEST` usa un `docker` de prueba;
instalador-y-release.md:87-98). Residual no bloqueante: N2 sobre cómo se promueve a `latest`.

### F10 — Cerrado (media)

El texto de `sso_identidad_no_verificada` ahora es neutro y no culpa a la identidad (hub-sso.md:106;
spec.md:92-96, :248-252). Es coherente con el código: el backend colapsa canje fallido, secreto vencido y
directorio caído en el mismo `401` (`api.py:297-307`) y distingue la causa solo en el log
(`entra.py:109-180`, `_causa`, `:288-290`). La guía (T039, tasks.md:345) y el quickstart §4.3
(quickstart.md:117-121) dicen qué esperar y dónde ver la causa. Elegir "solo Hub" respeta la base mínima.

---

## Hallazgos nuevos

| # | Sev. | Resumen |
|---|---|---|
| N1 | **Media** | Los dos topes globales (30/min de canje en el backend, 120/min de `/sso/login` en el Hub) son un interruptor de SSO para cualquiera sin autenticar a **ritmo sostenido** de 0,5 a 2 pedidos por segundo. El texto del plan lo llama "ráfaga" |
| N2 | **Media** | "Promover a `latest`" se define como **reconstruir** las imágenes, no como re-etiquetar la candidata probada; el cliente recibe bits distintos a los del piloto |
| N3 | Baja | El helper de `return_origin` revienta con un puerto inválido o IPv6, y devuelve el origen aun con `enabled:false` |
| N4 | Baja | El tope de canje cuenta **después** del fallo: bajo concurrencia pasan más de `tope` llamadas |
| N5 | Baja | `destinoBoton` valida "origen http(s)" sin pedir un origen bien formado |
| N6 | Baja | Huecos acotados del gate de marca blanca del Hub |
| N7 | Baja (preexistente) | Fijación de sesión en el login con contraseña y `parseCookies` que lanza ante una cookie malformada |
| N8 | Baja | Las pruebas de cookies de T012/T019/T020 no exigen que convivan el `sid` rotado y el borrado de la atadura |

### N1 — Media — Los topes globales cortan SSO para todos con un ritmo sostenido muy bajo

**Qué dice el plan**: el efecto está "aceptado": *"durante una ráfaga, un canje legítimo de la misma
ventana también recibe el 401"* (guardian-sso-api.md:97-99; research.md:169-172; spec.md:221-224 y
:225-228, "mientras dura la ráfaga"). El límite del Hub es `SSO_LOGIN_POR_MIN = 120` (hub-sso.md:40-43).

**Qué hay** [V el diseño; I el efecto]:

- La cookie de estado del backend se reutiliza 10 minutos (`api.py:59`, `:95`, `:335`). Con **una**
  cookie, un cliente sin sesión manda 30 `GET /callback?state=<state>&code=x` al inicio de cada ventana de
  60 s (`api.py:260-273`). Es 0,5 pedidos por segundo. Con el contador de canje agotado (T008,
  tasks.md:111-115), **todos** los canjes legítimos del resto de la ventana reciben el 401 sin llegar al
  directorio. No es una ráfaga: es un goteo permanente.
- En el Hub, 120 pedidos por minuto (2 por segundo) a `/sso/login` sin cookie dejan el ingreso con
  Microsoft en `sso_reintentar` para todos (hub-sso.md:40-43; data-model.md:44-53).
- **Sin ataque**, el límite de 120/min tampoco está derivado de ningún dato: el Hub guarda las sesiones
  en memoria, así que después de cada reinicio o actualización **todas** las personas tienen que
  volver a entrar (DESPLIEGUE-Y-REVERSION.md, "Sesiones del Hub en memoria"); con cientos de usuarios
  que lo hacen en pocos minutos (plan.md, Scale/Scope), el límite puede dispararse con tráfico legítimo.

**Por qué importa**: la disponibilidad del botón de SSO depende de un actor sin credenciales con costo
casi nulo. FR-006 se cumple (la contraseña sigue), y el owner aceptó el trueque. Lo que **no** está
bien es cómo se lo describe: "ráfaga" y "mientras dura" hacen creer que el corte es transitorio, y la
guía (T039, tasks.md:346) solo promete que "durante una ráfaga de ingresos falsos el botón puede fallar".

**Requisito que toca**: FR-006 (se cumple), FR-012 y FR-016 (texto de excepciones), Constitución
Security 3 (fail-closed: es el lado correcto del trueque). **No reabre D6 ni D11.**

**Corrección sugerida** (por `speckit-clarify`, el owner decide el alcance):

- Reescribir el Edge Case y la guía para decir la verdad: "un tercero con acceso de red al backend o al
  Hub puede mantener fuera de servicio el botón de Microsoft con pocos pedidos por segundo; el login con
  contraseña no se afecta".
- Opcional, decisión del owner: dar a cada contador un cupo reservado o una ventana deslizante, o
  derivar `120/min` de un dato (usuarios por minuto tras un reinicio) y dejarlo anotado.
- Agregar al HANDOFF (T047) y al quickstart §4 un caso que muestre cómo se ve en el panel (eventos de
  `auth_sso_denied`) y en el log (el warning con el conteo omitido) que el corte es una ráfaga y no
  una falla del directorio.

### N2 — Media — "Promover `056-rc1` a `latest`" reconstruye las imágenes: lo piloteado no es lo que se entrega

**Qué dice el plan**: Etapa 5 de DESPLIEGUE-Y-REVERSION.md (`:108-111`): *"Promover `056-rc1` a
`latest` (republicar con fecha)"*; instalador-y-release.md:81 (*"republicar con fecha y `LATEST=1`"*);
T048 (tasks.md:390): `VERSION=<fecha> deploy/release/publish-elea.sh`.

**Qué hay** [V]: `publish-elea.sh:34` hace `docker build` **cada vez** y `:41-42` empuja lo recién
construido. Republicar con `LATEST=1` genera una imagen nueva, no la candidata que se probó en la
Etapa 1 y se pilotó en la Etapa 4. Para el Hub ni siquiera es reproducible: `client/Dockerfile:10-11`
copia solo `package.json` (sin `package-lock.json`) y corre `npm install --production`, con
dependencias `^` (`client/package.json:11-13`); las capas `apk`/`pip` de `:4-6` tampoco están fijadas.
Entre la Etapa 1 y la Etapa 5 pueden cambiar versiones de dependencias o del sistema base.

**Por qué importa**: el principio 1 y el 4 del propio DESPLIEGUE ("nada llega al server hasta pasar la
prueba local" y "verificación idéntica al uso real") se rompen justo en el último paso: lo que se
promueve nunca se probó. Es el riesgo central del despliegue (plan.md, tabla de riesgos, "Imágenes
candidatas").

**Requisito que toca**: DESPLIEGUE-Y-REVERSION.md, Principios 1 y 4; spec.md US3 AS3
(actualización conserva comportamiento).

**Corrección sugerida** (por `speckit-clarify`/`speckit-tasks`, dentro de T030/T031 y T048): un modo de
**promoción por re-etiquetado**, por ejemplo `PROMOTE_FROM=056-rc1`, que hace `pull` de la
candidata, la etiqueta `:latest` (y la fecha) y empuja **el mismo digest**, sin `build`. El `stub` de
T030 prueba que no hay `build` en ese modo. T048 y DESPLIEGUE Etapa 5 pasan a usarlo. Sumar a la guía el
digest `PINNED …` que ya imprime el script (`publish-elea.sh:43`).

### N3 — Baja — El helper de `return_origin` y la exposición con `enabled:false`

**Qué hay** [V con `python3`]:

- `urlsplit(...).port` **lanza `ValueError`** con un puerto no numérico (`https://host:abc/x`) o fuera
  de rango (`:99999`), y `urlsplit` lanza con un IPv6 mal cerrado (`https://[::1/x`). T006 lee la
  variable en `sso_available` (tasks.md:101) y T004 no tiene esos casos (tasks.md:84-91): un error de
  tipeo en `SENTINEL_SSO_REDIRECT_URI` convertiría `/available` en un `500`, y hoy esa ruta **no mira** la
  variable (`api.py:179-200`), así que es un cambio de comportamiento de base. El Hub y el panel colapsan
  a "sin botón" ante el 500 (hub-sso.md:28; `frontend/src/services/api.ts:687-699`), pero queda un 500
  sin causa visible en una ruta pública.
- `hostname` devuelve `::1` **sin corchetes** para `http://[::1]:8095/...`: armar `scheme://hostname:port`
  produce `http://::1:8095`, que no es un origen válido.
- El contrato pide devolver `return_origin` **también con `enabled:false`** (guardian-sso-api.md:22;
  tasks.md:101). La justificación de seguridad de guardian-sso-api.md:24-26 ("el mismo valor viaja en el
  `redirect_uri` de la URL de Microsoft que ve cualquiera que pulse el botón") no vale con el proveedor
  apagado: nadie puede pulsar el botón. Con licencia con `sso` y proveedor apagado, el backend publicado en
  `:8091` (`elea-installer/docker-compose.yml:91-92`, citado en research.md:143-144) revelaría el nombre
  interno del Hub sin que nada lo necesite: el panel dibuja el botón solo con `enabled:true`
  (research.md H13) y el Hub ya colapsa a `null` (hub-sso.md:27).

**Requisito que toca**: constitución Security 3 y "base mínima y retrocompatible" (AGENTS.md y brief del
owner).

**Corrección sugerida**: en T004/T006, envolver el cálculo en `try/except ValueError → None`, volver a
poner corchetes si el host contiene `:`, y devolver `None` cuando `enabled` es `false`. Tests: puerto
inválido, fuera de rango, IPv6 con y sin puerto, y `enabled:false` → `return_origin: null`. (Si el
owner prefiere dejarlo con `enabled:false`, ajustar la frase de seguridad del contrato.)

### N4 — Baja — El tope de canje cuenta después del fallo: bajo concurrencia se pasa de `tope`

**Qué dice el plan**: el contador *"suma cada canje fallido"*; el chequeo mira el contador **antes** de
llamar al proveedor (guardian-sso-api.md:89-92; tasks.md:111-115). T005 pide *"exactamente `tope`
llamadas al proveedor"* con `tope + 5` repeticiones.

**Qué hay** [V el diseño; I el efecto]: `exchange_code` corre en el threadpool y tarda lo que tarde el
directorio (`api.py:288-294`; `httpx.Client(timeout=10.0)`, `entra.py:189`). Si N pedidos llegan juntos,
todos leen el contador en `tope-1` (o menos) y todos salen al directorio: el contador se incrementa
cuando vuelven con error. La cota queda en el tamaño del threadpool, no en `tope`. Además, si el
contador lo toca código en el threadpool (por ejemplo desde `_auditar_denegado`, `api.py:339-347`) y
también el event loop, sin lock, el conteo puede perder incrementos. T005 prueba solo repeticiones
**secuenciales**, así que no detecta ninguna de las dos cosas.

**Corrección sugerida**: **reservar** el cupo antes de llamar (incrementar y comparar de forma
atómica), devolverlo si el canje termina bien, y tocar el contador siempre desde el mismo hilo o con
`threading.Lock`. Test concurrente (`asyncio.gather` de `tope + 10` canjes con un doble lento):
exactamente `tope` llamadas.

### N5 — Baja — `destinoBoton` debería exigir un origen bien formado

**Qué dice el plan**: `destinoBoton` devuelve `null` si `return_origin` *"no es un origen `http(s)`"*
(hub-sso.md:137); el único caso negativo de los tests es `javascript:` (hub-sso.md:183-185; tasks.md:164).

**Qué hay** [V con `python3`]: el backend no valida los caracteres del host: `urlsplit('https://a"onmouseover=x/cb').hostname`
devuelve `a"onmouseover=x`, y `https://a b/x` devuelve `a b`. El valor sale de una variable que fija el
administrador de la instalación, así que la superficie es baja, pero T021 "dibuja" el botón en
`index.html` (tasks.md:206); si lo hace con una plantilla de texto en `innerHTML`, una comilla en el
origen rompe el atributo. Es el mismo tipo de XSS que F2 quería prevenir en `?sso_error=`.

**Corrección sugerida**: `destinoBoton` acepta solo si `new URL(x).origin === x` y el esquema es
`http:`/`https:`; casos de test con comillas, espacios, `<`, `\\` y userinfo; y el botón se arma con
`createElement` y `textContent`, nunca con `innerHTML`. Sumar ese caso a la lectura estática del test
20 (hub-sso.md:189-191).

### N6 — Baja — Huecos acotados del gate de marca blanca del Hub

El gate de F3 (T015, tasks.md:168-172) es suficiente para cerrar el hallazgo, con estos bordes
honestos:

- `client/public/index.html` y `client/server.js` se comparan **solo** con los tres nombres de
  `prohibited_names.txt` (`:9-11`), no con los motores de documentos y presentaciones (research.md:314-319).
  Si T021 escribe la etiqueta o un texto del botón directamente en `index.html` (tasks.md:206 dice que
  "dibuja" ahí), ese texto no pasa por la lista de motores internos.
- `server.js` ya contiene `Elea`/`ELEA_*` (`client/server.js:19`), así que los tres endpoints nuevos no se
  verifican contra FR-014.

**Corrección sugerida**: que T021 pida que **todo texto nuevo visible** (incluida la etiqueta del botón)
viva en `client/public/sso-ui.js`, que sí se cubre entero (hub-sso.md:195-198), y que T015 lo
verifique con un test de lectura estática de `index.html` (cualquier cadena literal nueva alrededor del
bloque de SSO). Con eso FR-013 queda cubierto sin tocar la lista compartida (decisión del owner).

### N7 — Baja (preexistente) — Fijación de sesión en el login con contraseña; cookie malformada rompe el Hub

La enmienda cierra con D12 la inyección de la cookie `elea_rag_sid` **para el camino SSO**, y deja
`POST /api/auth/login` idéntico por FR-005 (hub-sso.md:14). Pero:

- `client/server.js:90-95` acepta cualquier valor de `sid` que traiga el navegador, y
  `server.js:258-273` guarda la sesión bajo ese mismo `sid`, sin rotarlo. Quien pueda plantar
  `elea_rag_sid=A` (la misma capacidad que F6 asume) conoce `A`, y cuando la víctima entra **con
  contraseña** también conoce su sesión [V el código; I la explotación].
- `parseCookies` llama a `decodeURIComponent` sin `try` (`server.js:83`) dentro del middleware global
  (`:88-97`): una cookie con `%` mal formado hace lanzar `URIError` y el Hub responde 500 en **todas**
  las rutas para ese navegador, incluido `/sso/callback` [V la lectura; I el efecto].

Son preexistentes y la 056 no los introduce. Se anotan porque el HANDOFF y la guía dicen que la cookie
de sesión queda protegida con `Secure` solo en el camino SSO (tasks.md:346), y quien lea eso puede asumir
que el Hub entero ya está cubierto. **Sugerencia**: dejarlo como riesgo aceptado explícito en
tasks.md §Riesgos aceptados y en el HANDOFF, y abrir un issue aparte para rotar el `sid` en el login con
contraseña y blindar `parseCookies` (cambio chico, pero toca FR-005, por eso lo decide el owner).

### N8 — Baja — Las pruebas de cookies no exigen que convivan el `sid` rotado y el borrado de la atadura

T019 manda **borrar** `__Host-sso_flow` (tasks.md:190) y T020 manda **reemplazar** el `Set-Cookie` del
middleware con el `sid` rotado (tasks.md:198). Con `res.setHeader('Set-Cookie', …)` una cosa pisa la otra.
T012 solo exige "`Set-Cookie` nuevo" (tasks.md:150). Si se pisa el borrado, la cookie de atadura ya usada
queda en el navegador (inofensiva, porque el pendiente se consumió, pero deja basura y rompe el contrato de
hub-sso.md:71-72). **Sugerencia**: en T012/T013 verificar con `getSetCookie()` que la respuesta del
callback trae **exactamente** el `sid` rotado y el borrado de `__Host-sso_flow`, ambos, y que el `sid`
viejo no aparece.

---

## Estado de los hallazgos bajos B1–B9 (qa-plan.md:309-321)

Todos están absorbidos en una tarea o declarados como riesgo aceptado (research.md:396-404); las citas
de línea que revisé por muestreo coinciden con HEAD.

| # | Estado | Dónde |
|---|---|---|
| B1 | Documentado como límite (no se cambia `entra.py`) | spec.md:235-238; tasks.md:346, :387, :465-466 |
| B2 | Checklist de activación | spec.md:239-241; tasks.md:351, :359 |
| B3 | `URLSearchParams` + test con `&`, `=`, `#` | hub-sso.md:90-92, :175; tasks.md:151, :193 |
| B4 | Riesgo aceptado | tasks.md:462-464 |
| B5 | `scheme`/`hostname`/`port`, sin puerto por defecto; **ver N3 por los bordes** | guardian-sso-api.md:22, :45-48; tasks.md:85-87, :101 |
| B6 | `Cache-Control: no-store` + test | hub-sso.md:32-33; tasks.md:142, :177 |
| B7 | Se cierra en el piloto | tasks.md:358, :390 |
| B8 | Sección del Hub "solo si hay Hub"; tope × workers en el HANDOFF | tasks.md:341, :381-386 |
| B9 | `.gitignore` en el tramo 0 | tasks.md:44, :64-67, :467-468 |

## Matriz de cobertura: filas que cambian respecto de qa-plan.md

Leyenda: ✅ tarea y test automático · 🟡 tarea, test parcial o solo manual · ❌ sin test.

| Requisito | Antes | Ahora | Tareas / tests |
|---|---|---|---|
| FR-001 botón solo con SSO habilitado y retorno | ❌ | ✅ (cableado por lectura estática) | T010, T011, T014, T021 |
| FR-006 degrada solo SSO + mensaje | ❌ | ✅ | T014, T022 |
| FR-008 sin cambio obligatorio ni "cambiar contraseña" | ❌ | ✅ | T012, T014 |
| FR-010 HTTPS | 🟡 | 🟡 (reformulado: documentar y verificar) | T036, T040, T041, quickstart §3b |
| FR-012 auditoría de todo ingreso | 🟡 | ✅ | T005, T007, T008 (ver N4) |
| FR-013 sin nombres internos | ❌ | ✅ con los huecos de N6 | T015, T024, T042 |
| FR-014 genérico, sin strings de Elea | ❌ | 🟡 (solo archivos nuevos del Hub, ver N6) | T015, T024 |
| FR-015 `return_origin` | — (huérfano) | ✅ | T004, T006, T014, T025 |
| FR-016 atadura al navegador | — (huérfano) | ✅ | T010, T011, T013, T018–T020 |
| US1 AS5, US2 AS2, US2 AS3 | ❌ | ✅ | T012, T014, T022 |
| Caso borde: secreto vencido | 🟡 | 🟡 (mensaje en test; la causa, manual) | T014, T039, quickstart §4.3 |
| Caso borde: ráfagas | — | ✅ (ver N1 por el texto) | T005, T010, T011 |

Sin cambio: FR-003 sigue en 🟡 (se cumple por construcción; T011 podría sumar una aserción de que el
Hub solo llama a `ELEA_BACKEND_URL`), FR-011 y las filas de SC.

## Verificado sin hallazgos (no se reabre)

- **Citas de línea del plan contra HEAD** (muestreo, todas coinciden): `api.py:58-63`, `:102-124`,
  `:127-154`, `:157-176`, `:179-200`, `:203-247`, `:260-307`, `:309-336`, `:339-347`, `:374-380`;
  `entra.py:52`, `:109`, `:189`, `:201-206`, `:260-290`; `client/server.js:19`, `:75-97`, `:107`, `:119-127`,
  `:258-273`, `:284-309`, `:314-316`, `:318-333`; `index.html:444-455`, `:542`, `:976`, `:1051-1056`,
  `:1067`, `:2258`; `deploy/Makefile:42`, `:52-128`; `publish-elea.sh:34`, `:41-43`.
- **Líneas citadas por la tabla de resolución** (`research.md:384-404`): revisé las de `spec.md`,
  `tasks.md`, `hub-sso.md`, `guardian-sso-api.md`, `data-model.md`, `quickstart.md` e
  `instalador-y-release.md`. Coinciden, salvo la de research.md:149-151 (real `:148-151`).
- **Numeración y conteos de tramos** (tasks.md:42-49): 3 + 6 + 14 + 6 + 9 + 10 = 48 tareas
  (T001–T048), sin huecos ni duplicados.
- **Propiedad de archivos**: ningún archivo lo tocan dos tramos en paralelo; `deploy/Makefile` lo
  tocan D y luego E (tasks.md:48-49, :408-410).
- **Constitución**: auditoría metadata-only (`auth_events.py:46-53`), tenant desde
  `expected_tenant_id()` (`api.py:206`, `:259`), onboarding como datos (licencia + panel + una variable),
  sin migración, base mínima y retrocompatible (campo nuevo opcional, mismos status y `detail`),
  white-label (nombres de la lista compartida ausentes de `client/server.js` y `index.html`).
- **DoD**: T043 cubre `check-docs` y `docs-refs` (tasks.md:369); la variable
  `SENTINEL_SSO_REDIRECT_URI` ya está en el `.env.example` raíz (`.env.example:232`).

## Pendiente de tramo E, no es hallazgo

`SOLICITUD-A-ELEA.md` (punto 3: pide "el certificado y su clave privada… el IT los copia al servidor") y
DESPLIEGUE-Y-REVERSION.md ("Qué falta para que volver atrás sea real", Etapa 3 sin la verificación de
`__Host-sso_flow`) **todavía describen el diseño anterior a D7-B**. Está tasked: T041 (tasks.md:354-360)
los corrige en el tramo E. Lo anoto para que el coordinador no los dé por "desactualizados sin dueño".

## Evidencia de esta revisión

| Comando | Resultado |
|---|---|
| `cd client && npm test` (línea base del Hub en HEAD, sin código nuevo) | 43 tests, 43 pass, 0 fail, 0 cancelled; `git status` limpio después |
| `python3 -c "urlsplit(...)"` con `https://host:abc/x`, `:99999`, `https://[::1/x`, `http://[::1]:8095/x` y host con comilla/espacio | `ValueError` en los tres primeros; `hostname='::1'` sin corchetes; `hostname` con `"` y espacio aceptado (N3, N5) |
| `grep -i -E "litellm\|berriai\|presidio" client/server.js client/public/index.html` | sin salida (el test de marca blanca de T015 no nace en rojo por contenido existente) |
| `grep` de frases obsoletas, `TODO`/`NEEDS CLARIFICATION` y restos del WIP en `specs/056-*/` | sin restos fuera de contexto "descartado" |
| Lectura completa de `api.py` (50-404), `entra.py`, `auth_events.py`, `client/server.js` (15-340), `client/Dockerfile`, `publish-elea.sh`, `deploy/Makefile` (30-135) y de todos los artefactos de `specs/056-*/` | citas verificadas contra HEAD |
| `docker compose run … pytest`, `cd frontend && npm test`, `make -C deploy check` | **No se corrieron.** El cambio de esta revisión es un archivo Markdown sin efecto sobre esas suites, y la regla del owner prohíbe Docker sin aviso previo. La línea base de esas tres es T002 de tasks.md |

## Dictamen para el coordinador

- **F1, F2 y F3 (bloqueantes): cerrados.** F4 a F10: cerrados.
- **Hallazgos altos nuevos: ninguno.** Medios: N1 (describir bien el efecto de los topes), N2 (promoción
  por re-etiquetado). Bajos: N3 a N8.
- **Listo para `/speckit-implement`.** Recomiendo que el redactor (por los skills `speckit-*`) absorba
  N1 y N2 en spec.md/tasks.md antes de despachar los tramos A y D, y que el resto entre como casos de test
  dentro de las tareas existentes (T004/T006, T005/T008, T012, T014, T015, T021).
