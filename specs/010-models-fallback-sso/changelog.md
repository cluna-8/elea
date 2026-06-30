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
