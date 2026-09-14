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

## Desarrollo y pruebas

```bash
cd client && npm install
npm test          # 40 pruebas: dobles HTTP reales de Guardian, motor de documentos, tabular y Presenton
npm start         # escucha en PORT (8095)
```

Compose de desarrollo: perfil `rag` (`docker compose --profile rag --profile tabular --profile presentations up -d --build client`).
Regla de marca (spec 044): ningún nombre interno de motor o proveedor en el HTML servido ni en los
mensajes de error.
