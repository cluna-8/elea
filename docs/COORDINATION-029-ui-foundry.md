# COORDINATION 029 — Rediseño UI Azure Foundry (claro, lean)

**Orquestador**: Claude (srdev-claude). **Rama**: `029-ui-foundry` (worktree desde `dev-fran`).
**Regla dura**: NUNCA commit directo a `dev-fran`/`main`. Minions en worktrees; el orquestador integra + verifica.
Artefactos SDD: [spec.md](../specs/029-ui-foundry/spec.md) · [plan.md](../specs/029-ui-foundry/plan.md) · [tasks.md](../specs/029-ui-foundry/tasks.md).

## Objetivo
Panel admin (React+Vite+Tailwind) de OSCURO → CLARO estilo Azure AI Foundry, para el piloto Cámara (martes). 6 páginas: Login, Dashboard, Firewall, Users, Models, Playground + shell + fix auto-save del toggle headroom. JF aprueba el look FINAL cuando vuelve.

## Design tokens (FUENTE ÚNICA — la fundación los fija; las páginas SOLO los consumen)

**Paleta clara (CSS vars en `index.css` + `tailwind.config`):**
| Token | Valor | Uso |
|-------|-------|-----|
| `--canvas` | `#faf9f8` | fondo de página (área de trabajo) |
| `--surface` | `#ffffff` | cards, sidebar, inputs |
| `--surface-2` | `#f3f2f1` | headers de tabla, hovers sutiles, chips neutros |
| `--border` | `#e1dfdd` | bordes de card/input (1px) |
| `--border-strong` | `#c8c6c4` | divisores marcados |
| `--text` | `#242424` | texto primario |
| `--text-secondary` | `#616161` | secundario/labels |
| `--text-tertiary` | `#8a8886` | terciario/placeholder |
| `--primary` | `#0f6cbd` | **acento** (brand-overridable) — botón primario, item activo, links |
| `--primary-hover` | `#115ea3` | hover del acento |
| `--primary-tint` | `#f3f9fd` | fondo del item activo / selección |
| ok | bg `#dff6dd` / text `#0e700e` | pill éxito |
| warn | bg `#fff4ce` / text `#835c00` | pill advertencia (análogo al chip ámbar de la extensión) |
| danger | bg `#fde7e9` / text `#a4262c` | pill peligro |
| info | bg `#f3f9fd` / text `#0f6cbd` | pill info |

- Radios: `6px` inputs/pills, `8px` cards. Sombra card: `0 1px 2px rgba(0,0,0,.06), 0 0 1px rgba(0,0,0,.08)`.
- **Tipografía**: **Inter** (400/500/600/700) texto; **JetBrains Mono** (o similar) para IDs/keys/mono. **Auto-hospedadas** (woff2 en `assets/fonts/`, `@font-face`). Escala: h1 24/600, h2 18/600, h3 15/600, body 14/400, label 12/600 uppercase `tracking-wide` color `--text-secondary`.
- **Densidad**: tablas fila 44–48px, header `--surface-2` sticky, borde inferior `--border`. Espaciado generoso (cards p-5/p-6, gaps 16–24px).

**Regla de marca (FR-005)**: el tema claro es FIJO. `branding.ts` aplica del `brand.json` **solo `colors.primary`** a `--primary` (y deriva `--primary-hover`/`--primary-tint` si querés). **IGNORA** `colors.background`/`colors.panel` (el brand-pack de Cámara los trae oscuros y NO deben oscurecer el chrome). Logo y nombre siguen viniendo del brand-pack.

## Kit de componentes (`frontend/src/components/ui/`) — la fundación lo crea, las páginas lo reusan

APIs mínimas (props sugeridas; el minion A ajusta con sentido, pero mantené estos nombres para que las páginas los usen sin sorpresas):
- `Card` — `{ title?, actions?, className?, children }` → superficie blanca, borde `--border`, radio 8, sombra suave, padding.
- `PageHeader` — `{ title, subtitle?, actions? }` → h1 + subtítulo + zona de acciones a la derecha.
- `StatusBadge` — `{ tone: 'ok'|'warn'|'danger'|'info'|'neutral', children }` → pill semántica (fondo tenue + texto oscuro).
- `Button` — `{ variant: 'primary'|'secondary'|'ghost'|'danger', size?, ...btn }` → primary usa `--primary`.
- `Table` — thead/tbody helpers o un `<Table columns rows>` simple; header `--surface-2`, filas con borde inferior; contenedor con `overflow-x:auto`.
- (Opcional) `Field` (label+input), `Toggle` (switch accesible) si simplifican las páginas.

Todos consumen tokens (nada de hex hardcodeado en las páginas). Accesibilidad: focus ring visible (`ring-2 ring-[--primary]`), contraste AA en cuerpo.

## Roster de minions

### Fase A — Fundación (1 minion, BLOQUEANTE, corre primero)
**Minion FND** — rama `029-fnd`. POSEE: `frontend/src/index.css`, `frontend/tailwind.config.js`, `frontend/src/assets/fonts/**` (NUEVO), `frontend/src/services/branding.ts`, `frontend/src/components/ui/**` (NUEVO), `frontend/src/App.tsx`.
Entrega: tokens claros, fuentes auto-hospedadas (sin CDN), kit de componentes, shell Foundry, branding solo-acento. **NO** toca `pages/`.
Verifica: `cd frontend && npm run build` OK; `npm run lint` sin nuevos errores; `grep -rn 'fonts.googleapis\|fonts.gstatic' src/` → vacío; dev server levanta y el shell se ve claro (screenshot).

### Fase B — Páginas (paralelo, tras integrar A; cero solape)
Todas ramas desde el HEAD de `029-ui-foundry` YA con la fundación integrada. Cada minion POSEE solo sus archivos de `pages/` y reusa `components/ui/`.
- **Minion PA** — rama `029-p-a`: `pages/LoginPage.tsx` + `pages/DashboardPage.tsx`.
- **Minion PB** — rama `029-p-b`: `pages/FirewallMonitorPage.tsx` + `pages/ModelsPage.tsx`.
- **Minion PC** — rama `029-p-c`: `pages/PlaygroundPage.tsx` + `pages/SecurityPage.tsx` (+ **fix auto-save toggle headroom**: persistir al `onChange`, optimista con manejo de error; sin botón "Guardar Cambios" separado para ese toggle).
- **Minion PD** — rama `029-p-d`: `pages/UsersPage.tsx` (1427 líneas, solo).
Cada uno: reemplazar clases oscuras hardcodeadas (`slate-700/800`, `text-white`, `bg-background/panel` oscuro) por el kit/tokens claros; mantener TODA la lógica (datos, API, gating, handlers). Verifica: `npm run build` OK, la página renderiza clara sin restos oscuros, 0 errores de consola.

## Integración (orquestador)
1. Integro FND primero, verifico build + shell claro (Playwright screenshot).
2. Reviso cada page-minion, integro, verifico build.
3. Playwright: dev server, screenshots de las 6 páginas, 0 errores de consola, 0 requests a Google Fonts, auto-save del toggle headroom, override de marca (brand oscuro → sigue claro).
4. Codex review. NO merge a dev-fran (paso 3 joint con JF). Screenshots para su OK final.

## Verificación de integración (orquestador, 2026-07-24)

- **Merge**: FND → PA(login+dash) → PD(users) → PB(firewall+models) → PC(playground+security+auto-save headroom). Todos limpios. `npm run build` integrado OK.
- **Playwright vivo (headed, dev server vite)** — `frontend/e2e/029-screens.mjs`: 7 páginas tema claro (bg `#faf9f8`), **0 requests a Google Fonts** (air-gap ✓), 0 errores JS reales (los únicos son `Failed to fetch` por backend ausente en dev). Screenshots revisados por el orquestador: Login/Dashboard/Users/Firewall/Security/Playground se ven Foundry-claro coherentes.

### Codex — trayectoria de convergencia (§11.9)

| Pase | P1 | P2 | P3 | Notas |
|------|----|----|----|-------|
| 1 | 0 | 2 | 1 | (a) páginas legacy no-piloto quedan ilegibles (white-on-white) por el remap `bg-panel`→claro; (b) harness no declaraba playwright; (c) harness no forzaba isLight. |
| 2 | — | — | — | tras fixes (pendiente) |

**Acciones pase 1**:
- **P2 (a) legacy ilegibles** → barrido de legibilidad de las 5 páginas no-piloto (Costs/Governance/Compliance/Audit/Docs) a tokens claros (minions 029-legacy-a/b). Real: son alcanzables desde la sidebar y romperían el demo.
- **P2 (b) playwright** → `frontend/e2e/package.json` declara playwright (harness corre desde install limpio). Arreglado (`1d05b82`).
- **P3 (c) isLight** → el harness ahora falla (exit 1) si alguna página no es clara. Arreglado (`1d05b82`).

## Definition of Done
- [ ] 6 páginas + shell en tema claro coherente, sin restos oscuros, 0 errores de consola.
- [ ] Fuentes auto-hospedadas, 0 requests a Google Fonts (air-gap).
- [ ] Brand oscuro no rompe el tema claro; acento del brand aplicado; logo del cliente en sidebar.
- [ ] Toggle headroom auto-guarda + sobrevive reload.
- [ ] `npm run build` + lint verdes. Codex sin P1. Screenshots para JF.
- [ ] Rama `029-ui-foundry` PR-ready contra `dev-fran` (NO mergeada).
