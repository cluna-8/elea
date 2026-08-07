# Feature Specification: Página de Partner Enablement en la doc de producto

**Feature Branch**: `025-partner-enablement-docs`

**Created**: 2026-07-21

**Status**: Implementada — estado canónico en [`deploy/ROADMAP-factory.md`](../../deploy/ROADMAP-factory.md)

**Input**: User description: "Página de partner enablement en la doc de producto: programa de capacitación y certificación del partner (distribuidor) para que instale de forma autónoma"

## Contexto y problema

La sección Install/Deploy de la doc de producto explica **cómo** instalar (runbook de
punta a punta, licenciamiento, infraestructura), pero no existe ninguna página que
describa **el camino para que un partner nuevo llegue a instalar solo**: qué perfil
necesita su ingeniero, por qué etapas pasa, qué acompaña el fabricante en cada una y
cuándo se considera autónomo. Hoy ese conocimiento vive en conversaciones internas —
cada partner nuevo lo descubre ad-hoc, y el fabricante no tiene una referencia
canónica contra la cual ejecutar onboardings consistentes.

**Filtro editorial obligatorio**: la doc de producto **se vende** con el producto y la
lee el partner. Esta página describe el programa de cara al partner (etapas, requisitos,
expectativas, criterios de salida) y **excluye por diseño toda información interna del
fabricante**: capacidad en FTE, horas internas por alta, costos, cuellos de botella
operativos y decisiones de staffing.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - El ingeniero del partner se prepara para instalar solo (Priority: P1)

Un ingeniero del partner que va a ser responsable de las instalaciones abre la doc de
producto y encuentra una página que le dice: qué conocimientos previos necesita, por
qué etapas pasa el programa (formación → práctica → installs acompañados →
certificación), qué se espera de él en cada etapa, y con qué criterios se lo considera
autónomo.

**Why this priority**: es la audiencia primaria de toda la sección Install/Deploy y el
hueco que hoy existe — sin este camino, el runbook técnico no alcanza para volverse
autónomo.

**Independent Test**: una persona con el perfil objetivo lee sólo esta página y puede
enumerar (a) los prerequisitos, (b) las etapas del programa en orden, y (c) los
criterios de salida para operar sin acompañamiento.

**Acceptance Scenarios**:

1. **Given** un ingeniero de partner sin contexto previo, **When** lee la página,
   **Then** identifica los conocimientos base requeridos y puede autoevaluar si los
   cumple antes de empezar.
2. **Given** un ingeniero que completó la formación, **When** consulta la página,
   **Then** sabe cuál es la siguiente etapa y qué evidencia de avance se espera
   (instalación de práctica completa, installs reales acompañados).
3. **Given** un ingeniero que terminó sus installs acompañados, **When** revisa el
   checklist de autonomía, **Then** puede verificar punto por punto si está en
   condiciones de operar solo y qué canal le queda hacia el fabricante (escalación de
   bugs de producto).

---

### User Story 2 - El responsable del partner evalúa el compromiso (Priority: P2)

Un responsable no técnico del partner (quien decide asignar a su ingeniero al programa)
lee la página para entender cuánto tiempo de su gente compromete el programa, qué pone
el fabricante y qué pone el partner en cada etapa, y qué obtiene al final (capacidad de
instalar y dar soporte de primer nivel bajo su marca).

**Why this priority**: la decisión de entrar al programa es del negocio del partner; si
la página sólo habla al ingeniero, el sponsor no puede planificar la dedicación.

**Independent Test**: un lector no técnico extrae de la página la duración típica del
programa, la dedicación esperada de su ingeniero y el reparto de responsabilidades
fabricante/partner, sin necesitar leer el runbook técnico.

**Acceptance Scenarios**:

1. **Given** un responsable evaluando el programa, **When** lee la página, **Then**
   encuentra una expectativa de duración del programa expresada como rango y la
   advertencia de que los primeros installs reales toman más tiempo que uno maduro.
2. **Given** la pregunta "¿qué pone cada parte?", **When** consulta la página, **Then**
   ve el reparto por etapa: qué provee el fabricante (material, entorno de práctica,
   acompañamiento, certificación) y qué provee el partner (ingeniero con el perfil
   requerido, dedicación, clientes reales para los installs acompañados).

---

### User Story 3 - El fabricante ejecuta onboardings consistentes (Priority: P3)

Quien conduce el onboarding del lado del fabricante usa la página como referencia
canónica del programa: mismas etapas, mismos criterios de salida y mismo checklist para
todo partner, en lugar de improvisar cada onboarding.

**Why this priority**: consistencia y escala del canal; depende de que P1/P2 existan
primero.

**Independent Test**: dos onboardings conducidos por personas distintas siguen las
mismas etapas y aplican el mismo checklist de autonomía documentado.

**Acceptance Scenarios**:

1. **Given** un partner nuevo por onboardear, **When** el conductor sigue la página,
   **Then** las etapas ejecutadas y los criterios aplicados coinciden con los
   documentados, sin pasos "de memoria".

---

### Edge Cases

- **Ingeniero sin los prerequisitos**: la página debe decir explícitamente qué pasa —
  el programa asume el perfil base y la formación se alarga si falta; no es un curso
  de las tecnologías base.
- **Partner que quiere saltear los installs acompañados**: los criterios de salida son
  por evidencia (installs reales completados), no por tiempo transcurrido; la página
  debe dejar claro que la autonomía se certifica, no se declara.
- **Partner cuyo mercado es sólo on-prem/air-gapped**: la práctica y los installs
  acompañados deben cubrir el camino de despliegue que el partner va a operar en la
  realidad (el programa se adapta al camino, no al revés).
- **Estado del programa vs realidad**: el programa como proceso formal es nuevo; la
  página debe marcar honestamente qué soporte existe hoy (runbook, perfil por cliente,
  entorno reproducible) y qué es parte del programa en formalización, usando la
  leyenda de estado del sitio.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: La doc de producto MUST incluir una página de enablement del partner
  dentro de la sección Install/Deploy, enlazada desde el índice de esa sección.
- **FR-002**: La página MUST describir el programa como etapas ordenadas — formación,
  práctica en entorno de prueba, installs reales acompañados, certificación de
  autonomía — con el objetivo y el criterio de salida de cada etapa.
- **FR-003**: La página MUST enumerar los prerequisitos del ingeniero del partner
  (perfil técnico base) y el comportamiento del programa cuando no se cumplen.
- **FR-004**: La página MUST incluir un checklist de autonomía verificable punto por
  punto que define cuándo el partner queda certificado para operar solo.
- **FR-005**: La página MUST expresar expectativas de duración de cara al partner como
  rangos (duración típica del programa completo; los primeros installs reales toman
  2–3× lo que un install maduro), marcadas como estimaciones.
- **FR-006**: La página MUST explicitar el reparto fabricante/partner por etapa: qué
  provee cada parte y qué queda del lado del partner al certificarse (instalación,
  training a su cliente, soporte de primer/segundo nivel), y qué queda siempre del
  lado del fabricante (emisión de licencias, bugs de producto).
- **FR-007**: La página MUST NOT contener información interna del fabricante: horas
  internas por alta, capacidad en FTE, costos, cuellos operativos ni planes de
  staffing.
- **FR-008**: La página MUST cumplir el contrato editorial del sitio para páginas tipo
  GUÍA (estructura, audiencia explícita, diagrama conceptual, leyenda de estado
  honesta, sección de relacionados) y el naming marca-neutro que exige el gate del
  release.
- **FR-009**: La página MUST usar el término "partner" presentándolo como equivalente
  a "distribuidor" (término vigente en el resto del sitio) en su primera aparición; la
  migración de terminología del resto del sitio queda fuera de alcance.
- **FR-010**: La página MUST marcar con la leyenda de estado del sitio qué soporte del
  programa existe hoy y qué está en formalización — sin declarar como existente nada
  que no lo sea.

### Key Entities

- **Programa de enablement**: el camino formación → práctica → acompañamiento →
  certificación; atributos: etapas, criterios de salida, duración típica.
- **Etapa**: unidad del programa con objetivo, actividades, qué provee cada parte y
  criterio de salida verificable.
- **Checklist de autonomía**: lista de capacidades demostrables que certifican al
  partner; es el artefacto de cierre del programa.
- **Perfil del ingeniero del partner**: conocimientos base requeridos para entrar al
  programa.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: La página nueva pasa el gate de documentación del release completo
  (estructura, naming, build estricto, white-label) sin excepciones agregadas.
- **SC-002**: Un lector con el perfil objetivo puede enumerar prerequisitos, etapas en
  orden y criterios de salida leyendo sólo esta página (validable con una lectura de
  revisión de un integrante del equipo que no la escribió).
- **SC-003**: Una búsqueda de términos de economía interna del fabricante (FTE, horas
  internas, costo por alta, capacidad del equipo) sobre la página no devuelve ningún
  resultado.
- **SC-004**: El índice de Install/Deploy referencia la página nueva y la página
  referencia al menos dos páginas existentes del sitio con contexto.

## Assumptions

- Los rangos de duración de cara al partner (programa completo; primeros installs a
  2–3×) son información de expectativa razonable para publicar y no revelan economía
  interna del fabricante.
- El programa formal de certificación es nuevo: la página lo documenta como el camino
  oficial marcando su estado honestamente, apoyada en lo que sí existe hoy (runbook de
  instalación, perfil por cliente, entorno reproducible por contenedores).
- La terminología global del sitio sigue siendo "distribuidor"; esta página introduce
  "partner" como equivalente sin migrar el resto del sitio.
- El contenido es marca-neutro e idéntico entre marcas, como todo el sitio (never
  fork).
