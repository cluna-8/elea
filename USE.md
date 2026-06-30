# Basa Secure AI Gateway — Guía de Uso

> Pasarela de IA segura y conforme con GDPR / EU AI Act para entornos sanitarios.  
> Stack: FastAPI · LiteLLM · React · PostgreSQL · Redis · Docker Compose

---

## Índice

1. [Arquitectura de módulos](#1-arquitectura-de-módulos)
2. [Módulo: Chat / Inferencia](#2-módulo-chat--inferencia)
3. [Módulo: Usuarios y Grupos](#3-módulo-usuarios-y-grupos)
4. [Módulo: Llaves Virtuales y Presupuestos](#4-módulo-llaves-virtuales-y-presupuestos)
5. [Módulo: Guardianes de Seguridad](#5-módulo-guardianes-de-seguridad)
6. [Módulo: Compliance GDPR / EU AI Act](#6-módulo-compliance-gdpr--eu-ai-act)
7. [Módulo: Consentimientos](#7-módulo-consentimientos)
8. [Módulo: Revisión Humana (Man-in-the-Loop)](#8-módulo-revisión-humana-man-in-the-loop)
9. [Módulo: Audit Log y Analytics](#9-módulo-audit-log-y-analytics)
10. [Módulo: Exportación de Documentos GDPR](#10-módulo-exportación-de-documentos-gdpr)
11. [Módulo: Rate Limiting](#11-módulo-rate-limiting)
12. [Módulo: RBAC y Sesiones](#12-módulo-rbac-y-sesiones)
13. [Casos de uso: Agentes de IA](#13-casos-de-uso-agentes-de-ia)
14. [Casos de uso: Software externo / integraciones](#14-casos-de-uso-software-externo--integraciones)
15. [Casos de uso: Administrador de TI](#15-casos-de-uso-administrador-de-ti)
16. [Casos de uso: Responsable de Compliance (DPO)](#16-casos-de-uso-responsable-de-compliance-dpo)
17. [Casos de uso: Clínico / Profesional sanitario](#17-casos-de-uso-clínico--profesional-sanitario)
18. [Casos de uso: Desarrollador / Integrador](#18-casos-de-uso-desarrollador--integrador)
19. [Referencia rápida de la API](#19-referencia-rápida-de-la-api)

---

## 1. Arquitectura de módulos

```
                        ┌─────────────────────────────────┐
  Cliente               │         Basa Gateway             │
  (app, agente,   ──→   │  POST /api/v1/chat/completions   │
   curl, HIS…)          └────────────┬────────────────────┘
                                     │
                    ┌────────────────▼────────────────────┐
                    │          Pipeline de chat             │
                    │                                       │
                    │  1. Autenticación (llave virtual)     │
                    │  2. RBAC (rol del usuario)            │
                    │  3. Rate limiting RPM/TPM (Redis)     │
                    │  4. Presupuesto (tokens / USD)        │
                    │  5. Guardianes (bloqueo por patrón)   │
                    │  6. Enmascaramiento PHI/PII           │
                    │  7. Compliance (región EU, propósito) │
                    │  8. Motor de IA (LiteLLM → modelo)    │
                    │  9. Desenmascar respuesta             │
                    │ 10. Disclosure IA (Art. 50)           │
                    │ 11. Token revisión humana (si aplica) │
                    │ 12. Audit log                         │
                    └───────────────────────────────────────┘
                                     │
                    ┌────────────────▼────────────────────┐
                    │   Motor de IA (LiteLLM proxy)        │
                    │   OpenAI · Anthropic · Azure ·       │
                    │   Bedrock · Vertex · Ollama…         │
                    └─────────────────────────────────────┘
```

Todos los módulos son **independientes y configurables**. Si Redis no está disponible el rate limiting se omite; si no hay proyecto de compliance activo, el chat funciona sin restricciones adicionales.

---

## 2. Módulo: Chat / Inferencia

**Base URL**: `POST /api/v1/chat/completions`

El corazón del sistema. Recibe un mensaje del cliente, lo procesa a través del pipeline completo y devuelve la respuesta del modelo.

### Petición mínima

```http
POST /api/v1/chat/completions
Authorization: Bearer sk-basa-xxxxxxxxxxxx
Content-Type: application/json

{
  "message": "El paciente Juan Pérez, 68 años, tiene fiebre de 39°C y disnea. ¿Protocolo inicial?",
  "model": "gpt-4o"
}
```

### Petición completa (todas las opciones)

```http
POST /api/v1/chat/completions
Authorization: Bearer sk-basa-xxxxxxxxxxxx
X-Processing-Purpose: clinical_decision
Content-Type: application/json

{
  "message": "...",
  "model": "gpt-4o",
  "override_pii_masking": false,
  "override_gdpr_mode": false,
  "override_ai_act_mode": false,
  "override_headroom_mode": false
}
```

### Cabecera `X-Processing-Purpose`
Clasifica la llamada en el audit log. Valores válidos:

| Valor | Descripción |
|-------|-------------|
| `clinical_decision` | Apoyo a decisión clínica directa |
| `administrative` | Gestión administrativa, documentación |
| `research` | Investigación, análisis de cohortes |
| `training` | Formación de profesionales |

### Lo que hace el gateway automáticamente

| Paso | Acción | Configurable |
|------|--------|-------------|
| Enmascaramiento PHI | Detecta nombres, DNI, teléfonos, diagnósticos y los reemplaza por tokens antes de enviar al modelo | Sí — por guardián |
| Desenmascar | Restaura los tokens en la respuesta | Automático |
| Compression (Headroom) | Reduce el contexto para ahorrar tokens cuando el prompt es largo | Sí — override_headroom_mode |
| Disclosure IA | Añade aviso "Esta respuesta ha sido generada por IA" una vez por sesión (EU AI Act Art. 50) | Por proyecto |
| Revisión humana | Añade ⚠️ banner y registra la respuesta para validación si el proyecto lo requiere | Por proyecto |
| Audit | Registra metadatos de la transacción (sin contenido de prompts) | Siempre |

### Respuesta

```json
{
  "response": "Se recomienda... [texto del modelo, posiblemente con ⚠️ banner si requiere revisión]",
  "model": "gpt-4o",
  "usage": {
    "prompt_tokens": 120,
    "completion_tokens": 85,
    "total_tokens": 205
  },
  "cost_usd": 0.0062,
  "pii_masked": true,
  "compliance_status": "passed",
  "guardian_events": []
}
```

### Headers de rate limiting en la respuesta

```
X-RateLimit-Remaining-Requests: 58
X-RateLimit-Remaining-Tokens: 98432
```

---

## 3. Módulo: Usuarios y Grupos

Gestiona los usuarios humanos de la plataforma y sus grupos de compliance.

### Endpoints

| Método | Ruta | Descripción | Rol mínimo |
|--------|------|-------------|-----------|
| `POST` | `/api/v1/users/login` | Login — devuelve JWT | Público |
| `POST` | `/api/v1/users` | Crear usuario | admin |
| `GET` | `/api/v1/users` | Listar usuarios | admin |
| `GET` | `/api/v1/users/{id}` | Ver usuario | admin |
| `PUT` | `/api/v1/users/{id}` | Editar usuario | admin |
| `GET` | `/api/v1/users/{id}/spend` | Gasto del usuario | admin |
| `POST` | `/api/v1/users/groups` | Crear grupo | admin |
| `GET` | `/api/v1/users/groups` | Listar grupos | admin |
| `GET` | `/api/v1/users/groups/{id}/spend` | Gasto del grupo | admin |

### Roles disponibles

| Rol | Acceso |
|-----|--------|
| `admin` | Gestión completa de la plataforma |
| `compliance_officer` | Compliance, audit, exportaciones GDPR |
| `clinician` | Chat, revisar respuestas humanas |
| `developer` | Chat, gestionar sus propias llaves |

### Grupos de compliance

Un grupo vincula a un conjunto de usuarios con una base legal GDPR y un nivel de riesgo AI Act predeterminados. El sistema aplica automáticamente las reglas del grupo en cada llamada.

```json
POST /api/v1/users/groups
{
  "name": "Médicos UCI",
  "default_legal_basis": "art_9_2_h",
  "default_risk_level": "high_risk_annex3",
  "compliance_project_id": "uuid-proyecto-clinico"
}
```

Grupos predeterminados del sistema: `Médicos`, `Enfermería`, `Administración`, `Investigación`.

---

## 4. Módulo: Llaves Virtuales y Presupuestos

Las llaves virtuales (`sk-basa-...`) son las credenciales que usan las aplicaciones para llamar al gateway. Cada llave puede tener límites de gasto, velocidad y modelos permitidos.

### Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/api/v1/keys` | Generar llave |
| `GET` | `/api/v1/keys` | Listar llaves |
| `DELETE` | `/api/v1/keys/{id}` | Revocar llave |
| `GET` | `/api/v1/keys/{id}/spend` | Consultar gasto |

### Crear una llave

```json
POST /api/v1/keys
{
  "name": "App HIS Urgencias",
  "user_id": "uuid-medico-guardia",
  "group_id": "uuid-grupo-medicos",
  "max_budget": 50.00,
  "budget_duration": "monthly",
  "models": ["gpt-4o", "claude-sonnet-4-6"],
  "expires_at": "2026-12-31T23:59:59",
  "rpm_limit": 30,
  "tpm_limit": 50000,
  "compliance_project_id": "uuid-proyecto-clinico"
}
```

La llave generada se muestra **una sola vez** en la respuesta. El sistema solo guarda su hash SHA-256.

### Respuesta de gasto

```json
GET /api/v1/keys/{id}/spend
{
  "spend_usd": 12.40,
  "max_budget": 50.00,
  "remaining": 37.60
}
```

---

## 5. Módulo: Guardianes de Seguridad

Los guardianes son filtros configurables que inspeccionan el prompt **antes** de enviarlo al modelo. Pueden bloquear la llamada o dejar pasar con registro.

### Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/v1/guardians` | Listar guardianes |
| `POST` | `/api/v1/guardians` | Crear guardián |
| `PUT` | `/api/v1/guardians/{id}` | Editar guardián |
| `DELETE` | `/api/v1/guardians/{id}` | Eliminar guardián |
| `POST` | `/api/v1/guardians/{id}/test` | Probar guardián con texto |

### Tipos de acción por entidad

| Acción | Efecto |
|--------|--------|
| `MASK` | Detecta y reemplaza por token `<TIPO>` antes de enviar al LLM; restaura en la respuesta |
| `BLOCK` | Si la entidad se detecta, la llamada es rechazada con 403 |
| `ALLOW` | Pasa sin modificación ni registro |

### Ejemplo: guardián para urgencias

```json
PUT /api/v1/guardians/{id}
{
  "name": "Guardián PHI Clínico",
  "is_active": true,
  "gdpr_mode": true,
  "ai_act_mode": true,
  "entity_configs": {
    "PERSON": "MASK",
    "PHONE_NUMBER": "MASK",
    "ID_NUMBER": "MASK",
    "MEDICAL_LICENSE": "MASK",
    "CREDIT_CARD": "BLOCK"
  }
}
```

### Probar un guardián sin enviar al modelo

```json
POST /api/v1/guardians/{id}/test
{
  "text": "El paciente Juan Pérez, DNI 12345678X, llamó al 600123456"
}

→ {
  "blocked": false,
  "reason": null,
  "masked_text": "El paciente <PERSON>, DNI <ID_NUMBER>, llamó al <PHONE_NUMBER>"
}
```

---

## 6. Módulo: Compliance GDPR / EU AI Act

Gestiona los proyectos de compliance que gobiernan cómo se procesan los datos en cada contexto clínico.

### Proyectos de Compliance

Un proyecto define las reglas aplicables a un conjunto de llamadas:

```json
POST /api/v1/compliance/projects
{
  "name": "Asistencia Clínica UCI",
  "legal_basis": "art_9_2_h",
  "data_category": "health_data",
  "ai_act_risk_level": "high_risk_annex3",
  "is_active": true,
  "eu_region_required": true,
  "human_review_required": true,
  "ai_disclosure_enabled": true,
  "ai_disclosure_message": "Esta respuesta ha sido generada por un sistema de IA. Debe ser revisada por un médico cualificado.",
  "dpia_reference": "DPIA-2026-UCI-001"
}
```

| Campo | Efecto en el pipeline |
|-------|----------------------|
| `eu_region_required: true` | Bloquea llamadas a modelos no alojados en UE (OpenAI directo, etc.) |
| `human_review_required: true` | Cada respuesta queda en cola de revisión con banner ⚠️ |
| `ai_disclosure_enabled: true` | Añade aviso IA en la primera respuesta de cada sesión |
| `ai_act_risk_level: high_risk_annex3` | Fuerza revisión humana automáticamente |

### Bases legales GDPR disponibles

| Código | Descripción |
|--------|-------------|
| `art_9_2_h` | Prestación de asistencia sanitaria (el más común) |
| `art_9_2_j` | Interés público / investigación científica |
| `art_9_2_a` | Consentimiento explícito del paciente |
| `art_6_1_c` | Cumplimiento de obligación legal |
| `art_6_1_e` | Misión de interés público |

### DPAs (Acuerdos con Encargados del Tratamiento)

Registro obligatorio de los DPAs firmados con proveedores de LLM (GDPR Art. 28):

```json
POST /api/v1/compliance/dpas
{
  "provider_name": "Azure OpenAI (Microsoft)",
  "dpa_type": "enterprise",
  "signed_date": "2026-01-15",
  "expiration_date": "2027-01-15",
  "covers_special_categories": true,
  "processing_region": "eu"
}
```

El sistema alerta automáticamente en el Panel DPO cuando un DPA está por vencer (< 30 días) o ya expiró.

### Solicitudes de Derechos del Interesado (DSR)

Registro de solicitudes GDPR Art. 15–22 con plazo de 30 días:

```json
POST /api/v1/compliance/dsr
{
  "request_type": "erasure",
  "subject_identifier": "PAC-0042",
  "date_received": "2026-06-30",
  "handled_by": "dpo@hospital.es"
}
```

Tipos: `access`, `rectification`, `erasure`, `portability`, `restriction`.

### Retención de datos

Configura cuánto tiempo se conservan los diferentes tipos de logs:

| Tipo | Mínimo | Predeterminado |
|------|--------|---------------|
| `prompt_content` | 30 días | 90 días |
| `usage_metadata` | 30 días | 365 días |
| `security_events` | 90 días | 730 días |
| `config_audit` | 365 días | 1095 días |

---

## 7. Módulo: Consentimientos

Registro inmutable de consentimientos GDPR Art. 7 y Art. 9 por usuario.

### Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/v1/compliance/consent` | Listar todos los consentimientos |
| `GET` | `/api/v1/compliance/consent/{user_id}` | Consentimientos de un usuario |
| `GET` | `/api/v1/compliance/consent/{user_id}/active` | Verificar consentimientos activos |
| `POST` | `/api/v1/compliance/consent` | Registrar consentimiento |
| `DELETE` | `/api/v1/compliance/consent/{id}` | Revocar consentimiento |

### Tipos de consentimiento

| Tipo | Uso |
|------|-----|
| `ai_use` | Uso general de sistemas de IA para este usuario |
| `data_processing` | Tratamiento de sus datos por el gateway |
| `special_category` | Tratamiento de datos de salud (Art. 9(2)(a)) |

### Verificar antes de una llamada

```http
GET /api/v1/compliance/consent/{user_id}/active

→ {
  "has_ai_use": true,
  "has_data_processing": true,
  "has_special_category": false,
  "active_consents": ["ai_use", "data_processing"]
}
```

### Comportamiento de revocación

Al revocar un consentimiento, el registro existente se cierra con `revoked_at`. **No se elimina**. La revocación es trazable y auditable.

---

## 8. Módulo: Revisión Humana (Man-in-the-Loop)

Cuando un proyecto de compliance tiene `human_review_required: true`, cada respuesta del modelo se almacena en una cola de revisión para validación clínica.

### Flujo completo

```
1. Clínico envía prompt al gateway
2. Gateway llama al modelo → obtiene respuesta
3. Almacena la respuesta en human_reviews (sin el prompt — GDPR Art. 5)
4. Devuelve la respuesta al clínico con banner ⚠️:
   "[Respuesta del modelo]
   
   ---
   ⚠️ Esta respuesta está pendiente de revisión por un profesional."
5. DPO/supervisor ve la cola de revisión en el Panel DPO
6. Aprueba o rechaza con notas
7. La revisión queda registrada en el audit log
```

### Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/v1/compliance/review/pending` | Cola de revisiones pendientes |
| `POST` | `/api/v1/compliance/review/{token}` | Aprobar o rechazar |

### Cola de revisión — payload completo

```json
GET /api/v1/compliance/review/pending

[{
  "review_token": "uuid",
  "created_at": "2026-06-30T01:15:00",
  "response_text": "[texto de la respuesta del modelo a validar]",
  "context": {
    "model": "gpt-4o",
    "processing_purpose": "clinical_decision",
    "prompt_tokens": 120,
    "completion_tokens": 85,
    "pii_detected": true,
    "masked_entities": [{"type": "PERSON", "count": 1}],
    "compliance_status": "passed",
    "guardian_events": [],
    "ai_disclosure_delivered": true
  }
}]
```

### Aprobar / rechazar

```json
POST /api/v1/compliance/review/{token}
{
  "reviewer_id": "dr.garcia@hospital.es",
  "action": "approved",
  "notes": "Protocolo correcto para el cuadro descrito."
}
```

---

## 9. Módulo: Audit Log y Analytics

Registro inmutable de todas las transacciones. **Nunca almacena el contenido de los prompts** (GDPR Art. 5 minimización).

### Campos del audit log

| Campo | Descripción |
|-------|-------------|
| `timestamp` | Fecha y hora UTC |
| `user_id` | ID del usuario que generó la llamada |
| `api_key_id` | ID de la llave virtual usada |
| `model` | Modelo de IA seleccionado |
| `prompt_tokens` | Tokens del prompt |
| `completion_tokens` | Tokens de la respuesta |
| `cost_usd` | Coste estimado en USD |
| `pii_detected` | Boolean — se detectó PHI/PII |
| `masked_entities` | Array de tipos y conteos enmascarados |
| `compliance_status` | `passed` / `blocked` / `eu_region_blocked` |
| `guardian_events` | Array de eventos de guardianes activados |
| `processing_purpose` | Propósito declarado via `X-Processing-Purpose` |
| `latency_ms` | Latencia total de la llamada |
| `ai_disclosure_delivered` | Boolean — se entregó el aviso EU AI Act |

### Analytics agregados

```http
GET /api/v1/analytics/summary?range=week

→ {
  "period": "week",
  "total_requests": 1243,
  "total_cost_usd": 89.40,
  "pii_masking_rate": 34.2,
  "top_models": [{"model": "gpt-4o", "requests": 890}],
  "guardian_activations": {"Guardián PHI Clínico": 423},
  "compliance_block_rate": 0.8
}
```

### Estado del motor de IA

```http
GET /api/v1/analytics/engine-status

→ { "status": "online", "checked_at": "2026-06-30T01:20:00" }
```

### Exportar audit logs en CSV

```http
GET /api/v1/audit-logs/export?pii_detected=true&from_date=2026-06-01&to_date=2026-06-30
```

---

## 10. Módulo: Exportación de Documentos GDPR

Genera los documentos legales requeridos por el GDPR y la EU AI Act. Solo accesible para `admin` y `compliance_officer`.

### Registro de Actividades de Tratamiento — RAT / RoPA (Art. 30)

```http
GET /api/v1/reports/rat
→ CSV con: nombre_actividad, responsable, finalidad, base_juridica,
           categoria_datos, destinatarios, región_procesamiento,
           plazo_supresion, medidas_seguridad
```

### Exportación DSAR por sujeto (Art. 15/20)

```http
GET /api/v1/reports/dsar/{subject_identifier}
→ CSV con audit logs del sujeto: timestamps, modelos, propósito,
   tokens, coste, PII detectado (sin contenido de prompts)
```

### Log de revisiones humanas

```http
GET /api/v1/reports/human-review-log
→ CSV con: token, fecha, modelo, propósito, revisor, acción, notas
```

### Resumen ejecutivo (para AESIA / auditoría)

```http
GET /api/v1/reports/executive
→ {
    "audit": {
      "total_transactions": 5832,
      "pii_masking_rate_pct": 28.4,
      "ai_disclosure_rate_pct": 91.2
    },
    "human_review": {
      "pending": 3,
      "completed": 47,
      "completion_rate_pct": 94.0
    },
    "alerts": ["2 proyectos de alto riesgo sin DPIA registrada"]
  }
```

---

## 11. Módulo: Rate Limiting

Controla la velocidad de uso por llave virtual usando Redis. Fail-open: si Redis no está disponible, el tráfico no se bloquea.

### Límites por llave

| Parámetro | Default | Descripción |
|-----------|---------|-------------|
| `rpm_limit` | 60 | Peticiones por minuto |
| `tpm_limit` | 100 000 | Tokens por minuto |

### Respuesta cuando se supera el límite

```http
HTTP 429 Too Many Requests
Retry-After: 23

{
  "detail": "Límite de solicitudes por minuto superado. Intenta de nuevo en 23 segundos."
}
```

### Headers en cada respuesta exitosa

```
X-RateLimit-Remaining-Requests: 42
X-RateLimit-Remaining-Tokens: 67430
```

---

## 12. Módulo: RBAC y Sesiones

Autenticación basada en JWT (24h TTL) con control de acceso por rol.

### Login

```json
POST /api/v1/users/login
{ "username": "admin", "password": "admin" }

→ {
    "access_token": "eyJ...",
    "token_type": "bearer",
    "user": { "id": "...", "username": "admin", "role": "admin", "email": "..." }
  }
```

### Uso del token en peticiones

```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Matriz de acceso resumida

| Endpoint | admin | compliance_officer | clinician | developer |
|----------|-------|--------------------|-----------|-----------|
| Chat / inferencia | ✓ | ✓ | ✓ | ✓ |
| Crear usuarios | ✓ | ✗ | ✗ | ✗ |
| Gestionar llaves | ✓ | ✗ | ✗ | ✓ (propias) |
| Compliance / DPA / DSR | ✓ | ✓ | ✗ | ✗ |
| Aprobar revisiones humanas | ✓ | ✓ | ✓ | ✗ |
| Exportar RAT / DSAR | ✓ | ✓ | ✗ | ✗ |
| Ver audit logs | ✓ | ✓ | ✗ | ✗ |
| Analytics | ✓ | ✓ | ✗ | ✓ |

---

## 13. Casos de uso: Agentes de IA

Los agentes autónomos (LangChain, CrewAI, AutoGen, n8n, etc.) interactúan con el gateway exactamente igual que cualquier otra aplicación — via HTTP con su llave virtual.

### Configurar un agente LangChain

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    base_url="http://basa-gateway:8081/api/v1/chat",
    api_key="sk-basa-xxxxxxxxxxxxxxxxxxxx",
    model="gpt-4o",
    default_headers={
        "X-Processing-Purpose": "research",
    }
)

response = llm.invoke("Analiza el siguiente informe de laboratorio...")
```

El gateway intercepta la llamada, enmascara PHI, verifica presupuesto, audita y devuelve la respuesta. El agente no necesita saber nada de compliance.

### Agente con límites estrictos para investigación

```json
POST /api/v1/keys
{
  "name": "Agente análisis cohortes",
  "models": ["gpt-4o-mini"],
  "max_budget": 20.00,
  "budget_duration": "monthly",
  "rpm_limit": 10,
  "tpm_limit": 20000,
  "compliance_project_id": "uuid-proyecto-investigacion"
}
```

### Verificar consentimiento antes de llamar (agente avanzado)

```python
import httpx

def check_consent_before_call(user_id: str, token: str) -> bool:
    r = httpx.get(
        f"http://basa-gateway:8081/api/v1/compliance/consent/{user_id}/active",
        headers={"Authorization": f"Bearer {token}"}
    )
    return r.json()["has_special_category"]

if check_consent_before_call(patient_id, agent_token):
    result = llm.invoke(prompt)
else:
    result = "El paciente no ha dado consentimiento para el uso de IA."
```

### n8n / Zapier / Make

Configura un nodo HTTP con:
- **URL**: `http://basa-gateway:8081/api/v1/chat/completions`
- **Method**: POST
- **Header**: `Authorization: Bearer sk-basa-xxx`
- **Body**:
```json
{
  "message": "{{ $json.text }}",
  "model": "gpt-4o",
  "X-Processing-Purpose": "administrative"
}
```

---

## 14. Casos de uso: Software externo / integraciones

### HIS / EMR (Sistema de Información Hospitalaria)

El HIS puede integrar el gateway como un microservicio de IA. Cada departamento tiene su llave con su propio presupuesto y proyecto de compliance.

```python
# Integración desde el módulo de urgencias del HIS
import requests

GATEWAY = "http://basa:8081/api/v1"
KEY = "sk-basa-urgencias-xxx"

def consultar_ia(prompt: str, paciente_id: str) -> str:
    resp = requests.post(
        f"{GATEWAY}/chat/completions",
        headers={
            "Authorization": f"Bearer {KEY}",
            "X-Processing-Purpose": "clinical_decision",
        },
        json={"message": prompt, "model": "gpt-4o"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["response"]
```

### Aplicación móvil de clínicos

```javascript
// React Native / Flutter
const response = await fetch('http://basa:8081/api/v1/chat/completions', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${virtualKey}`,
    'Content-Type': 'application/json',
    'X-Processing-Purpose': 'clinical_decision',
  },
  body: JSON.stringify({ message: userInput, model: 'gpt-4o' }),
});
```

### Integración con sistema de reportes (exportar a BI)

```bash
# Exportar audit logs de junio a Power BI / Tableau
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  "http://basa:8081/api/v1/audit-logs/export?from_date=2026-06-01&to_date=2026-06-30" \
  -o audit_junio_2026.csv
```

---

## 15. Casos de uso: Administrador de TI

### Onboarding de un nuevo departamento

```bash
# 1. Crear el grupo con su perfil de compliance
curl -X POST http://localhost:8081/api/v1/users/groups \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Oncología",
    "engine_team_id": null
  }'

# 2. Crear los usuarios del departamento
curl -X POST http://localhost:8081/api/v1/users \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "dr.martinez",
    "email": "martinez@hospital.es",
    "role": "clinician",
    "password": "ChangeMe2026!",
    "group_id": "uuid-oncologia"
  }'

# 3. Generar llave virtual para la app del departamento
curl -X POST http://localhost:8081/api/v1/keys \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "App Oncología",
    "group_id": "uuid-oncologia",
    "max_budget": 200.00,
    "budget_duration": "monthly",
    "models": ["gpt-4o", "claude-sonnet-4-6"],
    "rpm_limit": 20,
    "compliance_project_id": "uuid-proyecto-oncologia"
  }'
```

### Monitorizar el gasto en tiempo real

Desde la UI → **Usuarios y Presupuestos** → columna "Gasto actual" de cada grupo y llave. O via API:

```bash
# Gasto del grupo de oncología
curl http://localhost:8081/api/v1/users/groups/{id}/spend \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Añadir un nuevo modelo de IA

```bash
curl -X POST http://localhost:8081/api/v1/chat/models \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model_name": "llama-3-local",
    "provider": "ollama",
    "model_id": "llama3:8b",
    "api_base": "http://ollama:11434"
  }'
```

### Revocar una llave comprometida

```bash
curl -X DELETE http://localhost:8081/api/v1/keys/{key_id} \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

## 16. Casos de uso: Responsable de Compliance (DPO)

### Revisión diaria del Panel DPO

1. Navegar a **Políticas de Cumplimiento → Panel DPO**
2. Verificar las 4 métricas: proyectos activos, DPAs vigentes, DPIAs pendientes, DSRs abiertas
3. Revisar la distribución de propósitos de tratamiento (gráfico de barras)
4. Atender la cola de revisión humana si hay items pendientes

### Gestionar una solicitud DSAR (Art. 15 — Derecho de acceso)

```
1. Un paciente solicita acceso a sus datos → registrar en la tab "Derechos del Interesado"
   Tipo: access | Sujeto: PAC-0042 | Recibida: 2026-06-30 | Responsable: dpo@hospital.es

2. Buscar los datos del sujeto:
   Tab DSR → Búsqueda → introducir "PAC-0042"
   → muestra audit logs asociados (sin contenido de prompts)

3. Exportar los datos para entregárselos al paciente:
   Tab DSR → fila de la solicitud → botón "↓ Exportar"
   → descarga CSV con metadatos de transacciones (timestamps, modelos, propósito, coste)

4. Marcar la solicitud como completada antes del plazo de 30 días
```

### Renovar un DPA antes de que venza

1. **Panel DPO** → alerta "1 DPA por vencer"
2. **Tab DPAs** → editar el DPA de Azure OpenAI → actualizar `expiration_date`
3. La alerta desaparece del panel

### Exportar el RAT para la auditoría anual

```
Políticas de Cumplimiento → Panel DPO → "Exportar documentos GDPR"
→ Botón "RAT — Art. 30 GDPR (CSV)"
→ Abrir en Excel / entregar a la AESIA
```

### Aprobar una revisión humana

```
Panel DPO → Cola de Revisión Humana → seleccionar item
→ Leer la respuesta de IA a validar
→ Ver contexto: modelo, propósito, PHI detectado, estado compliance
→ Clic en "✓ Aprobar" o "✗ Rechazar" con notas clínicas
```

---

## 17. Casos de uso: Clínico / Profesional sanitario

### Uso básico desde el Playground

1. Navegar a **Playground**
2. Seleccionar modelo (ej: `gpt-4o`)
3. Introducir la llave virtual asignada por el administrador
4. Escribir el prompt: *"Paciente 68 años, fiebre 39°C y disnea. ¿Protocolo inicial?"*
5. El gateway enmascara automáticamente cualquier PHI antes de enviarlo al modelo
6. La respuesta llega con el aviso de IA y, si el proyecto lo requiere, con el banner ⚠️ de revisión pendiente

### Interpretar el banner de revisión humana

Cuando ves este aviso al final de la respuesta:

```
---
⚠️ Esta respuesta está pendiente de revisión por un profesional.
   Úsala con precaución hasta que sea validada.
```

Significa que la respuesta ha quedado registrada para que un supervisor la valide. **La respuesta ya llegó al paciente** — el banner es informativo, no bloqueante.

### Verificar si el sistema de IA está disponible

Acceder a **Dashboard** → indicador "Estado del Motor de IA". Si aparece como `offline`, el gateway funcionará con respuestas simuladas (fallback) según la configuración.

---

## 18. Casos de uso: Desarrollador / Integrador

### Probar la integración localmente

```bash
# 1. Levantar el stack completo
cd llm-router
docker compose up -d

# 2. Esperar que todo esté healthy (~30s)
docker ps

# 3. Login para obtener token de administración
curl -X POST http://localhost:8081/api/v1/users/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}'

# 4. Crear una llave de desarrollo
curl -X POST http://localhost:8081/api/v1/keys \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Dev local", "rpm_limit": 60}'

# 5. Hacer una llamada de prueba
curl -X POST http://localhost:8081/api/v1/chat/completions \
  -H "Authorization: Bearer sk-basa-dev-xxxx" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hola, ¿cómo estás?", "model": "gpt-4o"}'
```

### Probar un guardián sin afectar al sistema

```bash
# Sin enviar al modelo — solo evalúa el guardián
curl -X POST http://localhost:8081/api/v1/guardians/{id}/test \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "El paciente Juan Pérez tiene fiebre"}'
```

### Cabeceras útiles para depuración

| Cabecera en respuesta | Descripción |
|-----------------------|-------------|
| `X-RateLimit-Remaining-Requests` | Peticiones restantes en el minuto actual |
| `X-RateLimit-Remaining-Tokens` | Tokens restantes en el minuto actual |

### Integrar con OpenAI SDK (modo compatible)

El gateway es compatible con el formato de la API de OpenAI. Puedes apuntar el SDK directamente:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8081/api/v1/chat",
    api_key="sk-basa-xxxxxxxxxxxx",
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "¿Cuál es el protocolo para sepsis?"}],
    extra_headers={"X-Processing-Purpose": "clinical_decision"},
)
```

### Variables de entorno del sistema

| Variable | Descripción |
|----------|-------------|
| `DATABASE_URL` | Conexión PostgreSQL |
| `LITELLM_MASTER_KEY` | Clave maestra del motor de IA |
| `FERNET_SECRET_KEY` | Clave de cifrado de credenciales |
| `SECRET_KEY` | Clave para firma de JWT |
| `REDIS_HOST` | Host de Redis para rate limiting y caché |
| `REDIS_PORT` | Puerto de Redis (default: 6379) |

---

## 19. Referencia rápida de la API

### Base URL

```
http://<host>:8081/api/v1
```

### Autenticación

Todos los endpoints (excepto `/users/login`) requieren:

```http
Authorization: Bearer <token-o-llave-virtual>
```

- **Llave virtual** (`sk-basa-...`): para llamadas de aplicaciones y agentes
- **Token JWT**: para llamadas de la UI o integración directa de usuario

### Resumen de endpoints

```
# Auth
POST   /users/login

# Chat
POST   /chat/completions
GET    /chat/models
POST   /chat/models
DELETE /chat/models/{model_name}

# Usuarios y grupos
GET    /users
POST   /users
GET    /users/{id}
PUT    /users/{id}
GET    /users/{id}/spend
POST   /users/groups
GET    /users/groups
GET    /users/groups/{id}/spend

# Llaves virtuales
GET    /keys
POST   /keys
DELETE /keys/{id}
GET    /keys/{id}/spend

# Guardianes
GET    /guardians
POST   /guardians
PUT    /guardians/{id}
DELETE /guardians/{id}
POST   /guardians/{id}/test

# Compliance
GET/POST/PUT/DELETE  /compliance/projects
GET/POST/PUT/DELETE  /compliance/dpas
GET/POST/PUT         /compliance/dsr
GET                  /compliance/dsr/search?subject_id=
GET/PUT              /compliance/retention
GET                  /compliance/dashboard
GET                  /compliance/review/pending
POST                 /compliance/review/{token}

# Consentimientos
GET    /compliance/consent
GET    /compliance/consent/{user_id}
GET    /compliance/consent/{user_id}/active
POST   /compliance/consent
DELETE /compliance/consent/{consent_id}

# Grupos compliance
GET    /groups
GET    /groups/{id}
PUT    /groups/{id}/compliance
GET    /groups/{id}/users
PUT    /groups/users/{user_id}/group

# Audit y analytics
GET    /audit-logs
GET    /audit-logs/export
GET    /analytics/summary?range=day|week|month
GET    /analytics/engine-status

# Exportación GDPR
GET    /reports/rat
GET    /reports/dsar/{subject_identifier}
GET    /reports/human-review-log
GET    /reports/executive

# Presupuestos
GET    /budgets
POST   /budgets
```

---

*Basa Secure AI Gateway — © basa dev. Versión 1.0.0 — Rama `feature/007-rate-limiting`*
