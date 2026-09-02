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
const ELEA_SERVICE_USERNAME = process.env.ELEA_SERVICE_USERNAME || 'admin';
const ELEA_SERVICE_PASSWORD = process.env.ELEA_SERVICE_PASSWORD || '';
const ANYTHINGLLM_URL = process.env.ANYTHINGLLM_URL || 'http://anythingllm:3001';
const ANYTHINGLLM_API_KEY = process.env.ANYTHINGLLM_API_KEY || '';
const MASKING_VIRTUAL_KEY = process.env.MASKING_VIRTUAL_KEY || '';

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

// Sesión de SERVICIO (spec 040 plan.md §3, opción b): un usuario admin dedicado cuyo JWT
// el cliente usa para consultar presupuesto en nombre del usuario logueado, sin exponer
// esa credencial al navegador. Se re-obtiene sola cuando expira (401).
let serviceToken = null;

async function eleaLogin(username, password) {
  const r = await fetch(`${ELEA_BACKEND_URL}/users/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  });
  const data = await r.json().catch(() => ({}));
  return { ok: r.ok, status: r.status, data };
}

async function getServiceToken(forceRefresh = false) {
  if (serviceToken && !forceRefresh) return serviceToken;
  if (!ELEA_SERVICE_PASSWORD) {
    throw new Error('ELEA_SERVICE_PASSWORD no configurada — no se puede consultar presupuesto.');
  }
  const { ok, data } = await eleaLogin(ELEA_SERVICE_USERNAME, ELEA_SERVICE_PASSWORD);
  if (!ok) throw new Error('La sesión de servicio del cliente no pudo autenticarse contra elea.');
  serviceToken = data.access_token;
  return serviceToken;
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

// Llamada con la sesión de SERVICIO (presupuesto), con un reintento si el JWT expiró.
async function eleaServiceFetch(pathname, opts = {}) {
  let token = await getServiceToken();
  let r = await fetch(`${ELEA_BACKEND_URL}${pathname}`, {
    ...opts,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...(opts.headers || {}) }
  });
  if (r.status === 401) {
    token = await getServiceToken(true);
    r = await fetch(`${ELEA_BACKEND_URL}${pathname}`, {
      ...opts,
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...(opts.headers || {}) }
    });
  }
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

// Enmascarado NER real (spec 040 US4): misma política que el resto de `elea`
// (POST /api/v1/gw/inspect, latam_ar hoy — DNI/CUIL/CBU). Fail-closed: si el motor de
// detección no responde, NO se sube el texto sin enmascarar — se corta la subida.
async function maskChunk(text) {
  if (!text) return { masked: '', blocked: false, entities: [] };
  const r = await fetch(`${ELEA_BACKEND_URL}/gw/inspect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Sentinel-Key': MASKING_VIRTUAL_KEY },
    body: JSON.stringify({ text, tool: 'elea-rag-client' })
  });
  if (!r.ok) throw new Error(`Enmascarado no disponible (HTTP ${r.status}) — no se sube el documento.`);
  const data = await r.json();
  // BUG real encontrado 31-ago con un archivo real (238 registros de salud): `ok:false`
  // no significa SOLO "key inválida" — también lo devuelve un bloqueo real de la capa de
  // gobernanza (`blocked:true`, con `motivo` explicando por qué). El mensaje anterior
  // ("sin key válida") era falso en ese caso y ocultaba la razón real del bloqueo.
  if (data.blocked) {
    return { masked: '', blocked: true, motivo: data.motivo || 'Bloqueado por la política de contenido.', entities: [] };
  }
  if (!data.ok) throw new Error('El motor de enmascarado no respondió correctamente (verificar la virtual key).');
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

async function maskText(text) {
  if (!text) return { masked: '', blocked: false, entities: [], truncated: false };
  const truncated = text.length > MASK_MAX_TOTAL_CHARS;
  const usable = truncated ? text.slice(0, MASK_MAX_TOTAL_CHARS) : text;
  const chunks = splitIntoChunks(usable);
  const maskedParts = [];
  const allEntities = [];
  for (const chunk of chunks) {
    const result = await maskChunk(chunk);
    if (result.blocked) return result; // un pedazo bloqueado bloquea todo el documento
    maskedParts.push(result.masked);
    allEntities.push(...result.entities);
  }
  // Sumar counts por tipo de entidad entre los pedazos (cada chunk cuenta desde 0).
  const merged = {};
  for (const e of allEntities) merged[e.type] = (merged[e.type] || 0) + e.count;
  return {
    masked: maskedParts.join('\n'),
    blocked: false,
    entities: Object.entries(merged).map(([type, count]) => ({ type, count })),
    truncated
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
    res.status(502).json({ error: `No se pudo contactar a elea: ${err.message}` });
  }
});

app.post('/api/auth/logout', (req, res) => {
  setSession(req, null);
  res.json({ success: true });
});

app.get('/api/user/current', async (req, res) => {
  const session = getSession(req);
  if (!session) return res.json({ isAuthenticated: false });

  const [budget, workspaces] = await Promise.all([
    fetchUserBudget(session.user.id).catch((err) => ({ error: err.message })),
    fetchWorkspacesSummary().catch(() => [])
  ]);

  res.json({
    isAuthenticated: true,
    user: session.user,
    budget,
    workspaces
  });
});

async function fetchUserBudget(userId) {
  const r = await eleaServiceFetch('/budgets');
  if (!r.ok) throw new Error(`No se pudo leer el presupuesto (HTTP ${r.status}).`);
  const budgets = await r.json();
  const mine = budgets.find((b) => b.user_id === userId);
  if (!mine) return { maxUsd: null, usedUsd: null, message: 'Sin presupuesto asignado.' };
  return {
    maxUsd: parseFloat(mine.max_spend_usd),
    usedUsd: parseFloat(mine.current_spend_usd),
    resetPeriod: mine.reset_period
  };
}

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
// WORKSPACES (US3) — proxy real a la API de AnythingLLM, con las opciones reales.
// =========================================================================
async function fetchWorkspacesSummary() {
  const r = await anythingllmFetch('/api/v1/workspaces');
  if (!r.ok) return [];
  const data = await r.json();
  return (data.workspaces || []).map((w) => ({
    slug: w.slug,
    name: w.name,
    chatMode: w.chatMode,
    documentCount: (w.documents || []).length
  }));
}

app.get('/api/workspaces', async (req, res) => {
  try {
    const r = await anythingllmFetch('/api/v1/workspaces');
    if (!r.ok) return res.status(r.status).json({ error: 'AnythingLLM no respondió.' });
    res.json(await r.json());
  } catch (err) {
    res.status(502).json({ error: `No se pudo contactar a AnythingLLM: ${err.message}` });
  }
});

app.get('/api/workspaces/:slug', async (req, res) => {
  try {
    const r = await anythingllmFetch(`/api/v1/workspace/${req.params.slug}`);
    if (!r.ok) return res.status(r.status).json({ error: 'Workspace no encontrado.' });
    res.json(await r.json());
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

// Historial real de un hilo (o del hilo principal del espacio si no se pasa
// threadSlug) — AnythingLLM SÍ persiste los mensajes server-side; hasta acá el
// cliente los tiraba al cambiar de hilo/espacio y volvían a aparecer vacíos
// (bug real reportado 02-sep: "salía del hilo y volvía, desaparecía la info").
app.get('/api/workspaces/:slug/messages', async (req, res) => {
  const { slug } = req.params;
  const { threadSlug } = req.query;
  const path = threadSlug
    ? `/api/v1/workspace/${slug}/thread/${threadSlug}/chats`
    : `/api/v1/workspace/${slug}/chats`;
  try {
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
  const { name } = req.body || {};
  if (!name) return res.status(400).json({ error: 'El workspace necesita un nombre.' });
  try {
    const createResp = await anythingllmFetch('/api/v1/workspace/new', {
      method: 'POST',
      body: JSON.stringify({ name })
    });
    if (!createResp.ok) return res.status(createResp.status).json({ error: 'AnythingLLM no pudo crear el workspace.' });
    const created = await createResp.json();
    const slug = created.workspace.slug;

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
    res.status(502).json({ error: `No se pudo contactar a AnythingLLM: ${err.message}` });
  }
});

app.post('/api/workspaces/settings', async (req, res) => {
  const { slug } = req.body || {};
  if (!slug) return res.status(400).json({ error: 'Falta el workspace.' });
  const settings = pickWorkspaceSettings(req.body);
  try {
    const r = await anythingllmFetch(`/api/v1/workspace/${slug}/update`, {
      method: 'POST',
      body: JSON.stringify(settings)
    });
    if (!r.ok) return res.status(r.status).json({ error: 'No se pudo actualizar el workspace.' });
    res.json(await r.json());
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

app.post('/api/workspaces/delete', async (req, res) => {
  const { slug } = req.body || {};
  if (!slug) return res.status(400).json({ error: 'Falta el workspace.' });
  try {
    const r = await anythingllmFetch(`/api/v1/workspace/${slug}`, { method: 'DELETE' });
    res.json({ success: r.ok });
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

// ── Hilos ──────────────────────────────────────────────────────────────────
app.post('/api/threads/create', async (req, res) => {
  const { slug, name } = req.body || {};
  if (!slug) return res.status(400).json({ error: 'Falta el workspace.' });
  try {
    const r = await anythingllmFetch(`/api/v1/workspace/${slug}/thread/new`, {
      method: 'POST',
      body: JSON.stringify({ name: name || 'Nuevo hilo' })
    });
    if (!r.ok) return res.status(r.status).json({ error: 'No se pudo crear el hilo.' });
    res.json(await r.json());
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

app.post('/api/threads/rename', async (req, res) => {
  const { slug, threadSlug, name } = req.body || {};
  try {
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
  const { slug, threadSlug } = req.body || {};
  try {
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
  const { slug, threadSlug, name } = req.body || {};
  try {
    await anythingllmFetch(`/api/v1/workspace/${slug}/thread/${threadSlug}`, { method: 'DELETE' });
    const r = await anythingllmFetch(`/api/v1/workspace/${slug}/thread/new`, {
      method: 'POST',
      body: JSON.stringify({ name: name || 'Nuevo hilo' })
    });
    res.json(await r.json());
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

// ── Documentos — enmascarado ANTES de subir (US4, plan.md §2) ─────────────────────────
app.post('/api/workspaces/upload', upload.single('file'), async (req, res) => {
  const { slug } = req.body || {};
  if (!req.file) return res.status(400).json({ error: 'No se recibió archivo.' });
  if (!slug) return res.status(400).json({ error: 'Falta el workspace destino.' });

  try {
    const rawName = Buffer.from(req.file.originalname, 'latin1').toString('utf8');
    const extractedText = extractText(req.file.path);

    // El original SIN enmascarar solo vive en disco lo que dura la extracción — se borra
    // acá, antes de que exista ninguna chance de que quede huérfano en `public/uploads/`
    // (spec 040 US4: el dato real no puede persistir en ningún punto del camino).
    fs.unlinkSync(req.file.path);

    const { masked, blocked, motivo, entities, truncated } = await maskText(extractedText);
    if (blocked) {
      return res.status(422).json({ error: `Documento bloqueado por la gobernanza de elea: ${motivo}` });
    }

    // Se sube el TEXTO ENMASCARADO como un .txt propio — AnythingLLM nunca ve el
    // archivo original con los datos reales, solo los placeholders.
    const maskedPath = `${req.file.path}.masked.txt`;
    fs.writeFileSync(maskedPath, masked, 'utf-8');

    // Nombre del archivo que ve AnythingLLM: SIEMPRE .txt, nunca la extensión original.
    // AnythingLLM elige el parser por extensión (.xlsx/.docx/.pdf usan parsers binarios
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
    if (!uploadResp.ok) return res.status(uploadResp.status).json({ error: 'AnythingLLM rechazó el documento.' });
    const uploaded = await uploadResp.json();
    const doc = (uploaded.documents || [])[0];
    if (!doc) return res.status(502).json({ error: 'AnythingLLM no devolvió el documento subido.' });

    await anythingllmFetch(`/api/v1/workspace/${slug}/update-embeddings`, {
      method: 'POST',
      body: JSON.stringify({ adds: [doc.location] })
    });

    const avisoTruncado = truncated
      ? ' ⚠️ El documento es grande — se indexó solo la primera parte (~150.000 caracteres) por ahora.'
      : '';
    res.json({
      success: true,
      document: { name: rawName, location: doc.location, entitiesEnmascaradas: entities, truncated: !!truncated },
      message: `"${rawName}" enmascarado e indexado (${entities.length} tipo(s) de dato protegido detectado(s)).${avisoTruncado}`
    });
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

app.post('/api/workspaces/documents/delete', async (req, res) => {
  const { slug, location } = req.body || {};
  try {
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
app.post('/api/chat', async (req, res) => {
  const session = getSession(req);
  if (!session) return res.status(401).json({ error: 'Sin sesión activa.' });
  const { message, slug, threadSlug, model } = req.body || {};
  if (!message) return res.status(400).json({ error: 'Mensaje vacío.' });

  try {
    if (slug) {
      const path = threadSlug
        ? `/api/v1/workspace/${slug}/thread/${threadSlug}/chat`
        : `/api/v1/workspace/${slug}/chat`;
      const r = await anythingllmFetch(path, {
        method: 'POST',
        body: JSON.stringify({ message, mode: 'chat' })
      });
      if (!r.ok) return res.status(r.status).json({ error: 'AnythingLLM no pudo responder.' });
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
    if (!r.ok) {
      const errBody = await r.json().catch(() => ({}));
      return res.status(r.status).json({ error: errBody.detail || 'elea no pudo responder.' });
    }
    const data = await r.json();
    res.json({
      role: 'assistant',
      content: data.response,
      model_used: data.pipeline_metadata && data.pipeline_metadata.layer_llm && data.pipeline_metadata.layer_llm.model_used,
      via: 'direct'
    });
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

app.listen(PORT, () => {
  console.log(`Cliente RAG de Elea escuchando en http://localhost:${PORT}`);
  console.log(`  elea backend:   ${ELEA_BACKEND_URL}`);
  console.log(`  AnythingLLM:    ${ANYTHINGLLM_URL}`);
});
