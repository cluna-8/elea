# Frontend e2e — verificación visual 029 (Playwright)

`029-screens.mjs`: carga las 6 páginas del piloto (+ Security) en Chrome real, saca screenshots,
y verifica **0 requests a Google Fonts** (air-gap) y **0 errores JS reales** (filtra los 500 por
backend ausente en dev). Siembra sesión admin en localStorage (`basa_session_token`/`basa_current_user`);
la app es un router por estado (App.tsx), navega clickeando la sidebar.

## Correr
```bash
# 1) deps del harness (separado del app para no bloatearlo):
cd frontend/e2e && npm install && cd ..
# 2) dev server del frontend (vite) en un puerto, p.ej. 5175:
npm run dev -- --port 5175 --strictPort
# 3) en otra terminal:
PLAYWRIGHT_BROWSERS_PATH="$HOME/Library/Caches/ms-playwright" \
  node e2e/029-screens.mjs http://localhost:5175 ./shots-029
```
`playwright` se declara en `frontend/e2e/package.json` (chromium en caché). El check falla (exit 1)
si alguna página no es clara, hay requests a Google Fonts, o hay errores JS reales.

## Resultado de referencia (integrado FND+PA+PB+PC+PD, 2026-07-24)
7/7 páginas tema claro (bg `#faf9f8`), 0 Google-Fonts, 0 errores JS reales.
