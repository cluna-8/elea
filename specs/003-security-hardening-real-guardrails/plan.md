# Implementation Plan: Security Hardening — Real Guardrails via AI Engine

**Branch**: `feature/003-security-hardening` | **Date**: 2026-06-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/003-security-hardening-real-guardrails/spec.md`

## Summary

Reemplazar las simulaciones de seguridad (keyword lists, regex) por guardrails reales usando el sistema de guardrails nativo del motor de IA interno. El motor tiene 46 integraciones disponibles; con las credenciales actuales funcionan sin configuración adicional: `litellm_content_filter` y `promptguard` (sin key externa), y `azure/prompt_shield` + `azure/text_moderations` (con las keys Azure ya configuradas).

La arquitectura preserva PII masking en nuestro backend (necesitamos el `placeholder_map` para el unmask de la respuesta). Los guardrails del motor se aplican sobre el texto ya enmascarado. También se añade Alembic para migrations versionadas.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript/React 18 (frontend)

**Primary Dependencies nuevas**:
- `alembic==1.13.x` — migrations versionadas
- `cryptography==42.x` — encriptación AES-256 para API keys de servicios
- Presidio real: `presidio-analyzer`, `presidio-anonymizer`, `spacy`, modelo `es_core_news_md` (P2, opcional)

**Storage**: PostgreSQL (nuestra DB). El motor de IA gestiona sus propias tablas.

**Testing**: Manual via Playground + curl. Los guardrails del motor se verifican activándolos desde SecurityPage y probando prompts conocidos.

**Target Platform**: Docker Compose (desarrollo local) → contenedores en producción

**Performance Goals**: Overhead del guardrail < 300ms por petición (el motor lo ejecuta en paralelo con la llamada al LLM en modo `pre_call`)

**Constraints**: White-label estricto — ningún nombre de proveedor de guardrails en API pública, mensajes de error ni UI.

## Constitution Check

| Principio | Estado | Notas |
|-----------|--------|-------|
| I. Privacy & PHI/PII Masking-First | ✅ **Mejora** | El PII masking se aplica ANTES de que el motor vea el texto. El motor opera siempre sobre texto con placeholders. |
| II. Strict Compliance (GDPR & AI Act) | ✅ | Guardrails reales refuerzan compliance. Alembic no afecta compliance. |
| III. Budget & Resource Enforcement | ✅ | Sin cambios en enforcement de presupuesto. |
| IV. Containerized & White-Label | ✅ **Refuerza** | Nuevos campos internos: `engine_guardrail_name`. Nombres de proveedores nunca en API ni UI. |
| V. Explanatory Playground | ✅ | El panel de prueba de guardrails extiende la funcionalidad de Playground sin romperlo. |

## Arquitectura: Guardian como proxy de guardrail del motor

```
Request del cliente
  │
  ▼
basa-backend
  ├── 1. Auth & budget check (nuestro)
  ├── 2. Secret detection (nuestro, regex — rápido, sin dependencias)
  ├── 3. PII masking (nuestro, regex → Presidio NLP en P2)
  │         guarda placeholder_map en memoria de la request
  │
  ▼
  4. Llama al motor con:
       - prompt ya enmascarado
       - metadata: { guardrails: ["filtro-contenido", "anti-jailbreak"] }
         (nuestros nombres white-label, mapeados a engine_guardrail_name internamente)
  │
  ▼
Motor de IA interno
  ├── pre_call guardrails (anti-jailbreak, filtro de contenido en prompt)
  ├── Llamada al LLM
  └── post_call guardrails (moderación de la respuesta)
  │
  ▼
basa-backend
  ├── 5. Recibe respuesta + guardrail events del motor
  ├── 6. PII unmask (aplica placeholder_map sobre la respuesta)
  └── 7. Audit log con guardian_events (sin texto original)
  │
  ▼
Cliente
```

## Arquitectura: Sincronización de config guardian → motor

```
Admin en SecurityPage
  └── PUT /api/v1/guardians/{id}
        │
        ▼
        basa-backend
          ├── 1. Persiste guardian en nuestra DB
          ├── 2. Si guardian tiene engine_guardrail_name:
          │       llama a AIEngineClient.sync_guardrail_config(guardian)
          │       → POST /config/update al motor (hot reload)
          └── 3. Retorna guardian actualizado
```

Si el motor no soporta hot reload del guardrail, fallback: el config se guarda en DB y se aplica en la próxima petición (nuestro backend pasa los guardrails activos por request, no es configuración estática del motor).

## Decisión: cómo se pasan los guardrails por request al motor

LiteLLM proxy acepta el campo `guardrails: [...]` en el body de la request de completions. Nuestro backend construye esta lista dinámicamente consultando la DB: todos los guardrails con `is_active=True` y `engine_guardrail_name != null`.

```python
# En chat.py, al preparar el request al motor:
active_guardrails = db.query(Guardian).filter(
    Guardian.is_active == True,
    Guardian.engine_guardrail_name != None
).all()
guardrail_names = [g.engine_guardrail_name for g in active_guardrails]
# guardrail_names = ["litellm_content_filter", "azure/prompt_shield", ...]
# Se pasan en el body al motor, nunca se exponen al cliente
```

Los guardrails `pii_masking`, `secret_detection` y `sensitive_routing` tienen `engine_guardrail_name = None` porque los ejecutamos nosotros, no el motor.

## Decisión: encriptación de service_api_key

Usamos `cryptography.fernet` (AES-128-CBC con HMAC). La clave de encriptación se genera desde `FERNET_SECRET_KEY` en `.env`. Si no está configurada, el campo `service_api_key_encrypted` permanece null y el guardrail usa las credenciales del `.env` del sistema.

## Decisión: Alembic + Docker

El entrypoint del contenedor backend cambia de:
```
CMD ["uvicorn", ...]
```
a:
```
CMD ["sh", "-c", "alembic upgrade head && uvicorn ..."]
```

La migración inicial (`001_initial_schema.py`) usa `IF NOT EXISTS` implícito via Alembic's `include_schemas` + `compare_type`. En una DB existente, Alembic detecta que ya existe y no hace nada. En DB nueva, crea todo.

## Project Structure

### Documentation (this feature)

```text
specs/003-security-hardening-real-guardrails/
├── spec.md              ✅ creado
├── plan.md              ✅ este archivo
├── tasks.md             (pendiente)
└── changelog.md         (se crea al final de cada sesión)
```

### Source Code (cambios en el repositorio)

```text
backend/
├── alembic/                             ← NUEVO: directorio de migrations
│   ├── env.py                           ← configuración de Alembic
│   ├── script.py.mako                   ← template de migrations
│   └── versions/
│       └── 001_initial_schema.py        ← migración baseline del schema actual
├── alembic.ini                          ← NUEVO: configuración de Alembic
├── requirements.txt                     ← agregar alembic, cryptography
├── Dockerfile                           ← entrypoint: alembic upgrade head + uvicorn
├── src/
│   ├── models/
│   │   └── guardian.py                  ← agregar: engine_guardrail_name, fail_mode, apply_on, service_api_key_encrypted
│   ├── services/
│   │   ├── ai_engine_client.py          ← agregar: sync_guardrail_config(), get_guardrail_test()
│   │   ├── guardian_service.py          ← reemplazar simulaciones por llamadas al motor
│   │   ├── presidio_service.py          ← (P2) upgrade a Presidio NLP real
│   │   └── encryption_service.py        ← NUEVO: encriptación de API keys
│   └── api/
│       ├── guardians.py                 ← agregar: POST /{id}/test, sync al motor en PUT
│       └── chat.py                      ← agregar guardrails dinámicos al request del motor

frontend/src/
└── pages/
    └── SecurityPage.tsx                 ← reemplazar badges "Simulación" por estado real,
                                            agregar panel de prueba, fail_mode, apply_on
```

## Fases de implementación

### Fase 0 — Alembic + schema (Foundational, bloqueante)
Instalar Alembic, crear migración baseline, actualizar Dockerfile. Modificar modelo Guardian con nuevos campos. Todas las fases dependen de esta.

### Fase 1 — Guardrails reales en backend (US1 + US2)
Agregar `engine_guardrail_name` a los guardians existentes en la DB. Actualizar `AIEngineClient` para sincronizar guardrail configs y pasar guardrails por request. Actualizar `chat.py` para incluir los guardrails activos en cada llamada al motor.

### Fase 2 — Engine guardian para moderación de respuestas (US2 post-call)
Actualizar `chat.py` para recibir y procesar los guardrail events que devuelve el motor en la respuesta. Si hay un evento de bloqueo post-call, retornar error genérico al cliente. Registrar guardian_events en el audit log.

### Fase 3 — SecurityPage UI real (US3)
Reemplazar badges "Simulación" por indicador real (activo con key / activo sin key / sin configurar). Agregar campos fail_mode y apply_on. Agregar panel de prueba (textarea + botón "Ejecutar test"). Remover descripciones hardcodeadas que revelan proveedores.

### Fase 4 — PII NLP real (US4, P2)
Actualizar `presidio_service.py` con el analyzer real de Presidio. Agregar fallback automático al regex si Presidio no carga. Agregar modelo spaCy español en el Dockerfile build.

### Fase 5 — Polish
White-label audit completo (grep de nombres de proveedores). Actualizar audit log con guardian_events. Changelog. Commit y tag.
