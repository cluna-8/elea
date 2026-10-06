# Quickstart — validar la redirección de modelos en Eleia con Azure

Guía de validación de punta a punta (no de implementación). Contratos: [contracts/](./contracts/);
datos: [data-model.md](./data-model.md). Lo que usa Docker se corre **solo con aviso previo al owner**.
Las evidencias van a `verificacion-cara-claude.md` (T045), `verificacion-cara-generica.md` (T051),
`verificacion-cache.md` (T078) y `verificacion-quickstart.md` (T083).

## 0. Antes de empezar (base compartida con el motor)

- Usar la base de desarrollo **existente** (con el libro de migraciones del motor ya creado) o bases
  separadas. **Nunca** una base nueva arrancando el backend antes que el motor (research R5; spike
  `ANALISIS-SEPARAR-BASES-MOTOR-2026-10.md` §1.3).
- No cambiar la versión ni el digest base del motor (`litellm/Dockerfile:6`; la variante `-ext` deriva de él). `DISABLE_SCHEMA_UPDATE=true` en el motor es
  una hipótesis sin ensayar (research R5): no se usa hasta que T019 la valide.
- Copia de la base antes de aplicar las migraciones de la extensión: volver a una versión sin la
  extensión después de aplicarlas no está soportado (FR-004b).

## 1. Activar la extensión en desarrollo

1. Variables en un `.env` local **no versionado** (HANDOFF §2.1): `GATEWAY_PLUGINS=sentinel.redirect.plugin`,
   `PLUGIN_PACKAGES=sentinel.redirect.api,sentinel.catalog.api`,
   `ALEMBIC_EXTRA_VERSION_LOCATIONS=/opt/sentinel-ext/sentinel/migrations`,
   `REDIRECT_INTERNAL_KEY=<openssl rand -base64 48>`, `REDIRECT_CACHE_TTL_S=5`,
   `SENTINEL_ENTITY_REGION=latam_ar`, `FERNET_SECRET_KEY` (ya existente), `MASKING_NONCE_KEY` (T-F),
   `REDIRECT_SEED_FILES` (regiones y reglas de habilitación de `deploy/redirect-seeds/`; el catálogo de Azure se carga aparte, §2.3). `INTERNAL_ALLOWED_CIDRS=auto` ya viene del arreglo de separación de bases.
   **No** definir `REDIRECT_OPERATOR_TENANT` (research R30). Plantilla sin secretos:
   `sentinel/extensions.env.example`.
2. Levantar con el override: `docker compose -f docker-compose.yml -f sentinel/docker/compose.dev.yml up -d`.
3. **Esperado**: el backend arranca con `upgrade heads` y quedan dos cabezas, `199fe429762a` y la de la
   extensión; **después de T-E** (T060, T064, T095), además, los seeds quedan cargados al arrancar y
   `GET /api/v1/redirect/health` = 200 (antes de T-E esa ruta no existe y T045 trabaja con una postura
   explícita, §3); `GET /api/v1/gw`
   no nombra componentes internos; el panel muestra «Modelos» con las pestañas de redirección en lugar
   del ítem base.

### 1b. Con el instalador, en local (T102, antes del servidor)

1. Imágenes `-ext` publicadas por `deploy/release/publish-elea.sh` (T091) con su tag propio.
2. Instalador `cluna-8/elea-installer` en la PC del owner con `ELEA_REDIRECT=1` (T100): elige las `-ext`,
   escribe el entorno de la extensión (modo 600); el proxy delante del backend y
   `INTERNAL_ALLOWED_CIDRS=auto` vienen del arreglo de separación de bases (dependencia; T101 lo verifica).
3. **Esperado**: lo mismo que §1 paso 3; además `curl http://<host>:8091/api/v1/internal/identity` desde la
   LAN ⇒ 404 y `GET /api/v1/gw` ⇒ responde; sin `ELEA_REDIRECT`, `docker compose config` idéntico al de la instalación ya corregida por el arreglo de
   separación de bases.
4. Claude Desktop y Claude Code de la PC contra la pasarela local, destino Azure (§3–§4); evidencia en
   `verificacion-instalador-local.md`. Recién después, el runbook del servidor (T103), con su vuelta atrás.

## 2. Cargar los datos

Paso 1, **después de T-E** (antes no existe el cargador de regiones); pasos 2 y 3, desde T-B.

1. Región: se carga sola al arrancar con `REDIRECT_SEED_FILES` (T095); a mano,
   `python -m sentinel.redirect.regions_seed deploy/redirect-seeds/regions.americas.yaml` (T064). **Esperado**: región `AMERICAS` de instalación con `region_profiles` ⊇ `latam_ar` y
   `default_posture = masked_all` (D2 del análisis legal: todo el redirigido sale enmascarado).
2. Reglas de habilitación explícita:
   `python -m sentinel.catalog.habilitacion deploy/redirect-seeds/habilitacion-explicita.yaml` (T027).
   **Esperado**: listas vacías (D1) y ningún destino bloqueado.
3. Catálogo de Azure: `python -m sentinel.catalog.seed deploy/redirect-seeds/catalog-seed.azure-demo.yaml` y,
   en «Modelos», completar en cada entrada la **jurisdicción de inferencia** (la región real del recurso
   de Azure), la **entidad responsable** y las **jurisdicciones de entidad y de control** (FR-028a; datos
   que no se presumen). Sin jurisdicción de inferencia el destino se rechaza. Destinos:

   | Entrada | `real_model` (despliegue de Azure) | Nota |
   |---|---|---|
   | gpt-5.6-luna | `gpt-5.6-luna` | **a confirmar con el owner** que el despliegue existe (research R9); si no, opus → gpt-5.1-chat |
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
3. Residencia: **antes de T-E** (prueba de T045), Cumplimiento carga una postura explícita
   *fuera de región con enmascarado forzado* sin jurisdicciones para el alcance (fuerza el enmascarado hacia
   Azure en EE. UU., como lo hará el default); **después de T-E** no hace falta postura: rige la postura por
   defecto (enmascarado forzado en todo destino; research R32, A9). Para probar sin enmascarado, Cumplimiento
   registra una relajación por región o por destino (§7).
4. Política: **Encendida** para el alcance.
5. **Medir SC-003**: del paso 1 al 4, menos de 15 minutos sin ayuda técnica.

## 4. Claude Desktop y Claude Code (US1, US4)

- Claude Desktop (3P): `inferenceGatewayBaseUrl = https://<dominio>/api/v1/gw`, llave virtual,
  `bearer`, descubrimiento activado ([contracts/cara-claude.md §8](./contracts/cara-claude.md)).
- Claude Code: `ANTHROPIC_BASE_URL=https://<dominio>/api/v1/gw`, `ANTHROPIC_AUTH_TOKEN=<llave>`.

| Escenario | Esperado |
|---|---|
| Lista de modelos | un modelo por tier con «Sonnet · servido por gpt-5.1-chat» y la ventana real (US1 esc. 1) |
| Conversación con herramientas y streaming en Claude Code (`?beta=true`) | responde el destino; `model` = id público; sin «Unrecognized request argument supplied: safeguards» (T139 de Sentinel); auditoría con id pedido, destino, cara y fidelidad, sin contenido (US1 esc. 2, esc. 7) |
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

Con un destino Azure en `AMERICAS` (p. ej. EE. UU.) y otro marcado fuera (p. ej. una región de la UE):

| Postura | Esperado |
|---|---|
| ninguna (`default_posture = masked_all`), destino en EE. UU. o en la UE | DNI, CUIT/CUIL y CBU salen enmascarados y vuelven restaurados (SC-006); `default_posture_applied = masked_all` |
| la misma, con el analizador caído | el pedido se bloquea («El pedido no pudo protegerse…»: 400 en la cara Claude, 403 en la genérica) aunque la instalación diga «degradar» |
| ninguna, destino sin jurisdicción de inferencia | 403 «Modelo no disponible para tu región.» |
| relajación por región: Cumplimiento crea una región de nivel empresa con `region_profiles` ⊇ `latam_ar` y `default_posture = masked_offregion` (o el super-admin cambia la de instalación) | el destino de EE. UU. (inferencia, entidad y control en `AMERICAS`) sale sin forzado; el de la UE, enmascarado; `masking_relaxation = region` |
| el mismo cambio intentado por el admin de la empresa | 403: solo Cumplimiento relaja |
| con `masked_all`, el admin de la empresa agrega *solo jurisdicciones permitidas* = `AMERICAS` | el destino de la UE deja de alcanzarse (o responde un fallback); el de EE. UU. **sigue enmascarado** (piso) |
| relajación por destino sobre el de EE. UU. sin retención cero declarada | 422 con el motivo; el destino sigue enmascarado |
| el admin de la empresa crea una postura *apagada* | 422 `posture_less_strict`; nada cambia |
| el admin de la empresa edita la jurisdicción de control o la retención cero de una ficha | 403; solo Cumplimiento o super-admin |
| sin postura, `system` con DNI/CUIT/CBU, un PDF con texto y la respuesta del asistente reenviada en el 2.º turno | todo sale enmascarado (el PDF como texto) y vuelve restaurado; `masking_scope = full` |
| sin postura, una imagen o un PDF escaneado | bloqueo «El pedido no pudo protegerse…»; `unanalyzable_kinds` en la auditoría |
| borrar la región `AMERICAS` **por SQL en la base de prueba** (la API lo impide con 409) y reiniciar sin `REDIRECT_SEED_FILES` | respaldo en código: hacia un destino en `LATAM/AR`, enmascarado; hacia Azure en EE. UU., 403 «Modelo no disponible para tu región.»; `GET /api/v1/redirect/health` = 503 `region_row_missing` |
| *solo jurisdicciones permitidas* con fallback en `AMERICAS` | responde el fallback y la auditoría registra la sustitución |
| `default_posture` cambiado a `reject_offregion` (prueba del mecanismo) | destino de la UE: 403 «Modelo no disponible para tu región.» |

Panel y documentación: «seudonimización reversible», nunca «anonimización» ni «cumple con»; la región
aparece como criterio de riesgo y la residencia con 🟡 (D3, D10).

## 8. Modelos chinos y económicos 🟡 (hasta tener credencial)

Mismo flujo, con entradas `deepseek`, `openai_compatible` (Qwen, Kimi, MiniMax con su `api_base`),
`zai` (GLM) y `openrouter` (con lista de proveedores). Lo validan hoy los tests con upstream falso
(T024, T025, T057, T058); la prueba real queda 🟡 en la documentación.

| Caso | Esperado |
|---|---|
| Regla con estrategia «más barato» entre varios destinos | elige el de menor precio del catálogo; el costo registrado es el del destino real |
| Con listas de habilitación vacías (seed de Eleia, D1) | ninguna entrada bloqueada; la API oficial china se da de alta y sale **enmascarada** por la postura por defecto |
| Una regla `jurisdiction` cargada desde el panel que cubre la entrada | nace bloqueada; se habilita desde «Modelos» con motivo (queda en el registro) |
| El mismo modelo alojado en América (Azure/AWS en EE. UU., o OpenRouter con lista de proveedores de EE. UU.) | por defecto, enmascarado; sin forzado solo con una relajación por destino de Cumplimiento (alojador nombrado, jurisdicciones cargadas, retención cero; D5) |
| Una nube con servidores en EE. UU. y jurisdicción de control fuera de `AMERICAS` (o sin cargar) | no cuenta como en región: una relajación por región no le quita el forzado (D12) |
| OpenRouter | cada pedido sale con cero retención, sin recolección de datos y solo a la lista de proveedores permitidos; `openrouter_zdr: true` en la auditoría |
