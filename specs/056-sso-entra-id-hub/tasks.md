---
description: "Tareas de la spec 056 — Ingreso con Microsoft Entra ID (SSO) en el Hub"
---

# Tasks: Ingreso con Microsoft Entra ID (SSO) en el Hub

**Input**: `specs/056-sso-entra-id-hub/`: [plan.md](plan.md), [spec.md](spec.md) (enmendada por
clarify el 2026-10-05), [research.md](research.md) (D1 a D15), [data-model.md](data-model.md),
[contracts/](contracts/), [quickstart.md](quickstart.md),
[DESPLIEGUE-Y-REVERSION.md](DESPLIEGUE-Y-REVERSION.md).

**Regenerado el 2026-10-05** después del QA crítico ([qa-plan.md](qa-plan.md)). Las tareas se
renumeraron. Los IDs que cita qa-plan.md son los de la versión anterior. La correspondencia de
cada hallazgo con su tarea nueva está en research.md, §Trazabilidad del QA.

**Tests**: **obligatorios** (AGENTS.md: TDD donde hay código nuevo). En cada tramo los tests se
escriben primero y **tienen que fallar** antes de la implementación. Eso incluye la pantalla del
Hub (research D13) y la marca blanca (research D14).

**Organización**: por historia de usuario (US1 a US4 de spec.md) y por **tramo**. Un tramo es un
paquete de ≤ 15 tareas que se despacha a **un** worker. Los tramos que corren en paralelo no
comparten ningún archivo (ver "Propiedad de archivos por tramo").

## Formato: `- [ ] T### [P?] [US?] [repo: …] Descripción con ruta`

- **[P]**: paralelizable **dentro del tramo** (otro archivo, sin dependencia pendiente).
- **[US#]**: historia de spec.md. Setup, Foundational y Polish no llevan historia.
- **[repo: elea]** = `cluna-8/elea` (este repo). **[repo: elea-installer]** =
  `cluna-8/elea-installer` (en local: `/home/drexgen/Documents/ELEA/LLMADMIN-Elea/elea-installer`).
- Commits: en ramas de feature, **nunca a `main`**; el trabajo termina en PR. Los commits de
  **base** (`backend/src/sso/`, `frontend/`, `docs/`) van separados de los del **Hub**
  (`client/`) y del **instalador**, con prefijo `base(sso)`, `base(panel)`, `hub(sso)` o
  `instalador`, para el orden de cherry-pick del HANDOFF.

**Base vs. línea** (aclaración del owner, 2026-10-05): `cluna-8/sentinel` es el upstream de la
base. Los tramos A y C (`backend/src/sso/`, `frontend/`) hacen **lo mínimo y retrocompatible**:
sin renombres, sin refactors oportunistas, campos nuevos opcionales y comportamiento por defecto
igual al de hoy. Los tramos B y D (Hub e instalador) pueden divergir de Sentinel.

## Tramos y propiedad de archivos

| Tramo | Fases | Tareas | Repo | Archivos (exclusivos del tramo) | Puede correr en paralelo con |
|---|---|---|---|---|---|
| **0** Setup | 1 | T001–T003 (3) | elea | rama; `.gitignore` (solo las dos entradas de prueba local). Licencia y compose de prueba quedan fuera de git | — (va primero) |
| **A** Base Guardian | 2 | T004–T009 (6) | elea | `backend/src/sso/api.py`, `backend/tests/integration/test_sso_api.py` | B, C, D |
| **B** Hub | 3, 4 | T010–T023 (14) | elea | `client/sso.js` (nuevo), `client/server.js`, `client/public/sso-ui.js` (nuevo), `client/public/index.html`, `client/README.md`, `client/tests/unit/sso-pendientes-056.test.js`, `client/tests/unit/sso-ui-056.test.js`, `client/tests/unit/whitelabel-hub-056.test.js`, `client/tests/contract/test_sso_hub_056.test.js`, `client/tests/integration/test_sso_flujo_056.test.js` | A, C, D |
| **C** Panel | 5 | T024–T029 (6) | elea | `frontend/src/services/api.ts`, `frontend/src/pages/LoginPage.tsx`, `frontend/src/pages/UsersPage.tsx`, `frontend/tests/contract/UsersPage.sso-config.test.tsx`, `frontend/tests/contract/LoginPage.sso-origin.test.tsx` | A, B, D |
| **D** Instalador y release | 6 | T030–T038 (9) | elea-installer + elea | `elea-installer/{docker-compose.yml,.env.example,install.sh,README.md,.gitignore,license/.gitkeep}`, `deploy/release/publish-elea.sh`, `deploy/release/checks/test_publish_elea_latest.sh` (nuevo), `deploy/Makefile` (target `check-release-publish`) | A, B, C |
| **E** Guía, docs y cierre | 7, 8 | T039–T048 (10) | elea | `docs/docs/install-deploy/sso.md`, `docs/docs/api-reference/openapi.json` (generado), `deploy/Makefile` (target `check-hub-whitelabel`; E corre después de D, nunca en paralelo), `specs/056-sso-entra-id-hub/{SOLICITUD-A-ELEA.md,DESPLIEGUE-Y-REVERSION.md,RESULTADOS-PRUEBA-LOCAL.md,HANDOFF-elea-a-sentinel.md}`, `specs/017-auth-rbac-sso/RUNBOOK-e2e-sso.md` | — (va al final) |

B y C programan contra el **contrato** de A ([guardian-sso-api.md](contracts/guardian-sso-api.md))
con dobles HTTP o mocks de `fetch`. No necesitan A mergeado para sus tests. La integración real
se valida en el tramo E (T046).

---

## Phase 1: Setup — Tramo 0

**Purpose**: rama, línea base y entorno de prueba. Lo hace el coordinador o un solo worker antes
de despachar A a D.

- [ ] T001 [repo: elea] Crear la rama `056-sso-entra-id-hub` desde `main` con los artefactos de `specs/056-sso-entra-id-hub/` (sin commits a `main`; cada tramo trabaja en su rama hija y termina en PR contra esta rama)
- [ ] T002 [repo: elea] Correr la línea base de gates y anotar los conteos para comparar al cierre: `cd client && npm test`, `cd frontend && npm test`, `docker compose run --rm --no-deps backend pytest tests/ -q`, `make -C deploy check`. Los comandos con Docker se corren **solo con aviso previo al owner**, que prepara la PC
- [ ] T003 [P] [repo: elea] Preparar el entorno de prueba de GUIA-PRUEBA-LOCAL-SSO.md §1 a §3:
  - directorio Entra **de prueba**, con las URIs Web `http://localhost:8090/sso/callback`, `http://localhost:8095/sso/callback` y `https://localhost:8443/sso/callback` (esta, para el ingreso por HTTPS local de quickstart §3b);
  - agregar a `.gitignore` las entradas `backend/config/licenses/dev-sso-local.lic` y `docker-compose.sso-local.yml` (B9 del QA: hoy no están ignoradas);
  - verificar con `git check-ignore -v` que las dos quedan ignoradas, y con `git status` que no aparecen.

  Commit `chore: …` aparte

**Checkpoint**: rama creada, línea base anotada, A a D despachables en paralelo.

---

## Phase 2: Foundational — Base Guardian (Tramo A)

**Purpose**: los cambios de base que consumen el Hub y el panel: `return_origin` (research D4,
FR-015) y la auditoría de los rechazos con tope de flujo y de canje (research D6 + F1, FR-012).
Genérico y sin strings de Elea: viaja a Sentinel por cherry-pick. `jit.py`, `entra.py`,
`registry.py` y `admin_api.py` **no se tocan** (FR-007).

**Tramo A** · repo elea · 6 tareas · contrato: [guardian-sso-api.md](contracts/guardian-sso-api.md)

- [ ] T004 [repo: elea] Tests de `return_origin` en `backend/tests/integration/test_sso_api.py`, junto a `test_available_*` (`:196-228`). Casos de [guardian-sso-api.md](contracts/guardian-sso-api.md) §1:
  - URI `https` sin puerto, con puerto explícito y con el puerto por defecto (`:443` → sin puerto, B5 del QA);
  - mayúsculas en esquema y host → minúsculas;
  - credenciales en la URI → nunca aparecen;
  - variable ausente, vacía o relativa → `null`;
  - flag apagado sigue en 403;
  - la respuesta sigue sin `config` ni secreto.

  Deben **fallar**
- [ ] T005 [repo: elea] Tests de auditoría y tope en `backend/tests/integration/test_sso_api.py`, junto a `test_callback_sin_cookie_400` y siguientes (`:322-430`). Cada caso de la tabla de [guardian-sso-api.md](contracts/guardian-sso-api.md) §2 deja **exactamente un** `auth_sso_denied`, incluidos el `404 sso_no_configurado` y el `500 sso_redirect_uri_no_configurado` del callback (F8 del QA). Ninguna columna del evento contiene el `state` ni el `code` usados, y el status y el `detail` no cambian. Casos del **tope**, con el reloj de la ventana inyectado:
  - **flujo**: `tope + 5` rechazos de flujo dejan exactamente `tope` eventos y un warning con el conteo omitido;
  - **canje** (F1 del QA): cookie válida + `code` basura, `tope + 5` veces → exactamente `tope` eventos y `tope` llamadas al proveedor (el doble del proveedor cuenta las llamadas), los `tope + 5` con `401 sso_identidad_no_verificada` intacto, y un warning con el conteo omitido;
  - **contadores independientes**: agotar el de flujo no impide un canje, y agotar el de canje no impide auditar un rechazo de flujo;
  - la ventana siguiente vuelve a auditar y a llamar al proveedor;
  - los rechazos de identidad (`api.py:313`, `:379`) se auditan con los dos topes agotados.

  Deben **fallar**
- [ ] T006 [repo: elea] Implementar `return_origin` en `sso_available` (`backend/src/sso/api.py:179-200`). Helper que lee `SENTINEL_SSO_REDIRECT_URI` con `urllib.parse.urlsplit` y arma el origen con `scheme`, `hostname` y `port` (**nunca** `netloc`), en minúsculas y sin el puerto por defecto; si no, `None`. Va en los dos caminos (`enabled` true y false). `enabled` no cambia de regla. T004 en verde
- [ ] T007 [repo: elea] Auditar los rechazos de flujo de `sso_callback` con `_auditar_denegado(db, tenant_id)` (`backend/src/sso/api.py:339-347`) **antes** de levantar el error:
  - cookie ausente o inválida (`_leer_estado`, `:260`);
  - `state` distinto (`:264-268`);
  - `code` ausente (`:269-273`);
  - proveedor apagado (`_cargar_config`, `:275`; hoy fuera de todo `try`);
  - proveedor cambiado (`:276-282`);
  - URI de retorno faltante (resolver `_redirect_uri` antes del `try` del canje, `:293`, para que `except HTTPException: raise` de `:295-296` no la deje pasar sin auditar).

  Sumar el **tope de flujo**: constante `_TOPE_DENEGADOS_POR_MIN = 30`, ventana de 60 s, por proceso, reloj inyectable. El excedente no escribe filas y se resume en un `logger.warning` metadata-only. El veredicto no cambia si auditar falla ni si se agota el tope. Casos de flujo de T005 en verde
- [ ] T008 [repo: elea] Implementar el **tope de canje** (research D6 + F1) en `sso_callback` (`backend/src/sso/api.py:286-307`). Usa la misma constante y la misma ventana que T007, con **contador propio**:
  - antes de `provider.exchange_code`, si los canjes fallidos de la ventana ya llegaron al tope: no llama al proveedor, no escribe fila, suma al conteo omitido y responde el mismo `401 sso_identidad_no_verificada`;
  - si el canje falla dentro del tope: suma al contador y audita como hoy (`:302`).

  `entra.py` no se toca. T005 completo en verde
- [ ] T009 [repo: elea] Gate del tramo: `docker compose run --rm --no-deps backend pytest tests/ -q` en verde (con aviso previo al owner), incluidos `test_sso_api.py`, `test_sso_config_api.py` y `test_role_matrix.py`. Commit `base(sso): …` que **solo** contenga `backend/` y PR a `056-sso-entra-id-hub`

**Checkpoint**: la API de base cumple su contrato; B y C pueden integrarse contra ella.

---

## Phase 3: User Story 1 — Un empleado entra al Hub con su cuenta corporativa (P1) 🎯 MVP — Tramo B

**Goal**: "Ingresar con Microsoft" en el Hub termina en la misma sesión que el login con
contraseña, sin que el token toque la URL ni el navegador (FR-001 a FR-004, FR-006, FR-008,
FR-013 a FR-016).

**Independent Test**: con la config cargada, un usuario existente entra por Microsoft y usa chat,
Documentos, Planillas y Presentaciones con su rol, grupo y presupuesto (quickstart §3, casos 1 a 5).

**Tramo B** (fases 3 y 4) · repo elea · 14 tareas · contrato: [hub-sso.md](contracts/hub-sso.md)

### Tests (escribir primero; deben fallar)

- [ ] T010 [P] [US1] [repo: elea] Tests unitarios de `client/sso.js` en `client/tests/unit/sso-pendientes-056.test.js`:
  - almacén de pendientes: guardar por `sid` con `atadura` opcional, reemplazo del mismo `sid`, `tomar` que borra (un solo uso), vencimiento a los 10 min con reloj inyectable;
  - almacén **lleno** (F5 del QA, research D11, FR-016): barre vencidos y, si sigue lleno, **rechaza el nuevo** sin expulsar a ningún pendiente en curso;
  - límite de ritmo de `/sso/login`: `SSO_LOGIN_POR_MIN` aceptados por ventana, el siguiente rechazado, la ventana siguiente vuelve a aceptar;
  - comparación de `state` y de `atadura` con `timingSafeEqual`: largos distintos no coinciden y no lanzan;
  - mapeo status/`detail` → código de error de la tabla de [hub-sso.md](contracts/hub-sso.md) §4, completo, incluido el desconocido → `sso_error`
- [ ] T011 [P] [US1] [repo: elea] Tests de contrato en `client/tests/contract/test_sso_hub_056.test.js` con el doble HTTP de `client/tests/mock-servers.js` ([hub-sso.md](contracts/hub-sso.md) §7, tests 1 a 5):
  - `GET /api/auth/sso/available` fail-closed: 200 `enabled:true`, 200 `enabled:false`, 403, 500, cuerpo no JSON, backend caído; `return_origin` pasa tal cual, incluido `null` (F4); `Cache-Control: no-store` (B6); nunca expone `provider_type`;
  - `GET /sso/login` guarda el pendiente y responde 302 a la `Location` del backend con `Cache-Control: no-store` y `Referrer-Policy: no-referrer`;
  - con retorno `https://` emite `__Host-sso_flow` con `Secure; HttpOnly; Path=/; SameSite=Lax`; con retorno `http://localhost` no la emite (F6, research D12);
  - primera visita **sin** `elea_rag_sid` y con retorno `https://`: la respuesta trae los **dos** `Set-Cookie` (el `sid` nuevo del middleware y `__Host-sso_flow`) y el pendiente queda bajo ese `sid` ([hub-sso.md](contracts/hub-sso.md) §2);
  - pasado el límite de ritmo → `sso_reintentar` sin llamar al backend; con el almacén lleno → `sso_reintentar` y un pendiente previo sigue consumible (F5, FR-016);
  - sin `Set-Cookie` o con status ≠ 302 → `302 /?sso_error=…` según §4
- [ ] T012 [P] [US1] [repo: elea] Tests de integración del camino feliz en `client/tests/integration/test_sso_flujo_056.test.js`:
  - login → callback con el mismo `sid`, `state` y atadura → el backend recibe `Cookie: sentinel_sso_state=…`;
  - sesión con `auth_method:'sso'`, `sid` **rotado** (`Set-Cookie` nuevo, con `Secure` si el retorno es `https://`, y el `sid` viejo sin sesión) y `302 /`;
  - `code` y `state` con `&`, `=` y `#` llegan al backend como un valor cada uno (B3 del QA);
  - ningún cuerpo ni cabecera del Hub contiene el `access_token`;
  - `GET /api/user/current` trae `user.auth_method`;
  - `POST /api/auth/change-password` con sesión SSO → 409 sin llamar al backend (FR-008)
- [ ] T013 [US1] [repo: elea] Tests de **atadura al navegador** (FR-016; research D1 y D12, CSRF de login) en `client/tests/integration/test_sso_flujo_056.test.js`:
  - callback desde **otro** `sid` → `sso_reintentar`, y el backend recibe la llamada **sin** cabecera `Cookie` (para auditar);
  - callback con el `sid` correcto pero **sin** la cookie `__Host-sso_flow`, o con otra (cookie `sid` inyectada, F6) → `sso_reintentar`, sin canje con cookie;
  - `state` distinto → no hay canje con cookie;
  - callback repetido → el segundo falla;
  - pendiente vencido → falla;
  - `Map` vacío, como tras un reinicio → `sso_reintentar`;
  - `error=access_denied` del directorio → `sso_cancelado`
- [ ] T014 [P] [US1] [repo: elea] Tests de la **pantalla** (F2 del QA, research D13) en `client/tests/unit/sso-ui-056.test.js`, con `node --test` sobre `client/public/sso-ui.js` ([hub-sso.md](contracts/hub-sso.md) §7, tests 17 a 20):
  - `destinoBoton`: `enabled:false` → sin botón (US2 AS3); `enabled:true` + `return_origin:null` → sin botón (FR-001, F4); mismo origen → `/sso/login`; otro origen → `${return_origin}/sso/login`; origen que no es `http(s)` → sin botón;
  - `mensajeError`: cada código de §4 → su texto; desconocido, vacío y con HTML → el genérico, que no contiene el valor recibido; todos recuerdan el acceso con contraseña (FR-006, US2 AS2);
  - `ofrecerCambioContrasena`: `auth_method:'sso'` → `false` (FR-008, US1 AS5);
  - lectura estática de `client/public/index.html`: carga `/sso-ui.js`, usa las tres funciones y no escribe el error de `sso_error` con `innerHTML`
- [ ] T015 [P] [US1] [repo: elea] Test de **marca blanca** del Hub (F3 del QA, FR-013, FR-014, research D14) en `client/tests/unit/whitelabel-hub-056.test.js`, solo con `node:fs` y sin dependencias:
  - `client/sso.js` y `client/public/sso-ui.js` no contienen ningún nombre de `deploy/release/checks/prohibited_names.txt`, de los motores internos de documentos y presentaciones (lista local del test) ni `Elea`/`Eleia`;
  - `client/public/index.html` y `client/server.js` no contienen ningún nombre de `prohibited_names.txt`.

  Debe **fallar** mientras los dos archivos nuevos no existan

### Implementación

- [ ] T016 [US1] [repo: elea] Crear `client/sso.js` (CommonJS, sin dependencias nuevas): almacén de flujos pendientes con rechazo del nuevo cuando está lleno y límite de ritmo ([data-model.md](data-model.md) §Flujo SSO pendiente y §Contador de ritmo), comparación en tiempo constante y mapeo de errores de [hub-sso.md](contracts/hub-sso.md) §4. Sin strings de marca. T010 en verde
- [ ] T017 [US1] [repo: elea] Implementar `GET /api/auth/sso/available` en `client/server.js`, junto a `/api/branding` (`:314-316`): proxy fail-closed con timeout de 3 s a `{ELEA_BACKEND_URL}/auth/sso/available`, respuesta `{enabled, return_origin}` con `Cache-Control: no-store`
- [ ] T018 [US1] [repo: elea] Implementar `GET /sso/login` en `client/server.js` ([hub-sso.md](contracts/hub-sso.md) §2):
  - límite de ritmo primero;
  - `fetch` con `redirect:'manual'`;
  - `Headers.getSetCookie()` para extraer `sentinel_sso_state`;
  - `state` y `redirect_uri` del query de `Location`;
  - con `redirect_uri` `https://`, cookie `__Host-sso_flow` y `atadura` en el pendiente, **agregada** al `Set-Cookie` que pueda haber dejado el middleware (`:93`), nunca pisándolo;
  - pendiente guardado por `req.sid` (`:88-97`), o `sso_reintentar` si el almacén está lleno;
  - 302 al IdP con `no-store` y `no-referrer`;
  - errores según §4.

  Tests de `/sso/login` de T011 en verde
- [ ] T019 [US1] [repo: elea] Implementar en `GET /sso/callback` (`client/server.js`) la **atadura** (FR-016; research D1, requisitos 1 a 3, y D12):
  - tomar y borrar el pendiente del `req.sid` siempre, y borrar `__Host-sso_flow`;
  - validar `state` y, si el pendiente tiene `atadura`, la cookie `__Host-sso_flow`, con `client/sso.js`;
  - sin pendiente, vencido, con `state` o atadura distintos, o con `error=` del directorio: llamar al callback del backend **sin** cookie (o con la cookie válida si hubo `error=`), solo para que el backend audite, y redirigir con el código de §4;
  - armar la URL al backend con `URLSearchParams` (B3).

  T013 en verde
- [ ] T020 [US1] [repo: elea] Completar el camino feliz de `GET /sso/callback` y las rutas afectadas en `client/server.js`:
  - canje con `Cookie: sentinel_sso_state=…`;
  - **rotación de `sid`** (research D1, requisito 4) con los mismos atributos de cookie de `:93`, más `Secure` si el pendiente tenía `atadura` (D12); si el middleware ya puso un `Set-Cookie` en esta respuesta, se reemplaza: una sola cookie `elea_rag_sid` por respuesta;
  - `setSession` con el **mismo token** que emite Guardian (FR-002), `auth_method:'sso'` y `302 /`; el cuerpo del backend nunca se loguea;
  - `user.auth_method` en `GET /api/user/current` (`:318-333`);
  - 409 en `POST /api/auth/change-password` (`:284-309`) para sesiones SSO.

  `POST /api/auth/login` (`:258-273`) **no se toca**. T011 y T012 en verde
- [ ] T021 [US1] [repo: elea] Crear `client/public/sso-ui.js` (módulo puro: `destinoBoton`, `mensajeError` con la tabla de §4 y el texto neutro de `sso_identidad_no_verificada` de research D15, `ofrecerCambioContrasena`; exporta por `module.exports` y por `window.SsoUi`) y cablearlo en `client/public/index.html` ([hub-sso.md](contracts/hub-sso.md) §6):
  - `<script src="/sso-ui.js">` antes del script inline (`:976`);
  - al mostrar el overlay (`boot`, `:1051-1056`), consultar `/api/auth/sso/available` y dibujar "Ingresar con Microsoft" bajo el formulario (`:444-455`) solo si `destinoBoton` devuelve un destino;
  - `?sso_error=` → `mensajeError` en `#login-error` con `textContent`, y limpiar la barra con `history.replaceState`;
  - `ofrecerCambioContrasena` gobierna el botón "Contraseña" (`:542`) y el modal (`:1067`).

  Textos sin marca fija; la marca sale de `/api/branding`. T014 y T015 en verde

**Checkpoint**: US1 completa con el doble del backend; lista para la prueba real en T046.

---

## Phase 4: User Story 2 — Nada de lo que funciona hoy deja de funcionar (P1) — Tramo B (continúa)

**Goal**: login con contraseña, cambio obligatorio de la 055 y motores idénticos. SSO
degradable sin afectar el resto (FR-005, FR-006).

**Independent Test**: suite del Hub en verde con los tests de regresión. En vivo: quickstart §4.

- [ ] T022 [US2] [repo: elea] Tests de regresión y degradación en `client/tests/contract/test_sso_hub_056.test.js`:
  - `POST /api/auth/login` con status, cuerpo y sesión idénticos a hoy, incluido `must_change_password` que pasa al `user`, y la cookie `elea_rag_sid` **sin** `Secure` (el camino con contraseña no cambia);
  - `change-password` con sesión de contraseña proxyado como hoy;
  - con licencia sin `sso` (backend 403) o backend caído, `available` → `enabled:false` y el login con contraseña sigue operativo;
  - backend caído durante `/sso/login` → `sso_proveedor_caido` sin afectar otras rutas;
  - con el límite de ritmo agotado, `POST /api/auth/login` sigue operativo.

  **Excepción a "los tests fallan primero"**: son de regresión y deben pasar sin tocar código de producción. Si alguno falla, se corrige en `client/server.js` dentro de este tramo
- [ ] T023 [US2] [repo: elea] Gate del tramo:
  - `cd client && npm test` en verde completo (incluye `smoke.test.js`, las suites de 044, 050, 051 y 053, y `whitelabel-hub-056.test.js`);
  - actualizar `client/README.md` (§Rutas con las tres rutas nuevas y `/sso-ui.js`; §Sesiones con flujos pendientes, atadura `__Host-`, límite de ritmo, rotación de `sid` y "sin variables de entorno nuevas");
  - commit `hub(sso): …` que **solo** contenga `client/`, y PR a `056-sso-entra-id-hub`

**Checkpoint**: US1 y US2 completas del lado del Hub.

---

## Phase 5: User Story 3 — El admin activa Entra desde el panel (P1) — Tramo C

**Goal**: formulario de config SSO en la pestaña "Autenticación & SSO" sobre la API existente, y
el botón del panel solo cuando el retorno es el propio panel (FR-009, FR-015, research D4 y D10).

**Independent Test**: vitest en verde. En vivo: quickstart §2 y §4.4 (apagar desde el panel
hace desaparecer el botón del Hub sin reiniciar).

**Tramo C** · repo elea · 6 tareas · contrato: [panel-sso-config.md](contracts/panel-sso-config.md)

- [ ] T024 [P] [US3] [repo: elea] Tests en `frontend/tests/contract/UsersPage.sso-config.test.tsx`, según [panel-sso-config.md](contracts/panel-sso-config.md) §3. Casos:
  - `404` → formulario vacío;
  - `200` precarga sin secreto;
  - secreto vacío → el `PUT` **no** lleva `client_secret`;
  - secreto cargado → se manda una vez y el campo queda vacío;
  - errores `sso_habilitado_sin_secreto` y `sso_cifrado_no_disponible` visibles;
  - `compliance_officer` sin formulario y sin llamada al `GET` de config (US3 AS5);
  - `403` sin formulario;
  - marca blanca de los textos del formulario y sus errores (FR-013, FR-014, research D14).

  Deben **fallar**
- [ ] T025 [P] [US3] [repo: elea] Tests en `frontend/tests/contract/LoginPage.sso-origin.test.tsx`. El botón se ve con `return_origin` `null` o igual a `window.location.origin`, y se oculta con otro origen y con `enabled:false` (FR-015). Deben **fallar**
- [ ] T026 [US3] [repo: elea] `frontend/src/services/api.ts`:
  - `getSsoAvailable` (`:687-699`) devuelve también `return_origin`, con el mismo criterio fail-closed;
  - agregar `getSsoConfig()` y `putSsoConfig()` sobre `/auth/sso/config`, con el `client_secret` solo si viene no vacío;
  - nunca loguear el secreto
- [ ] T027 [US3] [repo: elea] `frontend/src/pages/LoginPage.tsx` (`:43`, `:155-162`): dibujar el botón solo si `enabled` y `return_origin` es `null` o igual a `window.location.origin`. T025 en verde
- [ ] T028 [US3] [repo: elea] `frontend/src/pages/UsersPage.tsx`: en la pestaña "Autenticación & SSO" (`:1271-1376`), reemplazar el aviso "contacte a su equipo de soporte" (`:1372-1375`) por el formulario de Entra. Incluye:
  - campos tenant del directorio, identificador de la aplicación, secreto e interruptor;
  - visibilidad: **solo** `super_admin` y `tenant_admin` (US3 AS5); los demás roles ven solo la tarjeta de estado;
  - manejo de errores según el contrato;
  - el secreto no queda en el estado de React después del `PUT`.

  La tarjeta de estado y la grilla de "Próximamente" no cambian. T024 en verde
- [ ] T029 [US3] [repo: elea] Gate del tramo:
  - `cd frontend && npm test` y `cd frontend && npm run build` en verde;
  - commit `base(panel): …` que **solo** contenga `frontend/`, y PR a `056-sso-entra-id-hub`

**Checkpoint**: el admin activa y desactiva desde el panel; el panel no ofrece un botón que
vuelva al Hub.

---

## Phase 6: User Story 3 (cont.) — Instalador y publicación: conserva la config, arranca sin SSO, vuelta atrás real — Tramo D

**Goal**: los cambios previos de DESPLIEGUE-Y-REVERSION.md (FR-009b, FR-011, US3 AS3 y AS4):
`SENTINEL_SSO_REDIRECT_URI` desde `.env`, `ELEA_TAG`, licencia con `sso` montada desde el host y
candidatas publicadas sin mover `latest`, protegido en el gate. **Sin** servicio TLS (research
D7, opción B).

**Independent Test**: `docker compose config` renderiza lo esperado con y sin variables; el
stub de `docker` prueba que `LATEST=0` no toca `:latest`, y corre en `make -C deploy check`. En
vivo: quickstart §5.

**Tramo D** · repos elea-installer y elea · 9 tareas · contrato:
[instalador-y-release.md](contracts/instalador-y-release.md)

- [ ] T030 [P] [US3] [repo: elea] Test `deploy/release/checks/test_publish_elea_latest.sh`. Pone un `docker` *stub* en el `PATH` que registra argumentos, corre `deploy/release/publish-elea.sh` con `ONLY=rag-client` y verifica que con `LATEST=0` no aparece ningún `:latest` en `build`/`push` y que con el default sí. Debe **fallar**. Después implementar `LATEST` (default `1`) en `deploy/release/publish-elea.sh` (`:34`, `:42`) y documentar los dos modos en su encabezado de uso. Test en verde. Commit `release: …` aparte
- [ ] T031 [US3] [repo: elea] `deploy/Makefile` (F9 del QA, research D14): target `check-release-publish` que corre `deploy/release/checks/test_publish_elea_latest.sh`, agregado a `.PHONY` y a la lista de `check` (`:42`), con un comentario del porqué al estilo de los demás targets. Verificar con `make -C deploy check-release-publish` (sin Docker real). Va en el mismo commit `release: …` que T030
- [ ] T032 [P] [US3] [repo: elea-installer] `docker-compose.yml`: las seis imágenes propias pasan a `:${ELEA_TAG:-latest}` (`elea-guardian-nlp`, `-engine`, `-backend`, `-frontend`, `elea-rag-client`, `elea-tabular`). Postgres, redis y los motores de terceros no cambian
- [ ] T033 [US3] [repo: elea-installer] `docker-compose.yml`, servicio `backend` (`:87-128`):
  - `SENTINEL_LICENSE_TOKEN_FILE=${SENTINEL_LICENSE_TOKEN_FILE:-/app/config/licenses/dev-demo.lic}`;
  - `SENTINEL_SSO_REDIRECT_URI=${SENTINEL_SSO_REDIRECT_URI:-}`;
  - volumen `./license:/app/config/licenses/host:ro`.

  `SENTINEL_ALLOW_DEV_LICENSE=true` se mantiene (deuda conocida, research D8). Crear `license/.gitkeep` y agregar `license/*.lic` a `.gitignore`
- [ ] T034 [P] [US3] [repo: elea-installer] `.env.example`: bloques comentados "Versión de imágenes" (`ELEA_TAG`) e "Ingreso con Microsoft (opcional)" (`SENTINEL_SSO_REDIRECT_URI` vacía por defecto, con la nota "vacía = sin botón en el Hub"; `SENTINEL_LICENSE_TOKEN_FILE`), con marcadores `<nombre-del-hub>` y sin valores de Elea
- [ ] T035 [US3] [repo: elea-installer] `install.sh`:
  - `docker pull` del motor (`:56`) con `${ELEA_TAG:-latest}`;
  - imprimir el tag en uso en el resumen final;
  - avisar sin cortar si `SENTINEL_SSO_REDIRECT_URI` no está vacía y no es `https://` ni `http://localhost`;
  - cortar con un mensaje claro si `SENTINEL_LICENSE_TOKEN_FILE` apunta a `/app/config/licenses/host/…` y el archivo no está en `./license/`
- [ ] T036 [US3] [repo: elea-installer] `README.md`:
  - HTTPS con el proxy TLS del cliente (tabla de [instalador-y-release.md](contracts/instalador-y-release.md) §4: nombre, certificado, reenvío de todas las rutas a `:8095`, cabeceras, salida a `login.microsoftonline.com`);
  - licencia en `./license/`;
  - vuelta atrás por niveles con `ELEA_TAG` (nivel 1: vaciar la URI oculta el botón del Hub)
- [ ] T037 [US3] [repo: elea-installer] Verificación del tramo:
  - `docker compose config` sin variables nuevas renderiza `:latest`, `dev-demo.lic` y la URI vacía;
  - con `ELEA_TAG=056-rc1` renderiza ese tag en las seis imágenes;
  - `bash -n install.sh` (y `shellcheck`, si está instalado);
  - commit `instalador: …` en una rama del repo del instalador, **nunca `main`**, y PR.

  `docker compose config` solo renderiza (no levanta contenedores), pero igual se avisa al owner antes
- [ ] T038 [US3] [repo: elea] **Manual, lo hace el dueño de la clave**: emitir la licencia de Elea con `backend/scripts/issue_license.py --feature-flags monitor,sso`, con la misma clave y `kid`, los mismos asientos y el mismo vencimiento que la vigente (research D8). Se entrega **fuera de git**, para `./license/` del server. Pasar el `lic_id` (no el archivo) al tramo E para DESPLIEGUE y el HANDOFF

**Checkpoint**: el instalador arranca igual sin variables nuevas, fija versión y toma la licencia
del host. Las candidatas se pueden publicar sin riesgo y el gate lo protege.

---

## Phase 7: User Story 4 — El IT sabe qué registrar en Entra (P3) — Tramo E

**Goal**: guía corta y marca-neutra para registrar la aplicación con retorno al Hub, más el
proxy TLS y la activación desde el panel (FR-010, FR-013).

**Independent Test**: alguien que no participó registra la aplicación en un directorio de prueba
siguiendo solo la guía, y el ingreso por el Hub funciona (US4 AS1).

**Tramo E** (fases 7 y 8) · repo elea · 10 tareas · arranca cuando A a D están mergeados en
`056-sso-entra-id-hub`

- [ ] T039 [US4] [repo: elea] `docs/docs/install-deploy/sso.md`, sección nueva "Ingreso por el Hub de usuarios", **marcada "solo si la instalación tiene Hub"** (B8 del QA: Sentinel puede no tenerlo). Template GUÍA de `docs/README.md` y leyenda honesta. Contenido:
  - el flujo con el Hub como intermediario (diagrama de secuencia) y la URI de retorno que apunta al Hub;
  - qué registrar: plataforma Web, `https://<nombre-del-hub>/sso/callback`, `openid profile email` + `User.Read`, consentimiento, vencimiento del secreto, "asignación requerida" recomendada;
  - el cruce UPN ↔ email antes de activar;
  - qué mensaje ve el usuario cuando vence el secreto o el directorio no responde ("No se pudo confirmar el ingreso con Microsoft…") y dónde ver la causa en el log del backend (research D15, F10);
  - límites conocidos: baja en Entra sin SCIM y sesión vigente hasta 24 h; reinicio del Hub; cerrar sesión en el Hub no cierra la de Microsoft en una PC compartida (B1); la cookie de sesión lleva `Secure` solo en el camino SSO con HTTPS (D12); `return_origin`; durante una ráfaga de ingresos falsos el botón puede fallar para todos (tope de FR-012).

  Solo "Guardian", "Hub" y marcadores: sin nombres de Elea ni de componentes internos
- [ ] T040 [US4] [repo: elea] `docs/docs/install-deploy/sso.md`, dos secciones más:
  - "Detrás de un proxy TLS" (research D7-B, FR-010): qué publica el proxy, reenvío de todas las rutas al Hub, cabeceras, el Hub no depende de `X-Forwarded-*`, la salida HTTPS del backend al directorio;
  - "Activación y vuelta atrás": formulario del panel, interruptor como nivel 0, vaciar la URI como nivel 1 (el botón desaparece del Hub), variable de tag de imagen del instalador como nivel 2, sin migración; antes de activar, resetear o forzar el cambio de los usuarios con cambio obligatorio pendiente (B2).

  Corregir lo que el texto actual afirma solo para la consola (p. ej. "El directorio devuelve el navegador a la **consola**") para que cubra las dos superficies
- [ ] T041 [US4] [repo: elea] `specs/056-sso-entra-id-hub/SOLICITUD-A-ELEA.md` y `specs/056-sso-entra-id-hub/DESPLIEGUE-Y-REVERSION.md`:
  - el HTTPS lo pone el proxy de Elea o se configura a mano en el host; qué tiene que reenviar y a qué puerto (SOLICITUD punto 3, DESPLIEGUE Etapa 3); en la Etapa 3, verificar `__Host-sso_flow` y `Secure` en la sesión con el nombre HTTPS (FR-010);
  - `SENTINEL_SSO_REDIRECT_URI` con el nombre HTTPS;
  - la licencia en `./license/` con el `lic_id` de T038;
  - el cruce de la lista de UPN antes de la Etapa 4 (SC-002, que se cierra en el piloto: B7);
  - checklist de activación: usuarios con cambio obligatorio pendiente (B2);
  - en la sección "Qué falta para que volver atrás sea real", marcar `ELEA_TAG` como resuelto y aclarar que el nivel 1 (vaciar la URI) oculta el botón del Hub

**Checkpoint**: la guía alcanza para registrar la aplicación y activar sin ayuda.

---

## Phase 8: Polish & Cross-Cutting — Tramo E (continúa)

- [ ] T042 [repo: elea] `deploy/Makefile` (F3 del QA, research D14): target `check-hub-whitelabel` que corre `cd $(REPO_ROOT) && node --test client/tests/unit/whitelabel-hub-056.test.js` (sin Docker ni `npm ci`), agregado a `.PHONY` y a la lista de `check`, con su comentario, que anota que el gate necesita `node` en el `PATH`. Verificar con `make -C deploy check-hub-whitelabel`. Commit `release: …` aparte
- [ ] T043 [repo: elea] **Sitio de docs de producto (OBLIGATORIO, DoD)**. Las páginas de `docs/docs/**` que toca la feature (`docs/docs/install-deploy/sso.md`, y cualquier página que cite el aviso "contacte a soporte" o el SSO solo en la consola) quedan con curado marca-neutro, template de `docs/README.md` y leyenda 🟢/🟡/🔵 honesta: 🟢 solo para lo mergeado. Correr `make -C deploy docs-refs`, porque cambió la respuesta de `/auth/sso/available`, y después `make -C deploy check-docs` en verde (los dos con Docker: aviso previo al owner). Revisar los textos de docs nuevos contra `deploy/release/checks/prohibited_names.txt` y la regla de componentes internos (FR-013); Hub y panel ya los cubren T015, T024 y T042
- [ ] T044 [repo: elea] Gate completo del release sobre `056-sso-entra-id-hub` con A a D integrados, todo verde y comparado contra la línea base de T002 (los comandos con Docker, con aviso previo al owner). Pegar el resumen en el PR:
  - `make -C deploy check` (incluye `check-release-publish` y `check-hub-whitelabel`);
  - `docker compose run --rm --no-deps backend pytest tests/ -q`;
  - `cd client && npm test`;
  - `cd frontend && npm test`
- [ ] T045 [repo: elea] Publicar candidatas `LATEST=0 VERSION=056-rc1 deploy/release/publish-elea.sh` (depende de T030 y T044) y verificar en el registro que existe `:056-rc1` y que `:latest` **no** se movió
- [ ] T046 [repo: elea] Ejecutar [quickstart.md](quickstart.md) §1 a §5 contra el directorio de prueba: ingreso real por el Hub, atadura al navegador, **ingreso por HTTPS local** (§3b: `__Host-sso_flow` y `Secure` en un navegador real, FR-010 y FR-016), regresión (incluido vaciar la URI y apagar a mitad del ingreso), apagado desde el panel, instalación desde cero con la config SSO cargada, actualización a `056-rc1` y vuelta atrás con `ELEA_TAG`. Medir SC-001 (tiempo e interacciones, §3 caso 2) y SC-004. El registro de la aplicación en el directorio de prueba lo hace, solo con la guía de T039 y T040, alguien que no participó del desarrollo (US4, test independiente). Volcar resultados y capturas en `specs/056-sso-entra-id-hub/RESULTADOS-PRUEBA-LOCAL.md` y marcar la fila `login-real` de `specs/017-auth-rbac-sso/RUNBOOK-e2e-sso.md`
- [ ] T047 [repo: elea] Crear `specs/056-sso-entra-id-hub/HANDOFF-elea-a-sentinel.md` para `cluna-8/sentinel` (spec espejo 067). Contenido:
  - **orden de cherry-pick con los commits de base separados de los del Hub**:
    1. `base(sso)` (backend `sso/api.py` + tests);
    2. `base(panel)` (`frontend/`);
    3. docs `sso.md`, con la sección del Hub marcada "solo si hay Hub" (B8);
    4. aparte, `hub(sso)` (`client/`), que se porta como **enfoque** y no como diff, confirmando antes el diff del Hub de Sentinel;
    5. `release` e `instalador`, como enfoque para el wizard de la 065 (`ELEA_TAG` no es portable; los gates nuevos de `deploy/Makefile` sí, como enfoque).
  - verificación previa en Sentinel: migración `017_sso_providers` y paridad de `backend/src/sso/`;
  - nombres de variable idénticos (`SENTINEL_SSO_REDIRECT_URI`, `SENTINEL_LICENSE_TOKEN_FILE`);
  - nota de base: `sso/api.py` audita los rechazos de flujo y los canjes fallidos con un tope por proceso (research D6 + F1). Con la imagen prod de la base (`--workers ${WEB_CONCURRENCY:-2}`), el tope efectivo es `tope × workers`;
  - límite conocido: cerrar sesión no cierra la del directorio; `prompt=select_account` sería un cambio de base en `entra.py` (B1);
  - **deuda conocida**: la licencia de Elea sigue con firma dev y `SENTINEL_ALLOW_DEV_LICENSE=true`, y esta spec no la cambia (research D8; B9 del QA);
  - el resultado de T046
- [ ] T048 [repo: elea] Después del piloto en el server de Elea (Etapas 3 y 4 de DESPLIEGUE-Y-REVERSION.md, fuera de este repo), promover a `latest` con `VERSION=<fecha> deploy/release/publish-elea.sh` (`LATEST=1`). Anotar el tag en DESPLIEGUE-Y-REVERSION.md y el estado de cierre (incluido SC-002 con datos reales) en el HANDOFF

---

## Dependencies & Execution Order

### Por tramo

```text
Tramo 0 (T001–T003)
   ├──► Tramo A (T004–T009)  base Guardian ──────────┐
   ├──► Tramo B (T010–T023)  Hub, contra el contrato ─┤
   ├──► Tramo C (T024–T029)  panel, contra el contrato┼──► Tramo E (T039–T048)
   └──► Tramo D (T030–T038)  instalador + release ────┘
```

- A, B, C y D corren **en paralelo** en cuatro workers: no comparten archivos (tabla de propiedad).
- B y C no esperan a A para sus tests (dobles y mocks del contrato). La integración real es T044 y T046.
- E arranca con A a D mergeados en `056-sso-entra-id-hub`. `deploy/Makefile` lo tocan D (T031) y
  E (T042), que nunca corren en paralelo. T038 (licencia) es manual y puede llegar después: solo
  la necesitan la Etapa 3 en el server y el `lic_id` de T041 y T047.

### Por historia

- **US1 (P1)**: T010–T021. Depende del contrato de A, no de su merge.
- **US2 (P1)**: T022–T023 (Hub). Más T027 del panel, que evita su botón roto, y T044/T046 en vivo.
- **US3 (P1)**: T024–T029 (panel) y T030–T038 (instalador y release).
- **US4 (P3)**: T039–T041.

### Dentro de cada tramo

Tests antes que implementación, y los tests fallan primero. En A: T006 → T007 → T008 (mismo
archivo, en orden). En B: `sso.js` (T016) antes que las rutas (T017–T020); `server.js` antes que
`sso-ui.js` e `index.html` (T021); regresión (T022) antes del gate (T023). En D: T030 antes que
T031. En E: T039 → T040 → T041 → T042 → T043 (los docs antes de su check) → T044 a T048 en orden.
Las tareas sin [P] del mismo archivo van en el orden de su ID.

## Parallel Example

```bash
# Cuatro workers en paralelo después del Tramo 0:
Worker A: "Tramo A — T004..T009 (backend/src/sso/api.py + test_sso_api.py)"
Worker B: "Tramo B — T010..T023 (client/)"
Worker C: "Tramo C — T024..T029 (frontend/)"
Worker D: "Tramo D — T030..T038 (elea-installer/ + deploy/release/ + deploy/Makefile)"

# Dentro del Tramo B, los archivos de test arrancan juntos:
Task: "T010 tests unitarios en client/tests/unit/sso-pendientes-056.test.js"
Task: "T011 tests de contrato en client/tests/contract/test_sso_hub_056.test.js"
Task: "T012 tests de integración en client/tests/integration/test_sso_flujo_056.test.js"
Task: "T014 tests de pantalla en client/tests/unit/sso-ui-056.test.js"
Task: "T015 test de marca blanca en client/tests/unit/whitelabel-hub-056.test.js"
```

## Implementation Strategy

### MVP (US1)

Tramo 0 → A + B → integración y prueba real del ingreso por el Hub (T044 y T046, parte §3).
Con eso un usuario entra por Microsoft en local. La config se puede cargar por API mientras no
esté C (GUIA-PRUEBA-LOCAL-SSO.md §4).

### Entrega incremental

1. A + B → US1 + US2 en el Hub.
2. C → US3 desde el panel (sin API a mano).
3. D → instalable, versión fijable, licencia del host, candidatas sin `latest` protegidas en el gate.
4. E → guía, docs DoD, gate de marca blanca del Hub, gate completo, candidatas `056-rc1`, prueba de punta a punta, HANDOFF.
5. Server de Elea (fuera de tasks): Etapas 3 y 4 de DESPLIEGUE-Y-REVERSION.md, y después T048.

## Riesgos aceptados (hallazgos bajos del QA que no generan tarea)

- **B4**: el pendiente se consume en cualquier callback, así que un enlace externo puede cortar
  un ingreso en curso. Solo molesta y no da acceso; la persona vuelve a intentar (spec, caso
  borde de estado inválido).
- **B1** (parcial): `prompt=select_account` queda fuera porque cambia la base (`entra.py`). Se
  documenta en T039 y en el HANDOFF (T047).
- **B9** (parcial): la licencia de desarrollo sigue siendo la deuda declarada (research D8).
  Esta spec solo ignora los archivos de prueba local (T003).

## Notes

- Nunca commits a `main`, ni en `elea` ni en `elea-installer`. Cada tramo termina en PR.
- Nada que use Docker (`docker`, `docker compose`, `make -C deploy check` y `check-docs`, la suite
  del backend en contenedor) corre sin aviso previo al owner. `check-release-publish` y
  `check-hub-whitelabel` no usan Docker.
- Sin secretos en archivos versionados: ni el secreto del directorio, ni licencias `.lic` de
  clientes, ni `docker-compose.sso-local.yml`.
- Auditoría metadata-only: ningún test ni log nuevo imprime `state`, `code`, cookie de estado,
  cookie de atadura, email ni token.
- Lo que es base (A, C y los docs) se escribe genérico y sin strings de Elea ni Eleia (FR-014).
