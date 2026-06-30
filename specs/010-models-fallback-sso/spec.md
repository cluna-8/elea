# Feature 010 — Model Catalog, Fallback Automático & SSO Roadmap

## Objetivo
Tres mejoras al sistema de gestión de modelos y autenticación:

1. **Catálogo de modelos**: mostrar todos los modelos configurados en la pasarela (no solo los activos), con badges de compliance UE y estado de credencial.
2. **Fallback automático**: permitir configurar desde la UI qué modelo alternativo usar si el principal falla, usando el mecanismo nativo de router_settings del motor IA.
3. **SSO Roadmap**: mostrar en la UI los métodos de autenticación disponibles y próximos, para que administradores y clientes puedan planificar la integración.

## Módulos afectados

### Backend (`backend/src/api/chat.py`)
- `GET /chat/models` → devuelve TODOS los modelos del config.yaml con flags `is_configured` e `is_eu_compliant`. Anteriormente filtraba y solo devolvía los configurados.
- `PATCH /chat/models/{model_name}` → actualiza `api_key` y/o `api_base` de un modelo existente en config.yaml. Permite activar desde UI sin editar archivos.
- `GET /chat/fallbacks` → devuelve el mapa `{model_name: fallback_model_name}` leyendo `router_settings.fallbacks` del config.yaml.
- `PUT /chat/fallbacks/{model_name}` → escribe/borra la entrada de fallback para un modelo en `router_settings.fallbacks`.

### Frontend
- `ModelsPage.tsx`: rediseño completo — tabla de activos con selector de fallback por fila + modal de catálogo con filtros (Todos / Solo UE / Local) + modal de activación por modelo.
- `UsersPage.tsx`: nuevo tab "Autenticación & SSO" con 7 proveedores listados.
- `api.ts`: tres métodos nuevos (`updateModelCredential`, `getFallbacks`, `setFallback`).

## EU Compliance en modelos

Proveedores marcados como UE Compliant (pueden configurarse con residencia de datos en Europa):
- AWS Bedrock (`bedrock/*`) — regiones EU disponibles
- Google Vertex AI (`vertex_ai/*`) — regiones EU disponibles
- Azure OpenAI (`azure/*`) — EU Data Boundary
- IBM WatsonX (`watsonx/*`) — EU región disponible
- Ollama (`ollama/*`) — on-premise, sin salida de datos

Proveedores Cloud estándar (datos procesados en US por defecto):
- OpenAI, Anthropic, Gemini, Groq, Cloudflare

## Mecanismo de fallback

LiteLLM soporta `router_settings.fallbacks` en config.yaml nativamente. Cuando el modelo principal devuelve error (429, timeout, 500 del proveedor), el router reintenta automáticamente con el modelo de fallback antes de devolver error al cliente. Basa no necesita lógica adicional en Python — solo configurar el yaml.

Ejemplo de configuración generada:
```yaml
router_settings:
  disable_cooldowns: true
  fallbacks:
    - {gpt-4o: [claude-3-5-sonnet]}
    - {claude-3-5-sonnet: [gemini-2.5-flash]}
```

## SSO — Proveedores en Roadmap

| Proveedor | Protocolo | Target | Estado |
|-----------|-----------|--------|--------|
| Azure AD / Entra ID | OIDC / OAuth 2.0 | Enterprise | Próximamente |
| Google Workspace | OIDC / OAuth 2.0 | SME / Clínicas | Próximamente |
| Okta | OIDC / SAML 2.0 | Enterprise | Próximamente |
| Auth0 | OIDC / OAuth 2.0 | Universal | Próximamente |
| Keycloak | OIDC / SAML 2.0 | Self-hosted | Próximamente |
| SAML 2.0 genérico | SAML 2.0 | Enterprise heredado | Próximamente |
| Usuario & Contraseña (JWT) | JWT HS256 | Usuarios internos | **Activo** |

## Presidio — Guardián NLP real

Presidio corre como dos microservicios HTTP independientes (imágenes oficiales de Microsoft):
- `mcr.microsoft.com/presidio-analyzer` — detecta entidades PII/PHI usando NLP (spaCy)
- `mcr.microsoft.com/presidio-anonymizer` — anonimiza el texto según los resultados del analyzer

Integración en Basa:
- El guardián tipo `presidio` almacena `analyzer_url` y `anonymizer_url` en su config JSON
- `presidio_service.py` expone `analyze_text_http` y `anonymize_text_http` que llaman las APIs REST
- Si los servicios no están disponibles, el call falla silenciosamente y el regex de `pii_masking` actúa como fallback
- La integración en el pipeline de `guardian_service.py` (usar Presidio cuando esté configurado) queda pendiente para feature 011

## Fuera de alcance (010)
- Integración de Presidio en el pipeline de chat (feature 011 — T-032)
- Implementación real de SSO (autenticación contra proveedor externo)
- Hot-reload del motor al cambiar config.yaml (requiere llamada a `/reload` del motor)
