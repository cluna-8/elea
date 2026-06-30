# Políticas de Cumplimiento — Guía Operativa

> **Audiencia:** Administradores del sistema, DPO (Delegado de Protección de Datos), responsables de seguridad TI en centros sanitarios.

---

## Índice

1. [Visión general](#1-visión-general)
2. [Proyectos de Compliance](#2-proyectos-de-compliance)
3. [Registro de DPAs](#3-registro-de-dpas)
4. [Derechos del Interesado (DSR)](#4-derechos-del-interesado-dsr)
5. [Políticas de Retención](#5-políticas-de-retención)
6. [Panel DPO](#6-panel-dpo)
7. [Cómo se aplican en el pipeline de chat](#7-cómo-se-aplican-en-el-pipeline-de-chat)
8. [Escenarios de uso práctico](#8-escenarios-de-uso-práctico)
9. [Checklist antes de producción](#9-checklist-antes-de-producción)

---

## 1. Visión general

El módulo de compliance implementa los controles mínimos exigibles para desplegar un gateway de IA en entornos sanitarios españoles bajo:

| Marco legal | Artículos clave | Qué cubre este módulo |
|-------------|----------------|----------------------|
| **GDPR (Reglamento UE 2016/679)** | Art. 5, 9, 12–22, 28, 35 | Base legal, DPAs, DSRs, retención, DPIA |
| **EU AI Act (Reglamento UE 2024/1689)** | Art. 50 | Notificación al usuario de interacción con IA |
| **ENS (Esquema Nacional de Seguridad)** | Medidas de trazabilidad | Retención mínima de eventos de seguridad (365 días) |

> **Importante:** Este módulo **no reemplaza** la asesoría legal. Proporciona controles técnicos; el DPO del centro debe validar que la configuración se alinea con su DPIA específica.

---

## 2. Proyectos de Compliance

### Qué es

Un **Proyecto de Compliance** es la unidad central de configuración. Define las reglas que se aplican a **todas las llamadas al chat** mientras el proyecto esté activo.

Puedes tener múltiples proyectos, pero en la práctica un centro sanitario típico necesita uno por entorno de uso (ej: `Asistente Clínico`, `Soporte Administrativo`, `Investigación`).

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

> **Para un asistente clínico en hospital**: el nivel correcto es **Alto Riesgo — Annex III** (categoría 5(a): sistemas de IA para el diagnóstico o tratamiento de enfermedades). Esto activa la obligación de DPIA, notificación IA y revisión humana.

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

## 3. Registro de DPAs

### Qué es

Un **DPA (Data Processing Agreement)** es el contrato obligatorio entre el responsable del tratamiento (el hospital) y cada encargado del tratamiento (el proveedor del LLM) que exige el **Art. 28 GDPR**.

**Sin DPA firmado con el proveedor del LLM, no se pueden enviar datos de pacientes.**

### Proveedores y su cobertura

| Proveedor | DPA estándar cubre Art. 9 | Región EU disponible | Recomendación |
|-----------|--------------------------|---------------------|---------------|
| **Azure OpenAI** (Microsoft) | ✅ Sí — Microsoft Online Services DPA | ✅ Sí (`swedencentral`, `francecentral`) | **Recomendado para PHI** |
| **AWS Bedrock** (Amazon) | ✅ Sí — AWS BAA | ✅ Sí (`eu-west-1`, `eu-central-1`) | **Recomendado para PHI** |
| **Google Vertex AI** | ✅ Sí — Google Cloud DPA | ✅ Sí (`europe-west1`) | Válido con DPA firmado |
| **OpenAI directo** | ⚠️ Solo Enterprise | ❌ No garantizado | **No recomendado para PHI** sin Enterprise |
| **Ollama (local)** | ✅ N/A — procesamiento local | ✅ Siempre | Ideal para datos muy sensibles |

### Campos del registro

| Campo | Qué registrar |
|-------|--------------|
| **Proveedor** | Nombre legal del encargado (ej: `Microsoft Ireland Operations Ltd.`) |
| **Tipo** | `Estándar` (DPA del proveedor), `Adenda personalizada`, `Enterprise` |
| **Región de procesamiento** | Donde procesará los datos: `EU`, `US`, `Global` |
| **Cubre Art. 9** | Marcar solo si el DPA cubre explícitamente datos de categoría especial |
| **Fecha de firma** | Fecha en que el contrato entró en vigor |
| **Fecha de vencimiento** | Fecha de renovación (el panel muestra alerta 30 días antes) |
| **Referencia del documento** | URL interna o número de expediente del DPA firmado |

### Estados del DPA

| Estado | Significado | Acción requerida |
|--------|-------------|-----------------|
| 🟢 **Activo** | DPA vigente | Ninguna |
| 🟡 **Por vencer** | Vence en menos de 30 días | Renovar o negociar prórroga |
| 🔴 **Expirado** | Vencimiento pasado | **Detener uso del proveedor** hasta renovación |

---

## 4. Derechos del Interesado (DSR)

### Qué es

Los artículos 12–22 del GDPR otorgan a las personas físicas derechos sobre sus datos. El centro tiene obligación de responder en **30 días calendario** (Art. 12).

Este módulo proporciona un registro de solicitudes y una herramienta de búsqueda para localizar qué datos del sujeto están en el sistema.

### Tipos de solicitudes

| Tipo | Artículo GDPR | Qué implica técnicamente |
|------|---------------|-------------------------|
| **Acceso** | Art. 15 | Exportar todos los registros del sujeto en el audit log |
| **Rectificación** | Art. 16 | Corregir datos incorrectos (identificador, metadatos) |
| **Supresión** ("derecho al olvido") | Art. 17 | Anonimizar o eliminar registros del sujeto |
| **Portabilidad** | Art. 20 | Exportar datos en formato estructurado (JSON/CSV) |
| **Limitación** | Art. 18 | Marcar registros para no procesarlos en análisis |

### Flujo de trabajo recomendado

```
1. Recepción de solicitud (correo, formulario, presencial)
        ↓
2. Registrar en DSR tracker con identificador del sujeto
        ↓
3. Usar buscador → buscar por subject_id en audit logs
        ↓
4. Evaluar si la solicitud es procedente (verificar identidad)
        ↓
5. Ejecutar acción técnica (exportar / anonimizar / corregir)
        ↓
6. Marcar DSR como "Completada" con notas del resultado
        ↓
7. Notificar al sujeto (plazo máximo: 30 días desde recepción)
```

### Sobre el identificador del sujeto

El sistema **no almacena nombres ni NIF** — solo el identificador interno pseudonimizado que la API key del cliente envía. Para poder responder una DSR necesitas:

1. Conocer qué identificador usa tu sistema para ese paciente
2. Buscarlo en el audit log

> Si usas pseudonimización, el mapeo `identificador → persona real` debe estar en un sistema separado bajo custodia del DPO, nunca en este gateway.

---

## 5. Políticas de Retención

### Qué es

El **Art. 5(1)(e) GDPR** prohíbe conservar datos personales más tiempo del necesario. Este módulo permite configurar por cuánto tiempo se guardan los distintos tipos de registros.

### Tipos de registro y valores por defecto

| Tipo | Por defecto | Justificación | Mínimo recomendado |
|------|------------|--------------|-------------------|
| **Contenido de prompts y respuestas** | 90 días | Soporte técnico e investigación de incidencias | 30 días |
| **Metadatos de uso** (tokens, coste, modelo) | 365 días | Auditoría de costes y rendimiento | 90 días |
| **Eventos de seguridad** (guardianes, bloqueos) | 365 días | Detección de patrones de ataque, ENS | **365 días (no reducir)** |
| **Auditoría de configuración** | 730 días | Trazabilidad de decisiones administrativas | **365 días (mínimo bloqueado)** |

### Cómo ajustar la retención

1. Ir a **Políticas de Cumplimiento → Retención de Datos**
2. Modificar los días para cada tipo según la DPIA del centro
3. Completar el campo de justificación (este texto va a la DPIA)
4. Guardar

> **Nota:** El trabajo de purga automática (borrar registros vencidos) está en el roadmap de la **feature 007**. Por ahora la retención se configura pero la purga es manual.

### Cómo documentar para la DPIA

El campo "Justificación" de cada tipo de log es el texto que va directamente en la sección de retención de tu DPIA. Debe responder: *¿Por qué necesitamos estos datos durante este período?* Ej:

> "Los metadatos de uso se conservan 365 días para auditoría interna de costes y para poder responder a reclamaciones de facturación durante el año fiscal en que se generaron."

---

## 6. Panel DPO

### Qué es

Vista consolidada para el Delegado de Protección de Datos. Muestra el estado de cumplimiento de un vistazo sin necesidad de revisar cada sección.

### Indicadores y cómo interpretarlos

| Indicador | Verde | Amarillo | Rojo |
|-----------|-------|----------|------|
| **Proyectos Activos** | ≥1 activo, sin alertas | Activos con alertas (sin DPIA) | 0 activos |
| **DPAs Vigentes** | Todos activos | Alguno por vencer | Alguno expirado |
| **DPIAs Pendientes** | 0 pendientes | — | ≥1 proyecto alto riesgo sin DPIA |
| **Solicitudes DSR Abiertas** | 0 abiertas | ≥1 abierta | ≥1 abierta hace +25 días |
| **Enmascaramiento PHI** | >80% | 40–80% | <40% |
| **Notificación IA** | >90% | 50–90% | <50% (obligatorio desde ago. 2026) |
| **Revisión Humana** | >95% completadas | 80–95% | <80% |

### Revisión DPO recomendada (mensual)

1. Comprobar que no hay DPAs expirados
2. Verificar que todos los proyectos alto riesgo tienen DPIA referenciada
3. Revisar DSRs abiertas — si alguna supera 25 días, escalar
4. Revisar tasa de notificación IA — debe ser ~100%
5. Revisar revisiones humanas pendientes en `/api/v1/compliance/review/pending`

---

## 7. Cómo se aplican en el pipeline de chat

Cuando un usuario envía un mensaje al chat, el sistema ejecuta este flujo **por cada llamada**:

```
Petición entrante
      │
      ▼
[1] Autenticación API key
      │
      ▼
[2] Guardianes de contenido (Presidio PII, LiteLLM moderation)
      │
      ▼
[3] ◀── COMPLIANCE MIDDLEWARE ──▶
      │
      ├─ Lee todos los proyectos activos
      │
      ├─ [EU Region check]
      │   Si proj.eu_region_required = true
      │   Y modelo no empieza por azure- / bedrock- / vertex- / ollama-
      │   → HTTP 503 — petición bloqueada, LLM nunca la recibe
      │
      ├─ [AI Disclosure check]
      │   Si proj.ai_disclosure_enabled = true
      │   Y no se entregó disclosure en la última hora para esta API key
      │   → Preparar prefijo de notificación
      │
      └─ [Human Review check]
          Si proj.human_review_required = true
          → Generar UUID de revisión
      │
      ▼
[4] Llamada al LLM (LiteLLM → proveedor)
      │
      ▼
[5] Post-procesamiento
      │
      ├─ Si hay disclosure preparado → prepend al inicio de la respuesta
      ├─ Si hay review_token → guardar en tabla human_review
      └─ Audit log con ai_disclosure_delivered y review_token
      │
      ▼
Respuesta al usuario
```

### Ejemplo de respuesta con disclosure activo

```
ℹ️ Este servicio utiliza inteligencia artificial para generar respuestas.
Las respuestas pueden contener errores. Consulte siempre a un profesional
sanitario antes de tomar decisiones clínicas.

[Respuesta del LLM aquí]
```

El aviso aparece **una vez por hora por API key** — no en cada mensaje, para no interrumpir el flujo de conversación continuamente.

---

## 8. Escenarios de uso práctico

### Escenario A: Hospital con asistente clínico (caso típico)

**Configuración recomendada:**
- 1 proyecto activo: base legal Art. 9(2)(h), riesgo Alto Annex III
- Notificación IA: ✅ activada
- Revisión humana: ✅ activada (médico supervisa respuestas)
- Región EU: ✅ activada (usar Azure OpenAI `swedencentral` o Bedrock `eu-west-1`)
- DPA registrado: Microsoft Online Services DPA (cubre Art. 9)
- DPIA: obligatoria antes del despliegue en producción

**Flujo de revisión humana:**
1. Médico hace pregunta clínica
2. Sistema genera respuesta + review_token en audit log
3. Supervisor médico revisa `/api/v1/compliance/review/pending`
4. Aprueba o rechaza con notas

### Escenario B: Soporte administrativo (bajo riesgo)

**Configuración recomendada:**
- 1 proyecto activo: base legal Art. 6(1)(e) o Art. 9(2)(h) según contexto
- Notificación IA: ✅ activada (obligatoria en cualquier caso)
- Revisión humana: ❌ no necesaria para consultas administrativas
- Región EU: recomendada pero no bloqueante para datos administrativos
- Nivel de riesgo: Limitado

### Escenario C: Investigación con datos anonimizados

**Configuración recomendada:**
- Base legal: Art. 9(2)(j) — interés público / investigación
- Nivel de riesgo: Limitado o Mínimo (si los datos están verdaderamente anonimizados)
- Notificación IA: ✅ activada
- DPIA: recomendada aunque los datos sean anonimizados

---

## 9. Checklist antes de producción

### Legal / Organizativo

- [ ] DPIA completada y aprobada por el DPO para cada caso de uso de alto riesgo
- [ ] DPA firmado con cada proveedor de LLM que recibirá datos de pacientes
- [ ] Política de retención revisada y aprobada por el DPO
- [ ] Procedimiento de respuesta a DSR documentado (¿quién gestiona? ¿en qué plazo?)
- [ ] Registro de Actividades de Tratamiento (RAT) actualizado con este sistema
- [ ] Notificación a la AEPD si el tratamiento requiere inscripción

### Técnico

- [ ] Al menos 1 proyecto de compliance activo con base legal correcta
- [ ] DPA del proveedor LLM registrado con `cubre_art_9 = true`
- [ ] Notificación IA activada (obligatoria EU AI Act Art. 50 desde agosto 2026)
- [ ] Si se usan datos clínicos reales: `eu_region_required = true` y modelo `azure-*` o `bedrock-eu-*`
- [ ] Presidio activado para enmascaramiento de PII (ver Seguridad → Guardianes)
- [ ] Retención de prompt_content configurada según DPIA (recomendado ≤90 días para PHI)

### Verificación post-despliegue

- [ ] Panel DPO muestra 0 DPAs expirados y 0 DPIAs pendientes
- [ ] Tasa de notificación IA > 0% tras primeras llamadas de prueba
- [ ] Audit log registra `ai_disclosure_delivered = true` en primera llamada por sesión
- [ ] DSR de prueba creada, buscada y completada correctamente

---

*Documento generado para Basa Secure AI Gateway — Feature 005 — v1.0 — 2026-06-29*
*Actualizar cuando cambie la configuración de compliance o la normativa aplicable.*
