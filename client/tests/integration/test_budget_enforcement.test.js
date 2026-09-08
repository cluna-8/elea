// T021 (US2, FR-006): con presupuesto agotado (`status: "exceeded"`), el Hub bloquea
// ANTES de mandar el pedido a AnythingLLM/el motor — se verifica que el doble del motor
// NUNCA recibe la llamada de chat, y que el mensaje es el mismo texto neutro que un 402
// real del backend (para que la persona nunca note la diferencia entre bloqueo local y
// del servidor, FR-006).
const test = require('node:test');
const assert = require('node:assert');
const request = require('supertest');
const { startMockServer } = require('../mock-servers');

function buildFakeBackend(budgetStatus) {
  const state = { users: { 'token-ana': { id: 'ana-id', username: 'ana', role: 'client' } } };
  const handler = (req, res, body) => {
    const send = (status, json) => {
      res.writeHead(status, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(json));
    };
    const [pathname] = req.url.split('?');
    if (req.method === 'POST' && pathname === '/users/login') {
      return send(200, { access_token: 'token-ana', user: state.users['token-ana'] });
    }
    if (req.method === 'GET' && pathname === '/users/me/budget') {
      return send(200, { used_usd: 1.0, max_usd: 1.0, status: budgetStatus });
    }
    if (req.method === 'POST' && pathname === '/chat/completions') {
      return send(200, { response: 'no debería llegar acá si el presupuesto está agotado' });
    }
    return send(404, { detail: 'no encontrado en el doble de backend' });
  };
  return { handler };
}

test('presupuesto agotado: el Hub bloquea antes de llamar al motor, mismo mensaje que un 402 real', async (t) => {
  let motorLlamado = false;
  const fakeBackend = buildFakeBackend('exceeded');
  const backend = await startMockServer((req, res, body) => fakeBackend.handler(req, res, body));
  const engine = await startMockServer((req, res) => {
    motorLlamado = true;
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end('{}');
  });
  process.env.ELEA_BACKEND_URL = backend.url;
  process.env.ANYTHINGLLM_URL = engine.url;
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  process.env.MASKING_VIRTUAL_KEY = 'test-mask-key';
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  t.after(async () => { await backend.close(); await engine.close(); });

  const anaAgent = request.agent(app);
  await anaAgent.post('/api/auth/login').send({ username: 'ana', password: 'x' });

  const res = await anaAgent.post('/api/chat').send({ message: '¿cuánto es 2+2?' });
  assert.strictEqual(res.status, 402);
  assert.strictEqual(res.body.error, 'Alcanzaste tu presupuesto. Contactá a tu administrador.');
  assert.strictEqual(motorLlamado, false, 'el motor NUNCA debería recibir la llamada si el bloqueo es local');
});

test('presupuesto disponible: la pregunta sí llega al motor', async (t) => {
  const fakeBackend = buildFakeBackend('ok');
  const backend = await startMockServer((req, res, body) => fakeBackend.handler(req, res, body));
  const engine = await startMockServer((req, res) => { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{}'); });
  process.env.ELEA_BACKEND_URL = backend.url;
  process.env.ANYTHINGLLM_URL = engine.url;
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  process.env.MASKING_VIRTUAL_KEY = 'test-mask-key';
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  t.after(async () => { await backend.close(); await engine.close(); });

  const anaAgent = request.agent(app);
  await anaAgent.post('/api/auth/login').send({ username: 'ana', password: 'x' });

  const res = await anaAgent.post('/api/chat').send({ message: '¿cuánto es 2+2?' });
  assert.strictEqual(res.status, 200, JSON.stringify(res.body));
});
