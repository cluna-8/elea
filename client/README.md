# Cliente RAG de Elea

Cliente web (Node/Express) que da acceso **solo al RAG documental** (AnythingLLM), con
login real contra `elea` y enmascarado NER de todo documento antes de indexarlo. Ver
[specs/040-cliente-rag-elea-completo/](../specs/040-cliente-rag-elea-completo/) para el
detalle de diseño (spec.md, plan.md, tasks.md).

## Cómo funciona (todo real, nada simulado)

- **Login**: `POST /api/auth/login` reenvía a `POST {elea}/users/login` — usuario y
  contraseña reales, sin lista de usuarios hardcodeada.
- **Selector de modelo** (chat directo, sin workspace): catálogo real de `elea`
  (`GET /chat/models`), incluye "Automático" cuando el auto-router está activo.
- **Presupuesto**: el cliente mantiene una sesión de SERVICIO propia (usuario admin
  dedicado) para leer `GET /budgets` en nombre del usuario logueado — hoy `elea` no tiene
  un endpoint de autoservicio (`/me/budget`); ver plan.md §3 para la razón.
- **Workspaces**: proxy directo a la API real de AnythingLLM (crear, ajustar las 7
  opciones — modo, temperatura, historial, prompt, umbral de similitud, top-N, respuesta
  de rechazo —, borrar).
- **Documentos**: se extraen con `extract_text.py`, se enmascaran vía
  `POST {elea}/gw/inspect` (misma política que el resto del producto — DNI/CUIL/CBU en
  `latam_ar`) y **solo el texto enmascarado** se sube a AnythingLLM. Verificado: el dato
  real nunca llega al vector store.
- **Chat**: con workspace seleccionado → RAG real vía AnythingLLM (que a su vez habla con
  el motor de `elea`, enmascarado transparente en el turno de chat). Sin workspace → chat
  directo a `elea` con el modelo elegido.

## Variables de entorno

Ver `docker-compose.yml` (servicio `client`, perfil `rag`) y el `.env` de la raíz del repo:

```
ELEA_BACKEND_URL=http://backend:8000/api/v1
ELEA_SERVICE_USERNAME=admin
ELEA_SERVICE_PASSWORD=<contraseña del admin de elea>
ANYTHINGLLM_URL=http://anythingllm:3001
ANYTHINGLLM_API_KEY=<generada en AnythingLLM, ver abajo>
MASKING_VIRTUAL_KEY=<virtual key de elea, tool_type=chat-ui>
```

### Generar la API key de AnythingLLM (paso manual, una vez por instancia)

AnythingLLM no expone un endpoint de alta sin sesión. Con el contenedor arriba:

```bash
docker exec elea-anythingllm node -e "
const {PrismaClient} = require('/app/server/node_modules/@prisma/client');
const p = new PrismaClient();
p.api_keys.create({data:{name:'elea-rag-client', secret: require('crypto').randomBytes(32).toString('hex')}})
  .then(r => console.log(r.secret)).finally(() => process.exit());
"
```

Después, apuntar el proveedor LLM de AnythingLLM al motor de `elea` (nunca a un motor
externo, y nunca con una key de ejemplo commiteada):

```bash
curl -X POST http://localhost:3001/api/v1/system/update-env \
  -H "Authorization: Bearer <la key de arriba>" -H 'Content-Type: application/json' \
  -d '{"LLMProvider":"generic-openai","GenericOpenAiBasePath":"http://engine:4000/v1","GenericOpenAiModelPref":"azure-gpt-4o-mini","GenericOpenAiKey":"<virtual key de elea>"}'
```

### Virtual key de enmascarado (`MASKING_VIRTUAL_KEY`)

Un usuario de servicio + `POST /api/v1/keys` con `tool_type: "chat-ui"` (ver
`plan.md` para el detalle) — no reutilizar la del proveedor LLM de AnythingLLM.

## Límites conocidos de esta versión

- **Sin historial persistente entre recargas**: los mensajes de chat viven solo en el
  navegador mientras la pestaña está abierta (AnythingLLM sí guarda el hilo del lado de
  servidor; el cliente no lo relee al recargar).
- **Previsualización de documentos**: no implementada en esta vuelta (se puede ver qué
  documentos hay y su tamaño, no el contenido completo).

## Resuelto (31-ago, ronda de prueba multi-usuario)

- ✅ **Sesión por navegador**: cada uno tiene su propia cookie (`elea_rag_sid`), sesiones
  aisladas — verificado con 2 usuarios simultáneos, sin cruce.
- ✅ **CBU enmascarado** (faltaba, ver `specs/040.../tasks.md` Fase 7).
- ✅ **Auto-router sin Ollama**: default y las 3 categorías resuelven a `azure-gpt-4o-mini`
  (antes colgaban 30s o fallaban por falta de credencial).
