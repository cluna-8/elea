// T018 (servidor): un admin ve los espacios sin asignar y puede asignarles un dueño;
// una persona no-admin recibe 403 del propio backend (nunca una lista vacía disfrazada
// de "no hay", que ocultaría el error real). Regresión del bug real encontrado en esta
// sesión: el proxy llamaba `/workspaces?status=unassigned` cuando el backend espera
// `status_filter` (server.js no fallaba con error, simplemente devolvía la lista de
// espacios propios en lugar de los sin asignar — silencioso).
const test = require('node:test');
const assert = require('node:assert');
const request = require('supertest');
const crypto = require('node:crypto');
const { startMockServer } = require('../mock-servers');

function buildFakeBackend() {
  const state = {
    users: {
      'token-admin': { id: 'admin-id', username: 'admin', role: 'tenant_admin' },
      'token-luis': { id: 'luis-id', username: 'luis', role: 'client' }
    },
    unassigned: [
      { id: 'ws-huerfano-1', engine_slug: 'huerfano-1', display_name: 'Espacio Huérfano 1', status: 'unassigned' }
    ]
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
    const [pathname, qs] = req.url.split('?');
    const user = userFromAuth(req);
    if (req.method === 'POST' && pathname === '/users/login') {
      const token = body.username === 'admin' ? 'token-admin' : 'token-luis';
      return send(200, { access_token: token, user: state.users[token] });
    }
    if (!user) return send(401, { detail: 'no autenticado' });
    if (req.method === 'GET' && pathname === '/users/me/budget') {
      return send(200, { used_usd: 0, max_usd: null, status: 'ok' });
    }
    if (req.method === 'GET' && pathname === '/workspaces') {
      const params = new URLSearchParams(qs || '');
      if (params.get('status_filter') === 'unassigned') {
        if (user.role !== 'tenant_admin' && user.role !== 'super_admin') {
          return send(403, { detail: 'solo admins pueden ver espacios sin asignar' });
        }
        return send(200, { workspaces: state.unassigned });
      }
      return send(200, { workspaces: [] });
    }
    const memberMatch = pathname.match(/^\/workspaces\/([^/]+)\/members$/);
    if (memberMatch && req.method === 'POST') {
      const wsId = memberMatch[1];
      const ws = state.unassigned.find((w) => w.id === wsId);
      if (!ws) return send(404, { detail: 'no encontrado' });
      if (user.role !== 'tenant_admin' && user.role !== 'super_admin') {
        return send(403, { detail: 'sin acceso a este espacio' });
      }
      state.unassigned = state.unassigned.filter((w) => w.id !== wsId);
      return send(200, { user_id: crypto.randomUUID(), role: 'owner' });
    }
    return send(404, { detail: 'no encontrado en el doble de backend' });
  };
  return { handler, state };
}

async function setupApp() {
  const fakeBackend = buildFakeBackend();
  const backend = await startMockServer((req, res, body) => fakeBackend.handler(req, res, body));
  const engine = await startMockServer((req, res) => { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{}'); });
  process.env.ELEA_BACKEND_URL = backend.url;
  process.env.ANYTHINGLLM_URL = engine.url;
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  return { app, backend, engine };
}

test('sin asignar: admin ve la lista real (status_filter, no status)', async (t) => {
  const { app, backend, engine } = await setupApp();
  t.after(async () => { await backend.close(); await engine.close(); });
  const adminAgent = request.agent(app);
  await adminAgent.post('/api/auth/login').send({ username: 'admin', password: 'x' });

  const res = await adminAgent.get('/api/workspaces/unassigned');
  assert.strictEqual(res.status, 200, JSON.stringify(res.body));
  assert.strictEqual(res.body.workspaces.length, 1);
  assert.strictEqual(res.body.workspaces[0].display_name, 'Espacio Huérfano 1');
});

test('sin asignar: alguien no-admin recibe 403 del backend, no una lista vacía disfrazada', async (t) => {
  const { app, backend, engine } = await setupApp();
  t.after(async () => { await backend.close(); await engine.close(); });
  const luisAgent = request.agent(app);
  await luisAgent.post('/api/auth/login').send({ username: 'luis', password: 'x' });

  const res = await luisAgent.get('/api/workspaces/unassigned');
  assert.strictEqual(res.status, 403);
});

test('sin asignar: admin asigna un dueño y el espacio deja de aparecer en la lista', async (t) => {
  const { app, backend, engine } = await setupApp();
  t.after(async () => { await backend.close(); await engine.close(); });
  const adminAgent = request.agent(app);
  await adminAgent.post('/api/auth/login').send({ username: 'admin', password: 'x' });

  const assigned = await adminAgent.post('/api/workspaces/unassigned/ws-huerfano-1/members').send({ username: 'luis' });
  assert.strictEqual(assigned.status, 200, JSON.stringify(assigned.body));

  const after = await adminAgent.get('/api/workspaces/unassigned');
  assert.strictEqual(after.body.workspaces.length, 0);
});
