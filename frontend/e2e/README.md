# Frontend e2e — verificación visual 029 (Playwright)

`029-screens.mjs`: carga las 6 páginas del piloto (+ Security) en Chrome real, saca screenshots,
y verifica **0 requests a Google Fonts** (air-gap) y **0 errores JS reales** (filtra los 500 por
backend ausente en dev). Siembra sesión admin en localStorage (`sentinel_session_token`/`sentinel_current_user`);
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

---

# E2E de SSO — 017 US2 · T018 (Playwright)

`017-sso-e2e.mjs`: mide **SC-003** —que el login por directorio corporativo emite la misma
sesión que el login local, y que sin el flag `sso` la superficie no es alcanzable— contra un
tenant **Entra real**, dejando una captura por paso.

Una fase por estado del backend, porque cada una exige una licencia/configuración distinta y
un script de navegador no reinicia el backend. El procedimiento completo —qué estado poner
antes de cada fase, los identificadores del tenant de prueba y las trampas conocidas— está en
**`specs/017-auth-rbac-sso/RUNBOOK-e2e-sso.md`**; acá va sólo cómo se invoca.

```bash
cd frontend/e2e && npm install && cd ..
PLAYWRIGHT_BROWSERS_PATH="$HOME/Library/Caches/ms-playwright" \
  node e2e/017-sso-e2e.mjs http://localhost:8090 ./shots-017-sso --fase=sembrado \
  --usuario=<admin> --clave='<clave>' \
  --tenant-id=<directory-id> --client-id=<application-id> \
  --redirect-uri=http://localhost:8090/sso/callback
```

Fases: `sin-licencia` · `licenciado-sin-config` · `sembrado` · `degradacion` · `login-real`.
Exit 1 si algún paso de la fase falla. Escribe `reporte-<fase>.json` junto a las capturas.

El puerto **8090 no es negociable**: la URI de retorno registrada en el directorio lo nombra,
y OIDC exige que la del canje sea idéntica a la del inicio.

`login-real` abre el navegador **con cabeza** y espera a una persona: el segundo factor del
cliente no se automatiza a propósito — falsificar un MFA sería falsificar justo lo que este
E2E existe para probar.

## Resultado de referencia (main `02b1181`, 2026-08-24)
`sin-licencia` 7/7 · `licenciado-sin-config` 5/5 · `sembrado` 13/13 (el navegador llegó a la
pantalla de acceso real de Microsoft) · `degradacion` 5/5 (Microsoft rechazó el canje y sólo
cayó el camino SSO). **`login-real` no corrida**: falta el client secret y el usuario piloto
del tenant de prueba. Mientras esa fase no tenga fecha, SC-003 está medido a medias.
