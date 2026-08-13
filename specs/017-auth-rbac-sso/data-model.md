# Data Model — 017

## Migraciones de esta spec

| # | Qué | Tipo |
|---|---|---|
| `013_sso_providers` | tabla nueva por tenant (ver contrato proveedor-sso) bajo RLS | esquema |
| `014_role_lectura` | CHECK `ck_users_role` amplía el enum con `lectura` | esquema |
| `015_encrypt_engine_key` | re-cifra `engine_key_token` existente (Fernet) + DROP de su índice | datos + índice |
| `016_rls_strict` | DROP `tenant_isolation_bootstrap` + flip NOSUPERUSER — **env-gated `BASA_RLS_STRICT`, APAGADA por default** (release siguiente, con Factory) | esquema, diferida |

## Entidades

- **Rol canónico** (`users.role`): `super_admin | tenant_admin | compliance_officer | client | lectura`. La matriz (`contracts/matriz-roles.md` ↔ `auth/matrix.py`) es la fuente de qué puede cada uno; el shim traduce a los literales legacy de los routers. Labels sectoriales = display (D9).
- **Sesión (JWT)**: claims `{sub, role, username, tenant, exp}` — `tenant` nuevo (FR-011); tokens pre-release sin claim: válidos ≤24 h con tenant default, registrado. Sin jti/refresh (diferidos con nombre). Revocación efectiva = `is_active` releído por request (sin cambios, documentado).
- **Config de proveedor SSO** (`sso_providers`): ver contrato. Secret SIEMPRE Fernet.
- **Evento de auth**: fila de auditoría clase `security_events` (clasificador 018) — metadata only: evento, actor (si existe), resultado, timestamps. Jamás passwords/tokens/códigos.
- **Estado de lockout**: contador Redis por cuenta con TTL — efímero; lo durable es el evento.
- **Credencial sk-basa**: `engine_key_token` pasa a cifrado en reposo; `expires_at` se vuelve efectivo en los 3 planos (el campo ya existe, keys.py:202 — cambia el enforcement, no el esquema).

## Sin cambios

`audit_logs` (intocada — regla compartida con la 018) · `seat_counter`/licencias (el rol `lectura` no consume seat porque el seat es la Connection) · esquema de `api_keys` salvo el índice de `engine_key_token`.
