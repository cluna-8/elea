# Eleia Hub (`client/`)

Cliente web de Eleia (Node 20 / Express, una sola página en `public/index.html`). Es un
**conector fino**: la identidad, el presupuesto, el registro de espacios y toda la seguridad
viven en Guardian; los datos viven en los motores; el Hub solo une las piezas. Diseño y
contratos en [`specs/050-ia-hub-conector-motores/`](../specs/050-ia-hub-conector-motores/spec.md).

## Qué hace y qué no

| Hace | No hace |
|---|---|
| Login contra Guardian y sesión de la persona (cookie, en memoria) | No tiene usuarios ni contraseñas propias |
| Chat con documentos (motor de documentos) y chat directo con modelo `auto` (Guardian) | No enmascara: los archivos suben crudos al motor local; Guardian enmascara lo que va al modelo |
| Planillas: espacios de Excel/CSV, preguntas en lenguaje natural, diccionario de datos (motor tabular) | No guarda mensajes de chat (viven en cada motor) |
| Presentaciones desde cualquier respuesta, con plantillas modelo y datos de una planilla (Presenton) | No llama al motor `engine:4000` directamente, solo al backend de Guardian |
| "Mis archivos": presentaciones generadas, por persona | No arranca sin Guardian (decisión del dueño: hereda el SSO) |
| Historial en Planillas por hilo y chat personal con historial (spec 051): lo guardan los motores, el Hub lo muestra | No guarda mensajes ni tiene base propia: Guardian registra los hilos, cada motor guarda sus turnos |
| Proxy de administración de plantillas (puerto 8097, solo admins) | Ningún motor es obligatorio: la UI oculta lo que no está configurado |

Antes de tocar un motor sobre un espacio, el Hub verifica la membresía contra Guardian
(`GET /workspaces/{id}`); 403 ⇒ el motor nunca es llamado.

## Rutas (contrato completo: `specs/050-.../contracts/02-hub-api.md`)

- `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/user/current`, `GET /api/user/budget`, `GET /api/models`, `GET /api/branding`, `GET /api/features`
- Documentos: `GET/POST /api/workspaces*`, `POST /api/workspaces/upload`, `POST /api/threads/*`, `GET /api/workspaces/{slug}/messages`, `POST /api/chat`
- Planillas: `GET/POST /api/tabular/workspaces`, `GET/POST /api/tabular/workspaces/{id}/files`, `DELETE .../files/{file_id}`, `PUT .../dictionary`, `POST .../query` (`thread_key` opcional)
- Hilos de planillas (spec 051): `GET/POST .../threads`, `PATCH/DELETE .../threads/{key}`, `GET .../threads/{key}/turns`. El hilo se registra en Guardian a nombre de la persona (mismo registro que Documentos) y el motor guarda los turnos.
- Chat personal (spec 051): `POST /api/workspaces/personal` crea (una vez) o devuelve el espacio "Mi chat · <usuario>", sin documentos, con hilos e historial; la UI lo abre por defecto.
- Presentaciones: `GET /api/presentations/templates`, `GET .../templates/{id}/thumbnail`, `POST /api/presentations/generate`, `POST /api/handoff`
- Artefactos: `GET /api/artifacts`, `GET /api/artifacts/{id}/download`, `DELETE /api/artifacts/{id}`
- Ingreso corporativo (spec 056, contrato `specs/056-sso-entra-id-hub/contracts/hub-sso.md`):
  - `GET /api/auth/sso/available`: pre-auth, fail-closed. Devuelve `{enabled, return_origin}` con `Cache-Control: no-store`; ante cualquier falla del backend (403 de licencia, error, red caída, timeout de 3 s) responde `enabled:false`. No expone el tipo de proveedor ni su configuración.
  - `GET /sso/login`: inicia el flujo del lado del servidor y redirige (302) al directorio.
  - `GET /sso/callback`: retorno del directorio, **exactamente** esta ruta (es la de `SENTINEL_SSO_REDIRECT_URI`). Canjea con el backend y emite la sesión.
  - `GET /sso-ui.js`: módulo estático con la lógica y los textos de la pantalla de ingreso (lo carga `index.html`).
  - `GET /api/user/current` suma `user.auth_method` (`password` o `sso`) y `POST /api/auth/change-password` responde `409` a una sesión que entró por el directorio.

## Variables de entorno

| Variable | Obligatoria | Uso |
|---|---|---|
| `ELEA_BACKEND_URL` | sí | backend de Guardian (`http://backend:8000/api/v1`) |
| `ANYTHINGLLM_URL`, `ANYTHINGLLM_API_KEY` | no | motor de documentos |
| `TABULAR_URL`, `TABULAR_INTERNAL_TOKEN` | no | motor de planillas |
| `PRESENTON_URL` | no | motor de presentaciones (`http://presenton:80`) |
| `PRESENTON_ADMIN_PORT` | no | segundo puerto con la pantalla de plantillas de Presenton, solo admins (8097) |
| `ARTIFACTS_DIR` | no | carpeta de archivos generados (`/app/data/artifacts`, volumen) |
| `HUB_BRAND_*` | no | marca de la instalación (nombre, tagline, logo, etiquetas) |

Sin `TABULAR_URL`/`PRESENTON_URL` la sección correspondiente no aparece.

## Sesiones

La sesión vive en memoria del proceso: **reiniciar o reconstruir el contenedor cierra todas las
sesiones** y cada persona vuelve a entrar. Las cookies no distinguen puerto, por eso la misma
sesión vale para el 8095 y el 8097.

### Ingreso corporativo (spec 056)

Todo el estado del ingreso corporativo vive en memoria del proceso, como las sesiones. **Sin
variables de entorno nuevas**: el Hub solo usa `ELEA_BACKEND_URL`, y la URI de retorno la define el
backend (`SENTINEL_SSO_REDIRECT_URI`).

- **Flujos pendientes**: `GET /sso/login` guarda, por `sid`, la cookie de estado firmada del backend y su `state`. El Hub no los decodifica (no tiene el secreto). `GET /sso/callback` toma y **borra** el pendiente siempre: un solo uso, salga bien o mal. Vencen a los 10 minutos. Un reinicio del Hub los vacía y la persona recibe "volvé a intentarlo".
- **Atadura al navegador** (login CSRF): con retorno `https://` el Hub emite `__Host-sso_flow` (`Secure; HttpOnly; Path=/; SameSite=Lax`, 10 min) y el callback exige que coincida junto con el `sid` y el `state` (comparación en tiempo constante). Con retorno `http://localhost` (desarrollo) queda atado solo al `sid`. Si algo no coincide, el Hub igual llama al callback del backend **sin** la cookie de estado, solo para que registre el rechazo, y no canjea.
- **Rotación del `sid`**: al emitir la sesión corporativa el Hub genera un `sid` nuevo y borra la sesión del viejo; la cookie lleva `Secure` solo si el retorno es `https://`. El login con contraseña también rota el `sid` y sigue **sin** `Secure`. En ambos caminos la respuesta lleva una sola `elea_rag_sid` y las demás cookies (`__Host-sso_flow`) no se pisan.
- **Cookie mal formada**: una cookie con `%` inválido se ignora (como si no estuviera); nunca da 500.
- **Límites**: tope de 5 000 pendientes. Con la tabla llena, `GET /sso/login` rechaza al que llega (`sso_reintentar`) y no expulsa a nadie que esté a mitad del ingreso. Además, `GET /sso/login` acepta como máximo 120 pedidos por minuto en total (ventana de 60 s, por proceso, sin llamar al backend pasado el tope). Es un tope global y no sale de un dato medido: un ritmo sostenido de ~2 pedidos por segundo sin autenticarse deja el botón en `sso_reintentar` para todos mientras dure, y tras un reinicio el reingreso masivo legítimo también puede alcanzarlo. El login con contraseña no se afecta.
- **El token no sale del servidor**: el `access_token` queda solo en la sesión; no aparece en una URL, una respuesta ni un log. Los errores llegan a la pantalla de ingreso como `?sso_error=<código>` de una lista cerrada (`sso.js`); el `detail` del backend nunca se copia.
- **Marca**: la lógica y los textos de la pantalla viven en `public/sso-ui.js`, sin marca fija. `tests/unit/whitelabel-hub-056.test.js` lo verifica.

## Desarrollo y pruebas

```bash
cd client && npm install
npm test          # 192 pruebas: dobles HTTP reales de Guardian, motor de documentos, tabular y Presenton
npm start         # escucha en PORT (8095)
```

Compose de desarrollo: perfil `rag` (`docker compose --profile rag --profile tabular --profile presentations up -d --build client`).
Regla de marca (spec 044): ningún nombre interno de motor o proveedor en el HTML servido ni en los
mensajes de error.
