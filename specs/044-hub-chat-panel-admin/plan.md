# Implementation Plan: Eleia Hub con espacios privados, costos por persona y Eleia Guardian (panel) completo

**Branch**: `044-hub-chat-panel-admin` | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/044-hub-chat-panel-admin/spec.md`. Depende de los 6
contratos publicados por [043-aislamiento-atribucion-motor](../043-aislamiento-atribucion-motor/spec.md)
(`contracts/`) — este plan asume que esos contratos existen o, donde `tasks.md` de la 043 aún no
los cerró, que hay un doble de prueba con la misma forma (ver Assumptions de la spec).

**Marca**: acá todo es **Eleia** — el panel de administración es "Eleia Guardian", el cliente de
chat/RAG es "Eleia Hub". Nunca "Sentinel" en este repo.

## Summary

Cerrar, del lado de las dos interfaces (`client/` = Eleia Hub, `frontend/` = Eleia Guardian), lo
mismo que la 043 cerró del lado del motor/backend: el Hub deja de listar espacios y de cargar
historiales sin verificar pertenencia (consumiendo el contrato 1), muestra y aplica presupuesto
propio por autoservicio (contrato 2), envía un identificador por documento al enmascarar (contrato
3), y el panel gana edición completa de usuarios, distingue cuentas de servicio y deja de mostrar
`license`/`chat-ui` como modelos (contratos 4-5). Ambas interfaces dejan de nombrar el motor de
documentos, el motor de IA o el detector NLP en cualquier texto visible (contrato 6). Ninguna
historia P1 se da por cerrada sin el guion de integración de punta a punta contra la 043 real
(US6 de esta spec).

Enfoque técnico: `client/` (Node/Express, sin framework de frontend) gana sesión obligatoria en
cada ruta, un cliente HTTP fino hacia los nuevos endpoints del backend (`/workspaces`, `/users/me/
budget`), y un `document_id` generado por subida. `frontend/` (React + Vite + TS) gana una pestaña
de gestión de usuarios completa y ajustes en Dashboard/Costos/Seguridad para leer los campos nuevos
de la 043. Ninguna reescritura: se extiende el código existente, siguiendo el mismo patrón que la
042 (rediseño preservando 1:1 la lógica real).

## Technical Context

**Language/Version**: Node.js 22 + Express 4 (`client/`, sin TypeScript, JS plano igual que hoy); TypeScript 5.2 + React 18.3 + Vite 5.2 (`frontend/`).

**Primary Dependencies**: `client/`: `express`, `cors`, `multer` (ya en uso, sin nuevas dependencias de runtime previstas — el cliente HTTP es `fetch` nativo, ya usado). `frontend/`: `react-router-dom`, `framer-motion`, `lucide-react`, `react-markdown`, `tailwind-merge`, Tailwind CSS (ya en uso).

**Storage**: N/A del lado de las UIs — toda persistencia vive en el backend (spec 043). `client/` mantiene su `Map` de sesiones en memoria (deuda ya conocida, fuera de alcance salvo que bloquee una historia — no es el caso).

**Testing**: `client/` no tiene tooling de test hoy — se introduce `node:test` (nativo desde Node 18, sin dependencia nueva) + `supertest` para los endpoints Express. `frontend/` no tiene tooling de test hoy — se introduce Vitest + React Testing Library (integra nativo con Vite, mismo stack ya declarado en `devDependencies`).

**Target Platform**: navegador (ambas UIs son SPA/páginas servidas), contenedores Docker propios (`elea-rag-client`, `elea-guardian-frontend` vía nginx) reconstruidos por el instalador.

**Project Type**: Web — dos frontends independientes (Option 2 del template: backend ya existe en la 043, acá son los dos "frontend").

**Performance Goals**: sin objetivo nuevo de latencia; el badge de presupuesto debe reflejar el costo de una respuesta en <5s (SC-003, ya UX, no motor).

**Constraints**: `client/` sigue siendo el proxy fino hacia el backend — no debe convertirse en el lugar donde vive lógica de negocio nueva (autorización real vive en el backend, 043); el HTML/JS servido no debe llevar nombres de motor/proveedor ni en comentarios (US5). Reconstrucción de imágenes y actualización del instalador solo después de que el guion de integración (US6) pase completo.

**Scale/Scope**: piloto Elea — 2 UIs, un puñado de usuarios, 3 espacios reales a migrar sin pérdida.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación |
|---|---|
| I. Masking-First | Sin cambio de política — el Hub solo agrega `document_id` al enviar chunks (contrato 3 de la 043); no toca reglas de masking. **PASA**. |
| II. Compliance & Governance | Sin gates nuevos de compliance; la 044 consume, no decide. **PASA**. |
| III. Multi-Tenant | Las UIs no persisten nada propio; consumen `tenant_id` implícito en la sesión del backend. **PASA**. |
| IV. Client Onboarding as Data | El Hub Chat ES un `client_type=chat_ui` de primera clase (ya lo era); no se onboardea nada nuevo por código en esta spec. **PASA**. |
| V. Cost Governance | El Hub deja de usar sesión de admin para leer presupuesto (contrato 2) — cumple el espíritu de "ninguna request sin key válida user/group". **PASA, resuelve deuda declarada del lado UI**. |
| VI. LiteLLM-Native | N/A directo — las UIs no tocan el motor. **PASA**. |
| VII. Containerized & White-Label | US5 de esta spec (branding neutro en ambas UIs, prueba automática) es exactamente este principio aplicado a las dos interfaces. **PASA, resuelve deuda declarada**. |
| VIII. Pipeline Transparency | Sin cambios al Playground. **PASA, sin regresión**. |

**Constraints de seguridad**: ninguna credencial nueva en claro; la cabecera `X-Guardian-Acting-User`
la agrega el backend, no el cliente Node directamente desde datos no verificados (contrato 2 de la
043) — el plan de la 044 debe respetar esto: `client/server.js` sigue autenticando con el JWT de
sesión real contra el backend, y es el backend quien decide cuándo delega a una llave de servicio.

**Resultado**: PASA sin excepciones. Sin Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/044-hub-chat-panel-admin/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output (modelos de vista, no persistencia)
├── quickstart.md         # Phase 1 output — guion de integración con la 043 real
└── tasks.md               # Phase 2 output (/speckit-tasks — NO se crea acá)
```

### Source Code (repository root)

```text
client/                          # Eleia Hub
├── server.js                    # + guard de sesión en todos los endpoints de workspaces/hilos,
│                                 #   cliente HTTP hacia /workspaces y /users/me/budget del backend,
│                                 #   document_id por subida, mensajes de error neutros
├── public/
│   ├── index.html                # + estado vacío de "sin espacios", gestión de miembros,
│   │                              #   resumen de protección por documento, sin comentarios
│   │                              #   que nombren motores
│   └── eleia-logo.png            # (ya existe, nombre correcto)
└── tests/                        # NUEVO
    ├── contract/                  # contra dobles de los contratos 1-3 de la 043
    └── integration/

frontend/                         # Eleia Guardian
├── src/
│   ├── pages/
│   │   ├── UsersPage.tsx          # + editar rol/email/nombre/equipo, desactivar, dar de baja,
│   │   │                          #   sección plegada de cuentas de servicio
│   │   ├── DashboardPage.tsx      # + solo modelos reales
│   │   ├── CostsPage.tsx          # + consumo por persona (incluye actividad en espacios)
│   │   ├── SecurityPage.tsx       # + nombre neutro de la tarjeta NLP
│   │   └── WorkspacesUnassignedPage.tsx  # NUEVO — asignar miembros a espacios "sin asignar"
│   ├── services/
│   │   ├── api.ts                 # + engine_params (ya no litellm_params), endpoints de usuarios
│   │   │                          #   parciales/baja, workspaces sin asignar
│   │   └── branding.ts            # + título de pestaña enganchado a la marca configurada
│   └── index.html                 # <title> desde branding, no "Sentinel Secure AI Gateway"
└── tests/                         # NUEVO (Vitest + RTL)
    ├── contract/
    └── integration/
```

**Structure Decision**: se extiende el código existente en el lugar en ambos repos, sin
reescritura (mismo criterio que la 042). Se introduce tooling de test en los dos porque hoy no
existe ninguno y la spec exige pruebas de contrato (FR-031) y de branding (FR-030) — ambas
livianas y coherentes con el stack ya elegido de cada proyecto (Node nativo para `client/`, Vitest
para `frontend/`, que ya usa Vite).

## Complexity Tracking

*Sin violaciones — tabla omitida.*

## Constitution Check — post-diseño (re-evaluación tras Phase 1)

Con `data-model.md` y `quickstart.md` completos:

- **V. Cost Governance**: R1 confirma que el badge de presupuesto deja de depender de una sesión
  de admin — el autoservicio queda resuelto sin credenciales adicionales del lado del Hub. **PASA**.
- **VII. White-Label**: `quickstart.md` §5 y el contrato 6 de la 043 cubren juntos la verificación
  de que ningún nombre de motor/proveedor llega al navegador, en ambas UIs. **PASA**.
- **Reuse over Reinvent** (Development Workflow #2): R4 elige tooling de test ya alineado con cada
  stack (nativo de Node en `client/`, Vitest sobre Vite ya presente en `frontend/`) en vez de
  introducir un framework nuevo. **Cumple**.

**Resultado**: PASA sin excepciones nuevas. Sin `contracts/` propio — esta spec consume los 6
contratos de la 043, no publica contratos propios hacia otro sistema. Listo para `/speckit-tasks`.
