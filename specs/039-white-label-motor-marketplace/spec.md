# Feature Specification: White-label del motor hacia el cliente y el marketplace

**Feature Branch**: `039-white-label-motor-marketplace`

**Created**: 2026-08-31

**Status**: Borrador — a revisar antes de empaquetar el cliente Hub Chat + marketplace
(AnythingLLM / DB-GPT / Presenton) dentro del repo `elea`.

**Input**: Pedido directo del usuario al incorporar `installations/11_elea_standalone_chat`
(HARNES-PRUEBAS) y los servicios marketplace al repo `elea`: "no quiero que el cliente vea
la dependencia tan directa de litellm".

## El problema, con evidencia

El **Principio VII (Containerized & White-Label)** ya resolvió esto para el plano interno
del gateway: el servicio se llama `engine` (no `litellm`) en `docker-compose.yml`, la
variable que viaja al backend es `SENTINEL_ENGINE_MASTER_KEY` (alias deliberado de
`LITELLM_MASTER_KEY`, ver comentario en `docker-compose.yml:74-81`), y hay un gate de CI
(`check-docs`) que falla si el hostname del motor se filtra a documentación pública.

Ese trabajo **no cubre el marketplace**, porque esas piezas nacieron fuera del repo
(`HARNES-PRUEBAS`, sin la constitución del proyecto). Evidencia concreta encontrada el
31-ago:

1. **Hostname literal en dos composes de servicios externos**:
   `installations/06_db_gpt_relational_analytics/docker-compose.yml` —
   `OPENAI_API_BASE=http://demo-litellm-1:4000/v1` — y el contenedor `guardian-presenton`
   (env `CUSTOM_LLM_URL=http://demo-litellm-1:4000/v1`, inspeccionado en vivo). Un
   administrador que lea `docker ps` o el compose ve "litellm" en el nombre del contenedor
   vecino.
2. **Copy de cara al usuario menciona el motor por nombre**: 
   `installations/11_elea_standalone_chat/public/marketplace/app.js:30` —
   `"Cada comando, prompt y generación pasa por Basa GuardIAn (http://demo-litellm-1:4000/v1)..."`
   — un string que se renderiza en la UI del marketplace del Hub Chat.
3. **API key de ejemplo del motor hardcodeada** en ambos composes
   (`sk-e6cd727bc998e3733387c4ceab97226063990f02`) — mismo valor en los dos archivos,
   nunca rotada, y expuesta en texto plano en el repo (aparte del problema de naming, es
   una credencial viva que hay que invalidar).
4. **Los tres servicios apuntan al motor por su hostname de host** (`demo-litellm-1`, red
   `demo_default` externa) en vez de resolver por DNS interno del compose de `elea` — al
   moverlos al repo, esto además rompe: ya no existe esa red ni ese contenedor.

## User Scenarios & Testing

### User Story 1 - El operador del marketplace no ve "litellm" en ningún lado (Priority: P1)

Un admin que arma el demo para el cliente Elea revisa `docker-compose.yml`, los env vars
de cada servicio marketplace y la UI del Hub Chat. En ningún punto de esa revisión aparece
la palabra "litellm" ni el hostname `demo-litellm-1`.

**Por qué esta prioridad**: es el pedido explícito del usuario; sin esto no se puede
entregar el paquete al cliente.

**Criterios de aceptación**:
1. `grep -ril litellm` sobre `client/` y `marketplace/` (nuevos directorios propuestos,
   ver plan) solo encuentra menciones en comentarios internos de desarrollo (si las hay),
   nunca en strings servidos al usuario ni en nombres de servicio/contenedor.
2. Todos los servicios marketplace (DB-GPT, Presenton, Hub Chat) resuelven el motor por
   el nombre de servicio interno `engine` dentro de la red de `elea`, no por
   `demo-litellm-1` ni por `host.docker.internal:<puerto>`.
3. La API key hardcodeada se reemplaza por una virtual key propia, emitida vía
   `POST /api/v1/keys` (ver spec del cliente de marketplace) y provista por `.env`, nunca
   commiteada.

### User Story 2 - Rotación de la credencial filtrada (Priority: P1)

La key `sk-e6cd727bc998e3733387c4ceab97226063990f02`, expuesta en texto plano en dos
composes del laboratorio, se invalida y se reemplaza por una virtual key nueva, scopeada
al tenant/cliente de marketplace, antes de que el repo `elea` sea accesible a alguien más
que el usuario.

**Criterios de aceptación**:
1. La key vieja no figura en ningún archivo del repo `elea` tras el empaquetado.
2. La key nueva tiene `allowed_models` y `rpm/tpm` acotados al uso esperado del
   marketplace (no `unlimited`).

## Fuera de alcance

- Renombrar el directorio `litellm/` del propio motor o el nombre de imagen Docker
  (`ghcr.io/berriai/litellm`) — eso es visible solo para quien opera el repo, no para el
  cliente final, y ya está cubierto por el Principio VII existente.
- Cambiar el README técnico del repo (menciona LiteLLM explícitamente, es documentación
  para desarrolladores, no cara al cliente).
