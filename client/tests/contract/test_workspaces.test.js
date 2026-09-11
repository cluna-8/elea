// Contrato 1 (spec 044 US1, T008): GET /api/workspaces exige sesión (401 sin token) y
// solo devuelve los espacios propios del usuario autenticado (nunca los de otra persona).
// Doble HTTP real del backend Guardian (node:http) — Eleia Hub le habla por fetch de
// verdad, así que el doble más honesto es otro servidor HTTP, no un mock de módulo.
const test = require('node:test');
const assert = require('node:assert');
const request = require('supertest');
const crypto = require('node:crypto');
const { startMockServer } = require('../mock-servers');

function buildFakeBackend() {
  const state = {
    users: {
      'token-ana': { id: 'ana-id', username: 'ana', role: 'client' },
      'token-luis': { id: 'luis-id', username: 'luis', role: 'client' }
    },
    workspaces: []
  };
  function userFromAuth(req) {
    const auth = req.headers['authorization'] || '';
    return state.users[auth.replace(/^Bearer\s+/, '')] || null;
  }
  const handler = (req, res, body) => {
    const send = (status, json) => {
      res.writeHead(status, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(json));
    };
    const [pathname] = req.url.split('?');
    const user = userFromAuth(req);
    if (req.method === 'POST' && pathname === '/users/login') {
      const token = body.username === 'ana' ? 'token-ana' : 'token-luis';
      return send(200, { access_token: token, user: state.users[token] });
    }
    if (!user) return send(401, { detail: 'no autenticado' });
    if (req.method === 'GET' && pathname === '/users/me/budget') {
      return send(200, { used_usd: 0, max_usd: null, status: 'ok' });
    }
    if (req.method === 'GET' && pathname === '/workspaces') {
      const mine = state.workspaces
        .filter((w) => w.members.some((m) => m.user_id === user.id))
        .map((w) => ({
          id: w.id, engine_slug: w.engine_slug, display_name: w.display_name,
          role: w.members.find((m) => m.user_id === user.id).role, status: 'active',
          kind: w.kind || 'rag'
        }));
      return send(200, { workspaces: mine });
    }
    if (req.method === 'POST' && pathname === '/workspaces') {
      const ws = {
        id: crypto.randomUUID(), engine_slug: body.engine_slug, display_name: body.display_name,
        kind: body.kind || 'rag',
        members: [{ user_id: user.id, role: 'owner' }]
      };
      state.workspaces.push(ws);
      return send(200, { id: ws.id, engine_slug: ws.engine_slug, display_name: ws.display_name, role: 'owner', status: 'active', kind: ws.kind });
    }
    return send(404, { detail: 'no encontrado en el doble de backend' });
  };
  return { handler, state };
}

function buildFakeAnythingLLM() {
  const workspaces = {};
  const handler = (req, res, body) => {
    const send = (status, json) => {
      res.writeHead(status, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(json));
    };
    const [pathname] = req.url.split('?');
    if (req.method === 'POST' && pathname === '/api/v1/workspace/new') {
      const slug = (body.name || 'ws').toLowerCase().replace(/\s+/g, '-') + '-' + Math.random().toString(36).slice(2, 6);
      workspaces[slug] = { slug, name: body.name };
      return send(200, { workspace: { slug, name: body.name } });
    }
    return send(200, {});
  };
  return { handler };
}

test('contrato: GET /api/workspaces sin sesión responde 401', async (t) => {
  const backend = await startMockServer((req, res, body) => buildFakeBackend().handler(req, res, body));
  const engine = await startMockServer((req, res, body) => buildFakeAnythingLLM().handler(req, res, body));
  process.env.ELEA_BACKEND_URL = backend.url;
  process.env.ANYTHINGLLM_URL = engine.url;
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  process.env.MASKING_VIRTUAL_KEY = 'test-mask-key';
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  t.after(async () => { await backend.close(); await engine.close(); });

  const res = await request(app).get('/api/workspaces');
  assert.strictEqual(res.status, 401);
});

test('contrato: GET /api/workspaces solo devuelve los espacios propios', async (t) => {
  const fakeBackend = buildFakeBackend();
  const backend = await startMockServer((req, res, body) => fakeBackend.handler(req, res, body));
  const engine = await startMockServer((req, res, body) => buildFakeAnythingLLM().handler(req, res, body));
  process.env.ELEA_BACKEND_URL = backend.url;
  process.env.ANYTHINGLLM_URL = engine.url;
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  process.env.MASKING_VIRTUAL_KEY = 'test-mask-key';
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  t.after(async () => { await backend.close(); await engine.close(); });

  const anaAgent = request.agent(app);
  const luisAgent = request.agent(app);
  await anaAgent.post('/api/auth/login').send({ username: 'ana', password: 'x' });
  await luisAgent.post('/api/auth/login').send({ username: 'luis', password: 'x' });

  const created = await anaAgent.post('/api/workspaces/create').send({ name: 'Contabilidad' });
  assert.strictEqual(created.status, 200, JSON.stringify(created.body));
  const slug = created.body.workspace.slug;

  const anaList = await anaAgent.get('/api/workspaces');
  assert.ok(anaList.body.workspaces.some((w) => w.engine_slug === slug));

  const luisList = await luisAgent.get('/api/workspaces');
  assert.ok(!luisList.body.workspaces.some((w) => w.engine_slug === slug));
});

// Bug real encontrado en vivo (11-sep, spec 046): esta ruta alimenta el sidebar del modo
// Chat normal — sin filtrar por `kind`, los espacios de "Análisis exacto" (kind=
// exact_analysis, con su propia sección en su propio modo) también aparecían acá,
// mezclando los dos modos contra FR-001 (deben quedar SIEMPRE separados).
test('contrato: GET /api/workspaces nunca incluye espacios kind=exact_analysis (no se mezclan los dos modos)', async (t) => {
  const fakeBackend = buildFakeBackend();
  const backend = await startMockServer((req, res, body) => fakeBackend.handler(req, res, body));
  const engine = await startMockServer((req, res, body) => buildFakeAnythingLLM().handler(req, res, body));
  process.env.ELEA_BACKEND_URL = backend.url;
  process.env.ANYTHINGLLM_URL = engine.url;
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  process.env.MASKING_VIRTUAL_KEY = 'test-mask-key';
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  t.after(async () => { await backend.close(); await engine.close(); });

  const anaAgent = request.agent(app);
  await anaAgent.post('/api/auth/login').send({ username: 'ana', password: 'x' });

  // Un espacio de chat normal (kind=rag) y uno de análisis exacto, ambos de ana.
  const chatWs = await anaAgent.post('/api/workspaces/create').send({ name: 'Contabilidad' });
  assert.strictEqual(chatWs.status, 200, JSON.stringify(chatWs.body));
  fakeBackend.state.workspaces.push({
    id: crypto.randomUUID(), engine_slug: 'ventas-q3', display_name: 'Ventas Q3', kind: 'exact_analysis',
    members: [{ user_id: 'ana-id', role: 'owner' }],
  });

  const anaList = await anaAgent.get('/api/workspaces');
  assert.strictEqual(anaList.status, 200);
  assert.ok(anaList.body.workspaces.some((w) => w.display_name === 'Contabilidad'),
    'el espacio de chat normal sí debe aparecer');
  assert.ok(!anaList.body.workspaces.some((w) => w.display_name === 'Ventas Q3'),
    'el espacio de análisis exacto NUNCA debe aparecer en el listado del chat normal');
});
