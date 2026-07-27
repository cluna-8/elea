# Feature Specification: Rediseño de la UI del panel — estilo Azure Foundry (claro, lean)

**Feature Branch**: `029-ui-foundry`
**Created**: 2026-07-24
**Status**: Draft
**Input**: Pedido de JF — "la UI es muy horrible; quiero algo más como Azure Foundry, blanco, tipografías normales de Google Fonts, lean. EN/ES eventual. Piloto Cámara el martes." + 4 screenshots de Azure AI Foundry como referencia.

## Contexto

El panel admin (frontend React + Vite + Tailwind) hoy es OSCURO (navy `#0b1329` / cian `#00b4d8`), con Fira Sans **desde el CDN de Google Fonts**. El piloto Cámara (install del martes) muestra este panel al admin del cliente. Se rediseña a un estilo **claro tipo Azure AI Foundry / Fluent**: canvas gris muy claro, superficies blancas con bordes finos, sidebar clara con acento azul, tipografía limpia (Inter), pills de estado semánticas, mucho aire.

**Alcance del piloto: 6 páginas** — Login, Panel Principal (Dashboard), Firewall en vivo, Usuarios & Presupuestos, Modelos & Ollama, Playground — más el **shell** (sidebar/topbar) y el arreglo del auto-guardado del toggle de headroom en Seguridad. El resto de páginas heredan tokens y shell (no rotas), pero su restyle fino es fast-follow.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - El admin ve un panel claro, limpio y coherente (Priority: P1) · MUST-piloto

El admin del cliente (Cámara) abre el panel y ve una interfaz clara, ordenada y profesional —estilo Azure Foundry— en vez de la actual oscura y recargada. Navega entre las 6 páginas del piloto y todas comparten el mismo lenguaje visual (canvas claro, cards blancas, sidebar con acento, pills de estado, tipografía Inter).

**Why this priority**: Es lo que el cliente ve el martes. Una UI "muy horrible" resta credibilidad al producto de seguridad que se está vendiendo.

**Independent Test**: Levantar el frontend, recorrer las 6 páginas del piloto y verificar tema claro coherente (canvas, cards, sidebar, tipografía, pills) sin restos del tema oscuro ni errores de consola.

**Acceptance Scenarios**:
1. **Given** el panel, **When** el admin entra, **Then** ve canvas claro, sidebar izquierda clara con el item activo marcado en azul, cards blancas con borde fino, y tipografía Inter — no el tema oscuro anterior.
2. **Given** cualquiera de las 6 páginas del piloto, **When** el admin la abre, **Then** comparte tokens (colores, tipografía, espaciado, cards, pills) con las demás — coherencia visual.
3. **Given** un estado (ok/advertencia/peligro/info), **When** se muestra, **Then** usa una pill semántica legible (fondo tenue + texto oscuro), distinta del color de acento.

### User Story 2 - Marca del cliente respetada, sin romper el tema claro (Priority: P1) · MUST-piloto

La marca del cliente sigue configurándose en runtime (`/branding/brand.json`, spec 020), pero el tema claro es **fijo**: solo el **acento** (primary) se tiñe con la marca. El logo del cliente aparece en la sidebar.

**Why this priority**: El white-label no puede romperse (Constitución VII), pero un brand-pack con colores oscuros (como el de Cámara hoy) no debe volver a oscurecer todo el panel.

**Independent Test**: Con un brand.json que trae `colors.background`/`panel` oscuros, verificar que el canvas SIGUE claro y solo el acento toma `colors.primary`.

**Acceptance Scenarios**:
1. **Given** un brand.json con `primary` propio, **When** carga el panel, **Then** botones primarios / item activo / links usan ese acento; el canvas y las superficies siguen claros.
2. **Given** un brand.json con `background`/`panel` oscuros (caso Cámara actual), **When** carga el panel, **Then** el tema claro NO se rompe (esos overrides ya no oscurecen el chrome).
3. **Given** el brand del cliente, **When** carga, **Then** su logo aparece en la sidebar.

### User Story 3 - Sin dependencia de red para las fuentes (air-gap) (Priority: P1) · MUST-piloto

Las tipografías se **auto-hospedan** en el bundle (woff2 + `@font-face`), sin `@import` a `fonts.googleapis.com`. Una instalación air-gapped (caso on-prem del producto) no puede depender de un CDN externo.

**Why this priority**: Hoy `index.css` importa del CDN de Google; en air-gap ese fetch falla y la tipografía cae a la del sistema → la UI que el cliente ve no es la diseñada. Además es una fuga de egress en un producto que se vende como 0-egress.

**Independent Test**: Cargar el frontend **sin red externa** y verificar que la tipografía renderiza la fuente auto-hospedada (no una fallback del sistema) y que no hay requests a `fonts.googleapis.com`/`fonts.gstatic.com`.

**Acceptance Scenarios**:
1. **Given** el frontend buildeado, **When** se inspecciona la red al cargar, **Then** 0 requests a dominios de Google Fonts; las fuentes salen de assets locales.
2. **Given** el `index.css`, **When** se revisa, **Then** no hay `@import url('https://fonts.googleapis...')`.

### User Story 4 - El toggle de headroom guarda solo (sin "Guardar Cambios") (Priority: P2) · SHOULD

En Seguridad, el toggle de headroom (y toggles de la misma familia) persiste al instante al cambiarlo, sin requerir un botón "Guardar Cambios" aparte que el usuario olvida.

**Why this priority**: Bug de UX identificado: el usuario cambia el toggle, cree que quedó guardado, y no lo estaba. Chico pero real para el piloto.

**Independent Test**: Cambiar el toggle y verificar que la persistencia se dispara sola (llamada de guardado), sin depender de un botón aparte; recargar y ver el estado conservado.

**Acceptance Scenarios**:
1. **Given** el toggle de headroom, **When** el admin lo cambia, **Then** se guarda solo (optimista, con manejo de error) — no queda pendiente de un botón.

### Edge Cases
- **Brand.json ausente (dev)**: cae al default (acento azul Foundry, tema claro), sin romper.
- **Contraste/accesibilidad**: texto sobre canvas/cards cumple contraste legible (WCAG AA en texto de cuerpo).
- **Tablas anchas / contenido ancho**: scroll horizontal en su propio contenedor, el body nunca hace scroll lateral.
- **Páginas fuera del alcance del piloto**: heredan tokens y shell (no se rompen visualmente), aunque su restyle fino quede para después.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El sistema MUST presentar un tema CLARO (canvas gris muy claro, superficies blancas, bordes finos, texto oscuro) en el shell y en las 6 páginas del piloto.
- **FR-002**: El shell MUST tener sidebar izquierda clara con el item activo marcado con acento azul, logo del cliente, e info de usuario/salir.
- **FR-003**: La tipografía MUST ser una fuente limpia tipo Segoe/Fluent (Inter) para texto y una mono para IDs/keys, **auto-hospedadas** (sin CDN).
- **FR-004**: Los estados MUST mostrarse como pills semánticas (ok/advertencia/peligro/info) con fondo tenue + texto oscuro, distintas del color de acento.
- **FR-005**: El tema claro MUST ser fijo; solo el **acento** (primary) MUST poder teñirse por la marca del cliente en runtime (`/branding/brand.json`). Los overrides de `background`/`panel` de un brand-pack NO MUST oscurecer el chrome.
- **FR-006**: El frontend MUST NOT depender de un CDN externo para las fuentes (0 requests a Google Fonts); MUST funcionar air-gapped.
- **FR-007**: Las 6 páginas del piloto MUST compartir un set de componentes/tokens comunes (coherencia): al menos Card, Pill/Badge, PageHeader, Button, Table.
- **FR-008**: El toggle de headroom (y su familia) en Seguridad MUST persistir al cambiar, sin requerir un botón "Guardar Cambios" separado.
- **FR-009**: El rediseño MUST NOT romper la funcionalidad existente (datos, llamadas API, gating por rol, navegación).
- **FR-010**: El logo y el nombre del cliente MUST seguir viniendo del brand-pack (no horneados).

### Key Entities
- **Tokens de diseño**: paleta clara (canvas, surface, border, text primary/secondary/tertiary), acento (brand primary), semánticos (ok/warn/danger/info), tipografía (Inter, mono), radios, sombras. Fuente única (CSS vars + tailwind.config).
- **Kit de componentes**: Card, Pill/StatusBadge, PageHeader, Button, Table (+ los que hagan falta) reutilizados por las páginas.
- **Shell**: sidebar + área de contenido; consume tokens y marca.

## Success Criteria *(mandatory)*

- **SC-001**: Las 6 páginas del piloto renderizan en tema claro coherente, sin restos del tema oscuro, 0 errores de consola.
- **SC-002**: Con un brand.json de colores oscuros, el panel sigue claro (solo el acento cambia).
- **SC-003**: 0 requests a dominios de Google Fonts al cargar; la tipografía diseñada renderiza sin red externa.
- **SC-004**: El toggle de headroom persiste solo (verificado en vivo) y sobrevive un reload.
- **SC-005**: Screenshots de las 6 páginas para aprobación del look FINAL por JF.

## Assumptions
- **Aprobación final**: JF revisa y aprueba el look FINAL cuando vuelve (esta feature deja las 6 páginas implementadas y screenshoteadas, listas para su OK y ajustes).
- **EN/ES**: los textos quedan en ES (como hoy); la i18n EN/ES completa es fast-follow (JF: "eventualmente").
- **Router**: se mantiene el router por estado de `App.tsx` (no se migra a react-router en esta feature).
- **Páginas no-piloto**: heredan tokens/shell; su restyle fino es fast-follow, no bloquea el martes.
- **Referencia visual**: los 4 screenshots de Azure AI Foundry de JF (canvas claro, cards blancas con borde, nav lateral, acento azul, pills, mucho aire).
