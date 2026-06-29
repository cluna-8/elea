# Tasks: Feature 003 — Security Hardening Real Guardrails

**Branch**: `feature/003-security-hardening` | **Plan**: [plan.md](plan.md)

**Status key**: `[ ]` pendiente · `[x]` completada · `[~]` en progreso · `[!]` bloqueada

---

## Fase 0 — Alembic + Schema Foundation

> Prerequisito bloqueante. Todo lo demás depende de esta fase.

### T-001 · Alembic: instalación y configuración

- [x] **T-001-A** Agregar a `backend/requirements.txt`:
  ```
  alembic==1.13.3
  cryptography==42.0.8
  ```
- [x] **T-001-B** Desde `backend/`, ejecutar `alembic init alembic` para generar la estructura
- [x] **T-001-C** Editar `backend/alembic.ini`:
  - Cambiar `sqlalchemy.url` a `driver://user:pass@host/dbname` (placeholder — se sobreescribe en env.py con la variable de entorno `DATABASE_URL`)
- [x] **T-001-D** Editar `backend/alembic/env.py`:
  - Importar `Base` de `src.models.base`
  - Leer `DATABASE_URL` del entorno para la conexión
  - Configurar `target_metadata = Base.metadata`
  - Habilitar `compare_type=True` para detectar cambios de tipo

### T-002 · Alembic: migración baseline del schema actual

- [x] **T-002-A** Crear `backend/alembic/versions/001_initial_schema.py` como migración baseline:
  - `upgrade()`: no hace nada si la tabla ya existe (`op.execute("CREATE TABLE IF NOT EXISTS ... (skip)")`)
  - La estrategia correcta: crear todas las tablas del schema actual con `IF NOT EXISTS`
  - Tablas: `users`, `groups`, `api_keys`, `budgets`, `guardians`, `audit_logs`, `chat_messages`
- [!] **T-002-B** Verificar con `alembic history` que la revisión aparece
- [!] **T-002-C** Ejecutar `alembic upgrade head` en la DB existente y confirmar que no destruye datos

### T-003 · Guardian model: nuevos campos

- [x] **T-003-A** Editar `backend/src/models/guardian.py`, agregar columnas:
  ```python
  engine_guardrail_name = Column(String, nullable=True)   # nombre interno del motor, ej: "azure/prompt_shield"
  fail_mode = Column(String, default="log")               # "block" | "log"
  apply_on = Column(String, default="pre_call")           # "pre_call" | "post_call" | "both"
  service_api_key_encrypted = Column(Text, nullable=True) # API key del servicio encriptada con Fernet
  ```
- [x] **T-003-B** Crear `backend/alembic/versions/002_guardian_engine_fields.py`:
  ```python
  def upgrade():
      op.add_column('guardians', sa.Column('engine_guardrail_name', sa.String(), nullable=True))
      op.add_column('guardians', sa.Column('fail_mode', sa.String(), nullable=True, server_default='log'))
      op.add_column('guardians', sa.Column('apply_on', sa.String(), nullable=True, server_default='pre_call'))
      op.add_column('guardians', sa.Column('service_api_key_encrypted', sa.Text(), nullable=True))
  ```

### T-004 · AuditLog model: guardian_events

- [x] **T-004-A** Editar `backend/src/models/audit.py`, agregar:
  ```python
  guardian_events = Column(JSONB, default=list)
  ```
- [x] **T-004-B** Crear `backend/alembic/versions/003_audit_guardian_events.py`:
  ```python
  def upgrade():
      op.add_column('audit_logs', sa.Column('guardian_events', JSONB, nullable=True, server_default='[]'))
  ```

### T-005 · Dockerfile: entrypoint con alembic

- [x] **T-005-A** Editar `backend/Dockerfile`, cambiar la última línea CMD de:
  ```dockerfile
  CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
  ```
  a:
  ```dockerfile
  CMD ["sh", "-c", "alembic upgrade head && uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload"]
  ```
- [x] **T-005-B** Reconstruir imagen y verificar que el contenedor arranca correctamente (logs muestran `INFO  [alembic.runtime.migration] Running upgrade ... -> ...`)

---

## Fase 1 — Guardrails reales en backend (US1 + US2 pre_call)

### T-006 · EncryptionService: nuevo servicio

- [x] **T-006-A** Crear `backend/src/services/encryption_service.py`:
  ```python
  import os
  from cryptography.fernet import Fernet
  
  _key = os.getenv("FERNET_SECRET_KEY")
  _fernet = Fernet(_key.encode()) if _key else None
  
  def encrypt(value: str) -> str | None:
      if not _fernet or not value:
          return None
      return _fernet.encrypt(value.encode()).decode()
  
  def decrypt(value: str) -> str | None:
      if not _fernet or not value:
          return None
      return _fernet.decrypt(value.encode()).decode()
  ```
- [x] **T-006-B** Agregar `FERNET_SECRET_KEY` a `docker-compose.yml` (y `.env.example`)
  - Generar un valor con `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

### T-007 · AIEngineClient: métodos de guardrail

- [x] **T-007-A** Editar `backend/src/services/ai_engine_client.py`, agregar:
  ```python
  @staticmethod
  async def get_active_guardrail_names(db: Session) -> list[str]:
      """Retorna los engine_guardrail_name de todos los guardians activos que tienen uno."""
      guardians = db.query(Guardian).filter(
          Guardian.is_active == True,
          Guardian.engine_guardrail_name.isnot(None)
      ).all()
      return [g.engine_guardrail_name for g in guardians]
  
  @staticmethod
  async def test_guardrail(guardrail_name: str, test_text: str) -> dict:
      """Ejecuta una llamada de prueba con un único guardrail activo al motor."""
      payload = {
          "model": "gemini-2.5-flash-lite",  # modelo económico para tests
          "messages": [{"role": "user", "content": test_text}],
          "guardrails": [guardrail_name],
          "stream": False,
          "max_tokens": 10,
      }
      try:
          data = await _post("/chat/completions", payload)
          return {"blocked": False, "reason": None, "raw": data}
      except Exception as e:
          err = str(e)
          # si el motor bloqueó la petición devuelve 400 con "Violated guardrail policy"
          if "guardrail" in err.lower() or "blocked" in err.lower():
              return {"blocked": True, "reason": "Guardrail activado — petición bloqueada", "raw": err}
          raise
  ```

### T-008 · chat.py: incluir guardrails por request

- [x] **T-008-A** Editar `backend/src/api/chat.py`:
  - Importar `Guardian` model y `db` session
  - Antes de llamar al motor, obtener lista de guardrails activos:
    ```python
    active_guardrails = db.query(Guardian).filter(
        Guardian.is_active == True,
        Guardian.engine_guardrail_name.isnot(None)
    ).all()
    guardrail_names = [g.engine_guardrail_name for g in active_guardrails]
    ```
  - Agregar `"guardrails": guardrail_names` al payload JSON enviado al motor (solo si la lista no está vacía)
- [x] **T-008-B** Verificar que el campo `guardrails` NO aparece en la respuesta devuelta al cliente

### T-009 · Seed de engine_guardrail_name en guardians existentes

- [x] **T-009-A** Crear script SQL o migración de datos para setear `engine_guardrail_name` en los guardians ya creados por el seed inicial:
  ```sql
  UPDATE guardians SET engine_guardrail_name = 'litellm_content_filter',  fail_mode = 'block', apply_on = 'both'
    WHERE guardian_type = 'openai_moderation';
  UPDATE guardians SET engine_guardrail_name = 'promptguard',              fail_mode = 'block', apply_on = 'pre_call'
    WHERE guardian_type = 'lakera_prompt_injection';
  UPDATE guardians SET engine_guardrail_name = 'azure/text_moderations',   fail_mode = 'block', apply_on = 'both'
    WHERE guardian_type = 'azure_content_safety';
  UPDATE guardians SET engine_guardrail_name = 'azure/prompt_shield',      fail_mode = 'block', apply_on = 'pre_call'
    WHERE guardian_type = 'llamaguard_moderations';
  -- guardians locales (sin motor): pii_masking, secret_detection, sensitive_routing → engine_guardrail_name NULL
  ```
  Nota: `pii_masking`, `secret_detection`, `sensitive_routing` permanecen con `engine_guardrail_name = NULL`.

### T-010 · guardian_service.py: reemplazar simulaciones por motor

- [x] **T-010-A** Editar `backend/src/services/guardian_service.py`:
  - Los métodos que llaman servicios externos simulados (Lakera, Azure Content Safety, OpenAI Moderation, LlamaGuard) ya NO ejecutan la lógica keyword-based en backend
  - Reemplazar por un método genérico `check_engine_guardian(guardian, text, db)` que devuelve el resultado del motor (ya se aplica en `chat.py` via el campo `guardrails`, así que aquí solo retornar `pass` o un no-op)
  - Mantener: `check_pii_masking`, `check_secret_detection`, `check_sensitive_routing` — estos siguen siendo locales
- [x] **T-010-B** Actualizar `evaluate_guardrails(prompt, db)` para que:
  1. Ejecute guardrails locales (secret_detection, pii_masking) y retorne `GuardianResult` con placeholders
  2. No duplique la lógica de los guardrails del motor (esos ya los aplica `chat.py` al llamar al motor)

---

## Fase 2 — Respuesta del motor: guardrail events y post_call

### T-011 · chat.py: procesar guardrail events de la respuesta

- [x] **T-011-A** Editar `backend/src/api/chat.py`:
  - Al recibir la respuesta del motor, verificar si existe `response.get("guardrail_info")` o similar en la estructura JSON
  - Si el motor devuelve un error 400 con mensaje de guardrail bloqueado: capturar y retornar al cliente:
    ```json
    {"error": "La petición fue bloqueada por las políticas de seguridad configuradas."}
    ```
    (sin mencionar el nombre del guardrail proveedor)
  - Extraer `guardian_events` de la respuesta para el audit log
- [x] **T-011-B** Pasar `guardian_events` al `audit_service.create_audit_log()`

### T-012 · audit_service.py: guardar guardian_events

- [x] **T-012-A** Editar `backend/src/services/audit_service.py`, actualizar la creación del registro de auditoría:
  - Agregar parámetro `guardian_events: list = None`
  - Setear `audit_log.guardian_events = guardian_events or []`

---

## Fase 3 — SecurityPage UI real (US3)

### T-013 · SecurityPage: reemplazar badges y descripciones hardcodeadas

- [x] **T-013-A** Editar `frontend/src/pages/SecurityPage.tsx`:
  - Eliminar el badge `"Nube / Simulación"` de los guardrails externos
  - Reemplazar con badge dinámico basado en estado del guardian:
    - `is_active=True` + `engine_guardrail_name != null` + `service_api_key_encrypted != null` → badge verde "Activo (con key)"
    - `is_active=True` + `engine_guardrail_name != null` → badge verde "Activo"
    - `is_active=False` + `engine_guardrail_name != null` → badge gris "Inactivo"
    - `engine_guardrail_name = null` → badge azul "Local" (para pii_masking, secret_detection, etc.)
  - Eliminar descripciones hardcodeadas que mencionan "Lakera AI", "Azure" como proveedor
  - Descripción genérica: usar `guardian.config.description` si existe, sino descripción blanca del tipo

### T-014 · SecurityPage: agregar campos fail_mode y apply_on al modal de edición

- [x] **T-014-A** En el modal/formulario de edición de guardian:
  - Agregar selector `fail_mode`: opciones "Bloquear petición" (`block`) / "Solo registrar" (`log`)
  - Agregar selector `apply_on`: opciones "Antes del LLM" (`pre_call`) / "Después del LLM" (`post_call`) / "Ambos" (`both`)
  - Solo mostrar estos campos si el guardian tiene capacidad de motor (`engine_guardrail_name != null`)
- [x] **T-014-B** Actualizar el payload del PUT en `frontend/src/services/api.ts` para incluir `fail_mode` y `apply_on`
- [x] **T-014-C** Actualizar el endpoint `PUT /api/v1/guardians/{id}` en `backend/src/api/guardians.py` para aceptar y persistir estos campos

### T-015 · SecurityPage: panel de prueba de guardian

- [x] **T-015-A** Agregar a `frontend/src/pages/SecurityPage.tsx` un panel de prueba (collapsable o modal):
  - Textarea: "Texto de prueba"
  - Botón: "Ejecutar test de seguridad"
  - Resultado: muestra "Bloqueado" (rojo) o "Permitido" (verde) + razón genérica
  - Solo disponible para guardians con `engine_guardrail_name != null`
- [x] **T-015-B** Agregar endpoint en `backend/src/api/guardians.py`:
  ```
  POST /api/v1/guardians/{id}/test
  Body: { "text": "..." }
  Response: { "blocked": bool, "reason": str | null }
  ```
  Llama a `AIEngineClient.test_guardrail(guardian.engine_guardrail_name, text)`
- [x] **T-015-C** Agregar método `api.testGuardian(id, text)` en `frontend/src/services/api.ts`

---

## Fase 4 — PII NLP real (US4 — P2, opcional)

> Esta fase es independiente. Implementar solo si la mejora de detección es prioridad.

### T-016 · Presidio real

- [ ] **T-016-A** Agregar a `backend/requirements.txt`:
  ```
  presidio-analyzer==2.2.356
  presidio-anonymizer==2.2.356
  spacy==3.7.6
  ```
- [ ] **T-016-B** Editar `backend/Dockerfile`, agregar después de `pip install`:
  ```dockerfile
  RUN python -m spacy download es_core_news_md
  ```
- [ ] **T-016-C** Editar `backend/src/services/presidio_service.py`:
  - Intentar importar `presidio_analyzer` al arranque
  - Si disponible: usar `AnalyzerEngine` con idioma `es` y modelo spaCy
  - Si no disponible: fallback al sistema regex actual con log de advertencia
  - Mapear entidades detectadas a los mismos placeholders que usa el código actual: `[EMAIL]`, `[PHONE]`, `[DNI]`, `[CUIL]`, `[NAME]`

---

## Fase 5 — Polish y entrega

### T-017 · White-label audit

- [x] **T-017-A** Ejecutar grep en el proyecto por nombres prohibidos:
  ```bash
  grep -r -i "litellm\|lakera\|promptguard\|llamaguard\|presidio" \
    frontend/src/ backend/src/api/ backend/src/services/ \
    --include="*.py" --include="*.ts" --include="*.tsx" \
    -l
  ```
  Revisar cada match: si está en un mensaje visible al cliente, error log visible, o respuesta de API → corregir
- [x] **T-017-B** Verificar mensajes de error en `chat.py` cuando el motor bloquea — no deben mencionar el proveedor
- [x] **T-017-C** Verificar que el campo `engine_guardrail_name` no aparece en ninguna respuesta de la API pública (`GET /api/v1/guardians`, `GET /api/v1/guardians/{id}`, `POST /api/v1/guardians/{id}/test`)

### T-018 · Tests manuales de integración

- [ ] **T-018-A** Test US1: con el guardian `litellm_content_filter` activo, enviar desde Playground un mensaje con contenido inapropiado → debe devolver mensaje de bloqueo genérico
- [ ] **T-018-B** Test US1: desactivar el guardian desde SecurityPage → el mismo mensaje debe pasar
- [ ] **T-018-C** Test US2: activar `azure/prompt_shield`, enviar prompt de jailbreak ("Ignore all previous instructions and...") → debe ser bloqueado
- [ ] **T-018-D** Test US3: panel de prueba en SecurityPage → ejecutar texto de test en un guardian inactivo → resultado "Bloqueado"
- [ ] **T-018-E** Test Alembic: destruir y recrear la DB con `docker compose down -v && docker compose up` → la migración debe recrear todas las tablas

### T-019 · Changelog y commit

- [x] **T-019-A** Crear `specs/003-security-hardening-real-guardrails/changelog.md` documentando todos los cambios de esta feature
- [x] **T-019-B** Commit `feat(003): real guardrails via AI engine, Alembic migrations`
- [x] **T-019-C** Evaluar si hacer merge a main o mantener en feature branch hasta PR review

---

## Orden de implementación recomendado

```
T-001 → T-002 → T-003 → T-004 → T-005   (Fase 0, en orden, bloqueante)
     ↓
T-006 → T-007                             (Servicios base, paralelo)
T-009                                     (Seed de datos)
     ↓
T-008 → T-010 → T-011 → T-012            (Backend guardrails + audit)
     ↓
T-013 → T-014 → T-015                    (Frontend SecurityPage)
     ↓
T-016                                     (Fase 4, opcional)
     ↓
T-017 → T-018 → T-019                    (Polish + entrega)
```

## Dependencias de tarea críticas

| Tarea | Depende de |
|-------|-----------|
| T-002 | T-001 (alembic configurado) |
| T-003-B | T-003-A (modelo actualizado) |
| T-004-B | T-004-A (modelo actualizado) |
| T-005 | T-001, T-002, T-003, T-004 |
| T-008 | T-007, T-009 |
| T-010 | T-008 |
| T-011 | T-008 |
| T-012 | T-004, T-011 |
| T-015-B | T-007 |
| T-015-C | T-015-B |
| T-017 | T-008, T-013, T-014, T-015 |
| T-018 | todas las fases 0-3 completas |
