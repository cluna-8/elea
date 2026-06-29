# Feature Specification: LiteLLM Real Integration — Users, Budgets & Virtual Keys

**Feature Branch**: `feature/002-litellm-sync`

**Created**: 2026-06-29

**Status**: Draft

**Input**: User description: "Llevar el sistema a producción real usando LiteLLM como fuente de verdad para la gestión de usuarios, equipos, presupuestos y virtual keys. El backend actúa como capa de seguridad y orquestación; LiteLLM gestiona el enforcement financiero nativo."

## Context

El MVP (feature 001) construyó toda la gestión de usuarios, grupos, presupuestos y keys en nuestra propia base de datos PostgreSQL. Sin embargo, las keys `basa_sk_...` generadas no son reconocidas por LiteLLM, el enforcement de presupuesto es simulado, y el gasto real no se trackea. Este feature sincroniza ambos sistemas para que el producto sea funcional en producción.

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
- **Team sin `litellm_team_id`** (registros del MVP anterior): Al consultar el gasto de un team sin `litellm_team_id`, el backend devuelve `spend: null` y la UI muestra `-` sin crashear.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El sistema MUST llamar a `POST /team/new` en LiteLLM al crear un grupo/equipo y persistir el `litellm_team_id` retornado.
- **FR-002**: El sistema MUST llamar a `POST /user/new` en LiteLLM al crear un usuario y persistir el `litellm_user_id` retornado.
- **FR-003**: El sistema MUST generar virtual keys mediante `POST /key/generate` en LiteLLM (no localmente), pasando `max_budget`, `budget_duration`, `models`, y `team_id` o `user_id`.
- **FR-004**: El sistema MUST mostrar la key real `sk-...` devuelta por LiteLLM al usuario exactamente una vez. Solo se almacena el hash SHA-256 y el preview en nuestra DB.
- **FR-005**: El sistema MUST revocar keys en LiteLLM (`DELETE /key/delete`) antes de eliminarlas de nuestra DB.
- **FR-006**: El sistema MUST exponer un endpoint `GET /api/v1/keys/{key_id}/spend` que consulte `GET /key/info` en LiteLLM y retorne el gasto actual.
- **FR-007**: El sistema MUST exponer un endpoint `GET /api/v1/users/{user_id}/spend` que consulte `GET /user/info` en LiteLLM.
- **FR-008**: El sistema MUST exponer un endpoint `GET /api/v1/groups/{group_id}/spend` que consulte `GET /team/info` en LiteLLM.
- **FR-009**: La UI MUST mostrar el gasto real en la página de Usuarios, con barra de progreso respecto al `max_budget`.
- **FR-010**: Si LiteLLM no está disponible durante la creación de un recurso, el sistema MUST retornar HTTP 503 y NO persistir el registro localmente.
- **FR-011**: El `litellm/config.yaml` MUST tener habilitado `general_settings.store_model_in_db: true` y el `LITELLM_MASTER_KEY` configurado para habilitar la gestión de keys via API.

### Key Entities *(include if feature involves data)*

- **Group (actualizado)**: Agrega campo `litellm_team_id: String` — el ID del team en LiteLLM, usado para consultas de gasto y generación de keys de equipo.
- **User (actualizado)**: Agrega campo `litellm_user_id: String` — el ID del usuario en LiteLLM, usado para asociar keys personales.
- **APIKey (actualizado)**: Agrega campo `litellm_key_token: String` — los primeros 12 caracteres de la `sk-...` real, para poder referenciarla en LiteLLM. El campo existente `key_hash` pasa a hashear la key real de LiteLLM.
- **LiteLLMClient (nuevo servicio)**: Wrapper HTTP para la API de gestión de LiteLLM. No es una entidad de BD, es un servicio de infraestructura.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Una key generada via nuestra UI puede usarse directamente en un `curl` contra nuestro backend FastAPI (`Authorization: Bearer sk-...`) y la request se procesa correctamente.
- **SC-002**: Con budget=$0.01 asignado via UI, LiteLLM bloquea automáticamente la siguiente request después de que el gasto supera ese límite, sin intervención de nuestro backend.
- **SC-003**: La columna "Gasto actual" en la UI de Usuarios muestra valores mayores a $0.00 después de procesar requests reales desde el Playground.
- **SC-004**: Revocar una key via UI hace que la siguiente request con esa key retorne 401 en menos de 2 segundos.
- **SC-005**: Cero keys huérfanas en LiteLLM — cada key en LiteLLM debe tener un registro correspondiente en nuestra DB, y viceversa.

---

## Assumptions

- **LiteLLM acepta `LITELLM_MASTER_KEY`**: El master key configurado en `.env` es válido y LiteLLM está levantado con acceso a su DB antes de que el backend intente sincronizar.
- **Registros del MVP anterior son legacy**: Los users/groups/keys creados en el MVP (feature 001) no tienen `litellm_team_id` ni `litellm_user_id`. La UI los mostrará con gasto `-` sin errores. No se migrarán automáticamente.
- **Budget en USD**: LiteLLM trabaja con `max_budget` en USD. Los presupuestos en tokens del MVP se mantienen como información visual en nuestra UI pero no se sincronizan con LiteLLM (LiteLLM no tiene límites nativos de tokens por key en la versión OSS).
- **El cliente usa nuestro FastAPI como proxy**: Los clientes externos envían sus keys a nuestro backend (`http://basa-gateway:8081/api/v1/chat/completions`), no directamente a LiteLLM. Esto garantiza que las capas de seguridad (PII masking, guardianes) siempre se ejecutan.
- **LiteLLM OSS**: Se usa la versión open-source de LiteLLM, sin features Enterprise (auto-rotación de keys, SSO, etc.).
