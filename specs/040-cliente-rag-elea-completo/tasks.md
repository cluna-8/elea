# Tasks: Cliente RAG de Elea

Convención: `[ ]` pendiente, `[x]` hecho. Cada tarea referencia el US de `spec.md` que
cierra. Estado actualizado el 31-ago tras construir e integrar todo end-to-end (login real,
selector de modelo real, presupuesto real, workspace real con enmascarado, chat RAG real)
y verificarlo en vivo contra `elea` + AnythingLLM levantados.

## Fase 0 — Investigación (sin código, cierra las incógnitas de plan.md §5)

- [x] **T001** Confirmado contra el código real (31-ago) — ver plan.md §3 para el detalle:
  `POST /api/v1/gw/inspect` (enmascarar, ya existe), `GET /api/v1/chat/models` (catálogo,
  ya existe, accesible con el JWT del propio usuario), presupuesto de autoservicio NO
  existe (se implementó la opción de sesión de servicio).

## Fase 1 — Login real (US1)

- [x] **T010** Quitado `initialUsersDB` y el login sin password de `server.js`.
- [x] **T011** `POST /api/auth/login` reenvía a `POST {ELEA_BACKEND_URL}/users/login`;
  JWT en sesión de proceso. Verificado en vivo: login correcto → 200 con user real;
  password incorrecta → 401 real de `elea`.
- [x] **T012** Pantalla de login nueva en `public/index.html` (formulario usuario/
  contraseña, muestra el error tal cual lo da `elea`).
- [x] **T013** `POST /api/auth/logout` limpia la sesión en memoria.
- [x] **T014** Sacado el `user-selector` de cambio rápido de usuario sin password.

## Fase 2 — Selector de modelo real (US2)

- [x] **T020** `<select>` se llena desde `GET /api/models` (proxy a
  `GET {elea}/chat/models`) — catálogo real verificado en vivo (8 modelos + "auto").
- [x] **T021** El chat simple manda `model` real (o `"auto"`) a `elea`.
- [x] **T022** La respuesta muestra `model_used` real (`pipeline_metadata.layer_llm.
  model_used` — corregido tras verificar en vivo que NO está en la raíz de
  `pipeline_metadata` como se había asumido). Sin mencionar el motor subyacente.

## Fase 3 — Presupuesto real (US5)

- [x] **T030** Sesión de servicio (`ELEA_SERVICE_USERNAME`/`PASSWORD`) implementada con
  re-login automático en 401; consulta `GET /budgets` filtrando por `user_id`.
- [x] **T031** Badge de cabecera lee el número real — verificado en vivo: sin budget
  asignado muestra "Sin presupuesto asignado"; tras `POST /budgets` (admin) muestra
  `$0.00 / $50.00` correctamente.
- [x] **T032** Documentado en `client/README.md` (crear `Group` + `Budget` con
  `group_id` para presupuesto por rol — no se construyó UI nueva en el cliente).
- [x] **T033** El cliente propaga el error real de `elea` (`{error: data.detail}`) en vez
  de fabricar uno — mismo patrón para 401/402/lo que sea.

## Fase 4 — Workspace completo + enmascarado en ingesta (US3 + US4)

- [x] **T040** API key real generada en la instancia `elea-anythingllm` (inserción directa
  vía Prisma, documentado el comando en `client/README.md`) — la key de ejemplo
  `ANT-KEY-ELEA-PROD-2026` nunca estuvo en `client/`.
- [x] **T041** AnythingLLM configurado con el motor de `elea` como proveedor
  (`http://engine:4000/v1` + virtual key propia `tool_type=chat-ui`) — verificado en vivo,
  el chat responde con `provider: GenericOpenAiLLM`, `model: azure-gpt-4o-mini`.
- [x] **T042** Modal de ajustes de espacio con las 7 opciones reales + texto de ayuda cada
  una (`public/index.html`, modal `#modal-ws-settings`).
- [x] **T043** `POST /api/workspaces/create` llama de verdad a AnythingLLM — verificado en
  vivo (`workspace.slug` real devuelto, visible en `GET /api/v1/workspaces`).
- [x] **T044** Enmascarado real antes de subir — verificado en vivo con un documento con
  DNI/CUIL/email/nombre: las 4 entidades se detectaron y **el vector store de AnythingLLM
  solo contiene los placeholders**, nunca el dato real (confirmado leyendo `sources[].text`
  de una respuesta de chat).
- [x] **T045** `POST /api/chat` llama de verdad a AnythingLLM (`workspace/chat` o
  `thread/chat` según `threadSlug`) — verificado en vivo, incluida una respuesta dentro de
  un hilo creado por el cliente.
- [x] **T046** — **Nota de diseño, no pendiente**: no hace falta des-enmascarar la
  respuesta del RAG. A diferencia del plano de chat directo (donde el mapa
  placeholder→original vive un instante y se usa para restaurar la respuesta), acá el
  texto original **nunca se persiste en ningún lado** — es la garantía de anonimización
  permanente para lo que se embebe. La respuesta legítimamente cita `[DNI_0_...]`, no el
  valor real, porque AnythingLLM nunca tuvo el valor real. El chat SÍ pasa transparente por
  el enmascarado reversible del motor (para el turno de conversación en sí, no para el
  contexto RAG inyectado).
- [x] **T047** Borrado el código que fabricaba resumen/citas a mano.

## Fase 5 — Branding, barrido final (US6)

- [x] **T050** `grep -ril litellm client/` → vacío, verificado tras toda la Fase 4.
- [x] **T051** Textos de ayuda y pantalla de login revisados: sin "litellm", con "Elea"/
  "GuardIAn". Se sacó además el modal de "Configuración General" que exponía las URLs
  crudas de AnythingLLM y del motor al navegador — ya no hace falta, son env vars del
  servidor.
- [x] **T052** `docker-compose.yml`: `client` y `anythingllm` se resuelven por nombre de
  servicio interno (`engine`, `anythingllm`, `backend`) — sin `host.docker.internal` ni
  `demo-litellm-1`. La key filtrada (`sk-e6cd7...`) fue rotada: la instancia vieja
  (`guardian-anythingllm-portal`, ad-hoc, con esa key) se eliminó.

## Fase 6 — Perfiles de Docker (restricción de memoria)

- [x] **T060** `profiles:` agregado a `docker-compose.yml` (`frontend`→`full`,
  `anythingllm`+`client`→`rag`; `db`/`redis`/`nlp-analyzer`/`engine`/`backend` sin perfil
  = perfil `core` implícito, siempre arrancan).
- [x] **T061** Documentado en el README raíz (tabla de perfiles + comando + RAM aprox.,
  sección Quickstart).
