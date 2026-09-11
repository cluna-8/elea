# Feature Specification: Formateo de respuesta a demanda y presupuesto por rol en Eleia Hub

**Feature Branch**: `047-formato-respuesta-presupuesto-rol-eleia-hub`

**Created**: 2026-09-08

**Status**: Draft — lista para `/speckit-plan`

**Repos que toca**: solo `client/` (Eleia Hub) para US1; `frontend/` (Eleia Guardian) para US2.
**NO toca `backend/` ni `litellm/`.** El único punto compartido con el producto base ("Guardian")
es la identidad del usuario ya autenticado y el modelo de `Group`/`Budget` que **ya existe hoy**
en el backend (spec 011) — esta spec no pide ningún endpoint nuevo, solo UX sobre lo existente.

**Input**: puntos 5 y 6 del pedido original de 6 puntos del cliente Elea, auditados en spec 041
US2 y US3, retomados acá como spec de UI propia y completa.

## Diagnóstico (heredado de la spec 041, sin cambios desde el 31-ago)

| Punto | Estado hoy |
|---|---|
| Formateo de respuesta (mail, lista, resumen) | ❌ No existe ningún "modo de salida"; el modelo responde libre |
| Presupuesto por rol | 🟡 Cubierto por convención (`Budget.group_id` + `Group` representando un rol) pero 100% manual desde requests HTTP directas, sin UX |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Elegir el formato de la respuesta desde la interfaz (Priority: P2)

Antes de mandar un pedido al chat, la persona puede elegir un formato de salida (mail, lista con
viñetas, resumen ejecutivo, tabla, o "libre" por default) desde un control visible, y la respuesta
sale en ese formato sin depender de que la persona sepa pedirlo bien en lenguaje natural.

**Why this priority**: pedido explícito del cliente ("hoy en día no formatea"); P2 porque no
bloquea ningún otro flujo y tiene una decisión de diseño a confirmar antes de codear (ver
Assumptions).

**Independent Test**: seleccionar "Formato: Mail" antes de un pedido → la respuesta tiene
estructura de mail (saludo, cuerpo, cierre) sin que la persona lo haya pedido en el texto.

**Acceptance Scenarios**:

1. **Given** el selector de formato en "Mail", **When** se envía un pedido, **Then** la respuesta
   tiene estructura de correo (encabezado, cuerpo, cierre), no prosa libre.
2. **Given** el selector en "Lista", **When** se envía un pedido, **Then** la respuesta es una
   lista de viñetas o numerada, no un párrafo continuo.
3. **Given** el selector en "Libre" (default), **When** se envía un pedido, **Then** el
   comportamiento es idéntico al actual, sin regresión.
4. **Given** un formato seleccionado, **When** la persona cambia de hilo o de espacio, **Then** el
   formato vuelve al default (o se conserva por sesión — decisión de diseño a confirmar) sin
   sorprender a la persona con un formato que no eligió a propósito para el nuevo contexto.
5. **Given** la selección de formato, **When** se pide algo que no tiene sentido en ese formato
   (p. ej. "tabla" para una respuesta de una sola palabra), **Then** el sistema no falla, aplica el
   formato de la mejor manera razonable.

---

### User Story 2 - Asignar presupuesto a un rol en un solo paso (Priority: P2)

Un admin puede crear un rol con presupuesto asociado (o asignarle presupuesto a un rol existente)
desde el panel, sin tener que armar manualmente un `Group` y un `Budget` con requests HTTP
directas.

**Why this priority**: pedido explícito del cliente; hoy la capacidad ya existe en el backend, es
puramente una falta de UX que genera fricción operativa real para el equipo de Elea.

**Independent Test**: desde el panel, crear un rol nuevo ("Analista de Calidad") con un
presupuesto de $X, y verificar que un usuario asignado a ese rol hereda el presupuesto sin ningún
paso manual adicional.

**Acceptance Scenarios**:

1. **Given** el panel de administración, **When** el admin crea un rol nuevo con presupuesto,
   **Then** se crea el `Group` y el `Budget` asociado en un solo flujo, no en pasos separados.
2. **Given** un rol existente sin presupuesto, **When** el admin le asigna uno, **Then** todos los
   usuarios ya asignados a ese rol heredan el presupuesto sin tener que reasignarlos uno por uno.
3. **Given** un usuario con presupuesto individual Y presupuesto de rol, **When** se evalúa su
   gasto, **Then** el orden de precedencia (¿individual primero? ¿rol primero? ¿el más restrictivo
   gana?) es visible y entendible desde el panel, no una sorpresa oculta en el backend.

### Edge Cases

- Un rol sin ningún presupuesto asignado: el comportamiento es "sin límite de rol", heredando solo
  el individual si existe (documentado explícitamente, no ambiguo).
- Cambiar el presupuesto de un rol con usuarios activos consumiendo en ese momento: el cambio
  aplica desde la próxima evaluación de presupuesto (post-hoc, mismo criterio que el resto del
  sistema — Principio V de la constitución), no en tiempo real dentro de una respuesta en curso.
- Un formato de salida pedido junto con un pedido de generación de documentos (spec 045): se
  documenta si aplica o si son mutuamente excluyentes.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Eleia Hub MUST ofrecer un control visible de formato de salida con al menos las
  opciones "libre" (default), "mail", "lista", "resumen".
- **FR-002**: El formato seleccionado MUST traducirse en una instrucción de sistema agregada al
  pedido antes de enviarlo, sin cambiar el contenido sustantivo de la respuesta, solo su forma.
- **FR-003**: Sin selección explícita, el comportamiento MUST ser idéntico al actual (sin
  regresión).
- **FR-004**: Eleia Guardian MUST ofrecer un flujo de un solo paso para crear/editar un rol con
  presupuesto asociado, sin requerir que el admin arme requests HTTP a mano.
- **FR-005**: El panel MUST mostrar de forma explícita cómo se resuelve el presupuesto cuando un
  usuario tiene presupuesto individual y de rol a la vez.

### Key Entities

- **Formato de respuesta**: valor efímero por pedido (o por sesión, según Assumptions) — no se
  persiste como preferencia de usuario en esta spec salvo que `plan.md` decida agregarlo.
- **Rol con presupuesto**: proyección de UI sobre `Group` + `Budget`, ya existentes en el backend
  desde la spec 011 — esta spec no agrega campos nuevos al modelo de datos.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Una persona sin instrucción previa encuentra y usa el selector de formato en menos
  de 30 segundos en una prueba de usabilidad informal.
- **SC-002**: El admin completa la creación de un rol con presupuesto en un solo flujo, en menos
  de 2 minutos, sin necesitar ayuda técnica ni documentación externa.
- **SC-003**: Cero regresiones en el comportamiento del chat cuando no se selecciona ningún
  formato explícito.

## Assumptions

- **Decisión de diseño a confirmar con el usuario antes de `/speckit-plan` de US1** (ya señalada en
  spec 041 y todavía sin resolver): ¿el formato es (a) un selector visible en la interfaz, o (b)
  se deja librado a que la persona lo pida en lenguaje natural y esto no es una feature de
  producto sino un hábito de uso? El texto del cliente ("Hoy en día no formatea") sugiere (a), y
  esta spec asume (a) como default razonable, pero **debe confirmarse explícitamente** antes de
  comprometer el diseño de la interfaz.
- US1 y US2 son completamente independientes entre sí — pueden desarrollarse y entregarse en
  cualquier orden o en paralelo.
- Ninguna de las dos historias requiere cambios de modelo de datos en el backend — US2 es
  estrictamente UX sobre `Group`/`Budget`, ya existentes.
