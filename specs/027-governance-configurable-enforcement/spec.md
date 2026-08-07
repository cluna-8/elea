# Feature Specification: Governance configurable y enforcement honesto del firewall

**Feature Branch**: `027-governance-configurable-enforcement`

**Created**: 2026-07-22

**Status**: Implementada — estado canónico en [`ROADMAP-guardian.md`](../ROADMAP-guardian.md)

**Input**: User description: "Governance configurable y enforcement honesto del firewall: el Admin configura qué capas de gobernanza aplican por modo de conexión (suscripción vs gateway-models) y por superficie/herramienta, con un piso no-negociable siempre activo; la UI muestra el estado REAL de cada guardián en vez de mostrar activos los que no corren; y los guardrails del proveedor se cablean de verdad cuando el Admin los activa"

## Contexto del problema

El mapeo del plano firewall (2026-07-22) encontró que **el catálogo de guardianes que la UI presenta como activos no se corresponde con lo que realmente se ejecuta**:

- El firewall real aplica **tres capas**: enmascarado de PII, bloqueo de secretos y evaluación AI-Act.
- Las capas "de proveedor" que la UI ofrece (moderación de contenido, detección de inyección de prompts, content-safety, guardrails de proveedor cloud) **no se ejecutan en ningún plano**: se declaran "delegadas al motor", pero el motor no tiene ninguna de ellas habilitada.
- **No existe forma de que el cliente configure** qué capas aplican. La decisión está fija en el producto.

Además, **qué capas tienen sentido depende del modo de conexión**: cuando el tráfico viaja contra la suscripción del propio cliente, el proveedor upstream ya aplica sus propias defensas; cuando el tráfico va por **Modelo propio** (incluido un modelo local), **no hay nadie más protegiendo**. Hoy el producto no distingue esos dos mundos.

El valor central del producto es **interceptar y registrar todo el tráfico y evitar que salgan datos sensibles**. Esta feature no cambia ese piso: lo vuelve explícito, lo protege de ser apagado, y hace **honesto y configurable** todo lo que está por encima.

> **Ajuste de alcance sobre el pedido original**: el Input de arriba menciona que "los guardrails del proveedor se cablean de verdad cuando el Admin los activa". Ese cableado **salió del alcance** de esta spec (ver Out of Scope): pertenece al módulo de seguridad y guardianes. 027 entrega el **marco** que declara, configura, aplica y reporta cada capa con honestidad (FR-008); cuando el módulo de seguridad entrega una capa cableada, el marco la toma sin cambios de diseño.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - El Admin ve el estado REAL de cada capa (Priority: P1)

Un administrador abre la vista de gobernanza y ve, para cada capa de protección, **su estado verdadero**: aplicándose, requiere credencial, delegada al proveedor upstream, o no disponible. Ninguna capa aparece como activa si no se ejecuta.

**Why this priority**: Es el problema de confianza más grave y el prerrequisito de todo lo demás — no se puede configurar con criterio lo que se muestra de forma engañosa. Afirmar ante un cliente que una protección está activa cuando no corre es un riesgo de declaración de cumplimiento. Entrega valor por sí sola, sin ninguna capacidad de configuración nueva.

**Independent Test**: Con el cableado actual, la vista debe mostrar las tres capas que sí corren como aplicándose, y todas las capas de proveedor como *no activas / requieren configuración*, sin que haga falta tocar nada más del producto.

**Acceptance Scenarios**:

1. **Given** una capa de proveedor que el producto ofrece pero que no está habilitada en el motor, **When** el Admin abre la vista de gobernanza, **Then** esa capa se muestra como no aplicándose, con el motivo, y nunca como activa.
2. **Given** una capa que sí se ejecuta sobre el tráfico, **When** el Admin abre la vista, **Then** se muestra como aplicándose.
3. **Given** una capa marcada como delegada al proveedor upstream, **When** el Admin la consulta, **Then** el producto explica que la protección la aporta el proveedor y por qué, de modo que "no la aplicamos nosotros" no se confunda con "está desprotegido".
4. **Given** una capa que requiere credenciales y no las tiene configuradas, **When** el Admin consulta su estado, **Then** se reporta como *requiere credencial* y nunca como aplicándose.
5. **Given** una capa habilitada que no logra cargarse o aplicarse en tiempo de ejecución, **When** se consulta su estado, **Then** se reporta como degradada y nunca como activa.

---

### User Story 2 - El Admin configura la gobernanza por modo de conexión y por superficie (Priority: P2)

Un administrador decide qué capas opcionales aplican para el tráfico de **Suscripción** (token `subscription`) y cuáles para el tráfico de **Modelo propio** (token `gateway-models`), y puede afinarlo por **superficie/herramienta** dentro del conjunto de herramientas declaradas que el producto reconoce. El **piso no-negociable** está siempre activo y no puede apagarse.

El afinado por superficie **solo aplica al enum de herramienta declarada** (las herramientas de código y de chat que el producto identifica explícitamente). El tráfico de **navegador** y el de **API genérica** no tienen valor propio de superficie: resuelven **por modo de conexión** (fallback). Ampliar el enum de superficies es alcance del issue **#28**.

**Why this priority**: Es la feature en sí. Permite que cada cliente ajuste la gobernanza a su realidad — contra una suscripción el proveedor ya modera; contra un modelo propio o local no modera nadie — en vez de imponer una decisión única desde el producto.

**Independent Test**: Configurar capas distintas para cada modo (`subscription` vs `gateway-models`), enviar tráfico por ambos, y verificar que las capas aplicadas difieren según lo configurado y que el piso se aplica siempre en los dos casos.

**Acceptance Scenarios**:

1. **Given** una capa opcional habilitada solo para Modelo propio (`gateway-models`), **When** llega tráfico de Suscripción, **Then** esa capa no se aplica y el registro del pedido lo refleja.
2. **Given** la misma capa, **When** llega tráfico de Modelo propio, **Then** la capa se aplica y queda registrada como aplicada.
3. **Given** cualquier configuración posible, **When** el Admin intenta desactivar una capa del piso no-negociable, **Then** el sistema lo rechaza y el piso sigue aplicándose.
4. **Given** configuraciones distintas a nivel modo y a nivel superficie, **When** ambas aplican a un mismo pedido, **Then** el orden de resolución es determinista y el Admin puede verlo.

---

### Edge Cases

- ¿Qué pasa si el Admin activa una capa de proveedor y **no** aporta credencial? Debe quedar visible como *requiere credencial*, jamás como activa, y el tráfico no debe reportarse como protegido por ella.
- ¿Qué pasa si una capa configurada como activa **falla al cargarse** en tiempo de ejecución? Debe reportarse como degradada de forma visible; nunca seguir mostrándose como activa.
- ¿Qué pasa si la configuración de modo y la de superficie **se contradicen** para un mismo pedido? El orden de resolución debe ser determinista y consultable por el Admin.
- ¿Qué pasa cuando el proveedor upstream ya aporta una protección? La capa debe poder marcarse como *delegada*, explicando el motivo, para no confundir "no la aplicamos" con "no hay protección".
- ¿Qué pasa si un pedido se **bloquea** por una capa? Debe quedar registrado qué capa lo bloqueó (atribución), no solo que hubo un bloqueo.
- ¿Qué pasa si un tenant nuevo no configuró nada? Debe recibir un default seguro y explícito, con el piso activo.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El sistema MUST exponer, para cada capa de gobernanza, su estado real de ejecución (aplicándose / requiere credencial / delegada al proveedor / no disponible / degradada), y MUST NOT reportar como activa una capa que no se ejecuta.
- **FR-002**: El sistema MUST definir un **piso no-negociable** —interceptar todo pedido, registrarlo con su atribución, **detectar** datos personales y bloquear secretos— que ninguna configuración pueda desactivar. El **enmascarado** de los datos detectados es una capa gobernable por alcance; cuando está desactivado, el pedido MUST quedar registrado como *"datos personales detectados, no enmascarados por configuración"* — nunca invisible. *(Decisión del owner 2026-07-22: absorbe el toggle de enmascarado de la spec 013 como decisión de la capa, en vez de derogarlo.)*
- **FR-003**: El sistema MUST rechazar cualquier intento de configuración que deje el piso no-negociable desactivado, y MUST registrar el intento.
- **FR-004**: Los administradores MUST poder configurar qué capas opcionales aplican según el **modo de conexión**: **Suscripción** (token `subscription`, tráfico contra la suscripción del cliente) vs **Modelo propio** (token `gateway-models`).
- **FR-005**: Los administradores MUST poder configurar qué capas opcionales aplican según la **superficie/herramienta** del cliente, **limitado al enum de herramientas declaradas que el producto reconoce** (herramientas de código y de chat identificadas explícitamente). El tráfico de **navegador** y el de **API genérica** MUST resolverse **por modo de conexión** (fallback), porque no existe valor de superficie para ellos; el sistema MUST NOT ofrecer configuración por superficie para esos casos. *(Ampliar el enum de superficies es alcance del issue #28.)*
- **FR-006**: El orden de resolución cuando la configuración por modo y por superficie difieren MUST ser determinista y MUST ser consultable por el administrador.
- **FR-007**: Cuando una capa opcional requiere credenciales y no se aportaron, el sistema MUST reportarla como *requiere credencial* y MUST NOT aplicarla ni declararla activa.
- **FR-008**: El marco de gobernanza MUST poder **representar y aplicar capas provistas por el módulo de seguridad**: cuando una capa existe y está habilitada para un alcance, el marco MUST aplicarla a ese tráfico; cuando no existe o no está disponible, MUST reportarlo con honestidad. *(La implementación de cada capa de protección pertenece al módulo de seguridad y guardianes, no a esta feature.)*
- **FR-009**: El sistema MUST registrar, por cada pedido gobernado, **qué capas se aplicaron realmente**, de modo que un bloqueo o marca sea atribuible a la capa que lo produjo.
- **FR-010**: El sistema MUST ofrecer al administrador un resumen por modo de conexión que responda "¿qué protege hoy al tráfico de Suscripción y qué al de Modelo propio?".
- **FR-011**: La configuración de gobernanza MUST ser accesible como una sección propia del producto y MUST estar restringida a roles administrativos.
- **FR-012**: Los cambios de configuración de gobernanza MUST poder aplicarse desde el producto, sin que el operador edite archivos de configuración a mano.
- **FR-013**: Para capas delegadas al proveedor upstream, el sistema MUST explicar el motivo de la delegación, de forma que "no la aplicamos nosotros" no se confunda con "no hay protección".
- **FR-014**: Si una capa configurada como activa no logra cargarse o aplicarse en tiempo de ejecución, el sistema MUST reportarla como degradada de forma visible y MUST NOT continuar reportándola como activa.
- **FR-015**: La configuración de gobernanza MUST resolverse por tenant, de modo que cada cliente pueda tener una postura distinta sobre la misma base de producto.

### Key Entities

- **Capa de gobernanza**: una protección concreta que puede aplicarse al tráfico (enmascarado de datos personales, bloqueo de secretos, evaluación de cumplimiento, moderación de contenido, detección de inyección de prompts, content-safety). Atributos: si pertenece al piso o es opcional, si requiere credenciales, y su estado real de ejecución.
- **Perfil de gobernanza**: el conjunto de decisiones sobre capas que aplica a un alcance determinado.
- **Modo de conexión**: distingue **Suscripción** (token `subscription`, tráfico contra la suscripción del propio cliente) de **Modelo propio** (token `gateway-models`).
- **Superficie/herramienta**: el tipo de cliente que origina el tráfico. **Configurable solo para el enum cerrado de herramientas declaradas** que el producto reconoce (herramientas de código y de chat). **Navegador** y **API genérica** no son valores de este enum: su tráfico resuelve por **modo de conexión** (fallback). Ampliar el enum es alcance del issue **#28**.
- **Registro de gobernanza aplicada**: por cada pedido, qué capas se aplicaron efectivamente y cuál produjo un bloqueo o marca, si hubo.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: **Cero** capas reportadas como activas que no se ejecutan: el 100% de las capas que el producto muestra reflejan su estado real, verificable de forma automatizada.
- **SC-002**: Un administrador puede responder "¿qué protege hoy al tráfico de Suscripción y qué al de Modelo propio?" desde una sola vista, en menos de 1 minuto, sin leer código ni archivos de configuración.
- **SC-003**: El 100% de las capas **disponibles y habilitadas** para un alcance se aplican al tráfico de ese alcance, y el 100% de las **no disponibles** se reportan como tales — sin ningún caso ambiguo entre "no la aplicamos" y "no está protegido".
- **SC-004**: Ningún camino de configuración permite dejar el piso no-negociable desactivado: el 100% de los intentos se rechazan y quedan registrados.
- **SC-005**: El 100% de los pedidos gobernados tienen registro de qué capas se les aplicaron. Todo bloqueo es **atribuible a una capa concreta en el punto donde ocurre**: la atribución se emite al bloquear y se publica en el monitoreo en vivo, y queda en registro durable **en todos los flujos que alcanzan el registro**. *(Ajuste de Fase 0/1: en los caminos donde hoy el bloqueo interrumpe antes de todo registro, la durabilidad de esa fila es alcance de la spec 018 — este criterio no se marca cumplido sobre esa promesa.)*
- **SC-006**: Un administrador puede cambiar la postura de gobernanza de su organización sin intervención del proveedor y sin editar archivos a mano.
- **SC-007**: Un tenant recién creado queda con el piso activo y una postura por defecto explícita, sin configuración manual previa.

## Assumptions

- **Piso no-negociable**: lo innegociable es **interceptar y registrar todo el tráfico + detectar datos personales + bloquear secretos** (decisión del owner, 2026-07-22, sobre la Fase 0 — ver research D8). El **enmascarado** es la capa gobernable por excelencia: existe tráfico legítimo que lo necesita apagado (herramientas de código, donde enmascarar rompe el código), y su desactivación queda siempre **detectada y registrada**, nunca invisible. Esto absorbe el toggle de enmascarado existente (spec 013, FR-014) como decisión de capa en vez de derogarlo. La **tiering del cumplimiento** (qué evidencia pasa a ser gate duro) NO se redefine acá: es alcance de la spec de niveles de cumplimiento (018).
- **Granularidad**: esta feature configura por **modo de conexión** (`subscription` / `gateway-models`) y por **superficie/herramienta**, esta última **acotada al enum cerrado de herramientas declaradas** que el producto reconoce; navegador y API genérica resuelven por modo (fallback) y su incorporación como superficies propias es alcance del issue **#28**. La granularidad **por grupo y por cliente** se apoyará en el mecanismo de resolución en cascada que define la spec 015; esta spec no lo reimplementa y se integrará con él cuando exista.
- Se asume que las capas de proveedor disponibles son las que el motor de la instancia ya sabe operar; esta feature las habilita y las hace visibles, no incorpora proveedores nuevos.
- Se asume que la configuración es **dato por tenant** (config + seed), coherente con la regla de nunca bifurcar el producto por cliente.
- Se asume que la vista de gobernanza es para roles administrativos; los usuarios finales no la ven ni la modifican.

## Out of Scope

Deliberadamente **fuera de alcance**, por pertenecer a otros módulos/owners:

- **La implementación de las capas de protección en sí** — moderación de contenido, detección de inyección de prompts / anti-jailbreak, content-safety, guardrails de proveedor cloud — → **módulo de seguridad y guardianes**. Esta feature construye el **marco** que las declara, configura, aplica y reporta con honestidad; **no implementa ni cablea ninguna capa**. Cuando el módulo de seguridad entregue una capa, el marco de esta spec la toma sin cambios de diseño.
- **Enmascarado con NLP real** y hardening de detección de entidades → spec **016** ([PR #21](https://github.com/DrZuzzjen/basa-guardian/pull/21), en review).
- **Niveles de enforcement de cumplimiento** (qué evidencia pasa a gate duro, incluido el tratamiento del bloqueo por prácticas prohibidas), **retención de datos y purga**, y la **completitud/confiabilidad de la auditoría** (que los bloqueos queden registrados de forma durable y que el registro no se pierda ante fallos) → spec **018**.
- **Resolución en cascada por grupo/cliente** de políticas → spec **015**. Esta feature configura por modo y por superficie; la granularidad por grupo/usuario se apoyará en ese mecanismo cuando exista.
- **Gobernar la superficie de la API de Responses** (herramientas que solo hablan ese protocolo) → issue **#28**.
