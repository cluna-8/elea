# Research — 018 Retención con dientes

Fuente: mapa as-is verificado en fuente (workflow de 6 agentes, 13-ago-2026, ~876k tokens; todo `path:line` leído en main @ 81ea8ce, no de memoria). Este documento consolida las decisiones que el plan asume; cero NEEDS CLARIFICATION pendientes.

## D1 — Clasificación de filas: clasificador compartido, sin columna nueva

- **Decision**: la pertenencia de una fila de `audit_logs` a una clase de retención se resuelve con un clasificador único en código (`services/retention/classifier.py`), consumido por purgador y vitrina. El esquema no se toca.
- **Rationale**: `audit_logs` no tiene columna `log_type`; las 4 políticas seed (004:100-109) mapean a clases distinguibles solo por literales (`model='license'`, `compliance_status LIKE 'blocked%'/'rejected%'`, `config_change_*`) y la vitrina ya duplica esa lógica en constantes locales (audit.py:36-64). Además el rabbit-hole de la Parte 4 del BRIEF de Cristian sella «no tocar el esquema de audit_logs» — una columna nueva exigiría renegociar.
- **Alternatives considered**: columna `log_type` + backfill (más limpio, pero migración sobre la tabla más caliente + renegociación con Cristian); vistas SQL por clase (duplica la verdad en otro plano).

## D2 — Exclusión de la hash-chain: por diseño, no por configuración

- **Decision**: el clasificador excluye `model='license'` de forma **estructural** (no existe camino de configuración que las purgue).
- **Rationale**: `verify_chain` relee toda la cadena y acusa «evento anterior editado/borrado» ante cualquier hueco (audit_events.py:82-116); el true-up exige historial completo. Purgar un eslabón = incidente de confianza del modelo comercial 021.
- **Alternatives considered**: re-anclaje de cadena con checkpoint firmado (permitiría purgar eslabones viejos; mucho más caro, sin necesidad hoy — las filas license son pocas).

## D3 — El texto real muere: response_text bajo prompt_content

- **Decision**: al vencer `prompt_content` (90 d default), `human_reviews.response_text` se pone a NULL; la revisión persiste como metadata. `audit_log_id` sin FK queda como huérfano lógico documentado.
- **Rationale**: es el ÚNICO contenido real durable del sistema (models/compliance.py:84) y no tiene retención; sin esto la promesa «purga al día 91» no borra el único texto que existe. El BRIEF de Cristian ya lo fichaba como fuga.
- **Alternatives considered**: borrar la fila entera de review (pierde evidencia de que la revisión ocurrió — peor para el DPO); FK con ON DELETE (migración vetada por D1).

## D4 — Mecánica del purgador: scheduler existente + DELETE por lotes con ventana

- **Decision**: thread daemon con intervalo por env (patrón `licensing/reconcile.py:240-281`, único scheduler del proceso), DELETE por lotes (`BASA_PURGE_BATCH_SIZE=5000`, pausa 200 ms) solo dentro de ventana horaria (`02:00-05:00` local), edad contra el reloj de la DB, idempotente por diseño (el predicado es «vencida al momento de la corrida» — retomar tras interrupción no duplica ni salta).
- **Rationale**: la tabla no tiene particiones (DELETE puro), tiene 4 índices y lectores SQL calientes (costs/analytics/vitrina/export); C2 es el ciclo del gate 250 — un purgador glotón reprueba el examen (SC-003). Reusar el scheduler evita dependencia nueva en un producto air-gap.
- **Alternatives considered**: pg_cron (dependencia de extensión en instalaciones que no controlamos); particionado por rango + DROP PARTITION (la solución definitiva a escala, diferida a spec de infraestructura propia — Out of scope).

## D5 — Rastro de la purga: purge_log + fila resumen de auditoría

- **Decision**: cada corrida escribe (a) su entrada en el `purge_log` JSONB que la 004 dejó preparado (retención de las últimas 50 corridas por clase, capado para no crecer sin límite) y (b) una fila resumen en `audit_logs` clase `config_audit` (metadata: clase, filas, rango, duración, resultado).
- **Rationale**: SC-002 exige que un auditor reconstruya qué se borró solo con el registro; la fila de auditoría integra la purga al mismo canal de evidencia que todo lo demás (y muere a los 730 d como cualquier config_audit — sin filas inmortales nuevas).
- **Alternatives considered**: tabla purge_runs nueva (migración vetada por D1); solo purge_log JSONB (fuera del canal de auditoría estándar del DPO).

## D6 — Identidad batch: tenant_context con bypass explícito, verificado post-017

- **Decision**: purgador y emisor de la cadena de licencias (hoy `SessionLocal` pelado, audit_events.py:213-218) usan `tenant_context(bypass=True)` (mecanismo database.py:64-76, precedente gateway.py:901). Criterio verificable: la suite corre con `tenant_isolation_bootstrap` dropeada y rol NOSUPERUSER, y pasa.
- **Rationale**: RLS FORCE + el mandato escrito de la 017 de eliminar la policy bootstrap → un job sin contexto pasaría de funcionar a NO VER FILAS: retención que aparenta enforced sin serlo, el peor modo de falla. Sellarlo ahora cuesta un párrafo; en el merge costaría días.
- **Alternatives considered**: iterar por tenant con GUC por tenant (más «puro» multi-tenant; innecesario en single-tenant y más lento — se reevalúa cuando FR-010 despierte).

## D7 — Tier de enforcement: capa booleana sobre el registry 027

- **Decision**: `enforcement_tier_estricto` como capa booleana del registry 027 (on = estricto; off/ausente = estándar). Alta de la clave en el registry puro compartido (`basa_governance.py`) — cambio solo-código; el resolutor del motor ignora claves que no consume. Consumidores (backend): pisos de retención en FR-007, aserción de postura `BASA_AUDIT_FAIL` (incoherencia → health degradado + evento auditado, SIN reescribir el env ni tocar el espejo triple), consecuencias de capas con grado. La capa de piso AI-Act se evalúa SIEMPRE (invariante 027, basa_governance.py:272-283).
- **Rationale**: `governance_profiles.decision` tiene CHECK `on/off` y `layer_key` va sin FK/CHECK a propósito — capa nueva sin migración (≈1 semana menos que migrar el CHECK a vocabulario no binario y renegociar el contrato serializado entre planos). Es la opción sellada por JF (13-ago).
- **Alternatives considered**: migrar el CHECK a vocabulario de tiers (caro, toca librería compartida entre planos); tabla/dominio propio (más aún); env var (no auditable ni gobernable por UI).

### Pisos/topes por tier (defaults del plan, ajustables en tasks)

| Clase | `estándar` (mínimo) | `estricto` (mínimo) | Tope prompt_content |
|---|---|---|---|
| `config_audit` | 365 d (piso legal vigente) | 730 d | — |
| `security_events` | 30 d | 365 d | — |
| `usage_metadata` | 30 d | 365 d | — |
| `prompt_content` | 1 d | 1 d | estándar: 365 d · estricto: **90 d** (privacidad: el contenido no puede retenerse MÁS, no menos) |

## D8 — Dos-fases (#182, Cristian): la muerte queda definida, la clase no se crea

- **Decision**: si la apuesta dos-fases entra, las filas de intención heredan edad desde el timestamp de intención. Esta spec no crea la clase ni escribe su rastro.
- **Rationale**: deslinde limpio — #182 es la escritura del rastro; la 018 solo su muerte programada. Evita que dos papeles compitan por el mismo terreno en el betting.

## D9 — Fronteras confirmadas

- **036 (Cristian)**: la 018 = ENFORCEMENT; la 036 = futura FUENTE de configuración (retention_days en PolicyBundle, su FR-003). Esta spec consume la fuente vigente (`retention_policies`) y define el contrato de lectura.
- **DSAR**: fuera — dueño Guardian, spec propia C3 (decisión JF 13-ago, registrada en spec.md); fix del 500 (#193) = tarea suelta del encargo.
- **017 (paralela)**: FR-006 (identidad batch) y FR-009 (escritura de retención = tenant_admin) sellados en ambas specs; implementables en cualquier orden de merge gracias al criterio verificable de FR-006.
