# Feature Specification: Real NLP Masking & Entity Detection Hardening

**Feature Branch**: `016-real-nlp-masking`

**Created**: 2026-07-17

**Status**: Draft

**Input**: User description: "Real NLP entity detection and masking hardening: activate Presidio (or equivalent NLP) for PII/PHI detection replacing regex-only, connect SecurityPolicy entity_configs (per-entity MASK/BLOCK) to the live firewall path (spec 014 BasaGuardrail), and harden PERSON detection to not depend on title prefixes, fixing overlapping-match corruption risk in the masking engine"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Detección real de nombres sin prefijo (Priority: P1)

Un cliente/persona usa una herramienta conectada al firewall (Claude Code, Copilot, extensión browser) y en el curso normal de la conversación menciona el nombre de un paciente, colega o tercero sin anteponer un título ("Juan Pérez tiene turno el jueves", no "el paciente Juan Pérez..."). Hoy ese nombre **no se detecta ni se enmascara** — llega crudo al modelo. Esta historia cierra ese agujero: el sistema detecta nombres de persona en texto conversacional natural, con o sin prefijo, usando NLP real en vez de regex de prefijo fijo.

**Why this priority**: Es el gap de detección más grave del sistema hoy — la mayoría del texto real en salud no trae los prefijos que el regex exige, así que hoy la protección de PERSON es prácticamente inexistente en producción.

**Independent Test**: Enviar un prompt con un nombre de persona sin prefijo título a través del firewall y verificar que (a) el LLM upstream recibe un placeholder, no el nombre real, y (b) la respuesta al usuario final muestra el nombre real restaurado.

**Acceptance Scenarios**:

1. **Given** el firewall activo con masking habilitado, **When** un usuario envía "Juan Pérez tiene turno el jueves a las 10", **Then** el motor/LLM recibe el texto con el nombre reemplazado por un placeholder reversible, y la respuesta final que ve el usuario contiene "Juan Pérez" restaurado.
2. **Given** el mismo escenario, **When** el nombre aparece más de una vez en el mismo prompt, **Then** todas las apariciones del mismo nombre reciben el mismo placeholder (consistencia dentro del request).
3. **Given** un prompt sin ningún nombre de persona, **When** se procesa, **Then** no se generan placeholders de tipo PERSON (sin falsos positivos que degraden la respuesta).

---

### User Story 2 - Enforcement real de la política por tipo de entidad (Priority: P1)

Un compliance officer configura en el panel qué hacer con cada tipo de entidad detectada (por ejemplo: `PERSON: MASK`, `CREDIT_CARD: BLOCK`, `MEDICAL_RECORD_NUMBER: BLOCK`). Hoy esa configuración se guarda pero el firewall real que procesa el tráfico de las herramientas conectadas la **ignora por completo** — solo enmascara con una lista fija de tipos, sin distinguir MASK de BLOCK. Esta historia hace que la configuración del panel gobierne de verdad lo que pasa por el firewall.

**Why this priority**: Sin esto, la política de seguridad que un compliance officer cree en el panel es cosmética — dar una falsa sensación de control es peor que no tener el panel. Es P1 junto con la historia 1 porque ambas son precondición para poder decir "la política enmascara/bloquea lo que dice enmascarar/bloquear".

**Independent Test**: Configurar una entidad como `BLOCK` en la política activa, enviar una request que la contenga a través del firewall, y verificar que la request se rechaza con un motivo claro (no que se enmascare silenciosamente ni que pase intacta).

**Acceptance Scenarios**:

1. **Given** una política activa con `CREDIT_CARD: BLOCK`, **When** una request al firewall contiene un número de tarjeta, **Then** la request se rechaza antes de llegar al LLM, con un motivo auditable.
2. **Given** una política activa con `PERSON: MASK`, **When** una request contiene un nombre, **Then** la request se enmascara y sigue su curso normal (no se rechaza).
3. **Given** una política activa que NO incluye un tipo de entidad en `entity_configs`, **When** ese tipo se detecta, **Then** el sistema aplica un comportamiento por defecto documentado y consistente (no falla ni lo ignora silenciosamente).
4. **Given** una entidad configurada como `BLOCK`, **When** se rechaza la request, **Then** el registro de auditoría refleja el motivo (tipo de entidad, veredicto) sin persistir el valor real de la entidad (metadata-only, Constraint C1).

---

### User Story 3 - Detección NLP real en vez de solo-regex (Priority: P2)

Hoy toda la detección de entidades (en ambos caminos del código, panel legacy y firewall) es regex puro. La constitución (Principio I, Constraint SC-2) exige NLP real (tipo Presidio) como precondición para producción con PHI — el regex es aceptable solo en demo/dev. Esta historia activa un motor de detección NLP real, con formatos estructurados propios de cada región (p.ej. NIF/NIE en España) resueltos por reconocedores dedicados — built-in del motor NLP cuando existen, o un patrón propio inyectado por request cuando no (p.ej. DNI/CUIL en LATAM) — nunca por el regex genérico de dev/demo.

**Why this priority**: Es el requisito de "producción real" del producto, pero puede entregar valor después de que la 1 y la 2 ya resuelvan los gaps más urgentes de cobertura y enforcement con lo que haya disponible ese día (aunque sea regex mejorado).

**Independent Test**: Con el motor NLP real habilitado, enviar prompts con entidades que el regex actual no detecta (nombres sin prefijo, variantes ortográficas, entidades en otros formatos) y verificar que se detectan y enmascaran correctamente.

**Acceptance Scenarios**:

1. **Given** el motor NLP real configurado y disponible, **When** llega una request con PII/PHI, **Then** la detección usa el motor NLP (no el regex) como fuente primaria.
2. **Given** el motor NLP real configurado pero **no disponible** (caído/timeout), **When** llega una request, **Then** el sistema rechaza la request (fail-closed) en vez de degradar silenciosamente a un regex sin garantías — la ausencia de detección confiable nunca se traduce en "dejar pasar sin protección".
3. **Given** entidades de formato estructurado propias de la región activa (p.ej. NIF/NIE en España, DNI/CUIL en un despliegue LATAM), **When** se procesa el texto, **Then** se siguen detectando con la misma o mejor precisión que el regex que reemplazan — vía reconocedor NLP nativo si existe, o patrón dedicado inyectado al motor si no.

---

### User Story 4 - Integridad del texto enmascarado ante coincidencias solapadas (Priority: P2)

Hoy, si dos patrones de detección matchean fragmentos de texto que se superponen (por ejemplo, un número que califica simultáneamente como teléfono y como parte de un IBAN, o cualquier par de reconocedores compitiendo por el mismo tramo de dígitos), el reemplazo puede corromper el texto resultante porque no hay deduplicación de rangos antes de sustituir. Esta historia asegura que el texto enmascarado sea siempre válido y legible, sin importar cuántas entidades detectadas se superpongan — independientemente de qué tipos de entidad estén involucrados.

**Why this priority**: Es un bug de integridad de datos con probabilidad baja-media pero impacto alto (rompe la conversación del usuario o corrompe silenciosamente lo que ve el LLM) — no bloquea el uso normal del sistema hoy, así que puede ir después de las historias de cobertura/enforcement.

**Independent Test**: Construir un texto sintético con dos patrones de entidad que se solapen intencionalmente y verificar que el resultado enmascarado es texto válido, con el placeholder de mayor confianza/especificidad ganando el rango disputado, y que el mapa de reversión permite reconstruir el original sin pérdida.

**Acceptance Scenarios**:

1. **Given** un texto con dos entidades detectadas cuyos rangos se solapan, **When** se enmascara, **Then** el resultado es un texto bien formado (sin placeholders truncados o anidados) con exactamente un placeholder cubriendo el rango disputado.
2. **Given** ese mismo caso, **When** se desenmascara la respuesta del LLM, **Then** se recupera el valor original correcto para el rango que ganó la resolución de solapamiento.

---

### User Story 5 - Catálogo de entidades custom con asistente de IA (Priority: P2)

Un compliance officer quiere sumar un tipo de dato estructurado que la detección de fábrica no cubre
(p.ej. "número de historia clínica de un hospital específico") sin esperar un deploy. Describe en
lenguaje natural qué quiere detectar; un asistente de IA redacta un borrador (patrón + palabras de
contexto + casos de prueba); el compliance officer revisa el borrador y decide activarlo — recién ahí
empieza a aplicarse en el firewall real, igual que cualquier patrón estructurado de fábrica.

**Why this priority**: Extiende la cobertura de "todo lo que no cumpla GDPR" (pedido original de esta
spec) más allá de lo que el equipo pudo anticipar de antemano, sin convertir cada caso nuevo en una
tarea de desarrollo — pero llega después de que la detección/enforcement de base (US1/US2) ya funcionan,
porque el catálogo custom se apoya en esa misma tubería.

**Independent Test**: Crear una entidad custom con un patrón conocido, confirmar que el firewall real la
detecta y enmascara; confirmar que un borrador de IA con un patrón inseguro (ReDoS) nunca llega a
activarse, ni siquiera si el borrador "parece" pasar una revisión superficial.

**Acceptance Scenarios**:

1. **Given** una descripción en lenguaje natural de un dato a detectar, **When** se pide un borrador al
   asistente de IA, **Then** se devuelve un patrón + contexto + casos de prueba, **sin que nada se active
   todavía** — ninguna request de tráfico real lo ve hasta la confirmación explícita siguiente.
2. **Given** un borrador (de IA o tipeado a mano) con un patrón catastróficamente lento (ReDoS), **When**
   se intenta activarlo, **Then** el sistema lo rechaza con un motivo claro, sin excepción por venir de la
   IA ni por "ya haber pasado" una revisión anterior — se re-valida siempre antes de persistir.
3. **Given** una entidad custom activada, **When** llega tráfico real que la contiene, **Then** se detecta
   y enmascara igual que cualquier entidad de fábrica de la región activa (mismo mecanismo, no uno paralelo).
4. **Given** dos entidades custom activas con el mismo tipo declarado, **When** ambas están vigentes,
   **Then** el sistema debe evitar que una haga sombra silenciosa a la otra (o impedir la duplicación al
   crearlas, o garantizar que ambas se apliquen) — nunca una activación fantasma sin aviso.

### Edge Cases

- ¿Qué pasa cuando el mismo nombre de persona coincide con una palabra común del lenguaje (falso positivo NLP)? → Debe poder revisarse en auditoría (metadata: tipo + score) sin exponer el valor real.
- ¿Qué pasa cuando el texto supera el largo máximo que el detector NLP puede analizar en el timeout aceptable? → Se documenta como límite conocido; la request no debe colgarse indefinidamente (timeout explícito + fail-closed, ver US3 escenario 2).
- ¿Qué pasa con una entidad detectada que no tiene acción configurada en la política activa ni existe como tipo conocido? → Ver US2 escenario 3 (default documentado, nunca ignorado silenciosamente).
- ¿Qué pasa si la misma entidad aparece en `system` prompt o en mensajes `assistant` (fuera del alcance actual de escaneo, que es solo turnos `user`)? → Se mantiene el alcance actual (solo `user`) como decisión explícita documentada, no como omisión accidental (ver Assumptions).
- ¿Qué pasa durante streaming si un placeholder queda partido entre dos entidades solapadas cuyo ganador cambia el largo del placeholder? → El mecanismo de carry-split existente debe seguir siendo válido tras resolver el solapamiento antes del streaming (la resolución ocurre en el mapeo, no en el stream).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El sistema DEBE detectar entidades de tipo `PERSON` en texto conversacional sin requerir un prefijo/título fijo (paciente, doctor, sr., etc.) como condición de detección.
- **FR-002**: El sistema DEBE usar un motor de detección NLP real (no solo expresiones regulares) como fuente primaria de detección de entidades PII/PHI en el camino del firewall que procesa tráfico real de las herramientas conectadas.
- **FR-003**: El sistema DEBE seguir detectando correctamente los formatos estructurados propios de la región activa del despliegue (p.ej. NIF/NIE en España; DNI/CUIL en un despliegue LATAM) con precisión igual o mejor a la actual, combinando el motor NLP (reconocedores nativos cuando el motor los provee) con reglas de formato estructurado inyectadas cuando no.
- **FR-004**: Cuando el motor de detección NLP real no está disponible (error, timeout), el sistema DEBE rechazar la request (fail-closed) en vez de procesarla con una detección degradada sin garantías equivalentes.
- **FR-005**: El firewall (camino de tráfico real, spec 014) DEBE resolver la acción (`MASK` / `BLOCK`) configurada en la política de seguridad activa para cada tipo de entidad detectado, en vez de aplicar un enmascaramiento uniforme fijo.
- **FR-006**: Cuando una entidad detectada tiene acción `BLOCK` en la política activa, el sistema DEBE rechazar la request antes de que llegue al LLM upstream, con un motivo auditable que identifique el/los tipo(s) de entidad que causaron el bloqueo.
- **FR-007**: Cuando una entidad detectada tiene acción `MASK` en la política activa, el sistema DEBE enmascararla de forma reversible y continuar procesando la request normalmente.
- **FR-008**: El sistema DEBE definir y aplicar un comportamiento por defecto documentado para tipos de entidad detectados que no están explícitamemte configurados en `entity_configs` de la política activa.
- **FR-009**: El sistema DEBE resolver de forma determinística las coincidencias de detección cuyos rangos de texto se solapan, produciendo siempre un único reemplazo válido por rango disputado (nunca una sustitución que corrompa el texto resultante).
- **FR-010**: El mapa de reversión (placeholder → valor original) DEBE seguir permitiendo reconstruir exactamente el valor original tras la resolución de solapamientos, incluyendo sobre respuestas en streaming (reutilizando el mecanismo de carry-split existente).
- **FR-011**: El sistema DEBE mantener el registro de auditoría metadata-only (tipo de entidad, acción aplicada, score/confianza) sin persistir jamás el valor real de la entidad detectada, para las nuevas rutas de bloqueo introducidas por esta feature (Constraint C1).
- **FR-012**: El comportamiento de detección y enforcement DEBE ser consistente entre el camino de tráfico real del firewall (spec 014) y cualquier vista de previsualización/playground que exponga el mismo pipeline, evitando que ambos caminos diverjan silenciosamente en qué detectan (cerrando el patrón de duplicación regex actual).
- **FR-013**: El sistema DEBE permitir crear entidades de detección custom (patrón + palabras de contexto) sin requerir un deploy de código, persistidas junto a la configuración de detección existente.
- **FR-014**: El sistema PUEDE ofrecer un asistente que redacte un borrador de entidad custom a partir de una descripción en lenguaje natural, pero ese borrador NUNCA DEBE activarse automáticamente — activar una entidad (que empiece a aplicarse sobre tráfico real) requiere una acción explícita separada, posterior a la generación del borrador.
- **FR-015**: El sistema DEBE validar la seguridad de todo patrón antes de activarlo (compila, no es catastróficamente lento contra entradas adversariales) sin excepción según su origen (generado por IA o tipeado a mano) ni según intentos previos de validación.
- **FR-016**: El sistema DEBE evitar que dos entidades custom activas con el mismo tipo declarado se sombreen silenciosamente entre sí sin que quede evidencia de cuál aplica realmente.
- **FR-017**: El sistema DEBE sanitizar o rechazar identificadores de tipo de entidad custom que puedan interferir con el formato interno de los marcadores reversibles usados por el mecanismo de enmascaramiento.

### Key Entities *(include if feature involves data)*

- **SecurityPolicy / entity_configs**: configuración existente que mapea tipo de entidad → acción (`MASK`/`BLOCK`). Pasa de ser informativa a ser la fuente de verdad que el firewall real consulta por cada entidad detectada.
- **Detected Entity**: una ocurrencia de PII/PHI encontrada en un texto — tipo, rango de posición, score de confianza, y el motor que la detectó (NLP vs regla estructurada). Es efímera (vive solo en memoria del request), nunca se persiste con su valor real.
- **Placeholder Map (mapa reversible)**: asignación valor-original ↔ placeholder por request, ya existente; esta feature la extiende para sobrevivir a la resolución de solapamientos sin perder reversibilidad.
- **Audit Record**: entrada de auditoría metadata-only existente; esta feature agrega las nuevas causas de bloqueo por-entidad como motivo registrable.
- **Custom Entity**: definición de un patrón de detección agregado por un usuario (nombre, tipo, patrón, contexto, región, estado activo/borrador, si fue generado por IA). Vive junto a la configuración de detección del tenant; solo las activas llegan al motor de detección real.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un nombre de persona mencionado en texto conversacional natural (sin título/prefijo) se detecta y enmascara correctamente en al menos el 90% de un set de prueba representativo de frases en español rioplatense de contexto salud/negocios.
- **SC-002**: El 100% de las entidades configuradas como `BLOCK` en la política activa efectivamente detienen la request antes de llegar al LLM upstream, verificado por un set de prueba de contrato.
- **SC-003**: Cero casos, en el set de prueba de regresión, de texto enmascarado corrupto (placeholders truncados, anidados o mal formados) ante entidades con rangos solapados.
- **SC-004**: Cuando el motor de detección NLP real no responde, el 100% de las requests afectadas se rechazan de forma explícita (ninguna se procesa con detección degradada silenciosa).
- **SC-005**: La latencia adicional introducida por la detección NLP real sobre el camino del firewall no degrada la experiencia interactiva de las herramientas soportadas (percibida como respuesta "instantánea" por el usuario, sin timeouts visibles en uso normal).
- **SC-006**: Cero duplicación de listas de patrones/entidades mantenidas a mano en más de un lugar del código tras esta feature (el camino panel/playground y el camino firewall comparten la misma fuente de detección).
- **SC-007**: El 100% de los patrones que fallan la validación de seguridad (no compilan, o exceden el timeout contra entradas adversariales) quedan rechazados y jamás llegan a activarse — verificado por un set de prueba de contrato que incluye patrones catastróficos conocidos.
- **SC-008**: Cero entidades custom activas simultáneamente con el mismo tipo declarado sin que el sistema lo impida o lo señale explícitamente.

## Assumptions

- El alcance de escaneo se mantiene igual al actual: solo contenido de turnos `role=user` (texto y `tool_result`); `system` prompt y mensajes `assistant` quedan fuera de esta feature (documentado como decisión explícita, no reevaluado acá).
- "Motor de detección NLP real" se refiere a una capacidad equivalente a Presidio (analyzer + anonymizer) ya contemplada como scaffolding en el código heredado; esta spec no prescribe una herramienta específica distinta a menos que la investigación de la fase de plan encuentre una alternativa superior.
- La resolución de política sigue siendo sobre la `SecurityPolicy` activa **global** actual (sin cascada por client/group/tenant) — esa cascada es alcance de la spec 015 y esta feature debe construir el wiring de forma que 015 lo extienda sin reescribirlo.
- El fail-closed ante indisponibilidad del motor NLP aplica al camino de tráfico real (firewall); el camino de panel/playground (uso interno, no tráfico de producción hacia herramientas) puede degradar de forma visible al usuario interno sin bloquear, siempre que quede claramente señalado como modo degradado.
- El rendimiento del motor NLP en el request path es aceptable con un despliegue local/containerizado (no una llamada a un servicio SaaS externo de terceros), consistente con la postura de residencia de datos EU y de no delegar la reversibilidad del masking a un tercero (Principio I).
