# Tasks — 010 Model Catalog, Fallback Automático & SSO Roadmap

## Phase 1 — Backend

- [x] T-001: Extraer helpers `_get_config_path()` y `_check_configured()` en `chat.py` para eliminar código duplicado entre endpoints
- [x] T-002: Agregar constante `_EU_COMPLIANT_PROVIDERS` con los proveedores que soportan residencia de datos en la UE
- [x] T-003: Modificar `GET /chat/models` — devolver TODOS los modelos del config.yaml con campos `is_configured` e `is_eu_compliant` (antes filtraba solo los configurados)
- [x] T-004: Corregir bug en `GET /chat/models` — referencias a `LITELLM_URL` y `LITELLM_KEY` no definidas (reemplazadas por `_ENGINE_URL` y `_ENGINE_MASTER_KEY`)
- [x] T-005: Agregar `PATCH /chat/models/{model_name}` — actualizar `api_key` y/o `api_base` de un modelo existente en config.yaml
- [x] T-006: Agregar `GET /chat/fallbacks` — leer `router_settings.fallbacks` del config.yaml y devolver como dict `{model: fallback_model}`
- [x] T-007: Agregar `PUT /chat/fallbacks/{model_name}` — escribir/borrar entrada de fallback en `router_settings.fallbacks` del config.yaml

## Phase 2 — Frontend: api.ts

- [x] T-008: Agregar `updateModelCredential(modelName, apiKey, apiBase?)` — llama a `PATCH /chat/models/{name}`
- [x] T-009: Agregar `getFallbacks()` — llama a `GET /chat/fallbacks`
- [x] T-010: Agregar `setFallback(modelName, fallbackModel | null)` — llama a `PUT /chat/fallbacks/{name}`

## Phase 3 — Frontend: ModelsPage

- [x] T-011: Rediseñar ModelsPage — tabla de modelos activos (is_configured=true) como vista principal
- [x] T-012: Agregar columna "Fallback automático" a la tabla de activos con `<select>` que lista otros modelos activos; onChange auto-guarda via `setFallback`
- [x] T-013: Agregar columna "Compliance" con badge "UE Compliant" / "Cloud estándar"
- [x] T-014: Implementar modal "Catálogo de Modelos" — se abre al hacer click en "+ Agregar Modelo"
- [x] T-015: Catálogo con filtros: Todos / Solo UE Compliant / Local (Ollama)
- [x] T-016: Cada modelo en catálogo muestra: nombre, proveedor, badge EU, estado activo/sin credencial, hint de env vars requeridas
- [x] T-017: Botón "Configurar" en modelo no activo → abre modal de activación con form para ingresar API key
- [x] T-018: Modal de activación llama a `updateModelCredential` (PATCH)
- [x] T-019: Sección "Modelo personalizado" dentro del catálogo para registrar modelos no incluidos en config.yaml

## Phase 4 — Frontend: UsersPage SSO

- [x] T-020: Agregar tab "Autenticación & SSO" a UsersPage
- [x] T-021: Mostrar grid de 7 proveedores (Azure AD, Google, Okta, Auth0, Keycloak, SAML 2.0, JWT local) con badge Activo/Próximamente, protocolo y descripción

## Pendiente (fuera de scope 010)

- [ ] T-022: Hot-reload del motor tras cambio de config.yaml (llamar a endpoint `/reload` del motor IA)
- [ ] T-023: Implementación real de OAuth2/OIDC con Azure AD (feature 011 o posterior)
- [ ] T-024: Implementación real de Google Workspace SSO
- [ ] T-025: Implementación real de Keycloak / SAML 2.0
