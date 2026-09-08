# Feature Specification: Hub Chat con espacios privados, costos por persona y panel de administración completo (UIs)

**Feature Branch**: `044-hub-chat-panel-admin`

**Created**: 2026-09-08

**Status**: Draft — lista para `/speckit-plan`. **Depende de** [043-aislamiento-atribucion-motor](../043-aislamiento-atribucion-motor/spec.md) (contratos 1-6); las historias P1 no se cierran sin los contratos 1, 2 y 3.

**Repos/carpetas que toca**: `cluna-8/elea` → `client/` (Hub Chat, la UI que usan las personas de Elea) y `frontend/` (panel de administración). Las imágenes se reconstruyen y el `elea-installer` solo actualiza versiones. **NO toca** `backend/` ni `litellm/`.

**Input**: mismos dos mails de Tomás Mc Nally (03-sep y 07-sep-2026) que la 043 — ver allí el texto literal y el diagnóstico. Esta spec cubre la parte **de cara al usuario y al admin**: lo que la persona ve, toca y entiende.

**Decisiones selladas (08-sep)**: espacios con miembros (dueño + miembros, hilos privados por usuario); dos specs (motor+backend / UIs); enmascarado determinista por documento.

## Diagnóstico visible en las UIs (verificado 08-sep)

| Dónde | Qué ve hoy la persona | Causa (detalle en 043) |
|---|---|---|
| Hub Chat | Al entrar, aterriza en el primer espacio de la lista global con todo el historial de otro usuario cargado. | El Hub lista todos los espacios y auto-selecciona el primero; no hay noción de pertenencia. Además ~10 endpoints del Hub (espacios, hilos, historial, subida, borrado, ajustes) no exigen sesión. |
| Hub Chat | El badge de presupuesto se muestra pero el chat sigue respondiendo con presupuesto agotado. | El Hub muestra el presupuesto leído con una sesión de admin, pero no lo aplica antes de preguntar en un espacio. |
| Hub Chat | Errores como "AnythingLLM no pudo responder", "AnythingLLM rechazó el documento". | 7 mensajes de error nombran el motor de documentos; comentarios del HTML servido también lo nombran. |
| Panel admin › Usuarios | Solo "Asignar equipo" y "Restablecer contraseña"; no hay editar rol/email, ni desactivar, ni dar de baja. Aparecen `svc.anythingllm-provider` y `svc.rag-masking` como usuarios. | La UI no expone la edición que el backend ya soporta; la baja no existe en backend (043 US5); las cuentas de servicio no se distinguen (043 US4). |
| Panel admin › Dashboard y Costos | `license` y `chat-ui` figuran como modelos; el usuario de prueba no aparece con consumo. | Columnas sobrecargadas y credenciales compartidas (043 US2/US4). |
| Panel admin › Seguridad | La tarjeta de detección NLP dice "(Presidio)". La pestaña del navegador dice "Sentinel Secure AI Gateway", no la marca de Eleia. | Nombre sembrado (043 US6) y título no enganchado al branding configurable. |

**Fuera de alcance**: cruces exactos CSV/Excel (spec 041 US5); generación de documentos, pptx, formateo de respuesta (spec 041).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Cada persona ve solo sus espacios y sus hilos (Priority: P1)

Una persona entra al Hub Chat y ve únicamente los espacios de los que es miembro. Si no es
miembro de ninguno, ve un estado vacío claro ("Todavía no tenés espacios. Creá uno o pedile a tu
administrador que te agregue"). Dentro de un espacio ve solo sus propios hilos. Puede crear un
espacio (queda como dueña) e invitar miembros por nombre de usuario; puede ver quiénes son los
miembros. Ninguna pantalla ni acción del Hub funciona sin sesión iniciada.

**Why this priority**: es el bug prioritario del cliente y una fuga de datos entre personas.

**Independent Test**: con los contratos 1 de la 043 disponibles, dos personas en dos navegadores:
A crea "Contabilidad" y sube un documento; B no lo ve; A agrega a B; B lo ve y pregunta; los hilos
de A no aparecen a B ni viceversa; sin sesión, ninguna URL del Hub devuelve datos.

**Acceptance Scenarios**:

1. **Given** una persona sin espacios, **When** entra, **Then** ve el estado vacío con las dos acciones (crear / pedir acceso), y ningún historial ajeno.
2. **Given** una persona miembro de 2 de 5 espacios, **When** lista, **Then** ve exactamente esos 2.
3. **Given** un espacio con miembros A y B, **When** A abre la lista de hilos, **Then** ve solo los suyos; el "hilo principal" también es suyo.
4. **Given** la dueña de un espacio, **When** abre "Miembros", **Then** puede agregar/quitar por nombre de usuario y transferir la propiedad; un miembro no dueño solo ve la lista.
5. **Given** una URL directa a un espacio ajeno (identificador conocido), **When** se abre, **Then** el Hub muestra "No tenés acceso a este espacio" y no carga nada.
6. **Given** sin sesión, **When** cualquier llamada del Hub (listar, historial, subir, borrar, ajustes, hilos), **Then** responde "iniciá sesión" y no devuelve datos.
7. **Given** la instalación existente del cliente tras actualizar, **When** el admin entra, **Then** ve los 3 espacios reales en "Sin asignar" y puede asignarles miembros desde el Hub o el panel.

---

### User Story 2 - Presupuesto que se ve y se aplica; costos por persona en el panel (Priority: P1)

En el Hub, la persona ve su presupuesto (usado / máximo) leído con **su propia** sesión (sin
sesión de admin de fondo), actualizado tras cada respuesta. Si lo agotó, al intentar preguntar o
subir un documento recibe un aviso claro antes de que se consuma nada. En el panel, el admin ve el
consumo de cada persona (incluyendo lo que hace dentro de espacios) y puede ver el detalle por
modelo real; las operaciones de enmascarado figuran como tales (sin costo), no como modelo.

**Why this priority**: evaluar costos era objetivo explícito del piloto y hoy el usuario de prueba
"no existe" en el panel.

**Independent Test**: persona con presupuesto $1: dos preguntas en un espacio suben su badge; el
panel muestra a esa persona con ese consumo y el modelo real; al agotarlo, el Hub avisa y bloquea
la siguiente pregunta antes de enviarla; el panel no muestra consumo bajo `svc.*`.

**Acceptance Scenarios**:

1. **Given** una persona con presupuesto, **When** recibe una respuesta, **Then** el badge de presupuesto se actualiza con el costo de esa respuesta en menos de 5 s.
2. **Given** presupuesto agotado, **When** intenta preguntar o subir, **Then** ve "Alcanzaste tu presupuesto. Contactá a tu administrador" y el pedido no se envía; si el sistema igualmente rechaza (402), el Hub muestra el mismo mensaje, nunca un error técnico.
3. **Given** el panel de costos, **When** el admin filtra por persona, **Then** ve preguntas (con costo y modelo real) y enmascarados de documentos (sin costo, contados por documento) bajo esa persona.
4. **Given** el panel de costos, **When** el admin mira "modelos", **Then** solo hay modelos reales; ni `license` ni `chat-ui` ni ninguna superficie.
5. **Given** el Hub sin credenciales de admin configuradas, **When** una persona entra, **Then** ve su presupuesto igual (autoservicio, contrato 2 de la 043).

---

### User Story 3 - Enmascarado coherente en todo el documento, visible para la persona (Priority: P1)

Al subir un documento, la persona ve un resumen de protección por documento (no por trozo): "Se
protegieron 12 personas, 8 DNI, 3 CBU". Un mismo dato aparece con un único placeholder en todo el
documento, y el chat responde relacionando todas sus apariciones y mostrando el valor real.

**Why this priority**: segundo bug reportado; afecta la calidad de respuesta sobre CSV.

**Independent Test**: subir el CSV real del cliente; el resumen cuenta cada persona una vez;
"¿qué registros tiene Julián?" devuelve todas sus filas con el nombre real.

**Acceptance Scenarios**:

1. **Given** un documento en varios trozos, **When** se sube, **Then** el Hub envía un identificador de documento único a todos los trozos (contrato 3) y muestra un solo resumen agregado.
2. **Given** un reintento de subida por fallo de red, **When** el Hub reintenta, **Then** conserva el mismo identificador para que el resultado sea idéntico.
3. **Given** un documento subido antes de este cambio, **When** se consulta, **Then** el Hub lo indica ("documento protegido con el esquema anterior; reenviarlo para mejorar las respuestas") sin fallar.
4. **Given** un CSV con un nombre que el detector no reconoce en algunas filas, **When** el admin lo agrega a "nombres protegidos" en el panel, **Then** la próxima subida lo enmascara en todas las filas (mitigación documentada en el Hub y en el panel).

---

### User Story 4 - Panel de usuarios completo (Priority: P2)

El admin edita rol, email, nombre visible y equipo de un usuario desde la tabla; desactiva y
reactiva; da de baja definitivamente con confirmación explícita (escribiendo el nombre de usuario)
y un aviso de lo que implica (llaves revocadas, espacios propios a "sin asignar", auditoría
conservada). Las cuentas de servicio no aparecen entre las personas; hay una sección plegada
"Cuentas de servicio (2)" solo lectura con explicación de para qué sirve cada una.

**Why this priority**: pedido explícito; hoy la UI oculta capacidades que el backend ya tiene.

**Independent Test**: en el panel, cambiar solo el rol de un usuario (auditoría muestra el
cambio), luego solo el email; desactivar (no loguea); reactivar; dar de baja (no loguea, desaparece
de "personas", su consumo histórico sigue visible); las cuentas `svc.*` solo en la sección plegada.

**Acceptance Scenarios**:

1. **Given** la tabla de usuarios, **When** el admin edita un usuario, **Then** cambia solo lo que tocó, con validación en línea de email/usuario duplicado.
2. **Given** el admin intenta darse de baja o dar de baja al último admin, **When** confirma, **Then** la UI lo impide con explicación (y el backend también).
3. **Given** el listado, **When** carga, **Then** el contador "Usuarios activos" y los asientos de licencia no incluyen cuentas de servicio.
4. **Given** la sección de cuentas de servicio, **When** se despliega, **Then** cada una muestra nombre, propósito ("proveedor del motor de documentos", "protección de documentos") y estado, sin acciones destructivas.

---

### User Story 5 - Ningún nombre de motor, proveedor NLP ni motor de documentos visible (Priority: P2)

La persona en el Hub y el admin en el panel nunca leen "AnythingLLM", "Presidio", "LiteLLM" ni
nombres de proveedores de modelos: ni en textos, ni en errores, ni en el título de la pestaña, ni
en el código fuente servido al navegador. La pestaña del panel muestra la marca configurada del
cliente ("Eleia Guardian"); la del Hub, "Eleia Hub".

**Why this priority**: principio VII de la constitución y pedido explícito del dueño.

**Independent Test**: prueba automática que recorre el HTML/JS servido de ambas UIs, los textos
de error y los títulos buscando los términos prohibidos; y prueba manual de los 7 errores del Hub
(motor de documentos caído, documento rechazado, espacio no creado, etc.) mostrando copy neutro.

**Acceptance Scenarios**:

1. **Given** el motor de documentos caído, **When** la persona pregunta, **Then** ve "El servicio de documentos no está disponible. Intentá de nuevo en unos minutos" y el detalle técnico queda solo en el log del servidor.
2. **Given** el código fuente del Hub servido al navegador, **When** se inspecciona, **Then** no contiene nombres de motores ni proveedores (ni en comentarios).
3. **Given** la tarjeta de detección NLP del panel, **When** se muestra, **Then** su nombre y ayuda son neutros ("Detección lingüística de datos personales").
4. **Given** el panel, **When** se abre, **Then** el título de la pestaña es el de la marca configurada, no el nombre interno del producto.

---

### User Story 6 - Verificación de integración UI + backend antes de cerrar (Priority: P1, transversal)

Ninguna historia P1 de esta spec se marca como hecha sin una verificación de punta a punta con la
043 desplegada: (a) en una instalación limpia desde el instalador, y (b) en una copia de la
instalación del cliente (o en la real, en un espacio de prueba creado y borrado, como se hizo en
la 042). Se registra qué se probó, con qué usuarios y con qué documentos, en `CHANGELOG.md` de
esta spec.

**Why this priority**: al separar UI y backend en dos desarrollos, el riesgo principal es que cada
uno funcione solo y fallen juntos. Esta historia existe para que "funciona" signifique
"funciona integrado".

**Independent Test**: el guion de verificación (abajo) se corre completo y todos los pasos pasan.

**Acceptance Scenarios (guion de verificación)**:

1. **Given** instalación limpia, **When** se crean admin + 2 personas y se sigue el guion (crear espacio, invitar, subir CSV real, preguntar por "Julián", agotar presupuesto, intentar acceso cruzado, dar de baja a una persona), **Then** los 7 pasos pasan y no aparece ningún término prohibido.
2. **Given** los 3 espacios reales del cliente, **When** se actualiza, **Then** siguen ahí en "Sin asignar" y, al asignarles miembros, sus documentos e hilos previos siguen consultables (con el aviso del esquema anterior para documentos viejos).
3. **Given** un contrato de la 043 que cambia después de que la 044 lo consumió, **When** corre la suite, **Then** una prueba de contrato del lado del Hub falla antes de llegar a producción.

### Edge Cases

- La persona es quitada de un espacio mientras lo tiene abierto: el próximo pedido muestra "ya no tenés acceso" y vuelve a la lista.
- Una persona es dueña del único espacio y se la da de baja: el admin ve el espacio en "Sin asignar" y puede reasignar.
- Sesión del Hub expirada a mitad de una subida: se informa y se ofrece reintentar con el mismo identificador de documento.
- Subida grande (150.000 caracteres, ~12 s de enmascarado): la UI muestra progreso por trozo pero el resumen es único por documento.
- Presupuesto agotado a mitad de una respuesta: la respuesta en curso se completa; la siguiente se bloquea (no se promete corte en tiempo real).
- Panel abierto en dos pestañas editando el mismo usuario: gana el último guardado; la UI recarga y avisa.
- Usuario con rol "lectura" en el panel: ve todo, no puede editar ni dar de baja (botones ocultos y backend rechaza).

## Requirements *(mandatory)*

### Functional Requirements

**Hub Chat (`client/`)**

- **FR-001**: Toda ruta del Hub que devuelva o modifique datos MUST exigir sesión iniciada; sin sesión responde "iniciá sesión" sin datos.
- **FR-002**: El Hub MUST listar solo los espacios donde la persona es miembro (contrato 1) y MUST NOT auto-seleccionar un espacio que no le pertenece; sin espacios, MUST mostrar el estado vacío con "crear" y "pedir acceso".
- **FR-003**: El Hub MUST mostrar solo los hilos de la persona dentro de un espacio y crear los nuevos a su nombre.
- **FR-004**: El Hub MUST ofrecer gestión de miembros (ver, agregar por nombre de usuario, quitar, transferir propiedad) a la dueña y a admins; solo lectura a miembros.
- **FR-005**: El Hub MUST enviar la identidad de la persona en cada operación hecha con credencial de servicio (contrato 2) y MUST NOT usar una sesión de admin para leer su presupuesto (autoservicio).
- **FR-006**: El Hub MUST verificar el presupuesto antes de preguntar o subir y MUST mostrar el mismo mensaje neutro tanto si bloquea localmente como si el backend rechaza con 402.
- **FR-007**: El Hub MUST generar un identificador de documento por subida, enviarlo en todos los trozos (contrato 3), reutilizarlo en reintentos y mostrar un único resumen de protección por documento.
- **FR-008**: El Hub MUST marcar documentos protegidos con el esquema anterior y sugerir reenviarlos, sin fallar.
- **FR-009**: Los mensajes de error del Hub MUST ser neutros (sin nombre de motor de documentos, motor de IA ni proveedor); el detalle técnico va solo al log del servidor. El HTML/JS servido MUST NOT contener esos nombres ni en comentarios.
- **FR-010**: El Hub MUST mostrar a los admins una vista "Sin asignar" con los espacios heredados de la actualización, para asignar miembros.

**Panel de administración (`frontend/`)**

- **FR-020**: La tabla de usuarios MUST permitir editar rol, email, nombre visible y equipo con actualización parcial (contrato 5), validación en línea y confirmación para cambio de rol.
- **FR-021**: El panel MUST permitir desactivar/reactivar y dar de baja con confirmación fuerte (escribir el nombre de usuario) y explicación de consecuencias; MUST impedir en la UI la auto-baja y la baja del último admin.
- **FR-022**: El listado MUST excluir cuentas de servicio por defecto y mostrarlas en una sección plegada de solo lectura con propósito y estado (contrato 4); contadores y asientos MUST excluirlas.
- **FR-023**: Dashboard y Costos MUST mostrar solo modelos reales en "modelos" y MUST permitir ver consumo por persona incluyendo su actividad en espacios; los enmascarados de documentos se muestran como operaciones sin costo, por documento.
- **FR-024**: El panel MUST permitir a un admin asignar miembros a espacios "Sin asignar" (misma capacidad que el Hub, para no depender de que el admin use el Hub).
- **FR-025**: El título de la pestaña y los textos de marca MUST salir de la configuración de branding existente; la tarjeta de detección NLP MUST usar nombre y ayuda neutros (contrato 6).
- **FR-026**: El panel MUST ofrecer la lista de "nombres protegidos" con explicación de su uso para CSV (mitigación de US3), si no la ofrece ya de forma clara.

**Transversal**

- **FR-030**: Una prueba automática MUST recorrer el HTML/JS servido de ambas UIs y los textos de error buscando términos prohibidos, con lista de excepciones explícita, y correr en CI.
- **FR-031**: Cada contrato consumido de la 043 MUST tener una prueba de contrato del lado de la UI que falle si el contrato cambia.
- **FR-032**: El guion de verificación de integración (US6) MUST ejecutarse y registrarse antes de marcar cualquier P1 como hecha; las imágenes de `client` y `frontend` MUST reconstruirse y el instalador MUST apuntar a las versiones verificadas.

### Key Entities

- **Espacio visible**: proyección para la persona de un espacio (nombre, rol de la persona en él, miembros, estado "sin asignar" para admins).
- **Hilo propio**: hilo del espacio que pertenece a la persona.
- **Resumen de protección por documento**: identificador de documento, conteo agregado por tipo de entidad, esquema (actual / anterior).
- **Presupuesto propio**: usado, máximo, estado (ok / agotado), leído por autoservicio.
- **Cuenta de servicio (vista)**: nombre, propósito, estado, solo lectura.

## Contratos consumidos de la 043

| # | Contrato | Historias que lo necesitan |
|---|---|---|
| 1 | Espacios/membresías/hilos con verificación de acceso | US1, US6 |
| 2 | "En nombre de" para llaves de servicio + autoservicio de presupuesto/consumo | US2, US6 |
| 3 | Identificador de documento en el enmascarado | US3, US6 |
| 4 | Tipo de cuenta en usuarios; modelo/superficie separados en costos | US2, US4 |
| 5 | Actualización parcial y baja de usuarios | US4 |
| 6 | Nombres neutros y sanitización reutilizable | US5 |

Mientras un contrato no esté disponible, la historia correspondiente se desarrolla contra un
doble de prueba con la forma acordada y se marca "pendiente de integración"; no se cierra.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: En el guion de integración con 2 personas, 0 de 20 intentos cruzados (con y sin sesión) muestran datos ajenos en el Hub.
- **SC-002**: Una persona nueva sin espacios llega al estado vacío correcto en su primer inicio de sesión en el 100 % de los casos (no ve historial de nadie).
- **SC-003**: El badge de presupuesto refleja el costo de cada respuesta en menos de 5 s y el bloqueo por presupuesto agotado ocurre antes de enviar el pedido.
- **SC-004**: El admin encuentra el consumo del usuario de prueba en el panel en menos de 1 minuto sin ayuda, con modelo real y sin filas `license`/`chat-ui`.
- **SC-005**: En el CSV real del cliente, el resumen de protección cuenta cada persona una vez y la pregunta por "Julián" devuelve todas sus filas con el nombre real.
- **SC-006**: El admin completa editar rol, editar email, desactivar y dar de baja a un usuario desde el panel sin recurrir a la API; las cuentas de servicio no aparecen entre las personas.
- **SC-007**: La prueba de términos prohibidos pasa con 0 hallazgos en ambas UIs y corre en CI.
- **SC-008**: Los 3 espacios reales del cliente sobreviven la actualización y quedan asignables desde el Hub y el panel.

## Assumptions

- El Hub Chat sigue siendo el cliente Node existente (`client/`), no se reescribe; se le agregan sesión obligatoria, pertenencia, presupuesto por autoservicio, identificador de documento y copy neutro.
- La autoridad de acceso es el backend (043); el Hub filtra por UX pero nunca es la única barrera.
- Para atribuir el chat en espacios a la persona, el plan de la 043 decide entre "recuperación en el motor de documentos + generación en el motor de IA con la identidad de la persona" o "reconciliación del gasto"; esta spec asume que el Hub puede necesitar orquestar esa llamada (impacto en `client/`) y lo deja al plan conjunto.
- Los documentos subidos antes de la 043 conservan placeholders no relacionables; se avisa, no se migra.
- El panel usa el branding configurable ya existente; solo se engancha el título de pestaña y se corrigen textos.
- El rol "lectura" existente ve todo y no edita.
- Las pruebas de contrato viven junto a cada UI y se ejecutan contra el backend real en CI (instalación limpia vía compose), no solo contra dobles.

## Riesgos residuales y lo que queda fuera (revisado 08-sep)

Ver la tabla completa de cobertura contra los dos mails de Tomás en la spec 043 (misma revisión,
mismo día). Del lado de las UIs, dos notas propias:

- El cruce exacto fila/columna del CSV (mail del 03-sep) tampoco se resuelve acá — ninguna
  pantalla nueva de esta spec lo cubre; si Tomás vuelve a preguntar por eso, la respuesta es "está
  en la spec 041, es una pieza aparte, no de esta ronda".
- El hueco del puerto del motor de documentos expuesto (encontrado el 08-sep, corregido en la 043)
  no tenía nada que ver con el Hub ni con el panel — pero vale la pena que el guion de integración
  de US6 verifique explícitamente que, tras el fix, el Hub sigue siendo el único camino real hacia
  el motor de documentos (un intento directo a `http://<host>:3001` desde fuera del compose debe
  fallar por conexión, no por 403).
