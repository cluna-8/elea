# Quickstart (028): armar y probar la extensión del partner

## Armar el paquete white-label (US1)

```bash
# Genera extension-camara-comercio.zip desde el brand-pack (marca cc-guardian)
make -C deploy build-extension-brand BRAND=camara-comercio
# o directo:
deploy/release/render_extension_brand.sh camara-comercio deploy/clients/camara-comercio/brand.json
```

Verificar white-label (US7):

```bash
make -C deploy check-whitelabel   # incluye test_extension_whitelabel.sh
```

El zip debe: no contener `sentinel`/`PoC`/nombre del motor/`localhost`; declarar los íconos del partner; tener `manifest.key` (ID estable).

## Incluir en el bundle de install (US1)

```bash
# El bundle air-gapped lista el zip de la extensión con su sha256 en el MANIFEST
NLP_ANALYZER_IMAGE=... BACKEND_IMAGE=... [...] deploy/release/bundle.sh camara-comercio
```

## Probar la conexión (US2) — en Chrome contra un gateway real

1. `chrome://extensions` → modo desarrollador → cargar el zip descomprimido.
2. Abrir el popup → ingresar la **URL del gateway** (p.ej. `https://gateway.camara.../api/v1/gw`) y la **API key** → Conectar.
3. Chrome pide permiso para el host → **Permitir**. La extensión conecta (login por `whoami`).
4. Cambiar la URL a otro gateway → Chrome vuelve a pedir permiso → agnóstico ✅.
5. URL remota sin `https` → rechazada.

## Honestidad y bloqueos (US4/US5)

- Con la extensión conectada, el panel muestra el chip **ámbar** "Detección por patrones · cobertura parcial" (no verde). El texto viene de `whoami.proteccion` (server).
- Enviar un prompt que dispare un bloqueo de política (p.ej. material que AI-Act bloquea) → la extensión frena y muestra el **motivo del server**, no "servicio no disponible".

## Sesión (US6)

- Cortar la red → estado "no verificado", la key se conserva; vuelve la red → reconecta solo.
- Revocar la plaza del usuario (baja en el admin) → en la próxima revalidación (~30 min) o al reabrir el navegador, la extensión pasa a "desconectado" con mensaje de plaza inactiva y borra la key.

## Backend (US4 server + US8a)

```bash
docker run --rm --network sentinel-guardian_sentinel-network -v <repo>:/repo -w /repo/backend \
  -e POSTGRES_HOST=db -e POSTGRES_PORT=5432 sentinel-guardian-backend \
  python -m pytest tests/ -q -k "whoami or proteccion or expires"
```
