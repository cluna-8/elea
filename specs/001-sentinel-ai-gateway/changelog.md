# Changelog: Sentinel Secure AI Gateway

**Proyecto**: Sentinel Secure AI Gateway (by sentinel dev)
**Rama**: `001-sentinel-ai-gateway`
**Última actualización**: 2026-06-29

---

## Sesión 1 — 2026-06-29: Construcción completa del MVP

### Resumen ejecutivo

En esta sesión se construyó el sistema completo desde cero: infraestructura Docker, backend FastAPI, base de datos PostgreSQL, frontend React/Vite, sistema de guardianes de seguridad, y el playground interactivo con animación de capas.

---

## 1. Infraestructura y Docker

### 1.1 `docker-compose.yml`
- Se orquestaron **6 contenedores**: `sentinel-frontend`, `sentinel-backend`, `sentinel-litellm`, `sentinel-db` (los contenedores de Presidio se eliminaron por consumo excesivo de RAM).
- **Puertos de host** (configuración final):
  - Frontend: host `8080` → container `5173` (Vite)
  - Backend: host `8081` → container `8000` (FastAPI/Uvicorn)
  - LiteLLM: interno `4000`
  - PostgreSQL: interno `5432`

### 1.2 Variables de entorno (`.env`)
Claves gestionadas: `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION`, `GEMINI_API_KEY`, `DATABASE_URL`, `LITELLM_MASTER_KEY`

---

## 2. Backend — FastAPI

### 2.1 Routers (`backend/src/api/`)

| Router | Prefijo | Descripción |
|--------|---------|-------------|
| `users.py` | `/api/v1/users` | CRUD de usuarios y grupos |
| `budgets.py` | `/api/v1/budgets` | CRUD de presupuestos y límites |
| `keys.py` | `/api/v1/keys` | Generación y revocación de llaves virtuales |
| `policy.py` | `/api/v1/security/policy` | Política de seguridad activa |
| `guardians.py` | `/api/v1/guardians` | Catálogo de guardianes de seguridad |
| `audit.py` | `/api/v1/audit-logs` | Registro inmutable de transacciones |
| `chat.py` | `/api/v1/chat/completions` | Endpoint principal de la pasarela |

### 2.2 Pipeline de chat — 5 capas

```
[Entrada] → [01 Guardianes] → [02 Enmascaramiento PII] → [03 Optimización] → [04 LLM] → [05 Desenmascaramiento]
```

Campos devueltos en `metadata` de la respuesta:
- `layer_masking`: entidades detectadas, prompt enmascarado
- `layer_guardians`: lista `guardian_triggers` de guardianes activados
- `layer_llm`: modelo, tokens, `cost_usd`, latencia
- `layer_optimization`: tokens ahorrados
- `layer_unmasking`: respuesta restaurada

### 2.3 CORS permitidos en `main.py`
- `http://localhost:5173` (Vite dev)
- `http://localhost:8080` (host producción)

---

## 3. Modelos SQLAlchemy (`backend/src/models/`)

| Modelo | Tabla | Descripción |
|--------|-------|-------------|
| `User` | `users` | Usuario con rol, hash SHA-256, grupo |
| `Group` | `groups` | Departamento o equipo de trabajo |
| `Budget` | `budgets` | Límites USD/tokens por usuario o grupo |
| `APIKey` | `api_keys` | Llaves `sentinel_sk_...`, solo hash SHA-256 almacenado |
| `SecurityPolicy` | `security_policies` | Perfil GDPR/AI Act/Headroom |
| `AuditLog` | `audit_logs` | Transacciones sin PII crudo |
| `Guardian` | `guardians` | Catálogo de 8 guardianes de seguridad |

> **Regla**: Todos los modelos deben importarse en `backend/src/models/__init__.py` para que SQLAlchemy cree las tablas automáticamente en el startup.

**Hash de contraseñas**: SHA-256 via `hashlib` (evita bugs de passlib/bcrypt con Python 3.12).

**Llaves virtuales**: generadas con `secrets.token_urlsafe(32)`, prefijo `sentinel_sk_`, solo hash SHA-256 en BD, clave en claro mostrada **una sola vez**.

---

## 4. Servicios (`backend/src/services/`)

### 4.1 `presidio_service.py` — Motor de Enmascaramiento PII/PHI

Motor regex local sin dependencias externas. Entidades detectadas:
- `PERSON`, `DNI`, `CUIL`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `MEDICAL_LICENSE`

**Mecanismo de reversibilidad**: `placeholder_map` en memoria → `{ "<PERSON_1>": "Juan Pérez" }` → se aplica al texto de respuesta del LLM.

### 4.2 `guardian_service.py` — Sistema de Guardianes

Catálogo de 8 guardianes (pre-scan antes del LLM):

| # | Guardian | Tipo |
|---|----------|------|
| 1 | Enmascaramiento PII/PHI | Local |
| 2 | Detección de Secretos | Local |
| 3 | Enrutamiento Sensible (GDPR) | Local |
| 4 | Moderación OpenAI | Cloud/Mock |
| 5 | Lakera AI Guard (jailbreak) | Cloud/Mock |
| 6 | Azure Content Safety | Cloud/Mock |
| 7 | LlamaGuard (Meta) | Local/Mock |
| 8 | AWS Bedrock Guardrails | Cloud/Mock |

**Pre-scan de nombres personalizados** (`custom_names`):
- Se ejecuta antes de Presidio con regex de word boundaries
- Nombres por defecto: `["Pedro", "Cristian", "Juan Pérez", "María López", "Carlos Rodríguez"]`
- Seeding automático en startup con auto-migración

**Mutación de JSON en SQLAlchemy** (patrón requerido):
```python
from sqlalchemy.orm.attributes import flag_modified
guardian.config["custom_names"] = new_names
flag_modified(guardian, "config")
db.commit()
```

### 4.3 `routing_service.py` — Enrutamiento GDPR
Detecta política GDPR activa y redirige a endpoints EU. Si no hay endpoint EU disponible, registra warning pero no bloquea (configurable).

### 4.4 `audit_service.py` — Auditoría
Guarda `AuditLog` asíncronamente. Campos: `timestamp`, `user_id`, `api_key_id`, `model`, `prompt_tokens`, `completion_tokens`, `cost_usd`, `pii_detected`, `masked_entities`, `compliance_status`, `latency_ms`, `tokens_saved_by_optimization`. **Nunca almacena prompts originales ni PII crudo.**

---

## 5. Frontend — React/Vite (`frontend/src/`)

### 5.1 Principios de Diseño

- Interfaz **100% tipográfica**: sin iconos decorativos en navegación, botones o headers
- Jerarquía visual mediante tipografía, espaciado, colores y bordes
- Inspiración: Vercel, Linear, Railway (paneles de herramientas premium)

### 5.2 Páginas

| Página | Archivo | Descripción |
|--------|---------|-------------|
| Login | `LoginPage.tsx` | Auth demo `admin`/`admin`, persistencia localStorage |
| Playground | `PlaygroundPage.tsx` | Chat + animación de 5 capas en tiempo real |
| Seguridad | `SecurityPage.tsx` | Toggle de 8 guardianes + config PII |
| Modelos | `ModelsPage.tsx` | CRUD de modelos, sin referencias a LiteLLM |
| Políticas | `PoliciesPage.tsx` | CRUD de perfiles GDPR/AI Act |
| Usuarios | `UsersPage.tsx` | Equipos, miembros, presupuestos y llaves virtuales |
| Auditoría | `AuditPage.tsx` | Tabla filtrable y paginada de transacciones |

### 5.3 `services/api.ts` — Cliente

Base URL: `http://localhost:8081/api/v1`

Métodos: `getUsers`, `createUser`, `getGroups`, `createGroup`, `getBudgets`, `createBudget`, `getKeys`, `createKey`, `deleteKey`, `getSecurityPolicy`, `updateSecurityPolicy`, `getPolicies`, `createPolicy`, `updatePolicy`, `deletePolicy`, `getGuardians`, `updateGuardian`, `getAuditLogs`, `getModels`, `addModel`, `deleteModel`, `sendChatMessage`.

---

## 6. Bugs Corregidos

### BUG-001 — `$NaN` y `/ chars` en tablas de datos

**Causa**: SQLAlchemy serializa `NUMERIC` como `Decimal` → JSON lo convierte a string → `.toFixed()` no existe en strings → `TypeError`.

**Fix**: `Number(valor).toFixed(N)` en todos los puntos de formato numérico.

**Archivos**: `AuditPage.tsx`, `UsersPage.tsx`, `PlaygroundPage.tsx`

---

### BUG-002 — Mismatch de nombres de campos en Auditoría

| Frontend esperaba | API devuelve |
|------------------|--------------|
| `prompt_length` | `prompt_tokens` |
| `completion_length` | `completion_tokens` |
| `cost` | `cost_usd` |

**Fix**: Actualizar interfaz TypeScript `AuditLog` y todos los puntos de uso en `AuditPage.tsx`.

---

### BUG-003 — Tabla `guardians` no creada en startup

**Causa**: `Guardian` no importado en `models/__init__.py`.

**Fix**: Agregar `from .guardian import Guardian` al `__init__.py`.

---

### BUG-004 — Error 405 al guardar política de seguridad

**Causa**: Solo existía `GET /security/policy`, faltaba el endpoint `PUT`.

**Fix**: Implementar `PUT /security/policy` en `policy.py`.

---

### BUG-005 — Cambios a campos JSON en SQLAlchemy no persisten

**Causa**: SQLAlchemy no rastrea mutaciones de objetos anidados en columnas `JSON`.

**Fix**: Usar `flag_modified(guardian, "config")` antes de `db.commit()`.

---

## 7. Decisiones Técnicas

### Eliminar Presidio como servicio externo
Los contenedores de Presidio consumen >4 GB de RAM. Se reemplazaron por un motor regex local en `presidio_service.py` con latencia <5ms y zero overhead.

### Seeding automático en startup
`guardian_service.py` ejecuta `seed_guardians(db)` en el evento `startup` de FastAPI. No duplica registros. Incluye auto-migración de `custom_names`.

### Puertos: host vs contenedor
Los servicios internos mantienen sus puertos nativos (Vite `5173`, Uvicorn `8000`) dentro de la red Docker. Solo los puertos expuestos al host cambian (`8080`, `8081`). Preserva la resolución interna de nombres.

### White-labeling estricto
Ninguna referencia a "LiteLLM"/"litellm" en UI, mensajes de error, headers HTTP, ni logs visibles. Los errores internos de LiteLLM son interceptados en `chat.py` y reemitidos como errores nativos limpios.

---

## 8. Estado final del sistema

| Componente | URL |
|-----------|-----|
| Frontend (UI) | http://localhost:8080 |
| Backend (API) | http://localhost:8081/api/v1 |
| Swagger Docs | http://localhost:8081/docs |
| LiteLLM (interno) | litellm:4000 |
| PostgreSQL (interno) | db:5432 |

**Demo**: usuario `admin` / contraseña `admin`

---

## 9. Próximos pasos sugeridos

- [ ] Autenticación real con JWT (reemplazar mock `admin/admin`)
- [ ] Conectar guardianes cloud a sus APIs reales (Lakera, Azure Content Safety)
- [ ] Exportación de logs a CSV/PDF
- [ ] Alertas por email al superar el 80% del presupuesto
- [ ] Integración real de Headroom para compresión de contexto
- [ ] Tests unitarios con Pytest para los servicios del backend
- [ ] CI/CD con GitHub Actions
