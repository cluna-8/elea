# Extensión — e2e vivo en Chrome (Playwright)

Verificación de la 028 cargando la extensión **renderizada** en un Chrome real (persistent
context con `--load-extension`). La extensión MV3 no se renderiza en un iframe: se prueba
cargada en el navegador (patrón 019/024).

## Requisitos
- `node` ≥ 20, `playwright` (`npm i playwright`) con chromium en caché.
- Correr con los browsers en caché: `export PLAYWRIGHT_BROWSERS_PATH="$HOME/Library/Caches/ms-playwright"`.
- Modo **headed** (`headless:false`): el service worker MV3 no registra confiable en headless.

> **Gotcha** — `npm i` resuelve `playwright ^1.61.1` a la última minor, que pide una revisión de
> chromium que la caché puede no tener (`Executable doesn't exist at …/chromium-<rev>`). Se
> arregla con `npx playwright install chromium` (con `PLAYWRIGHT_BROWSERS_PATH` ya exportado);
> no es un fallo del harness.

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
node offline.mjs    "$EXT"    # FR-019/FR-023 gateway INALCANZABLE: key conservada + no_verificado + envío frenado (0 fuga) + recuperación
node perm-probe.mjs "$EXT"    # sanity: chrome.permissions disponible con el manifest de producción (optional_host_permissions)
```

`offline.mjs` reproduce el caso del piloto de la Cámara (30-jul-2026): la laptop sale de la LAN
y el gateway deja de ser alcanzable. Apaga el stub a mitad del test y verifica que la sesión NO
se cierra (key conservada, `sesion_estado="no_verificado"`, banner ámbar en el popup), que la
página carga normal y que el **envío** se frena con el modal «Servicio no disponible» sin que el
prompt llegue nunca al proveedor (contador de hits en el servidor de página). Cierra
reencendiendo el stub: el envío siguiente pasa sin reconectar a mano.

> Detalle observado, no un fallo: tras recuperar la red el envío funciona de inmediato, pero
> `sesion_estado` sigue en `no_verificado` (y el popup, en ámbar) hasta el próximo `whoami` —
> alarma de ~30 min, reapertura del navegador o botón «Conectar». Sólo `setConectado` lo revierte;
> el camino de `inspect` no toca el estado de sesión.

## Qué NO cubre (a propósito)
- El **prompt nativo** de `chrome.permissions.request` no se puede clickear en Playwright:
  `connected.mjs`/`block.mjs` usan un fixture con `host_permissions` estático para el host del
  stub. `perm-probe.mjs` confirma que la API existe con el manifest de producción; el gesto de
  conceder el permiso se valida en el ensayo en vivo.
- Enmascarado/desenmascarado sobre el DOM real de ChatGPT/Claude (requiere login del proveedor):
  se cubre en el ensayo con la cuenta del piloto.

## Resultado de referencia (integrado A+B+C, 2026-07-24)
`load-smoke` 7/7 · `connected` 7/7 · `block` 5/5 · `perm-probe` API disponible.

## Resultado de referencia (2026-07-30, macOS arm64, chromium 1234)
`connected` 5/5 · `block` 5/5 · `offline` 16/16 — cada uno corrido 2 veces seguidas, sin flakiness.
