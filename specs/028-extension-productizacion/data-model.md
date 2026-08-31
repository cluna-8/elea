# Data Model (028)

La 028 casi no toca datos persistidos. Las "entidades" son configuración y forma de mensajes, no tablas nuevas.

## Brand-pack del partner (existente, se extiende su uso)

`deploy/clients/<slug>/brand.json` — fuente única de la identidad visible. Campos que consume el render de la extensión:
- `nombre_producto` / display name → `manifest.name`
- `descripcion` → `manifest.description`
- íconos de marca (16/48/128) → `manifest.icons` + archivos del zip

No agrega campos nuevos si el brand-pack ya los tiene; si falta alguno, se documenta el mínimo requerido para la extensión.

## Paquete de extensión del partner (artefacto generado)

`extension-<slug>.zip` producido por `render_extension_brand.sh`:
- Identidad visible del partner (del brand-pack).
- `manifest.key` = clave pública base64 de un par RSA **por partner** → identificador de extensión **estable** entre carpetas/instalaciones. La privada vive fuera del repo.
- **No** contiene dirección de gateway (agnóstico).
- Versión con fuente única (el `manifest.version`).

## Conexión del usuario (runtime, `chrome.storage.local`)

- `sentinel_gateway`: URL del gateway (editable; default opcional pre-cargado desde `config.js`).
- `sentinel_key`: API key del usuario (no se re-inyecta ni persiste antes de validar — hardening #45).
- `sentinel_connected` / estado de sesión: **un solo dueño** (el service worker). Estados: `conectado` / `no_verificado` (sin red, key conservada) / `desconectado` (401/403, key borrada).
- Permiso de host: concedido en runtime vía `chrome.permissions` (no es storage propio; lo administra Chrome).

## Bloque `proteccion` (respuesta de whoami, no persistido)

Ver [contracts/whoami-proteccion.md](./contracts/whoami-proteccion.md). Calculado server-side en cada `whoami`; la extensión lo muestra, no lo guarda como verdad.

## `api_keys.expires_at` (existente — US8a)

Columna ya presente (`budget.py:52`), hoy **ignorada** por `_resolve_attribution`. US8a agrega el filtro `expires_at IS NULL OR expires_at > now()`. Sin cambio de esquema.

## Fuera de alcance (US9 diferido)

- `SURFACES` (`sentinel_governance.py:94`) — agregar valores de navegador (`chatgpt-web`/`claude-web`) + migración del `CHECK tool_type` (`budget.py:89`). Requiere coordinación con Cristian antes del freeze 027. **No en esta feature.**
