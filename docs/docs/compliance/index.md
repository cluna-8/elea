# Compliance

!!! note "Audiencia"
    Administradores del sistema, DPO (Delegado de Protección de Datos) y responsables de
    seguridad TI en centros sanitarios.

El módulo de compliance del producto implementa los controles mínimos exigibles para desplegar
un gateway de IA en entornos sanitarios españoles. Esta sección se organiza en dos páginas:

- **Esta página** — visión general del marco legal y configuración de **Proyectos de Compliance**
  (bases legales, niveles de riesgo del EU AI Act, configuración paso a paso).
- **[DPA · DSR · Retención](dpa-dsr-retention.md)** — registro de DPAs, derechos del interesado
  (DSR), políticas de retención, panel DPO, pipeline y checklist de producción.

---

## Visión general

El módulo de compliance cubre los siguientes marcos:

| Marco legal | Artículos clave | Qué cubre este módulo |
|-------------|----------------|----------------------|
| **GDPR (Reglamento UE 2016/679)** | Art. 5, 9, 12–22, 28, 35 | Base legal, DPAs, DSRs, retención, DPIA |
| **EU AI Act (Reglamento UE 2024/1689)** | Art. 50 | Notificación al usuario de interacción con IA |
| **ENS (Esquema Nacional de Seguridad)** | Medidas de trazabilidad | Retención mínima de eventos de seguridad (365 días) |

!!! warning "No reemplaza la asesoría legal"
    Este módulo **no reemplaza** la asesoría legal. Proporciona controles técnicos; el DPO del
    centro debe validar que la configuración se alinea con su DPIA específica.

---

## Proyectos de Compliance

### Qué es

Un **Proyecto de Compliance** es la unidad central de configuración. Define las reglas que se
aplican a **todas las llamadas al chat** mientras el proyecto esté activo.

Puedes tener múltiples proyectos, pero en la práctica un centro sanitario típico necesita uno
por entorno de uso (ej: `Asistente Clínico`, `Soporte Administrativo`, `Investigación`).

### Campos y su significado

| Campo | Tipo | Qué controla |
|-------|------|-------------|
| **Nombre** | Texto | Identificador del proyecto (ej: "Asistente Clínico H. Valle Verde") |
| **Base legal** | Selector | La justificación GDPR para tratar datos de salud. **Obligatorio.** |
| **Categoría de datos** | Texto | Tipo de datos que maneja (ej: `health_data`, `administrative`) |
| **Nivel de riesgo AI Act** | Selector | Clasifica el sistema según los Annexos del EU AI Act |
| **Activo** | Boolean | Solo los proyectos activos aplican sus reglas al pipeline |
| **Forzar región EU** | Boolean | Bloquea llamadas a modelos fuera de la UE |
| **Notificación IA** | Boolean | Entrega aviso legal de uso de IA al usuario (Art. 50) |
| **Revisión humana** | Boolean | Genera token de revisión por cada respuesta para supervisión clínica |
| **Referencia DPIA** | Texto | Número de documento de la evaluación de impacto (ej: `DPIA-2026-001`) |
| **Mensaje de notificación** | Texto | Texto del aviso IA. Si está vacío, usa el mensaje predeterminado en español |

### Bases legales disponibles

| Opción | Cuándo usarla |
|--------|--------------|
| `Art. 9(2)(h)` — Prestación sanitaria | **La más común.** Asistentes clínicos, diagnóstico, historia clínica. Requiere supervisión de profesional sanitario. |
| `Art. 9(2)(j)` — Interés público / investigación | Proyectos de investigación anonimizados. Requiere DPIA y medidas adicionales. |
| `Art. 9(2)(a)` — Consentimiento explícito | Solo si tienes consentimiento firmado del paciente. No recomendado para uso clínico rutinario. |
| `Art. 6(1)(c)` — Obligación legal | Para procesos obligatorios por ley (ej: notificación de enfermedades de declaración obligatoria). |
| `Art. 6(1)(e)` — Misión de interés público | Para entidades públicas. No cubre datos de categoría especial por sí solo; combinar con Art. 9. |

### Niveles de riesgo EU AI Act

| Nivel | Descripción | Obligaciones |
|-------|-------------|-------------|
| **Riesgo Mínimo** | Chatbots informativos generales, sin decisiones sobre personas | Sin obligaciones adicionales |
| **Riesgo Limitado** | Sistemas que interactúan con humanos | Art. 50: **notificación obligatoria desde ago. 2026** |
| **Alto Riesgo — Annex III** | Sistemas usados en diagnóstico, triaje, decisiones clínicas | Registro en EUDB, DPIA, supervisión humana, logs 10 años |
| **Alto Riesgo — Annex I (MDR)** | Producto sanitario con marcado CE (Directiva MDR 2017/745) | Requisitos de producto sanitario + EU AI Act acumulados |

!!! tip "Asistente clínico en hospital"
    Para un asistente clínico en hospital, el nivel correcto es **Alto Riesgo — Annex III**
    (categoría 5(a): sistemas de IA para el diagnóstico o tratamiento de enfermedades). Esto
    activa la obligación de DPIA, notificación IA y revisión humana.

### Cómo configurar un proyecto básico paso a paso

1. Ir a **Políticas de Cumplimiento → Proyectos → Nuevo Proyecto**
2. Nombre: `Asistente Clínico [Nombre del centro]`
3. Base legal: `Art. 9(2)(h) — Prestación sanitaria`
4. Nivel de riesgo: `Alto Riesgo — Annex III`
5. Activar: **Notificación IA** y **Revisión humana**
6. Si los datos son sensibles: activar **Forzar región EU**
7. Referencia DPIA: completar cuando el DPO entregue el documento
8. Guardar → **Activar el proyecto**

---

## Siguiente paso

Continuar con **[DPA · DSR · Retención](dpa-dsr-retention.md)**: registro de DPAs por proveedor,
gestión de solicitudes DSR, políticas de retención, panel DPO y el checklist antes de producción.
