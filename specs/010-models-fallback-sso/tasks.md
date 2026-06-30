# Tasks — 010 Model Catalog, Fallback Automático & SSO Roadmap

## Phase 1 — Backend

- [x] T-001: Extraer helpers `_get_config_path()` y `_check_configured()` en `chat.py` para eliminar código duplicado entre endpoints
- [x] T-002: Agregar constante `_EU_COMPLIANT_PROVIDERS` con los proveedores que soportan residencia de datos en la UE
- [x] T-003: Modificar `GET /chat/models` — devolver TODOS los modelos del config.yaml con campos `is_configured` e `is_eu_compliant` (antes filtraba solo los configurados)
- [x] T-004: Corregir bug en `GET /chat/models` — referencias a `LITELLM_URL` y `LITELLM_KEY` no definidas (reemplazadas por `_ENGINE_URL` y `_ENGINE_MASTER_KEY`)
- [x] T-005: Agregar `PATCH /chat/models/{model_name}` — recibe `litellm_params: dict` y hace merge con los params existentes del modelo en config.yaml (reemplaza el esquema original de api_key/api_base)
- [x] T-006: Agregar `GET /chat/fallbacks` — leer `router_settings.fallbacks` del config.yaml y devolver como dict `{model: fallback_model}`
- [x] T-007: Agregar `PUT /chat/fallbacks/{model_name}` — escribir/borrar entrada de fallback en `router_settings.fallbacks` del config.yaml

## Phase 2 — Frontend: api.ts

- [x] T-008: Agregar `updateModelCredential(modelName, litellmParams: Record<string,string>)` — llama a `PATCH /chat/models/{name}` con dict de params específicos por proveedor
- [x] T-009: Agregar `getFallbacks()` — llama a `GET /chat/fallbacks`
- [x] T-010: Agregar `setFallback(modelName, fallbackModel | null)` — llama a `PUT /chat/fallbacks/{name}`

## Phase 3 — Frontend: ModelsPage

- [x] T-011: Rediseñar ModelsPage — tabla de modelos activos (is_configured=true) como vista principal
- [x] T-012: Agregar columna "Fallback automático" a la tabla de activos con `<select>` que lista otros modelos activos; onChange auto-guarda via `setFallback`
- [x] T-013: Agregar columna "Compliance" con badge "UE Compliant" / "Cloud estándar"
- [x] T-014: Implementar modal "Catálogo de Modelos" — se abre al hacer click en "+ Agregar Modelo"
- [x] T-015: Catálogo con filtros: Todos / Solo UE Compliant / Local (Ollama)
- [x] T-016: Cada modelo en catálogo muestra: nombre, proveedor, badge EU, estado activo/sin credencial, hint de env vars requeridas
- [x] T-017: Botón "Configurar" en modelo no activo → abre modal de activación con campos específicos por proveedor (PROVIDER_FIELDS)
- [x] T-018: Modal de activación llama a `updateModelCredential` (PATCH) — campos per-provider: bedrock (3 AWS), azure (key+base+version), vertex_ai (project+location+credentials), watsonx (key+projectId+url), cloudflare (key+base), ollama (base url), openai/anthropic/gemini/groq (api_key único)
- [x] T-019: Sección "Modelo personalizado" dentro del catálogo para registrar modelos no incluidos en config.yaml

## Phase 4 — Frontend: UsersPage SSO

- [x] T-020: Agregar tab "Autenticación & SSO" a UsersPage
- [x] T-021: Mostrar grid de 7 proveedores (Azure AD, Google, Okta, Auth0, Keycloak, SAML 2.0, JWT local) con badge Activo/Próximamente, protocolo y descripción

## Phase 5 — Presidio (NLP real PII/PHI)

- [x] T-026: Agregar guardián `presidio` al seed en `guardian_service.py` — umbral subido de < 8 a < 9; config con `analyzer_url`, `anonymizer_url`, `language`, `entities`, `action`
- [x] T-027: `presidio_service.py` — agregar `analyze_text_http(text, analyzer_url, language, entities)` y `anonymize_text_http(text, anonymizer_url, results)` que llaman las HTTP APIs de Presidio con fallback a regex si el servicio no está disponible
- [x] T-028: `SecurityPage.tsx` — agregar Presidio a GUARDIAN_DESCRIPTIONS e GUARDIAN_ICONS; panel de config muestra Analyzer URL, Anonymizer URL, idioma, acción e instrucciones de setup (imágenes Docker de Microsoft)

## Phase 6 — Security UI redesign

- [x] T-029: Rediseñar SecurityPage — guardianes como card grid (1/2/3 col) con nombre, badge Local/Motor IA, chip apply_on, descripción y toggle independiente
- [x] T-030: Panel de configuración unificado bajo el grid — se abre al seleccionar una card, incluye panel de prueba para guardianes engine-backed

## Pendiente (fuera de scope 010)

- [ ] T-031: Hot-reload del motor tras cambio de config.yaml (llamar a endpoint `/reload` del motor IA)
- [ ] T-032: Integrar `analyze_text_http` en el pipeline de `guardian_service.py` — usar Presidio cuando `analyzer_url` está configurado, regex como fallback (feature 011)
- [ ] T-033: Implementación real de OAuth2/OIDC con Azure AD (feature 011 o posterior)
- [ ] T-034: Implementación real de Google Workspace SSO
- [ ] T-035: Implementación real de Keycloak / SAML 2.0
