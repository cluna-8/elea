# Plan — Feature 010: Model Catalog, Fallback Automático & SSO Roadmap

> As-built: documenta lo que se implementó.

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `backend/src/api/chat.py` | `GET /chat/models` devuelve TODOS los modelos con `is_configured` e `is_eu_compliant`; `PATCH /chat/models/{name}` merge de credenciales en config.yaml; `GET /chat/fallbacks`; `PUT /chat/fallbacks/{name}` |
| `frontend/src/pages/ModelsPage.tsx` | Tabla de activos con columna fallback (select), badge EU; modal catálogo con filtros y activación per-provider |
| `frontend/src/pages/SecurityPage.tsx` | Cards de guardianes (grid), panel de config unificado, Presidio integrado |
| `frontend/src/pages/UsersPage.tsx` | Tab "Autenticación & SSO" con 7 proveedores |
| `frontend/src/services/api.ts` | `updateModelCredential`, `getFallbacks`, `setFallback`, `getModelsPricing` |
| `backend/src/services/presidio_service.py` | `analyze_text_http`, `anonymize_text_http` — HTTP API Presidio con fallback a regex |
| `litellm/config.yaml` | Sección `router_settings.fallbacks` para fallback automático de modelos |

## Endpoints nuevos

| Endpoint | Descripción |
|----------|-------------|
| `PATCH /chat/models/{model_name}` | Actualiza credenciales de un modelo en config.yaml |
| `GET /chat/fallbacks` | Lee mapa `{model: fallback}` de router_settings |
| `PUT /chat/fallbacks/{model_name}` | Escribe/borra entrada de fallback en config.yaml |
| `GET /chat/models/pricing` | Devuelve precios input/output por 1M tokens |

## Decisiones clave

- Fallback se configura en `litellm/config.yaml → router_settings.fallbacks` (nativo de LiteLLM). La UI solo edita este YAML.
- SSO tab es roadmap visual (7 proveedores: Azure AD, Google, Okta, Auth0, Keycloak, SAML 2.0, JWT local). Solo JWT local activo.
- Presidio: guardián opcional que requiere servicios externos (analyzer + anonymizer). Fallback a regex si no disponible.
- `_EU_COMPLIANT_PROVIDERS` = Azure, Vertex AI (GCP), AWS Bedrock. Resto = "Cloud estándar".
- Hot-reload tras cambio de config.yaml pendiente (T-031).
