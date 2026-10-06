# QA crítico del plan — Spec 056 (Ingreso con Microsoft Entra ID en el Hub)

**Rol**: qa-critico (segundo nivel, lectura lógica; seguridad, datos sensibles, permisos).
**Fecha**: 2026-10-05 · **Rama**: `cluna-8/056-sso-entra-id-hub-plan` (base `1fac4f8`).
**Alcance**: `plan.md`, `research.md`, `data-model.md`, `contracts/*`, `tasks.md`, `quickstart.md` y
`DESPLIEGUE-Y-REVERSION.md` contra `spec.md`, `.specify/memory/constitution.md` (v2.2.0) y el
código real (`backend/src/sso/*`, `client/server.js`, `client/public/index.html`,
`deploy/release/checks/*`, `deploy/Makefile`).
**No se editó ningún artefacto del plan ni código de producto.** Los desvíos se reportan acá; las
correcciones van por los skills `.agents/skills/speckit-*` (AGENTS.md).

**Convención de evidencia**: **[V]** verificado leyendo el código citado (o ejecutando algo, si se
dice). **[I]** inferido de la lectura: hay que confirmarlo con un test antes de darlo por cierto.

## Veredicto

**El plan NO está listo para `/speckit-implement`.** Hay **3 hallazgos bloqueantes** (1 de seguridad
y 2 de cobertura de FR por test) y 7 de severidad media. El diseño central del flujo (estado atado
al `sid`, un solo uso, rotación de `sid`, token fuera de la URL, lista cerrada de errores,
fail-closed en `available`) es **sólido** y está confirmado contra el código (ver §Verificado
sin hallazgos). Los problemas están en los bordes: el tope de auditoría, el botón cuando falta
la URI, los tests de la mitad de pantalla del Hub y la spec sin enmendar.

| # | Sev. | Tipo | Resumen |
|---|---|---|---|
| F1 | **Alta (bloqueante)** | Seguridad / auditoría | El tope de D6 parte de una premisa falsa: los rechazos de identidad **sí** se pueden fabricar en masa y quedan sin tope |
| F2 | **Alta (bloqueante)** | FR sin test (TDD) | Toda la pantalla del Hub (`index.html`, T018) queda sin test: mitad UI de FR-001, FR-006, FR-008 y US1 AS5, US2 AS2/AS3 |
| F3 | **Alta (bloqueante)** | FR sin test | FR-013 y FR-014 no tienen tarea de verificación automática; los gates de marca blanca existentes no miran el Hub |
| F4 | Media | FR-001 / FR-009b | `return_origin: null` hace aparecer un botón que siempre falla (rollback nivel 1 incluido) |
| F5 | Media | Seguridad (disponibilidad) | El tope de 5 000 pendientes con "expulsar el más viejo" lo controla un atacante sin sesión |
| F6 | Media | Seguridad | La cookie `elea_rag_sid` sin `Secure` ni prefijo permite inyección de cookie y reabre el login CSRF que D1 quiere cerrar |
| F7 | Media | Spec sin enmendar | FR-010 (HTTPS), FR-012 (todo rechazo) y la base nueva (`return_origin`, tope) contradicen o exceden la spec, que "no se toca" |
| F8 | Media | FR-012 | Quedan rechazos sin auditar fuera de la tabla de D6 (404/500 del callback) |
| F9 | Media | Gate | `test_publish_elea_latest.sh` (T027) no entra a `make -C deploy check`; el Makefile no tiene dueño |
| F10 | Media | Mensajes / FR-006 | Secreto vencido o IdP caído en el callback se muestra como "Microsoft no confirmó tu identidad" |
| B1-B9 | Baja | Varios | Ver §Hallazgos bajos |

---

## F1 — Alta (bloqueante) — El tope de D6 no cierra la inundación: los rechazos de identidad se fabrican en masa

**Qué dice el plan**: research.md:147-148: *"Los rechazos de identidad (`api.py:302`, `:313`, `:379`)
no se tocan: exigen un canje real con el IdP y no se pueden fabricar en masa."* Se repite en
guardian-sso-api.md:188 y se traduce en T007 (tasks.md:81: el tope aplica **solo** a los rechazos
de flujo).

**Qué hay en el código** [V]:

1. `GET /auth/sso/login` es público (solo el gate de licencia, `api/__init__.py:53`) y entrega una
   cookie de estado válida a cualquiera: `api.py:203-247`. No exige sesión ni tiene límite.
2. Con esa cookie y su `state`, un cliente llama `GET /auth/sso/callback?state=<state>&code=cualquier-cosa`.
   Pasa `_leer_estado` (`api.py:260`) y la comparación de `state` (`api.py:264`), y el `code`
   no está vacío (`api.py:269`).
3. `exchange_code` hace un `POST` real al `token_endpoint` de Microsoft con ese `code`
   (`entra.py:260-293`, el `POST` en `:280`). Microsoft lo rechaza → `SsoTokenExchangeError`.
4. Cae en `except Exception` (`api.py:297`) y llama a `_auditar_denegado` (`api.py:302`): **una fila
   `auth_sso_denied` por intento, sin tope** (el tope de T007 no la toca) y **una llamada saliente a
   Microsoft por intento**.

El canje "real" no exige un usuario real: basta un `code` inventado. Es el vector exacto que D6 dice
cerrar.

**Por qué importa**:

- **Auditoría** (Constitución II y Security 6; FR-012): el canal metadata-only se llena de ruido sin
  autenticarse, igual que el caso que el owner decidió acotar (research.md:141-146).
- **Disponibilidad de SSO** (FR-006): cada intento golpea el `token_endpoint` de Microsoft con el
  `client_id` y el secreto de la instalación. Una ráfaga puede disparar el límite de peticiones del
  directorio y tumbar el botón para todos (el login con contraseña no se afecta).
- **Alcance nuevo**: el Hub publica `:8095` en la LAN y su `/sso/login` + `/sso/callback` son
  públicos. Un atacante con su propio `sid` hace el mismo recorrido por el Hub (el Hub reenvía la
  cookie cuando el `state` coincide, hub-sso.md:56-57). La 056 amplía la superficie sin cerrar este
  camino.

**Requisito que viola**: la propia decisión D6 (research.md:139-153) y FR-012/FR-006; Constitución
Security 3 (fail-closed) y 6.

**Corrección sugerida** (por `/speckit-clarify` + `/speckit-plan`, no a mano):

- Aplicar el tope también a `api.py:302` (fallo del canje), o poner un tope global sobre las
  llamadas salientes al `token_endpoint` desde `/callback`. Los rechazos de `:313` y `:379` sí
  requieren una identidad real de Entra y pueden seguir sin tope.
- Agregar a T005/T007 el caso: *cookie válida + `code` basura, `tope + 5` veces → `tope` eventos y
  `tope` llamadas al proveedor (doble del proveedor cuenta las llamadas), veredicto 401 intacto*.
- Corregir la frase de research.md:147-148, que hoy afirma algo falso.

---

## F2 — Alta (bloqueante) — La pantalla del Hub no tiene ningún test

**Qué hay**: T018 (tasks.md:149-155) cambia `client/public/index.html` en cuatro cosas: dibujar o no
el botón, mostrar `?sso_error=`, ocultar "Contraseña" y no abrir el modal. Ninguna de las tareas de
test del tramo B las cubre: T009-T012 y T019 son tests de servidor (`supertest`, `node:test`;
`client/package.json:7-9`). El Hub no tiene `jsdom` ni ningún test que cargue `index.html` [V]:
`grep -rn "index.html\|jsdom\|readFileSync" client/tests` no devuelve ninguno que lo haga.

**FR y escenarios que quedan sin test automático** (solo cobertura manual del quickstart §3-§4):

| Requisito | Parte que depende de `index.html` |
|---|---|
| FR-001, US2 AS3 | "el botón no aparece" sin SSO o sin licencia |
| FR-006, US2 AS2 | texto entendible que recuerda el acceso con contraseña |
| FR-008, US1 AS5 | no ofrecer "Contraseña" ni abrir el modal a quien entró por SSO |
| hub-sso.md:83-84 | código `sso_error` desconocido → genérico; limpiar la barra |

**Riesgo adicional de seguridad** [I]: `?sso_error=` es entrada controlada por cualquiera (un
enlace). Si la implementación lo pinta con `innerHTML` o lo usa para elegir texto sin lista cerrada,
hay XSS reflejado en el origen que guarda la sesión. El contrato lo previene ("lista cerrada"), pero
sin test nadie lo verifica.

**Requisito que viola**: AGENTS.md ("TDD donde hay código nuevo"), Constitución Development Workflow
3 ("todo cambio con lógica no trivial lleva tests automatizados"), y la consigna de esta revisión
(cada FR y escenario con al menos una tarea **y un test**).

**Corrección sugerida**: o bien extraer la lógica de la pantalla de ingreso a un módulo de cliente
testeable (por ejemplo `client/public/sso-ui.js`, puro, sin DOM) y testearlo con `node --test`; o
agregar `jsdom` como devDependency (el plan declara "ninguna dependencia nueva", plan.md:42, así que
sería una decisión a registrar). Tests mínimos: botón según `enabled`/`return_origin`; destino del
botón; `sso_error` conocido, desconocido y con HTML; `auth_method:'sso'` oculta "Contraseña".

---

## F3 — Alta (bloqueante) — FR-013 y FR-014 sin verificación automática; los gates no miran el Hub

**FR-013** (spec.md:204-206: nada visible al cliente nombra componentes internos). Los gates
existentes **no escanean el Hub** [V]:

- `deploy/release/checks/test_no_engine_name.sh:19-25` revisa el bundle de la imagen del **panel**
  (`/srv`) y los packs de `deploy/branding`.
- `test_docs_neutral_naming.sh` y `test_docs_whitelabel.sh` revisan el sitio de docs
  (`deploy/Makefile:70-71`).
- `client/public/index.html` y `client/server.js` no entran en ninguno.
- `deploy/release/checks/prohibited_names.txt:9-11` tiene solo `litellm`, `berriai`, `presidio`. No
  incluye los motores de documentos y presentaciones que FR-013 nombra. `index.html:2258` ya
  menciona "Presenton" (en un comentario, no visible), así que una lista ingenua tampoco sirve.

Las únicas verificaciones previstas son revisiones manuales (T026 y T038, tasks.md:216-219 y 304).
**FR-014** (sin strings de Elea/Eleia en lógica; spec.md:207-209) se declara "verificada en el
analyze" (spec.md:310) y ninguna tarea la comprueba.

**Corrección sugerida**: una tarea de test en el tramo B y otra en el C: un test que lea las
cadenas visibles nuevas (tabla de errores de `client/sso.js`, textos de `index.html` agregados por
T018, textos del formulario del panel) y falle si contienen un nombre de `prohibited_names.txt`, los
motores de documentos/presentaciones o `Elea`/`Eleia` fijos. Sumar a la lista compartida los nombres
de FR-013 sería una decisión del owner (afecta otros gates).

---

## F4 — Media — `return_origin: null` muestra un botón que siempre falla

**Qué dice el plan**: el Hub dibuja el botón si `enabled` y `return_origin` es `null` **o** igual a
su origen (hub-sso.md:98-99, tasks.md:150).

**Qué hay en el código** [V]: sin `SENTINEL_SSO_REDIRECT_URI`, `/auth/sso/login` responde `500
sso_redirect_uri_no_configurado` (`api.py:143-154`) y `/available` no mira esa variable
(`api.py:193-200`): sigue dando `enabled:true` si hay proveedor activo. Entonces `return_origin:null`
no significa "instalación vieja, comportamiento de hoy": significa "el flujo no puede arrancar".

**Efecto**:

- Viola FR-001 (botón solo con SSO habilitado *y configurado*, spec.md:167-169) y FR-009b ("si está
  vacía, la instalación arranca igual y sin SSO", spec.md:196-197).
- **El rollback de nivel 1** (DESPLIEGUE-Y-REVERSION.md:121, "vaciar `SENTINEL_SSO_REDIRECT_URI`") deja
  el botón visible en el Hub, con el proveedor aún activo en la base. Se degrada con mensaje
  (FR-006 se cumple), pero la promesa "sin SSO, sin errores" no.
- T010 y T019 no tienen el caso `enabled:true` + `return_origin:null`.

**Corrección sugerida**: en el Hub, `return_origin == null` ⇒ sin botón (el Hub no tiene instalaciones
viejas que preservar). El panel puede mantener la regla retrocompatible. Agregar el caso a T010.

---

## F5 — Media — El tope de pendientes lo controla un atacante sin sesión

**Qué dice el plan**: tope de 5 000 pendientes; al superarlo se barren vencidos y, si sigue lleno,
"el más viejo" (data-model.md:258-260; research.md:238-240; T009).

**Problema** [V el diseño; I el efecto]: cada `GET /sso/login` sin cookie crea un `sid` nuevo
(`server.js:88-97`) y un pendiente nuevo. Un cliente sin sesión que pida 5 000 veces en 10 minutos
(~8/s) hace que los pendientes legítimos sean "el más viejo" y se expulsen: **todos los ingresos en
curso terminan en `sso_reintentar`**. Cuesta además una consulta a la base y a un secreto cifrado
por pedido (`api.py:207`, `:176`). Solo se cae el camino SSO (FR-006 se cumple), pero es un corte
barato y repetible.

**Por qué no basta el plan**: expulsar al más viejo premia al que más pide. Un límite por IP no es
viable tal como está planteado: el plan dice que el Hub no usa `trust proxy` ni `X-Forwarded-*`
(research.md:177-181), así que detrás del proxy de Elea todos los pedidos vienen de la misma IP.

**Corrección sugerida**: al llenarse, **rechazar los nuevos** (fail-closed para el que llega) en vez
de expulsar a los que están a mitad de ingreso; y poner un límite de ritmo global simple a
`/sso/login` en el Hub. Test en T009: lleno el almacén, un pendiente en curso sigue consumible.

---

## F6 — Media — Cookie `elea_rag_sid` sin `Secure` ni prefijo: inyección de cookie y login CSRF

**Qué dice el plan**: la cookie conserva sus atributos (`HttpOnly; Path=/; SameSite=Lax`), sin
`Secure`, porque la misma instalación sigue sirviendo `http://…:8095` (research.md:182-183; límite
documentado en T035, tasks.md:283). La rotación de `sid` evita la **fijación** de sesión.

**Qué no cubre** [I, a confirmar con test]: la atadura al `sid` (D1) defiende contra el login CSRF
solo si el atacante no puede escribir la cookie `elea_rag_sid` en el navegador de la víctima. Con una
cookie sin `Secure` y sin `__Host-`, quien tenga posición de red (LAN, `http://<nombre>` antes de la
redirección a HTTPS) o control de un subdominio hermano puede fijar `elea_rag_sid=A` en la víctima.
Si `A` es el `sid` de un flujo que el atacante inició con su propia identidad, el callback de la
víctima encuentra **el pendiente del atacante**, el `state` coincide y el Hub abre en el navegador de
la víctima **una sesión con la identidad del atacante** (login CSRF). La rotación ocurre después y
no lo impide.

Además, tras el ingreso por SSO la cookie viaja en claro por cualquier pedido `http://<nombre>`.

**Mitigación barata, sin `trust proxy`**: en `/sso/login` el Hub lee el `redirect_uri` de la
`Location` del backend. Si empieza con `https://`, el callback **solo** puede llegar por HTTPS (Entra
no redirige a otro lado), y entonces la cookie rotada puede llevar `Secure` (y el pendiente solo se
acepta si la cookie llegó por ese origen). El acceso por `http://IP:8095` no se ve afectado porque
ya redirige al nombre HTTPS (D4).

**Requisito que viola**: Constitución Security 3 (fail-closed en identidad) y 5 (TLS en tránsito);
FR-004 en espíritu (la sesión es el equivalente del token). Hoy se acepta como "límite conocido"; la
mitigación es de bajo costo y conviene decidirla antes de implementar.

---

## F7 — Media — La spec no se enmendó y el plan la contradice o la excede

El plan declara `spec.md` "revisada (no se toca)" (plan.md:116) y su cabecera sigue diciendo
"Draft (especificada; sin plan ni tareas todavía)" (spec.md:7). Desvíos:

| Spec | Plan | Problema |
|---|---|---|
| **FR-010** (spec.md:198-199): "La instalación MUST servir el Hub por HTTPS" | D7-B (research.md:169-186): el instalador **no** sirve HTTPS; lo pone el proxy de Elea | Un MUST deliberadamente no implementado. La estimación de la spec (spec.md:277, "HTTPS 0,5 a 2 días") también quedó obsoleta |
| **FR-012** (spec.md:202-203): "Todo ingreso por SSO, aceptado o **rechazado**, MUST quedar en la auditoría" | D6 (research.md:139-153): el excedente del tope **no escribe filas** | Decisión del owner, pero contradice el texto literal del MUST sin una excepción escrita |
| Alcance de fase 1 (spec.md:254-255): "no hace falta que el backend acepte dos URIs" y backend solo si SSO en el panel (spec.md:9-11) | Tramo A cambia `backend/src/sso/api.py` (`return_origin`, auditoría, tope) y el panel | `return_origin` y el tope no tienen FR ni escenario de aceptación que los respalde; son requisitos huérfanos |

AGENTS.md pide spec → plan → tasks "con los skills `speckit-*`, no ediciones manuales". Una decisión
de plan que cambia un MUST se enmienda en la spec (`/speckit-clarify` o `/speckit-specify`) antes de
implementar, o la trazabilidad FR → tarea → test se pierde (justo lo que esta revisión audita).

**Corrección sugerida**: enmendar spec.md con (a) FR-010 reformulado como "documentar y verificar
el HTTPS delante del Hub", (b) excepción acotada en FR-012 para el tope, (c) un FR nuevo para
`return_origin` (el panel no ofrece un botón que no puede completar), y actualizar la cabecera.

---

## F8 — Media — Rechazos sin auditar fuera de la tabla de D6 (FR-012)

La tabla de D6 (guardian-sso-api.md:167-173) cubre `state`, `code` y proveedor cambiado. Quedan dos
rechazos del callback sin auditar [V]:

- `_cargar_config` levanta `404 sso_no_configurado` (`api.py:171-175`, invocado en `:275` fuera de
  todo `try`): el admin apagó el SSO a mitad del ingreso (rollback nivel 0, DESPLIEGUE:120) y el
  intento no deja rastro.
- `_redirect_uri` levanta `500 sso_redirect_uri_no_configurado` dentro del `try` del canje
  (`api.py:293`), y `except HTTPException: raise` (`api.py:295-296`) lo deja pasar sin auditar.

Ambos son "ingreso rechazado" para el FR-012 literal. Decidir si se auditan o si se declara la
excepción (junto con F7).

---

## F9 — Media — El test de `LATEST` no entra al gate y el Makefile no tiene dueño

T027 crea `deploy/release/checks/test_publish_elea_latest.sh` (tasks.md:238). Pero `make -C deploy
check` ejecuta una lista **explícita** de scripts (`deploy/Makefile:42`, `:52-128`); un archivo nuevo
en `checks/` no corre solo [V]. `deploy/Makefile` no figura en la propiedad de ningún tramo
(tasks.md:36-43). Resultado: el test que protege que `LATEST=0` no mueva `:latest` (el riesgo central
del despliegue, plan.md:192) corre solo si alguien se acuerda, y AGENTS.md define "el gate del release
es la verdad".

**Corrección sugerida**: sumar al tramo D la edición de `deploy/Makefile` (target nuevo en la lista
de `check`, sin Docker real: usa el stub) y a la propiedad de archivos.

---

## F10 — Media — Secreto vencido o IdP caído en el callback: mensaje equivocado

La spec pide error claro cuando vence el secreto (spec.md:161-162) y cuando el proveedor falla
(US2 AS2, spec.md:85-87). En el callback, cualquier excepción del canje —IdP caído, `invalid_client`
por secreto vencido, `code` vencido— sale como `401 sso_identidad_no_verificada` (`api.py:297-307`),
que el Hub mapea a "Microsoft no confirmó tu identidad" (hub-sso.md:77). El quickstart §4.3 da por
bueno ese texto. Al usuario final y al admin les dice lo contrario de lo que pasó (la persona sí es
quien dice; falló la instalación). Además se registra como `auth_sso_denied` aunque no fue un
rechazo de identidad. El backend **sí** distingue la causa en el log (`entra.py`, `_causa`, #294),
pero no la expone.

No es bloqueante porque FR-006 se cumple (el login con contraseña sigue). Conviene (a) un código
adicional en la lista cerrada para "falló la instalación" con texto que apunte al admin, y (b) que la
guía (T035) diga qué mensaje esperar cuando vence el secreto.

---

## Alcance acordado con el coordinador

- **Principio II**: se lee como la normativa del perfil de país (Ley 25.326 / AAIP), según la
  aclaración del owner recibida durante la revisión. **No se reporta** la ausencia de GDPR ni de EU
  AI Act. Lo que se revisó del Principio II es el mecanismo técnico (auditoría metadata-only, sin
  tokens, secretos ni PII), que vale igual.
- **Decisiones del owner (D1-D8 con D7 en B, y el tope de D6)**: no se reabren. Se revisó que estén
  bien volcadas en contratos y tareas, y que sean seguras. Los hallazgos F1, F5 y F6 son problemas
  de seguridad concretos con `archivo:línea`; F7 pide **reflejar** D7-B y el tope en la spec, no
  cambiarlos.
- **Base mínima y retrocompatible** (`backend/`, `frontend/`): el plan la respeta (campos nuevos
  opcionales, sin renombres, `jit.py`/`entra.py`/`registry.py`/`admin_api.py` intactos). Los
  puntos de base que conviene ajustar son F1 (alcance del tope), F8 y B5, todos dentro de
  `backend/src/sso/api.py`.

---

## Hallazgos bajos

| # | Hallazgo | Evidencia | Tipo |
|---|---|---|---|
| B1 | **Cerrar sesión en el Hub no cierra la sesión del directorio.** En una PC compartida, la persona siguiente pulsa "Ingresar con Microsoft" y entra como la anterior sin credenciales. El authorize no envía `prompt` (`entra.py:251-256`) y el logout del Hub solo borra la sesión local (`server.js:275-278`). Es comportamiento estándar de SSO, pero ni la spec ni la guía lo mencionan. Sugerencia: nota en T035 y evaluar `prompt=select_account` (cambio de base, mínimo) | `entra.py:251-256`, `server.js:275-278` | V |
| B2 | **Un usuario con cambio obligatorio pendiente (055) que entra por SSO nunca lo limpia**: el backend no impone el cambio del lado servidor (solo lo devuelve en el login, `users.py:214`; `grep must_change_password backend/src` no muestra ningún gate). Su contraseña temporal conocida por el admin sigue válida. Sugerencia: en la guía y en la checklist de activación, resetear o forzar el cambio de esos usuarios antes de activar | `users.py:214`, `:376`, `:731`, `:749` | V |
| B3 | **Reenvío de `code` y `state` al backend**: T016/T017 no piden codificarlos. Armar la URL por concatenación permite inyectar parámetros en la llamada interna (`code=x&state=otro`). Pedir `URLSearchParams` y un test con `&` y `#` | `tasks.md:135-148` | I |
| B4 | **Consumir el pendiente en cualquier callback** permite que un enlace externo (navegación de nivel superior, la cookie `Lax` viaja) mate el ingreso en curso. Solo molestia, no acceso. Asumido por la spec como "volvé a intentar" | `hub-sso.md:48` | I |
| B5 | **Normalización de `return_origin`**: el contrato dice `esquema://host[:puerto]` con el puerto "solo si la URI lo trae" (guardian-sso-api.md:141). Una URI `https://host:443/…` da `https://host:443` y nunca igualará `window.location.origin` (`https://host`): el botón se oculta mal. Con credenciales en la URI, `netloc` las incluiría; T006 debe usar `hostname`/`port`, no `netloc`. Casos a sumar a T004 | `tasks.md:73,80` | I |
| B6 | **`/api/auth/sso/available` sin `Cache-Control: no-store`**: US3 AS2 exige que el botón desaparezca "sin reiniciar nada". Con el ETag por defecto de Express es probable que funcione, pero no hay test ni cabecera explícita | `hub-sso.md:19-30` | I |
| B7 | **SC-002 con datos reales de Elea** no tiene tarea: T041 corre contra un directorio de prueba y "nunca el de Elea" (quickstart.md:5, tasks.md:311). La medición real ocurre en la Etapa 4 fuera del repo. Anotarlo como criterio que se cierra en el piloto | `spec.md:228-230` | V |
| B8 | **Portabilidad a Sentinel**: (a) el HANDOFF lista `docs/.../sso.md` como commit de base (tasks.md:315-316) pero T035 le suma una sección del Hub; marcarla "solo si hay Hub" para no portar documentación de algo que no existe; (b) `ELEA_TAG` no es portable (lo reconoce instalador-y-release.md:8-9); (c) el tope es una constante por proceso: correcto con el `uvicorn` de un solo proceso del `Dockerfile:19,35`, a revisar si Sentinel usa más | `tasks.md:312-324` | V/I |
| B9 | **Licencia con la clave de desarrollo**: con `SENTINEL_ALLOW_DEV_LICENSE=true` el permiso `sso` no es una frontera de seguridad real para quien tenga la clave `sentinel-dev-2026b`. Deuda ya declarada (plan.md:106-108); no la introduce esta spec. Además `.gitignore` no ignora `dev-sso-local.lic` ni `docker-compose.sso-local.yml` (`git check-ignore` no devuelve nada) y T003 confía solo en `git status` (tasks.md:58); ninguna tarea es dueña del `.gitignore` | `plan.md:106`, `tasks.md:58` | V |

---

## Matriz de cobertura: requisito → tarea → test

Leyenda: ✅ tarea y test automático · 🟡 tarea, test parcial o solo manual (quickstart) · ❌ sin test.

| Requisito | Tareas | Test automático | Estado |
|---|---|---|---|
| FR-001 botón solo con SSO habilitado | T010, T014, T018 | T010 (servidor) · UI sin test · falta caso `return_origin:null` | ❌ (F2, F4) |
| FR-002 misma sesión y token | T011, T017 | T011 | ✅ |
| FR-003 solo API de Guardian | T014-T017 | ninguno (por construcción) | 🟡 (sugerido: test que verifique que solo se llama a `ELEA_BACKEND_URL`) |
| FR-004 token fuera de la URL | T011, T015-T017 | T010/T011 (sin token en cabeceras ni cuerpo) | ✅ |
| FR-005 login con contraseña intacto | T019 | T019 | ✅ |
| FR-006 degrada solo SSO + mensaje | T019, T018 | T019 (servidor) · mensaje UI sin test | ❌ (F2, F10) |
| FR-007 reglas JIT intactas | T008 (gate), `jit.py` sin tocar | `test_sso_jit.py` existente | ✅ (por no tocar) |
| FR-008 sin cambio obligatorio ni "cambiar contraseña" | T011, T017, T018 | T011 (409) · UI sin test | ❌ (F2) |
| FR-009 config desde el panel, secreto cifrado | T021-T025 | T021 + `test_sso_config_api.py` existente | ✅ |
| FR-009b `SENTINEL_SSO_REDIRECT_URI` desde `.env` | T029, T033 | `docker compose config` | 🟡 |
| FR-010 HTTPS | T032, T036, T037 | ninguno (solo docs y quickstart) | 🟡 (F7: la spec dice "la instalación sirve") |
| FR-011 licencia con `sso` | T034 (manual) | quickstart §5.4 | 🟡 |
| FR-012 auditoría de todo ingreso | T005, T007 | T005 | 🟡 (F1, F7, F8) |
| FR-013 sin nombres internos | T026, T038 | ninguno automático sobre el Hub/panel | ❌ (F3) |
| FR-014 genérico, sin strings de Elea | T038 (parcial) | ninguno | ❌ (F3) |
| US1 AS1 existente conserva rol/grupo | T041 | `test_sso_jit.py` + manual §3.2 | 🟡 |
| US1 AS2 nuevo como `client`, ocupa puesto | T041 | `test_sso_jit.py` + manual §3.5 | 🟡 |
| US1 AS3 sin puestos | T009 (mapeo), T041 | T009 | ✅ |
| US1 AS4 baja no se revierte | T009 (mapeo), T041 | T009 + `test_sso_jit.py` | ✅ |
| US1 AS5 sin cambio de contraseña | T011, T018 | T011 · UI sin test | ❌ (F2) |
| US2 AS1 contraseña idéntica | T019 | T019 | ✅ |
| US2 AS2 error entendible | T019, T018 | T019 · UI sin test | ❌ (F2) |
| US2 AS3 sin botón y todo igual | T019, T018 | T019 · UI sin test | ❌ (F2) |
| US3 AS1 config cifrada, secreto no se muestra | T021, T025 | T021 + backend existente | ✅ |
| US3 AS2 apagar → botón desaparece sin reiniciar | T014 | manual §4.4 | 🟡 (B6) |
| US3 AS3 la config sobrevive a una actualización | T029-T033 | manual §5.6 | 🟡 |
| US3 AS4 sin datos de Entra → sin SSO y sin errores | T033, T019 | T019 + `compose config` | ✅ |
| US3 AS5 no-admin no ve ni cambia | T021, T025 | T021 (UI) · API deja leer a `compliance_officer` (`admin_api.py:66-68`), residual declarado | 🟡 |
| US4 AS1 la guía alcanza | T035-T037 | ninguno (requiere una persona ajena) | 🟡 |
| Caso borde: UPN ≠ email | T035, T037 | ninguno (guía y cruce de listas) | 🟡 |
| Caso borde: cuenta sin email | T009 | T009 + `test_sso_api.py:530` | ✅ |
| Caso borde: reinicio del Hub | T012 | T012 | ✅ |
| Caso borde: estado inválido o repetido | T005, T012 | T005, T012 | ✅ |
| Caso borde: secreto vencido | T041 §4.3 | manual | 🟡 (F10) |
| SC-001, SC-004 | T041 | medición manual | 🟡 |
| SC-002 datos reales de Elea | — | Etapa 4 fuera del repo | 🟡 (B7) |
| SC-003 regresión con SSO activo y roto | T019, T041 | T019 + manual | ✅ |
| SC-005 portabilidad | T042 | — | 🟡 (B8) |

**Resumen**: 0 FR sin ninguna tarea. Con test automático completo: FR-002, FR-004, FR-005, FR-007,
FR-009. Sin test en alguna de sus mitades: FR-001, FR-006, FR-008, FR-013, FR-014 (F2, F3).

---

## Verificado sin hallazgos

Contrastado contra el código; no hay desvío:

| Tema | Verificación |
|---|---|
| Atadura al navegador (D1) | El pendiente se indexa por `req.sid` (`server.js:88-97`); un callback de otro navegador no lo encuentra. El diseño de dos controles independientes (Hub compara `state`, el backend valida su cookie firmada, `api.py:102-124`, `:264`) es correcto. Falla solo ante F6 |
| Un solo uso | El backend solo borra la cookie del navegador (`api.py:335`), que no sirve si el cliente es un servidor; el contrato lo advierte (guardian-sso-api.md:213-216) y lo compensa consumiendo el pendiente. Correcto |
| Token fuera de la URL (FR-004) | El `access_token` llega en el cuerpo del callback del backend (`api.py:321-336`) y se queda en `sessions`; el navegador recibe `302 /`. Lo único en URL es `code`/`state`, de un solo uso |
| `redirect:'manual'` y `getSetCookie()` | Probado en este entorno (Node 22; la imagen usa `node:20-alpine`, `client/Dockerfile:1`): `fetch(..., {redirect:'manual'})` devuelve `302`, `Location` y `getSetCookie()` con la cookie `sentinel_sso_state`. H17 de research.md se confirma |
| Fail-closed de `available` | El contrato (hub-sso.md:23-30) colapsa todo lo que no sea `200 enabled:true`. Coincide con el criterio del panel |
| JIT y 055 intactos | Ningún tramo toca `jit.py`, `entra.py`, `registry.py` ni `admin_api.py` (tasks.md:40-43). `POST /api/auth/login` (`server.js:258-273`) queda fuera de T017. No hay migración (data-model.md:1-3) |
| Lista cerrada de errores | Los 403 de licencia (`sso_no_licenciado`, `api.py:78`), baja (`sso_usuario_inactivo`, `jit.py:116-119`) y puestos (`license_seat_limit_exceeded` 402 y `license_creation_blocked` 403, `licensing/gate.py:39,53,66,73,92`) se distinguen por prefijo, como el contrato lo describe (hub-sso.md:79-80). El mapeo es correcto |
| Auditoría metadata-only | `emit_auth_event` guarda solo ids, roles y `ts` (`auth_events.py:46-53`); `_auditar_denegado` no lleva email (`api.py:339-347`). Los eventos nuevos de D6 no agregan columnas |
| Multi-tenant | El tenant sale de `expected_tenant_id()` (`api.py:206`, `:259`); el JIT filtra por tenant (`jit.py:73-86`). El Hub no decide tenant |
| Sesión y puerto de plantillas | El proxy admin de plantillas lee `sessions.get(cookies[SID_COOKIE])` (`server.js:1573`): la rotación de `sid` no lo rompe (cookie por host, no por puerto) |
| Secreto | Se cifra con Fernet y no vuelve en ninguna respuesta (`admin_api.py:87-101`, `:118-195`); el formulario lo omite si está vacío. `PUT` rechaza `""` (`sso_secreto_vacio`). Coincide con panel-sso-config.md |
| Marca blanca de "Microsoft" | "Microsoft"/"Entra" ya figuran en el panel y en `docs/docs/install-deploy/sso.md:22` y pasan `check-docs`; no están en `prohibited_names.txt`. Es el proveedor de identidad del cliente, no un motor interno. Coherente con el plan (plan.md:94) |
| Números de línea del plan | Se verificaron por muestreo los citados de `api.py`, `server.js`, `index.html`, `jit.py` y `auth_events.py`: coinciden con `HEAD` |

---

## Orden recomendado para destrabar

1. **F1** (decisión de diseño, `/speckit-clarify` con el owner: extender el tope al canje fallido).
2. **F7 + F8** (una sola enmienda de spec: FR-010, FR-012 con su excepción, FR nuevo de `return_origin`).
3. **F2 + F3** (tareas de test para la pantalla del Hub y para FR-013/FR-014).
4. **F4, F5, F6, F9, F10** (ajustes de contrato y tareas; ninguno cambia la arquitectura).
5. Hallazgos bajos: absorberlos en `/speckit-tasks` o dejarlos como riesgos anotados.

---

## Evidencia de esta revisión

| Comando | Resultado |
|---|---|
| `cd client && npm ci && npm test` | 43 tests, 43 pass, 0 fail (línea base del Hub antes de la 056) |
| `node` con servidor HTTP de prueba: `fetch(…,{redirect:'manual'})` + `getSetCookie()` | `302`, `Location` y cookie `sentinel_sso_state` visibles (confirma H17) |
| `git check-ignore -v backend/config/licenses/dev-sso-local.lic docker-compose.sso-local.yml` | sin salida: no están ignorados (B9) |
| `grep -rn must_change_password backend/src` | solo se lee/escribe en `users.py` y el modelo; ningún gate server-side (B2) |
| `docker compose run … pytest`, `cd frontend && npm test`, `make -C deploy check` | **No se corrieron.** El cambio de esta revisión es un archivo Markdown sin efecto sobre esas suites; el backend y el panel requieren construir imágenes y `frontend/node_modules` no está instalado en este worktree. La línea base de esas tres es T002 de tasks.md |
