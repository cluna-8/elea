---
description: "Tareas de la spec 056 — Ingreso con Microsoft Entra ID (SSO) en el Hub"
---

# Tasks: Ingreso con Microsoft Entra ID (SSO) en el Hub

**Input**: `specs/056-sso-entra-id-hub/`: [plan.md](plan.md), [spec.md](spec.md),
[research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/),
[quickstart.md](quickstart.md), [DESPLIEGUE-Y-REVERSION.md](DESPLIEGUE-Y-REVERSION.md).

**Tests**: **obligatorios** (AGENTS.md: TDD donde hay código nuevo). En cada tramo los tests se
escriben primero y **tienen que fallar** antes de la implementación.

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
| **0** Setup | 1 | T001–T003 (3) | elea | rama; nada versionado (licencia y compose de prueba quedan fuera de git) | — (va primero) |
| **A** Base Guardian | 2 | T004–T008 (5) | elea | `backend/src/sso/api.py`, `backend/tests/integration/test_sso_api.py` | B, C, D |
| **B** Hub | 3, 4 | T009–T020 (12) | elea | `client/sso.js` (nuevo), `client/server.js`, `client/public/index.html`, `client/README.md`, `client/tests/unit/sso-pendientes-056.test.js`, `client/tests/contract/test_sso_hub_056.test.js`, `client/tests/integration/test_sso_flujo_056.test.js` | A, C, D |
| **C** Panel | 5 | T021–T026 (6) | elea | `frontend/src/services/api.ts`, `frontend/src/pages/LoginPage.tsx`, `frontend/src/pages/UsersPage.tsx`, `frontend/tests/contract/UsersPage.sso-config.test.tsx`, `frontend/tests/contract/LoginPage.sso-origin.test.tsx` | A, B, D |
| **D** Instalador y release | 6 | T027–T034 (8) | elea-installer + elea | `elea-installer/{docker-compose.yml,.env.example,install.sh,README.md,.gitignore,license/.gitkeep}`, `deploy/release/publish-elea.sh`, `deploy/release/checks/test_publish_elea_latest.sh` (nuevo) | A, B, C |
| **E** Guía, docs y cierre | 7, 8 | T035–T043 (9) | elea | `docs/docs/install-deploy/sso.md`, `docs/docs/api-reference/openapi.json` (generado), `specs/056-sso-entra-id-hub/{SOLICITUD-A-ELEA.md,DESPLIEGUE-Y-REVERSION.md,RESULTADOS-PRUEBA-LOCAL.md,HANDOFF-elea-a-sentinel.md}`, `specs/017-auth-rbac-sso/RUNBOOK-e2e-sso.md` | — (va al final) |

B y C programan contra el **contrato** de A ([guardian-sso-api.md](contracts/guardian-sso-api.md))
con dobles HTTP o mocks de `fetch`. No necesitan A mergeado para sus tests. La integración real
se valida en el tramo E (T041).

---

## Phase 1: Setup — Tramo 0

**Purpose**: rama, línea base y entorno de prueba. Lo hace el coordinador o un solo worker antes
de despachar A a D.

- [ ] T001 [repo: elea] Crear la rama `056-sso-entra-id-hub` desde `main` con los artefactos de `specs/056-sso-entra-id-hub/` (sin commits a `main`; cada tramo trabaja en su rama hija y termina en PR contra esta rama)
- [ ] T002 [repo: elea] Correr la línea base de gates y anotar los conteos para comparar al cierre: `cd client && npm test`, `cd frontend && npm test`, `docker compose run --rm --no-deps backend pytest tests/ -q`, `make -C deploy check`
- [ ] T003 [P] [repo: elea] Preparar el entorno de prueba de GUIA-PRUEBA-LOCAL-SSO.md §1 a §3. Directorio Entra **de prueba**, con las dos URIs Web `http://localhost:8090/sso/callback` y `http://localhost:8095/sso/callback`. Licencia `backend/config/licenses/dev-sso-local.lic` y `docker-compose.sso-local.yml` **fuera de git**. Verificar con `git status` que no aparecen

**Checkpoint**: rama creada, línea base anotada, A a D despachables en paralelo.

---

## Phase 2: Foundational — Base Guardian (Tramo A)

**Purpose**: los dos cambios de base que consumen el Hub y el panel: `return_origin` (research
D4) y la auditoría de los rechazos de flujo (research D6, FR-012). Genérico y sin strings de
Elea: viaja a Sentinel por cherry-pick. `jit.py`, `entra.py`, `registry.py` y `admin_api.py`
**no se tocan** (FR-007).

**Tramo A** · repo elea · 5 tareas · contrato: [guardian-sso-api.md](contracts/guardian-sso-api.md)

- [ ] T004 [repo: elea] Tests de `return_origin` en `backend/tests/integration/test_sso_api.py`, junto a `test_available_*` (`:196-228`). Casos: URI `https` sin puerto, con puerto explícito, variable ausente, vacía o relativa → `null`; flag apagado sigue en 403; la respuesta sigue sin `config` ni secreto. Deben **fallar**
- [ ] T005 [repo: elea] Tests de auditoría de rechazos de flujo en `backend/tests/integration/test_sso_api.py`, junto a `test_callback_sin_cookie_400` y siguientes (`:322-430`). Cada caso de la tabla de [guardian-sso-api.md](contracts/guardian-sso-api.md) §2 deja **exactamente un** `auth_sso_denied`, y ninguna columna del evento contiene el `state` ni el `code` usados. El status y el `detail` no cambian. Deben **fallar**
- [ ] T006 [repo: elea] Implementar `return_origin` en `sso_available` (`backend/src/sso/api.py:179-200`). Helper que lee `SENTINEL_SSO_REDIRECT_URI` con `urllib.parse.urlsplit` y devuelve `esquema://host[:puerto]` o `None`. Va en los dos caminos (`enabled` true y false). T004 en verde
- [ ] T007 [repo: elea] Emitir `auth_sso_denied` con `_auditar_denegado(db, tenant_id)` (`backend/src/sso/api.py:339-347`) antes de cada 400 de `sso_callback`: cookie ausente o inválida (`_leer_estado`, `:260`), `state` distinto (`:264-268`), `code` ausente (`:269-273`) y proveedor cambiado (`:276-282`). El veredicto no cambia si auditar falla. T005 en verde
- [ ] T008 [repo: elea] Gate del tramo: `docker compose run --rm --no-deps backend pytest tests/ -q` en verde, incluidos `test_sso_api.py`, `test_sso_config_api.py` y `test_role_matrix.py`. Commit `base(sso): …` que **solo** contenga `backend/` y PR a `056-sso-entra-id-hub`

**Checkpoint**: la API de base cumple su contrato; B y C pueden integrarse contra ella.

---

## Phase 3: User Story 1 — Un empleado entra al Hub con su cuenta corporativa (P1) 🎯 MVP — Tramo B

**Goal**: "Ingresar con Microsoft" en el Hub termina en la misma sesión que el login con
contraseña, sin que el token toque la URL ni el navegador (FR-001 a FR-004, FR-008).

**Independent Test**: con la config cargada, un usuario existente entra por Microsoft y usa chat,
Documentos, Planillas y Presentaciones con su rol, grupo y presupuesto (quickstart §3, casos 1 a 5).

**Tramo B** (fases 3 y 4) · repo elea · 12 tareas · contrato: [hub-sso.md](contracts/hub-sso.md)

### Tests (escribir primero; deben fallar)

- [ ] T009 [P] [US1] [repo: elea] Tests unitarios de `client/sso.js` en `client/tests/unit/sso-pendientes-056.test.js`:
  - almacén de pendientes: guardar por `sid`, reemplazo del mismo `sid`, `tomar` que borra (un solo uso), vencimiento a los 10 min con reloj inyectable, tope de entradas con barrido de vencidos y del más viejo;
  - comparación de `state` con `timingSafeEqual`: largos distintos no coinciden y no lanzan;
  - mapeo status/`detail` → código de error de la tabla de [hub-sso.md](contracts/hub-sso.md) §4, completo, incluido el desconocido → `sso_error`
- [ ] T010 [P] [US1] [repo: elea] Tests de contrato en `client/tests/contract/test_sso_hub_056.test.js` con el doble HTTP de `client/tests/mock-servers.js`:
  - `GET /api/auth/sso/available` fail-closed: 200 `enabled:true`, 200 `enabled:false`, 403, 500, cuerpo no JSON, backend caído; nunca expone `provider_type`;
  - `GET /sso/login` guarda el pendiente y responde 302 a la `Location` del backend con `Cache-Control: no-store` y `Referrer-Policy: no-referrer`;
  - sin `Set-Cookie` o con status ≠ 302 → `302 /?sso_error=…` según §4
- [ ] T011 [P] [US1] [repo: elea] Tests de integración del camino feliz en `client/tests/integration/test_sso_flujo_056.test.js`:
  - login → callback con el mismo `sid` y `state` → el backend recibe `Cookie: sentinel_sso_state=…`;
  - sesión con `auth_method:'sso'`, `sid` **rotado** (`Set-Cookie` nuevo y el `sid` viejo sin sesión) y `302 /`;
  - ningún cuerpo ni cabecera del Hub contiene el `access_token`;
  - `GET /api/user/current` trae `user.auth_method`;
  - `POST /api/auth/change-password` con sesión SSO → 409 sin llamar al backend (FR-008)
- [ ] T012 [US1] [repo: elea] Tests de **atadura al navegador** (requisito del coordinador sobre D1, CSRF de login) en `client/tests/integration/test_sso_flujo_056.test.js`:
  - callback desde **otro** `sid` → `sso_reintentar`, y el backend recibe la llamada **sin** cabecera `Cookie` (para auditar);
  - `state` distinto → no hay canje con cookie;
  - callback repetido → el segundo falla;
  - pendiente vencido → falla;
  - `Map` vacío, como tras un reinicio → `sso_reintentar`;
  - `error=access_denied` del directorio → `sso_cancelado`

### Implementación

- [ ] T013 [US1] [repo: elea] Crear `client/sso.js` (CommonJS, sin dependencias nuevas): almacén de flujos pendientes ([data-model.md](data-model.md) §Flujo SSO pendiente), comparación de `state` con tiempo constante y mapeo de errores de [hub-sso.md](contracts/hub-sso.md) §4. Sin strings de marca. T009 en verde
- [ ] T014 [US1] [repo: elea] Implementar `GET /api/auth/sso/available` en `client/server.js`, junto a `/api/branding` (`:314-316`): proxy fail-closed con timeout de 3 s a `{ELEA_BACKEND_URL}/auth/sso/available`, respuesta `{enabled, return_origin}`
- [ ] T015 [US1] [repo: elea] Implementar `GET /sso/login` en `client/server.js`:
  - `fetch` con `redirect:'manual'`;
  - `Headers.getSetCookie()` para extraer `sentinel_sso_state`;
  - `state` del query de `Location`;
  - pendiente guardado por `req.sid` (`:88-97`);
  - 302 al IdP con `no-store` y `no-referrer`;
  - errores según §4.

  T010 en verde
- [ ] T016 [US1] [repo: elea] Implementar en `GET /sso/callback` (`client/server.js`) la **atadura al `sid`** (research D1, requisitos 1 a 3):
  - tomar y borrar el pendiente del `req.sid` siempre;
  - validar el `state` con `client/sso.js`;
  - sin pendiente, vencido, con `state` distinto o con `error=` del directorio: llamar al callback del backend **sin** cookie (o con la cookie válida si hubo `error=`), solo para que el backend audite, y redirigir con el código de §4.

  T012 en verde
- [ ] T017 [US1] [repo: elea] Completar el camino feliz de `GET /sso/callback` y las rutas afectadas en `client/server.js`:
  - canje con `Cookie: sentinel_sso_state=…`;
  - **rotación de `sid`** (research D1, requisito 4) con los mismos atributos de cookie de `:93`; si el middleware ya puso un `Set-Cookie` en esta respuesta, se reemplaza: una sola cookie `elea_rag_sid` por respuesta;
  - `setSession` con `auth_method:'sso'` y `302 /`; el cuerpo del backend nunca se loguea;
  - `user.auth_method` en `GET /api/user/current` (`:318-333`);
  - 409 en `POST /api/auth/change-password` (`:284-309`) para sesiones SSO.

  `POST /api/auth/login` (`:258-273`) **no se toca**. T011 en verde
- [ ] T018 [US1] [repo: elea] `client/public/index.html`:
  - al mostrar el overlay de ingreso (`boot`, `:1051-1056`), consultar `/api/auth/sso/available` y dibujar "Ingresar con Microsoft" bajo el formulario (`:444-455`) solo si `enabled`; destino `/sso/login`, o `${return_origin}/sso/login` si el origen es otro;
  - mostrar `?sso_error=` en `#login-error` con los textos de §4 (siempre recordando el acceso con contraseña) y limpiar la barra con `history.replaceState`;
  - con `auth_method === 'sso'`, ocultar el botón "Contraseña" (`:542`) y no abrir el modal (`:1067`).

  Textos sin marca fija; la marca sale de `/api/branding`

**Checkpoint**: US1 completa con el doble del backend; lista para la prueba real en T041.

---

## Phase 4: User Story 2 — Nada de lo que funciona hoy deja de funcionar (P1) — Tramo B (continúa)

**Goal**: login con contraseña, cambio obligatorio de la 055 y motores idénticos. SSO
degradable sin afectar el resto (FR-005, FR-006).

**Independent Test**: suite del Hub en verde con los tests de regresión. En vivo: quickstart §4.

- [ ] T019 [US2] [repo: elea] Tests de regresión y degradación en `client/tests/contract/test_sso_hub_056.test.js`:
  - `POST /api/auth/login` con status, cuerpo y sesión idénticos a hoy, incluido `must_change_password` que pasa al `user`;
  - `change-password` con sesión de contraseña proxyado como hoy;
  - con licencia sin `sso` (backend 403) o backend caído, `available` → `enabled:false` y el login con contraseña sigue operativo;
  - backend caído durante `/sso/login` → `sso_proveedor_caido` sin afectar otras rutas.

  Deben pasar sin tocar código de producción. Si alguno falla, se corrige en `client/server.js` dentro de este tramo
- [ ] T020 [US2] [repo: elea] Gate del tramo:
  - `cd client && npm test` en verde completo (incluye `smoke.test.js` y las suites de 044, 050, 051 y 053);
  - actualizar `client/README.md` (§Rutas con las tres rutas nuevas; §Sesiones con flujos pendientes, rotación de `sid` y "sin variables de entorno nuevas");
  - commit `hub(sso): …` que **solo** contenga `client/`, y PR a `056-sso-entra-id-hub`

**Checkpoint**: US1 y US2 completas del lado del Hub.

---

## Phase 5: User Story 3 — El admin activa Entra desde el panel (P1) — Tramo C

**Goal**: formulario de config SSO en la pestaña "Autenticación & SSO" sobre la API existente, y
el botón del panel solo cuando el retorno es el propio panel (FR-009, research D4 y D10).

**Independent Test**: vitest en verde. En vivo: quickstart §2 y §4.4 (apagar desde el panel
hace desaparecer el botón del Hub sin reiniciar).

**Tramo C** · repo elea · 6 tareas · contrato: [panel-sso-config.md](contracts/panel-sso-config.md)

- [ ] T021 [P] [US3] [repo: elea] Tests en `frontend/tests/contract/UsersPage.sso-config.test.tsx`, según [panel-sso-config.md](contracts/panel-sso-config.md) §3. Casos:
  - `404` → formulario vacío;
  - `200` precarga sin secreto;
  - secreto vacío → el `PUT` **no** lleva `client_secret`;
  - secreto cargado → se manda una vez y el campo queda vacío;
  - errores `sso_habilitado_sin_secreto` y `sso_cifrado_no_disponible` visibles;
  - `compliance_officer` sin formulario y sin llamada al `GET` de config (US3 AS5);
  - `403` sin formulario.

  Deben **fallar**
- [ ] T022 [P] [US3] [repo: elea] Tests en `frontend/tests/contract/LoginPage.sso-origin.test.tsx`. El botón se ve con `return_origin` `null` o igual a `window.location.origin`, y se oculta con otro origen y con `enabled:false`. Deben **fallar**
- [ ] T023 [US3] [repo: elea] `frontend/src/services/api.ts`:
  - `getSsoAvailable` (`:687-699`) devuelve también `return_origin`, con el mismo criterio fail-closed;
  - agregar `getSsoConfig()` y `putSsoConfig()` sobre `/auth/sso/config`, con el `client_secret` solo si viene no vacío;
  - nunca loguear el secreto
- [ ] T024 [US3] [repo: elea] `frontend/src/pages/LoginPage.tsx` (`:43`, `:155-162`): dibujar el botón solo si `enabled` y `return_origin` es `null` o igual a `window.location.origin`. T022 en verde
- [ ] T025 [US3] [repo: elea] `frontend/src/pages/UsersPage.tsx`: en la pestaña "Autenticación & SSO" (`:1271-1376`), reemplazar el aviso "contacte a su equipo de soporte" (`:1372-1375`) por el formulario de Entra. Incluye:
  - campos tenant del directorio, identificador de la aplicación, secreto e interruptor;
  - visibilidad: **solo** `super_admin` y `tenant_admin` (US3 AS5); los demás roles ven solo la tarjeta de estado;
  - manejo de errores según el contrato;
  - el secreto no queda en el estado de React después del `PUT`.

  La tarjeta de estado y la grilla de "Próximamente" no cambian. T021 en verde
- [ ] T026 [US3] [repo: elea] Gate del tramo:
  - `cd frontend && npm test` y `cd frontend && npm run build` en verde;
  - revisar que ningún texto nuevo nombre componentes internos;
  - commit `base(panel): …` que **solo** contenga `frontend/`, y PR a `056-sso-entra-id-hub`

**Checkpoint**: el admin activa y desactiva desde el panel; el panel no ofrece un botón que
vuelva al Hub.

---

## Phase 6: User Story 3 (cont.) — Instalador y publicación: conserva la config, arranca sin SSO, vuelta atrás real — Tramo D

**Goal**: los cambios previos de DESPLIEGUE-Y-REVERSION.md (FR-009b, FR-011, US3 AS3 y AS4):
`SENTINEL_SSO_REDIRECT_URI` desde `.env`, `ELEA_TAG`, licencia con `sso` montada desde el host y
candidatas publicadas sin mover `latest`. **Sin** servicio TLS (research D7, opción B).

**Independent Test**: `docker compose config` renderiza lo esperado con y sin variables; el
stub de `docker` prueba que `LATEST=0` no toca `:latest`. En vivo: quickstart §5.

**Tramo D** · repos elea-installer y elea · 8 tareas · contrato:
[instalador-y-release.md](contracts/instalador-y-release.md)

- [ ] T027 [P] [US3] [repo: elea] Test `deploy/release/checks/test_publish_elea_latest.sh`. Pone un `docker` *stub* en el `PATH` que registra argumentos, corre `deploy/release/publish-elea.sh` con `ONLY=rag-client` y verifica que con `LATEST=0` no aparece ningún `:latest` en `build`/`push` y que con el default sí. Debe **fallar**. Después implementar `LATEST` (default `1`) en `deploy/release/publish-elea.sh` (`:34`, `:42`) y documentar los dos modos en su encabezado de uso. Test en verde. Commit `release: …` aparte
- [ ] T028 [P] [US3] [repo: elea-installer] `docker-compose.yml`: las seis imágenes propias pasan a `:${ELEA_TAG:-latest}` (`elea-guardian-nlp`, `-engine`, `-backend`, `-frontend`, `elea-rag-client`, `elea-tabular`). Postgres, redis, anythingllm y presenton no cambian
- [ ] T029 [US3] [repo: elea-installer] `docker-compose.yml`, servicio `backend` (`:87-128`):
  - `SENTINEL_LICENSE_TOKEN_FILE=${SENTINEL_LICENSE_TOKEN_FILE:-/app/config/licenses/dev-demo.lic}`;
  - `SENTINEL_SSO_REDIRECT_URI=${SENTINEL_SSO_REDIRECT_URI:-}`;
  - volumen `./license:/app/config/licenses/host:ro`.

  `SENTINEL_ALLOW_DEV_LICENSE=true` se mantiene (deuda conocida, research D8). Crear `license/.gitkeep` y agregar `license/*.lic` a `.gitignore`
- [ ] T030 [P] [US3] [repo: elea-installer] `.env.example`: bloques comentados "Versión de imágenes" (`ELEA_TAG`) e "Ingreso con Microsoft (opcional)" (`SENTINEL_SSO_REDIRECT_URI` vacía por defecto, `SENTINEL_LICENSE_TOKEN_FILE`), con marcadores `<nombre-del-hub>` y sin valores de Elea
- [ ] T031 [US3] [repo: elea-installer] `install.sh`:
  - `docker pull` del motor (`:56`) con `${ELEA_TAG:-latest}`;
  - imprimir el tag en uso en el resumen final;
  - avisar sin cortar si `SENTINEL_SSO_REDIRECT_URI` no está vacía y no es `https://` ni `http://localhost`;
  - cortar con un mensaje claro si `SENTINEL_LICENSE_TOKEN_FILE` apunta a `/app/config/licenses/host/…` y el archivo no está en `./license/`
- [ ] T032 [US3] [repo: elea-installer] `README.md`:
  - HTTPS con el proxy TLS del cliente (tabla de [instalador-y-release.md](contracts/instalador-y-release.md) §4: nombre, certificado, reenvío de todas las rutas a `:8095`, cabeceras, salida a `login.microsoftonline.com`);
  - licencia en `./license/`;
  - vuelta atrás por niveles con `ELEA_TAG`
- [ ] T033 [US3] [repo: elea-installer] Verificación del tramo:
  - `docker compose config` sin variables nuevas renderiza `:latest`, `dev-demo.lic` y la URI vacía;
  - con `ELEA_TAG=056-rc1` renderiza ese tag en las seis imágenes;
  - `bash -n install.sh` (y `shellcheck`, si está instalado);
  - commit `instalador: …` en una rama del repo del instalador, **nunca `main`**, y PR
- [ ] T034 [US3] [repo: elea] **Manual, lo hace el dueño de la clave**: emitir la licencia de Elea con `backend/scripts/issue_license.py --feature-flags monitor,sso`, con la misma clave y `kid`, los mismos asientos y el mismo vencimiento que la vigente (research D8). Se entrega **fuera de git**, para `./license/` del server. Pasar el `lic_id` (no el archivo) al tramo E para DESPLIEGUE y el HANDOFF

**Checkpoint**: el instalador arranca igual sin variables nuevas, fija versión y toma la licencia
del host. Las candidatas se pueden publicar sin riesgo.

---

## Phase 7: User Story 4 — El IT sabe qué registrar en Entra (P3) — Tramo E

**Goal**: guía corta y marca-neutra para registrar la aplicación con retorno al Hub, más el
proxy TLS y la activación desde el panel (FR-010, FR-013).

**Independent Test**: alguien que no participó registra la aplicación en un directorio de prueba
siguiendo solo la guía, y el ingreso por el Hub funciona (US4 AS1).

**Tramo E** (fases 7 y 8) · repo elea · 9 tareas · arranca cuando A a D están mergeados en
`056-sso-entra-id-hub`

- [ ] T035 [US4] [repo: elea] `docs/docs/install-deploy/sso.md`, sección nueva "Ingreso por el Hub de usuarios", con template GUÍA de `docs/README.md` y leyenda honesta. Contenido:
  - el flujo con el Hub como intermediario (diagrama de secuencia) y la URI de retorno que apunta al Hub;
  - qué registrar: plataforma Web, `https://<nombre-del-hub>/sso/callback`, `openid profile email` + `User.Read`, consentimiento, vencimiento del secreto, "asignación requerida" recomendada;
  - el cruce UPN ↔ email antes de activar;
  - límites conocidos: baja en Entra sin SCIM y sesión vigente hasta 24 h, reinicio del Hub, cookie del Hub sin `Secure`, `return_origin`.

  Solo "Guardian", "Hub" y marcadores: sin nombres de Elea ni de componentes internos
- [ ] T036 [US4] [repo: elea] `docs/docs/install-deploy/sso.md`, dos secciones más:
  - "Detrás de un proxy TLS" (research D7-B): qué publica el proxy, reenvío de todas las rutas al Hub, cabeceras, el Hub no depende de `X-Forwarded-*`, la salida HTTPS del backend al directorio;
  - "Activación y vuelta atrás": formulario del panel, interruptor como nivel 0, variable de tag de imagen del instalador como nivel 2, sin migración.

  Corregir lo que el texto actual afirma solo para la consola (p. ej. "El directorio devuelve el navegador a la **consola**") para que cubra las dos superficies
- [ ] T037 [US4] [repo: elea] `specs/056-sso-entra-id-hub/SOLICITUD-A-ELEA.md` y `specs/056-sso-entra-id-hub/DESPLIEGUE-Y-REVERSION.md`:
  - el HTTPS lo pone el proxy de Elea o se configura a mano en el host; qué tiene que reenviar y a qué puerto (SOLICITUD punto 3, DESPLIEGUE Etapa 3);
  - `SENTINEL_SSO_REDIRECT_URI` con el nombre HTTPS;
  - la licencia en `./license/` con el `lic_id` de T034;
  - el cruce de la lista de UPN antes de la Etapa 4 (SC-002);
  - en la sección "Qué falta para que volver atrás sea real", marcar `ELEA_TAG` como resuelto

**Checkpoint**: la guía alcanza para registrar la aplicación y activar sin ayuda.

---

## Phase 8: Polish & Cross-Cutting — Tramo E (continúa)

- [ ] T038 [repo: elea] **Sitio de docs de producto (OBLIGATORIO, DoD)**. Las páginas de `docs/docs/**` que toca la feature (`docs/docs/install-deploy/sso.md`, y cualquier página que cite el aviso "contacte a soporte" o el SSO solo en la consola) quedan con curado marca-neutro, template de `docs/README.md` y leyenda 🟢/🟡/🔵 honesta: 🟢 solo para lo mergeado. Correr `make -C deploy docs-refs`, porque cambió la respuesta de `/auth/sso/available`, y después `make -C deploy check-docs` en verde. Revisar todos los textos visibles nuevos (Hub, panel, docs) contra `deploy/release/checks/prohibited_names.txt` y la regla de componentes internos (FR-013)
- [ ] T039 [repo: elea] Gate completo del release sobre `056-sso-entra-id-hub` con A a D integrados, todo verde y comparado contra la línea base de T002. Pegar el resumen en el PR:
  - `make -C deploy check`;
  - `docker compose run --rm --no-deps backend pytest tests/ -q`;
  - `cd client && npm test`;
  - `cd frontend && npm test`
- [ ] T040 [repo: elea] Publicar candidatas `LATEST=0 VERSION=056-rc1 deploy/release/publish-elea.sh` (depende de T027 y T039) y verificar en el registro que existe `:056-rc1` y que `:latest` **no** se movió
- [ ] T041 [repo: elea] Ejecutar [quickstart.md](quickstart.md) §1 a §5 contra el directorio de prueba: ingreso real por el Hub, atadura al navegador, regresión, apagado desde el panel, instalación desde cero, actualización a `056-rc1` y vuelta atrás con `ELEA_TAG`. Medir SC-001 y SC-004. Volcar resultados y capturas en `specs/056-sso-entra-id-hub/RESULTADOS-PRUEBA-LOCAL.md` y marcar la fila `login-real` de `specs/017-auth-rbac-sso/RUNBOOK-e2e-sso.md`
- [ ] T042 [repo: elea] Crear `specs/056-sso-entra-id-hub/HANDOFF-elea-a-sentinel.md` para `cluna-8/sentinel` (spec espejo 067). Contenido:
  - **orden de cherry-pick con los commits de base separados de los del Hub**:
    1. `base(sso)` (backend `sso/api.py` + tests);
    2. `base(panel)` (`frontend/`);
    3. docs `sso.md`;
    4. aparte, `hub(sso)` (`client/`), que se porta como **enfoque** y no como diff, confirmando antes el diff del Hub de Sentinel;
    5. `release` e `instalador`, como enfoque para el wizard de la 065.
  - verificación previa en Sentinel: migración `017_sso_providers` y paridad de `backend/src/sso/`;
  - nombres de variable idénticos (`SENTINEL_SSO_REDIRECT_URI`, `SENTINEL_LICENSE_TOKEN_FILE`);
  - **deuda conocida**: la licencia de Elea sigue con firma dev y `SENTINEL_ALLOW_DEV_LICENSE=true`, y esta spec no la cambia (research D8);
  - el resultado de T041
- [ ] T043 [repo: elea] Después del piloto en el server de Elea (Etapas 3 y 4 de DESPLIEGUE-Y-REVERSION.md, fuera de este repo), promover a `latest` con `VERSION=<fecha> deploy/release/publish-elea.sh` (`LATEST=1`). Anotar el tag en DESPLIEGUE-Y-REVERSION.md y el estado de cierre en el HANDOFF

---

## Dependencies & Execution Order

### Por tramo

```text
Tramo 0 (T001–T003)
   ├──► Tramo A (T004–T008)  base Guardian ──────────┐
   ├──► Tramo B (T009–T020)  Hub, contra el contrato ─┤
   ├──► Tramo C (T021–T026)  panel, contra el contrato┼──► Tramo E (T035–T043)
   └──► Tramo D (T027–T034)  instalador + release ────┘
```

- A, B, C y D corren **en paralelo** en cuatro workers: no comparten archivos (tabla de propiedad).
- B y C no esperan a A para sus tests (dobles y mocks del contrato). La integración real es T039 y T041.
- E arranca con A a D mergeados en `056-sso-entra-id-hub`. T034 (licencia) es manual y puede
  llegar después: solo la necesita la Etapa 3 en el server y el `lic_id` de T037 y T042.

### Por historia

- **US1 (P1)**: T009–T018. Depende del contrato de A, no de su merge.
- **US2 (P1)**: T019–T020 (Hub). Más T024 del panel, que evita su botón roto, y T039/T041 en vivo.
- **US3 (P1)**: T021–T026 (panel) y T027–T034 (instalador y release).
- **US4 (P3)**: T035–T037.

### Dentro de cada tramo

Tests antes que implementación, y los tests fallan primero. En B: `sso.js` (T013) antes que las
rutas (T014–T017); `server.js` antes que `index.html` (T018); regresión (T019) antes del gate
(T020). En E: T035 → T036 → T037 → T038 (los docs antes de su check) → T039 a T043 en orden.
Las tareas sin [P] del mismo archivo van en el orden de su ID.

## Parallel Example

```bash
# Cuatro workers en paralelo después del Tramo 0:
Worker A: "Tramo A — T004..T008 (backend/src/sso/api.py + test_sso_api.py)"
Worker B: "Tramo B — T009..T020 (client/)"
Worker C: "Tramo C — T021..T026 (frontend/)"
Worker D: "Tramo D — T027..T034 (elea-installer/ + deploy/release/publish-elea.sh)"

# Dentro del Tramo B, los tres archivos de test arrancan juntos:
Task: "T009 tests unitarios en client/tests/unit/sso-pendientes-056.test.js"
Task: "T010 tests de contrato en client/tests/contract/test_sso_hub_056.test.js"
Task: "T011 tests de integración en client/tests/integration/test_sso_flujo_056.test.js"
```

## Implementation Strategy

### MVP (US1)

Tramo 0 → A + B → integración y prueba real del ingreso por el Hub (T039 y T041, parte §3).
Con eso un usuario entra por Microsoft en local. La config se puede cargar por API mientras no
esté C (GUIA-PRUEBA-LOCAL-SSO.md §4).

### Entrega incremental

1. A + B → US1 + US2 en el Hub.
2. C → US3 desde el panel (sin API a mano).
3. D → instalable, versión fijable, licencia del host, candidatas sin `latest`.
4. E → guía, docs DoD, gate, candidatas `056-rc1`, prueba de punta a punta, HANDOFF.
5. Server de Elea (fuera de tasks): Etapas 3 y 4 de DESPLIEGUE-Y-REVERSION.md, y después T043.

## Notes

- Nunca commits a `main`, ni en `elea` ni en `elea-installer`. Cada tramo termina en PR.
- Sin secretos en archivos versionados: ni el secreto del directorio, ni licencias `.lic` de
  clientes, ni `docker-compose.sso-local.yml`.
- Auditoría metadata-only: ningún test ni log nuevo imprime `state`, `code`, cookie de estado,
  email ni token.
- Lo que es base (A, C y los docs) se escribe genérico y sin strings de Elea ni Eleia (FR-014).
