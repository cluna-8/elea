# Changelog — Feature 010: Model Catalog, Fallback Automático & SSO Roadmap

## [1.0.0] — 2026-06-30

### Added

**Backend — `backend/src/api/chat.py`**
- Helpers `_get_config_path()`, `_check_configured()`, constante `_EU_COMPLIANT_PROVIDERS` extraídos como funciones reutilizables (antes inline en cada endpoint)
- `GET /chat/models` rediseñado: devuelve TODOS los modelos del config.yaml con `is_configured: bool` e `is_eu_compliant: bool`. Antes filtraba solo los que tenían credencial configurada, lo que ocultaba el catálogo completo al admin.
- `PATCH /chat/models/{model_name}` — actualiza `api_key` y/o `api_base` de un modelo ya existente en config.yaml. Permite configurar modelos pre-existentes desde la UI sin editar archivos.
- `GET /chat/fallbacks` — lee `router_settings.fallbacks` del config.yaml y devuelve `{model_name: fallback_model_name}`.
- `PUT /chat/fallbacks/{model_name}` — escribe la entrada de fallback en `router_settings.fallbacks`. Si `fallback_model` es null, elimina la entrada.

**Frontend — `frontend/src/services/api.ts`**
- `updateModelCredential(modelName, apiKey, apiBase?)` — PATCH /chat/models/{name}
- `getFallbacks()` — GET /chat/fallbacks
- `setFallback(modelName, fallbackModel | null)` — PUT /chat/fallbacks/{name}

**Frontend — `frontend/src/pages/ModelsPage.tsx`** (reescritura completa)
- Vista principal: tabla de modelos activos con columnas Nombre, Proveedor, Compliance (UE/Cloud), Fallback (select auto-guardado), Eliminar
- Modal catálogo: se abre con "+ Agregar Modelo"; muestra todos los modelos del config.yaml con filtros Todos / Solo UE / Local
- Badges por modelo en catálogo: proveedor, "UE Compliant" (verde), "✓ Activo" o "Sin credencial" + hint del env var necesario
- Modal activación: al hacer click en "Configurar" sobre modelo sin credencial; formulario con campo API key + API base (condicional por proveedor)
- Sección "Modelo personalizado" dentro del catálogo (pestaña dentro del modal) para registrar modelos fuera del catálogo estándar

**Frontend — `frontend/src/pages/UsersPage.tsx`**
- Nuevo tab "Autenticación & SSO" (4to tab)
- Grid de 7 proveedores con nombre, protocolo, target, descripción y badge Activo/Próximamente:
  - Azure AD / Entra ID — OIDC/OAuth 2.0 — Enterprise — Próximamente
  - Google Workspace — OIDC/OAuth 2.0 — SME/Clínicas — Próximamente
  - Okta — OIDC/SAML 2.0 — Enterprise — Próximamente
  - Auth0 — OIDC/OAuth 2.0 — Universal — Próximamente
  - Keycloak — OIDC/SAML 2.0 — Self-hosted — Próximamente
  - SAML 2.0 genérico — SAML 2.0 — Enterprise heredado — Próximamente
  - Usuario & Contraseña (JWT) — JWT HS256 — Usuarios internos — **Activo**

### Fixed
- Bug en `GET /chat/models`: referencias a variables `LITELLM_URL` y `LITELLM_KEY` no definidas en el bloque de fallback al motor IA. Corregidas a `_ENGINE_URL` y `_ENGINE_MASTER_KEY`.
- Eliminación de código duplicado en `delete_model` que hardcodeaba el path del config (ahora usa `_get_config_path()`).

### Design Decisions
- **Todos los modelos visibles**: el catálogo muestra los 14 modelos del config.yaml independientemente de si tienen credenciales. Esto permite al admin entender qué proveedores están disponibles y qué necesita configurar para activarlos.
- **Fallback nativo del motor**: los fallbacks se escriben en `router_settings.fallbacks` del config.yaml y son procesados por el motor IA internamente. No se requiere lógica adicional en el backend de Basa.
- **SSO solo visual**: los proveedores SSO se muestran como roadmap. No hay implementación de OAuth2/OIDC en esta feature — el objetivo es informar al admin y permitir planificar la integración con el equipo de Basa.
- **Credenciales en config.yaml**: al activar un modelo desde la UI, la API key se escribe directamente en config.yaml (no en .env). Esto es consistente con el comportamiento existente del endpoint `POST /chat/models`. En producción, se recomienda preferir variables de entorno en .env para claves sensibles.

---

## [1.2.0] — 2026-06-30 (QA Session — cross-feature fixes)

### Fixed

**Backend — `backend/src/api/chat.py`**
- Auth pipeline reescrito: distingue llave virtual (`sk-` prefix, valida contra hash SHA-256 en DB) de sesión JWT (decodifica con HS256, resuelve usuario y grupo). Antes solo se aceptaban llaves virtuales, lo que bloqueaba el Playground con "Llave virtual inválida" cuando el usuario usaba su sesión.
- Resolución de grupo para sesiones JWT: si el usuario tiene `group_id`, se carga `user.group` para aplicar compliance del equipo. Antes las reglas de grupo no se aplicaban en sesiones de frontend.
- Alcance del proyecto de compliance corregido: si la llave/usuario/grupo no tiene proyecto asignado, se devuelve `[]` (sin reglas). Antes se aplicaban **todos** los proyectos activos a cualquier sesión, causando que "Pendiente de validación sanitaria" apareciera para todos los usuarios sin asignación.
- `guardian_events` en audit log: los eventos de guardianes locales (`guardian_triggers` del pipeline Basa) ya se fusionan con los eventos del motor IA (`guardian_events`). Antes ambas listas eran independientes y los triggers locales no aparecían en el log.

**Backend — `backend/src/services/guardian_service.py`**
- Secret detection regex de OpenAI API Key relajado: `sk-[a-zA-Z0-9]{10,}` (antes `{48}`, que requería exactamente 48 chars y perdía claves de test cortas).

**Frontend — `frontend/src/pages/PlaygroundPage.tsx`**
- Selector de modo de autenticación: botones "Sesión actual" (JWT, default) / "Llave virtual" (input manual). Antes el Playground solo aceptaba llave virtual introducida manualmente, lo que era confuso para usuarios que ya tenían sesión abierta.

**Frontend — `frontend/src/pages/UsersPage.tsx`**
- Botón "Asignar equipo" en tabla de usuarios: abre modal con selector de grupo; llama a `PUT /users/{id}` con todos los campos requeridos. Antes no había forma de asignar un grupo a un usuario existente desde la UI.
- Botón "Editar" en tarjetas de presupuesto: abre modal para modificar límite USD y tokens; llama a `PUT /budgets/{id}` con todos los campos requeridos. Antes no había forma de editar un presupuesto existente desde la UI.
- Spend de presupuesto con 4 decimales: `$0.0040` en lugar de `$0` para gastos pequeños.

**Frontend — `frontend/src/pages/CompliancePage.tsx`**
- Banner de uso interno en tab DSR: advierte que el módulo es herramienta de registro interno y no sustituye el proceso legal.
- Banner en Consentimientos: advierte que no hay firma digital — su valor legal depende del sistema origen.
- Banner en Cola de Revisión Humana: advierte que es supervisión interna, no validación clínica con valor legal.

### Added

**Backend — `backend/src/api/chat.py`**
- `GET /chat/models/pricing`: consulta `GET {ENGINE_URL}/model/info` y devuelve lista de modelos con `input_cost_per_million`, `output_cost_per_million`, `max_tokens`, `max_input_tokens`. Multiplica `*_cost_per_token` × 1 000 000 para display.

**Frontend — `frontend/src/services/api.ts`**
- `getModelsPricing()` — GET /chat/models/pricing
- `updateUser(userId, current, patch)` — PUT /users/{id} con merge de campos actuales
- `updateBudget(budgetId, patch)` — PUT /budgets/{id}

**Frontend — `frontend/src/pages/ModelsPage.tsx`**
- Columna "Precio / 1M tokens" en tabla de modelos activos: carga en paralelo con modelos; muestra IN / OUT en USD o "Gratis" para modelos Ollama locales.

**`litellm/config.yaml`**
- `model_info: input_cost_per_token: 0 / output_cost_per_token: 0` para `ollama-gemma4-31b` y `ollama-qwen3-2b`. Los modelos locales aparecen con precio $0 en el widget y en audit logs.

**`docker-compose.yml`**
- `extra_hosts: - "host.docker.internal:host-gateway"` en servicio litellm para resolución de nombre en Linux.

### Design Decisions (1.2.0)
- **Orden de resolución compliance**: llave virtual → usuario → grupo → vacío. Sin asignación explícita, ninguna regla de compliance aplica. Esto evita que reglas de proyectos "médicos" se apliquen a usuarios administrativos no asignados.
- **Playground dual-auth**: el modo "Sesión actual" usa el JWT de la sesión (el mismo que usa toda la UI) y no requiere ninguna llave. El modo "Llave virtual" permite probar el presupuesto y permisos exactos de una llave específica.
- **Banners de uso interno en compliance**: los módulos DSR, Consentimientos y Cola de Revisión tienen valor como herramienta de registro interno, pero sin integración con firma digital / HIS / asesoría jurídica no tienen valor legal autónomo. Los banners previenen malentendidos sin deshabilitar las funcionalidades.

---

## [1.1.0] — 2026-06-30

### Added (correcciones post-1.0.0)

**Backend — `backend/src/api/chat.py`**
- `PATCH /chat/models/{model_name}` rediseñado: acepta `litellm_params: dict` genérico en lugar de `api_key/api_base`. Hace merge con los params existentes, permitiendo configurar campos específicos de cada proveedor (aws_access_key_id, vertex_project, ibm_api_key, etc.)

**Backend — `backend/src/services/guardian_service.py`**
- Umbral de re-seed cambiado de `< 8` a `< 9`
- Agregado guardián `presidio` (g9): type=`presidio`, inactivo por defecto, config con `analyzer_url`, `anonymizer_url`, `language` (es), `entities`, `action` (MASK)

**Backend — `backend/src/services/presidio_service.py`**
- Agregado `analyze_text_http(text, analyzer_url, language, entities)`: llama a `POST {analyzer_url}/analyze` de Presidio Analyzer HTTP API. Fallback silencioso a regex si el servicio no responde.
- Agregado `anonymize_text_http(text, anonymizer_url, analyzer_results)`: llama a `POST {anonymizer_url}/anonymize` de Presidio Anonymizer HTTP API.

**Frontend — `frontend/src/services/api.ts`**
- `updateModelCredential` actualizado: firma cambiada a `(modelName, litellmParams: Record<string,string>)`

**Frontend — `frontend/src/pages/ModelsPage.tsx`**
- `PROVIDER_FIELDS` — mapa de campos específicos por proveedor con label, placeholder, type y hint contextual:
  - `bedrock`: aws_access_key_id, aws_secret_access_key, aws_region_name (hint de regiones EU)
  - `azure`: api_key, api_base, api_version
  - `vertex_ai`: vertex_project, vertex_location, vertex_credentials
  - `watsonx`: ibm_api_key, ibm_project_id, ibm_url
  - `cloudflare`: api_key, api_base (hint de Account ID)
  - `ollama`: api_base (con mensaje explicativo, sin key requerida)
  - `openai/anthropic/gemini/groq`: api_key único
- Modal Configurar: usa `PROVIDER_FIELDS` para renderizar los inputs correctos por proveedor; el botón Guardar recoge todos los fields como `litellm_params` dict y llama a PATCH

**Frontend — `frontend/src/pages/SecurityPage.tsx`**
- `presidio` agregado a `GUARDIAN_DESCRIPTIONS` y `GUARDIAN_ICONS`
- `isPresidio` flag en el panel de config
- Panel Presidio: campos Analyzer URL, Anonymizer URL, Idioma, Acción + nota de setup con imágenes Docker de Microsoft + aviso de fallback a regex

### Design Decisions (1.1.0)
- **Per-provider fields**: cada proveedor de IA tiene una estructura de credenciales diferente (Bedrock usa AWS IAM, Vertex usa Service Accounts, WatsonX usa IBM IAM). El modal unifica todo con una sola config por proveedor en lugar de un campo genérico.
- **Presidio como guardián separado**: Presidio convive con el guardián `pii_masking` (regex). Presidio está inactivo por defecto y requiere infraestructura adicional. El regex sigue siendo el default para entornos sin servicios Presidio desplegados.
- **HTTP fallback silencioso en Presidio**: si el Analyzer no responde, `analyze_text_http` devuelve `[]` (lista vacía) y el pipeline continúa con regex. Nunca rompe el flujo de chat.
