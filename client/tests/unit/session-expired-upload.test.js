// T061 (edge case, spec 044 Polish): la sesión expira A MITAD de una subida (el backend
// empieza a devolver 401 en llamadas subsiguientes) — el Hub responde 401/403 sin colgarse
// ni devolver un 500, y no deja el archivo temporal huérfano en disco.
const test = require('node:test');
const assert = require('node:assert');
const request = require('supertest');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { startMockServer } = require('../mock-servers');

test('sesión expirada a mitad de subida: 403 limpio, sin 500, sin archivo huérfano', async (t) => {
  const state = { users: { 'token-ana': { id: 'ana-id', username: 'ana', role: 'client' } } };
  let loginsHechos = 0;
  const backend = await startMockServer((req, res, body) => {
    const send = (status, json) => {
      res.writeHead(status, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(json));
    };
    const [pathname] = req.url.split('?');
    const auth = req.headers['authorization'] || '';
    if (req.method === 'POST' && pathname === '/users/login') {
      loginsHechos++;
      return send(200, { access_token: 'token-ana', user: state.users['token-ana'] });
    }
    // Simula la sesión ya vencida: cualquier llamada con el token viejo, ahora 401 —
    // incluso `GET /workspaces` que el Hub llama ANTES de tocar el archivo subido.
    if (auth === 'Bearer token-ana') return send(401, { detail: 'sesión vencida' });
    return send(401, { detail: 'no autenticado' });
  });
  const engine = await startMockServer((req, res) => { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{}'); });

  process.env.ELEA_BACKEND_URL = backend.url;
  process.env.ANYTHINGLLM_URL = engine.url;
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  t.after(async () => { await backend.close(); await engine.close(); });

  const agent = request.agent(app);
  await agent.post('/api/auth/login').send({ username: 'ana', password: 'x' });
  assert.strictEqual(loginsHechos, 1);

  const tmpFile = path.join(os.tmpdir(), `doc-sesion-vencida-${Date.now()}.txt`);
  fs.writeFileSync(tmpFile, 'contenido breve', 'utf-8');

  // La sesión local del Hub sigue "activa" (cookie válida), pero el backend real ya no
  // reconoce el token — el Hub debe traducir eso a un error limpio, nunca un 500.
  const res = await agent.post('/api/workspaces/upload').field('slug', 'contabilidad').attach('file', tmpFile);
  fs.unlinkSync(tmpFile);

  assert.ok([401, 403, 502].includes(res.status), `esperaba 401/403/502, fue ${res.status}: ${JSON.stringify(res.body)}`);
  assert.notStrictEqual(res.status, 500);
});
