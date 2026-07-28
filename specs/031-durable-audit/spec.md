# Feature Specification: Auditoría durable — bloqueos registrados, escritura ruidosa, UI honesta

**Feature Branch**: `031-durable-audit`

**Created**: 2026-07-28

**Status**: Draft

**Input**: User description: "Lo de auditoría sí o sí arreglar, es un problemón. Somos un
producto de auditoría. (JF, 28-jul — decisión: sin coordinación con Cristian, deducir el
contrato del código y aplicar buenas prácticas de auditoría.) Para la demo del jueves
31-jul. La purga automática de retención (spec 018) queda explícitamente FUERA."

## El problema, con evidencia (28-jul, líneas verificadas en el código)

**El pitch del producto es «logueamos TODO para compliance», y hoy el evento más importante
— «se intentó y se impidió» — es el único que no deja rastro durable:**

1. **Plano motor (LiteLLM — TODO el tráfico byok de herramientas)**: los 4 puntos de bloqueo
   del guardrail devuelven el rechazo desde el pre-call (`basa_guardrail.py:105-166`) y el
   logger de auditoría **solo implementa el hook de éxito** (`basa_audit_logger.py:101`;
   `async_log_failure_event` no existe en el repo). Un bloqueo del motor NUNCA produce fila.
2. **Plano chat del backend (Playground/portal)**: 3 puntos de bloqueo (AI-Act
   `chat.py:598→603`, guardián `728→733`, residencia `839→844`) publican al monitor
   efímero de Redis (TTL 300 s) y hacen `raise` ANTES del único `log_transaction`
   (`chat.py:1137`). Diferido a «la 018» por el corte D6 (`chat.py:357-360`) — esta spec ES
   ese pago.
3. **Plano `/gw` passthrough**: único que SÍ escribe fila al bloquear (`gateway.py:818-825`),
   pero la escritura pasa por los tragadores de abajo. El camino byok se sale antes
   (`gateway.py:801-802`) y delega en el plano 1 (que no audita bloqueos).
4. **Escritura best-effort en TODAS las capas**: el POST del motor al plano interno traga
   4xx/5xx/timeout con un `print` (`basa_audit_logger.py:177-180, 104-105`); el escritor del
   backend dropea con `logger.error` y devuelve `None` que nadie mira
   (`audit_service.py:117-120`, deuda declarada en `:57-62`); el gateway envuelve todo otra
   vez (`gateway.py:603-604`). Este agujero YA causó pérdida total de auditoría byok en el
   ensayo del piloto (documentado en `basa_audit_logger.py:145-150`).
5. **Retención = campo de formulario**: `retention_days` se guarda y se muestra
   (`compliance.py:314-334`, pestaña «Retención de Datos») pero NINGÚN proceso lo lee para
   purgar; `purge_log` tiene cero escritores; el único scheduler del proceso es el de
   licencias (`main.py:80-88`).
6. **Guardianes**: de los 9 `guardian_type` sembrados, solo el plano regex/NLP ejecuta hoy
   (pii_masking/secret_detection/sensitive_routing, y solo en el plano chat); los 5 cloud
   son **features opcionales incoming por diseño de producto** (aclaración JF 28-jul) — el
   defecto NO es que existan sino que la UI los muestra como toggles activables cuando el
   motor descarta sus nombres en silencio (`ai_engine_client.py:201-204`,
   `governance_status.py:24-26`); `fail_mode`/`apply_on` no los lee ningún plano.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Todo bloqueo deja fila durable, en los tres planos (Priority: P1)

Un compliance officer filtra Logs de Auditoría por «bloqueado» y ve TODOS los intentos
impedidos — vengan del Playground, de un coding tool por `/gw` byok o del passthrough de
suscripción — con su atribución (usuario/llave/herramienta), la capa que bloqueó, el motivo
y las entidades detectadas. Regla de oro: **registrar → bloquear** (la fila se escribe antes
de, o con independencia de, lanzar el rechazo al cliente).

**Why this priority**: es la promesa central del producto; sin esto la demo de compliance
es indefendible («¿y si un empleado intenta pegar el padrón de socios? — no queda rastro»).

**Independent Test**: provocar un bloqueo en cada plano (prompt AI-Act prohibido en
Playground; mismo prompt por `/gw` con llave byok; y por passthrough) → 3 filas en
`audit_logs` con estado de bloqueo, plano y atribución correctos, visibles en la UI.

**Acceptance Scenarios**:

1. **Given** una política que bloquea cierto contenido, **When** un usuario lo intenta en
   el Playground, **Then** recibe el 4xx de siempre Y existe fila durable con
   estado=bloqueado, capa=la que actuó, atribución completa.
2. **Given** ídem, **When** el intento entra por `/gw` byok (motor), **Then** el guardrail
   registra la fila (con la identidad de la Connection) ANTES de devolver el rechazo.
3. **Given** ídem por passthrough, **Then** la fila existente de `gateway.py:818` sobrevive
   a las capas de tragado del punto 4 (US2) y llega a la base.
4. **Given** un bloqueo con la base de auditoría CAÍDA, **Then** aplica la política de la
   US2 (nunca «se bloqueó y no quedó nada» en silencio).
5. **Given** los filtros de Logs de Auditoría, **When** el officer filtra por bloqueados,
   **Then** los distingue de los permitidos sin ambigüedad (estado explícito, no un 0/0
   tokens que hay que interpretar).

---

### User Story 2 - La auditoría no falla en silencio: ruidosa por defecto, fail-closed opcional (Priority: P2)

Si la escritura de auditoría falla, el sistema deja de fingir que no pasó nada. Dos
comportamientos, elegibles por configuración de la instalación:

- **`audit_fail=open` (default del piloto)**: el tráfico se sigue sirviendo, pero el fallo
  (a) se reintenta acotadamente, (b) incrementa un contador visible en el health y en la
  UI (banner en Logs de Auditoría: «N eventos no registrados desde HH:MM»), y (c) queda en
  el log del servicio con nivel de error. Nunca un `print`.
- **`audit_fail=closed`**: instalaciones donde el cliente exige «sin auditoría no hay
  servicio»: la petición se rechaza con error honesto (503) mientras la auditoría no pueda
  escribirse. Mismo patrón que el fail-closed de licencias (021).

**Why this priority**: un registro con agujeros silenciosos es peor que ninguno — el
officer confía en algo incompleto. Ya nos pasó (pérdida total del rastro byok en el ensayo).

**Independent Test**: tirar la base de auditoría con tráfico corriendo: en `open`, el
tráfico sigue + contador sube + banner aparece + al volver la base el contador queda como
constancia; en `closed`, las peticiones reciben 503 honesto y al volver la base todo fluye.

**Acceptance Scenarios**:

1. **Given** `open` y la base caída, **When** se sirven 5 peticiones, **Then** las 5
   responden, el contador marca 5 y la UI lo muestra sin que nadie lo busque.
2. **Given** `closed` y la base caída, **When** llega una petición, **Then** 503 con motivo
   honesto y sin llamada al proveedor (no se gasta dinero en tráfico inauditable).
3. **Given** un fallo transitorio (1 timeout), **Then** el reintento acotado lo absorbe y
   no hay ni pérdida ni ruido.
4. **Given** el hash-chain de licencias (021) conviviendo en la misma tabla, **Then** nada
   de esta spec rompe su verificación (los eslabones `model='license'` quedan intactos).

---

### User Story 3 - La UI no promete lo que el producto no hace (Priority: P3)

El admin/officer ve el estado REAL: la pestaña «Retención de Datos» declara que la purga
automática aún no ejecuta (estado «programada — pendiente de activación», sin fingir
enforcement); la página «Seguridad y Guardianes» presenta el guardián regex/NLP como EL
guardián activo de la instalación, y los 5 cloud como lo que son por diseño de producto:
**opciones futuras del catálogo** («próximamente» / «no instalado», no activables) —
aclaración de JF 28-jul: son features incoming, no promesas rotas; lo que corrige esta US
es que hoy se pintan como toggles operativos. Los que sí ejecutan declaran su alcance
(«aplica en el chat interno», no «en todo»).

**Why this priority**: JF lo definió como «governance configurable + UI honesta». Vender
con una marquesina que promete 9 guardianes y entrega 3 es un riesgo comercial y de
confianza mayor que decir la verdad bien dicha.

**Independent Test**: revisar ambas páginas contra la tabla de consumo real (evidencia de
esta spec): cero afirmaciones de la UI sin respaldo en un plano de ejecución.

**Acceptance Scenarios**:

1. **Given** «Seguridad y Guardianes», **When** el admin mira un guardián cloud del
   catálogo incoming, **Then** lo ve etiquetado «próximamente / no instalado» (no un
   toggle verde que no hace nada), y activarlo NO es posible mientras no exista el
   guardrail que lo respalde.
2. **Given** «Retención de Datos», **Then** el copy y el estado dejan claro que el valor
   es la política DECLARADA y que la purga automática llega con la 018 — sin checkbox
   mentiroso ni fecha inventada.
3. **Given** los 3 guardianes reales, **Then** su tarjeta dice en qué plano(s) ejecutan.

---

### Edge Cases

- Bloqueo del motor SIN identidad resoluble (llave inválida) → fila igual, con atribución
  anónima (el intento existe aunque no sepamos de quién es; ya hay patrón en `_audit`).
- Doble registro (motor registra el bloqueo Y el gateway passthrough también) → deduplicar
  por diseño de responsabilidades: cada plano registra SOLO sus propios bloqueos; el
  passthrough no re-registra lo que bloqueó el motor.
- Avalancha de bloqueos (script malicioso) → la escritura durable no puede convertirse en
  DoS interno: mismo presupuesto de reintentos acotado; el contador de pérdida es la
  válvula, no una cola infinita.
- `audit_fail=closed` con la base caída Y el health del motor consultándose → el health
  refleja el estado (degradado por auditoría), no un «healthy» mentiroso.
- Streaming en curso cuando la auditoría falla en `closed` → la petición YA aceptada se
  completa; el corte aplica a las siguientes (documentado, no sorpresa).
- La fila de bloqueo del plano motor necesita datos que hoy viven en el verdict del
  guardrail (capa, entidades) → viajan en el evento, sin inventar campos nuevos si los de
  `audit_logs` alcanzan (el officer necesita: cuándo, quién, qué capa, por qué).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Todo bloqueo en cualquier plano (motor/pre-call, chat backend, gateway
  passthrough) MUST producir una fila durable en `audit_logs` con: timestamp, plano,
  estado de bloqueo, capa/regla que bloqueó, atribución (tenant/usuario/llave/herramienta
  cuando existan), y conteo de entidades si aplica. El orden MUST ser registrar→bloquear
  (o registro garantizado independiente del raise).
- **FR-002**: Los 3 puntos de bloqueo de `chat.py` MUST escribir la fila durable además
  del evento de monitor efímero que ya publican (que se conserva: la vitrina sigue).
- **FR-003**: El plano motor MUST registrar sus bloqueos con la identidad de la Connection
  que autenticó la petición; la vía de escritura reusa el plano interno existente
  (`/api/v1/internal/audit`) — Principio VI: sin parchear LiteLLM, todo en extensiones.
- **FR-004**: La escritura de auditoría MUST tener reintento acotado y, si aun así falla,
  MUST incrementar un contador expuesto en el health y visible en la UI de Logs; los
  `print` de las extensiones MUST desaparecer en favor de logging real.
- **FR-005**: La instalación MUST poder elegir `audit_fail=open|closed` (config de
  perfil, default `open`); en `closed`, tráfico no-auditable MUST rechazarse con error
  honesto ANTES de llamar al proveedor.
- **FR-006**: Los filtros de Logs de Auditoría MUST permitir aislar los bloqueos, y la
  fila MUST distinguirse visualmente (no inferirse de tokens 0/0).
- **FR-007**: «Seguridad y Guardianes» MUST reflejar disponibilidad real por guardián
  (cargado/no disponible en esta instalación) y plano de aplicación; activar un guardián
  sin guardrail cargado MUST ser imposible o declarar `no_disponible` (reusar el resolutor
  de la 027, que ya calcula exactamente esto).
- **FR-008**: «Retención de Datos» MUST declarar el estado real de la purga (no ejecuta
  aún; llega con la 018) manteniendo editable la política declarada.
- **FR-009**: La purga automática, los 5 guardianes cloud y el dead-letter con reproceso
  quedan explícitamente FUERA (018/roadmap) — esta spec no los promete ni los aparenta.
- **FR-010**: Nada de esta spec MUST romper el hash-chain de licencias (021) ni el filtro
  `model <> 'license'` de la vitrina/analytics (protegido tras el hallazgo de la 028).

### Key Entities

- **Evento de bloqueo durable**: fila de `audit_logs` con estado de bloqueo, plano de
  origen, capa/regla, atribución, entidades; misma tabla, sin esquema paralelo.
- **Política de fallo de auditoría**: `open|closed` + contador de eventos perdidos +
  timestamp del último fallo; vive en config de instalación y se expone en health.
- **Disponibilidad de guardián**: cargado / no disponible / plano de aplicación —
  derivada del resolutor 027 + config real del motor, nunca del `is_active` deseado.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Bloqueo provocado en cada uno de los 3 planos → 3 filas durables correctas
  (plano, capa, atribución) visibles en la UI filtrando por «bloqueados». Hoy: 0 de 3
  sobreviven a los 5 minutos del monitor.
- **SC-002**: Base de auditoría caída 60 s con tráfico: en `open`, 0 peticiones fallidas,
  contador == peticiones no auditadas, banner visible; en `closed`, 100% de rechazos
  honestos y 0 llamadas al proveedor durante la caída.
- **SC-003**: Suite de la 021 (hash-chain/licencias) sigue verde sin modificar sus tests.
- **SC-004**: Cero afirmaciones de capacidad en «Seguridad y Guardianes» y «Retención»
  sin plano de ejecución que las respalde (checklist contra la tabla de consumo real).
- **SC-005**: Demo del jueves: intento de fuga bloqueado en vivo → el officer lo encuentra
  en Logs de Auditoría en <30 s, con quién/qué/cuándo/qué capa.

## Assumptions

- La tabla `audit_logs` existente alcanza para el evento de bloqueo (estado + metadatos);
  si el estado necesita un valor nuevo, es un valor de columna, no una tabla nueva.
- El default del piloto es `audit_fail=open` (continuidad primero, señal visible) — JF
  puede cambiarlo a `closed` por perfil de instalación; la Cámara se instala con `open`.
- El evento del plano motor viaja por el plano interno HTTP existente (el motor no tiene
  driver de DB — restricción conocida de la imagen LiteLLM).
- La decisión JF 28-jul aplica: sin coordinación previa con el owner del módulo de
  seguridad; el contrato del evento se deduce del verdict del guardrail y de las columnas
  existentes; su review llega vía PR como cualquier cambio.
- El monitor efímero (TTL 300 s) NO cambia: es vitrina, la durabilidad es de esta spec.
