# 042 — Rediseño de UI, historial de hilos real, bóveda de PII para RAG

**Fecha**: 02/03-sep-2026
**Estado**: ✅ **Lista.** Hecho, verificado end-to-end (local y en `eleavdmia`), desplegado en producción.
**Depende de**: [040-cliente-rag-elea-completo](../040-cliente-rag-elea-completo/spec.md),
[041-cliente-rag-cobertura-completa-cliente-elea](../041-cliente-rag-cobertura-completa-cliente-elea/spec.md).

Este doc no sigue el template de spec (no es trabajo por hacer) — es el registro de lo que
se hizo, por qué, y cómo quedó verificado, para que quede trazable junto con las demás specs.

---

## 1. Rediseño de UI (tema claro, marca EleIA)

**Origen**: un mock de demo/marketplace (`llm-guardian/elea-rag-client`, repo distinto,
sin backend real detrás — confirmado leyendo su `/api/chat`: simula respuestas, nunca llama
a un LLM) tenía un rediseño visual completo hecho por otra sesión. Se auditó ese mock antes
de tocar nada:

- **2 filtraciones reales encontradas y arregladas en el mock** (no se portaron): `GET /api/config`
  devolvía `guardianApiKey`/`anythingLlmApiKey` en texto plano sin auth (nunca las usaba el
  frontend); la tarjeta de OpenHands en el Marketplace mostraba el hostname interno
  `demo-litellm-1:4000` en texto client-facing.
- **Decisión**: portar solo el CSS/layout/logo (`public/eleia-logo.png`) al `client/` real
  (el que tiene login/masking/RAG/presupuesto reales), preservando 1:1 toda la lógica JS —
  auditado con un script que confirma que todo `getElementById()` usado por el JS real tiene
  su `id` en el HTML nuevo (0 faltantes).
- **Cosas del mock dejadas AFUERA a propósito**: pestaña Marketplace y modal de
  configuración (sin función real detrás en el cliente real), indicador falso de
  "RAG Status: Active/Offline" (no existe ese endpoint en el backend real — se dejó como
  texto estático), y la branding "Basa GuardIAn" corregida a **"Elea GuardIAn"** (nombre
  correcto del producto para este cliente).

Archivo: `client/public/index.html` (reescrito completo), `client/public/eleia-logo.png` (nuevo).

## 2. Historial de hilos real (bug: "salía del hilo y volvía, desaparecía la info")

**Causa real**: `messages` era estado SOLO del navegador — `selectWorkspace()`/
`selectThread()` lo vaciaban (`messages = []`) y nunca releían el historial que
AnythingLLM sí persiste server-side (`GET /v1/workspace/{slug}/chats` y
`.../thread/{threadSlug}/chats`, ambos ya existentes en su API).

**Fix**: nuevo endpoint `GET /api/workspaces/:slug/messages` (con `?threadSlug=` opcional)
en `client/server.js`, mapeado al mismo shape que ya arma `/api/chat` para mensajes nuevos
(`sources: [{document, extracto}]` — si no, el historial recargado mostraba
"Fuente (RAG): undefined"). `selectWorkspace()`/`selectThread()` en `public/index.html`
ahora llaman `loadMessages()` antes de renderizar.

**Verificado en vivo** (local y en `eleavdmia`): crear un hilo, mandar un mensaje, navegar
al hilo principal, volver — el mensaje sigue ahí.

## 3. Bóveda de PII — desenmascarado real también en RAG (decisión de producto de Elea)

### El hallazgo

Con un documento enmascarado correctamente, el chat **nunca** restauraba el valor real —
ni DNI/CBU ni el resto — contra la expectativa del producto ("mismo comportamiento que el
chat directo", donde mask+unmask sí funcionan porque pasan en el MISMO request).

**Causa raíz**: el mapa reversible (`ph_to_orig`) vive en memoria SOLO del request que
enmascara. Para RAG, ese request es la **subida del documento** — completamente distinto
(y mucho antes) del chat que lo consulta después. Sin persistir el mapa en algún lado, no
hay nada que desenmascarar del lado del motor cuando llega la pregunta.

`litellm/extensions/sentinel_guardian_policy.py` documentaba esto como **Constraint C1**
("Constitución I"): el mapa JAMÁS se persiste, deliberado para todo despliegue de
Sentinel/GuardIAn. Antes de tocar una restricción constitucional del producto compartido
(no solo de Elea), se consultó el trade-off explícitamente al usuario — eligió reversible
también en RAG.

### El fix — opt-in, no rompe otros despliegues

- `sentinel_guardian_policy.py`: bóveda Redis nueva, con flag
  `SENTINEL_PII_VAULT_ENABLED` (**default `false`** — cualquier despliegue de
  Sentinel/GuardIAn que no fije la env var sigue con Constraint C1 tal cual).
  `mask_body()` persiste `ph_to_orig` con TTL (`SENTINEL_PII_VAULT_TTL_SECONDS`, default
  90 días) cuando está prendida. `resolve_placeholders_from_vault(text)` nueva: busca
  placeholders sueltos en un texto y los resuelve contra la bóveda. Best-effort en los dos
  sentidos — si Redis no responde, el masking sigue funcionando igual, solo no persiste
  (nunca rompe ni bloquea una request por esto).
- `sentinel_guardrail.py`: `async_post_call_success_hook` ahora, si la bóveda está prendida
  y el mapa del request actual no alcanza, arma el texto completo de la respuesta
  (`_response_text_preview`, nueva) y lo resuelve contra la bóveda antes de desenmascarar.
  Cubre el shape bridged real (`choices[].message.content`) que usa la ruta RAG vía
  AnythingLLM → motor. **Streaming no cubierto** (el flujo real del cliente usa
  `chatSync`, no streaming — queda como límite conocido si en el futuro se agrega un modo
  streaming).
- `docker-compose.yml` / `.env.example`: `SENTINEL_PII_VAULT_ENABLED=true` para este
  despliegue de Elea (engine + backend, mismo Redis que ya usan).

### El hallazgo secundario — el modelo alucinaba en vez de citar

Verificado en vivo: la bóveda funciona perfecto cuando el modelo **repite el token
textual** (nombres/emails ya lo hacían solos), pero para IDs numéricos (DNI/CBU/teléfono)
el modelo **alucinaba** un valor con formato plausible en vez de citar el placeholder
(ej. preguntado el CBU, respondía `0000000000000000000000`; el DNI, `12345678` — ambos
inventados, no el dato real ni el placeholder). Sin el token literal en la respuesta, la
bóveda no tiene nada que reemplazar.

**Mitigación**: `client/server.js`, default de `openAiPrompt` en workspaces nuevos con una
instrucción explícita ("si ves un token `[TIPO_n_xxxx]`, copiarlo exacto, nunca inventar un
reemplazo"). Con esto el mismo modelo (`azure-gpt-4o-mini`) empezó a citar el token exacto
y DNI/CBU/teléfono salen correctos. Se combina con cualquier `openAiPrompt` personalizado
que ya tenga el espacio (no lo pisa, lo concatena).

### Verificación end-to-end (los 3 hallazgos juntos)

1. **Local, stack completo desde cero** (`docker compose --profile rag up -d`, bootstrap
   real de admin/usuario/API keys): documento con DNI, email, teléfono, CBU y nombre
   reales → el chat respondió con los 5 datos reales y exactos, sin tocar nada a mano
   (con los defaults del código tal cual quedan).
2. **`eleavdmia` (servidor real del cliente)**: mismo flujo, desde el propio Chrome logueado
   del usuario, en un espacio de prueba creado y borrado para no ensuciar sus datos reales
   — DNI, email, teléfono y CBU reales y exactos en la respuesta del chat de producción.
3. Los 3 espacios reales del cliente (`Area 1`, `Contabilidad`, `Análisis NDA`, con 2 días
   de uso real) sobrevivieron la actualización sin ningún problema — documentos e hilos
   intactos. **Nota**: documentos subidos ANTES de este cambio quedan con sus placeholders
   sin resolver para siempre (la bóveda no existía cuando se subieron) — solo los subidos
   DESPUÉS se benefician del desenmascarado.

## 4. Imágenes e instalador

Reconstruidas y publicadas en `ghcr.io/cluna-8/*` las 4 imágenes (`elea-guardian-backend`,
`elea-guardian-engine`, `elea-guardian-frontend`, `elea-rag-client`) desde el estado final
de este trabajo. `cluna-8/elea-installer` actualizado (`docker-compose.yml`/`.env.example`
con las variables de la bóveda) y **probado desde cero en una carpeta limpia**
(`./install.sh` sin tocar nada salvo las 3 credenciales de Azure) antes de subirlo a
ningún lado — mismo resultado: DNI/email/teléfono/CBU reales en la respuesta.

Sincronizado también a Azure DevOps (`celula-ia-proyectos`, rama `master`) — solo el
contenido del instalador, sin código fuente, siguiendo la regla del proyecto de que ese
repo es puente hacia el servidor, nunca destino de specs/WIP.

## 5. Despliegue en `eleavdmia`

Actualizado en caliente, **sin bajar la instancia ni tocar volúmenes** (así se preservaron
los datos reales de 2 días de uso): `git pull` del instalador → `docker compose pull` de
las 4 imágenes → `docker compose up -d` (recreó solo lo que cambió; `db`/`redis`/
`anythingllm`/`nlp-analyzer` siguieron corriendo sin interrupción). Confirmado con los
digests de imagen exactos, y con el flag `SENTINEL_PII_VAULT_ENABLED=true` presente en
los contenedores `elea-engine` y `elea-backend` reales.

## Archivos tocados

- `client/public/index.html` (reescrito), `client/public/eleia-logo.png` (nuevo),
  `client/server.js` (+`/api/workspaces/:slug/messages`, +default de `openAiPrompt`).
- `litellm/extensions/sentinel_guardian_policy.py` (bóveda Redis opt-in),
  `litellm/extensions/sentinel_guardrail.py` (consulta a la bóveda en el post-call hook).
- `docker-compose.yml`, `.env.example` (`SENTINEL_PII_VAULT_ENABLED`/`_TTL_SECONDS`,
  `SENTINEL_ENTITY_REGION` default corregido a `latam_ar`).
- `cluna-8/elea-installer`: `docker-compose.yml`, `.env.example` (mismas variables).

## Nota de mejora — extracción de Excel/CSV: ¿duplicamos trabajo con AnythingLLM?

Duda real del usuario (03-sep): el `client/extract_text.py` extrae `.xlsx` a mano con
pandas, pero AnythingLLM **ya trae su propio procesador nativo de xlsx**
(`asXlsx.js` en su `collector/`, usa `node-xlsx`, convierte cada hoja a CSV y arma un
documento por hoja) — parecería trabajo duplicado.

**Por qué hoy no se puede usar el nativo tal cual**: el enmascarado de PII tiene que
pasar ANTES de que el archivo llegue a AnythingLLM — si le subiéramos el `.xlsx`
original para que lo procese su collector nativo, el vector store quedaría con los
datos reales sin proteger (justo lo que el flujo actual evita). AnythingLLM no expone
ningún hook para interceptar entre "extraje el archivo" y "lo indexé" — o se enmascara
afuera antes de subir (lo que hacemos hoy), o habría que forkear/parchear su collector
(mucho más invasivo, y hay que mantenerlo contra cada actualización de imagen).

**Mejora real posible, no una reescritura completa**: nuestra extracción con pandas es
más cruda que la de AnythingLLM (un volcado plano `columna: valor | columna: valor`,
sin distinguir hojas). El código de `asXlsx.js` ya resuelve bien el caso multi-hoja
(CSV por hoja, con su nombre) — se podría portar SOLO esa lógica de parseo/formato
(no el pipeline de indexado) a `extract_text.py`, para que el texto que enmascaramos y
subimos tenga la misma calidad/estructura que si AnythingLLM lo hubiera procesado él
mismo, en vez de reinventar el formato de salida. Pendiente de spec propia si se decide
priorizar — no es urgente, el volcado actual funciona (verificado con archivos reales).

## Pendiente (no tocado en esta ronda, ver spec 041)

PPTX, generación de documentos, cruces exactos CSV/Excel (DB-GPT), formateo de respuesta
a demanda, presupuesto por rol con UX propia. Sin cambios de estado respecto a spec 041.
