# Implementation Plan: Ingreso con Microsoft Entra ID (SSO) en el Hub

**Branch**: `056-sso-entra-id-hub` (plan redactado en `cluna-8/056-sso-entra-id-hub-plan`, revisado
en `cluna-8/056-sso-entra-id-hub-plan-v2`) | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/056-sso-entra-id-hub/spec.md`, enmendada por clarify
el 2026-10-05 (§Clarifications: D1 a D8 del plan y F1, F5, F6, F8 y F10 del QA; FR-001,
FR-006, FR-010 y FR-012 ajustados; FR-015 y FR-016 nuevos). Los
supuestos a confirmar con Elea siguen en su §Assumptions. Documentos operativos de la misma
carpeta: [DESPLIEGUE-Y-REVERSION.md](DESPLIEGUE-Y-REVERSION.md),
[SOLICITUD-A-ELEA.md](SOLICITUD-A-ELEA.md), [GUIA-PRUEBA-LOCAL-SSO.md](GUIA-PRUEBA-LOCAL-SSO.md).
Decisiones de diseño: [research.md](research.md), D1 a D8 confirmadas por el coordinador el
2026-10-05, D9 y D10 técnicas (sin alternativas en disputa); D11 a D15 salen del QA crítico ([qa-plan.md](qa-plan.md)), y D11, D12 y D15 los
aprobó el owner vía coordinador el mismo día. La trazabilidad de cada hallazgo del QA está al
final de research.md (§Trazabilidad del QA).

## Summary

El SSO con Entra **ya existe en la base** (spec 017: `backend/src/sso/`), pero no le llega al
usuario real: entra solo por el Hub, que tiene usuario y contraseña (`client/server.js:258`).
Esta spec agrega cuatro piezas y no cambia el modelo de datos:

1. **Hub como intermediario OIDC** (específico de la línea, se porta el enfoque): rutas
   `GET /api/auth/sso/available`, `GET /sso/login` y `GET /sso/callback` en `client/server.js`. El
   Hub llama a la API de Guardian del lado del servidor, guarda el estado firmado del backend
   como **flujo pendiente atado al `sid` del navegador** (un solo uso, `state` validado) y deja
   el token de sesión **solo en su `Map` de sesiones**. El navegador recibe un 302 a `/`
   (research D1, D3). Endurecido por el QA: con retorno `https://` el flujo se ata además a una
   cookie `__Host-` y la sesión rotada lleva `Secure` (D12). El almacén lleno rechaza al que
   llega y `/sso/login` tiene un límite de ritmo global (D11). La lógica de la pantalla va en un
   módulo puro testeable, `client/public/sso-ui.js` (D13).
2. **Base Guardian, chica y retrocompatible** (viaja a Sentinel por cherry-pick):
   `/auth/sso/available` informa `return_origin` (D4, FR-015). El callback audita también los
   rechazos de flujo, con un tope por proceso que cubre además el canje fallido y corta la
   llamada al directorio pasado el tope (D6 + F1, FR-012). Todo en `backend/src/sso/api.py`. El
   panel usa `return_origin` para no mostrar un botón que volvería al Hub, y la pestaña
   "Autenticación & SSO" suma el formulario de configuración sobre la API existente (D10).
3. **Instalador** (`cluna-8/elea-installer`): `SENTINEL_SSO_REDIRECT_URI` desde `.env`, tag de
   imagen fijable `ELEA_TAG` y licencia montada desde el host (D8, D9). **Sin** servicio TLS: el
   HTTPS lo pone el proxy de Elea y se documenta (D7, opción B).
4. **Release, gates y docs**: `publish-elea.sh` con `LATEST=0` para candidatas; dos targets
   nuevos en `make -C deploy check` (`check-release-publish` y `check-hub-whitelabel`, D14);
   `docs/docs/install-deploy/sso.md` con el ingreso por el Hub y la sección del proxy TLS; y
   `HANDOFF-elea-a-sentinel.md` con commits de base y del Hub separados.

## Technical Context

**Language/Version**: Node.js 20 (`client/Dockerfile:1`, Express 4) para el Hub · Python 3.12 +
FastAPI para el backend · TypeScript/React + Vite para el panel · Bash + Docker Compose para el
instalador y el release.

**Primary Dependencies**: ninguna nueva. El Hub usa `fetch` nativo de Node 20 con
`redirect: 'manual'` y `Headers.getSetCookie()` (research H17), y `crypto.timingSafeEqual`. El
backend reutiliza `jose`, `emit_auth_event` y el registry de proveedores existentes.

**Storage**: PostgreSQL sin cambios. **Sin migración**: la tabla `sso_providers` existe desde la
017 (`017_sso_providers.py`). Estado nuevo **solo en memoria del Hub**: el `Map` de flujos
pendientes (TTL 10 min, con tope), junto al `Map` de sesiones que ya existe (`client/server.js:75`).
Ver [data-model.md](data-model.md).

**Testing**: Hub: `node --test` + `supertest` con dobles HTTP reales del backend
(`client/tests/mock-servers.js`), `cd client && npm test`. La pantalla se prueba por su módulo
puro `client/public/sso-ui.js` con `node --test`, sin `jsdom` (D13). La marca blanca del Hub, con
un test de `node:fs` que también corre en `make -C deploy check` (D14). Backend: pytest junto a los tests de
`sso/` (`backend/tests/integration/test_sso_api.py`, `test_sso_config_api.py`), con
`docker compose run --rm --no-deps backend pytest tests/ -q`. Panel: vitest
(`frontend/tests/contract/UsersPage.*.test.tsx`), `cd frontend && npm test`. Release y docs:
`make -C deploy check` (incluye `check-docs`, `check-release-publish` y `check-hub-whitelabel`). Instalador: `docker compose config` con y sin las
variables nuevas, más el ensayo de reversión de la Etapa 1. Punta a punta: `quickstart.md`
contra un directorio Entra de prueba (nunca el de Elea).

**Target Platform**: Linux con Docker Compose, on-prem en el server de Elea
(`eleavdmia`, `172.16.0.120`). Salida HTTPS a `login.microsoftonline.com` desde el backend.
Hub servido por HTTPS en un nombre DNS de Elea, por un proxy TLS **de Elea** delante del puerto
`8095`.

**Project Type**: aplicación web (Hub Node + API FastAPI + panel React) más un repo de instalador.

**Performance Goals**: SC-001, ingreso en menos de 30 s y en no más de 3 interacciones. El
Hub suma dos llamadas internas al backend por ingreso (login y callback), las mismas que hace el
panel.

**Constraints**: FR-003 (el Hub no valida tokens de Microsoft, solo habla con la API de
Guardian) · FR-004 (el token nunca en una URL) · FR-005/006 (login con contraseña intacto, solo
degrada el camino SSO) · FR-007 (reglas JIT de la 017 sin tocar: `backend/src/sso/jit.py` no se
modifica) · FR-013/014 (sin nombres internos ni strings de Elea en código; textos del Hub desde
`/api/branding`) · FR-012 (todo rechazo auditado; única excepción, el excedente del tope por
proceso) · FR-015 (ninguna pantalla ofrece un botón que no puede completar) · FR-016 (ingreso
atado al navegador; con retorno HTTPS, cookie `__Host-` y sesión `Secure`; una ráfaga no corta los
ingresos en curso) · auditoría
metadata-only · sesiones del Hub en memoria (un reinicio corta los ingresos en curso, que es el
caso borde aceptado) · cambios de base mínimos y retrocompatibles (upstream: `cluna-8/sentinel`).

**Scale/Scope**: una instalación, un tenant, un proveedor (Entra), del orden de cientos de
usuarios. Tres rutas nuevas en el Hub, dos cambios acotados en `sso/api.py`, un formulario en el
panel, tres variables en el instalador, un flag en el script de publicación y dos targets de gate.

## Constitution Check

*GATE: pasa antes de la Fase 0 y se re-evaluó después del diseño (Fase 1). Constitución 2.2.0.*

| Principio / constraint | Cómo lo cumple este plan | Estado |
|---|---|---|
| **I. Privacy & PII masking-first** | No toca el pipeline de prompts. El email de la identidad no se loguea en el Hub ni viaja en la URL. | PASS (N/A al pipeline) |
| **II. Compliance & governance (auditoría metadata-only)** | **Lectura para esta línea** (aclaración del owner, 2026-10-05): Eleia es la base localizada para América (perfil Argentina). El Principio II se aplica como la normativa del perfil de país (Ley 25.326 / AAIP), no como EU AI Act ni GDPR. Los mecanismos técnicos valen igual. Todo ingreso SSO, aceptado o rechazado, queda como `auth_sso_login` / `auth_sso_denied` en el canal de auth events existente (`backend/src/services/auth_events.py:23`). D6 suma la auditoría de los rechazos de flujo **sin** `state`, `code`, email ni token. El tope (D6 + F1) es la única excepción, está escrita en FR-012 y deja un warning metadata-only con el conteo: la ráfaga queda registrada, no silenciosa. El Hub no audita por su cuenta y no loguea tokens. | PASS |
| **III. Multi-tenant** | El tenant sale de `expected_tenant_id()` en el backend (`api.py:206`, `:259`); el JIT busca por email acotado al tenant (`jit.py:73-86`). El Hub no decide tenant. | PASS |
| **IV. Onboarding como datos** | Activar SSO para un cliente es licencia + config por el panel/API + una variable de entorno. Cero código por cliente. | PASS |
| **V. Cost governance** | El token SSO es el mismo de la sesión local (`api.py:321-323`): presupuestos y llaves no cambian. | PASS |
| **VI. Motor nativo, sin parches** | No toca el motor. | PASS (N/A) |
| **VII. Contenedores + white-label, config + seed, nunca fork** | Sin nombres de motor ni de componentes internos en lo visible; "Microsoft" es el proveedor de identidad elegido por el cliente y no está en `deploy/release/checks/prohibited_names.txt`. Textos con la marca de `/api/branding` (`client/server.js:46-52`). Verificado por gate: `check-hub-whitelabel` en `make -C deploy check` y el test de marca del panel (D14). Base y Hub separados para portar a Sentinel. | PASS |
| **VIII. Transparencia del pipeline** | No toca el pipeline de requests. | PASS (N/A) |
| **Security 3: fail-closed en identidad** | `/api/auth/sso/available` del Hub colapsa a "sin botón" ante cualquier cosa distinta de `200 enabled:true` con `return_origin` no nulo. Callback sin pendiente, con otro `sid`, sin la cookie de atadura (retorno `https://`) o con `state` distinto → rechazo (FR-016). Almacén lleno o límite de ritmo → rechazo del nuevo, nunca expulsión. Tope de canje agotado → 401 sin llamar al directorio. El login con contraseña es fallback permanente declarado (FR-005), no fail-open. | PASS |
| **Security 5: TLS en tránsito, Fernet en reposo** | El secreto del IdP se sigue cifrando con Fernet (`admin_api.py:155-169`) y el formulario nunca lo muestra. TLS: lo termina el proxy de Elea delante del Hub (D7-B, FR-010 enmendado). La sesión SSO con retorno `https://` lleva `Secure` (D12). El tramo Hub → backend es red interna de Docker, igual que hoy. | PASS, con nota: el TLS queda fuera del instalador por decisión del owner, se documenta y se verifica en la Etapa 3 (sin violación: la constraint pide TLS en tránsito, no quién lo termina) |
| **Security 6: metadata-only** | Ver II. | PASS |
| **Workflow: SDD, tests, docs vivas** | TDD por tramo (tests primero en cada fase de tasks.md), incluida la pantalla del Hub (D13); spec enmendada por clarify antes de implementar; docs de producto y HANDOFF en Polish; gate `make -C deploy check` (con los dos targets nuevos) + pytest + `npm test` de Hub y panel. | PASS |
| **AGENTS.md: migraciones con id por hash** | No hay migración. | PASS (N/A) |

**Re-evaluación post-diseño** (repetida después del QA, 2026-10-05): sin violaciones. El único
estado nuevo vive en memoria del Hub (pendientes, contador de ritmo) y en memoria del proceso del
backend (dos contadores del tope). Ninguno contiene secretos persistentes: el JWT de estado
firmado dura 10 min y se consume una vez, y la atadura es un aleatorio de un solo uso.
Complexity Tracking vacío.

**Deuda conocida (no la introduce ni la resuelve esta spec)**: la licencia de Elea sigue firmada
con la clave de desarrollo y `SENTINEL_ALLOW_DEV_LICENSE=true`
(`elea-installer/docker-compose.yml:109-110`). Se anota en research D8 y en el HANDOFF.

## Project Structure

### Documentation (this feature)

```text
specs/056-sso-entra-id-hub/
├── spec.md                        # enmendada por clarify (2026-10-05)
├── plan.md                        # este archivo
├── research.md                    # D1–D15 con la elección final + trazabilidad del QA
├── qa-plan.md                     # QA crítico del plan (no se edita)
├── data-model.md                  # estado en memoria del Hub + respuestas extendidas
├── quickstart.md                  # validación de punta a punta (local + regresión + reversión)
├── contracts/
│   ├── hub-sso.md                 # rutas nuevas del Hub y lo que consume de Guardian
│   ├── guardian-sso-api.md        # cambios de base en /auth/sso/* (return_origin, auditoría)
│   ├── panel-sso-config.md        # formulario de la pestaña "Autenticación & SSO"
│   └── instalador-y-release.md    # variables del instalador, licencia montada, LATEST=0, proxy TLS
├── tasks.md                       # Fase 2 (/speckit-tasks)
├── DESPLIEGUE-Y-REVERSION.md      # operativo (se actualiza en Polish)
├── SOLICITUD-A-ELEA.md            # pedido a Elea (se actualiza en Polish)
├── GUIA-PRUEBA-LOCAL-SSO.md       # prueba del SSO del panel sin código nuevo
└── HANDOFF-elea-a-sentinel.md     # se crea en Polish
```

### Source Code (repository root)

```text
cluna-8/elea (este repo)
├── client/                                  # Hub — específico de la línea (se porta el enfoque)
│   ├── server.js                            # rutas /api/auth/sso/available, /sso/login, /sso/callback;
│   │                                        #   Map de pendientes; auth_method en la sesión; 409 en change-password
│   ├── sso.js                               # pendientes, ritmo, comparación en tiempo constante, mapeo de errores
│   ├── public/sso-ui.js                     # lógica pura de la pantalla: destino del botón, textos de error, "Contraseña"
│   ├── public/index.html                    # solo cablea sso-ui.js (botón, #login-error con textContent, modal)
│   └── tests/
│       ├── contract/test_sso_hub_056.test.js
│       ├── integration/test_sso_flujo_056.test.js
│       ├── unit/sso-pendientes-056.test.js
│       ├── unit/sso-ui-056.test.js
│       └── unit/whitelabel-hub-056.test.js  # FR-013/FR-014; también corre en make -C deploy check
├── backend/src/sso/api.py                   # BASE: return_origin en /available; auditoría de rechazos con tope (flujo y canje)
├── backend/tests/integration/test_sso_api.py  # BASE: tests nuevos junto a los de sso/ (viajan con el módulo)
├── frontend/src/
│   ├── services/api.ts                      # BASE: getSsoAvailable con return_origin; get/put de config SSO
│   ├── pages/LoginPage.tsx                  # BASE: botón solo si return_origin coincide con el origen
│   └── pages/UsersPage.tsx                  # BASE: formulario de config SSO en la pestaña "Autenticación & SSO"
├── frontend/tests/contract/
│   ├── UsersPage.sso-config.test.tsx
│   └── LoginPage.sso-origin.test.tsx
├── deploy/release/publish-elea.sh           # LATEST=0 para candidatas
├── deploy/release/checks/test_publish_elea_latest.sh  # docker de prueba: LATEST=0 no toca :latest
├── deploy/Makefile                          # targets check-release-publish (D) y check-hub-whitelabel (E)
├── docs/docs/install-deploy/sso.md          # ingreso por el Hub + proxy TLS + vuelta atrás
└── specs/056-sso-entra-id-hub/              # artefactos y HANDOFF

cluna-8/elea-installer
├── docker-compose.yml                       # ${ELEA_TAG:-latest}, SENTINEL_SSO_REDIRECT_URI, licencia montada
├── .env.example                             # ELEA_TAG, SENTINEL_SSO_REDIRECT_URI, SENTINEL_LICENSE_TOKEN_FILE
├── install.sh                               # pull con ELEA_TAG; tag usado en el resumen final
└── README.md                                # HTTPS por proxy de Elea, licencia en ./license/, vuelta atrás
```

**Structure Decision**: aplicación web existente de tres superficies más el repo del
instalador. `cluna-8/sentinel` es el **upstream** de la base: lo que toca la base
(`backend/src/sso/`, `frontend/`) es **mínimo y retrocompatible**, porque se sincroniza después con
Sentinel. Lo propio de la línea (`client/` = Hub, instalador) puede divergir. No se crean módulos nuevos. El código **de base** (backend `sso/`, panel `frontend/`,
docs) se escribe genérico y en commits separados del código **del Hub** (`client/`) y del
**instalador**, para que el HANDOFF pueda listar el orden de cherry-pick a Sentinel sin mezclar.
Archivos por tramo en [tasks.md](tasks.md): ningún archivo lo tocan dos tramos que corran en
paralelo.

## Fases de entrega (resumen; el detalle está en tasks.md)

| Tramo | Repo | Qué | Depende de |
|---|---|---|---|
| Tramo A Base Guardian | elea | `sso/api.py` (`return_origin`, auditoría con tope de flujo y de canje) + tests | — |
| Tramo B Hub | elea | `client/sso.js`, `client/server.js`, `client/public/sso-ui.js`, `client/public/index.html` + tests (incluidos pantalla y marca blanca) | contrato del Tramo A (puede arrancar con el doble HTTP) |
| Tramo C Panel | elea | `LoginPage.tsx`, `UsersPage.tsx`, `api.ts` + tests | contrato del Tramo A |
| Tramo D Instalador y release | elea-installer + `deploy/release/` + `deploy/Makefile` | `ELEA_TAG`, `SENTINEL_SSO_REDIRECT_URI`, licencia montada, `LATEST=0` y su target de gate | — |
| Tramo E Polish | elea | docs, SOLICITUD/DESPLIEGUE, target `check-hub-whitelabel`, quickstart real, HANDOFF, gate | Tramos A a D |

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| El usuario entra por `http://IP:8095` y el retorno va al nombre DNS (cookies distintas por origen) | D4: el Hub ve que `return_origin` es otro y manda el botón a `${return_origin}/sso/login`; la guía anuncia el nombre DNS como acceso principal. |
| UPN distinto del email cargado → duplicados | Fuera del código (FR-007 no cambia): cruce de listas antes de activar (DESPLIEGUE, Riesgos). |
| Reinicio del Hub a mitad del ingreso | Aceptado por la spec: "volvé a intentar" (código `sso_reintentar`). |
| El panel muestra un botón roto | D4: el panel oculta el botón si `return_origin` no es su origen. |
| Imágenes candidatas tomadas por accidente | `LATEST=0` + `ELEA_TAG=056-rc1` explícito en el server, protegido por `check-release-publish` en el gate (D14). |
| Inundación de la auditoría o del directorio desde la LAN, sin autenticarse | Tope por proceso de rechazos de flujo y de canjes fallidos; pasado el tope no hay fila ni llamada al `token_endpoint` (D6 + F1). |
| Inundación de `/sso/login` del Hub que expulsa ingresos en curso | El almacén lleno rechaza al que llega; límite de ritmo global (D11). |
| Login CSRF con una cookie `sid` inyectada por red o por un subdominio | Cookie de atadura `__Host-sso_flow` y `Secure` en la sesión con retorno `https://` (D12). |
| PC compartida: cerrar sesión en el Hub no cierra la de Microsoft | Límite estándar de SSO, documentado en la guía. `prompt=select_account` queda fuera: es un cambio de base (`entra.py:251-256`). |
| Usuario con cambio obligatorio pendiente (055) que entra por SSO | Checklist de activación: resetear o forzar el cambio antes de activar. |

## Complexity Tracking

> Sin violaciones de la constitución que justificar.
