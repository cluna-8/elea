# Contratos internos — 018

## Contrato 1 · Clasificador de clases de retención (FR-002/FR-003)

**Módulo**: `backend/src/services/retention/classifier.py` — LA única definición de «qué fila pertenece a qué clase».

```
clases() -> list[str]                       # las 4 clases seed, orden estable
predicado(clase: str) -> ColumnElement      # predicado SQLAlchemy sobre AuditLog
clase_de(fila: AuditLog) -> str | None      # clasificación de una fila (para tests de partición)
```

Reglas del contrato:
1. **Partición total de lo purgable**: toda fila de `audit_logs` matchea exactamente una clase o la exclusión `license`. Test de partición obligatorio sobre dataset sembrado que cubra todos los emisores actuales (blocked%, rejected%, config_change_*, license, tráfico normal).
2. **`model='license'` es exclusión estructural**: `predicado()` de ninguna clase puede devolverla; no existe parámetro para incluirla.
3. **Consumidores obligatorios**: purgador y vitrina (`api/audit.py` — sus constantes locales BLOQUEADO_LIKE/MODELO_LICENCIA/rechazados se reemplazan por llamadas al clasificador). Criterio: paridad exacta de resultados de la vitrina pre/post refactor.
4. Los literales del mapeo son los del seed 004 y los emisores vigentes; agregar un emisor nuevo con literal no clasificado debe romper el test de partición (eso es una feature, no un bug).

## Contrato 2 · Identidad batch bajo RLS (FR-006 — costura 017)

Todo job batch que toque tablas bajo RLS declara identidad con el mecanismo existente:

```python
with tenant_context(bypass=True):   # database.py:64-76; precedente: gateway.py:901
    ...  # trabajo del job
```

Reglas:
1. **Prohibido** `SessionLocal()` pelado en jobs (el emisor de la cadena, `audit_events.py:213-218`, se corrige a este contrato en esta spec).
2. El bypass es **explícito y localizado** — nunca un default de sesión.
3. **Criterio verificable (SC-004)**: fixture de harness que (a) dropea `tenant_isolation_bootstrap` y (b) conecta con un rol NOSUPERUSER; la suite de purga + el emisor de la cadena pasan bajo esa fixture. Ese es el mundo que la 017 activa después — acá se prueba antes.

## Contrato 3 · Capa de tier sobre el registry 027 (FR-008)

- Clave: `enforcement_tier_estricto` — alta en el registry puro compartido (`basa_governance.py`), decision `on`/`off`.
- Semántica: `on` = `estricto`, `off`/ausente = `estándar`. La capa de piso `ai_act_evaluation` se evalúa SIEMPRE, cualquiera sea el tier (invariante 027).
- Consumidores backend:
  1. **Pisos/topes de retención** en `PUT /compliance/retention` (tabla research.md D7) — violación → error de validación (SC-005).
  2. **Postura de auditoría**: tier `estricto` exige `BASA_AUDIT_FAIL=closed`; incoherencia → health degradado + evento auditado. **No** se reescribe el env ni se toca el espejo triple del motor.
  3. Consecuencias de capas con grado (bloquear vs registrar) según resolución 027 vigente.
- Cambio de tier: auditado con valor anterior y nuevo (SC-006). El plano motor no consume esta capa en v1 (decisión de diseño — evita rebundle).
- **Costura 037/perfil**: el bloque `compliance_tier` reservado en el schema del perfil (sellado con Cristian/Falime 13-ago) escribe esta capa al instalar; la licencia autoriza los juguetes, el perfil solo configura.
