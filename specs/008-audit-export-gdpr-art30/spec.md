# Feature 008 — Audit Export & Registros de Tratamiento (GDPR Art. 30)

## Objetivo
Generar documentos exportables que cubran las obligaciones de registro del GDPR y la EU AI Act: Registro de Actividades de Tratamiento (RAT/RoPA), exportación DSAR por sujeto, e informe ejecutivo para la AESIA.

## Alcance
- `GET /api/v1/reports/rat` → CSV con todas las actividades de tratamiento por proyecto de compliance
- `GET /api/v1/reports/dsar/{subject_identifier}` → JSON/CSV con todos los logs asociados al sujeto (pseudonimizado)
- `GET /api/v1/reports/executive` → JSON con resumen ejecutivo: totales, tasas de compliance, alertas
- `GET /api/v1/reports/human-review-log` → CSV de revisiones humanas completadas (aprobadas/rechazadas)
- Frontend: botones de exportación en Panel DPO y en AuditPage

## Formato RAT (Art. 30)
Campos: nombre_actividad, responsable_tratamiento, finalidad, base_juridica, categoria_datos, destinatarios, transferencias_internacionales, plazos_supresion, medidas_seguridad.

## Fuera de alcance
- Generación de PDF (se usa CSV/JSON descargable)
- Firma digital de documentos
- Envío automático a la AESIA

## Restricción white-label
El nombre del motor de IA no debe aparecer en ningún campo exportado.
