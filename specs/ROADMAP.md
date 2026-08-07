# Roadmap — Basa Secure AI Gateway

> **HISTÓRICO (banner 07-ago-2026)** — roadmap del fork gatelite, congelado el 03-jul. Se conserva SOLO por la deuda heredada A–F que cita `ROADMAP-guardian.md`. La planificación viva: [`ROADMAP-guardian.md`](./ROADMAP-guardian.md) + [`ROADMAP-pisos.md`](./ROADMAP-pisos.md). Nota: la spec 012 figura abajo como draft pero está **CERRADA** (✅ US1–US6, 20/20 tests).

**Última actualización**: 2026-07-03
**Estado del proyecto**: 11 specs (5 completos, 6 parciales) + 1 spec nuevo en draft (012).

Este roadmap consolida TODO el trabajo pendiente del proyecto: tareas abiertas de los specs 001–011, mejoras no formalizadas y la nueva feature de reducción de costes (spec 012). Era el documento único de planificación del fork; cada item apunta a su spec de origen.

---

## Leyenda

- **Estado**: Abierto / En curso / Hecho / Verificar (ya implementado, falta validar)
- **Riesgo**: Alto (pérdida de datos/security) / Medio / Bajo
- **Esfuerzo**: Trivial / Bajo / Medio / Alto

---

## A. Verificación y riesgos técnicos (prioridad alta)

Cerrar primero. Son tests e2e y verificaciones que validan código ya escrito.

| ID | Spec | Tarea | Riesgo | Esfuerzo | Estado |
|----|------|-------|--------|----------|--------|
| A1 | 003 | T-002-B/C — verificar `alembic upgrade head` sobre DB existente sin destruir datos `[!]` | **Alto** | Bajo | Abierto |
| A2 | 003 | T-018-A–E — 5 tests e2e (content filter, prompt shield, panel prueba, toggle guardian, alembic recreate) | Medio | Medio | Abierto |
| A3 | 004 | T-009-A–F — 6 tests dashboard (KPIs, selector período, estado motor, expand fila, export CSV, filtro fechas) | Bajo | Medio | Abierto |
| A4 | 005 | T-016–T-020 — 5 tests integración docker (Alembic 004, proyecto Art. 9(2)(h), DPA, DSR acceso, retención 30d) | Medio | Medio | Abierto |

---

## B. Deuda de documentación / inconsistencias (prioridad media)

| ID | Spec | Tarea | Esfuerzo | Estado |
|----|------|-------|----------|--------|
| B1 | 006 | T-025 — actualizar `docs/compliance-policies.md` (sección grupos y consentimiento) | Bajo | Abierto |
| B2 | 006 | T-026 — desmarcar pendiente: el changelog **ya existe**, solo tachar la task | Trivial | Abierto |
| B3 | 011 | T-048 — actualizar `USE.md` (presupuestos doble capa, eliminar, nueva UsersPage 5 tabs) | Bajo | Abierto |
| B4 | 011 | Alinear `plan.md` con el fix post-QA (modelo **secuencial** con `break`, no paralelo) | Trivial | Abierto |

---

## C. Scope diferido explícito (features futuras)

Marcadas como fuera de scope en sus specs originales.

| ID | Spec | Tarea | Esfuerzo | Estado |
|----|------|-------|----------|--------|
| C1 | 010 | T-031 — hot-reload config.yaml del motor (`/reload` endpoint) | Medio | Abierto |
| C2 | 010/003 | T-032 / T-016 — Presidio NLP real integrado en pipeline (analyzer+anonymizer, fallback regex) | Alto | Abierto |
| C3 | 010 | T-033 — OAuth2/OIDC Azure AD real | Alto | Abierto |
| C4 | 010 | T-034 — Google Workspace SSO real | Alto | Abierto |
| C5 | 010 | T-035 — Keycloak / SAML 2.0 real | Alto | Abierto |

---

## D. Mejoras no formalizadas (sugerencias del spec 001, sin task)

| ID | Tarea | Esfuerzo | Estado |
|----|-------|----------|--------|
| D1 | Guardianes cloud reales (Lakera/Azure) en vez de mock | Medio-Alto | Abierto |
| D2 | Export PDF + firma digital de reports (CSV ya existe en 004/008) | Medio | Abierto |
| D3 | Alertas email (umbrales de presupuesto / incidentes PII) | Medio | Abierto |
| D4 | Tests Pytest automatizados + CI/CD | Medio-Alto | Abierto |
| D5 | Mover credenciales de config.yaml a env vars (endurecimiento prod) | Bajo | Abierto |

---

## E. Spec 012 — Ahorro de Costes IA: compresión de tokens + reducción de costes

Feature nueva. Convierte la compresión de contexto (antes "Headroom", nombre de terceros) en un mecanismo real de ahorro medible, seguro y con ROI, integrado con presupuestos, analytics y una nueva sección de Costos con **calculadora que recomienda activar o no**.

Documentación completa en [`012-ahorro-costes-ia/`](./012-ahorro-costes-ia/).

| ID | User Story | Prioridad | Esfuerzo | Estado |
|----|------------|-----------|----------|--------|
| E1 / US1 | Compresor determinista seguro (preserva placeholders/URLs/código) + tiktoken + umbral mínimo | P1 | Medio | Draft |
| E2 / US2 | Sección dedicada **Costos** + calculadora interactiva con **veredicto activar/no** (tokens → tras compresión → ahorro USD) | P1 | Medio | Draft |
| E3 / US3 | Ahorro medible: `tokens_saved`/`cost_saved_usd` en audit + reflejado en presupuesto + KPI "Ahorro de Costes IA" | P1 | Medio | Draft |
| E4 / US4 | Toggle de compresión desde Costos + config rica por Policy/Group (estrategia, umbral, agresividad, modelo) | P2 | Medio | Draft |
| E5 / US5 | Compresión LLM asistida vía LiteLLM + guardia de ROI + **caché Redis por hash** | P2 | Alto | Draft |
| E6 / US6 | Telemetría por modelo + guardia de calidad (revertir si la respuesta degrada) | P3 | Medio | Draft |

### Decisiones de diseño abiertas (spec 012)

- **Motor compresor**: Determinista seguro + LLM opcional (recomendado) / Solo LLM / Solo determinista — **a confirmar**.
- **Integración de coste**: Presupuesto + dashboard (recomendado) / Solo telemetría / Solo fix del bug — **a confirmar**.
- **Caché Redis**: confirmada en la capa LLM (por hash del prompt); el determinista no cachea.

---

## F. Verificación de presupuesto en Users (no es feature nueva)

| ID | Tarea | Esfuerzo | Estado |
|----|-------|----------|--------|
| F1 | Verificar que la asignación/edición de presupuestos a usuario y grupo (spec 011) funciona e2e; decidir si se reubica en la sección Costos | Bajo | Verificar |

> **Nota**: La asignación y edición de presupuestos a nivel usuario y grupo **ya está implementada** en el spec 011 (`POST/PUT/DELETE /budgets`, modales "Asignar Límite" / "Editar presupuesto" / "Asignar equipo" en `UsersPage`). Este item es solo validación o reubicación opcional.

---

## Orden sugerido para "probar lo nuevo" (spec 012 + F)

Secuencia pensada para entregar algo visible y testeable cuanto antes, sin riesgo ni coste extra, dejando lo caro (capa LLM) para el final.

1. **F1-a · Sección Costos (shell + visualización)** — nueva `CostsPage`, reusa datos existentes. Visible sin backend nuevo.
2. **E1 / US1 · Compresor determinista seguro + tiktoken** — reescribe `optimization_service.py`, arregla el bug del regex que corrompe URLs/código.
3. **E2 / US2 · Calculadora interactiva** — en Costos, usa US1 para mostrar tokens → tras compresión → ahorro USD.
4. **E3 / US3 · Ahorro medible en presupuesto + KPI** — persistencia + descuento neto + KPI.
5. **E4 / US4 · Toggle de compresión + config rica por Policy/Group**.
6. **E5 / US5 · Compresión LLM asistida + ROI + caché Redis** (el caro/opcional).
7. **E6 / US6 · Telemetría + guardia de calidad**.
8. **F1 · Verificar/mover presupuestos**.

---

## Resumen por estado

| Estado | Cantidad |
|--------|----------|
| Completo (specs 001, 002, 007, 008, 009) | 5 |
| Parcial (specs 003, 004, 005, 006, 010, 011) | 6 |
| Draft nuevo (spec 012) | 1 |
| Items abiertos totales (A–F) | 22 |