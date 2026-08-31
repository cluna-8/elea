# Feature Specification: Productización de la extensión de navegador

**Feature Branch**: `028-extension-productizacion`

**Created**: 2026-07-24

**Status**: Implementada — estado canónico en [`ROADMAP-guardian.md`](../ROADMAP-guardian.md)

**Input**: User description: "Preparar la extensión de navegador para el primer piloto real (Cámara de Comercio, install del martes). La extensión intercepta Claude y ChatGPT en el navegador, enmascara PII antes de que salga y muestra bloqueos de gobernanza. Debe entregarse con la marca del partner (white-label), declarar honestamente su nivel de protección, entender los bloqueos de la 027, distinguir sesión caída por red vs por permiso, y viajar dentro del entregable que se instala en el servidor del cliente. Brief de handoff completo en issue #46."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Una sola extensión, generada por partner desde su marca (Priority: P1) · MUST-piloto

Un operador de release necesita entregar la extensión a un partner (p. ej. Cámara de Comercio) con la identidad de ese partner, sin editar archivos a mano ni mantener copias divergentes. A partir de la marca del partner, un solo comando produce un paquete instalable listo para repartir al equipo de IT del cliente, y ese paquete viaja dentro del entregable que se instala en el servidor. **El paquete hornea solo la identidad del partner (marca + identificador estable), no la dirección del gateway** — la dirección la aporta el usuario en tiempo de uso (ver US2), lo que hace al paquete agnóstico al despliegue y elimina la dependencia de conocer la URL al empaquetar.

**Why this priority**: Sin esto, cada partner es una edición manual del paquete → la "fábrica de copias divergentes" que ya nos costó una fuga de PII. Además, el paquete de la extensión hoy NO forma parte del entregable de instalación; si no entra, el instalador no tiene qué repartir. Es la base del entregable del piloto.

**Independent Test**: Generar el paquete para un partner de prueba desde su marca, verificar que el paquete resultante es instalable en el navegador y muestra la identidad del partner, y confirmar que aparece listado en el manifiesto del entregable con su huella (checksum).

**Acceptance Scenarios**:

1. **Given** la marca de un partner, **When** el operador genera el paquete de la extensión, **Then** obtiene un paquete instalable cuyo nombre, descripción, íconos e identificador estable salen de la marca del partner, sin ninguna edición manual y sin ninguna dirección de gateway horneada.
2. **Given** un paquete generado para un partner, **When** se arma el entregable de instalación, **Then** el paquete queda incluido en el entregable y listado en su manifiesto con su checksum.
3. **Given** dos empleados que instalan el mismo paquete del partner en carpetas distintas, **When** ambos lo cargan en el navegador, **Then** ambas instalaciones tienen la misma identidad estable (mismo identificador de extensión).
4. **Given** el paquete del partner, **When** se genera, **Then** puede armarse en tiempo de partner (la marca se conoce temprano) sin esperar a que un cliente despliegue ni a conocer su URL.

---

### User Story 2 - El usuario conecta la extensión a su gateway (URL + key) (Priority: P1) · MUST-piloto

El usuario final configura la extensión con dos datos que le da su administrador: la dirección de su gateway y su API key personal. La extensión queda así **agnóstica al despliegue** (se enchufa a cualquier gateway), y la conexión funciona de verdad — no como hoy, donde la dirección es editable pero el navegador bloquea silenciosamente la conexión a cualquier host no declarado ("libertad falsa").

**Why this priority**: Sin esto, la extensión solo habla con un host fijo horneado y no puede apuntar al gateway real del cliente; con la dirección editable pero sin resolver el permiso de host, el usuario cree que configuró y no conecta. Es la diferencia entre "parece que anda" y "anda".

**Independent Test**: Instalar el paquete del partner, ingresar la URL del gateway y una key, conceder el permiso que pide el navegador, y verificar que la extensión enmascara y valida contra ese gateway; repetir apuntando a otro gateway distinto y verificar que también funciona (agnóstico).

**Acceptance Scenarios**:

1. **Given** la extensión recién instalada, **When** el usuario ingresa la URL de su gateway y su key y confirma, **Then** el navegador le pide permiso para acceder a ese host, y al concederlo la extensión conecta y enmascara contra ese gateway.
2. **Given** un usuario que ingresa una URL de gateway remota que no es segura (no `https`), **When** intenta conectar, **Then** la extensión rechaza la URL (una credencial por usuario sobre conexión insegura viaja en claro); una URL local queda permitida sin `https`.
3. **Given** una extensión ya conectada a un gateway, **When** el usuario cambia la URL a otro host, **Then** el navegador pide permiso para el host nuevo antes de usarlo.
4. **Given** el paquete del partner, **When** se genera, **Then** la URL puede venir pre-cargada como valor por defecto editable (conveniencia), pero nunca fija: el usuario siempre puede cambiarla.
5. **Given** un usuario que no concede el permiso de host, **When** intenta conectar, **Then** la extensión muestra un mensaje claro de que necesita el permiso para conectar (no un fallo silencioso).

---

### User Story 3 - El paquete lleva la marca del partner y ninguna otra (Priority: P1) · MUST-piloto

El cliente final no debe ver la marca del fabricante ni nombres internos del motor en la lista de extensiones de su navegador cuando el partner rebrandeó el producto.

**Why this priority**: Es una promesa contractual del modelo white-label. Una sola fuga de marca ("Sentinel", "PoC", el nombre del motor) en la ficha visible rompe la propuesta ante el cliente del partner.

**Independent Test**: Inspeccionar el paquete generado para un partner y verificar que en ningún texto visible aparece la marca del fabricante, el término "PoC", el nombre del motor de detección ni una dirección de desarrollo.

**Acceptance Scenarios**:

1. **Given** un paquete generado para un partner, **When** se inspecciona su contenido visible (nombre, descripción, textos de la interfaz, documentación incluida), **Then** no contiene la marca del fabricante, "PoC", el nombre del motor de detección ni "localhost".
2. **Given** el mismo paquete, **When** se revisan sus íconos y su número de versión, **Then** los íconos provienen de la marca del partner y la versión tiene una única fuente de verdad (no está duplicada en varios lugares que puedan divergir).

---

### User Story 4 - La extensión declara su nivel real de protección (Priority: P1) · MUST-piloto

El usuario que trabaja en el navegador debe entender que, en esta superficie, la detección de datos personales funciona por patrones conocidos (correo, teléfono, documentos, credenciales) y no por análisis lingüístico — para no leer "protegido" y asumir que cubre más de lo que cubre.

**Why this priority**: Mostrar un "protegido" genérico junto a "no se encontró PII" comunica una garantía que la superficie no da. La honestidad-por-plano es el principio que justifica la 027 entera; la extensión no puede contradecirlo.

**Independent Test**: Con la extensión conectada, verificar que la interfaz muestra un indicador ámbar de "detección por patrones · cobertura parcial" (no verde, sin la palabra "protegido") y un texto que explica en lenguaje llano el alcance real, tomado del servidor.

**Acceptance Scenarios**:

1. **Given** la extensión conectada a un gateway cuya superficie de navegador detecta por patrones, **When** el usuario abre el panel de la extensión, **Then** ve un indicador ámbar "Detección por patrones · cobertura parcial" y un texto que explica que puede no reconocer nombres o direcciones en texto libre.
2. **Given** un gateway que no informa el nivel de protección (versión anterior), **When** el usuario abre el panel, **Then** la extensión asume la promesa más chica ("patrones"), nunca la más grande.
3. **Given** que el texto de alcance se define en un solo lugar del servidor, **When** cambia esa definición, **Then** la extensión refleja el cambio sin tocar el paquete (no hay texto de protección hardcodeado en la extensión).

---

### User Story 5 - La extensión explica el motivo real de un bloqueo de gobernanza (Priority: P1) · MUST-piloto

Cuando el gateway bloquea un envío por política (AI-Act, secretos), el usuario debe ver el motivo real del bloqueo, no un mensaje de "servicio no disponible" que parece una caída de infraestructura.

**Why this priority**: En cuanto la gobernanza (027) esté activa en el servidor del cliente, empezará a bloquear por política. Hoy la extensión muestra "gateway no disponible" ante cualquier respuesta negativa → un bloqueo legítimo se lee como una caída y el cliente abre un ticket de soporte durante el piloto.

**Independent Test**: Simular una respuesta de bloqueo por política del gateway y verificar que la extensión frena el envío y muestra el motivo provisto por el servidor; simular una respuesta de servicio caído y verificar que muestra "servicio no disponible".

**Acceptance Scenarios**:

1. **Given** una respuesta del gateway que indica bloqueo por una capa de política con su motivo, **When** el usuario intenta enviar, **Then** la extensión frena el envío y muestra el motivo del servidor (no un texto inventado por la extensión).
2. **Given** una respuesta de fallo del gateway **sin** indicación de bloqueo por política, **When** el usuario intenta enviar, **Then** la extensión frena el envío y muestra "servicio no disponible".
3. **Given** cualquier respuesta de bloqueo, **When** la extensión la muestra, **Then** nunca expone identificadores internos crudos de la capa que bloqueó.

---

### User Story 6 - La sesión distingue "sin red" de "sin permiso" y se revalida sola (Priority: P1) · MUST-piloto

Con una API key por usuario y sin gestión centralizada de dispositivos, la revocación de una plaza (dar de baja a alguien) es el único mecanismo de offboarding. La extensión debe reaccionar a una key revocada desconectando al usuario, y debe distinguir un corte de red (no borra la key) de una revocación de permiso (borra la key).

**Why this priority**: Hoy la extensión solo reacciona a "key inválida" y no a "plaza revocada" → un usuario dado de baja queda conectado para siempre. Simétricamente, un corte de red lo desloguea y le hace re-ingresar la key sin motivo. En un piloto de 25 plazas, el offboarding tiene que funcionar.

**Independent Test**: Con la extensión conectada, simular por separado: (a) corte de red, (b) key inválida, (c) plaza revocada; verificar tres estados distinguibles con mensajes distintos, y que solo (b) y (c) borran la key.

**Acceptance Scenarios**:

1. **Given** la extensión conectada, **When** ocurre un corte de red, **Then** pasa a estado "no verificado" con la key conservada, y se recupera sola cuando vuelve la red.
2. **Given** la extensión conectada, **When** la plaza del usuario fue revocada, **Then** pasa a "desconectado", borra la key y muestra un mensaje distinto al de "key inválida" (algo como "tu plaza ya no está activa").
3. **Given** la extensión conectada, **When** pasa el tiempo, **Then** la sesión se revalida periódicamente (del orden de media hora) y al reabrir el navegador, sin intervención del usuario.
4. **Given** la extensión abierta en varias pestañas, **When** cambia el estado de sesión, **Then** hay un único componente responsable de ese estado (no se pisan entre pestañas).

---

### User Story 7 - Gate de release que ve la extensión (Priority: P2) · SHOULD

El proceso de release debe fallar si un paquete de la extensión reintroduce la marca del fabricante, para que la limpieza de la US2 no se re-ensucie en el próximo cambio.

**Why this priority**: Sin un gate automático, el white-label de la extensión es una limpieza puntual que se degrada. Importa antes del segundo partner, no bloquea el primer install.

**Independent Test**: Introducir a propósito la marca del fabricante en un paquete generado y verificar que el gate de release lo marca en rojo.

**Acceptance Scenarios**:

1. **Given** un paquete generado para un partner, **When** corre el gate de white-label del release, **Then** falla si el paquete contiene la marca del fabricante o nombres de internals, además de los nombres ya prohibidos del motor.
2. **Given** un paquete limpio, **When** corre el gate, **Then** pasa.

---

### User Story 8 - El backend rechaza keys vencidas y de otra superficie (Priority: P2) · SHOULD

El gateway debe rechazar una key vencida y una key que no sea de superficie de navegador, para que el offboarding por expiración funcione y una key de otra herramienta no abra la superficie del navegador.

**Why this priority**: Con key por usuario y plazas limitadas, una key que ignora su fecha de expiración rompe el offboarding por vencimiento. Y una key de otra herramienta accediendo a la superficie del navegador es una confusión de superficie que ensucia la auditoría. Endurecimiento del servidor; no bloquea el primer install pero lo respalda.

**Independent Test**: Con una key vencida y con una key de otra superficie, verificar que ambas son rechazadas con el mismo error indistinguible, sin revelar cuál de las dos condiciones falló.

**Acceptance Scenarios**:

1. **Given** una key vencida, **When** se usa contra la superficie de navegador, **Then** es rechazada con el mismo error genérico que una key inválida (sin oráculo que distinga vencida de inexistente).
2. **Given** una key cuya herramienta no es de superficie navegador, **When** se usa contra la superficie de navegador, **Then** es rechazada.

---

### Edge Cases

- **Gateway inaccesible al generar el paquete**: la generación no depende de que el gateway esté vivo; solo hornea la URL. La verificación de conectividad es responsabilidad del usuario al conectar, no del build.
- **URL de gateway local (`localhost`)**: permitida sin `https` (entorno de desarrollo/demo); solo se exige `https` para URLs remotas.
- **Respuesta del servidor sin el bloque de protección** (backend anterior a esta feature): la extensión degrada a la promesa más chica ("patrones"), nunca asume análisis lingüístico.
- **Adapter que deja de matchear** (el sitio del proveedor cambió su ruta interna): fuera del alcance del piloto detectarlo automáticamente (ver Supuestos, diferido); el comportamiento ante un request identificado que no se puede inspeccionar sigue siendo fail-closed (frenar, no dejar pasar en claro).
- **Key ingresada antes de validar**: no se persiste ni se re-inyecta hasta validarse contra el gateway (ya resuelto en el hardening previo; no reintroducir).

## Requirements *(mandatory)*

### Functional Requirements

**Generación y marca del paquete (US1, US3)**

- **FR-001**: El sistema MUST generar el paquete instalable de la extensión de un partner a partir de su marca, sin edición manual de archivos, horneando **solo la identidad del partner** (marca + identificador estable) y **ninguna** dirección de gateway.
- **FR-002**: El paquete generado MUST tomar de la marca del partner el nombre visible, la descripción y los íconos.
- **FR-003**: El paquete generado MUST tener una identidad estable e independiente de la carpeta donde se instale.
- **FR-004**: El paquete MUST poder generarse en tiempo de partner (la marca se conoce temprano), sin depender de conocer la URL de ningún cliente ni de que un cliente haya desplegado.
- **FR-005**: El entregable de instalación MUST incluir el paquete de la extensión y listarlo en su manifiesto con su checksum.
- **FR-006**: El paquete generado para un partner MUST NOT contener, en ningún texto visible ni recurso, la marca del fabricante, el término "PoC", el nombre del motor de detección ni una dirección de desarrollo.
- **FR-007**: El número de versión del paquete MUST tener una única fuente de verdad.

**Conexión configurada por el usuario (US2)**

- **FR-008**: El usuario MUST poder configurar la extensión con la dirección de su gateway y su API key; la dirección MUST ser editable, con un valor por defecto opcional pre-cargado (nunca fija).
- **FR-009**: Al conectar a un host de gateway, la extensión MUST obtener permiso de acceso a ese host en tiempo de ejecución (no depender de un host fijo horneado); cambiar a otro host MUST volver a solicitar permiso.
- **FR-010**: La extensión MUST rechazar una URL de gateway remota que no sea segura (`https`), permitiendo `http` solo para entornos locales.
- **FR-011**: Si el usuario no concede el permiso de acceso al host, la extensión MUST mostrar un mensaje claro (no fallar en silencio).
- **FR-012**: La extensión MUST conectar al gateway sin requerir configuración de CORS en el servidor (la comunicación la realiza el componente de la extensión que tiene permiso de host, no la página interceptada).

**Honestidad de protección (US4)**

- **FR-013**: El sistema MUST exponer, para la superficie de navegador, una declaración de nivel de protección que indique detección "por patrones" y un texto de alcance en lenguaje llano.
- **FR-014**: La interfaz de la extensión MUST mostrar ese nivel como un indicador ámbar ("cobertura parcial"), no verde, y sin la palabra "protegido".
- **FR-015**: Cuando el servidor no informe el nivel de protección, la extensión MUST asumir el nivel más conservador ("patrones").
- **FR-016**: El texto de alcance MUST provenir del servidor (fuente única de copy), NOT estar hardcodeado en la extensión, de modo que el día que la superficie use análisis lingüístico el mensaje cambie sin re-empaquetar.
- **FR-017**: El vocabulario del nivel de detección expuesto al usuario MUST NOT contener nombres de motor ni de tecnología.

**Bloqueos de gobernanza (US5)**

- **FR-018**: Ante una respuesta de bloqueo por política, la extensión MUST frenar el envío y mostrar el motivo provisto por el servidor.
- **FR-019**: Ante una respuesta de fallo sin indicación de bloqueo por política, la extensión MUST mostrar "servicio no disponible".
- **FR-020**: La extensión MUST NOT exponer identificadores internos crudos de la capa que bloqueó.

**Sesión y revocación (US6)**

- **FR-021**: La extensión MUST distinguir tres estados: conectado, no verificado (fallo de red, key conservada) y desconectado (permiso denegado, key borrada).
- **FR-022**: La extensión MUST tratar una revocación de plaza como estado distinto de una key inválida, con un mensaje propio, y borrar la key en ambos casos.
- **FR-023**: Un corte de red MUST NOT borrar la key.
- **FR-024**: La extensión MUST revalidar la sesión periódicamente (del orden de media hora) y al reabrir el navegador.
- **FR-025**: El estado de sesión MUST tener un único componente responsable.

**Endurecimiento del servidor (US7, US8)**

- **FR-026**: El proceso de release MUST fallar cuando un paquete generado contiene la marca del fabricante o nombres de internals (además de los nombres de motor ya prohibidos).
- **FR-027**: El gateway MUST rechazar una key vencida con el mismo error indistinguible que una key inexistente.
- **FR-028**: El gateway MUST rechazar, en la superficie de navegador, una key cuya herramienta no sea de superficie navegador.

### Key Entities *(include if feature involves data)*

- **Paquete de extensión del partner**: el artefacto instalable generado para un partner; deriva su identidad visible (nombre, descripción, íconos, identificador estable) de la marca del partner. NO contiene la dirección del gateway.
- **Marca del partner (brand-pack)**: la fuente de verdad de la identidad visible de un partner; ya usada para el sitio de documentación y el frontend, ahora también para la extensión.
- **Conexión del usuario**: la dirección del gateway y la API key que el usuario ingresa; la dirección es editable y agnóstica al despliegue, con un valor por defecto opcional; el acceso al host del gateway se concede en tiempo de ejecución.
- **Declaración de nivel de protección**: el dato, producido por el servidor para la superficie de navegador, que describe cómo detecta datos personales ("patrones") y su alcance en lenguaje llano; incluye qué capas quedan delegadas.
- **Motivo de bloqueo**: el texto, provisto por el servidor, que explica por qué un envío fue frenado por política.
- **Estado de sesión**: conectado / no verificado / desconectado, con un único dueño en la extensión.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un operador genera el paquete de un partner desde su marca en un solo comando, sin editar ningún archivo del paquete a mano y sin necesitar la URL de ningún cliente.
- **SC-001b**: La misma extensión instalada conecta a dos gateways distintos con solo cambiar la URL (agnóstica al despliegue), concediendo el permiso de host que pide el navegador.
- **SC-002**: El 100% de los paquetes generados para un partner están libres de la marca del fabricante y nombres de internals, verificado automáticamente por el gate de release.
- **SC-003**: El entregable de instalación incluye el paquete de la extensión; el instalador (JF) puede repartirlo al IT del cliente sin pasos manuales adicionales de armado.
- **SC-004**: Ante un bloqueo de política, el 100% de los casos muestran el motivo real y 0% se muestran como "servicio no disponible".
- **SC-005**: Una plaza revocada desconecta la extensión en la siguiente revalidación (≤ ~30 min) sin intervención del usuario; un corte de red no obliga a re-ingresar la key al volver la conexión.
- **SC-006**: El usuario nunca ve un indicador "protegido" verde en la superficie de navegador; ve el nivel real ("detección por patrones · cobertura parcial").

## Assumptions

- **Superficies del piloto**: la extensión intercepta **Claude y ChatGPT** en el navegador (ya funcionando). **Gemini queda explícitamente fuera de alcance de esta feature** y se aborda como fast-follow post-piloto (adapter nuevo + telemetría de superficie sin tráfico), por decisión de producto de JF.
- **Decisiones de owner ya cerradas (no se re-litigan en esta spec)**: API key por usuario (el admin la emite); los partners rebrandean (no hay una ficha neutra única); sin gestión centralizada de dispositivos (instalación manual o zip a IT); la key es un setup de una vez que no se vuelve a mostrar ("es un login"); la protección PII no es desactivable por el usuario; la superficie de navegador detecta por patrones, no por análisis lingüístico (aceptado en PR #21).
- **Modelo de conexión (decisión de JF, 2026-07-24 — revierte dos puntos del brief #46)**: la dirección del gateway la ingresa el **usuario** (editable, agnóstica, con default opcional), NO viene horneada en el paquete → el brief decía "gateway no editable / horneado", se revierte. Para que una URL editable funcione de verdad en el navegador (hoy es "libertad falsa": el host está clavado y el navegador bloquea el resto), el acceso al host se concede en tiempo de ejecución vía permiso de host opcional → el brief decía "no usar permisos de host opcionales", se revierte. Fundamento técnico: el componente de la extensión que habla con el gateway tiene permiso de host, así que no hay CORS; el único portón es ese permiso. No hace falta ningún microservicio ni proxy del lado servidor.
- **Hardening previo ya hecho (no rehacer)**: la fuga del mapa reversible de PII a la página, el puente abierto a mensajes de la página y la escritura de PII en el título fueron cerrados en la feature previa (issue #44 / PR #45); un rebase no debe reintroducirlos.
- **Diferido a otras specs / fast-follow**: superficie canónica de navegador en el catálogo de superficies del servidor y su migración de datos (requiere coordinación con el dueño del módulo de seguridad antes del congelamiento de la 027); telemetría de adapter que dejó de matchear; límites de tasa por key. No bloquean el install del piloto.
- **Distribución**: para el piloto se acepta la instalación manual (carga del paquete) o entrega del paquete al IT del cliente; un listado en la tienda del navegador por partner queda como salida futura.
- **Dependencia de la 027**: el motivo real de bloqueo (US5) se apoya en el contrato de bloqueo de la gobernanza (027), ya disponible en la rama de integración de trabajo; no requiere esperar a un merge externo.
- **Higiene de seguridad (acción humana, no código)**: si una key real que estuvo expuesta en documentación borrada sigue viva en alguna base, debe revocarse.
