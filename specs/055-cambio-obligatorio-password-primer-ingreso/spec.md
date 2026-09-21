# Feature Specification: Cambio obligatorio de contraseña en el primer ingreso

**Feature Branch**: `055-cambio-obligatorio-password-primer-ingreso`

**Created**: 2026-09-21

**Status**: 🟢 Implementada y verificada en ambas superficies (Guardian y Hub) — ver sección de
implementación.

**Repos que toca**: `cluna-8/elea` (`backend/src/models/user.py`, `backend/src/api/users.py`,
`backend/alembic/versions/`, `frontend/src/App.tsx`, `frontend/src/pages/UserPortal.tsx`,
`frontend/src/components/CambiarMiPasswordModal.tsx`, `frontend/src/services/auth.ts`,
`client/server.js`, `client/public/index.html`).

**Input**: pedido del dueño del producto (21-sep-2026): *"cuando se crea la password el usuario
en su primer ingreso lo pueda cambiar"*. Textual, sobre un sistema en producción — el pedido
explícito de encuadre fue evaluar el cambio, no romper nada de lo ya instalado en el cliente, y
planificar la aplicación al servidor real con cuidado.

## Diagnóstico verificado en código (21-sep)

| # | Qué se esperaba | Qué había en realidad |
|---|---|---|
| 1 | Al dar de alta o resetear la contraseña de un usuario, el sistema recuerda que esa contraseña la puso el admin | `User` (`backend/src/models/user.py:81-149`) no tenía **ningún** campo de este tipo — ni `must_change_password` ni equivalente. La contraseña de alta la fija el admin en el form (`UserCreate.password`, obligatoria desde que se sacó el `or "sentinel123"` legacy) y queda como definitiva, sin fecha de vencimiento ni marca de "pendiente de cambio". |
| 2 | El usuario puede cambiarla en su primer ingreso | Ya existía el endpoint (`POST /users/me/password`, `change_own_password`) y el modal (`CambiarMiPasswordModal.tsx`) para cambiarla **voluntariamente** desde el menú — pero nada lo disparaba automáticamente tras un alta o un reseteo, ni en Guardian ni en el Hub. |
| 3 | Esa protección le llega a los usuarios reales del cliente | **No, en la primera versión de este cambio.** El pedido se implementó primero solo en `frontend/` (el panel Guardian, puerto 8090). El dueño del producto aclaró en la revisión: *"nunca tocan Eleia Guardian, solo los admin lo hacen"* — los usuarios reales (rol `client`) entran exclusivamente por **Eleia Hub** (`client/`, puerto 8095), que es un frontend Node/Express + vanilla JS completamente aparte (`client/server.js` + `client/public/index.html`), no una vista más de `frontend/`. El Hub reusa el mismo backend y el mismo JWT (`client/server.js:119-127` llama a `POST /users/login`), y el campo nuevo le llegaba sin filtrar en la respuesta — pero nada en el Hub lo leía ni actuaba sobre él. Sin la segunda ronda de esta spec, la protección hubiera quedado sin efecto práctico para el cliente. |

**Es código de la base (Guardian), no de la localización argentina** — mismo criterio que otros
hallazgos de esta línea: se implementa acá porque acá se encontró y se pidió acá, y se documenta
para portar a Sentinel por handoff, no por gemelo reescrito.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Forzar el cambio tras un alta o un reseteo de admin (Priority: P1)

Un administrador da de alta a una persona (o le resetea la contraseña porque la olvidó) y le
comunica esa contraseña por un canal seguro. La persona, en su primer ingreso con esa contraseña,
debe poder — y debe estar obligada a — ponerse una propia que nadie más conozca, sin que eso
requiera un paso manual del admin ni un segundo endpoint que no existiera ya.

**Por qué esta prioridad**: es el pedido explícito del dueño del producto y la brecha real de
seguridad — sin esto, la contraseña que tipeó/vio/comunicó el admin queda vigente
indefinidamente, igual que el hallazgo original que ya había motivado sacar el default
`"sentinel123"` del alta.

**Independent Test**: dar de alta un usuario con una contraseña temporal, loguear con ese usuario
(en Guardian y en el Hub) y confirmar que aparece un modal de cambio de contraseña que no se
puede cerrar sin completarlo; completarlo y confirmar que el siguiente login (o un refresh de la
página) ya no lo vuelve a pedir. Repetir el mismo flujo para un reseteo de admin sobre un usuario
ya existente.

**Acceptance Scenarios**:

1. **Given** un admin da de alta un usuario con una contraseña, **When** ese usuario hace su
   primer login (en Guardian o en el Hub), **Then** se le presenta un modal obligatorio de
   cambio de contraseña, sin opción de cancelar ni cerrar.
2. **Given** el mismo escenario, **When** el usuario completa el cambio con una contraseña nueva
   válida, **Then** el modal se cierra, la sesión continúa con normalidad, y ese cambio queda
   persistido (no se le vuelve a pedir en un refresh ni en el siguiente login).
3. **Given** un admin resetea la contraseña de un usuario ya existente, **When** ese usuario
   vuelve a loguearse, **Then** ve el mismo modal obligatorio, igual que en el alta.
4. **Given** un usuario cambia su propia contraseña voluntariamente (sin que un admin la haya
   tocado), **When** completa ese cambio, **Then** no queda ningún flag pendiente ni se le fuerza
   nada en su próximo login.
5. **Given** cualquier usuario ya existente antes de este cambio, **When** hace login después de
   desplegarlo, **Then** entra con total normalidad, sin ningún modal — el cambio no afecta
   retroactivamente a nadie.

### Edge Cases

- **Bootstrap del primer admin** (`_bootstrap_admin_si_sin_dueno`, instalación sin dueño): no
  queda forzado a cambiar su contraseña — es un runbook especial y aparte, no un alta hecha por
  otro admin; no fue parte del pedido.
- **Cuentas de servicio** (`svc.*`, creadas por el instalador): el alta las marca igual que a
  cualquier persona (`must_change_password=True`), pero como no se loguean nunca por contraseña
  (usan API keys del motor), el flag queda sin efecto práctico — no se agregó un caso especial
  para excluirlas, por mantener el alta simple y porque no hay downside real.
- **Sesión ya abierta en el Hub cuando se cambia la contraseña**: el JWT sigue siendo válido tras
  el cambio (el endpoint de cambio de contraseña no lo revoca), así que el Hub actualiza el flag
  en su sesión en memoria (`client/server.js`) en el mismo request de éxito, sin depender de un
  nuevo login para que dejar de pedirlo.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El sistema DEBE marcar a un usuario como "debe cambiar su contraseña" cuando un
  admin fija su contraseña, ya sea en el alta o en un reseteo.
- **FR-002**: El sistema NO DEBE marcar ese flag cuando el propio usuario cambia su contraseña
  voluntariamente; ese cambio, al contrario, DEBE apagar el flag si estaba prendido.
- **FR-003**: El endpoint de login DEBE exponer ese flag de forma aditiva, sin romper el contrato
  existente de la respuesta para ningún consumidor actual (Guardian o Hub).
- **FR-004**: Ninguna de las dos superficies de acceso de usuarios reales (Guardian y Eleia Hub)
  DEBE dejar operar con normalidad a un usuario con el flag activo — el modal de cambio DEBE ser
  obligatorio (sin cerrar/cancelar) hasta completarse con éxito.
- **FR-005**: El cambio NO DEBE afectar a ningún usuario ya existente al momento del despliegue —
  la migración de base de datos DEBE dejarlos a todos con el flag apagado por default.
- **FR-006**: El cambio de contraseña forzado DEBE reusar el mismo endpoint y la misma política
  de validación que el cambio voluntario ya existente (`POST /users/me/password`) — sin una ruta
  ni una regla de contraseña nueva y paralela.

### Key Entities

- **User**: gana `must_change_password` (bool, `NOT NULL`, default `false`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Los usuarios existentes antes del despliegue hacen login idéntico a como lo hacían
  antes — verificado contra una base con usuarios reales de prueba previa: los 17 quedaron en
  `false` tras la migración.
- **SC-002**: Un usuario nuevo o reseteado ve el modal obligatorio tanto en Guardian
  (`frontend/`, rol admin/compliance/lectura) como en el Hub (`client/`, rol `client`) — las dos
  superficies por las que un usuario real puede entrar.
- **SC-003**: Tras completar el cambio, ni un refresh de página ni un nuevo login lo vuelven a
  pedir.

## Assumptions

- El backend es la única autoridad sobre cuándo se prende y apaga el flag; ambos frontends
  (Guardian y Hub) son puramente reactivos a lo que el login/las llamadas de cambio de contraseña
  devuelven — ninguno decide por su cuenta.
- El bloqueo es a nivel de interfaz (overlay que tapa el resto de la pantalla), no un guard del
  lado del servidor que rechace otras llamadas mientras el flag esté activo — igual que el resto
  de la UI de ambos productos, que confía en el backend para la autorización real de cada
  operación puntual, no en que el frontend "no deje" hacer algo.
- No se agrega expiración de contraseña ni política de rotación periódica — el pedido fue
  puntualmente sobre el primer ingreso tras un alta/reseteo, no un sistema de vencimiento.

## Implementación (21-sep)

### Ronda 1 — Guardian (`frontend/`)

- **FR-001/FR-005**: migración `199fe429762a_users_must_change_password.py` (agrega
  `must_change_password` a `users`, `server_default=false`, `down_revision` encadenado al head
  anterior `7a6fee614cfd`); mismo campo en el modelo `User`
  (`backend/src/models/user.py`).
- **FR-001**: se prende en `create_user` → `_insertar_usuario` (alta) y en
  `reset_user_password` (reseteo admin), ambos en `backend/src/api/users.py`.
- **FR-002**: se apaga en `change_own_password` (mismo archivo).
- **FR-003**: `_LoginSnapshot`/`_instantanea` propagan el campo; la respuesta de
  `POST /users/login` lo agrega dentro de `user`, sin tocar ningún campo existente.
- **FR-004** (Guardian): `App.tsx` (dashboard admin) y `UserPortal.tsx` (rol `client`/
  `clinician`) abren `CambiarMiPasswordModal` en modo `obligatorio` (sin botón "Cancelar") al
  detectar el flag en el login; el cierre persiste el estado en `localStorage` vía
  `authStorage.save` para no reabrirse en un refresh.

### Ronda 2 — Eleia Hub (`client/`), agregada tras la aclaración del dueño del producto

El Hub **no** heredaba nada de la ronda 1 — es un servicio Node/Express + HTML/JS vanilla
completamente separado de `frontend/`, con su propia pantalla de login (`client/public/
index.html`) y su propia sesión en memoria (`client/server.js`, `sessions` Map indexado por
cookie `sid`). El JWT y el campo `must_change_password` ya le llegaban (el Hub llama al mismo
`/users/login`), pero nada los leía.

- **FR-004** (Hub) y **FR-006**: nuevo endpoint proxy `POST /api/auth/change-password` en
  `client/server.js` — reenvía a `POST /users/me/password` del backend (misma validación, mismo
  error en español) y, en éxito, actualiza `session.user.must_change_password = false` en la
  sesión del Hub para reflejar lo que el backend ya hizo.
- Nuevo modal en `client/public/index.html` (`#modal-change-password`, reusa las clases
  `.modal-backdrop`/`.modal-box` ya existentes en el Hub): dos modos —
  - **Voluntario**: botón "Contraseña" nuevo en el header, junto a "Salir" (antes no existía
    ninguna forma de cambiar la propia contraseña desde el Hub).
  - **Obligatorio**: se abre solo desde `boot()` si `currentUser.must_change_password` es
    `true`; sin botón de cierre (`✕` y "Cancelar" ocultos), `z-index` por encima de toda la app;
    la única salida es completar el cambio con éxito.
- **Verificación end-to-end real** (no solo unitaria): stack local reconstruido desde cero
  (`db → nlp → redis → engine → backend`, respetando el orden real de `install.sh` — ver nota de
  proceso más abajo), usuario de prueba dado de alta desde Guardian, logueado en el Hub con su
  contraseña temporal → modal obligatorio con el branding real de Eleia → cambio completado →
  refresh sin volver a pedirlo. Confirmado también que un usuario preexistente entra sin modal
  en ambas superficies.

### Nota de proceso (no es parte del feature, pero se encontró haciendo esta verificación)

Armando el entorno de prueba local se encontró y documentó por separado (en
`deploy-privado-elea/MANUAL-CICD-ELEA.md`, sección de troubleshooting) un riesgo real de pérdida
de datos si `backend` se levanta manualmente **antes** que `engine` contra una base ya no vacía
(Prisma, el ORM del motor, puede correr un diff destructivo sobre tablas que no reconoce como
suyas). `install.sh` no lo sufre porque ya respeta el orden correcto — se señala para que nadie
lo repita levantando contenedores sueltos a mano.

### Suite y verificación

- TypeScript de `frontend/` compila sin errores (`tsc --noEmit`).
- `client/server.js` verificado con `node -c` (sintaxis) y probado en vivo contra el backend
  real vía navegador (Chrome, ambas superficies).
- No se corrió la suite de tests automatizados de backend en esta ronda (no se tocó lógica de
  negocio fuera de lo descrito arriba); la verificación fue end-to-end manual, en línea con la
  exigencia de la regla del equipo de no declarar un cambio probado sin una prueba idéntica al
  uso real del cliente.
