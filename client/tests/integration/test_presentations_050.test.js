// Presentaciones y artefactos (spec 050 US3, FR-013/FR-015). Dobles HTTP reales de Guardian y
// de Presenton; Hub real por fetch. Artefactos en un directorio temporal (ARTIFACTS_DIR).
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const request = require('supertest');
const { startMockServer } = require('../mock-servers');

const PPTX = Buffer.concat([Buffer.from('PK'), Buffer.alloc(4096, 1)]);

function buildFakeGuardian() {
  const users = { 'token-ana': { id: 'ana-id', username: 'ana', role: 'client' }, 'token-bruno': { id: 'bruno-id', username: 'bruno', role: 'client' } };
  let budget = { used_usd: 1, max_usd: 10, status: 'ok' };
  const handler = (req, res, body) => {
    const send = (s, j) => { res.writeHead(s, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(j)); };
    const [pathname] = req.url.split('?');
    if (req.method === 'POST' && pathname === '/users/login') {
      const tok = body.username === 'bruno' ? 'token-bruno' : 'token-ana';
      return send(200, { access_token: tok, user: users[tok] });
    }
    if (!users[(req.headers.authorization || '').replace('Bearer ', '')]) return send(401, {});
    if (pathname === '/users/me/budget') return send(200, budget);
    if (pathname === '/workspaces') return send(200, { workspaces: [] });
    return send(404, {});
  };
  return { handler, setBudget: (b) => { budget = b; } };
}

function buildFakePresenton() {
  const calls = [];
  let mode = 'ok';
  const handler = (req, res, body) => {
    calls.push({ method: req.method, url: req.url, body });
    if (req.method === 'POST' && req.url === '/api/v1/ppt/presentation/generate') {
      if (mode === 'down') { res.writeHead(500); return res.end('boom'); }
      if (mode === 'slow') return; // nunca responde → timeout del Hub
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ presentation_id: 'p-1', path: '/app_data/exports/p-1.pptx', edit_path: '/presentation?id=p-1' }));
    }
    if (req.method === 'GET' && req.url === '/api/v1/ppt/template/all') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ items: [{ id: 'general', name: 'General', is_default: true }, { id: 'a1b2', name: 'Elea corporativa', is_default: false, description: 'Marca Elea' }] }));
    }
    if (req.method === 'GET' && req.url === '/app_data/exports/p-1.pptx') {
      res.writeHead(200, { 'Content-Type': 'application/octet-stream' });
      return res.end(mode === 'empty' ? Buffer.alloc(10) : PPTX);
    }
    res.writeHead(404); res.end();
  };
  return { handler, calls, setMode: (m) => { mode = m; } };
}

async function boot(t, { withPresenton = true } = {}) {
  const guardian = buildFakeGuardian();
  const presenton = buildFakePresenton();
  const g = await startMockServer((req, res, body) => guardian.handler(req, res, body));
  const p = await startMockServer((req, res, body) => presenton.handler(req, res, body));
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hub-artifacts-'));
  process.env.ELEA_BACKEND_URL = g.url;
  process.env.ANYTHINGLLM_URL = 'http://127.0.0.1:1';
  process.env.ANYTHINGLLM_API_KEY = 'k';
  process.env.ARTIFACTS_DIR = dir;
  process.env.PRESENTON_TIMEOUT_MS = '800';
  if (withPresenton) process.env.PRESENTON_URL = p.url; else delete process.env.PRESENTON_URL;
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  t.after(async () => { await g.close(); await p.close(); fs.rmSync(dir, { recursive: true, force: true }); });
  const ana = request.agent(app);
  await ana.post('/api/auth/login').send({ username: 'ana', password: 'x' }).expect(200);
  return { ana, app, guardian, presenton, dir };
}

test('presentación: generar desde una respuesta, guardar como artefacto, listar, descargar solo la dueña, borrar', async (t) => {
  const { ana, app, presenton, dir } = await boot(t);
  assert.strictEqual((await ana.get('/api/features')).body.presentations, true);

  const r = await ana.post('/api/presentations/generate').send({ content: 'Ventas 2025 crecieron 30%.', title: 'Ventas 2025', n_slides: 5, export_as: 'pptx', thread_key: 'ws1/t1' });
  assert.strictEqual(r.status, 200, JSON.stringify(r.body));
  const art = r.body.artifact;
  assert.strictEqual(art.kind, 'pptx');
  assert.strictEqual(art.title, 'Ventas 2025');
  assert.strictEqual(art.size, PPTX.length);
  const gen = presenton.calls.find((c) => c.method === 'POST');
  assert.strictEqual(gen.body.n_slides, 5);
  assert.strictEqual(gen.body.export_as, 'pptx');
  assert.ok(gen.body.content.includes('Ventas 2025 crecieron 30%'));
  assert.ok(fs.existsSync(path.join(dir, 'ana-id', `${art.id}.pptx`)));

  const list = await ana.get('/api/artifacts');
  assert.deepStrictEqual(list.body.artifacts.map((a) => a.id), [art.id]);

  const dl = await ana.get(`/api/artifacts/${art.id}/download`).buffer(true).parse((res, cb) => { const chunks = []; res.on('data', (c) => chunks.push(c)); res.on('end', () => cb(null, Buffer.concat(chunks))); });
  assert.strictEqual(dl.status, 200);
  assert.ok(dl.headers['content-type'].includes('presentationml'));
  assert.ok(dl.headers['content-disposition'].includes('Ventas%202025.pptx'));
  assert.strictEqual(dl.body.length, PPTX.length);

  // Bruno no ve ni descarga lo de Ana (FR-015).
  const bruno = request.agent(app);
  await bruno.post('/api/auth/login').send({ username: 'bruno', password: 'x' }).expect(200);
  assert.deepStrictEqual((await bruno.get('/api/artifacts')).body.artifacts, []);
  assert.strictEqual((await bruno.get(`/api/artifacts/${art.id}/download`)).status, 403);
  assert.strictEqual((await bruno.delete(`/api/artifacts/${art.id}`)).status, 403);

  assert.strictEqual((await ana.delete(`/api/artifacts/${art.id}`)).status, 200);
  assert.deepStrictEqual((await ana.get('/api/artifacts')).body.artifacts, []);
  assert.ok(!fs.existsSync(path.join(dir, 'ana-id', `${art.id}.pptx`)));
});

test('presentación: plantillas modelo — las propias del cliente primero, y la elegida viaja a Presenton', async (t) => {
  const { ana, presenton } = await boot(t);
  const tpl = await ana.get('/api/presentations/templates');
  assert.strictEqual(tpl.status, 200);
  assert.deepStrictEqual(tpl.body.templates.map((x) => [x.id, x.custom]), [['a1b2', true], ['general', false]]);
  const r = await ana.post('/api/presentations/generate').send({ content: 'x', template: 'a1b2' });
  assert.strictEqual(r.status, 200);
  assert.strictEqual(presenton.calls.filter((c) => c.method === 'POST').pop().body.template, 'a1b2');
  const r2 = await ana.post('/api/presentations/generate').send({ content: 'x', template: '../x; DROP' });
  assert.strictEqual(presenton.calls.filter((c) => c.method === 'POST').pop().body.template, 'xDROP');
  assert.strictEqual(r2.status, 200);
});

test('presentación: límites de n_slides y validaciones', async (t) => {
  const { ana, presenton } = await boot(t);
  assert.strictEqual((await ana.post('/api/presentations/generate').send({ content: '' })).status, 400);
  const r = await ana.post('/api/presentations/generate').send({ content: 'x', n_slides: 99, export_as: 'exe' });
  assert.strictEqual(r.status, 200);
  const gen = presenton.calls.filter((c) => c.method === 'POST').pop();
  assert.strictEqual(gen.body.n_slides, 20);
  assert.strictEqual(gen.body.export_as, 'pptx');
});

test('presentación: motor caído, archivo vacío, timeout y presupuesto → copy neutro con código', async (t) => {
  const { ana, presenton, guardian } = await boot(t);
  presenton.setMode('down');
  let r = await ana.post('/api/presentations/generate').send({ content: 'x' });
  assert.strictEqual(r.status, 502); assert.match(r.body.error, /no está disponible/);
  presenton.setMode('empty');
  r = await ana.post('/api/presentations/generate').send({ content: 'x' });
  assert.strictEqual(r.status, 422); assert.match(r.body.error, /vacía/);
  presenton.setMode('slow');
  r = await ana.post('/api/presentations/generate').send({ content: 'x' });
  assert.strictEqual(r.status, 504); assert.match(r.body.error, /tardó demasiado/);
  presenton.setMode('ok');
  guardian.setBudget({ used_usd: 10, max_usd: 10, status: 'exceeded' });
  r = await ana.post('/api/presentations/generate').send({ content: 'x' });
  assert.strictEqual(r.status, 402);
  for (const c of [r.body.error]) assert.doesNotMatch(c.toLowerCase(), /presenton/);
});

test('presentación: sin motor configurado, features lo dice y la ruta devuelve 404; artefactos siguen', async (t) => {
  const { ana } = await boot(t, { withPresenton: false });
  assert.strictEqual((await ana.get('/api/features')).body.presentations, false);
  const r = await ana.post('/api/presentations/generate').send({ content: 'x' });
  assert.strictEqual(r.status, 404); assert.strictEqual(r.body.code, 'feature_disabled');
  assert.strictEqual((await ana.get('/api/artifacts')).status, 200);
});
