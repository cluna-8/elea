# Tasks: Cliente RAG de Elea

Convención: `[ ]` pendiente, `[x]` hecho. Cada tarea referencia el US de `spec.md` que
cierra.

## Fase 0 — Investigación (sin código, cierra las incógnitas de plan.md §5)

- [ ] **T001** Confirmar contra el código de `backend/` (no asumir):
  - ¿`presidio_service.py` tiene o puede exponer un endpoint HTTP público para
    enmascarar texto arbitrario desde un cliente externo? (US4)
  - ¿Existe algún endpoint que liste el catálogo de modelos vivos del motor
    (`GET /api/v1/models` o similar), o hay que agregarlo? (US2)
  - ¿Con qué credencial concreta (JWT de un usuario admin dedicado vs. algo mejor) el
    cliente Node puede consultar `/{user_id}/spend` en nombre del usuario logueado, sin
    exponerla al navegador? (US5)
  - Salida: actualizar plan.md §3 con la respuesta real, no la hipótesis.

## Fase 1 — Login real (US1)

- [ ] **T010** Quitar `initialUsersDB` y el login sin password de `server.js`.
- [ ] **T011** `POST /api/auth/login` del cliente reenvía a
  `POST {ELEA_BACKEND_URL}/users/login`; guardar JWT + datos de usuario en sesión de
  proceso (no en disco en claro, no en el navegador).
- [ ] **T012** Pantalla de login nueva en `public/index.html` (usuario/contraseña real,
  hoy no existe — el mockup entraba directo). Mostrar error 401 tal cual lo da `elea`.
- [ ] **T013** `POST /api/auth/logout` limpia la sesión en memoria.
- [ ] **T014** Sacar el `user-selector` de cambio rápido de usuario sin password.

## Fase 2 — Selector de modelo real (US2)

- [ ] **T020** Reemplazar el `<select>` hardcodeado de 4 modelos falsos por una carga
  desde `elea` (endpoint que confirme T001).
- [ ] **T021** El envío del chat simple manda `model` real (o `"auto"`) a `elea`, no un
  string inventado.
- [ ] **T022** Mostrar en la respuesta qué modelo respondió de verdad (campo que ya
  devuelve `elea` en el chat), sin mencionar el motor subyacente.

## Fase 3 — Presupuesto real (US5)

- [ ] **T030** Implementar el camino elegido en plan.md §3 punto "usedUsd" (credencial de
  servicio del cliente Node → `/{user_id}/spend`).
- [ ] **T031** Badge de cabecera lee el número real, deja de incrementarse con la fórmula
  fabricada de `/api/chat`.
- [ ] **T032** Documentar en `client/README.md` cómo un admin asigna presupuesto por rol
  (crear `Group` en `elea` + `Budget` con `group_id`) — no construir UI nueva para esto en
  el cliente, es tarea del panel admin ya existente.
- [ ] **T033** El cliente propaga el 402 real de `elea` cuando se agota el presupuesto (no
  el mensaje inventado actual).

## Fase 4 — Workspace completo + enmascarado en ingesta (US3 + US4)

- [ ] **T040** Generar la API key real de AnythingLLM (paso manual documentado en
  `client/README.md`: entrar a `:3001` → Settings → API Keys) y cargarla en `.env` — sacar
  `ANT-KEY-ELEA-PROD-2026` del código.
- [ ] **T041** Configurar AnythingLLM con el motor de `elea` como proveedor LLM interno
  (`http://engine:4000/v1` + virtual key propia emitida vía `POST /api/v1/keys`).
- [ ] **T042** Formulario de creación/edición de workspace: agregar las 7 opciones reales
  de la tabla de `spec.md` US3, con su texto de ayuda.
- [ ] **T043** `POST /api/workspaces/create` del cliente llama de verdad a
  `POST AnythingLLM /api/v1/workspace/new` + `update` — deja de ser JSON local.
- [ ] **T044** Subida de documento: insertar el paso de enmascarado (plan.md §2) entre
  `extract_text.py` y `POST AnythingLLM /api/v1/document/upload`.
- [ ] **T045** `POST /api/chat` del cliente llama de verdad a
  `POST AnythingLLM /api/v1/workspace/{slug}/chat`, respeta `chatMode` del workspace.
- [ ] **T046** Des-enmascarar la respuesta de AnythingLLM antes de devolverla al
  navegador (mismo criterio que el resto de `elea`).
- [ ] **T047** Borrar el código de `/api/chat` que fabrica resumen/citas a mano
  (`extractText` de las primeras 5 líneas, cita fija `"Pág. 1"`).

## Fase 5 — Branding, barrido final (US6)

- [ ] **T050** `grep -ril litellm client/` → debe seguir vacío tras toda la fase 4.
- [ ] **T051** Revisar cada texto de ayuda nuevo (US3) y la pantalla de login (US1): sin
  "litellm", con "Elea"/"GuardIAn" donde corresponda.
- [ ] **T052** `docker-compose.yml` del cliente: servicios por nombre interno
  (`engine`, `anythingllm`, `backend`), nunca `host.docker.internal:<puerto>` ni
  `demo-litellm-1`.

## Fase 6 — Perfiles de Docker (restricción de memoria)

- [ ] **T060** Agregar `profiles:` a `docker-compose.yml` de `elea` según plan.md §1
  (`core` default, `rag`, `full`).
- [ ] **T061** Documentar en el README raíz del repo el comando exacto para cada perfil y
  cuánta RAM aproximada consume.
