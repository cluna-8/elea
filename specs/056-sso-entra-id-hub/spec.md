# Feature Specification: Ingreso con Microsoft Entra ID (SSO) en Eleia Hub

**Feature Branch**: `056-sso-entra-id-hub`

**Created**: 2026-09-23

**Status**: Draft, enmendada por clarify el 2026-10-05 después del plan y del QA crítico
([qa-plan.md](qa-plan.md)). Plan: [plan.md](plan.md). Tareas: [tasks.md](tasks.md).

**Repos que toca (previsto)**: `cluna-8/elea` (`client/server.js`, `client/sso.js`,
`client/public/index.html`, `client/public/sso-ui.js`, `frontend/src/pages/UsersPage.tsx`,
`frontend/src/pages/LoginPage.tsx`, `backend/src/sso/api.py` (base mínima: `return_origin` y
auditoría con tope, ver Clarifications), `deploy/`, `docs/`), `cluna-8/elea-installer`
(`docker-compose.yml`, `.env.example`, `install.sh`), más una licencia nueva con el permiso `sso`.

**Input**: pedido del dueño del producto (23-sep-2026): *"analizar el costo en desarrollo que
llevaría agregar Entra ID para Elea, ellos tienen Active Directory… la forma de mantener la
funcionalidad y poder activar Entra ID"*. Después: *"creame la spec… para evitar clarify"* y
*"dejar todo listo para también agregar a Sentinel"*. Las ambigüedades quedan como
**supuestos a confirmar con Elea** (ver Assumptions), no como preguntas abiertas.

## Diagnóstico verificado en código (23-sep)

| # | Qué se esperaba | Qué hay en realidad |
|---|---|---|
| 1 | Hay que construir SSO | **Ya está construido en la base Guardian** (spec 017): `backend/src/sso/` (`entra.py`, `api.py`, `jit.py`, `admin_api.py`, `registry.py`), tabla `sso_providers` (migración `017_sso_providers.py`), secreto cifrado con Fernet, validación de firma, emisor, audiencia, vencimiento y nonce. El callback emite **el mismo token de sesión** que el login con contraseña, así que roles, grupos, presupuestos, llaves y motores no se tocan. |
| 2 | El panel Eleia Guardian tiene SSO | Sí: botón en `frontend/src/pages/LoginPage.tsx`, ruta `/sso/callback` (`SsoCallbackPage.tsx`) y pestaña "Autenticación & SSO" en `UsersPage.tsx`. |
| 3 | En la instalación de Elea funciona | **No.** La licencia `backend/config/licenses/dev-demo.lic` trae `feature_flags: ["monitor"]`, sin `sso`, y por eso todas las rutas `/auth/sso/*` responden 403. Además `elea-installer/docker-compose.yml` no le pasa al backend `SENTINEL_SSO_REDIRECT_URI`. |
| 4 | Los usuarios reales pueden entrar con Microsoft | **No.** Los usuarios reales (rol `client`) entran **solo por Eleia Hub** (`client/server.js:258`, `POST /api/auth/login`), que tiene únicamente usuario y contraseña. Es la misma lección que la spec 055: si no se implementa en el Hub, SSO no le llega al usuario real. |
| 5 | El retorno del proveedor sirve para las dos pantallas | El backend admite **una sola** URI de retorno (`_redirect_uri`, `backend/src/sso/api.py:127`). Hoy apunta al panel. |
| 6 | Alta automática segura | `jit.py`: busca por email dentro del tenant. Si ya existe, entra con **su rol y su grupo actuales**. Si no existe, lo crea como `client`, respetando el límite de puestos. Nunca sube el rol de nadie, nunca reactiva a un usuario que el admin dio de baja, no le pone el cambio obligatorio de contraseña de la spec 055 y no tiene contraseña local utilizable. El mapeo de grupos del proveedor a roles está explícitamente fuera de alcance desde la 017. |
| 7 | Hace falta HTTPS | Sí. Entra no acepta URIs de retorno `http://` salvo `localhost`. Hoy la instalación de Elea se sirve por puertos HTTP. |

**Es código de la base (Guardian), no de la localización argentina.** El SSO del backend ya es base.
Lo nuevo (login SSO en el Hub y cableado del instalador) se diseña genérico para portarlo a
Sentinel por handoff (ver §Preparación para Sentinel).

## Clarifications

### Session 2026-10-05

Decisiones que el owner tomó durante el plan y el QA crítico, por medio del coordinador (D1 a
D8 del plan; F1, F5, F6, F8 y F10 del QA, aprobadas el 2026-10-05; N1 del QA v2, aprobada el
mismo día). Se
registran acá para que la spec, el plan y las tareas digan lo mismo. El detalle y las alternativas
descartadas están en [research.md](research.md).

- Q: ¿Cómo intermedia el Hub el login y el callback si la cookie de estado firmada la emite el
  backend para su propio origen? → A: el flujo queda pendiente en el servidor del Hub, atado al
  navegador (`sid`), con `state` validado, de un solo uso y con rotación del `sid` al emitir la
  sesión (D1, opción A).
- Q: ¿Cómo sabe el Hub si mostrar el botón? → A: con un proxy fail-closed de
  `/auth/sso/available`. Solo un `200` con `enabled:true` lo muestra (D2, opción A).
- Q: ¿Cómo viajan el token y los errores? → A: el token queda solo en el servidor del Hub. El error
  vuelve a la pantalla como un código de una lista cerrada, sin copiar el `detail` del backend
  (D3).
- Q: Con una sola URI de retorno, ¿cómo evita cada pantalla mostrar un botón que no puede
  completar? → A: `/auth/sso/available` informa `return_origin` (esquema, host y puerto de la
  URI). El panel muestra su botón solo si `return_origin` es nulo o es su propio origen. El Hub lo
  muestra solo si `return_origin` no es nulo, y si es otro origen el botón lleva a ese origen
  (D4, opción A, más F4 del QA). → FR-001, FR-015.
- Q: ¿Cómo se oculta "cambiar contraseña" a quien entró por SSO? → A: con una marca de sesión
  `auth_method:'sso'` en el Hub, sin tocar el backend (D5, opción A).
- Q: ¿Se auditan los rechazos de flujo, que hoy no dejan rastro? → A: sí. El callback emite
  `auth_sso_denied` metadata-only antes de cada rechazo de flujo. El Hub no audita por su cuenta
  (D6). → FR-012.
- Q: ¿Cómo se acota la inundación de la auditoría desde afuera, sin autenticarse? → A: con un tope
  fijo por minuto y por proceso (~30) en el backend, que cubre los rechazos de flujo y también el
  **canje fallido** (`api.py:297-302`). Pasado el tope, ese rechazo no escribe fila, no llama al
  `token_endpoint` del directorio y se resume en un warning con el conteo. El veredicto HTTP no
  cambia. Los rechazos que exigen una identidad real del directorio (sin email, baja, sin puestos)
  no tienen tope (D6, opción A, extendida por F1 del QA). → FR-012, Edge Cases.
- Q: ¿Quién sirve el HTTPS delante del Hub? → A: el proxy TLS del cliente, o uno configurado a
  mano en el host. El instalador **no** suma un servicio TLS. El requisito se documenta y se
  verifica en la prueba (D7, opción B). → FR-010.
- Q: ¿Con qué clave se firma la licencia con `sso`? → A: con la misma clave y el mismo `kid` que
  la licencia vigente. Pasar a una clave de producción es una decisión aparte (D8).
- Q: ¿Se auditan también los rechazos del callback que hoy no están en la tabla de D6 (proveedor
  apagado a mitad del ingreso, `404 sso_no_configurado`; dirección de retorno faltante, `500
  sso_redirect_uri_no_configurado`)? → A: sí, como rechazos de flujo, dentro del tope (F8 del
  QA). → FR-012.
- Q: ¿Qué hace el Hub cuando alguien pide `/sso/login` en ráfaga y llena el almacén de ingresos
  en curso? → A: con el almacén lleno rechaza al que llega ("volvé a intentar") sin expulsar a
  ningún ingreso en curso, y además aplica un límite de ritmo global por proceso a `/sso/login`
  (120 por minuto) que corta sin llamar al backend (D11, opción B, por F5 del QA). → FR-016,
  Edge Cases.
- Q: ¿Cómo se evita que una cookie de sesión plantada en el navegador de la víctima le abra una
  sesión con la identidad del atacante (login CSRF)? → A: con retorno HTTPS, el Hub ata el
  ingreso además a una cookie `__Host-` de un solo uso, que no se puede escribir desde HTTP ni
  desde otro subdominio, y la cookie de sesión rotada lleva `Secure`. Con retorno HTTP
  (desarrollo en `localhost`) el ingreso queda atado solo a la sesión del navegador, como en D1.
  Solo Hub, sin cambio de base (D12, opción C, por F6 del QA). → FR-016.
- Q: ¿Qué mensaje ve la persona cuando falla el canje con el directorio (secreto vencido,
  directorio caído, respuesta vencida)? → A: un texto neutro que no culpa a la identidad: "No se
  pudo confirmar el ingreso con Microsoft. Si se repite, avisá al administrador." La guía dice qué
  esperar cuando vence el secreto y dónde ver la causa. Sin cambio de base ni código nuevo (D15,
  opción A, por F10 del QA). → FR-006, Edge Cases.
- Q: ¿Qué efecto real tienen los topes globales (30/min de canje fallido en el backend, 120/min de
  `/sso/login` en el Hub) y cómo se registra? → A: no se trata de una "ráfaga" pasajera. Un ritmo
  **sostenido** de 0,5 pedidos/s contra el callback del backend (con una sola cookie de estado,
  que vale 10 minutos) o de 2 pedidos/s contra `/sso/login` del Hub, sin autenticarse, deja el
  ingreso con Microsoft fuera de servicio **para todos** mientras dure. El login con contraseña
  no se afecta (FR-006). Se acepta como límite conocido y el diseño no cambia: D6 y D11 siguen
  igual. El valor de 120/min no sale de un dato medido; tras un reinicio del Hub, el reingreso
  masivo con tráfico legítimo también lo puede alcanzar. La guía y la prueba muestran cómo
  distinguir el corte por tope de una falla del directorio (N1 del QA v2,
  [qa-plan-v2.md](qa-plan-v2.md)). → FR-012, FR-016, Edge Cases.

### Session 2026-10-06

Preguntas del QA v2 que quedaron para el día siguiente, contestadas por el coordinador (las
marcadas "provisorio" quedan pendientes de una decisión del owner).

- Q: Si "promover a `latest`" pasa a ser re-etiquetar y empujar los mismos digests de la
  candidata probada (N2 del QA v2, fijado por el owner), ¿hace falta además que la imagen del Hub
  se construya con su lockfile? → A: **provisorio**: no en esta spec. Se anota como residual
  (research D9 y HANDOFF), sujeto a la política de dependencias e imágenes reproducibles que va a
  definir el owner. El server de Elea es **producción**; "piloto" nombra solo al grupo de 2 o 3
  usuarios que prueba el SSO primero. → US3 AS3, §Despliegue y vuelta atrás.
- Q: ¿`return_origin` se informa también cuando el SSO no está habilitado (`enabled:false`), y
  qué pasa si la dirección de retorno está mal escrita? → A: con `enabled:false` es nulo: sin
  proveedor activo nadie puede pulsar el botón y no hace falta revelar el nombre del Hub. Una
  dirección mal formada (puerto inválido o IPv6 mal cerrado) también da nulo, nunca un error
  de la consulta. Un host IPv6 conserva sus corchetes (N3 del QA v2). → FR-015.
- Q: El login con contraseña del Hub guarda la sesión bajo el `sid` que trae el navegador, sin
  renovarlo, y una cookie con `%` mal formado hace fallar todas las rutas para ese navegador
  (preexistente, N7 del QA v2). ¿Se corrige en esta spec? → A: sí, por decisión del owner
  (2026-10-06). El login con contraseña del Hub renueva el `sid` al emitir la sesión, igual que
  el camino SSO, y una cookie mal formada se ignora en vez de dar error. FR-005 se mantiene: lo
  que ve la persona en el login con contraseña no cambia. → FR-005, Edge Cases.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Un empleado de Elea entra al Hub con su cuenta corporativa (Priority: P1)

Una persona de Elea abre Eleia Hub, elige "Ingresar con Microsoft", se autentica con su cuenta
corporativa (la misma de Windows y Office) y llega al Hub con su rol, su grupo, su presupuesto y
sus espacios de siempre, sin haber creado ni recordado otra contraseña.

**Why this priority**: es el pedido. El usuario real entra por el Hub (Diagnóstico #4).

**Independent Test**: con la configuración de Entra cargada, un usuario ya dado de alta en
Guardian con el mismo email entra al Hub por Microsoft y usa chat, Documentos, Planillas y
Presentaciones. El gasto se imputa a esa persona y a su grupo.

**Acceptance Scenarios**:

1. **Given** un usuario existente en Guardian con email igual a su cuenta corporativa, **When**
   ingresa por "Ingresar con Microsoft", **Then** entra al Hub con el mismo rol, grupo,
   presupuesto, espacios e historial que cuando entra con contraseña.
2. **Given** una persona de Elea que todavía no existe en Guardian y hay puestos libres,
   **When** ingresa por Microsoft, **Then** se crea como `client`, sin grupo, y ocupa un puesto.
3. **Given** que no quedan puestos libres, **When** una persona nueva ingresa por Microsoft,
   **Then** ve un mensaje claro de que no hay puestos y no se crea el usuario.
4. **Given** un usuario dado de baja por un admin en Guardian, **When** intenta ingresar por
   Microsoft, **Then** se le niega el acceso y la baja no se revierte.
5. **Given** un usuario ingresado por Microsoft, **When** usa el Hub, **Then** no se le pide
   cambio obligatorio de contraseña ni se le ofrece cambiar una contraseña local que no tiene.

---

### User Story 2 - Nada de lo que funciona hoy deja de funcionar (Priority: P1)

Con SSO activo, el login con usuario y contraseña del Hub y del panel sigue igual. Lo mismo
el cambio obligatorio de contraseña (spec 055), las llaves de servicio de los motores y los
presupuestos. Si Microsoft no responde o la configuración está mal, solo falla el botón de
Microsoft.

**Why this priority**: el sistema ya está en producción en Elea. El pedido explícito es
"mantener la funcionalidad".

**Independent Test**: con SSO activo, repetir el recorrido de regresión (admin y un usuario
`client` con contraseña, alta con cambio obligatorio, uso de los cuatro motores). Después
romper a propósito la configuración de Entra y confirmar que el login con contraseña sigue
funcionando.

**Acceptance Scenarios**:

1. **Given** SSO activo, **When** un usuario entra con usuario y contraseña, **Then** el
   comportamiento es idéntico al de antes de esta spec.
2. **Given** que el proveedor está caído o mal configurado, **When** alguien pulsa "Ingresar
   con Microsoft", **Then** ve un error entendible que recuerda que el acceso con contraseña
   sigue disponible, y el resto del Hub no se ve afectado.
3. **Given** una instalación sin SSO configurado, o con una licencia sin permiso `sso`,
   **When** se abre el Hub, **Then** el botón de Microsoft no aparece y todo funciona como hoy.

---

### User Story 3 - El admin de Elea activa Entra desde el panel de su server (Priority: P1)

La activación se hace **en el server de Elea, desde el panel Eleia Guardian**, no desde nuestra
infraestructura. El admin carga el tenant, el identificador de la aplicación y el secreto, y
enciende o apaga el ingreso con Microsoft sin editar archivos ni la base a mano. El secreto lo
puede tipear el propio IT de Elea, así nunca pasa por nosotros.

**Why this priority**: es la forma pedida para activarlo (23-sep). Hoy la pestaña
"Autenticación & SSO" (`frontend/src/pages/UsersPage.tsx`) solo muestra el estado y dice
"contacte a soporte": la configuración se carga únicamente por API (`PUT /api/v1/auth/sso/config`,
que ya existe). Falta el formulario. El interruptor además es la **vuelta atrás inmediata**.

**Independent Test**: en una instalación con la licencia correcta, cargar los datos desde el
panel, confirmar que el botón de Microsoft aparece en el Hub y funciona, apagarlo desde el panel
y confirmar que desaparece sin reiniciar nada. Actualizar la instalación y confirmar que la
configuración se conserva.

**Acceptance Scenarios**:

1. **Given** un admin en el panel, **When** carga tenant, identificador y secreto y activa el
   interruptor, **Then** el SSO queda activo y el secreto queda cifrado. El panel nunca vuelve a
   mostrar el secreto: solo indica que está cargado.
2. **Given** SSO activo, **When** el admin lo desactiva, **Then** el botón de Microsoft
   desaparece del Hub en el próximo ingreso y el login con contraseña sigue igual.
3. **Given** una instalación ya activada, **When** se actualiza con el instalador, **Then** la
   configuración de SSO se conserva.
4. **Given** que nadie cargó datos de Entra, **When** se instala o se actualiza, **Then** la
   instalación queda sin SSO y sin errores.
5. **Given** un usuario que no es `super_admin` ni `tenant_admin`, **When** entra al panel,
   **Then** el panel no le muestra ni le deja cambiar la configuración de SSO (ver el residual
   de la API en Edge Cases).

---

### User Story 4 - El IT de Elea sabe qué registrar en Entra (Priority: P3)

El IT de Elea tiene una guía corta que dice qué aplicación registrar, qué dirección de retorno
usar, qué permisos dar, qué datos devolver y cuándo vence el secreto.

**Why this priority**: es un requisito para activar, pero es documentación.

**Independent Test**: una persona que no participó del desarrollo registra la aplicación en un
tenant de prueba siguiendo solo la guía, y el login funciona.

**Acceptance Scenarios**:

1. **Given** la guía, **When** el IT registra la aplicación, **Then** obtiene los tres datos que
   pide el instalador y la dirección de retorno coincide con la que espera Eleia.

---

### Edge Cases

- **El email corporativo (UPN) no coincide con el email cargado en Guardian**: se crea un
  usuario nuevo `client` en lugar de reconocer al existente. Mitigación: antes de activar,
  alinear los emails de los usuarios existentes. Queda en la guía y en la checklist de
  activación.
- **La cuenta corporativa no trae email**: se niega el ingreso con un mensaje claro. No se
  inventa un identificador.
- **Usuario deshabilitado en Entra con sesión abierta**: no puede volver a ingresar por
  Microsoft, pero su sesión vigente dura hasta su vencimiento normal (24 h). Sin SCIM no hay
  baja automática en Guardian. Queda documentado como límite conocido.
- **El Hub se reinicia a mitad del ingreso con Microsoft** (las sesiones del Hub están en
  memoria): el ingreso falla con un mensaje de "volvé a intentar", sin quedar a medias.
- **Ingreso con Microsoft vencido o manipulado** (estado inválido, respuesta repetida): se
  rechaza y se registra como intento denegado.
- **Ingresos falsos sostenidos sin autenticarse** (estados o `code` inventados contra el
  callback): cada rechazo responde igual, pero pasado el tope por minuto (FR-012) deja de
  escribir filas y de llamar al directorio. Con una sola cookie de estado alcanza un ritmo
  sostenido de 0,5 pedidos/s (30 canjes falsos al inicio de cada minuto) para que **todo**
  ingreso legítimo reciba el mismo mensaje de falla mientras dure. Un tercero con acceso de red
  al backend puede mantener fuera de servicio el ingreso con Microsoft. Es un límite conocido y
  aceptado (Clarifications, N1). Solo se degrada el camino SSO: el login con contraseña sigue
  (FR-006).
- **Pedidos de inicio sostenidos contra el Hub** (`/sso/login` en bucle, sin sesión): pasado el
  límite de ritmo, o con el almacén de ingresos en curso lleno, el que llega recibe "volvé a
  intentar" sin que el Hub llame al backend. Con 2 pedidos/s sostenidos el botón falla para
  todos mientras dure; un tercero con acceso de red al Hub alcanza. Lo mismo puede pasar sin
  ataque, si muchas personas reingresan juntas tras un reinicio del Hub. Los ingresos que ya
  estaban en curso no se pierden (FR-016). El login con contraseña sigue. Límite conocido y
  aceptado (Clarifications, N1).
- **Cookie de sesión plantada en el navegador de la víctima** (por red o desde un subdominio
  hermano) para que el ingreso de la víctima termine con la identidad de otro: con retorno HTTPS
  el ingreso se rechaza con "volvé a intentar", porque falta la cookie de atadura (FR-016).
- **Cookie de sesión plantada antes de un login con contraseña** (para conocer la sesión que
  abra la víctima): el Hub renueva la cookie al ingresar, así que la plantada no sirve. Una
  cookie mal formada se ignora y el Hub sigue respondiendo (FR-005, Clarifications N7).
- **El admin apaga el SSO, o falta la dirección de retorno, a mitad de un ingreso**: el ingreso
  termina con "no disponible", queda auditado (FR-012) y el login con contraseña sigue. Con la
  dirección de retorno vacía, el Hub no dibuja el botón (FR-001, FR-015).
- **Cerrar sesión en el Hub no cierra la sesión corporativa de Microsoft**: en una PC compartida,
  la persona siguiente que pulse "Ingresar con Microsoft" puede entrar con la cuenta anterior si
  la sesión de Microsoft sigue abierta. Es el comportamiento estándar de SSO. Queda documentado
  como límite conocido en la guía.
- **Usuario existente con cambio obligatorio pendiente (spec 055) que entra por SSO**: no se le
  pide el cambio (FR-008) y su contraseña temporal sigue valiendo para el login local. La
  checklist de activación indica resetear o forzar el cambio de esos usuarios antes de activar.
- **Un `compliance_officer` consulta la configuración por API**: la API de la spec 017 le permite
  leerla (tenant e identificador de la aplicación, nunca el secreto). El panel no se la muestra
  (US3 AS5). Es un residual conocido de la base: cambiar la matriz de roles queda fuera de
  alcance para no tocar la base.
- **Un admin entra al Hub por Microsoft**: entra con su rol de admin actual, porque el SSO no
  cambia roles. El panel Eleia Guardian sigue con contraseña en la fase 1.
- **Vence el secreto de la aplicación en Entra, o el directorio no responde durante el canje**:
  el botón de Microsoft falla con "No se pudo confirmar el ingreso con Microsoft. Si se repite,
  avisá al administrador.", que no culpa a la identidad de la persona. El login con contraseña
  sigue funcionando. La guía indica qué mensaje esperar, dónde ver la causa en el log del backend
  y cómo renovar el secreto.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Eleia Hub MUST ofrecer "Ingresar con Microsoft" junto al login con usuario y
  contraseña **solo** cuando la instalación tiene SSO habilitado (licencia con permiso `sso` y
  proveedor configurado y activo) **y** tiene configurada la dirección de retorno
  (`return_origin` no nulo, FR-015). Sin dirección de retorno el flujo no puede arrancar, así que
  el Hub no dibuja el botón.
- **FR-002**: El ingreso con Microsoft desde el Hub MUST terminar en la misma sesión de Hub
  que el login con contraseña, con el mismo token emitido por Guardian. Así chat, Documentos,
  Planillas, Presentaciones, presupuestos y permisos de espacios funcionan sin cambios.
- **FR-003**: El Hub MUST obtener la identidad **únicamente por la API de Guardian**: sin base
  compartida, sin imports cruzados y sin validar él mismo los tokens de Microsoft (regla de la
  spec 051: Guardian ↔ Hub es cliente ↔ proveedor).
- **FR-004**: El token de sesión MUST NOT viajar en la URL del navegador en ningún paso. Queda
  del lado del servidor del Hub, igual que hoy.
- **FR-005**: El login con usuario y contraseña del Hub y del panel MUST seguir disponible y sin
  cambios de comportamiento visibles para la persona (mismas respuestas, mensajes y cambio
  obligatorio de la 055). SSO es un camino adicional, nunca un reemplazo. Única excepción,
  interna e invisible: el login con contraseña del Hub renueva la cookie de sesión al ingresar,
  y el Hub ignora una cookie mal formada en vez de fallar (Clarifications, N7).
- **FR-006**: Si el proveedor falla, no está configurado o la licencia no lo habilita, MUST
  degradarse solo el camino SSO, con un mensaje que recuerde que el acceso con contraseña sigue
  disponible.
- **FR-007**: Las reglas de alta automática existentes MUST mantenerse:
  - buscar al usuario por email dentro del tenant;
  - crear con rol `client` si no existe, respetando el límite de puestos;
  - no cambiar nunca el rol, el grupo ni el tenant de un usuario existente;
  - no reactivar nunca a un usuario dado de baja.
- **FR-008**: Los usuarios que ingresan por SSO MUST NOT quedar sujetos al cambio obligatorio de
  contraseña (spec 055), y el Hub MUST NOT ofrecerles "cambiar contraseña" si no tienen
  contraseña local.
- **FR-009**: El panel Eleia Guardian MUST permitir que un admin (`super_admin` o
  `tenant_admin`) cargue, cambie, active y desactive la configuración de Entra (tenant,
  identificador de la aplicación y secreto) usando la API de configuración SSO que ya existe. El
  secreto MUST guardarse cifrado, MUST NOT volver a mostrarse y MUST NOT quedar en claro en
  archivos. La configuración MUST sobrevivir a una actualización.
- **FR-009b**: El instalador MUST pasar al backend la dirección de retorno del Hub
  (`SENTINEL_SSO_REDIRECT_URI`) desde `.env`. Si está vacía, la instalación arranca igual y sin SSO.
- **FR-010**: El Hub MUST quedar accesible por HTTPS en el nombre registrado como retorno en
  Entra, y el server MUST poder salir por HTTPS a `login.microsoftonline.com`. El TLS lo termina un
  proxy del cliente delante del Hub (o uno configurado a mano en el host). El instalador no lo
  sirve (Clarifications, D7-B). La entrega MUST **documentar** el requisito (qué publica el proxy,
  a qué puerto reenvía y qué rutas) y **verificarlo** en la prueba de punta a punta.
- **FR-011**: La licencia de Elea MUST incluir el permiso `sso`. Sin él, FR-001 y FR-006 aplican
  (sin botón y sin errores).
- **FR-012**: Todo ingreso por SSO, aceptado o rechazado, MUST quedar en la auditoría de
  autenticación existente, solo con metadatos: sin tokens, secretos, `state`, `code` ni email.
  Cubre lo que llega al callback del backend. Los cortes del Hub al **iniciar** el ingreso
  (límite de ritmo o almacén lleno, FR-016) no llegan al backend ni son un ingreso: no se
  auditan. "Rechazado" incluye los rechazos de **flujo** del callback: estado ausente, inválido o repetido,
  `code` ausente, proveedor cambiado, apagado o sin configurar a mitad del ingreso, dirección de
  retorno faltante. Incluye también el **canje fallido** con el directorio y los rechazos de
  **identidad**: sin email, usuario dado de baja, sin puestos. **Única excepción**: los rechazos
  de flujo y de canje fallido tienen un tope fijo por minuto y por proceso (Clarifications, D6 y
  F1). Pasado el tope, el rechazo no escribe fila y se resume en un warning con el conteo
  omitido. El canje fallido, además, deja de llamar al directorio. El veredicto que ve el usuario
  no cambia. Los rechazos de identidad no tienen tope.
- **FR-013**: Nada de lo visible para el cliente (pantallas, errores, guía) MUST exponer nombres
  de componentes internos (motor de gateway, motores de documentos o presentaciones), según la
  regla vigente del producto.
- **FR-014**: Todo lo nuevo MUST ser genérico y configurable, sin nombres, dominios, tenants ni
  marcas de Elea fijos en el código, para portarlo a Sentinel sin reescribir (ver §Preparación
  para Sentinel). Aplica al código de base y del Hub. El instalador propio de la línea puede usar
  nombres propios (p. ej. la variable del tag de imagen), y el HANDOFF lo porta como enfoque.
- **FR-015**: La consulta pre-auth de disponibilidad de SSO MUST informar el **origen de
  retorno** (`return_origin`: esquema, host y puerto de la dirección de retorno configurada, sin
  ruta, query ni credenciales; nulo si falta, no es absoluta, está mal formada o el SSO no está
  habilitado). Ninguna pantalla MUST ofrecer un
  botón de Microsoft que no pueda completar el ingreso:
  - el panel lo muestra solo si `return_origin` es nulo (comportamiento de hoy) o es su propio
    origen;
  - el Hub lo muestra solo si `return_origin` no es nulo, y si es otro origen el botón lleva a
    ese origen.

  El campo es opcional y retrocompatible: un cliente que lo ignora se comporta como hoy.
- **FR-016**: El ingreso con Microsoft desde el Hub MUST quedar atado al navegador que lo inició:
  validado contra el `state` guardado, de un solo uso y con la sesión del navegador renovada al
  emitirla. Con dirección de retorno HTTPS, la atadura MUST incluir una cookie que no se pueda
  escribir desde HTTP ni desde otro subdominio, y la cookie de sesión resultante MUST llevar
  `Secure`. Una ráfaga de pedidos de inicio MUST NOT cortar los ingresos que ya están en curso:
  el Hub rechaza al que llega (almacén lleno o límite de ritmo) en vez de expulsar a otro
  (Clarifications, D1, D11 y D12).

### Key Entities

- **Proveedor SSO del tenant** (ya existe, `sso_providers`): tipo de proveedor (`entra`),
  tenant e identificador de la aplicación en Microsoft, secreto cifrado, habilitado sí/no. Uno
  por tenant.
- **Usuario** (ya existe): el email es la clave de cruce con la cuenta corporativa. Los usuarios
  nacidos por SSO no tienen contraseña local utilizable.
- **Sesión del Hub** (ya existe, en memoria): guarda el token de Guardian del lado del
  servidor. Se usa igual venga del login con contraseña o del SSO.
- **Licencia** (ya existe): el permiso `sso` habilita la funcionalidad.
- **Ingreso en curso** (nuevo, en memoria del Hub): ata un ingreso con Microsoft al navegador
  que lo inició (sesión del navegador, estado esperado y, con retorno HTTPS, cookie de atadura).
  Vence a los 10 minutos y se usa una sola vez (FR-016).
- **Contador de ritmo de inicio** (nuevo, en memoria del Hub): cuenta los inicios de ingreso por
  minuto para cortar una ráfaga sin afectar a los que están en curso (FR-016).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un empleado de Elea con cuenta corporativa entra al Hub en menos de 30 segundos y
  en no más de 3 interacciones, sin crear ni tipear una contraseña de Eleia.
- **SC-002**: El 100 % de los usuarios existentes cuyo email coincide con su cuenta corporativa
  entran con su rol, grupo y presupuesto intactos, y 0 usuarios duplicados en la prueba con datos
  reales de Elea.
- **SC-003**: El recorrido de regresión (login con contraseña, cambio obligatorio de la 055,
  cuatro motores, presupuestos) pasa completo con SSO activo y con SSO roto a propósito.
- **SC-004**: El admin de Elea activa o desactiva SSO desde el panel en menos de 5 minutos una vez que
  tiene los datos de Entra, sin editar código ni la base a mano.
- **SC-005**: El cambio se porta a Sentinel sin reescribir lógica: solo configuración, licencia
  y, si corresponde, adaptar la pantalla de ingreso de su superficie de usuarios.

## Assumptions

**Supuestos a confirmar con Elea** (clarify registró las decisiones de diseño, no estos supuestos; si alguno cae, cambia el costo):

1. **El Active Directory de Elea está sincronizado con Entra ID** (Entra Connect / Microsoft 365).
   Si solo tienen AD local, sin Entra, esta spec no alcanza: haría falta ADFS con un proveedor
   OIDC genérico (+1 a 2 días) o LDAP (+3 a 5 días), en una spec aparte.
2. **El UPN o email corporativo coincide con el email cargado en Guardian** para los usuarios
   existentes. Si no, se alinean antes de activar.
3. **Elea puede dar un nombre DNS, un certificado** (CA interna o público) **y un proxy TLS**
   delante del Hub (FR-010, D7-B). Es el punto que más puede estirar el plazo y depende de su red.
4. El IT de Elea registra la aplicación en Entra (≈1 h) y entrega tenant, identificador y secreto.
   El secreto vence (máximo 24 meses) y hay que renovarlo.

**Decisiones de alcance (fase 1):**

- SSO **solo en Eleia Hub**. El panel Eleia Guardian sigue con contraseña para los admins, y no
  hace falta que el backend acepte dos URIs de retorno. El backend sí recibe dos cambios de base
  chicos y retrocompatibles: `return_origin` en la consulta de disponibilidad (FR-015) y la
  auditoría de los rechazos de flujo con tope (FR-012).
- HTTPS por el proxy del cliente, solo documentado y verificado (FR-010). El instalador no
  termina TLS.
- Solo el proveedor Microsoft Entra (el que ya existe). Sin MFA propio: la MFA la aplica Entra si
  Elea la tiene configurada.

**Fuera de alcance, con estimación, por si se piden después:**

| Extra | Días de dev |
|---|---|
| SSO también en el panel Eleia Guardian (backend con lista de URIs de retorno permitidas) | +0,5 a 1 |
| Mapeo de grupos de Entra a rol y grupo de Guardian (claim `groups`, más de 200 grupos, pantalla de mapeo) | +2 a 4 |
| Baja automática desde Entra (SCIM) | +3 a 5 |
| Sesiones del Hub persistentes (hoy en memoria) | aparte, no bloquea |

**Estimación de la fase 1: 5,25 a 6,25 días de dev**. Suma el formulario del panel y el versionado
para volver atrás, pedidos el 23-sep. Se re-estimó el 2026-10-05: el HTTPS queda en el proxy del
cliente (D7-B) y se suman el tope de auditoría, los tests de la pantalla del Hub y el gate de marca
blanca (QA del plan).

| Tarea | Días |
|---|---|
| Licencia con `sso` | 0,25 |
| Cableado del instalador (`SENTINEL_SSO_REDIRECT_URI`) | 0,25 |
| Formulario de configuración SSO en el panel (usa la API existente) | 0,5 a 1 |
| Vuelta atrás real: tag de imagen fijable en el instalador (`ELEA_TAG`), publicar candidatas sin mover `latest`, licencia montada desde el host | 0,5 |
| HTTPS: documentar y verificar el proxy TLS del cliente (el tiempo de su red no es de dev) | 0,25 |
| Base: `return_origin` y auditoría con tope | 0,25 a 0,5 |
| SSO en el Hub, con tests de la pantalla y el gate de marca blanca | 1,75 a 2 |
| Prueba de punta a punta con el tenant real y regresión | 1 |
| Guía para IT y docs | 0,5 |

## Despliegue y vuelta atrás

Procedimiento completo en [DESPLIEGUE-Y-REVERSION.md](DESPLIEGUE-Y-REVERSION.md). Lo que Elea tiene
que preparar está en [SOLICITUD-A-ELEA.md](SOLICITUD-A-ELEA.md).

## Preparación para Sentinel

Pedido explícito del dueño (23-sep): *"dejar todo listo para también agregar a Sentinel"*.
Mismo patrón que las specs 053, 054 y 055: se implementa en `cluna-8/elea` y se entrega a
`cluna-8/sentinel` (producto base, "Guardian") con un `HANDOFF-elea-a-sentinel.md` en esta
carpeta al cerrar.

| Pieza | Dónde | ¿Base o de Eleia? |
|---|---|---|
| SSO del backend (proveedor Entra, alta automática, config cifrada, callback) | `backend/src/sso/` | **Base, ya existe** (spec 017). Confirmar que Sentinel tenga la migración `017_sso_providers` y la misma versión de `sso/`. |
| Permiso `sso` en licencia | licencias firmadas | Base. Cada línea emite la suya con su clave. |
| `return_origin` en `/auth/sso/available` y auditoría de los rechazos de flujo y del canje fallido con tope por proceso (FR-012, FR-015) | `backend/src/sso/api.py` | **Base**, mínima y retrocompatible: campo opcional nuevo, mismos status y `detail`. Viaja por cherry-pick con sus tests. El tope es una constante por proceso: se revisa si Sentinel corre más de un proceso. |
| Lista de URIs de retorno (solo si se pide SSO en el panel) | `backend/src/sso/api.py` | Base, retrocompatible: si no hay lista, se usa la variable única de hoy. |
| Variable `SENTINEL_SSO_REDIRECT_URI` en compose y `.env.example` | `elea-installer/` | Base en enfoque. Portar al instalador de Sentinel con nombres de variable **iguales**. |
| Formulario de configuración SSO en el panel | `frontend/src/pages/UsersPage.tsx` (pestaña "Autenticación & SSO") | **Base**: es el mismo `frontend/` que comparten las dos líneas. Portable tal cual, confirmando antes el diff (mismo caveat que la 054 y la 055). |
| Login SSO del Hub | `client/server.js`, `client/public/index.html` | **Específico de esta línea**, igual que en la 055. En Sentinel se porta el **enfoque** (el Hub hace de intermediario con la API de Guardian y guarda el token del lado del servidor), no el diff, y solo si Sentinel tiene una superficie de usuarios equivalente. Si sus usuarios entran por el panel, alcanza con el SSO que el panel ya tiene. |
| Guía de registro en Entra | `docs/docs/install-deploy/sso.md` | Base, sin marca: redactar con "Guardian" y marcadores para el nombre de la instalación. |

**Estado del porte (23-sep)**: la spec espejo ya existe en Sentinel, `specs/067-porte-elea-sso-entra-hub/` (cluna-8/sentinel#24). Allí también está el plan de prueba simultánea: directorio personal para Eleia y directorio de Evidenze para Sentinel. Backend y panel se escriben una sola vez y se cherry-pickean.

**Reglas de diseño para que el port sea directo** (se verifican en el analyze y, las de marca,
con el gate automático de marca blanca del Hub y los tests del panel):

- Sin strings de Elea ni Eleia en lógica. Textos visibles tomados de la marca configurada de la
  instalación.
- Toda la configuración por variables de entorno o por la API de config SSO existente, nunca por
  código.
- Las migraciones, si hicieran falta, con id por hash (`alembic revision`), no secuencial, por el
  choque de numeración Base/Sentinel/Eleia documentado en `specs/README.md`.
- Los tests nuevos de backend viven junto a los de `sso/` para que viajen con el módulo.
- El handoff lista el orden de cherry-pick y separa commits de base y commits del Hub.
