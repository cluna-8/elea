# ADR-0003: La región de compliance por país es un campo por tenant, no un servicio Docker aparte

**Fecha:** 2026-08-11 (propuesto) · **Adoptado:** 2026-08-24 (stack 036, #137)
**Estado:** aceptado
**Decisores:** Cristian (autor) · JF (sello de canon, 12-ago y 24-ago) · adoptado por el equipo Jeff

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

## Canon sellado (JF, 12-ago — ver #137 para la discusión completa)

Dos modelos que en un primer momento parecían competir en realidad se **componen**:

- **La región vive en el TENANT.** Es el mecanismo canónico de almacenamiento — el que
  este ADR describe abajo — y se queda tal cual.
- **El wizard de instalación (issue #174, fuera de este PR) es la capa UX** que la
  escribe al tenant inicial al instalar. En el caso común —una caja = un cliente = un
  tenant— los dos modelos son lo mismo.
- La env `BASA_ENTITY_REGION` queda como **default de arranque de la instalación**,
  nunca como fuente canónica: un tenant que fija su propia región la pisa.

## Decisión

`region` se resuelve **por tenant**, con el mismo mecanismo que `nlp_fail_mode`:
clave `region` en `Guardian.config` del guardián `pii_masking`, propagada por el
`identity` que ya viaja en cada request (`internal.py` / `custom_auth.py` →
`basa_guardrail.py`). El default de instalación (`BASA_ENTITY_REGION`) se conserva
como fallback retrocompatible cuando el tenant no fija su propio valor.

No se crea ningún servicio ni contenedor nuevo.

### Los 4 planos leen la MISMA región resuelta (cerrado en la adopción, #137 PR2)

El gate adversarial del 12-ago encontró que el mecanismo de resolución sólo estaba
cableado en el plano motor (byok); los otros tres seguían en env-only o hardcodeados.
Cerrado así:

| Plano | Resuelve por tenant vía |
|---|---|
| byok (motor) | `basa_guardrail.py` → `policy.resolve_region(identity, default=env)` |
| `/gw` (passthrough) | `gateway._nlp_context` + `gateway._build_analyze` |
| navegador (`/gw/inspect`) | reusa `gateway._build_analyze` (mismo punto que `/gw`) |
| Playground | `guardian_service.process_prompt` → `presidio_service.py` |

Los caminos **degrade** (analyzer NLP real caído, se sirve con el regex de dev) de los
cuatro planos también resuelven la región del tenant, no el default de la instalación
— un degrade que pierde la región es la falla silenciosa clásica, justo cuando el
sistema ya está en problemas.

**Gap de datos conocido, fuera de alcance:** `FALLBACK_STRUCTURED_BY_REGION` (los
patrones del regex de degrade/dev) hoy sólo tiene entradas para `eu`. Con la región
correctamente threadeada, un tenant `latam_ar` en degrade recibe `region="latam_ar"`
pero el regex de dev no tiene patrones propios para esa región todavía (devuelve el
subconjunto vacío de esa clave) — es ingeniería de patrones (código, revisado por PR),
no un problema de wiring. La región LLEGA; poblar `FALLBACK_STRUCTURED_BY_REGION` con
más países es trabajo futuro cuando haya un despliegue `latam_ar` real con el detector
NLP degradado.

### Escritura por tenant no-default: parcial a propósito (H2, decisión de JF)

`region` vive en `Guardian.config`, pero hoy no existe una superficie (UI ni API) para
dar de alta guardianes en un tenant *no-default* — el alta/PUT actual siempre opera
sobre el tenant por defecto o sobre una fila ya existente. Un tenant nuevo,
multi-inquilino en la misma instalación, no tiene hoy cómo fijar su propia región sin
tocar la base a mano.

**Decisión explícita de JF (12-ago):** NO se construye ese camino en este ciclo
(`POST /guardians` con `tenant_id`, filtro en el `GET`, etc.) — se parkea como mejora
futura, a construir cuando aparezca el primer partner con clientes de más de un país en
la misma instalación. Hoy, con una instalación = un tenant, el mecanismo por-tenant y el
mecanismo por-instalación son observacionalmente el mismo, así que no bloquea nada real.

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
  que nació `nlp_fail_mode` antes de su UI en Seguridad → Enmascaramiento de datos).
- **Auditoría del cambio de región: cerrada en la adopción (#137 PR2), corrección de
  esta misma sección.** La versión original de este ADR citaba el issue #72 como el
  gap que justificaba la ausencia de fila durable — cita **incorrecta**: #72 es sobre
  el ACTOR de la fila de `nlp_fail_mode` (quién la cambió), no sobre si la fila existe;
  la fila de `nlp_fail_mode` en sí siempre existió (`_auditar_cambio_postura_tenant`,
  issue #63/#104). Lo que faltaba era la fila EQUIVALENTE para `region`, que no tenía
  ningún issue que la justificara — simplemente no se había escrito. Ya está: un cambio
  en la región EFECTIVA del tenant (`_region_efectiva_tenant`, mismo desempate
  determinista del #104/#119 que los cuatro lectores de tráfico) deja fila
  `config_change_region` con el mismo actor (FR-004/#72) que ya lleva la de
  `nlp_fail_mode` — filas separadas, no combinadas, para que cada decisión de
  compliance quede filtrable por su cuenta.

## Adopción (24-ago-2026)

Sello de JF (canal guardian-manager, `c929cbb0`): el stack 036 se adopta al equipo Jeff.
Mecánica: cherry-pick del commit original de Cristian (`44d6cb0`, autoría preservada) +
dos PRs de cierre sobre rama propia (`adopcion/137-region-por-tenant` →
`adopcion/137-region-4-planos`), gate cross-familia por PR:

- **PR 1** — el default de instalación llega a los 4 planos: `docker-compose.yml` +
  `deploy/docker/compose.prod.yml` ahora pasan `BASA_ENTITY_REGION` también al servicio
  `backend` (antes sólo lo recibía `litellm`); el seed fresco de guardianes deriva la
  región del env en vez de cablear `"eu"` literal; aviso (WARNING, no rechazo) si un
  admin escribe una región no reconocida.
- **PR 2** — los 4 planos resuelven la región POR TENANT (no sólo el default de
  instalación), incluidos los caminos degrade; fila de auditoría del cambio de región;
  esta sección corregida.
