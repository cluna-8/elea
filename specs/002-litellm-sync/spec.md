# Feature Specification: LiteLLM Real Integration — Users, Budgets & Virtual Keys

**Feature Branch**: `feature/002-litellm-sync`

**Created**: 2026-06-29

**Status**: Implementado ✅ (mergeado a master, 2026-06-29)

**Input**: User description: "Llevar el sistema a producción real usando LiteLLM como fuente de verdad para la gestión de usuarios, equipos, presupuestos y virtual keys. El backend actúa como capa de seguridad y orquestación; LiteLLM gestiona el enforcement financiero nativo."

## Context

El MVP (feature 001) construyó toda la gestión de usuarios, grupos, presupuestos y keys en nuestra propia base de datos PostgreSQL. Sin embargo, las keys `sentinel_sk_...` generadas no son reconocidas por LiteLLM, el enforcement de presupuesto es simulado, y el gasto real no se trackea. Este feature sincroniza ambos sistemas para que el producto sea funcional en producción.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Administrador crea un equipo y genera su primera key real (Priority: P1) 🎯 MVP

Como administrador, quiero crear un equipo (ej. "Cardiología"), asignarle un presupuesto de $50/mes y generar una virtual key que los médicos del equipo puedan usar para acceder a los modelos, con la seguridad de que si superan el límite, LiteLLM bloqueará las requests automáticamente.

**Why this priority**: Es el flujo más crítico del producto. Sin keys reales y enforcement real, el sistema no puede venderse ni usarse en producción.

**Independent Test**: Crear un equipo via UI, asignarle budget de $0.01, generar una key, hacer una request con esa key, y verificar que LiteLLM bloquea la siguiente request por presupuesto agotado.

**Acceptance Scenarios**:

1. **Given** un administrador crea el equipo "Cardiología" via la UI, **When** el backend procesa la creación, **Then** el equipo existe tanto en nuestra DB (con `litellm_team_id`) como en LiteLLM (`POST /team/new`).
2. **Given** un equipo existe con `litellm_team_id`, **When** el administrador genera una key para ese equipo con max_budget=$50, **Then** LiteLLM devuelve una key real `sk-...`, que se muestra al usuario una sola vez y se guarda hasheada en nuestra DB.
3. **Given** una key real con budget=$0.01, **When** se hacen requests hasta agotar el presupuesto, **Then** LiteLLM retorna `HTTP 429` con mensaje de budget exhausted sin necesidad de lógica de enforcement en nuestro backend.

---

### User Story 2 - Administrador ve el gasto real en tiempo real (Priority: P1) 🎯 MVP

Como administrador, quiero ver en la UI cuánto ha gastado cada key, usuario y equipo en tiempo real, con los datos que LiteLLM trackea automáticamente por cada completions request.

**Why this priority**: Sin visibilidad de gasto real, el producto no tiene utilidad como gateway empresarial. Es la propuesta de valor central junto con la seguridad.

**Independent Test**: Hacer 3 requests desde el Playground, luego abrir la página de Usuarios y verificar que el gasto acumulado refleja el costo real de esas requests (no cero como ahora).

**Acceptance Scenarios**:

1. **Given** una key ha procesado requests, **When** el administrador abre la página de Usuarios/Keys, **Then** la columna "Gasto actual" muestra el valor real consultado a `GET /key/info?key=sk-...` de LiteLLM.
2. **Given** un equipo tiene múltiples keys activas, **When** el administrador consulta el detalle del equipo, **Then** ve el gasto agregado del equipo desde `GET /team/info?team_id=...`.
3. **Given** un usuario tiene budget $10 y ha gastado $7, **When** la UI renderiza su fila, **Then** muestra una barra de progreso con 70% de uso y color de advertencia.

---

### User Story 3 - Administrador crea un usuario individual con su key (Priority: P2)

Como administrador, quiero crear un usuario individual (no necesariamente parte de un equipo) con su propio presupuesto y una key personal, para casos de acceso individual o de prueba.

**Why this priority**: Los equipos son el caso de uso principal en entornos sanitarios, pero el acceso individual es necesario para administradores, desarrolladores y usuarios de prueba.

**Independent Test**: Crear un usuario individual, asignarle budget, generar su key, y verificar que el usuario existe en LiteLLM (`GET /user/info`) y la key está asociada a ese `user_id`.

**Acceptance Scenarios**:

1. **Given** un administrador crea el usuario "dr.garcia@hospital.es", **When** el backend procesa la creación, **Then** se llama a `POST /user/new` en LiteLLM y se guarda el `litellm_user_id` devuelto en nuestra DB.
2. **Given** un usuario existe con `litellm_user_id`, **When** se genera una key con `user_id` y `max_budget`, **Then** la key de LiteLLM está asociada a ese usuario y el presupuesto se aplica a nivel de key.

---

### User Story 4 - Administrador revoca una key comprometida (Priority: P2)

Como administrador, quiero poder revocar una virtual key inmediatamente si sospecho que fue comprometida, asegurándome de que LiteLLM deje de aceptarla al instante.

**Why this priority**: La seguridad requiere poder invalidar accesos de forma instantánea. Hoy el delete solo borra el registro de nuestra DB; LiteLLM nunca se entera.

**Independent Test**: Crear una key, verificar que funciona para hacer una request, revocarla via UI, intentar hacer otra request con esa key y verificar que LiteLLM retorna `HTTP 401`.

**Acceptance Scenarios**:

1. **Given** una key activa `sk-...`, **When** el administrador hace click en "Revocar", **Then** el backend llama a `DELETE /key/delete` en LiteLLM antes de eliminarla de nuestra DB.
2. **Given** una key fue revocada, **When** un cliente intenta hacer una request con esa key, **Then** LiteLLM retorna `HTTP 401 Unauthorized` sin procesar la request.

---

### Edge Cases

- **LiteLLM no disponible al crear un recurso**: Si LiteLLM devuelve error al crear user/team/key, el backend NO debe persistir el registro en nuestra DB (transacción atómica: o ambos o ninguno).
- **Key creada en LiteLLM pero falla el guardado local**: Si nuestra DB falla después de crear la key en LiteLLM, se debe intentar revocar la key en LiteLLM para evitar keys huérfanas.
- **Gasto reportado por LiteLLM es `null`**: Si LiteLLM devuelve `spend: null` para una key nueva (sin requests), la UI debe mostrar `$0.00` sin errores.
- **Team sin `engine_team_id`** (registros del MVP anterior): Al consultar el gasto de un team sin `engine_team_id`, el backend devuelve `spend: null` y la UI muestra `-` sin crashear.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El sistema MUST llamar al motor de IA al crear un grupo/equipo y persistir el `engine_team_id` retornado.
- **FR-002**: El sistema MUST llamar al motor de IA al crear un usuario y persistir el `engine_user_id` retornado.
- **FR-003**: El sistema MUST generar virtual keys a través del motor de IA (no localmente), pasando `max_budget`, `budget_duration`, `models`, y `team_id` o `user_id`.
- **FR-004**: El sistema MUST mostrar la key real `sk-...` devuelta por el motor al usuario exactamente una vez. Solo se almacena el hash SHA-256 y el preview en nuestra DB.
- **FR-005**: El sistema MUST revocar keys en el motor de IA antes de eliminarlas de nuestra DB.
- **FR-006**: El sistema MUST exponer un endpoint `GET /api/v1/keys/{key_id}/spend` que consulte el gasto real al motor y retorne `{spend_usd, max_budget, remaining}`.
- **FR-007**: El sistema MUST exponer un endpoint `GET /api/v1/users/{user_id}/spend` que retorne el gasto del usuario.
- **FR-008**: El sistema MUST exponer un endpoint `GET /api/v1/groups/{group_id}/spend` que retorne el gasto del equipo.
- **FR-009**: La UI MUST mostrar el gasto real en la página de Usuarios, con barra de progreso respecto al `max_budget`.
- **FR-010**: Si el motor de IA no está disponible durante la creación de un recurso, el sistema MUST retornar HTTP 503 y NO persistir el registro localmente.
- **FR-011**: El motor de IA MUST tener habilitada la gestión de keys via API con `store_model_in_db: true`.
- **FR-012**: El sistema MUST ser completamente white-label. Ningún nombre de tecnología de terceros (motores de IA subyacentes, proxies, librerías) debe aparecer en: respuestas de la API, mensajes de error, logs visibles al cliente, nombres de campos en la API pública, ni en la UI. Los archivos de configuración de infraestructura interna quedan excluidos de esta regla.

### Key Entities *(include if feature involves data)*

- **Group (actualizado)**: Agrega campo `engine_team_id: String` — identificador del equipo en el motor de IA interno. Opaco para el cliente.
- **User (actualizado)**: Agrega campo `engine_user_id: String` — identificador del usuario en el motor de IA interno. Opaco para el cliente.
- **APIKey (actualizado)**: Agrega campo `engine_key_token: String` — referencia interna para operar sobre la key en el motor. El campo existente `key_hash` hashea la key real. Ninguno de estos campos se expone en la API pública.
- **AIEngineClient (nuevo servicio)**: Wrapper HTTP para la API de gestión del motor de IA subyacente. No es una entidad de BD. El nombre del motor no aparece en el nombre del servicio ni en sus logs externalizados.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Una key generada via nuestra UI puede usarse directamente en un `curl` contra nuestro backend FastAPI (`Authorization: Bearer sk-...`) y la request se procesa correctamente.
- **SC-002**: Con budget=$0.01 asignado via UI, el motor de IA bloquea automáticamente la siguiente request después de que el gasto supera ese límite, sin intervención de nuestro backend.
- **SC-003**: La columna "Gasto actual" en la UI de Usuarios muestra valores mayores a $0.00 después de procesar requests reales desde el Playground.
- **SC-004**: Revocar una key via UI hace que la siguiente request con esa key retorne 401 en menos de 2 segundos.
- **SC-005**: Cero keys huérfanas en el motor — cada key activa en el motor debe tener un registro correspondiente en nuestra DB, y viceversa.
- **SC-006**: Ninguna respuesta de la API pública (`/api/v1/...`), mensaje de error, ni elemento de la UI contiene el nombre de ningún motor, librería o proveedor de IA subyacente.

---

## Assumptions

- **Motor de IA disponible**: El motor interno está levantado y tiene acceso a su DB antes de que el backend intente sincronizar recursos.
- **Registros del MVP anterior son legacy**: Los users/groups/keys creados en el MVP (feature 001) no tienen `engine_team_id` ni `engine_user_id`. La UI los mostrará con gasto `-` sin errores. No se migrarán automáticamente.
- **Budget en USD**: El motor trabaja con `max_budget` en USD. Los presupuestos en tokens del MVP se mantienen como información visual en nuestra UI pero no se sincronizan con el motor (no tiene límites nativos de tokens por key en la versión OSS).
- **El cliente usa nuestro FastAPI como proxy**: Los clientes externos envían sus keys a nuestro backend (`http://sentinel-gateway:8081/api/v1/chat/completions`), nunca directamente al motor interno. Esto garantiza que las capas de seguridad (PII masking, guardianes) siempre se ejecutan.
- **Motor OSS**: Se usa la versión open-source del motor de IA, sin features Enterprise (auto-rotación de keys, SSO, etc.).
- **Separación infraestructura / producto**: Los archivos de configuración internos (`config.yaml`, variables de entorno del servidor) pueden referenciar nombres de tecnología. Lo que no puede hacerlo es el código de la capa de producto: nombres de clases, campos de DB, respuestas de API, logs de aplicación y UI.
