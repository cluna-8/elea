# Implementation Plan: Rediseño UI Azure Foundry (029)

**Branch**: `029-ui-foundry` | **Date**: 2026-07-24 | **Spec**: [spec.md](./spec.md)

## Summary
Virar el panel admin (React+Vite+Tailwind) de OSCURO a un tema CLARO tipo Azure Foundry, en 2 fases: (A) **fundación** — tokens claros (CSS vars + tailwind.config), fuentes auto-hospedadas (Inter, sin CDN), kit de componentes común (Card/Pill/PageHeader/Button/Table) y shell (App.tsx sidebar/topbar); (B) **páginas** — restyle de las 6 del piloto reusando la fundación + fix del auto-save del toggle de headroom. El tema claro es fijo; solo el acento se tiñe por marca (branding.ts deja de aplicar background/panel).

## Technical Context
**Language**: TypeScript/React 18, Vite 5, TailwindCSS 3, lucide-react, framer-motion.
**Fuentes**: Inter (texto) + mono, **woff2 auto-hospedadas** en `frontend/src/assets/fonts/` con `@font-face`; se quita el `@import` del CDN de `index.css`.
**Theming**: CSS vars en `index.css` + `tailwind.config` (paleta clara + semánticos). Marca runtime via `/branding/brand.json` → **solo `primary`** (branding.ts).
**Testing**: Vite dev server + **Playwright** (screenshots de las 6 páginas, 0 errores de consola, 0 requests a Google Fonts, auto-save del toggle en vivo).
**Constraints**: no romper datos/API/gating por rol; air-gap (0 CDN); white-label (logo/nombre/acento del brand-pack); contraste WCAG AA en cuerpo.

## Constitution Check
- **Principio VII (white-label)**: logo/nombre/acento del brand-pack; tema neutro (no marca del fabricante horneada). ✅
- **Air-gap / 0-egress**: fuentes auto-hospedadas cierran una fuga de egress preexistente (CDN). ✅
- Sin violaciones que requieran Complexity Tracking.

## Fases
- **Fase A — Fundación (bloqueante, 1 minion)**: `index.css` (vars claras + @font-face), `tailwind.config.js` (paleta clara + tokens semánticos + Inter), fuentes woff2 en `assets/fonts/`, `services/branding.ts` (solo `primary`), kit `components/ui/*` (Card, Pill/StatusBadge, PageHeader, Button, Table), y `App.tsx` (shell Foundry). Debe landear antes que las páginas.
- **Fase B — Páginas (paralelo, minions por página/grupo)**: Login+Dashboard · Firewall+Models · Playground+Security(+fix headroom) · Users (grande, solo). Cada uno reusa la fundación; cero solape de archivos.
- **Verificación**: dev server + Playwright (screenshots 6 páginas, consola limpia, sin Google Fonts, auto-save headroom); review Codex; screenshots para el OK final de JF.

## Project Structure
```
frontend/src/
├── index.css              # A: vars claras + @font-face (sin CDN)
├── tailwind.config.js     # A: paleta clara + semánticos + Inter   (nota: está en frontend/, no en src/)
├── assets/fonts/*.woff2   # A: Inter + mono auto-hospedadas
├── services/branding.ts   # A: aplica solo `primary`
├── components/ui/*.tsx     # A: Card, Pill/StatusBadge, PageHeader, Button, Table (NUEVO)
├── App.tsx                # A: shell (sidebar/topbar) claro
└── pages/
    ├── LoginPage.tsx           # B
    ├── DashboardPage.tsx       # B
    ├── FirewallMonitorPage.tsx # B
    ├── ModelsPage.tsx          # B
    ├── PlaygroundPage.tsx      # B
    ├── SecurityPage.tsx        # B (+ fix auto-save headroom)
    └── UsersPage.tsx           # B (grande, solo)
```

## Complexity Tracking
N/A.
