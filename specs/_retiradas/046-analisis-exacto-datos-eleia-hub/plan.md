# Implementation Plan: Análisis exacto de datos (Excel/CSV) en Eleia Hub

**Branch**: `044-hub-chat-panel-admin` (mismo criterio que 043-045/047/048 en este repo) | **Date**: 2026-09-11 | **Spec**: [spec.md](spec.md)

## Summary

Agregar al Hub una sección propia, **separada visualmente del chat RAG** (US2/FR-001): un tab
lateral "Análisis exacto" con su propia lista de espacios, su propio flujo de subida de archivo, y
su propio panel de pregunta/respuesta (con el SQL ejecutado visible, a diferencia del chat RAG que
nunca muestra SQL). `client/server.js` agrega 3 rutas proxy nuevas que llaman 1:1 a los 3
endpoints ya construidos y probados en vivo del backend (spec 048: `POST /exact-analysis/
workspaces`, `.../files`, `.../query`) — el Hub nunca habla con DB-GPT, siempre con el backend.

## Technical Context

**Language/Version**: Node.js (client/server.js, ya en uso), JS vanilla (client/public/index.html,
sin framework — mismo criterio que el resto del Hub)

**Primary Dependencies**: ninguna nueva — `fetch` nativo del lado del server (ya en uso vía
`eleaFetch`), sin librerías de UI nuevas

**Storage**: N/A — todo el estado vive en el backend (spec 048)

**Testing**: `node:test` + `supertest` (client/tests/, mismo patrón que el resto)

**Target Platform**: mismo Hub existente (:8095)

**Project Type**: extensión de una web app existente

## Constitution Check

| Principio | Chequeo | Resultado |
|---|---|---|
| IV. Client Onboarding as Data | ¿reusa la sesión/usuario ya existente? | ✅ mismas cookies de sesión del Hub, sin login aparte |
| V. Cost Governance | ¿el 402 se ve igual que en el resto? | ✅ el backend ya lo devuelve (spec 048 FR-008); el Hub solo lo muestra con el mismo mensaje neutro ya usado (`MENSAJE_PRESUPUESTO_AGOTADO`) |
| VII. Containerized & White-Label | ¿sin nombrar "DB-GPT" en la UI? | ✅ FR-005 lo exige; todos los textos dicen "análisis exacto"/"motor de datos", nunca el nombre real |
| VIII. Pipeline Transparency | ¿se ve el SQL ejecutado? | ✅ a diferencia del chat RAG (que nunca expone SQL), acá SÍ se muestra — es la pieza que hace "exacto" creíble/auditable para la persona |

**Sin violaciones.**

## Project Structure

```text
client/
├── public/index.html   # EXTENDER: tab "Análisis exacto" en el sidebar, su propia vista
│                        # (lista de espacios, subida, pregunta/respuesta con SQL)
├── server.js            # EXTENDER: 3 rutas proxy 1:1 hacia backend /exact-analysis/*
└── tests/integration/
    └── test_exact_analysis_ui_046.test.js   # NUEVO
```

**Structure Decision**: sección nueva dentro del MISMO `index.html` (no una página separada) —
mismo criterio que el resto del Hub (SPA de un archivo, sin router). Se activa con un tab lateral
nuevo, nunca mezclado con la vista de chat RAG existente (US2/FR-001: "visualmente distinto").

## Complexity Tracking

*Sin violaciones — tabla omitida.*
