// Administración de plantillas (spec 050, 13-sep): la pantalla de Presenton se publica por el
// Hub en un segundo puerto SOLO para administradores. Doble HTTP real de Presenton.
const test = require('node:test');
const assert = require('node:assert');
const http = require('node:http');
const request = require('supertest');
const { startMockServer } = require('../mock-servers');

function fakeGuardian() {
  const users = { 'token-ana': { id: 'ana-id', username: 'ana', role: 'client' }, 'token-root': { id: 'root-id', username: 'root', role: 'tenant_admin' } };
  return (req, res, body) => {
    const send = (s, j) => { res.writeHead(s, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(j)); };
    const [pathname] = req.url.split('?');
    if (req.method === 'POST' && pathname === '/users/login') { const tok = body.username === 'root' ? 'token-root' : 'token-ana'; return send(200, { access_token: tok, user: users[tok] }); }
    if (!users[(req.headers.authorization || '').replace('Bearer ', '')]) return send(401, {});
    if (pathname === '/users/me/budget') return send(200, { used_usd: 0, max_usd: null, status: 'ok' });
    if (pathname === '/workspaces') return send(200, { workspaces: [] });
    return send(404, {});
  };
}

function fakePresenton() {
  const calls = [];
  const handler = (req, res, body) => {
    calls.push({ method: req.method, url: req.url, cookie: req.headers.cookie || null, host: req.headers.host });
    if (req.url === '/api/v1/ppt/template/all') { res.writeHead(200, { 'Content-Type': 'application/json' }); return res.end(JSON.stringify({ items: [{ id: 'general', name: 'General', is_default: true, thumbnail: '/app_data/templates/general/static/thumbnail.png' }] })); }
    if (req.url === '/app_data/templates/general/static/thumbnail.png') { res.writeHead(200, { 'Content-Type': 'image/png' }); return res.end(Buffer.from([0x89, 0x50, 0x4e, 0x47])); }
    if (req.url === '/templates') { res.writeHead(200, { 'Content-Type': 'text/html' }); return res.end('<html>PANTALLA DE PLANTILLAS</html>'); }
    if (req.method === 'POST' && req.url === '/api/v1/ppt/template/init') { res.writeHead(200, { 'Content-Type': 'application/json' }); return res.end(JSON.stringify({ ok: true, echo: body })); }
    res.writeHead(404); res.end();
  };
  return { handler, calls };
}

function raw(port, { method = 'GET', path = '/', headers = {}, body = null } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request({ hostname: '127.0.0.1', port, method, path, headers }, (res) => {
      const chunks = []; res.on('data', (c) => chunks.push(c)); res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks).toString() }));
    });
    req.on('error', reject); if (body) req.write(body); req.end();
  });
}

test('plantillas admin: proxy solo para admins, sin cookie del Hub hacia Presenton; miniaturas por el Hub', async (t) => {
  const presenton = fakePresenton();
  const g = await startMockServer(fakeGuardian());
  const p = await startMockServer((q, r, b) => presenton.handler(q, r, b));
  process.env.ELEA_BACKEND_URL = g.url; process.env.ANYTHINGLLM_URL = 'http://127.0.0.1:1'; process.env.ANYTHINGLLM_API_KEY = 'k';
  process.env.PRESENTON_URL = p.url; process.env.PRESENTON_ADMIN_PORT = '0';
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  const proxy = app.crearProxyAdminPresenton();
  await new Promise((r) => proxy.listen(0, '127.0.0.1', r));
  const port = proxy.address().port;
  t.after(async () => { await g.close(); await p.close(); await new Promise((r) => proxy.close(r)); });

  // Sin sesión → 403 con página propia, y Presenton nunca recibió nada.
  let r = await raw(port, { path: '/templates' });
  assert.strictEqual(r.status, 403); assert.match(r.body, /Solo administradores/);
  assert.strictEqual(presenton.calls.length, 0);

  // Cliente común (ana) → 403.
  const sidDe = (resp) => (resp.headers['set-cookie'] || []).map(String).find((c) => c.startsWith('elea_rag_sid=')).split(';')[0];
  const ana = request.agent(app); const la = await ana.post('/api/auth/login').send({ username: 'ana', password: 'x' }).expect(200);
  r = await raw(port, { path: '/templates', headers: { cookie: sidDe(la) } });
  assert.strictEqual(r.status, 403);
  assert.strictEqual(presenton.calls.length, 0);

  // Admin (root) → pasa; la cookie del Hub NO viaja a Presenton; host reescrito.
  const root = request.agent(app); const lr = await root.post('/api/auth/login').send({ username: 'root', password: 'x' }).expect(200);
  const rootCookie = sidDe(lr);
  r = await raw(port, { path: '/templates', headers: { cookie: rootCookie } });
  assert.strictEqual(r.status, 200); assert.match(r.body, /PANTALLA DE PLANTILLAS/);
  assert.strictEqual(presenton.calls[0].cookie, null);
  assert.strictEqual(presenton.calls[0].host, new URL(p.url).host);

  // POST con cuerpo se reenvía tal cual (creación de plantilla desde la pantalla de Presenton).
  r = await raw(port, { method: 'POST', path: '/api/v1/ppt/template/init', headers: { cookie: rootCookie, 'content-type': 'application/json' }, body: JSON.stringify({ name: 'Elea' }) });
  assert.strictEqual(r.status, 200); assert.deepStrictEqual(JSON.parse(r.body).echo, { name: 'Elea' });

  // features anuncia el puerto solo si está configurado; miniatura vía Hub para cualquier sesión.
  process.env.PRESENTON_ADMIN_PORT = '8097';
  const f = await root.get('/api/features'); assert.strictEqual(f.body.presentations_admin_port, null); // el módulo ya leyó '0'
  const th = await ana.get('/api/presentations/templates/general/thumbnail');
  assert.strictEqual(th.status, 200); assert.strictEqual(th.headers['content-type'], 'image/png');
  assert.strictEqual((await ana.get('/api/presentations/templates/../etc/thumbnail')).status, 404);
});
