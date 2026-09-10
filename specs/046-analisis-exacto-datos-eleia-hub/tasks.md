---

description: "Task list — spec 046: Análisis exacto de datos (Excel/CSV) en Eleia Hub"

---

# Tasks: Análisis exacto de datos (Excel/CSV) en Eleia Hub

**Numeración**: continúa la secuencia global (última usada: T097, spec 048).

## Phase 1: Setup

- [ ] T098 Rutas proxy en `client/server.js`: `POST /api/exact-analysis/workspaces`,
      `POST /api/exact-analysis/workspaces/:id/files`, `POST /api/exact-analysis/workspaces/:id/query`
      — 1:1 hacia el backend (spec 048, ya probado en vivo), con la misma sesión del Hub

## Phase 2: User Story 1 - Preguntar y obtener un cálculo exacto (Priority: P1)

- [ ] T099 [US1] Tab lateral "Análisis exacto" en el sidebar — sección propia, nunca mezclada
      con la lista de espacios RAG (FR-001/US2)
- [ ] T100 [US1] Lista + creación de espacios de análisis exacto (reusa el modal de "+ Nuevo",
      con el `kind` correcto)
- [ ] T101 [US1] Subida de archivo — solo `.csv`/`.xlsx`/`.xls` (rechazo claro de otros formatos,
      Edge Case de spec.md), muestra columnas detectadas si el backend las devuelve (FR-006)
- [ ] T102 [US1] Panel de pregunta/respuesta — input de pregunta, respuesta, y el SQL ejecutado
      visible (Pipeline Transparency) — nunca oculto, a diferencia del chat RAG
- [ ] T103 [US1] Presupuesto agotado (402) → mismo mensaje neutro ya usado en el resto del Hub
- [ ] T104 [US1] Motor no disponible (502) → mensaje neutro, sin nombrar "DB-GPT" (FR-005)

## Phase 3: User Story 2 - Distinguir del chat RAG (Priority: P1)

- [ ] T105 [US2] Copy explícito en la sección ("Para cálculos exactos sobre planillas — sumas,
      conteos, cruces. No es el chat de documentos.") — cierra SC-002

## Phase 4: Polish

- [ ] T106 [P] Test de integración `client/tests/integration/test_exact_analysis_ui_046.test.js`
- [ ] T107 Verificación en vivo por Chrome real (Browser pane) — el guion de US1 completo,
      clickeando, no por API — es lo que el dueño del producto pidió ver

## Implementation Strategy

MVP = T098-T104 (US1 completo) — ya demuestra el flujo real pedido. T105 (US2) y T106/T107 cierran
la entrega.
