# Feature Specification: Aislamiento por usuario, atribución de gasto y enmascarado determinista (motor + backend + instalador)

**Feature Branch**: `043-aislamiento-atribucion-motor`

**Created**: 2026-09-08

**Status**: 🟢 **67/69 tareas hechas y verificadas contra Postgres real** (0 regresiones — suite
completa 2734 passed). Las 3 restantes (docs de producto pendiente de la sección de conceptos de
motor, `quickstart.md` en vivo, publicación de imágenes) están bloqueadas por infraestructura real
no disponible en el entorno de desarrollo — ver
[CHANGELOG.md](CHANGELOG.md) y
[../VERIFICACION-043-044-pruebas.md](../VERIFICACION-043-044-pruebas.md).

**Repos que toca**: `cluna-8/elea` (`backend/`, `litellm/extensions/`), `cluna-8/elea-installer`.
**NO toca** `frontend/` ni `client/` — todo lo de cara al usuario vive en la spec hermana
[044-hub-chat-panel-admin](../044-hub-chat-panel-admin/spec.md). Esta spec **publica los contratos**
que la 044 consume (sección "Contratos hacia la 044").

**Input**: Dos mails de Tomás Mc Nally (Elea, 03-sep y 07-sep-2026) tras validar la spec 042:

> (07-sep, prioritario) "La memoria de chats es compartida. Los usuarios cada vez que registro uno
> nuevo pueden ver todo el historial de chat de usuarios previos." "No se puede realizar edición de
> roles de usuarios ni eliminar usuarios, ni editar mails." "Aparece en modelos: license y chat-ui."
> "Aparece en usuarios: anythingllm-provider y rag-masking." "No aparece nada asociado a mi usuario
> con el que estuve probando, por lo que no puedo evaluar costos."
>
> (03-sep) "El enmascaramiento no parece ser determinista: el nombre Julián se enmascara de forma
> diferente [en distintas filas del mismo CSV], lo cual hace que el modelo no pueda relacionar
> ambos." "El almacenamiento del csv parece haberse hecho dentro de una Base Vectorial con Chunks,
> lo que hace que no se pueda aplicar un análisis cruzando filas/columnas."

Decisiones del dueño del producto (08-sep, esta sesión): (1) dos specs, motor+backend / UIs;
(2) modelo de aislamiento = **espacios con miembros** (dueño + miembros, hilos privados por
usuario dentro del espacio); (3) enmascarado determinista **por documento**, sin seudónimo
estable entre documentos.

## Diagnóstico verificado en código (08-sep)

Resumen de las causas raíz, con la evidencia; el detalle (file:line) queda en `plan.md`.

| # | Síntoma reportado | Causa raíz confirmada |
|---|---|---|
| 1 | Memoria de chats compartida | **Nunca existió aislamiento.** El Hub Chat habla con el motor de documentos con una sola credencial de servicio global; ningún componente (backend, motor de documentos, cliente) sabe qué espacio o hilo pertenece a quién. Peor que lo reportado: ~10 endpoints de espacios/hilos/historial del Hub **no exigen sesión**, así que el historial es legible y borrable por anónimos que alcancen el puerto. |
| 2 | Enmascarado no determinista | El placeholder es `[TIPO_índice_nonce]` con un **nonce aleatorio por request** y contadores que arrancan en 0 por request. El cliente envía **un request por trozo de 4.000 caracteres**, así que "Julián" recibe un token distinto en cada trozo. Dentro de un mismo request sí es estable. El constructor del mapa ya acepta un `nonce` externo que nadie pasa. Riesgo adicional independiente: la detección de nombres por NLP depende del contexto de la fila; en CSV puede detectar "Julián" en unas filas y en otras no (esas filas irían en claro). |
| 3 | `license` y `chat-ui` como "modelos" | La columna `model` de la auditoría está sobrecargada con tres taxonomías: modelos reales, **superficies** (`chat-ui` — el endpoint de enmascarado audita la superficie de la llave en el campo modelo; el instalador dio `tool_type: chat-ui` a las llaves de servicio) y **marcas de evidencia** (`license`, filas de la cadena de licencias). Las vitrinas de compliance/reports sí las excluyen; las dos de costos (`top_models`, desglose por modelo) no. |
| 4 | `anythingllm-provider` y `rag-masking` como "usuarios" | Son las dos **cuentas de servicio** que crea el instalador (`svc.anythingllm-provider`, `svc.rag-masking`) con sus llaves. El listado de usuarios devuelve todos sin distinguir tipo; no existe atributo de "cuenta de servicio". Consumen además asientos de licencia. |
| 5 | Sin costos por usuario | El Hub Chat es un **proxy con credenciales compartidas**: el enmascarado usa la llave de servicio `rag-masking`; el chat RAG usa la llave de proveedor del motor de documentos (`anythingllm-provider`). Ningún camino lleva la identidad del usuario final aguas abajo; el modelo de datos no tiene concepto de "usuario final" separado del dueño de la llave. Solo el chat directo (sin espacio) atribuye bien. El presupuesto del usuario se **muestra** pero **no se aplica** en el camino RAG. |
| 6 | Edición/baja de usuarios | El backend ya permite editar rol/email/grupo (PUT de reemplazo completo) pero **no existe endpoint de baja**; solo baja lógica vía `is_active`. |
| 7 | Branding | Errores del motor se sanitizan solo en el plano del chat interno, no en el plano `/gw`; el campo público `litellm_params` viaja en la API y el OpenAPI; el guardián NLP se siembra con nombre "(Presidio)"; los logs del contenedor `engine` muestran el banner del motor cuando el instalador pide `docker compose logs engine`. |

**Fuera de alcance explícito**: cruces exactos fila/columna sobre CSV/Excel (punto 2 del mail del
03-sep). Es un motor de cómputo nuevo (texto→SQL), ya descartado para esta ronda por decisión del
usuario el 31-ago y documentado en la spec 041 (US5). Se le responde al cliente que el RAG es
semántico por diseño y que el cruce exacto es una pieza aparte.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Espacios de trabajo con miembros (Priority: P1)

Un administrador (o el dueño de un espacio) define quiénes son miembros de cada espacio de
trabajo. Un usuario solo puede ver, consultar y operar los espacios de los que es miembro. Dentro
de un espacio, los hilos de conversación son privados de quien los creó. El sistema (no el cliente
web) es la autoridad de esa pertenencia: cualquier operación sobre un espacio o hilo se verifica
contra ella, aunque el pedido venga con la credencial de servicio.

**Why this priority**: es el bug prioritario del cliente y es una fuga de datos entre personas.
Sin esto, el piloto no puede abrirse a más usuarios.

**Independent Test**: crear dos usuarios A y B; A crea el espacio "Contabilidad" y sube un
documento; B no lo ve en su listado ni puede leer su historial ni sus documentos aunque conozca el
identificador del espacio; el admin agrega a B como miembro → B lo ve, pregunta sobre el documento,
y sus hilos no aparecen a A ni los de A a B.

**Acceptance Scenarios**:

1. **Given** un usuario sin pertenencia a ningún espacio, **When** lista espacios, **Then** recibe una lista vacía (no el espacio de otro).
2. **Given** un usuario que conoce el identificador de un espacio ajeno, **When** pide su historial, sus documentos, o intenta chatear, borrar o cambiar ajustes, **Then** el sistema lo rechaza con "sin acceso" y registra el intento en auditoría.
3. **Given** un espacio con miembros A y B, **When** A crea un hilo y conversa, **Then** B no ve ese hilo ni sus mensajes; el hilo principal del espacio también es por usuario.
4. **Given** el admin quita a B de un espacio, **When** B vuelve a listar, **Then** el espacio ya no aparece y sus hilos quedan inaccesibles para él (no se borran).
5. **Given** la instalación existente del cliente con 3 espacios reales creados antes de esta feature, **When** se actualiza, **Then** ninguno se pierde: quedan asignados al administrador como dueño y sin miembros hasta que el admin los asigne (pantalla de "espacios sin asignar" en la 044).
6. **Given** un usuario dado de baja, **When** intenta cualquier operación, **Then** es rechazado; sus espacios propios pasan a "sin asignar" para reasignación.

---

### User Story 2 - Cada pedido queda atribuido al usuario que lo hizo, y su presupuesto se aplica (Priority: P1)

Todo consumo que un usuario genera desde el Hub Chat (enmascarar un documento, preguntar en un
espacio, chatear sin espacio) queda registrado a **su** nombre en la auditoría y en las vistas de
costos, no al de una cuenta de servicio. Si el usuario agotó su presupuesto, el pedido se rechaza
**antes** de consumir, con un mensaje claro; el gasto real de cada respuesta se descuenta de su
presupuesto (y del de su grupo). Las cuentas de servicio siguen existiendo pero dejan de acumular
gasto de personas.

**Why this priority**: el cliente no puede evaluar costos (objetivo explícito del piloto) y el
control de presupuesto —propuesta de valor del producto— hoy no frena nada en el camino RAG.

**Independent Test**: con el usuario de prueba con presupuesto de $1, subir un documento y hacer
tres preguntas en un espacio; la vista de costos del admin muestra esas operaciones bajo ese
usuario con costo > 0 para las preguntas; al superar $1, la cuarta pregunta devuelve "presupuesto
agotado" sin llegar al proveedor; la auditoría no muestra ese gasto bajo `svc.*`.

**Acceptance Scenarios**:

1. **Given** un usuario con presupuesto vigente, **When** pregunta en un espacio, **Then** aparece una fila de auditoría con su identidad, el modelo real usado, tokens y costo > 0, y su gasto acumulado sube en esa cantidad.
2. **Given** un usuario con presupuesto agotado, **When** intenta preguntar (con o sin espacio) o subir un documento, **Then** recibe rechazo 402 con copy neutro y no se genera consumo en el proveedor.
3. **Given** un pedido que llega con una identidad de usuario final que no coincide con la sesión autenticada que lo origina, **When** el sistema lo valida, **Then** lo rechaza (la identidad de usuario final nunca se acepta a ciegas desde el cuerpo del pedido).
4. **Given** el enmascarado de un documento de 150 KB (≈38 trozos), **When** se audita, **Then** se registra como **una** operación de enmascarado atribuida al usuario (no 38 filas con "modelo" `chat-ui`), con el conteo de entidades agregado.
5. **Given** un pedido hecho por una cuenta de servicio en nombre de nadie (p. ej. embeddings de fondo), **When** se audita, **Then** queda bajo la cuenta de servicio, sin costo humano, y no aparece en los rankings de usuarios.

---

### User Story 3 - Enmascarado determinista por documento (Priority: P1)

Cuando un documento se enmascara en varios trozos, el mismo valor (p. ej. "Julián", un DNI, un
CBU) recibe **el mismo placeholder en todo el documento**, de modo que el modelo puede relacionar
todas sus apariciones. Dos documentos distintos siguen recibiendo placeholders distintos para el
mismo valor (no se crea un seudónimo estable entre documentos: el perfil de privacidad queda igual
que hoy). El desenmascarado en la respuesta sigue funcionando.

**Why this priority**: es el segundo bug reportado y afecta directamente la calidad de las
respuestas sobre CSV, el caso de uso central del piloto.

**Independent Test**: subir el CSV real del cliente donde "Julián" aparece en N filas repartidas
en más de un trozo; inspeccionar el texto enmascarado que se indexa: hay exactamente un placeholder
para "Julián" en todo el documento; preguntar "¿qué registros tiene Julián?" devuelve las N filas y
la respuesta muestra "Julián" (desenmascarado); subir el mismo CSV de nuevo produce un placeholder
distinto.

**Acceptance Scenarios**:

1. **Given** un documento con el mismo valor en trozos distintos, **When** se enmascara, **Then** todas las ocurrencias comparten placeholder y el conteo de entidades del documento cuenta cada valor distinto una vez.
2. **Given** dos documentos con el mismo valor, **When** se enmascaran, **Then** sus placeholders difieren.
3. **Given** un placeholder emitido bajo este esquema, **When** el modelo lo cita en la respuesta, **Then** se desenmascara al valor real (compatibilidad con la bóveda de la spec 042 y con el streaming del motor).
4. **Given** un cliente que llama al enmascarado sin indicar documento (p. ej. la extensión de navegador), **When** enmascara, **Then** el comportamiento es el actual (nonce por request), sin regresión.
5. **Given** un nombre que el NLP detecta en unas filas y no en otras del mismo CSV, **When** el admin lo registra en la lista de nombres protegidos del despliegue, **Then** se enmascara en todas las filas (mitigación existente; se documenta y se prueba, no se rediseña el detector en esta spec).

---

### User Story 4 - Vistas de modelos y costos sin ruido de servicio (Priority: P2)

El admin ve en "modelos" únicamente modelos de IA reales, y en "usuarios" únicamente personas.
Las cuentas de servicio existen, se pueden ver bajo demanda en una sección propia, no consumen
asientos de licencia y no aparecen en rankings de consumo. Las filas de evidencia (licencia) y de
superficie (enmascarado, chat interno) dejan de contarse como modelos.

**Why this priority**: confunde al cliente y erosiona la confianza en los números, pero no filtra
datos.

**Independent Test**: en una instalación limpia con las dos cuentas de servicio y un usuario humano,
el listado de usuarios devuelve 1 (y 3 con "incluir cuentas de servicio"); "modelos con consumo"
lista solo los deployments reales; el conteo de asientos es 1.

**Acceptance Scenarios**:

1. **Given** filas de auditoría de licencia, enmascarado y chat interno, **When** el admin consulta desglose por modelo o top de modelos, **Then** ninguna de esas filas aparece como modelo.
2. **Given** las cuentas de servicio del instalador, **When** se listan usuarios, **Then** por defecto no aparecen; con un filtro explícito sí, marcadas como "cuenta de servicio".
3. **Given** un límite de asientos de licencia, **When** se cuentan, **Then** las cuentas de servicio no se cuentan.
4. **Given** una instalación existente, **When** se actualiza, **Then** las dos cuentas de servicio ya creadas quedan marcadas como tales sin intervención manual.

---

### User Story 5 - Gestión completa del ciclo de vida de usuarios (Priority: P2)

Un admin puede cambiar el rol, el email, el nombre visible y el equipo de un usuario sin reenviar
todo el objeto; puede desactivar y reactivar; y puede dar de baja definitivamente a un usuario
(con sus llaves revocadas), conservando la auditoría histórica atribuida a él.

**Why this priority**: pedido explícito del cliente; hoy el backend cubre la edición pero no la
baja, y la 044 necesita el contrato.

**Independent Test**: crear un usuario, cambiarle solo el rol, luego solo el email, desactivarlo
(no puede loguear), reactivarlo, darlo de baja (no puede loguear, sus llaves ya no autentican, su
auditoría sigue visible bajo su nombre).

**Acceptance Scenarios**:

1. **Given** un usuario existente, **When** el admin cambia un solo atributo, **Then** el resto no cambia y el cambio de rol queda en auditoría.
2. **Given** un admin que intenta bajarse a sí mismo o al último admin activo, **When** lo intenta, **Then** el sistema lo impide.
3. **Given** un usuario dado de baja, **When** alguien intenta autenticar con sus llaves o credenciales, **Then** es rechazado; sus filas de auditoría conservan su identidad.
4. **Given** un email o nombre de usuario ya usado en el mismo tenant, **When** se intenta asignar a otro, **Then** se rechaza con mensaje claro.

---

### User Story 6 - Ningún nombre de motor ni proveedor de cara al cliente (Priority: P2)

Ni el usuario final, ni el admin, ni el operador que instala ven nombres de motor, de proveedor
NLP ni de motor de documentos en la API pública, los mensajes de error, la documentación
generada de la API, los nombres sembrados en la base ni la salida que el instalador les pide leer.
Se verifica con una prueba automática que falla si reaparecen.

**Why this priority**: es principio VII de la constitución del producto y pedido explícito del
dueño; hoy la sanitización es parcial.

**Independent Test**: una prueba automática recorre las respuestas de la API pública, la
documentación OpenAPI generada, los nombres sembrados de guardianes/políticas y los mensajes de
error de los dos planos (chat interno y `/gw`) buscando los términos prohibidos, con lista de
excepciones explícita y vacía por defecto para lo visible.

**Acceptance Scenarios**:

1. **Given** un error del motor en el plano `/gw` (p. ej. proveedor caído, modelo inexistente), **When** llega al cliente, **Then** el texto no contiene el nombre del motor ni del proveedor y sí un mensaje neutro accionable.
2. **Given** la documentación generada de la API, **When** se inspecciona, **Then** ningún campo público lleva nombre de motor (el campo de parámetros de modelo se llama de forma neutra, con compatibilidad hacia atrás para el nombre anterior durante una versión).
3. **Given** una instalación nueva, **When** se siembra el guardián de detección NLP, **Then** su nombre visible es neutro; en una instalación existente el nombre se actualiza.
4. **Given** un operador que sigue el instalador, **When** este le indica cómo ver logs o diagnosticar, **Then** el comando sugerido devuelve salida sin banner ni prefijos del motor.

### Edge Cases

- Un usuario miembro de un espacio es dado de baja mientras tiene hilos activos: los hilos se conservan (auditoría) pero dejan de ser accesibles para todos salvo exportación por admin.
- El dueño de un espacio es dado de baja: el espacio pasa a "sin asignar" y lo hereda el admin.
- Dos trozos del mismo documento se enmascaran concurrentemente: el resultado debe ser el mismo que en secuencia (no debe depender del orden de llegada).
- Un documento se reenvía por reintento (fallo de red a mitad de la subida): reutilizar el mismo identificador de documento da los mismos placeholders; uno nuevo da otros. Ambos válidos, el cliente decide.
- Un placeholder colisiona entre dos valores distintos del mismo documento: el sistema detecta la colisión y acuña otro token; nunca devuelve el dato de otra persona.
- El almacén de la bóveda no responde durante el enmascarado: se enmascara igual, se registra la degradación, el desenmascarado posterior puede no resolver (comportamiento actual, documentado).
- El presupuesto se agota a mitad de una respuesta: se completa esa respuesta y se rechaza la siguiente (enforcement post-hoc, principio V; no se promete corte en tiempo real).
- La identidad de usuario final llega en un pedido de una llave que no es de servicio: se ignora y se audita el intento (solo las llaves de servicio autorizadas pueden actuar "en nombre de").
- Instalación existente con auditoría previa bajo `svc.*`: no se reescribe el histórico; se documenta el corte de fecha a partir del cual los números por usuario son fiables.

## Requirements *(mandatory)*

### Functional Requirements

**Aislamiento (US1)**

- **FR-001**: El sistema MUST mantener, como fuente de verdad, la relación entre espacios de trabajo y usuarios: dueño, miembros, tenant, y fecha de alta/baja de cada membresía.
- **FR-002**: El sistema MUST exponer operaciones para: listar los espacios visibles para un usuario, consultar si un usuario tiene acceso a un espacio, agregar/quitar miembros y transferir el dueño; solo admins y el dueño del espacio pueden modificar membresías.
- **FR-003**: El sistema MUST registrar a qué usuario pertenece cada hilo de conversación de un espacio y rechazar el acceso a hilos ajenos, incluso para otros miembros del mismo espacio.
- **FR-004**: Toda operación de espacio/hilo/documento realizada "en nombre de" un usuario MUST verificarse contra FR-001/FR-003 en el sistema, no solo en el cliente web.
- **FR-005**: Los intentos de acceso rechazados MUST quedar en auditoría con la identidad del solicitante y el recurso, sin contenido.
- **FR-006**: La actualización de una instalación existente MUST conservar todos los espacios, documentos e hilos, asignándolos a un estado "sin asignar / dueño admin" hasta que se asignen miembros.
- **FR-007**: El instalador (`elea-installer`) MUST provisionar lo necesario para que el aislamiento funcione desde una instalación limpia sin pasos manuales, y MUST fijar la versión del motor de documentos (hoy `latest` sin pin).

**Atribución y presupuesto (US2)**

- **FR-010**: El sistema MUST aceptar, en los pedidos hechos por llaves de servicio autorizadas, la identidad del usuario final en cuyo nombre se actúa, y MUST validarla (nunca aceptarla a ciegas desde el cuerpo del pedido).
- **FR-011**: Cada fila de auditoría MUST distinguir "quién autenticó" (llave/cuenta de servicio) de "en nombre de quién" (usuario final); las vistas de costos y consumo MUST agrupar por usuario final cuando exista.
- **FR-012**: El presupuesto del usuario final (y de su grupo) MUST evaluarse antes de cada pedido con consumo y rechazar con 402 y copy neutro cuando esté agotado; el costo real de cada respuesta MUST descontarse del usuario final.
- **FR-013**: El enmascarado de un documento en varios trozos MUST auditarse como una operación por documento, con las entidades agregadas, sin costo de proveedor y sin ocupar la columna de modelo.
- **FR-014**: Las llaves de servicio del instalador MUST tener una superficie propia ("servicio"), no la del chat interno.
- **FR-015**: El sistema MUST ofrecer a la 044 un modo de consulta del presupuesto y consumo **propio** del usuario autenticado (autoservicio), para que el Hub Chat no necesite una sesión de admin para mostrarlo.

**Enmascarado (US3)**

- **FR-020**: El enmascarado MUST aceptar un identificador de documento opcional; con el mismo identificador, el mismo valor MUST recibir el mismo placeholder en todos los trozos, y valores distintos placeholders distintos.
- **FR-021**: Sin identificador, el comportamiento MUST ser el actual (sin regresión para otros clientes del despliegue compartido Guardian).
- **FR-022**: El placeholder MUST conservar la gramática vigente `[TIPO_n_hex]` para que el desenmascarado, la bóveda, el conteo por tipo y el streaming sigan funcionando sin cambios.
- **FR-023**: Dos documentos distintos MUST NOT compartir placeholders para el mismo valor (no se introduce seudónimo estable entre documentos; no cambia la Constitución I).
- **FR-024**: El identificador de documento MUST ser efímero y no derivable del contenido; MUST NOT persistirse junto con valores en claro más allá de lo que hoy ya hace la bóveda.
- **FR-025**: La lista de nombres protegidos del despliegue MUST estar documentada como mitigación para la detección inconsistente en CSV, con prueba que lo verifique.

**Vistas y cuentas de servicio (US4)**

- **FR-030**: Cada usuario MUST tener un tipo de cuenta (`persona` | `servicio`); el instalador MUST marcar las suyas como `servicio`; la actualización MUST marcar retroactivamente las existentes.
- **FR-031**: El listado de usuarios MUST excluir cuentas de servicio por defecto y permitir incluirlas explícitamente; los conteos de usuarios activos, rankings de consumo y asientos de licencia MUST excluirlas.
- **FR-032**: La auditoría MUST separar "modelo" de "superficie" y de "tipo de evento" (evidencia de licencia); toda consulta de "modelos" MUST devolver únicamente modelos reales.

**Usuarios (US5)**

- **FR-040**: El sistema MUST permitir actualización parcial de usuario (rol, email, nombre visible, equipo, estado) con validación de unicidad por tenant y auditoría del cambio de rol.
- **FR-041**: El sistema MUST permitir dar de baja a un usuario: revoca sus llaves y sesiones, impide autenticar, conserva la auditoría y libera su asiento; MUST impedir la baja del último admin activo y la auto-baja.
- **FR-042**: La baja MUST propagarse al aislamiento (FR-001/003: membresías cerradas, espacios propios a "sin asignar").

**Branding (US6)**

- **FR-050**: Los mensajes de error de los dos planos (chat interno y `/gw`) MUST sanitizarse con el mismo mecanismo, sin nombres de motor ni proveedor.
- **FR-051**: Ningún campo público de la API ni de la documentación generada MUST llevar nombre de motor; se MUST mantener compatibilidad hacia atrás para el nombre anterior durante al menos una versión.
- **FR-052**: Los nombres sembrados de guardianes/políticas MUST ser neutros; la actualización MUST renombrar los existentes.
- **FR-053**: El instalador MUST ofrecer un comando propio para ver logs y diagnóstico cuya salida no muestre banner ni prefijos del motor.
- **FR-054**: Una prueba automática MUST fallar si reaparece cualquier término prohibido (motor, proveedor NLP, motor de documentos, proveedores de modelos) en superficies visibles, con lista de excepciones explícita.

### Key Entities

- **Espacio de trabajo (Workspace)**: espacio de documentos e hilos; tiene tenant, dueño, miembros, identificador externo en el motor de documentos, estado (activo / sin asignar).
- **Membresía**: relación usuario↔espacio con rol (dueño | miembro) y fechas.
- **Hilo**: conversación dentro de un espacio; pertenece a exactamente un usuario.
- **Usuario**: ya existe; gana `tipo de cuenta` (persona | servicio) y estado de baja.
- **Registro de auditoría**: ya existe; gana `usuario final` (en nombre de quién), `superficie` separada de `modelo`, y `tipo de evento`.
- **Operación de enmascarado de documento**: agrupa los trozos de un documento; identificador efímero, entidades agregadas, usuario final.

## Contratos hacia la 044 (lo que esta spec publica)

1. Operaciones de espacios/membresías/hilos con verificación de acceso (US1).
2. Modo "en nombre de" para llaves de servicio + autoservicio de presupuesto/consumo (US2).
3. Identificador de documento en el enmascarado (US3).
4. Filtro/tipo de cuenta en usuarios; separación modelo/superficie en costos (US4).
5. Actualización parcial y baja de usuarios (US5).
6. Nombres neutros y mecanismo de sanitización reutilizable (US6).

La 044 no puede cerrar sus historias P1 sin 1, 2 y 3. Orden de entrega sugerido: US1 y US3
primero (fugas), US2 después (números), US4-6 en paralelo.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Con dos usuarios y un espacio de cada uno, 0 de 20 intentos cruzados (listar, leer historial, chatear, borrar, cambiar ajustes, con y sin sesión) accede al espacio o hilo ajeno.
- **SC-002**: Los 3 espacios reales del cliente sobreviven la actualización con el 100 % de sus documentos e hilos.
- **SC-003**: En el CSV real del cliente, cada valor detectado tiene exactamente 1 placeholder en el documento completo, y la pregunta "¿qué registros tiene Julián?" devuelve todas sus filas con el nombre real.
- **SC-004**: Tras 1 día de uso del usuario de prueba, el 100 % de su consumo (enmascarados y preguntas) aparece bajo su nombre en costos y 0 % bajo cuentas de servicio; el rechazo por presupuesto agotado ocurre antes del primer token consumido en exceso (tolerancia: la respuesta en curso).
- **SC-005**: En una instalación limpia, "modelos con consumo" lista solo los deployments reales (hoy 3) y "usuarios" lista solo personas.
- **SC-006**: La prueba de branding pasa con 0 términos prohibidos en superficies visibles y se ejecuta en CI en cada cambio.
- **SC-007**: Ningún cambio de esta spec altera el comportamiento de un despliegue Guardian que no active las opciones nuevas (suite de contrato existente en verde).

## Assumptions

- La autoridad de identidad y de pertenencia es el backend Guardian (no el motor de documentos): encaja con el modelo multi-tenant existente (`tenant_id` en usuarios) y no depende de la API administrativa del motor de documentos, que varía entre versiones. Alternativa (multiusuario nativo del motor de documentos) evaluada y descartada en el diagnóstico por acoplamiento y por no eliminar la credencial omnipotente.
- La identidad "en nombre de" solo la pueden afirmar llaves de servicio marcadas explícitamente como tales, y se valida contra la sesión que la origina; el plan decide el mecanismo concreto (cabecera firmada, token de sesión, o llave por usuario).
- Para atribuir el camino RAG al usuario (US2), el plan evaluará dos vías: (a) que el Hub Chat haga la recuperación de contexto en el motor de documentos y la generación en el motor de IA con la identidad del usuario, o (b) reconciliar el gasto agregado del proveedor. Se prefiere (a) porque da atribución, presupuesto y desenmascarado en el mismo pedido sin tocar el motor de documentos; queda como decisión del plan.
- El alcance del determinismo es **por documento** (decisión sellada 08-sep); cualquier alcance mayor (espacio, tenant) es una enmienda constitucional a escalar aparte, no una continuación técnica.
- El enmascarado sigue siendo un módulo puro (sin I/O en el camino caliente); el determinismo se logra derivando el token del identificador del documento, no consultando un almacén.
- La detección NLP no se rediseña aquí; la inconsistencia por contexto en CSV se mitiga con la lista de nombres protegidos y se documenta como límite conocido.
- Los cruces exactos CSV/Excel quedan fuera (spec 041, US5).
- La versión del motor de documentos se fija en el instalador; subirla es una tarea con prueba, no un efecto colateral.
- Streaming: no se promete enforcement de presupuesto ni desenmascarado en streaming (límite ya documentado en 042 y en el principio V).

## Riesgos residuales y lo que queda fuera (revisado 08-sep)

Revisión cruzada contra los dos mails de Tomás, punto por punto:

| Pedido de Tomás | ¿Cubierto acá? |
|---|---|
| Memoria de chats compartida (prioritario) | Sí — US1 |
| Editar rol/email, borrar usuarios | Sí — US5 |
| `license`/`chat-ui` como modelos | Sí — US4 |
| `anythingllm-provider`/`rag-masking` como usuarios | Sí — US4 |
| Sin costos por usuario | Sí — US2 |
| Enmascarado no determinista (Julián) | Sí — US3 |
| Cruces exactos fila/columna del CSV | **No, fuera de alcance explícito** — necesita un motor nuevo (spec 041 US5, decisión ya tomada el 31-ago). Hay que decírselo a Tomás directamente, no queda resuelto por esta ronda. |

**Hueco encontrado el 08-sep, no reportado por Tomás pero real**: el puerto del motor de documentos
(`3001`) estaba publicado al host en `elea-installer/docker-compose.yml`. Cualquiera en la misma
red podía hablar directo con el motor de documentos, en modo single-user y sin las verificaciones
de US1/US2, saltándose todo el aislamiento de esta spec. **Corregido el mismo día** (`ports` →
`expose`, solo alcanzable desde la red interna del compose) — tarea T021b en `tasks.md`. Verificar
en la revisión final que ningún otro servicio interno (el motor de IA, el detector NLP) tenga el
mismo problema.

**No cubierto por esta spec, abierto en spec 041** (no mencionado en estos dos mails, pero
pendiente de antes): carga de `.pptx`, generación de documentos, formateo de respuesta a demanda,
presupuesto por rol con UX propia.
