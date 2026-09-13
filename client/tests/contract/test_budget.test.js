// Contrato 2 (spec 044 US2, T020): el presupuesto se lee con la sesión propia de la
// persona (`session.token`), nunca con una sesión de admin de fondo (el bug real que
// diagnostico.md §5 de la 043 documenta: `ELEA_SERVICE_USERNAME=admin` leyendo TODOS
// los presupuestos y filtrando en memoria). Doble HTTP real del backend que verifica
// EXACTAMENTE con qué token llega la llamada.
const test = require('node:test');
const assert = require('node:assert');
const request = require('supertest');
const { startMockServer } = require('../mock-servers');

function buildFakeBackend() {
  const state = {
    users: { 'token-ana': { id: 'ana-id', username: 'ana', role: 'client' } },
    // Si alguna vez el Hub usara una sesión de servicio/admin en vez de la propia, este
    // otro token existiría y respondería con datos ajenos — la prueba falla si el
    // request llega con cualquier cosa distinta de 'token-ana'.
  };
  const handler = (req, res, body) => {
    const send = (status, json) => {
      res.writeHead(status, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(json));
    };
    const [pathname] = req.url.split('?');
    const auth = req.headers['authorization'] || '';
    if (req.method === 'POST' && pathname === '/users/login') {
      return send(200, { access_token: 'token-ana', user: state.users['token-ana'] });
    }
    if (req.method === 'GET' && pathname === '/users/me/budget') {
      if (auth !== 'Bearer token-ana') return send(401, { detail: 'no autenticado' });
      return send(200, { used_usd: 0.5, max_usd: 1.0, status: 'ok' });
    }
    if (req.method === 'GET' && pathname === '/workspaces') return send(200, { workspaces: [] });
    return send(404, { detail: 'no encontrado en el doble de backend' });
  };
  return { handler };
}

test('contrato: el presupuesto se lee con la sesión propia, no con una sesión de admin', async (t) => {
  const backend = await startMockServer((req, res, body) => buildFakeBackend().handler(req, res, body));
  const engine = await startMockServer((req, res) => { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{}'); });
  process.env.ELEA_BACKEND_URL = backend.url;
  process.env.ANYTHINGLLM_URL = engine.url;
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  t.after(async () => { await backend.close(); await engine.close(); });

  const anaAgent = request.agent(app);
  await anaAgent.post('/api/auth/login').send({ username: 'ana', password: 'x' });

  const res = await anaAgent.get('/api/user/budget');
  assert.strictEqual(res.status, 200, JSON.stringify(res.body));
  assert.strictEqual(res.body.usedUsd, 0.5);
  assert.strictEqual(res.body.maxUsd, 1.0);
});

test('contrato: sin sesión, el presupuesto no se devuelve', async (t) => {
  const backend = await startMockServer((req, res, body) => buildFakeBackend().handler(req, res, body));
  const engine = await startMockServer((req, res) => { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{}'); });
  process.env.ELEA_BACKEND_URL = backend.url;
  process.env.ANYTHINGLLM_URL = engine.url;
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  t.after(async () => { await backend.close(); await engine.close(); });

  const res = await request(app).get('/api/user/budget');
  assert.strictEqual(res.status, 401);
});
