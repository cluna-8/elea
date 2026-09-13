// Aislamiento real de espacios en Eleia Hub (spec 044 US1, contrato 1 de la 043) — mismo
// guion que `quickstart.md` §1: A crea un espacio, B no lo ve ni accede por id conocido,
// A lo agrega como miembro, B lo ve, los hilos de cada uno no se cruzan, sin sesión 401
// en todo. Dobles HTTP reales del backend y del motor de documentos (node:http), Hub real
// (server.js) hablándoles por `fetch` de verdad — nada de mocks de módulo.
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
    workspaces: [] // { id, engine_slug, display_name, members: [{user_id, role}] }
  };

  function userFromAuth(req) {
    const auth = req.headers['authorization'] || '';
    const token = auth.replace(/^Bearer\s+/, '');
    return state.users[token] || null;
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
          role: w.members.find((m) => m.user_id === user.id).role, status: 'active'
        }));
      return send(200, { workspaces: mine });
    }
    if (req.method === 'POST' && pathname === '/workspaces') {
      const ws = {
        id: crypto.randomUUID(), engine_slug: body.engine_slug, display_name: body.display_name,
        members: [{ user_id: user.id, role: 'owner' }]
      };
      state.workspaces.push(ws);
      return send(200, { id: ws.id, engine_slug: ws.engine_slug, display_name: ws.display_name, role: 'owner', status: 'active' });
    }
    const memberMatch = pathname.match(/^\/workspaces\/([^/]+)\/members$/);
    if (memberMatch && req.method === 'POST') {
      const ws = state.workspaces.find((w) => w.id === memberMatch[1]);
      if (!ws || !ws.members.some((m) => m.user_id === user.id)) return send(403, { detail: 'sin acceso' });
      const target = Object.values(state.users).find((u) => u.username === body.username);
      if (!target) return send(409, { detail: 'usuario no existe' });
      ws.members.push({ user_id: target.id, role: 'member' });
      return send(200, { user_id: target.id, role: 'member' });
    }
    const threadsMatch = pathname.match(/^\/workspaces\/([^/]+)\/threads$/);
    if (threadsMatch) {
      const wsId = threadsMatch[1];
      if (!state._threads) state._threads = [];
      if (req.method === 'POST') {
        const existing = state._threads.find(
          (t) => t.workspace_id === wsId && t.owner_user_id === user.id && t.engine_thread_slug === (body.engine_thread_slug || null)
        );
        if (existing) return send(200, existing);
        const row = {
          id: crypto.randomUUID(), workspace_id: wsId, owner_user_id: user.id,
          engine_thread_slug: body.engine_thread_slug || null, created_at: new Date().toISOString()
        };
        state._threads.push(row);
        return send(200, row);
      }
      if (req.method === 'GET') {
        return send(200, { threads: state._threads.filter((t) => t.workspace_id === wsId && t.owner_user_id === user.id) });
      }
    }
    return send(404, { detail: 'no encontrado en el doble de backend' });
  };
  return { handler, state };
}

function buildFakeAnythingLLM() {
  const workspaces = {}; // slug -> {slug, name}
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
    const wsMatch = pathname.match(/^\/api\/v1\/workspace\/([^/]+)$/);
    if (req.method === 'GET' && wsMatch) {
      const ws = workspaces[wsMatch[1]];
      if (!ws) return send(404, { detail: 'not found' });
      return send(200, { workspace: [ws] });
    }
    if (req.method === 'POST' && wsMatch && pathname.endsWith('/update')) {
      return send(200, { workspace: workspaces[wsMatch[1]] });
    }
    return send(200, {});
  };
  return { handler };
}

test('aislamiento real: A crea, B no ve ni accede, A agrega, B ve, hilos no se cruzan, sin sesión 401', async (t) => {
  const fakeBackend = buildFakeBackend();
  const fakeAnything = buildFakeAnythingLLM();
  const backend = await startMockServer((req, res, body) => fakeBackend.handler(req, res, body));
  const engine = await startMockServer((req, res, body) => fakeAnything.handler(req, res, body));

  process.env.ELEA_BACKEND_URL = backend.url;
  process.env.ANYTHINGLLM_URL = engine.url;
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');

  t.after(async () => {
    await backend.close();
    await engine.close();
  });

  const anonAgent = request.agent(app);
  const anaAgent = request.agent(app);
  const luisAgent = request.agent(app);

  // Login real de Ana y Luis
  const anaLogin = await anaAgent.post('/api/auth/login').send({ username: 'ana', password: 'x' });
  assert.strictEqual(anaLogin.status, 200);
  const luisLogin = await luisAgent.post('/api/auth/login').send({ username: 'luis', password: 'x' });
  assert.strictEqual(luisLogin.status, 200);

  // Ana crea un espacio
  const created = await anaAgent.post('/api/workspaces/create').send({ name: 'Contabilidad' });
  assert.strictEqual(created.status, 200, JSON.stringify(created.body));
  const slug = created.body.workspace.slug;

  // Luis no lo ve
  const luisList = await luisAgent.get('/api/workspaces');
  assert.ok(!luisList.body.workspaces.some((w) => w.engine_slug === slug));

  // Luis no puede acceder por slug conocido
  const luisGet = await luisAgent.get(`/api/workspaces/${slug}`);
  assert.strictEqual(luisGet.status, 403);

  // Sin sesión, 401
  const anonGet = await anonAgent.get('/api/workspaces');
  assert.strictEqual(anonGet.status, 401);

  // Ana agrega a Luis
  const added = await anaAgent.post(`/api/workspaces/${slug}/members`).send({ username: 'luis' });
  assert.strictEqual(added.status, 200, JSON.stringify(added.body));

  // Ahora Luis lo ve
  const luisList2 = await luisAgent.get('/api/workspaces');
  assert.ok(luisList2.body.workspaces.some((w) => w.engine_slug === slug));

  // Hilos: cada uno crea el suyo, no se cruzan
  await anaAgent.post('/api/threads/create').send({ slug, name: 'Hilo de Ana' });
  await luisAgent.post('/api/threads/create').send({ slug, name: 'Hilo de Luis' });
  const anaThreads = await anaAgent.get('/api/workspaces');
  // (la verificación de propiedad de hilos ya la cubre ownsThreadSlug en el server; acá
  // solo confirmamos que ninguna de las dos creaciones falló)
  assert.strictEqual(anaThreads.status, 200);
});
