# ADR-0003: La región de compliance por país es un campo por tenant, no un servicio Docker aparte

**Fecha:** 2026-08-11 · **Estado:** propuesto
**Decisores:** Cristian · pendiente review de JF (toca su código de spec 016, CODEOWNERS)

## Contexto

Con Argentina/España/Colombia entrando como perfiles de configuración reales (ADR-0001),
surgió la pregunta de dónde vive la política de compliance/entidades PII por país
(`STRUCTURED_ID_PATTERNS_BY_REGION`), y si conviene un servicio Docker aparte para que
empresas y países se puedan actualizar sin tocar el resto del stack.

Hasta este ADR, `region` se leía SOLO de `BASA_ENTITY_REGION`, una env var fija por
contenedor (`litellm/extensions/basa_guardrail.py`), con un comentario del propio JF
marcándola como YAGNI deliberado "mientras solo exista Europa" — condición ya vencida.

En paralelo, el equipo cerró la constitución D10 (`nlp_fail_mode`, issue #63/#104):
un ajuste gobernable por tenant, resuelto desde `Guardian.config` vía el mismo canal
`identity` que ya carga `entity_configs`/`custom_names`/`custom_entities`, sin
contenedor nuevo. Es el mismo tipo de decisión que `region`, resuelta días antes.

## Decisión

`region` se resuelve **por tenant**, con el mismo mecanismo que `nlp_fail_mode`:
clave `region` en `Guardian.config` del guardián `pii_masking`, propagada por el
`identity` que ya viaja en cada request (`internal.py` / `custom_auth.py` →
`basa_guardrail.py`). El default de instalación (`BASA_ENTITY_REGION`) se conserva
como fallback retrocompatible cuando el tenant no fija su propio valor.

No se crea ningún servicio ni contenedor nuevo.

## Alternativas consideradas

- **Servicio Docker aparte (`policy-service`)**: descartada por ahora — paga el costo
  documentado de "alta de imagen nueva en 5 ubicaciones" (hoy manual, sin CI/CD de
  imágenes según `ROADMAP-factory.md`) sin resolver nada que el patrón per-tenant no
  resuelva ya; el precedente `presidio-analyzer` muestra que "ser servicio aparte" no
  garantiza hot-reload por sí solo.
- **Dejarlo en `BASA_ENTITY_REGION` (env var por instalación)**: descartada — asume un
  país por instalación/VM; un partner con clientes de más de un país en la misma
  instancia no puede expresarlo.
- **Policy pack como archivo versionado en git, sincronizado a DB**: no descartada,
  queda como extensión futura si se necesita trazabilidad tipo PR por cambio de
  política; no es necesaria para este alcance (un campo, dos valores válidos hoy).

## Consecuencias

- Agregar un país nuevo a `STRUCTURED_ID_PATTERNS_BY_REGION` sigue siendo código
  (ingeniería de patrones, revisado por PR); asignar ESE país a un tenant ya es
  config, sin restart ni redeploy — mismo patrón que `nlp_fail_mode`.
- `internal.py` (`_IDENTITY_SQL`) y `custom_auth.py` (`_IDENTITY_SQL`) quedan
  espejados también en esta columna: cambian juntos, como ya exige el comentario
  ⚠️ ESPEJO existente para `nlp_fail_mode`.
- Instalaciones existentes no cambian de comportamiento: sin `region` en ningún
  tenant, siguen resolviendo `BASA_ENTITY_REGION`/`DEFAULT_REGION` igual que antes.
- Pendiente, fuera de este alcance: UI de Admin para editar `region` por tenant (hoy
  solo editable vía `PUT /guardians/{id}`, sin pantalla dedicada — mismo estado en
  que nació `nlp_fail_mode` antes de su UI en Seguridad → Enmascaramiento de datos) y
  auditoría del cambio de postura efectiva (issue #72, gap ya conocido y documentado
  para `nlp_fail_mode`).
