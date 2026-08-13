# Feature Specification: Retención con dientes — purga programada + tiers de enforcement

**Feature Branch**: `018-retencion-tiers`

**Created**: 2026-08-13

**Status**: Draft — en gate de producto (JF)

**Input**: ROADMAP-guardian fila 018 (P1, camino crítico del 5-SEP) + mapa as-is del terreno (research 13-ago, 5 lectores + síntesis, evidencia `path:line` verificada sobre `main` @ `81ea8ce`)

---

## Contexto y honestidad SDD *(léelo antes que nada)*

**La promesa que esta spec paga**: el producto vende «retención configurable» y hoy eso es verdad solo a medias — se puede *configurar* y no se *cumple*. Las cuatro políticas de retención existen sembradas desde la migración 004 (`prompt_content` 90 días, `usage_metadata` 365, `security_events` 365, `config_audit` 730 — `backend/alembic/versions/004_compliance_tables.py:100-109`), la UI permite editarlas, y **ningún proceso las hace cumplir**: no existe un solo job de purga en el producto (el único scheduler es la reconciliación de seats de la 021), y `purge_log` existe desde la 004 con **cero escritores** (grep verificado). La purga real al día 91 es la mitad RGPD de la promesa de Fase 0 (Art. 5.1.e, limitación del plazo de conservación).

**Por qué ahora**: (1) camino crítico del 5-SEP; (2) es uno de los tres disparadores del gate 250 — toca la tabla de auditoría cuyos SLOs de paridad mide La ITV; (3) la 031 dejó la auditoría durable y difirió explícitamente la purga «a la 018».

**Deslinde con el módulo de Cristian (OBLIGATORIO leerlo así)**: la Parte 4 del BRIEF del módulo de políticas («Retención con dientes», ✅ confirmada con Cristian el 11-ago, rama shaping líneas 200-212) describe **este mismo trabajo**. Para que al betting no lleguen dos papeles por la misma purga, esta spec nace deslindada:

- **La 018 (esta spec) absorbe el ENFORCEMENT**: el job de purga, los tiers, la exclusión de la hash-chain, el purge_log.
- **La 036 (Cristian) conserva la FUENTE de configuración**: `retention_days` por clase dentro del PolicyBundle (su FR-003). Cuando su módulo entre, el purgador lee de ahí; hasta entonces, lee de `retention_policies` como hoy.
- **La Parte 5 del BRIEF (DSR rectificación + borrado por sujeto) y el DSAR #62 quedan FUERA de esta spec** (ver Out of scope). Dueño resuelto por JF (13-ago): con Cristian a cargo del wizard 037, el DSAR pasa a Guardian como **spec propia en C3** — hereda de esta spec el contrato de identidad batch y de la 017 el actor/RLS, que es justo la maquinaria que abarata el borrado por sujeto.
- El rabbit-hole sellado de su Parte 4 — «no tocar el esquema de `audit_logs`» — **se respeta como restricción de diseño** (ver FR-002). Si la implementación demuestra que no alcanza, se renegocia con Cristian explícitamente; no se pisa.

**Costura con la 017 (se escribe en paralelo)**: `audit_logs` está bajo RLS FORCE. Hoy cualquier proceso sin contexto de tenant escribe/lee gracias a la policy permisiva `tenant_isolation_bootstrap`, que la 017 tiene **mandato escrito de eliminar** (`010_multitenant_foundation.py:33-38,82-84`). Un purgador escrito «como hoy» pasaría de funcionar a **no ver filas** el día que la 017 mergee — retención que aparenta enforced sin serlo, el peor modo de falla. El contrato de identidad de los jobs batch (FR-006) se sella en ambas specs.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — La instalación cumple sola lo que promete (Priority: P1)

El administrador de una instalación configuró (o heredó por defecto) los plazos de retención. A partir del despliegue de esta feature, los datos que superan su plazo **desaparecen solos**: al día 91, el contenido clasificado como `prompt_content` ya no existe en la instalación, sin que nadie corra nada a mano.

**Why this priority**: es la promesa RGPD literal. Sin esto, todo lo demás de la spec es decoración.

**Independent Test**: sembrar una instalación con filas sintéticas fechadas hasta 200 días atrás; dejar pasar un ciclo del purgador; verificar por SQL que no queda ninguna fila vencida de las clases purgables y que las no vencidas están intactas.

**Acceptance Scenarios**:

1. **Given** filas de auditoría con edad > plazo de su clase, **When** corre el ciclo de purga, **Then** esas filas ya no existen y las de edad ≤ plazo permanecen completas.
2. **Given** la corrida terminó, **When** el auditor consulta el registro de purgas, **Then** encuentra una entrada por corrida con clase, cantidad de filas eliminadas, rango de fechas afectado y duración.
3. **Given** una fila de la cadena de licencias (clase excluida), **When** corre cualquier ciclo de purga, **Then** la fila sigue existiendo y `verify_chain` + el export de true-up pasan igual que antes de la corrida.
4. **Given** una revisión humana cuyo texto de respuesta superó el plazo de `prompt_content`, **When** corre el ciclo, **Then** el texto ya no existe pero la revisión persiste como metadata (quién revisó, cuándo, veredicto).

### User Story 2 — El administrador gobierna el rigor con un tier (Priority: P2)

El administrador elige el **tier de enforcement** de la instalación — `estricto` o `estándar` — y con eso queda fijado, de una sola vez y auditablemente, cuán duro se comporta el producto ante los grises: qué consecuencia tienen las capas de gobernanza que admiten grado, qué postura de fallo adopta la auditoría y qué pisos de retención son inviolables.

**Why this priority**: es la otra mitad del título de la spec; convierte decisiones dispersas (env vars, toggles) en una postura de compliance declarable ante el cliente.

**Independent Test**: cambiar el tier por la API y verificar que (a) el cambio queda auditado como cambio de configuración, (b) las consecuencias declaradas del tier se observan en el comportamiento (una petición que en `estándar` se registra, en `estricto` se bloquea), (c) los pisos del tier no se pueden violar por configuración individual.

**Acceptance Scenarios**:

1. **Given** tier `estricto`, **When** un administrador intenta configurar un plazo de retención por debajo del piso del tier, **Then** el backend lo rechaza con error de validación (no lo acepta y lo ignora en silencio).
2. **Given** un cambio de tier, **When** se consulta la auditoría, **Then** existe una fila de cambio de configuración con el tier anterior y el nuevo.
3. **Given** cualquier tier, **When** se evalúa la capa de piso del AI-Act, **Then** la evaluación ocurre siempre — el tier gobierna **consecuencias**, jamás apaga evaluaciones (invariante heredada de la 027, `basa_governance.py:272-283`).

### User Story 3 — La purga no le cuesta el examen a nadie (Priority: P2)

La ITV corre el gate 250 sobre una instalación con el purgador activo. La purga trabaja por lotes acotados dentro de una ventana configurada y **los SLOs del examen no se enteran** de que existe.

**Why this priority**: `audit_logs` es la tabla más caliente del producto (4 índices, lectores SQL directos de costos/analytics/vitrina/export) y no tiene particiones — la purga es DELETE puro. C2 es exactamente el ciclo del gate 250: un purgador glotón aprobaría lo funcional y reprobaría el examen.

**Independent Test**: bajo el perfil de carga del gate 125 (el instrumento ya existe), disparar una corrida de purga concurrente con backlog real y verificar que los SLOs de latencia y paridad del examen se mantienen.

**Acceptance Scenarios**:

1. **Given** carga sostenida del perfil 125 y backlog de filas vencidas, **When** la purga corre en su ventana, **Then** los 4 SLOs de oro del examen se mantienen en verde.
2. **Given** una corrida interrumpida a mitad de lote, **When** el purgador vuelve a arrancar, **Then** retoma sin duplicar registro de purga ni saltarse filas vencidas (idempotencia por diseño).

### Edge Cases

- **Filas de intención sin cierre** (si la apuesta dos-fases #182 de Cristian entra): la edad cuenta **desde el timestamp de la intención**. Esta spec no crea esa clase — solo deja definida su muerte para que el purgador no necesite re-especificarse.
- **Plazo acortado en caliente**: si el administrador baja un plazo, la siguiente corrida purga el backlog nuevo — el sistema converge a la política vigente, no a la histórica. El purge_log de esa corrida evidencia el salto de volumen.
- **Reloj**: la edad se calcula contra el reloj de la base de datos, no del proceso — una desincronización del host no puede purgar de más.
- **Referencias colgantes**: `human_reviews.audit_log_id` es UUID **sin FK** (`models/compliance.py:77`); tras purgar la fila de auditoría, la revisión queda con referencia a una fila inexistente. Se acepta como huérfano lógico documentado: la revisión es metadata con valor propio y su TEXTO ya tiene muerte propia (FR-004).
- **Cadena de licencias intercalada**: la exclusión de FR-003 es por clase, no por rango de fechas — filas `license` de hace dos años sobreviven a cualquier purga aunque todo lo demás de esa época muera.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001 — Purga programada**: el sistema DEBE eliminar automáticamente las filas de auditoría cuya edad supere el plazo vigente de su clase de retención, mediante un proceso recurrente que trabaja **por lotes acotados** dentro de una **ventana horaria configurable** (tamaño de lote y ventana con defaults definidos en el plan; ambos operables sin redeploy).
- **FR-002 — Clasificación sin tocar el esquema**: la pertenencia de una fila a una clase de retención se determina por un **clasificador único y compartido** definido en un solo lugar, consumido tanto por el purgador como por la vitrina de auditoría (que hoy duplica esa lógica en constantes locales — `backend/src/api/audit.py:36-64`). El esquema de `audit_logs` NO se modifica (restricción heredada del rabbit-hole sellado de la Parte 4 del BRIEF; renegociación explícita con Cristian como única vía de cambio).
- **FR-003 — La cadena no se toca**: las filas de la cadena de evidencia de licencias (`model='license'`) quedan **permanentemente excluidas** de toda purga. Es un requisito de diseño, no un detalle: `verify_chain` acusa manipulación ante cualquier hueco (`licensing/audit_events.py:82-116`) y el true-up exige historial completo — purgar un eslabón es un incidente de confianza con el cliente, no un bug.
- **FR-004 — El único texto real también muere**: `human_reviews.response_text` — hoy el único contenido real durable del sistema (`models/compliance.py:84`), sin retención alguna — entra bajo el plazo de `prompt_content`: al vencer, el texto se elimina y la revisión persiste como metadata. Sin esto, «purga al día 91» no borra el único contenido que de verdad existe.
- **FR-005 — La purga es auditable**: cada corrida escribe su entrada de registro (clase, filas eliminadas, rango temporal, duración, resultado) en el mecanismo de `purge_log` que la 004 dejó preparado y nadie escribe. Una purga que no deja rastro no es demostrable ante un auditor.
- **FR-006 — Contrato de identidad batch (costura 017)**: el purgador — y todo job batch que toque tablas bajo RLS — declara su identidad mediante el contexto de tenant con bypass explícito y documentado (`database.py:64-76` es el mecanismo existente; `gateway.py:901` el precedente). El emisor de eventos de la cadena de licencias, que hoy escribe con sesión pelada (`audit_events.py:213-218`), se corrige al mismo contrato en esta spec. **Criterio verificable**: los tests de purga corren con la policy bootstrap eliminada y rol de base de datos sin bypass — el mundo post-017 — y pasan.
- **FR-007 — Validación de plazos en el backend**: los cambios de política de retención se validan en el servidor (mínimos por clase, incluido el piso vigente `config_audit` ≥ 365; máximos razonables por clase), no solo en la UI como hoy (`compliance.py:319-334`). Valor fuera de rango → error de validación explícito.
- **FR-008 — Tiers de enforcement**: existe un **tier por instalación** (`estricto` | `estándar`) que fija de una vez: (a) la consecuencia de las capas de gobernanza que admiten grado (bloquear vs registrar) — la capa de piso del AI-Act se evalúa SIEMPRE, el tier solo gobierna consecuencias; (b) la postura de fallo de auditoría permitida (en `estricto`, fail-closed obligatorio); (c) los pisos de retención inviolables por configuración individual. El tier se modela **sobre el registry de capas de la 027** (opción sin migración estructural); su cambio queda auditado como cambio de configuración.
- **FR-009 — Quién escribe retención (decisión conjunta con la 017)**: tras la matriz de roles de la 017, la escritura de políticas de retención y del tier queda en el administrador del tenant; el rol auditor (read-only) las **lee** pero no las modifica. Hoy `PUT /compliance/retention` acepta ambos (`compliance.py:319`) — esta spec asume el recorte y la 017 lo ejecuta; ninguna de las dos implementa la escritura para el auditor.
- **FR-010 — Retención por tenant: diferida con nombre**: el UNIQUE global de `log_type` se mantiene (una política por clase por instalación). La partición por tenant `(tenant_id, log_type)` que el modelo reserva por comentario a esta spec (`models/compliance.py:93-95`) queda **explícitamente diferida** — consistente con la asunción sellada en la 036 («una instalación = un cliente fijo») — y documentada como deuda con dueño en el ROADMAP.

### Key Entities

- **Clase de retención**: agrupación lógica de filas de auditoría (`prompt_content`, `usage_metadata`, `security_events`, `config_audit`) con un plazo en días. Ya existe en `retention_policies`; esta spec le da dientes.
- **Corrida de purga**: unidad auditable de trabajo del purgador — qué clase, cuántas filas, qué rango, cuánto tardó, cómo terminó.
- **Tier de enforcement**: postura de rigor de la instalación (`estricto`/`estándar`) que gobierna consecuencias, posturas de fallo y pisos — nunca evaluaciones.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: en una instalación sembrada con 200 días de datos sintéticos, tras un ciclo completo de purga: **cero** filas vencidas de clases purgables, **cero** filas no vencidas afectadas, y `verify_chain` + export de true-up en verde. Verificable por SQL sin conocer la implementación.
- **SC-002**: el 100% de las corridas de purga tienen su entrada de registro; un auditor externo puede reconstruir qué se borró, cuándo y bajo qué política **solo** con el registro de purgas.
- **SC-003**: bajo el perfil de carga del gate 125 con purga concurrente activa, los 4 SLOs de oro del examen se mantienen en verde (medible con el harness 035 existente, sin infra nueva).
- **SC-004**: con la policy bootstrap eliminada y rol de DB sin bypass (el mundo post-017), la suite de purga completa pasa — la retención sigue enforced después del cierre de RLS.
- **SC-005**: un intento de configurar un plazo bajo el piso del tier devuelve error de validación en el 100% de los casos — por API, no solo por UI.
- **SC-006**: el cambio de tier queda auditado en el 100% de los casos, con valor anterior y nuevo.

---

## Out of scope *(explícito, para que el betting no lo re-discuta)*

- **DSAR #62 y el borrado por sujeto**: purgar por edad y borrar por persona son obras distintas. **Decisión sellada (JF, 13-ago)**: el DSAR deja de ser la Parte 5 del BRIEF de Cristian (quedó huérfana al pasar él al wizard 037) y pasa a Guardian como **spec propia en C3**, después de que 017/018 dejen lista la maquinaria de la que depende (identidad batch, actor, RLS). El export DSAR roto hoy (500 a cualquier rol, `reports.py:89`; issue #193) es un **bug** y su fix de una línea va como tarea suelta del encargo de implementación — no espera a C3.
- **Particionado de `audit_logs`** u otra cirugía de esquema para acelerar purgas: si el volumen algún día lo exige, será una spec de infraestructura con sus propios números.
- **Retención de la base propia del motor** (`basa_engine`): inventariarla es un spike de C3; esta spec purga el plano del producto.
- **La FUENTE de configuración futura** (retention_days dentro del PolicyBundle): es FR-003 de la 036 de Cristian. Esta spec consume la fuente vigente y define el contrato de lectura, no la reemplaza.

## Assumptions

- Instalación single-tenant en la práctica (asunción compartida con la 036); el multi-tenant real despierta en specs posteriores.
- La apuesta dos-fases (#182) puede entrar o no en C2: el purgador definido aquí no depende de ella; si entra, la clase de intención hereda la regla de edad del Edge Case correspondiente.
- El patrón de scheduler existente (reconciliación 021) es reutilizable como vehículo; si el plan técnico elige otro, los FRs no cambian.
- Los plazos por defecto sembrados (90/365/365/730) son los correctos de negocio; esta spec no los re-discute, los hace cumplir.

## Dependencies

- **017** (paralela): contrato de identidad batch (FR-006) y recorte de escritura del auditor (FR-009) — sellados en ambas specs, implementables en cualquier orden de merge gracias al criterio verificable de FR-006.
- **036/#141-#147 (Cristian)**: deslinde de fuente de configuración (arriba). Orden de merge de su stack: no bloqueante para esta spec (no comparte archivos calientes).
- **Gate 250 (La ITV)**: esta spec es uno de sus tres disparadores; SC-003 se mide con su instrumento.
