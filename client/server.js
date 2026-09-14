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
// Motores opcionales (spec 050 FR-010): vacío = el motor no existe en esta instalación y la
// UI oculta su sección. El Hub arranca con cualquier combinación (solo Guardian es obligatorio).
const TABULAR_URL = (process.env.TABULAR_URL || '').replace(/\/$/, '');
const TABULAR_INTERNAL_TOKEN = process.env.TABULAR_INTERNAL_TOKEN || '';
const PRESENTON_URL = (process.env.PRESENTON_URL || '').replace(/\/$/, '');
const DOCGEN_URL = (process.env.DOCGEN_URL || '').replace(/\/$/, '');
// Artefactos generados por persona (spec 050 FR-015): pptx/pdf hoy, docx/xlsx después.
const ARTIFACTS_DIR = process.env.ARTIFACTS_DIR || path.join(__dirname, 'data', 'artifacts');
const PRESENTON_TIMEOUT_MS = parseInt(process.env.PRESENTON_TIMEOUT_MS || '300000', 10);
// Administración de plantillas (spec 050, pedido 13-sep): en vez de programar en el Hub la
// creación de plantillas desde un PPTX, se reusa ENTERA la pantalla de Presenton, publicada por
// el Hub en un segundo puerto solo para administradores (sesión del Hub + rol admin). Presenton
// sigue sin puertos propios (FR-032): el único camino es este proxy.
const PRESENTON_ADMIN_PORT = parseInt(process.env.PRESENTON_ADMIN_PORT || '0', 10);
const HUB_ADMIN_ROLES = ['super_admin', 'tenant_admin'];

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

// Spec 050 (12-sep-2026): el Hub YA NO enmascara. Guardian es firewall + base de usuarios y
// no recibe archivos: los documentos suben crudos al motor de documentos local y la PII se
// enmascara únicamente cuando el motor manda el prompt por `engine:4000/v1/chat/completions`.
// El bloque de enmascarado por trozos (`maskText`/`maskCsvText`/`maskXlsxBuffer`, `/gw/inspect`,
// `MASKING_VIRTUAL_KEY`) se retiró entero — ver specs/050-ia-hub-conector-motores (FR-001/002).

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
    workspaces
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
    const all = await getMemberWorkspaces(session);
    // Bug real encontrado en vivo (11-sep, spec 046): esta ruta alimenta el sidebar del
    // modo Chat normal — sin filtrar, los espacios `kind=exact_analysis` (que tienen su
    // propia sección en el modo "Planillas", ver /api/tabular/workspaces más
    // abajo) también aparecían acá, mezclando los dos modos contra FR-001 (deben quedar
    // SIEMPRE separados). `kind` es `'rag'` por default (columna vieja, sin backfill) —
    // por eso el filtro es "no es exact_analysis", no "es rag", para no perder espacios
    // preexistentes que nunca tuvieron `kind` seteado explícito.
    res.json({ workspaces: all.filter((w) => w.kind !== 'exact_analysis') });
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

    // El original solo vive en disco lo que dura la extracción — se borra acá, antes de
    // que exista ninguna chance de que quede huérfano en `public/uploads/`.
    fs.unlinkSync(req.file.path);

    // Nombre del archivo que ve el motor de documentos: SIEMPRE .txt, nunca la extensión
    // original. Elige el parser por extensión (.xlsx/.docx/.pdf usan parsers binarios
    // específicos) — lo que subimos acá es texto plano ya extraído, nunca el binario
    // original. Con la extensión original (ej. .xlsx) intentaba parsear texto plano como
    // Excel real y el contenido quedaba vacío o corrupto (bug real, encontrado subiendo una
    // planilla real: el RAG respondía "no tengo acceso a documentos").
    const uploadName = `${rawName}.txt`;
    const form = new FormData();
    form.append('file', new Blob([extractedText], { type: 'text/plain' }), uploadName);

    const uploadResp = await fetch(`${ANYTHINGLLM_URL}/api/v1/document/upload`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${ANYTHINGLLM_API_KEY}` },
      body: form
    });
    if (!uploadResp.ok) return res.status(uploadResp.status).json({ error: 'El servicio de documentos no aceptó este archivo.' });
    const uploaded = await uploadResp.json();
    const doc = (uploaded.documents || [])[0];
    if (!doc) return res.status(502).json({ error: 'El servicio de documentos no devolvió el documento subido.' });

    await anythingllmFetch(`/api/v1/workspace/${slug}/update-embeddings`, {
      method: 'POST',
      body: JSON.stringify({ adds: [doc.location] })
    });

    res.json({
      success: true,
      document: { name: rawName, location: doc.location },
      message: `"${rawName}" indexado.`
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
// MOTORES CONFIGURADOS (spec 050 FR-010) — la UI pregunta qué hay y oculta lo que no.
// =========================================================================
app.get('/api/features', (req, res) => {
  res.json({
    documents: !!process.env.ANYTHINGLLM_URL || !!ANYTHINGLLM_API_KEY,
    tabular: !!(TABULAR_URL && TABULAR_INTERNAL_TOKEN),
    presentations: !!PRESENTON_URL,
    presentations_admin_port: (PRESENTON_URL && PRESENTON_ADMIN_PORT) ? PRESENTON_ADMIN_PORT : null,
    docgen: !!DOCGEN_URL
  });
});

// =========================================================================
// ANÁLISIS DE PLANILLAS — motor tabular (spec 050 US2, contratos 02 y 03 §3.2).
// El Hub verifica membresía contra Guardian ANTES de tocar el motor (FR-011); el motor
// confía en el Hub por red interna + token. Guardian nunca ve el archivo.
// =========================================================================
const MENSAJE_MOTOR_ANALISIS_NO_DISPONIBLE =
  'El servicio de análisis de datos no está disponible. Intentá de nuevo en unos minutos.';
const MENSAJE_SIN_ACCESO = 'No tenés acceso a este espacio.';

function tabularDisponible(res) {
  if (TABULAR_URL && TABULAR_INTERNAL_TOKEN) return true;
  res.status(404).json({ error: 'El análisis de planillas no está habilitado en esta instalación.', code: 'feature_disabled' });
  return false;
}

async function tabularFetch(session, pathname, opts = {}) {
  const r = await fetch(`${TABULAR_URL}${pathname}`, {
    ...opts,
    headers: {
      Authorization: `Bearer ${TABULAR_INTERNAL_TOKEN}`,
      'X-Hub-User-Id': session.user.id,
      ...(opts.headers || {})
    }
  });
  return r;
}

// Membresía real contra Guardian (FR-011): 403 uniforme, nunca revela si el espacio existe.
async function requireTabularWorkspace(session, id, res) {
  const r = await eleaFetch(session.token, `/workspaces/${encodeURIComponent(id)}`);
  if (r.status === 403 || r.status === 404) {
    res.status(403).json({ error: MENSAJE_SIN_ACCESO });
    return null;
  }
  if (!r.ok) throw new Error(`No se pudo verificar el espacio (HTTP ${r.status}).`);
  const ws = await r.json();
  if (ws.kind && ws.kind !== 'exact_analysis') {
    res.status(403).json({ error: MENSAJE_SIN_ACCESO });
    return null;
  }
  return ws;
}

// El espacio en el motor se crea a demanda (idempotente): si Guardian registró el espacio
// pero el motor no lo tenía (motor caído al crear, volumen nuevo), se crea acá.
async function ensureTabularSpace(session, id) {
  const r = await tabularFetch(session, '/v1/spaces', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace_id: id })
  });
  if (r.status !== 201 && r.status !== 409) throw new Error(`tabular no pudo crear el espacio (HTTP ${r.status}).`);
}

function mensajeErrorTabular(status, data) {
  const code = data && data.detail && data.detail.code;
  if (status === 502 && code === 'engine_error') {
    const s = data.detail.status;
    if (s === 402) return [402, MENSAJE_PRESUPUESTO_AGOTADO];
    if (s === 400) return [422, 'La pregunta fue bloqueada por la política de protección de datos.'];
    return [502, MENSAJE_MOTOR_ANALISIS_NO_DISPONIBLE];
  }
  const porCodigo = {
    unsafe_sql: [422, 'No pude responder con una consulta segura. Probá reformular la pregunta.'],
    sql_error: [422, 'No pude armar una consulta válida para esa pregunta. Probá reformularla.'],
    not_answerable: [422, 'Esa pregunta no se puede responder con los datos de las planillas de este espacio. Preguntá por lo que está en sus columnas (cantidades, sumas, cruces, búsquedas por un término).'],
    no_files: [422, 'Este espacio todavía no tiene planillas. Subí una primero.'],
    unsupported_format: [415, 'Este modo solo acepta planillas .csv y .xlsx.'],
    file_too_large: [413, `El archivo supera el máximo permitido (${(data.detail && data.detail.max_mb) || 50} MB).`],
    empty_file: [422, 'La planilla no tiene datos.'],
    unreadable_file: [422, 'No se pudo leer la planilla. Verificá que no esté dañada.'],
    timeout: [504, 'La consulta tardó demasiado. Probá con una pregunta más acotada.'],
    file_not_found: [404, 'Ese archivo ya no está en el espacio.'],
    space_not_found: [404, 'El espacio no existe en el motor de análisis.']
  };
  return porCodigo[code] || [502, MENSAJE_MOTOR_ANALISIS_NO_DISPONIBLE];
}

app.post('/api/tabular/workspaces', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  if (!tabularDisponible(res)) return;
  const { display_name } = req.body || {};
  if (!display_name) return res.status(400).json({ error: 'Falta el nombre del espacio.' });
  try {
    // Registro de acceso en Guardian (FR-041: `kind` al crear) — quién ve este espacio.
    const r = await eleaFetch(session.token, '/workspaces', {
      method: 'POST',
      body: JSON.stringify({ display_name, kind: 'exact_analysis' })
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) return res.status(r.status).json({ error: data.detail || 'No se pudo crear el espacio.' });
    // Base del espacio en el motor (a demanda si acá falla — ver ensureTabularSpace).
    try { await ensureTabularSpace(session, data.id); } catch (err) { console.warn('tabular:', err.message); }
    res.json({ id: data.id, display_name: data.display_name, kind: 'exact_analysis', role: 'owner' });
  } catch (err) {
    console.error('tabular crear espacio falló:', err.message);
    res.status(502).json({ error: MENSAJE_MOTOR_ANALISIS_NO_DISPONIBLE });
  }
});

// Espacios de planillas propios — reusa /workspaces (trae `kind`) y filtra del lado del Hub.
app.get('/api/tabular/workspaces', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  if (!tabularDisponible(res)) return;
  try {
    const all = await getMemberWorkspaces(session);
    res.json({ workspaces: all.filter((w) => w.kind === 'exact_analysis') });
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

app.get('/api/tabular/workspaces/:id/files', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  if (!tabularDisponible(res)) return;
  try {
    if (!(await requireTabularWorkspace(session, req.params.id, res))) return;
    await ensureTabularSpace(session, req.params.id);
    const r = await tabularFetch(session, `/v1/spaces/${encodeURIComponent(req.params.id)}/files`);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { const [st, msg] = mensajeErrorTabular(r.status, data); return res.status(st).json({ error: msg }); }
    res.json(data);
  } catch (err) {
    console.error('tabular listar archivos falló:', err.message);
    res.status(502).json({ error: MENSAJE_MOTOR_ANALISIS_NO_DISPONIBLE });
  }
});

app.post('/api/tabular/workspaces/:id/files', upload.single('file'), async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  if (!tabularDisponible(res)) { if (req.file) fs.unlinkSync(req.file.path); return; }
  const { id } = req.params;
  if (!req.file) return res.status(400).json({ error: 'No se recibió archivo.' });
  const rawName = Buffer.from(req.file.originalname, 'latin1').toString('utf8');
  const ext = (rawName.split('.').pop() || '').toLowerCase();
  if (!['csv', 'xlsx'].includes(ext)) {
    fs.unlinkSync(req.file.path);
    return res.status(415).json({
      error: 'Este modo solo acepta planillas .csv y .xlsx — para otro tipo de documento, usá el chat normal.'
    });
  }
  try {
    const buffer = fs.readFileSync(req.file.path);
    fs.unlinkSync(req.file.path);
    if (buffer.length > 50 * 1024 * 1024) return res.status(413).json({ error: 'El archivo supera el máximo permitido (50 MB).' });
    if (!(await requireTabularWorkspace(session, id, res))) return;
    await ensureTabularSpace(session, id);
    // Multipart real: nunca por `eleaFetch`/JSON (bug real del 11-sep, mismo criterio que la
    // subida al motor de documentos más arriba).
    const form = new FormData();
    form.append('file', new Blob([buffer], { type: req.file.mimetype || 'application/octet-stream' }), rawName);
    const r = await tabularFetch(session, `/v1/spaces/${encodeURIComponent(id)}/files`, { method: 'POST', body: form });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { const [st, msg] = mensajeErrorTabular(r.status, data); return res.status(st).json({ error: msg }); }
    res.json(data);
  } catch (err) {
    if (req.file && fs.existsSync(req.file.path)) {
      try { fs.unlinkSync(req.file.path); } catch (_) { /* ya no está */ }
    }
    console.error('tabular subida falló:', err.message);
    res.status(502).json({ error: MENSAJE_MOTOR_ANALISIS_NO_DISPONIBLE });
  }
});

// Diccionario de datos del espacio (pedido del dueño 13-sep): qué significa cada columna.
// Viaja al modelo con cada pregunta. Cualquier miembro del espacio puede editarlo.
app.put('/api/tabular/workspaces/:id/dictionary', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  if (!tabularDisponible(res)) return;
  const tables = (req.body && req.body.tables) || {};
  if (typeof tables !== 'object') return res.status(400).json({ error: 'Formato inválido.' });
  try {
    if (!(await requireTabularWorkspace(session, req.params.id, res))) return;
    const r = await tabularFetch(session, `/v1/spaces/${encodeURIComponent(req.params.id)}/dictionary`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tables })
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { const [st, msg] = mensajeErrorTabular(r.status, data); return res.status(st).json({ error: msg }); }
    res.json(data);
  } catch (err) {
    console.error('tabular diccionario falló:', err.message);
    res.status(502).json({ error: MENSAJE_MOTOR_ANALISIS_NO_DISPONIBLE });
  }
});

app.delete('/api/tabular/workspaces/:id/files/:fileId', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  if (!tabularDisponible(res)) return;
  try {
    if (!(await requireTabularWorkspace(session, req.params.id, res))) return;
    const r = await tabularFetch(session,
      `/v1/spaces/${encodeURIComponent(req.params.id)}/files/${encodeURIComponent(req.params.fileId)}`, { method: 'DELETE' });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { const [st, msg] = mensajeErrorTabular(r.status, data); return res.status(st).json({ error: msg }); }
    res.json({ status: 'ok' });
  } catch (err) {
    console.error('tabular borrar archivo falló:', err.message);
    res.status(502).json({ error: MENSAJE_MOTOR_ANALISIS_NO_DISPONIBLE });
  }
});

app.post('/api/tabular/workspaces/:id/query', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  if (!tabularDisponible(res)) return;
  const { id } = req.params;
  const { question, history } = req.body || {};
  if (!question || typeof question !== 'string') return res.status(400).json({ error: 'Falta la pregunta.' });
  try {
    // Presupuesto propio antes de gastar (mismo criterio que /api/chat).
    const budget = await fetchOwnBudget(session).catch(() => null);
    if (budget && budget.status === 'exceeded') return res.status(402).json({ error: MENSAJE_PRESUPUESTO_AGOTADO });
    if (!(await requireTabularWorkspace(session, id, res))) return;
    const hist = Array.isArray(history)
      ? history.slice(-5).map((h) => ({ question: String(h.question || ''), answer: String(h.answer || '') }))
      : [];
    const r = await tabularFetch(session, `/v1/spaces/${encodeURIComponent(id)}/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: question.slice(0, 4000), history: hist })
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { const [st, msg] = mensajeErrorTabular(r.status, data); return res.status(st).json({ error: msg }); }
    res.json({ answer: data.answer, sql: data.sql, columns: data.columns, rows: data.rows, model_used: data.model_used });
  } catch (err) {
    console.error('tabular consulta falló:', err.message);
    res.status(502).json({ error: MENSAJE_MOTOR_ANALISIS_NO_DISPONIBLE });
  }
});

// =========================================================================
// ARTEFACTOS GENERADOS (spec 050 FR-015) — almacén propio del Hub, por persona.
// `/app/data/artifacts/<userId>/<uuid>.<ext>` + `index.json`. Descarga solo para la dueña.
// =========================================================================
function artifactsUserDir(userId) {
  const safe = String(userId).replace(/[^A-Za-z0-9_-]/g, '');
  const dir = path.join(ARTIFACTS_DIR, safe);
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}
function readArtifactIndex(userId) {
  const p = path.join(artifactsUserDir(userId), 'index.json');
  try { return JSON.parse(fs.readFileSync(p, 'utf-8')); } catch (_) { return []; }
}
function writeArtifactIndex(userId, list) {
  const dir = artifactsUserDir(userId);
  const tmp = path.join(dir, 'index.json.tmp');
  fs.writeFileSync(tmp, JSON.stringify(list, null, 1), 'utf-8');
  fs.renameSync(tmp, path.join(dir, 'index.json'));
}
function saveArtifact(userId, { kind, title, threadKey, buffer, source }) {
  const id = crypto.randomUUID();
  const dir = artifactsUserDir(userId);
  fs.writeFileSync(path.join(dir, `${id}.${kind}`), buffer);
  const entry = { id, kind, title, thread_key: threadKey || null, source: source || null,
    created_at: new Date().toISOString(), size: buffer.length };
  const list = readArtifactIndex(userId);
  list.unshift(entry);
  writeArtifactIndex(userId, list);
  return entry;
}
const ARTIFACT_MIME = {
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  pdf: 'application/pdf',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
};

app.get('/api/artifacts', (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  res.json({ artifacts: readArtifactIndex(session.user.id) });
});

app.get('/api/artifacts/:id/download', (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const entry = readArtifactIndex(session.user.id).find((a) => a.id === req.params.id);
  // 403 uniforme: el id de otra persona no existe en SU índice — nunca se revela si existe.
  if (!entry) return res.status(403).json({ error: 'No tenés acceso a este archivo.' });
  const file = path.join(artifactsUserDir(session.user.id), `${entry.id}.${entry.kind}`);
  if (!fs.existsSync(file)) return res.status(404).json({ error: 'El archivo ya no está disponible.' });
  const safeTitle = (entry.title || 'archivo').replace(/[^\w\- áéíóúñÁÉÍÓÚÑ]/g, '').slice(0, 80) || 'archivo';
  res.setHeader('Content-Type', ARTIFACT_MIME[entry.kind] || 'application/octet-stream');
  res.setHeader('Content-Disposition', `attachment; filename*=UTF-8''${encodeURIComponent(`${safeTitle}.${entry.kind}`)}`);
  fs.createReadStream(file).pipe(res);
});

app.delete('/api/artifacts/:id', (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const list = readArtifactIndex(session.user.id);
  const entry = list.find((a) => a.id === req.params.id);
  if (!entry) return res.status(403).json({ error: 'No tenés acceso a este archivo.' });
  try { fs.unlinkSync(path.join(artifactsUserDir(session.user.id), `${entry.id}.${entry.kind}`)); } catch (_) { /* ya no está */ }
  writeArtifactIndex(session.user.id, list.filter((a) => a.id !== entry.id));
  res.json({ status: 'ok' });
});

// =========================================================================
// PRESENTACIONES — motor Presenton (spec 050 US3, contrato 03 §3.3). El Hub manda el texto,
// Presenton pide el contenido de las diapositivas a Guardian con su llave `svc.presenton`,
// exporta el archivo y el Hub lo copia a los artefactos de la persona. Copy neutro (FR-016).
// =========================================================================
const MENSAJE_PRESENTACIONES_NO_DISPONIBLE =
  'El servicio de presentaciones no está disponible. Intentá de nuevo en unos minutos.';

function presentacionesDisponible(res) {
  if (PRESENTON_URL) return true;
  res.status(404).json({ error: 'La generación de presentaciones no está habilitada en esta instalación.', code: 'feature_disabled' });
  return false;
}

async function generarPresentacion(session, { content, title, n_slides, export_as, instructions, thread_key, source, template }) {
  const budget = await fetchOwnBudget(session).catch(() => null);
  if (budget && budget.status === 'exceeded') return { status: 402, error: MENSAJE_PRESUPUESTO_AGOTADO };
  const nSlides = Math.min(20, Math.max(3, parseInt(n_slides, 10) || 8));
  const exportAs = export_as === 'pdf' ? 'pdf' : 'pptx';
  const texto = (title ? `Título de la presentación: ${title}\n\n` : '') + String(content).slice(0, 20000);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PRESENTON_TIMEOUT_MS);
  try {
    const r = await fetch(`${PRESENTON_URL}/api/v1/ppt/presentation/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content: texto, n_slides: nSlides, language: 'Spanish', export_as: exportAs,
        // Plantilla modelo (pedido del dueño 13-sep): las integradas de Presenton o las propias
        // creadas a partir de un PPTX del cliente; ambas aparecen en `GET /api/presentations/templates`.
        template: String(template || 'general').replace(/[^A-Za-z0-9_-]/g, '') || 'general',
        // La pista de tokens es la misma del chat (spec 040): el firewall enmascara el contenido
        // que Presenton manda al modelo y restituye el valor real solo si el token vuelve EXACTO.
        // Visto en vivo (12-sep): "OTC" fue tomado por nombre de persona y volvió como
        // "[PERSON / 0 / 31d5]" en una diapositiva. Con esta instrucción el modelo lo copia tal cual.
        instructions: `${instructions || 'Presentación corporativa en español, clara y concreta. Sin inventar datos que no estén en el contenido.'} ` +
          'Si en el contenido aparece un token entre corchetes con el formato exacto [TIPO_numero_codigo] (por ejemplo [PERSON_0_a03c]), ' +
          'es un dato protegido: copialo EXACTAMENTE igual, con corchetes y guiones bajos, sin espacios ni cambios, en el lugar donde corresponda.',
        include_title_slide: true
      }),
      signal: controller.signal
    });
    if (!r.ok) {
      console.error('presenton generate:', r.status, (await r.text().catch(() => '')).slice(0, 300));
      return { status: 502, error: MENSAJE_PRESENTACIONES_NO_DISPONIBLE };
    }
    const data = await r.json();
    if (!data.path) return { status: 502, error: MENSAJE_PRESENTACIONES_NO_DISPONIBLE };
    const fileUrl = data.path.startsWith('http') ? data.path : `${PRESENTON_URL}${data.path.startsWith('/') ? '' : '/'}${data.path}`;
    const f = await fetch(fileUrl, { signal: controller.signal });
    if (!f.ok) {
      console.error('presenton download:', f.status, fileUrl);
      return { status: 502, error: MENSAJE_PRESENTACIONES_NO_DISPONIBLE };
    }
    const buffer = Buffer.from(await f.arrayBuffer());
    if (buffer.length < 1024) return { status: 422, error: 'La presentación generada vino vacía. Probá de nuevo.' };
    const entry = saveArtifact(session.user.id, {
      kind: exportAs, title: title || 'Presentación', threadKey: thread_key, buffer, source: source || 'presentation'
    });
    return { status: 200, artifact: entry };
  } catch (err) {
    if (err.name === 'AbortError') return { status: 504, error: 'La presentación tardó demasiado. Probá con menos diapositivas o menos texto.' };
    console.error('presenton falló:', err.message);
    return { status: 502, error: MENSAJE_PRESENTACIONES_NO_DISPONIBLE };
  } finally {
    clearTimeout(timer);
  }
}

// Plantillas modelo disponibles: las integradas de Presenton y las propias del cliente (creadas
// a partir de un PPTX corporativo desde la API de Presenton; ver contrato 03 §3.3).
app.get('/api/presentations/templates', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  if (!presentacionesDisponible(res)) return;
  try {
    const r = await fetch(`${PRESENTON_URL}/api/v1/ppt/template/all`);
    if (!r.ok) return res.status(502).json({ error: MENSAJE_PRESENTACIONES_NO_DISPONIBLE });
    const data = await r.json();
    const items = (data.items || data || []).map((t) => ({
      id: t.id, name: t.name || t.id, description: t.description || '', custom: t.is_default === false
    }));
    // Las propias del cliente primero: son las que representan la marca.
    items.sort((a, b) => Number(b.custom) - Number(a.custom) || a.name.localeCompare(b.name));
    res.json({ templates: items });
  } catch (err) {
    console.error('presenton templates:', err.message);
    res.status(502).json({ error: MENSAJE_PRESENTACIONES_NO_DISPONIBLE });
  }
});

// Miniatura de una plantilla (para elegirla viendo cómo es). Solo imágenes de `app_data/templates`.
app.get('/api/presentations/templates/:id/thumbnail', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  if (!presentacionesDisponible(res)) return;
  const id = String(req.params.id).replace(/[^A-Za-z0-9_-]/g, '');
  try {
    const r = await fetch(`${PRESENTON_URL}/api/v1/ppt/template/all`);
    const data = r.ok ? await r.json() : { items: [] };
    const t = (data.items || []).find((x) => x.id === id);
    if (!t || !t.thumbnail) return res.status(404).end();
    const img = await fetch(`${PRESENTON_URL}${t.thumbnail.startsWith('/') ? '' : '/'}${t.thumbnail}`);
    if (!img.ok) return res.status(404).end();
    res.setHeader('Content-Type', img.headers.get('content-type') || 'image/png');
    res.setHeader('Cache-Control', 'private, max-age=300');
    res.end(Buffer.from(await img.arrayBuffer()));
  } catch (err) {
    res.status(502).end();
  }
});

// Proxy de administración hacia la pantalla de Presenton (segundo puerto). La cookie de sesión
// del Hub vale acá porque los navegadores no distinguen puerto en las cookies de `localhost`
// ni de un mismo host: quien entró al Hub como admin, entra acá; nadie más.
function crearProxyAdminPresenton() {
  const http = require('http');
  const target = new URL(PRESENTON_URL);
  const PAGINA_403 = `<!doctype html><meta charset="utf-8"><title>Plantillas</title>
<body style="font-family:sans-serif;max-width:520px;margin:80px auto;line-height:1.5">
<h2>Solo administradores</h2><p>La administración de plantillas de presentaciones es para cuentas de
administrador. Entrá primero al Hub con una cuenta de administrador y volvé a abrir esta página.</p></body>`;
  const server = http.createServer((req, res) => {
    const cookies = parseCookies(req.headers.cookie);
    const session = sessions.get(cookies[SID_COOKIE]) || null;
    if (!session || !HUB_ADMIN_ROLES.includes(session.user.role)) {
      res.writeHead(403, { 'Content-Type': 'text/html; charset=utf-8' });
      return res.end(PAGINA_403);
    }
    const headers = { ...req.headers, host: target.host };
    delete headers.cookie; // la sesión del Hub no viaja a Presenton
    const up = http.request({
      hostname: target.hostname, port: target.port || 80, method: req.method, path: req.url, headers
    }, (upRes) => {
      res.writeHead(upRes.statusCode, upRes.headers);
      upRes.pipe(res);
    });
    up.on('error', (err) => {
      console.error('proxy presenton:', err.message);
      if (!res.headersSent) res.writeHead(502, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('El servicio de presentaciones no está disponible.');
    });
    req.pipe(up);
  });
  return server;
}

app.post('/api/presentations/generate', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  if (!presentacionesDisponible(res)) return;
  const { content, title, n_slides, export_as, instructions, thread_key, template } = req.body || {};
  if (!content || typeof content !== 'string' || !content.trim()) return res.status(400).json({ error: 'Falta el contenido de la presentación.' });
  const out = await generarPresentacion(session, { content, title, n_slides, export_as, instructions, thread_key, template });
  if (out.status !== 200) return res.status(out.status).json({ error: out.error });
  res.json({ artifact: out.artifact });
});

// =========================================================================
// "ENVIAR A" / ENCADENADO (spec 050 US4, FR-014, contrato 02 §handoff). Toma una respuesta
// (del chat o de planillas), opcionalmente le suma la respuesta a una pregunta sobre un
// espacio de planillas (motor tabular), y manda el conjunto al motor destino. Si la consulta
// a planillas falla, se aborta: nunca se genera un archivo parcial sin avisar.
// =========================================================================
function tablaMarkdown(columns, rows, max = 50) {
  if (!Array.isArray(columns) || !columns.length || !Array.isArray(rows) || !rows.length) return '';
  const cell = (v) => (v === null || v === undefined ? '' : String(v)).replace(/\|/g, '/');
  const lineas = [columns.join(' | '), columns.map(() => '---').join(' | ')];
  rows.slice(0, max).forEach((r) => lineas.push(columns.map((c) => cell(r[c])).join(' | ')));
  if (rows.length > max) lineas.push(`(mostrando ${max} de ${rows.length} filas)`);
  return lineas.join('\n');
}

app.post('/api/handoff', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const { target, content, tabular, options } = req.body || {};
  if (!['presentation', 'document'].includes(target)) return res.status(400).json({ error: 'Destino inválido.' });
  if (target === 'document') {
    if (!DOCGEN_URL) return res.status(404).json({ error: 'La generación de documentos no está habilitada en esta instalación.', code: 'feature_disabled' });
    return res.status(501).json({ error: 'La generación de documentos llega en una próxima versión.', code: 'not_implemented' });
  }
  if (!presentacionesDisponible(res)) return;
  let texto = String(content || '').trim();
  let tabularUsado = false;

  if (tabular && tabular.workspace_id) {
    if (!tabularDisponible(res)) return;
    const question = String(tabular.question || '').trim();
    if (!question) return res.status(400).json({ error: 'Falta la pregunta para la planilla.' });
    try {
      if (!(await requireTabularWorkspace(session, tabular.workspace_id, res))) return;
      const r = await tabularFetch(session, `/v1/spaces/${encodeURIComponent(tabular.workspace_id)}/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: question.slice(0, 4000), history: [] })
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        const [, msg] = mensajeErrorTabular(r.status, data);
        return res.status(502).json({ error: `No se pudo consultar la planilla, así que no se generó nada. ${msg}`, code: 'tabular_failed' });
      }
      const tabla = tablaMarkdown(data.columns, data.rows);
      texto = `${texto}\n\nDatos de la planilla — pregunta: ${question}\n${data.answer || ''}${tabla ? `\n\nTabla de resultados:\n${tabla}` : ''}`.trim();
      tabularUsado = true;
    } catch (err) {
      console.error('handoff tabular falló:', err.message);
      return res.status(502).json({ error: 'No se pudo consultar la planilla, así que no se generó nada.', code: 'tabular_failed' });
    }
  }
  if (!texto) return res.status(400).json({ error: 'Falta el contenido.' });

  const opts = options || {};
  const out = await generarPresentacion(session, {
    content: texto, title: opts.title, n_slides: opts.n_slides, export_as: opts.export_as,
    instructions: opts.instructions, thread_key: opts.thread_key, template: opts.template,
    source: tabularUsado ? 'handoff+tabular' : 'handoff'
  });
  if (out.status !== 200) return res.status(out.status).json({ error: out.error });
  res.json({ artifact: out.artifact, tabular_used: tabularUsado });
});

// Spec 044 (Setup, T001): solo escucha cuando se ejecuta directo (`node server.js` /
// `npm start`) — al `require()`-arlo desde un test (node:test + supertest) el módulo
// exporta `app` sin abrir un puerto real. Comportamiento de producción sin cambios.
if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`Eleia Hub escuchando en http://localhost:${PORT}`);
    console.log(`  Guardian:              ${ELEA_BACKEND_URL}`);
    console.log(`  servicio de documentos: ${ANYTHINGLLM_URL}`);
    console.log(`  motor tabular:          ${TABULAR_URL || '(no configurado)'}`);
    console.log(`  presentaciones:         ${PRESENTON_URL || '(no configurado)'}`);
    if (PRESENTON_URL && PRESENTON_ADMIN_PORT) {
      crearProxyAdminPresenton().listen(PRESENTON_ADMIN_PORT, () => {
        console.log(`  plantillas (solo admin): http://localhost:${PRESENTON_ADMIN_PORT}/templates`);
      });
    }
  });
}

module.exports = app;
module.exports.crearProxyAdminPresenton = crearProxyAdminPresenton;
