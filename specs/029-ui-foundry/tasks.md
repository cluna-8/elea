# Tasks: Rediseño UI Azure Foundry (029)

**Input**: [spec.md](./spec.md), [plan.md](./plan.md). **Orden**: Fundación (A) → Páginas (B) → verificación.
Rama `029-ui-foundry` (worktree desde `dev-fran`). Nunca commit directo a `dev-fran`/`main`.

## Fase A — Fundación (bloqueante)
- [ ] **T001** [A] `index.css`: reemplazar el `@import` del CDN por `@font-face` local (Inter + mono woff2); redefinir CSS vars a la paleta CLARA (canvas/surface/border/text*/semánticos); body a canvas claro + Inter. (FR-001/003/006)
- [ ] **T002** [A] `tailwind.config.js`: paleta clara + tokens semánticos (`ok/warn/danger/info`) + `surface`/`border`/`text.*` como vars + `fontFamily` Inter/mono; sombras suaves. (FR-001/004/007)
- [ ] **T003** [A] `assets/fonts/`: woff2 de Inter (400/500/600/700) + mono; declarados en `@font-face`. Sin red externa. (FR-006)
- [ ] **T004** [A] `services/branding.ts`: aplicar **solo `primary`** de `brand.json` a la var de acento; ignorar `background`/`panel` (no oscurecer). Logo/nombre siguen. (FR-005/010)
- [ ] **T005** [A] `components/ui/`: kit común — `Card`, `StatusBadge`(pill), `PageHeader`, `Button`, `Table` (+ `Field`/`Toggle` si aplica), con API clara y tokens. (FR-007)
- [ ] **T006** [A] `App.tsx`: shell claro — sidebar (logo, nav item activo con acento azul, usuario/salir), área de contenido con canvas claro. (FR-002)

## Fase B — Páginas (paralelo, reusan A)
- [ ] **T007** [B] `LoginPage.tsx` + `DashboardPage.tsx`: restyle claro con el kit. (FR-001/007)
- [ ] **T008** [B] `FirewallMonitorPage.tsx` + `ModelsPage.tsx`: restyle claro con el kit. (FR-001/007)
- [ ] **T009** [B] `PlaygroundPage.tsx` + `SecurityPage.tsx`: restyle claro; **fix del auto-save del toggle de headroom** (persistir al cambiar, sin botón aparte). (FR-001/007/008)
- [ ] **T010** [B] `UsersPage.tsx` (grande): restyle claro con el kit, tabla/pills/cards. (FR-001/007)

## Fase C — Verificación & Polish
- [ ] **T011** [P] `speckit-analyze` (consistencia spec↔plan↔tasks) antes de implementar.
- [ ] **T012** Playwright: levantar dev server, screenshots de las 6 páginas, **0 errores de consola**, **0 requests a Google Fonts**, tema claro coherente. (SC-001/003/005)
- [ ] **T013** Playwright: auto-save del toggle de headroom en vivo + sobrevive reload. (SC-004)
- [ ] **T014** Verificar override de marca: brand.json con colores oscuros → panel sigue claro, acento cambia. (SC-002)
- [ ] **T015** Review Codex + suite frontend (`npm run build` + lint) verde antes de dejar PR-ready. Screenshots para OK final de JF.

## Fuera de alcance (fast-follow)
- i18n EN/ES completa. Restyle fino de las páginas no-piloto (Costs, Governance, Compliance, Audit, Docs) — heredan tokens/shell, no se rompen.
