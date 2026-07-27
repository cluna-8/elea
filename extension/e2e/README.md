# Extensión — e2e vivo en Chrome (Playwright)

Verificación de la 028 cargando la extensión **renderizada** en un Chrome real (persistent
context con `--load-extension`). La extensión MV3 no se renderiza en un iframe: se prueba
cargada en el navegador (patrón 019/024).

## Requisitos
- `node` ≥ 20, `playwright` (`npm i playwright`) con chromium en caché.
- Correr con los browsers en caché: `export PLAYWRIGHT_BROWSERS_PATH="$HOME/Library/Caches/ms-playwright"`.
- Modo **headed** (`headless:false`): el service worker MV3 no registra confiable en headless.

## Armar la extensión renderizada del partner
```bash
make -C deploy build-extension-brand BRAND=camara-comercio
# → deploy/clients/camara-comercio/rendered/extension/
```

## Correr
```bash
EXT=../../deploy/clients/camara-comercio/rendered/extension   # o ruta absoluta
node load-smoke.mjs "$EXT"    # packaging + white-label (cc-guardian) + validación FR-010 + fail-closed UI + sin errores de consola
node connected.mjs  "$EXT"    # US2 conectar + US4 chip ámbar desde el server + US6 sesión (stub gateway inline)
node block.mjs      "$EXT"    # US5 overlay de bloqueo con el motivo REAL del server (fetch shape ChatGPT → guard → SW → gateway)
node perm-probe.mjs "$EXT"    # sanity: chrome.permissions disponible con el manifest de producción (optional_host_permissions)
```

## Qué NO cubre (a propósito)
- El **prompt nativo** de `chrome.permissions.request` no se puede clickear en Playwright:
  `connected.mjs`/`block.mjs` usan un fixture con `host_permissions` estático para el host del
  stub. `perm-probe.mjs` confirma que la API existe con el manifest de producción; el gesto de
  conceder el permiso se valida en el ensayo en vivo.
- Enmascarado/desenmascarado sobre el DOM real de ChatGPT/Claude (requiere login del proveedor):
  se cubre en el ensayo con la cuenta del piloto.

## Resultado de referencia (integrado A+B+C, 2026-07-24)
`load-smoke` 7/7 · `connected` 7/7 · `block` 5/5 · `perm-probe` API disponible.
