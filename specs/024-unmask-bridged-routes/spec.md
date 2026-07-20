# Feature Specification: Restauración de PII y atribución en respuestas byok (rutas bridged)

**Feature Branch**: `024-unmask-bridged-routes`

**Created**: 2026-07-20

**Status**: Draft

**Input**: User description: "Fix-spec del issue #27 (spike 019 batch 1): en el camino byok con modelos no-Claude del motor, la restauración (unmask) de PII sobre la respuesta no corre — el empleado ve placeholders — y los eventos del monitor llegan sin identidad (tool/client/tenant null). Cerrar el round-trip mask→unmask en TODO camino byok y devolver la atribución, con la evidencia e2e que hoy falta."

## Contexto (por qué ahora)

El spike batch 1 de la 019 (2026-07-20, evidencia en `specs/019-integration-surfaces/spikes-batch1.md`)
probó que el gateway puede gobernar **modelos propios/locales** del cliente — incluido el modo
Agent de Claude Code — pero dejó tres superficies de la matriz en **PARCIAL** por un único
defecto: el enmascaramiento de ida funciona (el modelo jamás ve el dato real), pero la
**restauración de vuelta no corre** en el camino de modelos puenteados por el motor, ni en
streaming ni en no-streaming. El empleado ve `[EMAIL_ADDRESS_…]` donde debía ver el valor;
una herramienta de edición puede dejar el placeholder escrito en un archivo. Además, los
eventos del monitor de ese camino llegan **sin identidad** — un producto que se vende por su
auditoría muestra eventos anónimos. Es fail-safe (cero fuga), pero es deuda de honestidad
del producto: la matriz no puede decir FUNCIONA hasta que esto cierre.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - El empleado recibe valores reales, no placeholders (streaming) (Priority: P1)

Una empleada de un cliente de infraestructura usa su coding tool (Claude Code / Aider)
contra el gateway con el modelo propio de la organización. Su prompt menciona el email de
un paciente; la protección lo enmascara antes de salir al modelo. Cuando el asistente
responde citando ese email, ella ve **el valor real**, no el placeholder — la protección es
invisible para quien trabaja.

**Why this priority**: el streaming es el camino real de todas las coding tools (Claude
Code siempre streamea). Es el defecto visible que hoy frena la promoción de tres superficies
de la matriz y el argumento de venta del "entorno controlado" acordado para clientes de
infraestructura.

**Independent Test**: con el stack vivo y un modelo local registrado, enviar por el gateway
un prompt en streaming con PII pidiendo repetirla; verificar que el texto que llega al
cliente contiene el valor original y que el modelo solo vio el placeholder.

**Acceptance Scenarios**:

1. **Given** una Connection byok con masking activo y un modelo puenteado por el motor,
   **When** el empleado envía en streaming un prompt con un email y el modelo lo repite,
   **Then** los fragmentos que llegan al cliente contienen el email original y en ningún
   fragmento sobrevive el placeholder.
2. **Given** el mismo escenario, **When** el modelo repite el dato partido entre dos
   fragmentos del stream (el placeholder cruza el borde), **Then** la restauración
   reconstruye el valor completo sin perder ni duplicar texto.
3. **Given** el mismo escenario, **When** la respuesta incluye el dato dentro de los
   argumentos de una tool o de un bloque de razonamiento, **Then** esos campos también
   vuelven restaurados (mismo contrato que el camino de suscripción).
4. **Given** una respuesta sin placeholders, **When** atraviesa la restauración, **Then**
   llega intacta (misma estructura, mismos ids y usage) sin costo perceptible.

---

### User Story 2 - Round-trip completo en no-streaming (Priority: P2)

Un integrador del cliente consume el gateway por API directa (sin streaming) para un flujo
batch. El mismo contrato aplica: lo que se enmascaró a la ida vuelve restaurado, sea cual
sea el modelo del motor que respondió.

**Why this priority**: el no-streaming es el camino de integraciones programáticas y de
partes del flujo editor de Aider; hoy falla igual que el streaming pero afecta a menos
superficies visibles.

**Independent Test**: petición no-streaming con PII contra un modelo puenteado; la
respuesta JSON contiene el valor original en todos los campos de texto.

**Acceptance Scenarios**:

1. **Given** una Connection byok con masking activo, **When** una petición no-streaming con
   PII recibe respuesta de un modelo puenteado, **Then** todos los campos de texto,
   razonamiento y argumentos de tools de la respuesta vuelven con los valores originales.
2. **Given** una herramienta de edición (tipo Aider) que escribe archivos con lo que el
   modelo devuelve, **When** el prompt contiene PII que el modelo debe reproducir, **Then**
   el archivo final contiene el valor real, no el placeholder.

---

### User Story 3 - El operador ve QUIÉN habló en el monitor (Priority: P3)

El operador del cliente abre el monitor del gateway y ve, para cada petición byok, la
herramienta, el cliente y el tenant que la originaron — igual que en el camino de
suscripción. Hoy esos eventos llegan anónimos (`tool/client/tenant: null`).

**Why this priority**: la auditoría con identidad es parte del contrato del producto
(pipeline transparente); sin ella el monitor del camino byok no sirve para un ticket ni
para un informe de compliance. Es independiente del unmask y entregable por separado.

**Independent Test**: enviar tráfico byok identificado con una virtual key; verificar que
el evento del feed lleva la herramienta detectada y la identidad de la Connection.

**Acceptance Scenarios**:

1. **Given** tráfico byok con una virtual key válida, **When** el evento aparece en el feed
   del monitor, **Then** lleva tool, client y tenant de la Connection que lo originó.
2. **Given** el mismo tráfico, **When** el guardrail enmascaró entidades, **Then** el
   evento registra el conteo de entidades enmascaradas (metadata-only, sin contenido).

---

### Edge Cases

- Placeholder partido entre fragmentos del stream (incluido un multibyte UTF-8 partido) →
  reconstrucción sin pérdida (escenario 1.2).
- Stream truncado a mitad de un placeholder (el upstream corta) → lo retenido se entrega
  restaurado al cierre; jamás se pierde texto del usuario.
- Respuesta con múltiples placeholders del mismo tipo en el mismo fragmento → todos
  restaurados con su valor correspondiente (el mapping es por token único).
- El mapping de tokens no está disponible al volver (petición no enmascarada, o error
  interno) → la respuesta se entrega tal cual, sin romperla ni bloquearla (fail-safe), y
  el evento del monitor lo refleja.
- Modelos cloud del motor (no solo el modelo local) atraviesan el mismo camino puenteado →
  el contrato aplica igual, sea cual sea el proveedor.
- Peticiones con masking desactivado por Connection (`redact_enabled=false`) → sin cambios:
  nada que restaurar, la respuesta pasa intacta.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Toda respuesta byok cuyo request fue enmascarado DEBE llegar al cliente con
  los valores originales restaurados, en streaming y en no-streaming, **independientemente
  del modelo/proveedor del motor que la sirvió** (passthrough o puenteado).
- **FR-002**: La restauración DEBE cubrir los campos de texto, los bloques de razonamiento
  y los argumentos/resultados de tools de la respuesta — el mismo alcance que ya cumple el
  camino de suscripción del gateway.
- **FR-003**: La restauración NO DEBE alterar nada más del payload: estructura de eventos,
  ids, usage y orden de fragmentos se preservan fuera de los reemplazos.
- **FR-004**: Un placeholder partido entre fragmentos del stream DEBE reconstruirse sin
  pérdida ni duplicación de texto, incluido el cierre de un stream truncado.
- **FR-005**: Si el mapping de restauración no está disponible, la respuesta DEBE
  entregarse tal cual (fail-safe: jamás se rompe ni se bloquea una respuesta por no poder
  restaurar).
- **FR-006**: Los eventos del monitor originados por tráfico byok DEBEN llevar la identidad
  de la Connection (herramienta detectada, cliente, tenant) y el conteo de entidades
  enmascaradas, metadata-only.
- **FR-007**: El repositorio DEBE quedar con verificación automatizada del round-trip
  mask→unmask **contra el motor vivo** (streaming y no-streaming, con al menos un modelo
  puenteado), que falle si el unmask deja de correr — el hueco de evidencia que permitió
  que este defecto llegara a la matriz sin detectarse.
- **FR-008**: La solución DEBE respetar el Principio VI (motor nativo, sin parchear): todo
  cambio vive en las extensiones propias montadas sobre el motor, nunca en su código.
- **FR-009**: Al cierre, el registro de superficies (019) DEBE reflejar las promociones que
  esta evidencia habilite (PARCIAL → FUNCIONA donde el unmask era el único freno) y la
  documentación de producto afectada DEBE actualizarse (G9, §3.5, matriz — DoD de docs).

### Key Entities

- **Mapping de restauración (pii_tokens)**: pares placeholder → valor original generados al
  enmascarar la petición; viven solo durante el ciclo request/response y nunca se persisten.
- **Evento de monitor**: registro metadata-only de una petición gobernada (herramienta,
  cliente, tenant, modelo, estado de compliance, conteos de entidades) — sin contenido.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: En el entorno de verificación vivo, el 100% de las respuestas byok con PII
  enmascarada vuelve con los valores originales (streaming y no-streaming, modelo local y
  modelo cloud puenteado) — hoy: 0%.
- **SC-002**: 0 placeholders visibles en archivos generados por el flujo editor verificado
  (Aider) cuando el prompt lleva PII — hoy: el archivo hereda el placeholder.
- **SC-003**: La protección de ida no se degrada: el modelo upstream sigue sin ver jamás el
  dato real en el 100% de los casos verificados (mismo estándar de evidencia del spike).
- **SC-004**: El 100% de los eventos byok del feed del monitor lleva herramienta, cliente y
  tenant — hoy: null.
- **SC-005**: Tres superficies del registro 019 (Ollama upstream, Claude Code → modelo
  propio, Aider) quedan promovidas a FUNCIONA con evidencia, y G9 pasa de límite vigente a
  gotcha histórico resuelto en la documentación de producto.
- **SC-006**: Una regresión futura del round-trip se detecta en el gate del repo, no en
  producción (la verificación de FR-007 falla en rojo si el unmask deja de correr).

## Assumptions

- **Alcance acotado al camino del motor**: el round-trip del gateway para el passthrough de
  suscripción ya funciona y está cubierto por tests de contrato — esta spec NO lo toca.
- **La detección/masking de ida no cambia**: la cobertura de detectores (p. ej. patrones
  AWS) es territorio de la spec 016 (módulo seguridad); acá solo se cierra la vuelta y la
  atribución.
- **Superficie compartida**: el trabajo toca la extensión de política montada en el motor
  (`litellm/`, CODEOWNERS de los tres) y es frontera con el módulo seguridad — coordinación
  con Cristian ya iniciada en el issue #27; el PR pedirá su review.
- **La ruta Responses del motor queda fuera**: corre sin política por diseño actual y no se
  ofrece a clientes; su gobernanza llega con la spec de superficies de compatibilidad
  (issue #28), no con este fix.
- **El stack de verificación vivo existe** (motor + modelo local del spike batch 1); la
  evidencia e2e de FR-007 lo reutiliza.
