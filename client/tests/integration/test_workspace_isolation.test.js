// Integración (spec 044 US1, T009): acceso cruzado a un espacio ajeno por slug conocido
// responde 403 sin filtrar datos, y luego de que el dueño agrega a la otra persona como
// miembro, el acceso se habilita. Dos sesiones simuladas contra dobles HTTP reales.
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
    const getById = pathname.match(/^\/workspaces\/([^/]+)$/);
    if (req.method === 'GET' && getById) {
      const ws = state.workspaces.find((w) => w.id === getById[1] || w.engine_slug === getById[1]);
      if (!ws) return send(404, { detail: 'no encontrado' });
      const membership = ws.members.find((m) => m.user_id === user.id);
      if (!membership) return send(403, { detail: 'sin acceso' });
      return send(200, { id: ws.id, engine_slug: ws.engine_slug, display_name: ws.display_name, role: membership.role, status: 'active' });
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
    return send(404, { detail: 'no encontrado en el doble de backend' });
  };
  return { handler };
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

test('integración: 403 sin filtrar datos en espacio ajeno, luego alta de miembro habilita el acceso', async (t) => {
  const fakeBackend = buildFakeBackend();
  const backend = await startMockServer((req, res, body) => fakeBackend.handler(req, res, body));
  const engine = await startMockServer((req, res, body) => buildFakeAnythingLLM().handler(req, res, body));
  process.env.ELEA_BACKEND_URL = backend.url;
  process.env.ANYTHINGLLM_URL = engine.url;
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  t.after(async () => { await backend.close(); await engine.close(); });

  const anaAgent = request.agent(app);
  const luisAgent = request.agent(app);
  await anaAgent.post('/api/auth/login').send({ username: 'ana', password: 'x' });
  await luisAgent.post('/api/auth/login').send({ username: 'luis', password: 'x' });

  const created = await anaAgent.post('/api/workspaces/create').send({ name: 'Contabilidad' });
  const slug = created.body.workspace.slug;

  const denied = await luisAgent.get(`/api/workspaces/${slug}`);
  assert.strictEqual(denied.status, 403);
  assert.strictEqual(denied.body.display_name, undefined);

  const added = await anaAgent.post(`/api/workspaces/${slug}/members`).send({ username: 'luis' });
  assert.strictEqual(added.status, 200, JSON.stringify(added.body));

  const allowed = await luisAgent.get(`/api/workspaces/${slug}`);
  assert.strictEqual(allowed.status, 200);
});
