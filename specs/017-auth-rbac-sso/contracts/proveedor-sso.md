# Contrato · Proveedor SSO (FR-006..FR-010)

## El contrato (registry-style, como las capas 027)

```
class SsoProvider(Protocol):
    provider_type: str                          # "entra" | "google" (C3) | ...
    def authorize_url(config, state) -> str     # inicio del flujo (redirect al IdP)
    def exchange_code(config, code) -> Identity # callback: code → identidad verificada
    # Identity = {email, subject, display_name} — lo MÍNIMO; claims extra se descartan
```

Alta de un proveedor nuevo = implementar el contrato + registrarlo. El flujo común (rutas, JIT, emisión de sesión, flag de licencia) NO se toca. v1: `entra` (OIDC authorization code + discovery, authlib — research D2).

## Config por tenant (tabla `sso_providers`, migración de esta spec)

| Campo | Contenido |
|---|---|
| `tenant_id` | dueño de la config (RLS) |
| `provider_type` | clave del registro |
| `config` JSONB | los 3 datos del cliente: directory/tenant ID del IdP, client_id, + metadata de discovery |
| `client_secret_encrypted` | Fernet (precedente 010:216-222) — jamás en claro, jamás en logs |
| `enabled` | interruptor operativo del tenant |

La escribe: el wizard 037 vía el bloque `sso` del perfil (sellado con Cristian/Falime 13-ago) o el tenant_admin por UI/API. La redirect URI se registra en el IdP DEL cliente (operatoria de instalación, documentada en docs vendibles).

## El flujo, de punta a punta

1. `GET /api/v1/auth/sso/login` → **gate `feature_enabled('sso')`** (fail-closed, primer consumidor 021) → authorize_url del proveedor del tenant.
2. Callback `GET /api/v1/auth/sso/callback` → exchange_code → Identity verificada.
3. **JIT por email** (research D4): centinela → activa ese User; nuevo → alta `role=client` por el camino actual (seat gate); existente activo → solo login. Jamás re-asigna rol/tenant.
4. Emisión: `create_session_token` — EL MISMO JWT del login local, con tenant claim (FR-007/FR-011). Aguas abajo, cero bifurcación.

## Reglas duras

- **Password login = fallback PERMANENTE** (FR-009): IdP caído o config rota degrada SOLO el camino SSO, con error claro + auth event; el login local no se entera. En sede air-gap, SSO simplemente no está.
- **Flag apagado** (FR-010): superficie oculta/inactiva (router 404/403 coherente + botón frontend ausente); la config del tenant PERSISTE. Licencias vigentes (Cámara `flags=[]`) operan sin re-emisión. *El perfil configura, la licencia autoriza.*
- **Lockout no aplica al camino SSO** (la identidad la custodia el IdP); ambos caminos emiten auth events.
- Futuros consumidores anotados, NO comprometidos: Google (C3), mapeo de grupos IdP→roles, SCIM, MFA.
