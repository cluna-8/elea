# Quickstart — validar la redirección de modelos en Eleia con Azure

Guía de validación de punta a punta (no de implementación). Contratos: [contracts/](./contracts/);
datos: [data-model.md](./data-model.md). Lo que usa Docker se corre **solo con aviso previo al owner**.
Las evidencias van a `verificacion-cara-claude.md` (T045), `verificacion-cara-generica.md` (T051),
`verificacion-cache.md` (T078) y `verificacion-quickstart.md` (T083).

## 0. Antes de empezar (base compartida con el motor)

- Usar la base de desarrollo **existente** (con el libro de migraciones del motor ya creado) o bases
  separadas. **Nunca** una base nueva arrancando el backend antes que el motor (research R5; spike
  `ANALISIS-SEPARAR-BASES-MOTOR-2026-10.md` §1.3).
- No cambiar la imagen del motor (`litellm/Dockerfile:6`). El override de la extensión fija
  `DISABLE_SCHEMA_UPDATE=true` en el motor durante la prueba.
- Copia de la base antes de aplicar las migraciones de la extensión: volver a una versión sin la
  extensión después de aplicarlas no está soportado (FR-004b).

## 1. Activar la extensión en desarrollo

1. Variables en un `.env` local **no versionado** (HANDOFF §2.1): `GATEWAY_PLUGINS=sentinel.redirect.plugin`,
   `PLUGIN_PACKAGES=sentinel.redirect.api,sentinel.catalog.api`,
   `ALEMBIC_EXTRA_VERSION_LOCATIONS=/opt/sentinel-ext/sentinel/migrations`,
   `REDIRECT_INTERNAL_KEY=<openssl rand -base64 48>`, `REDIRECT_CACHE_TTL_S=5`,
   `SENTINEL_ENTITY_REGION=latam_ar`, `FERNET_SECRET_KEY` (ya existente), `MASKING_NONCE_KEY` (T-F).
   Plantilla sin secretos: `sentinel/extensions.env.example`.
2. Levantar con el override: `docker compose -f docker-compose.yml -f sentinel/docker/compose.dev.yml up -d`.
3. **Esperado**: el backend arranca con `upgrade heads` y quedan dos cabezas, `199fe429762a` y la de la
   extensión; `GET /api/v1/gw` no nombra componentes internos; el panel muestra «Modelos» con las
   pestañas de redirección en lugar del ítem base.

## 2. Cargar los datos

1. Región: `python -m sentinel.redirect.regions_seed deploy/redirect-seeds/regions.americas.yaml`
   (T064). **Esperado**: región `AMERICAS` de instalación con `region_profiles` ⊇ `latam_ar` y
   `offregion_default` = el valor sembrado (pendiente del análisis legal; de fábrica `reject`).
2. Reglas de habilitación explícita:
   `python -m sentinel.catalog.habilitacion deploy/redirect-seeds/habilitacion-explicita.yaml` (T027).
   **Esperado**: mientras el análisis legal no esté, listas vacías y ningún destino bloqueado.
3. Catálogo de Azure: `python -m sentinel.catalog.seed deploy/redirect-seeds/catalog-seed.azure-demo.yaml` y,
   en «Modelos», completar en cada entrada la **jurisdicción de inferencia y de entidad** de la región
   real del recurso de Azure (dato que no se presume). Destinos:

   | Entrada | `real_model` (despliegue de Azure) | Nota |
   |---|---|---|
   | gpt-5.6-luna | `gpt-5.6-luna` | no está en `litellm/config.yaml`: solo en el catálogo |
   | gpt-5.1-chat | `gpt-5.1-chat` | |
   | gpt-5.4-mini | `gpt-5.4-mini` | |
   | gpt-4o-mini | `gpt-4o-mini` | |

   **Esperado**: cada entrada pasa la verificación de despliegue (`deployment_check.status = ok`); una
   entrada con un nombre de despliegue inventado queda `inactive` con «El despliegue … no existe».

## 3. Publicar, mapear y encender (US1)

1. Publicados, cara Claude, alcance = grupo «Desarrollo» (o la conexión de la herramienta): ids que la
   versión instalada de Claude Code / Desktop reconozca, p. ej. `claude-opus-5-5`, `claude-sonnet-5-5`,
   `claude-haiku-4-5`.
2. Reglas sugeridas: **opus → gpt-5.6-luna**, **sonnet → gpt-5.1-chat**, **haiku → gpt-5.4-mini**
   (fallback de haiku: gpt-4o-mini).
3. Residencia: si la región de Azure está en `AMERICAS` no hace falta postura. Si no, fijar
   *fuera de región con enmascarado forzado* desde Cumplimiento.
4. Política: **Encendida** para el alcance.
5. **Medir SC-003**: del paso 1 al 4, menos de 15 minutos sin ayuda técnica.

## 4. Claude Desktop y Claude Code (US1, US4)

- Claude Desktop (3P): `inferenceGatewayBaseUrl = https://<dominio>/api/v1/gw`, llave virtual,
  `bearer`, descubrimiento activado ([contracts/cara-claude.md §8](./contracts/cara-claude.md)).
- Claude Code: `ANTHROPIC_BASE_URL=https://<dominio>/api/v1/gw`, `ANTHROPIC_AUTH_TOKEN=<llave>`.

| Escenario | Esperado |
|---|---|
| Lista de modelos | un modelo por tier con «Sonnet · servido por gpt-5.1-chat» y la ventana real (US1 esc. 1) |
| Conversación con herramientas y streaming en Claude Code (`?beta=true`) | responde el destino; `model` = id público; sin «Unrecognized request argument supplied: safeguards» (T139); auditoría con id pedido, destino, cara y fidelidad, sin contenido (US1 esc. 2, esc. 7) |
| Sondeo de arranque de Desktop (`max_tokens: 1`) | responde; `adjusted_params` registra el piso de 16 y `max_completion_tokens` (US1 esc. 8) |
| Cambiar sonnet → gpt-5.4-mini en el panel | los pedidos siguientes los sirve el nuevo destino en < 1 min (SC-009) |
| Id no publicado | 404 «Modelo no disponible para tu organización.» (US1 esc. 4) |
| Pedir `rdx-azure/gpt-5.1-chat` o mandar `api_base` propio | rechazado o ignorado (US1 esc. 6) |
| Sesión larga de Cowork con datos personales | sin cortes por inactividad (pings ≤ 15 s); aprovechamiento de caché registrado (US4, T-F) |

## 5. Otra empresa o grupo sin política (US2)

Con la política apagada y sin postura, la batería de no-regresión
(`backend/tests/contract/test_gw_no_regresion_057.py`, T003, y
`sentinel/tests/integration/test_no_regresion_con_extension.py`, T018) y una conversación real de
Claude Code dan el mismo resultado que antes del porte, incluida la lista de modelos.

## 6. Cara genérica (US5)

opencode y Aider (modo OpenAI) con base `https://<dominio>/api/v1/gw/v1`, llave virtual y modelo =
alias publicado («rápido» → gpt-5.4-mini, «pro» → gpt-5.1-chat). **Esperado**: listan solo sus alias;
conversación con streaming y herramientas; `model` = alias; un usuario de otro grupo no ve los alias
(SC-014).

## 7. Residencia (US3)

Con un destino Azure marcado en una jurisdicción fuera de `AMERICAS` (p. ej. una región de la UE):

| Postura | Esperado |
|---|---|
| ninguna, `offregion_default = reject` | 403 «Modelo no disponible para tu región.» |
| *fuera de región con enmascarado forzado* | DNI, CUIT/CUIL y CBU salen enmascarados y vuelven restaurados (SC-006) |
| la misma, con el analizador caído | el pedido se bloquea aunque la instalación diga «degradar» |
| *solo jurisdicciones permitidas* con fallback en `AMERICAS` | responde el fallback y la auditoría registra la sustitución |

## 8. Modelos chinos y económicos 🟡 (hasta tener credencial)

Mismo flujo, con entradas `deepseek`, `openai_compatible` (Qwen, Kimi, MiniMax con su `api_base`),
`zai` (GLM) y `openrouter` (con lista de proveedores). Lo validan hoy los tests con upstream falso
(T024, T025, T057, T058); la prueba real queda 🟡 en la documentación.

| Caso | Esperado |
|---|---|
| Regla con estrategia «más barato» entre varios destinos | elige el de menor precio del catálogo; el costo registrado es el del destino real |
| API oficial china con una regla de habilitación explícita que la cubre | nace bloqueada; se habilita desde «Modelos» con motivo (queda en el registro) |
| Con listas de habilitación vacías | ninguna entrada bloqueada; todo funciona |
| API oficial china habilitada, fuera de `AMERICAS` | según la postura y el `offregion_default` (§7) |
| El mismo modelo alojado en América (Azure/AWS en EE. UU., o OpenRouter con proveedores de EE. UU.) | se usa sin enmascarado forzado |
| OpenRouter | cada pedido sale con cero retención, sin recolección de datos y solo a la lista de proveedores permitidos; `openrouter_zdr: true` en la auditoría |
