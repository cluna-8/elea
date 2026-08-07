# Feature Specification: Ahorro de Costes IA en el plano firewall

**Feature Branch**: `023-ahorro-costes-firewall`

**Created**: 2026-07-15

**Status**: Draft

**Owner**: JF — herencia 03-ago, la división por módulos del 15-jul quedó superada (ver `ROADMAP-guardian.md`)

**Input**: User description: "Llevar Ahorro de Costes IA (spec 012) al plano firewall: compresión de tokens en el motor para clientes byok, perfiles de optimización por scope (tenant/grupo/cliente, perfiles developer sin fricción), ahorro medible en presupuesto y auditoría, y ruteo coste-consciente a modelos más baratos con guardia de calidad"

## Contexto

La spec 012 ("Ahorro de Costes IA", heredada de gatelite) entregó un compresor determinista seguro,
calculadora de decisión, ahorro neto en presupuesto y telemetría — pero **solo en el path legacy del
panel** (`chat.py`, capa 1.5). Desde 014/019, el tráfico real de la organización entra por la **puerta
única del firewall** (gateway + motor), y en ese plano **hoy no se optimiza nada**:

- La cascada `compression_mode` (key > group > tenant) **ya se resuelve** en la identidad del motor
  (custom_auth la incluye en el contexto de cada request), pero **ningún componente la consume**: el
  enchufe está puesto, sin nada conectado.
- Una organización que conecta Copilot, Cursor o cualquier herramienta byok paga el 100% de los tokens,
  aunque su tenant tenga la compresión activada en el panel.
- El "ruteo" hoy es estático: el cliente pide un modelo y ese modelo responde; no existe la opción de
  servir un modelo más barato equivalente cuando el perfil del equipo lo permite.

Esta spec **generaliza** la 012 al plano firewall — no la reescribe. La promesa de producto (ahorro
medible por equipo, sin romper flujos de trabajo) pasa a aplicar donde está el volumen real de tokens.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Compresión de tokens en el plano byok (Priority: P1)

Como administrador de un tenant con equipos que usan herramientas byok (Copilot, Cursor, tools con
base URL), quiero que las peticiones que pasan por el firewall se compriman según la configuración de
mi organización, para que el ahorro de costes aplique al tráfico real y no solo al playground del panel.

**Why this priority**: es el corazón de la spec y el gap más caro — todo el tráfico byok paga tokens
completos hoy. La cascada de configuración ya llega al motor; falta el consumidor. Entrega valor medible
por sí sola.

**Independent Test**: con compresión activa para un grupo, una petición byok de ese grupo con contenido
estructurado grande llega al proveedor LLM con menos tokens que los enviados por el cliente, con
placeholders PII, URLs, código y markdown intactos; una petición de un grupo con compresión inactiva
pasa byte a byte igual.

**Acceptance Scenarios**:

1. **Given** un grupo con compresión activa y umbral configurado, **When** una petición byok de ese
   grupo supera el umbral, **Then** el prompt enviado al proveedor está comprimido y la respuesta al
   cliente no se ve afectada.
2. **Given** una petición cuyo contenido incluye placeholders de enmascaramiento (`[PII_N]`), URLs,
   bloques de código y markdown, **When** se comprime, **Then** todos esos elementos se preservan
   íntegros (los placeholders son atómicos: la restauración posterior nunca falla por la compresión).
3. **Given** una petición por debajo del umbral, **When** se procesa, **Then** no se comprime y el
   contenido pasa intacto (`tokens_saved=0`).
4. **Given** compresión inactiva para el scope resuelto, **When** se procesa una petición, **Then** el
   contenido pasa byte a byte sin alteración.
5. **Given** un fallo interno del compresor, **When** se procesa una petición, **Then** la petición
   continúa con el contenido original (fail-open para optimización: ahorrar nunca rompe el servicio).
6. **Given** una petición con tool-calling (definiciones de herramientas, resultados de tools),
   **When** se comprime, **Then** las estructuras de tool-calling no se alteran (solo se comprime el
   contenido conversacional/documental).

---

### User Story 2 - Perfiles de optimización por scope, sin fricción para developers (Priority: P1)

Como administrador, quiero configurar la optimización como un **perfil por scope** (tenant, grupo,
cliente/key) con estrategia, umbral y agresividad — y que los equipos de desarrollo tengan por defecto
un perfil que no toque sus prompts — para ahorrar donde conviene sin generar fricción donde no.

**Why this priority**: sin control por scope la compresión es un interruptor global peligroso: lo que
ahorra en un equipo de marketing rompe el flujo de un developer (código, diffs, tool-calling). La
decisión de la reunión de equipo fue explícita: optimización personalizable por usuario/equipo.

**Independent Test**: configuro perfil agresivo para el grupo "Marketing" y perfil developer (off) para
el grupo "Ingeniería"; una misma petición grande se comprime viniendo de Marketing y pasa intacta
viniendo de Ingeniería; un override a nivel de key gana sobre el grupo.

**Acceptance Scenarios**:

1. **Given** perfiles distintos en dos grupos del mismo tenant, **When** cada grupo envía peticiones,
   **Then** cada petición se optimiza según el perfil resuelto de su scope (key > grupo > tenant).
2. **Given** una herramienta de coding identificada por el firewall (client_type de coding tool),
   **When** no hay perfil explícito, **Then** el default efectivo es no alterar el prompt (perfil
   developer: compresión off).
3. **Given** un cambio de perfil desde el panel, **When** se guarda, **Then** aplica a la siguiente
   petición sin reiniciar servicios.
4. **Given** un perfil con estrategia y umbral, **When** el administrador lo consulta en el panel,
   **Then** ve la configuración efectiva resuelta por scope (qué aplica y de dónde viene: key, grupo
   o tenant).

---

### User Story 3 - Ahorro medible en presupuesto y auditoría del firewall (Priority: P2)

Como administrador/DPO, quiero que el ahorro de cada petición optimizada en el plano firewall quede
registrado (metadata-only) y que el presupuesto descuente los tokens netos enviados, para que la
optimización se traduzca en coste real visible por tenant, grupo y modelo.

**Why this priority**: sin medición la compresión es cosmética — cierra el lazo comprimir → ahorrar →
verlo en presupuesto y KPI. Depende de US1.

**Independent Test**: una petición byok de 2000 tokens comprimida a 1200 registra `tokens_saved=800`
y su equivalente en USD en la auditoría del motor; el presupuesto descuenta 1200; el KPI de ahorro
acumulado del tenant sube.

**Acceptance Scenarios**:

1. **Given** una petición comprimida, **When** se completa, **Then** la auditoría del motor registra
   tokens ahorrados y coste ahorrado como metadata (nunca contenido), junto al scope que originó el perfil.
2. **Given** la misma petición, **When** se descuenta presupuesto, **Then** se descuentan los tokens
   netos enviados, respetando la lógica de doble capa existente (personal → grupo).
3. **Given** peticiones optimizadas en el plano firewall y en el path del panel, **When** se consulta
   el KPI "Ahorro de Costes IA", **Then** ambos orígenes suman en el acumulado, desglosables por plano.
4. **Given** streaming, **When** los tokens reales se conocen al final de la respuesta, **Then** el
   ajuste neto se aplica post-respuesta sin bloquear el stream.

---

### User Story 4 - Ruteo coste-consciente con guardia de calidad (Priority: P3)

Como administrador, quiero definir reglas de equivalencia de modelos por perfil (p.ej. "para este grupo,
las peticiones a modelo premium pueden servirse con el modelo estándar equivalente"), para capturar el
ahorro de ruteo sin sorpresas: siempre opt-in, siempre auditado, nunca silencioso.

**Why this priority**: es la segunda palanca de ahorro (la primera es comprimir), pero requiere confianza
en la medición (US3) y control por scope (US2) antes de activarse. El riesgo de degradar calidad exige
guardia y transparencia.

**Independent Test**: con una regla de equivalencia activa para un grupo, una petición a un modelo caro
se sirve con el modelo barato designado; la auditoría registra modelo solicitado vs servido; con la regla
inactiva, la petición va al modelo solicitado.

**Acceptance Scenarios**:

1. **Given** una regla de equivalencia activa en el perfil del grupo, **When** llega una petición al
   modelo caro, **Then** se sirve con el modelo designado y la auditoría registra ambos modelos
   (solicitado y servido) y el ahorro estimado.
2. **Given** ruteo coste-consciente inactivo (default), **When** llega cualquier petición, **Then** se
   sirve exactamente el modelo solicitado.
3. **Given** una respuesta anómala del modelo barato (vacía o degradada según la guardia de calidad),
   **When** se detecta, **Then** se reintenta con el modelo original y el evento queda registrado.
4. **Given** reintentos repetidos por degradación en una regla, **When** superan un umbral, **Then** el
   sistema lo señala al administrador (sugerencia de revisar o desactivar la regla).

---

### Edge Cases

- **Placeholders adyacentes**: la compresión nunca fusiona ni recorta placeholders `[PII_N]` — son
  tokens atómicos; si el algoritmo no puede garantizarlo en un segmento, ese segmento pasa intacto.
- **Petición multimodal o con adjuntos**: solo se optimiza contenido textual; bloques no-texto pasan intactos.
- **Perfil resuelto en conflicto** (key dice on, grupo dice off): gana el scope más específico (key),
  consistente con la cascada existente.
- **Modelo sin tarifa conocida**: el ahorro se registra en tokens; el USD queda vacío (no se inventa tarifa).
- **Doble optimización**: una petición nunca se comprime dos veces (si el path legacy del panel ya
  comprimió, el plano firewall lo detecta por marca de la petición y no re-comprime).
- **Ruteo + modelos con capacidades distintas**: si la petición usa capacidades que el modelo barato no
  soporta (p.ej. tool-calling), la regla de equivalencia no aplica y se sirve el modelo solicitado.
- **Fallo del proveedor tras ruteo**: los reintentos/fallbacks existentes aplican sobre el modelo servido;
  la auditoría refleja la cadena real.
- **Plano passthrough**: fuera de alcance por diseño (ver Assumptions) — el firewall no altera el body
  de suscripción más allá de la política de seguridad.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El sistema MUST aplicar compresión de tokens a las peticiones del plano byok cuando el
  perfil de optimización resuelto para el scope de la petición la active, y MUST dejar el contenido
  byte a byte intacto cuando no.
- **FR-002**: La compresión MUST ejecutarse después del enmascaramiento PII/PHI y antes del envío al
  proveedor, tratando los placeholders de enmascaramiento como unidades atómicas inalterables.
- **FR-003**: La compresión MUST preservar URLs, bloques de código, estructura markdown y estructuras
  de tool-calling (definiciones y resultados de herramientas no se comprimen).
- **FR-004**: El sistema MUST aplicar un umbral mínimo de tamaño por perfil: por debajo, la petición
  pasa intacta con ahorro cero.
- **FR-005**: La optimización MUST ser fail-open: cualquier fallo del optimizador (compresión o ruteo)
  deja pasar la petición original sin error para el usuario, registrando el fallo para diagnóstico.
- **FR-006**: El sistema MUST resolver el perfil de optimización en cascada key > grupo > tenant,
  reutilizando la resolución de identidad existente del motor (la cascada ya viaja en el contexto de
  cada petición).
- **FR-007**: El perfil de optimización MUST incluir al menos: estrategia (off/determinista), umbral,
  agresividad y reglas de ruteo coste-consciente; MUST ser administrable desde el panel como
  config-as-data (sin despliegue ni reinicio).
- **FR-008**: Para clientes identificados como herramientas de coding, el default efectivo sin perfil
  explícito MUST ser no alterar el prompt (perfil developer).
- **FR-009**: El sistema MUST registrar por petición optimizada, como metadata de auditoría (nunca
  contenido): tokens ahorrados, coste ahorrado (si hay tarifa conocida), scope del perfil aplicado y,
  si hubo ruteo, modelo solicitado y modelo servido.
- **FR-010**: El presupuesto MUST descontarse por los tokens netos enviados tras la optimización,
  respetando la lógica de descuento de doble capa existente (personal → grupo).
- **FR-011**: El KPI de ahorro acumulado MUST agregarse por tenant, grupo, modelo y período, sumando
  el plano firewall y el path del panel, con desglose por origen.
- **FR-012**: El ruteo coste-consciente MUST ser opt-in por perfil mediante reglas de equivalencia de
  modelos definidas por el administrador; MUST NOT existir sustitución de modelo autónoma o silenciosa.
- **FR-013**: Toda petición ruteada MUST quedar auditada con modelo solicitado vs servido; la guardia
  de calidad MUST reintentar con el modelo original ante respuesta anómala y registrar el evento.
- **FR-014**: Una petición MUST NOT comprimirse más de una vez a través de los distintos planos
  (panel legacy y firewall).

### Key Entities

- **OptimizationProfile**: configuración de optimización por scope (tenant/grupo/key). Atributos:
  estrategia, umbral, agresividad, reglas de ruteo (lista de equivalencias modelo→modelo), activo.
  Reemplaza/extiende el flag booleano `compression_mode` actual manteniendo compatibilidad con la
  cascada existente.
- **Registro de ahorro (metadata de auditoría)**: tokens ahorrados, coste ahorrado, scope aplicado,
  plano de origen (panel/firewall), modelo solicitado/servido si hubo ruteo. Nunca contiene contenido
  de prompts (constitución: metadata-only).
- **Regla de equivalencia de modelos**: par (modelo solicitado → modelo servido) + condiciones de
  aplicabilidad (capacidades requeridas) + estado, definida dentro del perfil.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Una petición byok con contenido estructurado por encima del umbral se reduce al menos un
  20% en tokens sin corromper ningún placeholder, URL, bloque de código ni estructura de tool-calling
  (suite de contrato con casos de los 12 bugs históricos de la 012 en verde).
- **SC-002**: Con perfil developer (default de coding tools), el 100% de las peticiones pasa byte a
  byte intacto: cero regresiones en los tests de tool-calling y superficies de la 019.
- **SC-003**: El ahorro acumulado (tokens y USD) es visible por tenant/grupo/modelo/período y el
  presupuesto descuenta neto: para cualquier petición comprimida, `descuento = tokens netos`,
  verificable en auditoría.
- **SC-004**: La decisión de optimización (perfil resuelto + umbral) añade una latencia imperceptible
  para el usuario en peticiones no optimizadas (p95 del overhead de decisión < 50 ms).
- **SC-005**: El 100% de las peticiones con ruteo coste-consciente registra modelo solicitado vs
  servido en auditoría; cero sustituciones de modelo sin regla explícita activa.
- **SC-006**: Cero peticiones fallidas atribuibles al optimizador en la suite E2E (fail-open verificado
  con fallo inyectado).

## Assumptions

- **El plano passthrough (suscripción) queda fuera de alcance por diseño**: el coste de suscripción es
  fijo (comprimir no ahorra dinero y añade riesgo) y el contrato de ese plano es reenviar el body
  verbatim salvo política de seguridad. La optimización aplica al plano byok, donde cada token cuesta.
- **La 012 es la base, no se reescribe**: el compresor determinista seguro, la calculadora de decisión
  y el KPI existen y quedan válidos en el path del panel; esta spec los generaliza al plano firewall.
  La estrategia LLM-asistida de la 012 (US5) no se porta en esta spec (evaluable a futuro sobre la
  medición que esta spec habilita).
- **La cascada ya existe**: la identidad del motor ya resuelve `compression_mode` key > grupo > tenant;
  el perfil rico la extiende sin romper compatibilidad (un booleano existente se interpreta como
  estrategia off/determinista con defaults).
- **Coordinación con la spec 015 (SecurityPolicy scoped)**: ambas usan resolución por scope. Si la 015
  aterriza primero, el perfil de optimización sigue su mismo patrón de resolución; si no, esta spec no
  la bloquea (usa la cascada ya presente en la identidad del motor). Tocan archivos comunes del motor:
  coordinar orden de merge entre módulos (seguridad ↔ costes).
- **Presupuestos y KPI existentes se reutilizan** (specs 011/012): mismo modelo de descuento neto y
  mismo KPI, extendidos con el origen "firewall".
- **White-label**: ningún nombre de tercero (librerías, modelos compresores) se expone en UI ni exports
  (constitución, principio config-as-data / never fork).
- **Multi-tenant**: los perfiles viven bajo el modelo 013 (tenant → grupo → cliente/key) con RLS; un
  tenant nunca ve ni hereda perfiles de otro.
