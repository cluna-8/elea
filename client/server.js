// Cliente RAG de Elea — habla con el backend real de `elea` (login, catálogo de modelos,
// presupuesto, enmascarado NER) y con la API real de AnythingLLM (workspaces, hilos,
// documentos, chat). Ver specs/040-cliente-rag-elea-completo/ (spec.md, plan.md, tasks.md).
//
// Nada de esto simula: cada endpoint de abajo hace una llamada HTTP real. Si `elea` o
// AnythingLLM no responden, el cliente devuelve el error real, nunca inventa uno.
const express = require('express');
const cors = require('cors');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const multer = require('multer');
const { execSync } = require('child_process');

const app = express();
const PORT = process.env.PORT || 8095;

// ── Config (ver docker-compose.yml servicio `client` y client/README.md) ──────────────
const ELEA_BACKEND_URL = process.env.ELEA_BACKEND_URL || 'http://backend:8000/api/v1';
const ANYTHINGLLM_URL = process.env.ANYTHINGLLM_URL || 'http://anythingllm:3001';
const ANYTHINGLLM_API_KEY = process.env.ANYTHINGLLM_API_KEY || '';
const MASKING_VIRTUAL_KEY = process.env.MASKING_VIRTUAL_KEY || '';

// Marca como CONFIG en runtime (mismo criterio que `frontend/src/services/branding.ts`,
// spec 020 US2) — encontrado en revisión (09-sep): el Hub tenía "Elea"/"Eleia"/"Laboratorios
// ELEA" fijos en `public/index.html` (título, logo, tag del tenant, tagline, nombre de
// archivo de transcripción). Eso contradice el principio "Eleia Hub es un cliente más": el
// MISMO Hub, sin tocar código, tiene que poder apuntar a cualquier instancia de Guardian
// (Eleia, la base genérica, o la de otro cliente) y mostrar SU marca, no la de Elea a la
// fuerza. Default neutro — nunca "Elea" por default; la instalación de Elea lo fija por env
// (ver `elea-installer/docker-compose.yml`).
const HUB_BRAND = {
  name: process.env.HUB_BRAND_NAME || 'Guardian Hub',
  tagline: process.env.HUB_BRAND_TAGLINE || 'Chat corporativo con documentos, protegido',
  logoUrl: process.env.HUB_BRAND_LOGO_URL || '/guardian-logo.svg',
  tenantLabel: process.env.HUB_BRAND_TENANT_LABEL || '',
  governanceLabel: process.env.HUB_BRAND_GOVERNANCE_LABEL || 'Guardian',
};
// T034 (US3, R5 de research.md): fecha de corte para avisar "esquema anterior" en
// documentos subidos ANTES de que el enmascarado determinista (document_id) existiera —
// se setea al desplegar esta feature, nunca inferida. Sin esto configurado, ningún
// documento se marca (mejor no avisar que avisar mal por un default arbitrario).
const MASKING_DETERMINISM_SINCE = process.env.MASKING_DETERMINISM_SINCE || null;

const uploadDir = path.join(__dirname, 'public', 'uploads');
if (!fs.existsSync(uploadDir)) fs.mkdirSync(uploadDir, { recursive: true });
const upload = multer({
  storage: multer.diskStorage({
    destination: (req, file, cb) => cb(null, uploadDir),
    filename: (req, file, cb) => {
      const rawName = Buffer.from(file.originalname, 'latin1').toString('utf8');
      cb(null, `${Date.now()}_${rawName}`);
    }
  })
});

app.use(cors({ origin: true, credentials: true }));
app.use(express.json());

// =========================================================================
// SESIÓN POR NAVEGADOR (spec 040, fix 31-ago: varias personas probando a la vez
// se pisaban con una sola sesión global en memoria). Cada navegador recibe una
// cookie `sid` propia (aleatoria, httpOnly); el JWT real de `elea` vive en el
// Map del servidor, indexado por `sid` — nunca en el navegador.
// =========================================================================
const sessions = new Map(); // sid -> { token, user: {id, username, role, email} }
const SID_COOKIE = 'elea_rag_sid';

function parseCookies(header) {
  const out = {};
  (header || '').split(';').forEach((part) => {
    const idx = part.indexOf('=');
    if (idx === -1) return;
    out[part.slice(0, idx).trim()] = decodeURIComponent(part.slice(idx + 1).trim());
  });
  return out;
}

app.use((req, res, next) => {
  const cookies = parseCookies(req.headers.cookie);
  let sid = cookies[SID_COOKIE];
  if (!sid) {
    sid = crypto.randomBytes(24).toString('hex');
    res.setHeader('Set-Cookie', `${SID_COOKIE}=${sid}; HttpOnly; Path=/; SameSite=Lax`);
  }
  req.sid = sid;
  next();
});

function getSession(req) {
  return sessions.get(req.sid) || null;
}
function setSession(req, value) {
  if (value) sessions.set(req.sid, value);
  else sessions.delete(req.sid);
}

app.use(express.static(path.join(__dirname, 'public')));

function extractText(filepath) {
  try {
    const pythonScript = path.join(__dirname, 'extract_text.py');
    return execSync(`python3 "${pythonScript}" "${filepath}"`, { encoding: 'utf-8' }).trim();
  } catch (err) {
    console.error('Error al extraer texto:', err.message);
    return '';
  }
}

async function eleaLogin(username, password) {
  const r = await fetch(`${ELEA_BACKEND_URL}/users/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  });
  const data = await r.json().catch(() => ({}));
  return { ok: r.ok, status: r.status, data };
}

// Llamada autenticada a `elea` con el JWT de la sesión del navegador que pide (nunca la
// variable global vieja — cada request trae su propio token).
async function eleaFetch(token, pathname, opts = {}) {
  if (!token) throw new Error('Sin sesión activa.');
  const r = await fetch(`${ELEA_BACKEND_URL}${pathname}`, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...(opts.headers || {})
    }
  });
  return r;
}

async function anythingllmFetch(pathname, opts = {}) {
  const r = await fetch(`${ANYTHINGLLM_URL}${pathname}`, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${ANYTHINGLLM_API_KEY}`,
      ...(opts.headers || {})
    }
  });
  return r;
}

// =========================================================================
// AISLAMIENTO POR USUARIO (spec 044 US1, contrato 1 de la 043) — el backend es la
// ÚNICA autoridad de a qué espacio/hilo pertenece cada persona. Este Hub NUNCA decide
// por su cuenta: cada operación sobre un workspace/thread se verifica acá primero, y
// solo si el backend la autoriza se proxya al motor de documentos con la credencial de
// servicio (que sigue siendo omnisciente del lado del motor — el control real está acá).
// =========================================================================

// Espacios donde la persona de esta sesión es miembro — YA filtrado por el backend
// (GET /workspaces, contrato 1). Nunca la lista cruda de AnythingLLM.
async function getMemberWorkspaces(session) {
  const r = await eleaFetch(session.token, '/workspaces');
  if (!r.ok) throw new Error(`No se pudo consultar los espacios (HTTP ${r.status}).`);
  const data = await r.json();
  return data.workspaces || [];
}

// Resuelve un `slug` de AnythingLLM contra la lista de espacios PROPIOS del backend.
// `null` si la persona no es miembro (o el espacio no existe) — el caller responde 403
// uniforme, nunca revela si el espacio existe.
async function findMemberWorkspaceBySlug(session, slug) {
  const workspaces = await getMemberWorkspaces(session);
  return workspaces.find((w) => w.engine_slug === slug) || null;
}

// Hilos PROPIOS de la persona dentro de un espacio (backend, contrato 1) — nunca los de
// otro miembro, aunque comparta el mismo espacio (FR-003).
async function getOwnThreads(session, workspaceId) {
  const r = await eleaFetch(session.token, `/workspaces/${workspaceId}/threads`);
  if (!r.ok) throw new Error(`No se pudieron consultar los hilos (HTTP ${r.status}).`);
  const data = await r.json();
  return data.threads || [];
}

// Registra (o confirma) que un `threadSlug` de AnythingLLM es del hilo PROPIO de esta
// persona en el backend — idempotente (create_or_get). Se llama ANTES de crear/usar un
// hilo en AnythingLLM, así el backend siempre sabe de quién es cada hilo nuevo.
async function claimOwnThread(session, workspaceId, engineThreadSlug) {
  const r = await eleaFetch(session.token, `/workspaces/${workspaceId}/threads`, {
    method: 'POST',
    body: JSON.stringify({ engine_thread_slug: engineThreadSlug || null })
  });
  if (!r.ok) throw new Error(`No se pudo registrar el hilo (HTTP ${r.status}).`);
  return r.json();
}

// Verifica que un `threadSlug` puntual sea de la persona (para leer/borrar/renombrar un
// hilo existente) — `undefined` = "hilo principal", siempre válido para uno mismo.
async function ownsThreadSlug(session, workspaceId, threadSlug) {
  if (!threadSlug) return true; // hilo principal: no hace falta un registro previo
  const own = await getOwnThreads(session, workspaceId);
  return own.some((t) => t.engine_thread_slug === threadSlug);
}

// Bug real encontrado en verificación en vivo (10-sep, el reclamo original de Tomás: "la
// memoria de chats es compartida"). Antes de este fix, "hilo principal" (sin threadSlug)
// no tenía NINGÚN hilo real detrás en el motor — el Hub hablaba directo con el chat/
// historial A NIVEL DE ESPACIO de AnythingLLM, compartido por cualquiera que use ese
// espacio sin crear un hilo propio (o sea, el caso normal). Confirmado con sesión limpia,
// sin caché: un usuario nuevo agregado a un espacio veía la conversación completa de otro.
//
// Esta función resuelve (o crea, la primera vez) un hilo REAL del motor que respalda el
// "hilo principal" de ESTA persona en ESTE espacio — nunca vuelve a tocar el endpoint
// compartido a nivel de espacio. Se persiste en el backend (`principal_engine_thread_slug`,
// migración 019) así se reutiliza el mismo hilo real entre sesiones, en vez de crear uno
// nuevo cada vez que alguien pregunta sin haber elegido un hilo explícito.
async function resolvePrincipalEngineThreadSlug(session, workspaceId, engineSlug) {
  const own = await getOwnThreads(session, workspaceId);
  const principalRow = own.find((t) => t.engine_thread_slug === null);
  if (principalRow && principalRow.principal_engine_thread_slug) {
    return principalRow.principal_engine_thread_slug;
  }
  // Primera vez: crear el hilo real en el motor y registrarlo. Si dos requests del mismo
  // usuario llegan casi juntos (dos pestañas), el backend deduplica por el índice único
  // (workspace, usuario) y devuelve el que haya ganado la carrera — usamos SIEMPRE lo que
  // el backend confirma, nunca lo que acabamos de crear acá a ciegas.
  const r = await anythingllmFetch(`/api/v1/workspace/${engineSlug}/thread/new`, {
    method: 'POST',
    body: JSON.stringify({ name: 'Principal' })
  });
  if (!r.ok) throw new Error(`No se pudo crear el hilo principal (HTTP ${r.status}).`);
  const data = await r.json();
  const nuevoSlug = data.thread && data.thread.slug;
  if (!nuevoSlug) throw new Error('El motor no devolvió un slug de hilo válido.');
  const claimed = await eleaFetch(session.token, `/workspaces/${workspaceId}/threads`, {
    method: 'POST',
    body: JSON.stringify({ engine_thread_slug: null, principal_engine_thread_slug: nuevoSlug })
  });
  if (!claimed.ok) throw new Error(`No se pudo registrar el hilo principal (HTTP ${claimed.status}).`);
  const claimedData = await claimed.json();
  return claimedData.principal_engine_thread_slug || nuevoSlug;
}

// Enmascarado NER real (spec 040 US4): misma política que el resto de `elea`
// (POST /api/v1/gw/inspect, latam_ar hoy — DNI/CUIL/CBU). Fail-closed: si el motor de
// detección no responde, NO se sube el texto sin enmascarar — se corta la subida.
//
// `documentId` (spec 044 US3, contrato 3 de la 043): el mismo id en todos los chunks de
// una subida hace que el mismo valor detectado reciba el MISMO placeholder en todo el
// documento — antes cada chunk creaba su propio mapa con un nonce aleatorio, así que
// "Julián" en la fila 3 y en la fila 40 de un CSV salían con placeholders distintos (bug
// real reportado por Tomás Mc Nally, 03-sep). `acted_for_user_id` (contrato 2): la
// llave de servicio de enmascarado actúa "en nombre de" la persona real de la sesión —
// sin esto, el gasto y el enmascarado quedaban atribuidos a la cuenta de servicio, no a
// quien realmente subió el documento (diagnostico.md §5 de la 043).
// Reintento (spec 044 US3, T029/R2 de research.md) — SOLO ante un fallo de RED (fetch
// que ni siquiera llega a tener respuesta: timeout, conexión rechazada), nunca ante un
// 4xx/402 real (eso es una decisión de política o de presupuesto, reintentarla no
// cambiaría nada). Reusa el MISMO `documentId` del cierre de `maskText` — no genera uno
// nuevo — así que el chunk reintentado sigue perteneciendo al mismo documento.
const MASK_CHUNK_RETRY_ATTEMPTS = 3;
const MASK_CHUNK_RETRY_DELAY_MS = 300;

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function maskChunk(text, { documentId, actingUserId } = {}) {
  if (!text) return { masked: '', blocked: false, entities: [] };
  const headers = { 'Content-Type': 'application/json', 'X-Sentinel-Key': MASKING_VIRTUAL_KEY };
  if (actingUserId) headers['X-Guardian-Acting-User'] = actingUserId;

  let r;
  let lastNetworkError;
  for (let intento = 1; intento <= MASK_CHUNK_RETRY_ATTEMPTS; intento++) {
    try {
      r = await fetch(`${ELEA_BACKEND_URL}/gw/inspect`, {
        method: 'POST',
        headers,
        // 'hub-client' es descriptivo, no funcional: no está en el enum SURFACES del
        // backend (inspect.py `_SURFACES_POR_TOKEN`), así que nunca decide la superficie
        // auditada — eso lo resuelve `tool_type` de la Connection ("servicio"). Antes
        // decía 'elea-rag-client', un nombre atado a Elea en un cliente que se conecta a
        // cualquier instancia de Guardian (encontrado en revisión, 09-sep).
        body: JSON.stringify({ text, tool: 'hub-client', document_id: documentId })
      });
      lastNetworkError = null;
      break;
    } catch (err) {
      lastNetworkError = err;
      if (intento < MASK_CHUNK_RETRY_ATTEMPTS) await sleep(MASK_CHUNK_RETRY_DELAY_MS);
    }
  }
  if (lastNetworkError) {
    throw new Error('El servicio de protección de documentos no está disponible — no se sube el documento.');
  }

  if (r.status === 402) {
    const data = await r.json().catch(() => ({}));
    return { masked: '', blocked: true, budgetExceeded: true,
      motivo: data.motivo || 'Alcanzaste tu presupuesto asignado.', entities: [] };
  }
  if (!r.ok) throw new Error(`El servicio de protección de documentos no está disponible (HTTP ${r.status}) — no se sube el documento.`);
  const data = await r.json();
  // BUG real encontrado 31-ago con un archivo real (238 registros de salud): `ok:false`
  // no significa SOLO "key inválida" — también lo devuelve un bloqueo real de la capa de
  // gobernanza (`blocked:true`, con `motivo` explicando por qué). El mensaje anterior
  // ("sin key válida") era falso en ese caso y ocultaba la razón real del bloqueo.
  if (data.blocked) {
    return { masked: '', blocked: true, motivo: data.motivo || 'Bloqueado por la política de contenido.', entities: [] };
  }
  if (!data.ok) throw new Error('El servicio de protección de documentos no respondió correctamente.');
  return { masked: data.masked, blocked: false, entities: data.entities || [] };
}

// El analizador NLP (Presidio) es lento de verdad: medido en vivo, ~330 caracteres/
// segundo por CPU (spaCy es_core_news_md, 1 core al 100%) — un texto grande de una sola
// vez agotaba el timeout del motor y el documento quedaba bloqueado por fail-closed
// (BUG real encontrado 31-ago con una planilla real de 570KB/238 filas: "no autorizó el
// texto" era en realidad un ReadTimeout del analizador, no un rechazo de política). El
// motor ahora tolera hasta 15s por trozo (ver litellm/extensions/sentinel_guardian_
// policy.py) — 4000 caracteres a ~330 c/s son ~12s, con margen real, no al límite.
const MASK_CHUNK_CHARS = 4000;
// Tope total honesto: a esta velocidad medida, un documento de más de ~150.000
// caracteres tardaría varios minutos en subir (secuencial, un trozo detrás de otro).
// Se corta ahí y se avisa — mejor una subida rápida con parte del contenido que una
// espera de 10+ minutos sin saber si sigue viva.
const MASK_MAX_TOTAL_CHARS = 150000;

function splitIntoChunks(text) {
  if (text.length <= MASK_CHUNK_CHARS) return [text];
  const lines = text.split('\n');
  const chunks = [];
  let current = '';
  for (const line of lines) {
    if (current.length + line.length + 1 > MASK_CHUNK_CHARS && current) {
      chunks.push(current);
      current = '';
    }
    current += (current ? '\n' : '') + line;
  }
  if (current) chunks.push(current);
  return chunks;
}

// `actingUserId` (spec 044 US2/US3): quien realmente sube el documento, propagado a cada
// chunk. `documentId` se genera UNA vez acá (crypto.randomUUID) y viaja igual a todos los
// chunks de esta subida — es lo que hace determinista el enmascarado dentro del
// documento sin correlacionar nada entre documentos distintos (cada subida, un id nuevo).
async function maskText(text, { actingUserId } = {}) {
  if (!text) return { masked: '', blocked: false, entities: [], truncated: false, documentId: null };
  const documentId = crypto.randomUUID();
  const truncated = text.length > MASK_MAX_TOTAL_CHARS;
  const usable = truncated ? text.slice(0, MASK_MAX_TOTAL_CHARS) : text;
  const chunks = splitIntoChunks(usable);
  const maskedParts = [];
  const allEntities = [];
  for (const chunk of chunks) {
    const result = await maskChunk(chunk, { documentId, actingUserId });
    if (result.blocked) return { ...result, documentId }; // un pedazo bloqueado bloquea todo el documento
    maskedParts.push(result.masked);
    allEntities.push(...result.entities);
  }
  // Resumen agregado por DOCUMENTO (spec 044 US3), no por chunk: cada tipo de dato
  // detectado se cuenta una vez por documento, ya no "cada chunk cuenta desde 0".
  const merged = {};
  for (const e of allEntities) merged[e.type] = (merged[e.type] || 0) + e.count;
  return {
    masked: maskedParts.join('\n'),
    blocked: false,
    entities: Object.entries(merged).map(([type, count]) => ({ type, count })),
    truncated,
    documentId
  };
}

// Enmascarado línea por línea para CSV (bug real encontrado en vivo 11-sep, spec 046):
// `maskText` junta varias líneas en un mismo trozo de hasta `MASK_CHUNK_CHARS` antes de
// mandarlo al analizador NER — Presidio/spaCy no tratan el salto de línea como un límite
// duro, así que pueden detectar una entidad que ABARCA dos filas (medido en vivo:
// "Julian,1200\nVentas" salió como una sola entidad LOCATION) y reemplazarla por UN
// placeholder — fusiona dos filas en una y corre las columnas. El motor de análisis
// exacto entonces rechaza el archivo con un 422 genérico, sin ningún error propio: el
// CSV ya no es tabular, no es un problema del motor. Enmascarar fila por fila hace
// IMPOSIBLE que una entidad cruce un límite de fila — el costo es una llamada al
// analizador por fila en vez de una cada ~4000 caracteres, aceptable para las planillas
// que espera este modo (T090 de la 048 lo dejaba pendiente; esto lo cierra para .csv).
//
// La PRIMERA fila (encabezado) NUNCA se manda al analizador (decisión explícita del
// usuario, 11-sep, tras encontrar en vivo que el NER da falsos positivos sobre nombres de
// columna y valores categóricos cortos — "depto" salió marcado PERSON, "Marketing"/
// "Ventas" salieron LOCATION). Enmascarar el encabezado no protege ningún dato personal
// real (un nombre de columna no es PII) pero SÍ rompe la semántica que el motor de
// análisis exacto necesita para armar el SQL: si "depto" se reemplaza por un placeholder
// tipo `PERSON_xxx`, el motor arma `WHERE person_id = '<placeholder de otro valor>'`
// contra una columna que ya no existe con ese nombre, y la respuesta vuelve `null` — no
// es un error visible, es una respuesta vacía o incorrecta silenciosa, peor que no
// enmascarar. Los VALORES de datos (filas 2 en adelante) sí siguen enmascarándose fila
// por fila como antes — ahí es donde puede haber PII real (nombres de personas, DNIs,
// etc. en columnas de datos, no en el nombre de la columna).
//
// Gap conocido, documentado a propósito (mismo criterio que el gap de .xlsx sin
// enmascarar, T090 de la 048): un valor categórico REPETIDO en muchas filas (p.ej. un
// nombre de departamento) todavía puede dar falso positivo fila por fila y quedar
// enmascarado de forma inconsistente entre filas (cada fila es una llamada independiente
// al NER, sin memoria de "esto ya lo vi antes y decidí que es una categoría, no PII")
// — eso puede seguir devolviendo respuestas incorrectas para ESE caso puntual. Excluir
// headers cierra el caso más común y más dañino (el nombre de columna, que aparece una
// sola vez pero rompe el SQL entero); no cierra el caso general de valores categóricos
// repetidos, que queda fuera de esta ronda.
async function maskCsvText(text, { actingUserId } = {}) {
  if (!text) return { masked: '', blocked: false, entities: [], truncated: false, documentId: null };
  const documentId = crypto.randomUUID();
  const truncated = text.length > MASK_MAX_TOTAL_CHARS;
  const usable = truncated ? text.slice(0, MASK_MAX_TOTAL_CHARS) : text;
  const lines = usable.split('\n');
  const maskedLines = [];
  const allEntities = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line) { maskedLines.push(line); continue; } // línea vacía: nada que mandar al analizador
    if (i === 0) { maskedLines.push(line); continue; } // encabezado: nunca se enmascara (ver comentario arriba)
    const result = await maskChunk(line, { documentId, actingUserId });
    if (result.blocked) return { ...result, documentId }; // una fila bloqueada bloquea todo el documento
    maskedLines.push(result.masked);
    allEntities.push(...result.entities);
  }
  const merged = {};
  for (const e of allEntities) merged[e.type] = (merged[e.type] || 0) + e.count;
  return {
    masked: maskedLines.join('\n'),
    blocked: false,
    entities: Object.entries(merged).map(([type, count]) => ({ type, count })),
    truncated,
    documentId
  };
}

// =========================================================================
// AUTENTICACIÓN (US1) — login real contra elea, sin lista de usuarios falsa.
// =========================================================================
app.post('/api/auth/login', async (req, res) => {
  const { username, password } = req.body || {};
  if (!username || !password) {
    return res.status(400).json({ error: 'Usuario y contraseña son obligatorios.' });
  }
  try {
    const { ok, status, data } = await eleaLogin(username, password);
    if (!ok) {
      return res.status(status).json({ error: data.detail || 'Credenciales incorrectas.' });
    }
    setSession(req, { token: data.access_token, user: data.user });
    res.json({ success: true, user: data.user });
  } catch (err) {
    res.status(502).json({ error: 'No se pudo contactar al backend de Guardian. Intentá de nuevo en unos minutos.' });
  }
});

app.post('/api/auth/logout', (req, res) => {
  setSession(req, null);
  res.json({ success: true });
});

// Marca en runtime, pública (necesaria ANTES del login — el logo también se muestra en la
// pantalla de login). Mismo criterio que `frontend`: la instancia decide su marca por env,
// el código del Hub no tiene ninguna atada.
app.get('/api/branding', (req, res) => {
  res.json(HUB_BRAND);
});

app.get('/api/user/current', async (req, res) => {
  const session = getSession(req);
  if (!session) return res.json({ isAuthenticated: false });

  const [budget, workspaces] = await Promise.all([
    fetchOwnBudget(session).catch((err) => ({ error: err.message })),
    getMemberWorkspaces(session).catch(() => [])
  ]);

  res.json({
    isAuthenticated: true,
    user: session.user,
    budget,
    workspaces,
    maskingDeterminismSince: MASKING_DETERMINISM_SINCE
  });
});

// Spec 044 (US2, contrato 2): autoservicio — la propia sesión de la persona, sin sesión
// de admin de fondo (antes leía TODOS los presupuestos con una sesión de servicio y
// filtraba en memoria por user_id — diagnostico.md §5 de la 043).
async function fetchOwnBudget(session) {
  const r = await eleaFetch(session.token, '/users/me/budget');
  if (!r.ok) throw new Error(`No se pudo leer el presupuesto (HTTP ${r.status}).`);
  const data = await r.json();
  if (data.max_usd === null || data.max_usd === undefined) {
    return { maxUsd: null, usedUsd: null, message: 'Sin presupuesto asignado.', status: 'ok' };
  }
  return { maxUsd: data.max_usd, usedUsd: data.used_usd, status: data.status };
}

app.get('/api/user/budget', async (req, res) => {
  const session = getSession(req);
  if (!session) return res.status(401).json({ error: 'Sin sesión activa.' });
  try {
    res.json(await fetchOwnBudget(session));
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

// =========================================================================
// SELECTOR DE MODELO (US2) — catálogo real de elea, nunca una lista inventada.
// =========================================================================
app.get('/api/models', async (req, res) => {
  const session = getSession(req);
  if (!session) return res.status(401).json({ error: 'Sin sesión activa.' });
  try {
    const r = await eleaFetch(session.token, '/chat/models');
    if (!r.ok) return res.status(r.status).json({ error: 'No se pudo leer el catálogo de modelos.' });
    res.json(await r.json());
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

// =========================================================================
// WORKSPACES (spec 044 US1) — el backend (contrato 1 de la 043) decide QUÉ ve cada
// persona; este Hub solo proxya a AnythingLLM lo que el backend ya autorizó. Cada
// endpoint exige sesión (FR-001) y, salvo el listado propio, verifica pertenencia antes
// de tocar AnythingLLM (FR-004) — nunca al revés.
// =========================================================================

function requireSession(req, res) {
  const session = getSession(req);
  if (!session) {
    res.status(401).json({ error: 'iniciá sesión' });
    return null;
  }
  return session;
}

app.get('/api/workspaces', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  try {
    const workspaces = await getMemberWorkspaces(session);
    res.json({ workspaces });
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

// Espacios sin dueño tras una migración (FR-006/FR-010 de la 043) — solo para asignar
// miembros; el backend ya exige rol admin del lado suyo.
app.get('/api/workspaces/unassigned', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  try {
    const r = await eleaFetch(session.token, '/workspaces?status_filter=unassigned');
    if (!r.ok) return res.status(r.status).json({ error: 'No se pudo consultar los espacios sin asignar.' });
    res.json(await r.json());
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

// Asignar el primer miembro a un espacio sin asignar (T018): a diferencia de
// `/api/workspaces/:slug/members`, acá quien llama NO es miembro todavía (por
// definición, el espacio no tiene dueño) — no podemos verificar pertenencia local, así
// que se pasa el id directo y el backend es quien exige rol admin (ver workspaces.py
// `add_member`/`is_admin`). Nunca confiar en el rol que mande el cliente.
app.post('/api/workspaces/unassigned/:workspaceId/members', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const { username } = req.body || {};
  if (!username) return res.status(400).json({ error: 'Falta el nombre de usuario a agregar.' });
  try {
    const r = await eleaFetch(session.token, `/workspaces/${req.params.workspaceId}/members`, {
      method: 'POST',
      body: JSON.stringify({ username })
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) return res.status(r.status).json({ error: data.detail || 'No se pudo agregar el miembro.' });
    res.json(data);
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

app.get('/api/workspaces/:slug', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  try {
    const membership = await findMemberWorkspaceBySlug(session, req.params.slug);
    if (!membership) return res.status(403).json({ error: 'No tenés acceso a este espacio.' });
    const r = await anythingllmFetch(`/api/v1/workspace/${req.params.slug}`);
    if (!r.ok) return res.status(r.status).json({ error: 'Espacio no encontrado.' });
    const data = await r.json();
    const workspace = Array.isArray(data.workspace) ? data.workspace[0] : data.workspace;
    // Bug real 10-sep, junto con el del hilo principal: `threads` acá venía CRUDO del
    // motor — TODOS los hilos del espacio, de cualquier persona, sin filtrar (el
    // sidebar terminaba listando "Hilo de otra persona" a cualquier miembro). FR-003:
    // solo los hilos EXPLÍCITOS propios se muestran como ítems — el "hilo principal"
    // (el real que respalda el default) es un detalle interno, nunca un ítem de la lista.
    if (workspace && Array.isArray(workspace.threads)) {
      const own = await getOwnThreads(session, membership.id);
      const ownExplicitSlugs = new Set(
        own.filter((t) => t.engine_thread_slug).map((t) => t.engine_thread_slug)
      );
      workspace.threads = workspace.threads.filter((t) => ownExplicitSlugs.has(t.slug));
    }
    res.json({ ...data, workspace, role: membership.role });
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

// ── Miembros (FR-002) — solo dueño del espacio o admin, el backend ya lo exige ────────
app.get('/api/workspaces/:slug/members', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  try {
    const membership = await findMemberWorkspaceBySlug(session, req.params.slug);
    if (!membership) return res.status(403).json({ error: 'No tenés acceso a este espacio.' });
    const r = await eleaFetch(session.token, `/workspaces/${membership.id}/members`);
    if (!r.ok) return res.status(r.status).json({ error: 'No se pudo consultar los miembros.' });
    res.json(await r.json());
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

app.post('/api/workspaces/:slug/members', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const { username } = req.body || {};
  if (!username) return res.status(400).json({ error: 'Falta el nombre de usuario a agregar.' });
  try {
    const membership = await findMemberWorkspaceBySlug(session, req.params.slug);
    if (!membership) return res.status(403).json({ error: 'No tenés acceso a este espacio.' });
    const r = await eleaFetch(session.token, `/workspaces/${membership.id}/members`, {
      method: 'POST',
      body: JSON.stringify({ username })
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) return res.status(r.status).json({ error: data.detail || 'No se pudo agregar el miembro.' });
    res.json(data);
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

app.delete('/api/workspaces/:slug/members/:userId', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  try {
    const membership = await findMemberWorkspaceBySlug(session, req.params.slug);
    if (!membership) return res.status(403).json({ error: 'No tenés acceso a este espacio.' });
    const r = await eleaFetch(session.token, `/workspaces/${membership.id}/members/${req.params.userId}`, {
      method: 'DELETE'
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) return res.status(r.status).json({ error: data.detail || 'No se pudo quitar el miembro.' });
    res.json({ success: true });
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

app.patch('/api/workspaces/:slug/transfer-owner', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const { newOwnerUserId } = req.body || {};
  try {
    const membership = await findMemberWorkspaceBySlug(session, req.params.slug);
    if (!membership) return res.status(403).json({ error: 'No tenés acceso a este espacio.' });
    const r = await eleaFetch(session.token, `/workspaces/${membership.id}/transfer-owner`, {
      method: 'PATCH',
      body: JSON.stringify({ new_owner_user_id: newOwnerUserId })
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) return res.status(r.status).json({ error: data.detail || 'No se pudo transferir la propiedad.' });
    res.json(data);
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

// Historial real de un hilo (o del hilo principal del espacio si no se pasa
// threadSlug) — AnythingLLM SÍ persiste los mensajes server-side; hasta acá el
// cliente los tiraba al cambiar de hilo/espacio y volvían a aparecer vacíos
// (bug real reportado 02-sep: "salía del hilo y volvía, desaparecía la info").
app.get('/api/workspaces/:slug/messages', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const { slug } = req.params;
  const { threadSlug } = req.query;
  try {
    const membership = await findMemberWorkspaceBySlug(session, slug);
    if (!membership) return res.status(403).json({ error: 'No tenés acceso a este espacio.' });
    // FR-003: aunque sea miembro del espacio, solo puede leer SUS propios hilos.
    if (threadSlug && !(await ownsThreadSlug(session, membership.id, threadSlug))) {
      return res.status(403).json({ error: 'Ese hilo no te pertenece.' });
    }
    // Bug real 10-sep: "hilo principal" (sin threadSlug) NUNCA debe leer el historial
    // compartido a nivel de espacio — cada persona tiene su propio hilo real detrás.
    const realThreadSlug = threadSlug || await resolvePrincipalEngineThreadSlug(session, membership.id, slug);
    const path = `/api/v1/workspace/${slug}/thread/${realThreadSlug}/chats`;
    const r = await anythingllmFetch(path);
    if (!r.ok) return res.status(r.status).json({ error: 'No se pudo leer el historial del hilo.' });
    const data = await r.json();
    // Mismo shape que ya arma /api/chat para mensajes nuevos ({document, extracto})
    // — si no, el historial recargado muestra "Fuente (RAG): undefined".
    const messages = (data.history || []).map((m) => ({
      role: m.role,
      content: m.content,
      sources: (m.sources || []).map((s) => ({ document: (s.title || '').replace(/\.txt$/i, ''), extracto: s.text })),
      modelUsed: m.metrics && m.metrics.model,
      timestamp: m.sentAt
        ? new Date(m.sentAt * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : undefined
    }));
    res.json({ messages });
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

// Las 7 opciones reales de AnythingLLM documentadas en spec.md US3 — nada de
// nombre/descripción nada más.
function pickWorkspaceSettings(body) {
  const out = {};
  if (body.chatMode) out.chatMode = body.chatMode; // "chat" | "query"
  if (body.openAiTemp !== undefined) out.openAiTemp = body.openAiTemp;
  if (body.openAiHistory !== undefined) out.openAiHistory = body.openAiHistory;
  if (body.openAiPrompt) out.openAiPrompt = body.openAiPrompt;
  if (body.similarityThreshold !== undefined) out.similarityThreshold = body.similarityThreshold;
  if (body.topN !== undefined) out.topN = body.topN;
  if (body.queryRefusalResponse !== undefined) out.queryRefusalResponse = body.queryRefusalResponse;
  return out;
}

app.post('/api/workspaces/create', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const { name } = req.body || {};
  if (!name) return res.status(400).json({ error: 'El workspace necesita un nombre.' });
  try {
    const createResp = await anythingllmFetch('/api/v1/workspace/new', {
      method: 'POST',
      body: JSON.stringify({ name })
    });
    if (!createResp.ok) return res.status(createResp.status).json({ error: 'No se pudo crear el espacio.' });
    const created = await createResp.json();
    const slug = created.workspace.slug;

    // Registra la pertenencia en el backend (contrato 1) — sin esto, el espacio recién
    // creado en AnythingLLM sería invisible para todos, incluida la persona que lo creó.
    const registered = await eleaFetch(session.token, '/workspaces', {
      method: 'POST',
      body: JSON.stringify({ display_name: name, engine_slug: slug })
    });
    if (!registered.ok) {
      // Reversión best-effort: si el backend rechaza el registro, no dejar un espacio
      // huérfano en AnythingLLM que nadie podría ver ni administrar.
      await anythingllmFetch(`/api/v1/workspace/${slug}`, { method: 'DELETE' }).catch(() => {});
      return res.status(registered.status).json({ error: 'No se pudo registrar el espacio.' });
    }

    // Default de AnythingLLM (similarityThreshold: 0.25) es DEMASIADO estricto para
    // texto tipo tabla/CSV (filas de datos, no lenguaje natural) contra el modelo de
    // embeddings nativo chico (Xenova/all-MiniLM-L6-v2) — la búsqueda por similitud no
    // superaba el umbral y devolvía CERO fragmentos, así que el chat contestaba con
    // conocimiento genérico del modelo en vez de leer el documento real (BUG raíz real
    // encontrado 31-ago, con archivos reales del usuario: "no lee, solo veo títulos").
    // Confirmado en vivo: bajando a 0.05 el mismo archivo se responde con datos reales.
    //
    // `openAiPrompt`: el motor SÍ desenmascara los tokens [TIPO_n_xxxx] que el modelo
    // repita literal en su respuesta (bóveda Redis, SENTINEL_PII_VAULT_ENABLED — ver
    // sentinel_guardian_policy.py) — pero verificado en vivo (02-sep): sin esta
    // instrucción, ante "¿cuál es el DNI/CBU/teléfono?" el modelo NO copiaba el token,
    // ALUCINABA un valor con formato plausible (ej. CBU "000...000", DNI "12345678")
    // en vez de citarlo — el desenmascarado no tiene nada que reemplazar si el modelo
    // no reprodujo el placeholder exacto. Con esta línea en el prompt, el mismo
    // modelo (azure-gpt-4o-mini) empezó a citar el token exacto y el DNI/CBU/teléfono
    // reales aparecieron correctos en la respuesta. Nombres/emails ya funcionaban sin
    // esto (el modelo los copia solo), pero se agrega igual por consistencia.
    const DEFAULT_UNMASK_PROMPT_HINT = 'Cuando en el contexto veas un token entre '
      + 'corchetes con este formato exacto [TIPO_numero_codigo] (por ejemplo '
      + '[DNI_0_a03c], [PHONE_NUMBER_0_a03c], [EMAIL_ADDRESS_0_a03c]), es un dato '
      + 'protegido. Si el usuario pide ese dato, respondé copiando el token EXACTO '
      + 'tal cual aparece entre corchetes, letra por letra — NUNCA inventes, adivines '
      + 'ni generes un valor de reemplazo con un formato similar.';
    const customSettings = pickWorkspaceSettings(req.body);
    const settings = {
      similarityThreshold: 0.05,
      topN: 8,
      ...customSettings,
      openAiPrompt: customSettings.openAiPrompt
        ? `${customSettings.openAiPrompt}\n\n${DEFAULT_UNMASK_PROMPT_HINT}`
        : DEFAULT_UNMASK_PROMPT_HINT
    };
    await anythingllmFetch(`/api/v1/workspace/${slug}/update`, {
      method: 'POST',
      body: JSON.stringify(settings)
    });
    res.json({ success: true, workspace: created.workspace });
  } catch (err) {
    res.status(502).json({ error: 'El servicio de documentos no está disponible. Intentá de nuevo en unos minutos.' });
  }
});

app.post('/api/workspaces/settings', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const { slug } = req.body || {};
  if (!slug) return res.status(400).json({ error: 'Falta el workspace.' });
  const settings = pickWorkspaceSettings(req.body);
  try {
    const membership = await findMemberWorkspaceBySlug(session, slug);
    if (!membership) return res.status(403).json({ error: 'No tenés acceso a este espacio.' });
    const r = await anythingllmFetch(`/api/v1/workspace/${slug}/update`, {
      method: 'POST',
      body: JSON.stringify(settings)
    });
    if (!r.ok) return res.status(r.status).json({ error: 'No se pudo actualizar el espacio.' });
    res.json(await r.json());
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

app.post('/api/workspaces/delete', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const { slug } = req.body || {};
  if (!slug) return res.status(400).json({ error: 'Falta el workspace.' });
  try {
    const membership = await findMemberWorkspaceBySlug(session, slug);
    if (!membership) return res.status(403).json({ error: 'No tenés acceso a este espacio.' });
    const r = await anythingllmFetch(`/api/v1/workspace/${slug}`, { method: 'DELETE' });
    res.json({ success: r.ok });
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

// ── Hilos (FR-003: siempre PROPIOS, aunque el espacio se comparta) ────────────────────
app.post('/api/threads/create', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const { slug, name } = req.body || {};
  if (!slug) return res.status(400).json({ error: 'Falta el workspace.' });
  try {
    const membership = await findMemberWorkspaceBySlug(session, slug);
    if (!membership) return res.status(403).json({ error: 'No tenés acceso a este espacio.' });
    const r = await anythingllmFetch(`/api/v1/workspace/${slug}/thread/new`, {
      method: 'POST',
      body: JSON.stringify({ name: name || 'Nuevo hilo' })
    });
    if (!r.ok) return res.status(r.status).json({ error: 'No se pudo crear el hilo.' });
    const data = await r.json();
    // Registra en el backend a quién pertenece este hilo nuevo — sin esto, quedaría
    // técnicamente creado pero sin dueño verificable.
    await claimOwnThread(session, membership.id, data.thread && data.thread.slug);
    res.json(data);
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

app.post('/api/threads/rename', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const { slug, threadSlug, name } = req.body || {};
  try {
    const membership = await findMemberWorkspaceBySlug(session, slug);
    if (!membership) return res.status(403).json({ error: 'No tenés acceso a este espacio.' });
    if (!(await ownsThreadSlug(session, membership.id, threadSlug))) {
      return res.status(403).json({ error: 'Ese hilo no te pertenece.' });
    }
    const r = await anythingllmFetch(`/api/v1/workspace/${slug}/thread/${threadSlug}/update`, {
      method: 'POST',
      body: JSON.stringify({ name })
    });
    res.json({ success: r.ok });
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

app.post('/api/threads/delete', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const { slug, threadSlug } = req.body || {};
  try {
    const membership = await findMemberWorkspaceBySlug(session, slug);
    if (!membership) return res.status(403).json({ error: 'No tenés acceso a este espacio.' });
    if (!(await ownsThreadSlug(session, membership.id, threadSlug))) {
      return res.status(403).json({ error: 'Ese hilo no te pertenece.' });
    }
    const r = await anythingllmFetch(`/api/v1/workspace/${slug}/thread/${threadSlug}`, { method: 'DELETE' });
    res.json({ success: r.ok });
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

// "Limpiar" = borrar el hilo y crear uno nuevo con el mismo nombre — AnythingLLM no
// expone un endpoint propio de "vaciar hilo sin borrarlo" (verificado contra la API viva,
// spec 040 tasks.md T001 nota).
app.post('/api/threads/clear', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const { slug, threadSlug, name } = req.body || {};
  try {
    const membership = await findMemberWorkspaceBySlug(session, slug);
    if (!membership) return res.status(403).json({ error: 'No tenés acceso a este espacio.' });
    if (!(await ownsThreadSlug(session, membership.id, threadSlug))) {
      return res.status(403).json({ error: 'Ese hilo no te pertenece.' });
    }
    await anythingllmFetch(`/api/v1/workspace/${slug}/thread/${threadSlug}`, { method: 'DELETE' });
    const r = await anythingllmFetch(`/api/v1/workspace/${slug}/thread/new`, {
      method: 'POST',
      body: JSON.stringify({ name: name || 'Nuevo hilo' })
    });
    const data = await r.json();
    await claimOwnThread(session, membership.id, data.thread && data.thread.slug);
    res.json(data);
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

// ── Documentos — enmascarado ANTES de subir (US4, plan.md §2) ─────────────────────────
app.post('/api/workspaces/upload', upload.single('file'), async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const { slug } = req.body || {};
  if (!req.file) return res.status(400).json({ error: 'No se recibió archivo.' });
  if (!slug) return res.status(400).json({ error: 'Falta el workspace destino.' });

  try {
    const membership = await findMemberWorkspaceBySlug(session, slug);
    if (!membership) {
      fs.unlinkSync(req.file.path);
      return res.status(403).json({ error: 'No tenés acceso a este espacio.' });
    }

    const rawName = Buffer.from(req.file.originalname, 'latin1').toString('utf8');
    const extractedText = extractText(req.file.path);

    // El original SIN enmascarar solo vive en disco lo que dura la extracción — se borra
    // acá, antes de que exista ninguna chance de que quede huérfano en `public/uploads/`
    // (spec 040 US4: el dato real no puede persistir en ningún punto del camino).
    fs.unlinkSync(req.file.path);

    // documentId (spec 044 US3): un solo id para TODOS los chunks de esta subida — mismo
    // valor detectado, mismo placeholder en cualquier parte del documento.
    // acted_for_user_id (US2): la llave de enmascarado actúa en nombre de esta persona.
    const { masked, blocked, budgetExceeded, motivo, entities, truncated, documentId } =
      await maskText(extractedText, { actingUserId: session.user.id });
    if (budgetExceeded) {
      return res.status(402).json({ error: 'Alcanzaste tu presupuesto asignado. Contactá a tu administrador.' });
    }
    if (blocked) {
      return res.status(422).json({ error: `Documento bloqueado por la política de protección de datos: ${motivo}` });
    }

    // Se sube el TEXTO ENMASCARADO como un .txt propio — el motor de documentos nunca ve
    // el archivo original con los datos reales, solo los placeholders.
    const maskedPath = `${req.file.path}.masked.txt`;
    fs.writeFileSync(maskedPath, masked, 'utf-8');

    // Nombre del archivo que ve el motor de documentos: SIEMPRE .txt, nunca la extensión
    // original. Elige el parser por extensión (.xlsx/.docx/.pdf usan parsers binarios
    // específicos) — lo que subimos acá es texto plano ya extraído y enmascarado, nunca
    // el binario original. Con la extensión original (ej. .xlsx) intentaba parsear texto
    // plano como Excel real y el contenido quedaba vacío o corrupto (bug real, encontrado
    // subiendo una planilla real: el RAG respondía "no tengo acceso a documentos").
    const uploadName = `${rawName}.txt`;
    const form = new FormData();
    form.append('file', new Blob([fs.readFileSync(maskedPath)], { type: 'text/plain' }), uploadName);

    const uploadResp = await fetch(`${ANYTHINGLLM_URL}/api/v1/document/upload`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${ANYTHINGLLM_API_KEY}` },
      body: form
    });
    fs.unlinkSync(maskedPath);
    if (!uploadResp.ok) return res.status(uploadResp.status).json({ error: 'El servicio de documentos no aceptó este archivo.' });
    const uploaded = await uploadResp.json();
    const doc = (uploaded.documents || [])[0];
    if (!doc) return res.status(502).json({ error: 'El servicio de documentos no devolvió el documento subido.' });

    await anythingllmFetch(`/api/v1/workspace/${slug}/update-embeddings`, {
      method: 'POST',
      body: JSON.stringify({ adds: [doc.location] })
    });

    const avisoTruncado = truncated
      ? ' ⚠️ El documento es grande — se indexó solo la primera parte (~150.000 caracteres) por ahora.'
      : '';
    res.json({
      success: true,
      document: { name: rawName, location: doc.location, entitiesEnmascaradas: entities, truncated: !!truncated, documentId },
      // Resumen agregado por DOCUMENTO, no por chunk (spec 044 US3) — cada tipo de dato
      // protegido se cuenta una sola vez para todo el archivo.
      message: `"${rawName}" protegido e indexado (${entities.length} tipo(s) de dato protegido detectado(s)).${avisoTruncado}`
    });
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

app.post('/api/workspaces/documents/delete', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const { slug, location } = req.body || {};
  try {
    const membership = await findMemberWorkspaceBySlug(session, slug);
    if (!membership) return res.status(403).json({ error: 'No tenés acceso a este espacio.' });
    const r = await anythingllmFetch(`/api/v1/workspace/${slug}/update-embeddings`, {
      method: 'POST',
      body: JSON.stringify({ deletes: [location] })
    });
    res.json({ success: r.ok });
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

// =========================================================================
// CHAT (US2 + US3) — dos caminos reales, nunca fabricado:
//   - Con workspace  → RAG real vía AnythingLLM (que a su vez habla con el motor de
//     elea; el enmascarado del turno de chat lo aplica el motor, transparente).
//   - Sin workspace   → chat simple directo a elea con el modelo elegido (o "auto").
// =========================================================================
// Copy neutro compartido (spec 044 US2/US6) — sea que el bloqueo lo decida el Hub antes
// de enviar, o que lo devuelva el backend con un 402 real, la persona ve SIEMPRE el mismo
// mensaje: nunca un error técnico, nunca una distinción entre "local" y "del servidor".
const MENSAJE_PRESUPUESTO_AGOTADO = 'Alcanzaste tu presupuesto. Contactá a tu administrador.';

app.post('/api/chat', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const { message, slug, threadSlug, model } = req.body || {};
  if (!message) return res.status(400).json({ error: 'Mensaje vacío.' });

  try {
    // FR-006 (spec 044 US2): verificar presupuesto ANTES de enviar, con la sesión
    // propia (autoservicio, contrato 2) — no una sesión de admin de fondo.
    const budget = await fetchOwnBudget(session).catch(() => null);
    if (budget && budget.status === 'exceeded') {
      return res.status(402).json({ error: MENSAJE_PRESUPUESTO_AGOTADO });
    }

    if (slug) {
      const membership = await findMemberWorkspaceBySlug(session, slug);
      if (!membership) return res.status(403).json({ error: 'No tenés acceso a este espacio.' });
      if (!(await ownsThreadSlug(session, membership.id, threadSlug))) {
        return res.status(403).json({ error: 'Ese hilo no te pertenece.' });
      }
      // Bug real 10-sep: "hilo principal" (sin threadSlug) NUNCA debe chatear contra el
      // espacio compartido — cada persona habla con su propio hilo real del motor.
      const realThreadSlug = threadSlug || await resolvePrincipalEngineThreadSlug(session, membership.id, slug);
      const path = `/api/v1/workspace/${slug}/thread/${realThreadSlug}/chat`;
      const r = await anythingllmFetch(path, {
        method: 'POST',
        body: JSON.stringify({ message, mode: 'chat' })
      });
      if (r.status === 402) return res.status(402).json({ error: MENSAJE_PRESUPUESTO_AGOTADO });
      if (!r.ok) return res.status(r.status).json({ error: 'El servicio de documentos no está disponible. Intentá de nuevo en unos minutos.' });
      const data = await r.json();
      return res.json({
        role: 'assistant',
        content: data.textResponse,
        sources: (data.sources || []).map((s) => ({ document: (s.title || '').replace(/\.txt$/i, ''), extracto: s.text })),
        model_used: data.metrics && data.metrics.model,
        via: 'rag'
      });
    }

    const r = await eleaFetch(session.token, '/chat/completions', {
      method: 'POST',
      body: JSON.stringify({ message, model: model || 'auto' })
    });
    if (r.status === 402) return res.status(402).json({ error: MENSAJE_PRESUPUESTO_AGOTADO });
    if (!r.ok) {
      const errBody = await r.json().catch(() => ({}));
      return res.status(r.status).json({ error: errBody.detail || 'No se pudo obtener una respuesta. Intentá de nuevo.' });
    }
    const data = await r.json();
    res.json({
      role: 'assistant',
      content: data.response,
      model_used: data.pipeline_metadata && data.pipeline_metadata.layer_llm && data.pipeline_metadata.layer_llm.model_used,
      via: 'direct'
    });
  } catch (err) {
    // Bug real encontrado en verificación en vivo (09-sep, P6 paso 1): con el motor de
    // documentos completamente CAÍDO (no solo respondiendo error, sino sin escuchar en
    // el puerto), `fetch()` lanza ANTES de llegar al `if (!r.ok)` de arriba — este catch
    // devolvía `err.message` crudo ("fetch failed", o peor con DNS: "getaddrinfo ENOTFOUND
    // anythingllm") directo al chat. Mismo criterio que el resto del handler: mensaje
    // neutro al usuario, el detalle técnico solo al log del servidor.
    console.error('POST /api/chat falló:', err.message);
    const mensaje = slug
      ? 'El servicio de documentos no está disponible. Intentá de nuevo en unos minutos.'
      : 'No se pudo obtener una respuesta. Intentá de nuevo.';
    res.status(502).json({ error: mensaje });
  }
});

// =========================================================================
// ANÁLISIS EXACTO DE DATOS (spec 046, UI) — 1:1 proxy hacia el backend (spec 048, ya
// probado en vivo). El Hub NUNCA habla con el motor de análisis exacto directamente —
// mismo criterio de "solo el backend proxea autenticación/atribución" que ya rige RAG.
// =========================================================================
const MENSAJE_MOTOR_ANALISIS_NO_DISPONIBLE =
  'El servicio de análisis de datos no está disponible. Intentá de nuevo en unos minutos.';

app.post('/api/exact-analysis/workspaces', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const { display_name } = req.body || {};
  if (!display_name) return res.status(400).json({ error: 'Falta el nombre del espacio.' });
  try {
    const r = await eleaFetch(session.token, '/exact-analysis/workspaces', {
      method: 'POST',
      body: JSON.stringify({ display_name })
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) return res.status(r.status).json({ error: data.detail || 'No se pudo crear el espacio.' });
    res.json(data);
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

// Espacios de análisis exacto propios — reusa /workspaces (ya trae `kind`, spec 048) y
// filtra del lado del Hub; no hace falta un endpoint de listado aparte en el backend.
app.get('/api/exact-analysis/workspaces', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  try {
    const all = await getMemberWorkspaces(session);
    res.json({ workspaces: all.filter((w) => w.kind === 'exact_analysis') });
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

app.post('/api/exact-analysis/workspaces/:id/files', upload.single('file'), async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const { id } = req.params;
  if (!req.file) return res.status(400).json({ error: 'No se recibió archivo.' });

  const ext = (req.file.originalname.split('.').pop() || '').toLowerCase();
  if (!['csv', 'xlsx', 'xls'].includes(ext)) {
    fs.unlinkSync(req.file.path);
    return res.status(422).json({
      error: 'Este modo solo acepta planillas (.csv, .xlsx, .xls) — para otro tipo de documento, usá el chat normal.'
    });
  }

  try {
    let buffer = fs.readFileSync(req.file.path);
    let contentType = req.file.mimetype || 'text/csv';

    // Enmascarado ANTES de que el dato salga del Hub (FR-003) — hoy solo para .csv (texto
    // delimitado real: enmascarar valor por valor conserva filas/columnas intactas, el motor
    // sigue pudiendo calcular sobre la estructura). .xlsx es binario — extraer, enmascarar y
    // re-empaquetar como .xlsx real queda FUERA de esta ronda (T090 de la 048, documentado,
    // no escondido: ver el log de abajo). Sigue siendo mejor que no enmascarar nada.
    if (ext === 'csv') {
      const rawText = buffer.toString('utf-8');
      const { masked, blocked, budgetExceeded, motivo } =
        await maskCsvText(rawText, { actingUserId: session.user.id });
      fs.unlinkSync(req.file.path);
      if (budgetExceeded) return res.status(402).json({ error: MENSAJE_PRESUPUESTO_AGOTADO });
      if (blocked) {
        return res.status(422).json({ error: `Archivo bloqueado por la política de protección de datos: ${motivo}` });
      }
      buffer = Buffer.from(masked, 'utf-8');
      contentType = 'text/csv';
    } else {
      console.warn(
        `exact-analysis: subida .${ext} SIN pasar por enmascarado (T090 de la spec 048, ` +
        'pendiente) — solo .csv lo aplica hoy.'
      );
      fs.unlinkSync(req.file.path);
    }

    // Bug real encontrado en vivo (11-sep): `eleaFetch` fuerza SIEMPRE
    // `Content-Type: application/json` — para un `FormData` eso pisa el boundary
    // multipart real que el propio `fetch` arma solo, y el backend recibía un body
    // multipart con Content-Type mintiendo "json" (422, `doc_file` nunca llegaba
    // parseado). Mismo motivo por el que el upload de AnythingLLM (más arriba en este
    // archivo) tampoco usa `eleaFetch` — un fetch directo, sin forzar headers.
    const form = new FormData();
    form.append('doc_file', new Blob([buffer], { type: contentType }), req.file.originalname);
    const r = await fetch(`${ELEA_BACKEND_URL}/exact-analysis/workspaces/${id}/files`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${session.token}` },
      body: form
    });
    const data = await r.json().catch(() => ({}));
    if (r.status === 403) return res.status(403).json({ error: 'No tenés acceso a este espacio.' });
    if (!r.ok) return res.status(r.status).json({ error: MENSAJE_MOTOR_ANALISIS_NO_DISPONIBLE });
    res.json(data);
  } catch (err) {
    console.error('exact-analysis upload falló:', err.message);
    res.status(502).json({ error: MENSAJE_MOTOR_ANALISIS_NO_DISPONIBLE });
  }
});

app.post('/api/exact-analysis/workspaces/:id/query', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const { id } = req.params;
  const { question, conv_uid, select_param } = req.body || {};
  if (!question || !conv_uid || !select_param) {
    return res.status(400).json({ error: 'Faltan datos del archivo — subilo de nuevo.' });
  }
  try {
    const r = await eleaFetch(session.token, `/exact-analysis/workspaces/${id}/query`, {
      method: 'POST',
      body: JSON.stringify({ question, conv_uid, select_param })
    });
    const data = await r.json().catch(() => ({}));
    if (r.status === 402) return res.status(402).json({ error: MENSAJE_PRESUPUESTO_AGOTADO });
    if (r.status === 403) return res.status(403).json({ error: 'No tenés acceso a este espacio.' });
    if (!r.ok) return res.status(r.status).json({ error: MENSAJE_MOTOR_ANALISIS_NO_DISPONIBLE });
    res.json(data);
  } catch (err) {
    console.error('exact-analysis query falló:', err.message);
    res.status(502).json({ error: MENSAJE_MOTOR_ANALISIS_NO_DISPONIBLE });
  }
});

// Spec 044 (Setup, T001): solo escucha cuando se ejecuta directo (`node server.js` /
// `npm start`) — al `require()`-arlo desde un test (node:test + supertest) el módulo
// exporta `app` sin abrir un puerto real. Comportamiento de producción sin cambios.
if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`Eleia Hub escuchando en http://localhost:${PORT}`);
    console.log(`  Guardian:              ${ELEA_BACKEND_URL}`);
    console.log(`  servicio de documentos: ${ANYTHINGLLM_URL}`);
  });
}

module.exports = app;
