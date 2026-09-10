# Feature Specification: Motor de análisis exacto de datos (DB-GPT) para Eleia Hub

**Feature Branch**: `048-motor-analisis-exacto-dbgpt`

**Created**: 2026-09-10

**Status**: Draft — lista para `/speckit-plan`

**Repos que toca**: `backend/` (contrato de identidad/atribución/presupuesto hacia el motor,
proxy de autenticación) y despliegue (`docker-compose.yml`, `elea-installer/`) — el contenedor
nuevo de DB-GPT. **NO toca `litellm/`** salvo como destino de las llamadas de modelo que DB-GPT
hace **a través de** Eleia (ver FR-004). `client/` (Eleia Hub) consume el contrato que define esta
spec desde el punto de integración que dejó abierto la spec 046 US1/US2 — su UI no es objeto de
esta spec.

**Input**: la spec 046 ("Análisis exacto de datos Excel/CSV en Eleia Hub") dejó explícitamente
deferida "la spec de backend aparte" para el motor en sí — esta es esa spec. Retoma la
investigación cerrada en `specs/RESULTADOS-INVESTIGACION-DOCGEN-DBGPT.md` (Parte 2) y la decisión
explícita del dueño del producto (10-sep-2026): **usar DB-GPT como motor**, no el módulo propio de
DuckDB que la investigación había recomendado — con las mitigaciones de seguridad que esa misma
investigación deja documentadas como condición para usarlo.

## Por qué esta spec existe pese a que la investigación recomendaba lo contrario

`RESULTADOS-INVESTIGACION-DOCGEN-DBGPT.md` (Parte 2) encontró tres problemas reales en DB-GPT:

1. Su escena "Chat Excel" acepta un solo archivo y solo la primera hoja — no cruza archivos.
2. No valida que el SQL generado sea de solo lectura, y manda filas de muestra reales al LLM sin
   pasar por el enmascarado de Eleia.
3. **CVE-2026-80104 (crítica, RCE sin autenticación, ago-2026)** y otros 8 advisories de 2025.

El dueño del producto decidió usar DB-GPT igual, informado de estos hallazgos. Esta spec existe
para que esa decisión no llegue a producción con los mismos riesgos: cada uno de los tres puntos
de arriba se convierte en un requisito obligatorio de esta spec (FR-002, FR-003, FR-006/FR-007).
**No es una spec que reintroduce el riesgo documentado — es la que lo cierra.**

## Diagnóstico (heredado de la spec 046, sin cambios)

El chat RAG (AnythingLLM, ya en producción) responde por similitud semántica sobre fragmentos
indexados — no por cómputo exacto. Preguntas tipo "sumá la columna X para los registros de Y" no
tienen respuesta correcta posible desde un vector store. DB-GPT resuelve esto con texto→SQL sobre
los datos reales de la planilla.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - El motor responde con la identidad y el costo de la persona real, nunca de una cuenta compartida (Priority: P1)

Cuando Eleia Hub reenvía una pregunta de análisis exacto al motor DB-GPT, el motor necesita
resolver el modelo de lenguaje (texto→SQL) llamando a un proveedor — y en Eleia ese proveedor es
siempre el motor interno (LiteLLM) autenticado con una llave de servicio, nunca una credencial de
Azure OpenAI propia de DB-GPT. El gasto de esa llamada queda atribuido a la persona que hizo la
pregunta, exactamente como ya pasa con el chat directo (spec 043 US2) — no al motor, no a una
cuenta de servicio anónima.

**Why this priority**: es la condición para que "usar Eleia para los modelos y el costo" (el
pedido explícito) sea cierto y no una nueva versión del mismo problema que dejó la limitación de
atribución del RAG documental (CHANGELOG 044 §13) — sin esto, DB-GPT es un segundo egreso de
modelo fuera del control de costos del producto, exactamente lo que el producto existe para
evitar.

**Independent Test**: preguntar algo que dispare una llamada de modelo desde DB-GPT (p. ej. "sumá
la columna Monto") y confirmar en Costos → "Gasto por usuario" que el gasto aparece bajo el
usuario real que preguntó, con el modelo real usado (uno de los deployments de Azure ya
configurados en `litellm/config.yaml`), no bajo una cuenta `svc.*` ni con un modelo ajeno al
catálogo de Eleia.

**Acceptance Scenarios**:

1. **Given** una pregunta de análisis exacto de una persona con sesión válida, **When** DB-GPT
   necesita resolver texto→SQL, **Then** la llamada de modelo sale hacia el motor interno de Eleia
   (LiteLLM), nunca hacia un proveedor configurado directamente en DB-GPT.
2. **Given** esa misma pregunta, **When** se completa, **Then** el gasto queda atribuido a la
   persona real en Costos → "Gasto por usuario" (mismo mecanismo que el chat directo — un header
   "en nombre de", análogo a `X-Guardian-Acting-User`, contrato 2 de la 043).
3. **Given** el catálogo de modelos configurado en Eleia (los deployments reales de Azure), **When**
   DB-GPT elige un modelo, **Then** solo puede elegir entre los del catálogo — nunca uno
   hardcodeado propio de DB-GPT ni uno inventado.
4. **Given** el presupuesto de la persona agotado, **When** pregunta algo de análisis exacto,
   **Then** se bloquea con el mismo mensaje neutro que cualquier otra operación de consumo
   (spec 044 US2), antes de que la pregunta llegue a DB-GPT.

---

### User Story 2 - Aislamiento: cada persona solo analiza SUS archivos, cruzados entre sí, nunca los de otra (Priority: P1)

Una persona sube dos planillas a un espacio de análisis exacto del que es dueña o miembro (mismo
modelo de pertenencia que los `Workspace` de la spec 043). Sus preguntas pueden cruzar esas dos
planillas entre sí (join real, no aproximación) pero jamás ven, ni pueden referenciar, archivos
subidos por otra persona en otro espacio — ni por accidente de diseño ni por un prompt que lo
pida.

**Why this priority**: es el aislamiento básico ya exigido en toda la plataforma (spec 043 US1) —
introducir un motor nuevo sin heredarlo sería repetir, en una pieza nueva, el bug crítico del
hilo compartido que ya se encontró y corrigió en el chat RAG (10-sep-2026, ver CHANGELOG 044 §14).
También cierra el problema #1 encontrado en DB-GPT (solo soporta un archivo, sin cruces): acá se
exige lo contrario, cruzar SIN exponer archivos ajenos.

**Independent Test**: dos personas, cada una con su propio espacio de análisis exacto y su propia
planilla; ninguna pregunta de una ve datos de la planilla de la otra, verificado con sesiones
reales (no solo por diseño de la query). Una tercera planilla subida al MISMO espacio por la
misma persona sí se puede cruzar con la primera en una sola pregunta.

**Acceptance Scenarios**:

1. **Given** dos personas con espacios de análisis exacto separados, **When** cualquiera de las
   dos pregunta algo, **Then** la respuesta nunca incluye, cita ni infiere datos de la planilla
   de la otra persona.
2. **Given** dos planillas en el mismo espacio de la misma persona, **When** pregunta algo que
   requiere cruzarlas (join por una columna común), **Then** la respuesta es correcta y usa datos
   de ambas.
3. **Given** un intento de acceso directo por un identificador de planilla ajeno (conocido o
   adivinado), **When** se pide, **Then** se rechaza con 403, sin filtrar si la planilla existe.
4. **Given** el motor DB-GPT en sí, **When** se lo inspecciona desde la red donde corre, **Then**
   NO tiene ningún puerto publicado hacia fuera del backend de Eleia ni hacia internet — solo el
   backend puede alcanzarlo (mitigación obligatoria de CVE-2026-80104, ver FR-006/FR-007).

---

### User Story 3 - El enmascarado vigente sigue aplicando dentro de DB-GPT (Priority: P1)

Los datos personales presentes en una planilla (DNI, nombres, montos asociados a una persona) se
enmascaran ANTES de que DB-GPT los vea, con el mismo mecanismo que ya protege el resto de las
subidas del Hub — no después, no "confiando en que DB-GPT no los expone".

**Why this priority**: cierra el problema #2 encontrado en la investigación (DB-GPT manda 5 filas
de muestra reales al LLM sin enmascarar). Es un requisito de seguridad, no de UX — sin esto, DB-GPT
sería el único camino de la plataforma que filtra PII sin protección al proveedor de modelo.

**Independent Test**: subir una planilla con una columna de DNI/nombre real, preguntar algo que
NO involucre esa columna directamente (p. ej. sumar una columna de montos) y confirmar, por log
de la llamada saliente al motor de Eleia, que ningún valor de la columna protegida viajó en claro
en el prompt ni en la muestra de filas.

**Acceptance Scenarios**:

1. **Given** una planilla con una columna de datos personales, **When** se carga en el espacio de
   análisis exacto, **Then** esa columna pasa por el mismo pipeline de enmascarado que cualquier
   documento subido al Hub (mismo `document_id` determinista de la spec 044 US3 si aplica al
   formato tabular).
2. **Given** una pregunta que involucra directamente la columna protegida ("¿cuál es el DNI de
   Fulano?"), **When** se responde, **Then** se aplica la misma política de desenmascarado vigente
   para esa persona/rol — ni más laxa ni más estricta que en el chat RAG.
3. **Given** el SQL que DB-GPT genera internamente para resolver una pregunta, **When** se
   audita, **Then** el sistema valida que sea de solo lectura (`SELECT`/`WITH`, nunca `INSERT`/
   `UPDATE`/`DELETE`/`DROP`/DDL) antes de ejecutarlo — cierra el problema #2 sobre SQL sin validar.

### Edge Cases

- El motor DB-GPT no responde (caído, timeout): mensaje neutro, sin nombrar la herramienta interna
  (mismo criterio que el resto de la plataforma, spec 044 US5) — bug ya encontrado y corregido en
  el chat RAG cuando AnythingLLM está caído (CHANGELOG 044 §14), este motor nuevo hereda el mismo
  estándar desde el día uno.
- Una pregunta que intenta hacer que el modelo genere SQL de escritura ("borrá la fila donde…"):
  se rechaza en la validación de solo-lectura, con una explicación de que este modo es solo de
  consulta.
- Una planilla cuyo tamaño excede lo que el motor puede cargar en memoria en un tiempo razonable:
  tope documentado, aviso claro, no un cuelgue silencioso ni un OOM del contenedor.
- Un intento de acceder al motor DB-GPT saltando a Eleia Hub (llamada directa a su puerto/IP):
  debe ser técnicamente imposible desde fuera de la red interna del backend — no solo bloqueado
  por una capa de aplicación que se pueda evadir.
- Actualización de versión de la imagen de DB-GPT: sigue el mismo criterio de pin-by-digest que
  el motor LiteLLM (spec 014 T004/FR-026, Principio VI) — nunca `:latest`, bump deliberado con
  prueba, nunca automático.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El sistema MUST desplegar DB-GPT como un contenedor Docker separado (imagen pinneada
  por digest, nunca `:latest`), como parte del `docker-compose.yml` de Eleia y de
  `elea-installer/`.
- **FR-002 (mitiga CVE-2026-80104)**: El contenedor de DB-GPT MUST NOT publicar ningún puerto hacia
  el host ni hacia ninguna red alcanzable desde fuera del backend de Eleia — solo el backend
  (nunca el navegador, nunca `client/`) puede alcanzarlo, en una red Docker interna dedicada.
  Ningún usuario final, autenticado o no, tiene una ruta de red directa hacia DB-GPT.
- **FR-003 (mitiga el hallazgo de SQL sin validar)**: Toda consulta SQL que DB-GPT genere y vaya a
  ejecutar MUST validarse como de solo lectura (allow-list `SELECT`/`WITH`) antes de correr contra
  los datos — una consulta que no pase la validación se rechaza sin ejecutarse, nunca se "sanea".
- **FR-004**: El sistema MUST configurar DB-GPT para resolver sus llamadas de modelo de lenguaje
  EXCLUSIVAMENTE contra el motor interno de Eleia (LiteLLM), autenticado con una llave de servicio
  dedicada — nunca contra una credencial de Azure OpenAI (u otro proveedor) configurada
  directamente en DB-GPT, aunque DB-GPT lo soporte nativamente.
- **FR-005**: El sistema MUST atribuir el costo de cada llamada de modelo que DB-GPT dispare a la
  persona real que hizo la pregunta de análisis exacto — mismo contrato "en nombre de" ya
  implementado para el chat directo y el enmascarado (contrato 2 de la 043,
  `X-Guardian-Acting-User`/`acted_for_user_id`), no a la llave de servicio de DB-GPT.
- **FR-006 (mitiga el hallazgo de PII sin enmascarar)**: Ninguna fila ni valor de una columna
  marcada como dato personal MUST llegar en claro a la llamada de modelo que hace DB-GPT — pasa
  por el mismo pipeline de enmascarado que protege el resto del Hub antes de indexarse en DB-GPT.
- **FR-007**: El acceso a un espacio/planilla de análisis exacto MUST verificarse contra el mismo
  modelo de pertenencia (`Workspace`/`WorkspaceMembership`) de la spec 043 — DB-GPT nunca decide
  por su cuenta quién puede ver qué; el backend de Eleia es la única autoridad de acceso, igual
  que ya es para `client/` (mismo criterio, contrato 1 de la 043).
- **FR-008**: El presupuesto y su enforcement (402) MUST aplicar antes de que una pregunta llegue a
  DB-GPT — mismo criterio ya usado en el chat RAG (FR-006 de la spec 044 US2), no un enforcement
  duplicado ni distinto dentro de DB-GPT.
- **FR-009**: Los mensajes de error de este motor hacia la persona MUST ser neutros, sin nombrar
  "DB-GPT" ni ningún detalle técnico interno (spec 044 US5).
- **FR-010**: El sistema MUST poder cruzar (join) múltiples planillas subidas al mismo espacio en
  una sola pregunta — resuelve explícitamente la limitación de "un solo archivo" encontrada en la
  investigación (Parte 2, hallazgo #1).

### Key Entities

- **Espacio de análisis exacto**: mismo concepto que definió la spec 046 US2 — este backend expone
  el punto de integración que esa spec de UI consume, reusando el modelo de pertenencia de la 043.
- **Llave de servicio de DB-GPT**: análoga a `svc.anythingllm-provider`/`svc.rag-masking` (spec
  043) — `can_act_on_behalf` habilitado (a diferencia de la del proveedor de AnythingLLM, que
  deliberadamente NO lo tiene), porque acá el "en nombre de quién" SÍ tiene que viajar (FR-005).
- **Consulta SQL generada**: efímera, nunca persistida en claro salvo en el log de auditoría ya
  existente (mismo criterio que el resto de las llamadas al motor) — el resultado tabular sí se
  devuelve a la persona, la consulta queda como evidencia auditable de qué se ejecutó.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: En una planilla real de prueba con dos archivos relacionados, al menos 9 de 10
  preguntas de cómputo exacto (suma/conteo/filtro/cruce entre los dos archivos) devuelven el valor
  correcto verificado a mano.
- **SC-002**: El 100% de las llamadas de modelo disparadas por DB-GPT en las pruebas de aceptación
  quedan atribuidas a la persona real en Costos → "Gasto por usuario", nunca a una cuenta de
  servicio.
- **SC-003**: Un escaneo de red desde fuera de la red interna del backend confirma 0 puertos
  alcanzables del contenedor DB-GPT, en el 100% de las corridas de verificación.
- **SC-004**: 0 valores de columnas marcadas como datos personales aparecen en claro en las
  llamadas de modelo salientes de DB-GPT, verificado contra el log de auditoría en las pruebas de
  aceptación.

## Assumptions

- **Decisión de arquitectura ya tomada (10-sep-2026, explícita del dueño del producto)**: usar
  DB-GPT pese a la recomendación en contrario de la investigación — esta spec no vuelve a discutir
  esa elección, solo la implementa con las mitigaciones que la misma investigación dejó como
  condición. Si en el futuro DB-GPT deja de ser viable (otra CVE crítica sin parche disponible,
  abandono del proyecto), la migración al módulo propio DuckDB+Azure OpenAI ya evaluado en
  `RESULTADOS-INVESTIGACION-DOCGEN-DBGPT.md` (Parte 2) queda como plan B documentado, no como
  trabajo a re-investigar desde cero.
- Se asume que DB-GPT soporta configurarse contra un proveedor OpenAI-compatible propio (el motor
  LiteLLM de Eleia ya expone esa interfaz para otros consumidores, p. ej. AnythingLLM) — confirmar
  el mecanismo exacto de configuración de proveedor de DB-GPT es tarea de `research.md` en
  `/speckit-plan`, no de esta spec.
- El "modo de análisis exacto" y su UI (cómo la persona sube una planilla, ve el resultado, y
  distingue este modo del chat RAG normal) es responsabilidad de la spec 046 (`client/`) — esta
  spec solo expone el contrato que esa UI consume, no la interfaz en sí.
- Esta spec no resuelve generación de documentos (spec 045/049) — son piezas independientes del
  mismo pedido original del cliente.
- Versión de DB-GPT a pinnear, límites de tamaño de planilla, y el mecanismo exacto de la llave
  de servicio (nueva vs. reutilizar el patrón de `svc.rag-masking`) son decisiones de `plan.md`,
  no de esta spec.
