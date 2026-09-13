// Encadenado "Excel + investigación → presentación" (spec 050 US4, FR-014). Dobles HTTP reales
// de Guardian, del motor tabular y de Presenton; Hub real por fetch.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const request = require('supertest');
const { startMockServer } = require('../mock-servers');

const TOKEN = 'tabular-internal-test-token';
const PPTX = Buffer.concat([Buffer.from('PK'), Buffer.alloc(4096, 1)]);

function fakeGuardian() {
  const users = { 'token-ana': { id: 'ana-id', username: 'ana', role: 'client' } };
  return (req, res, body) => {
    const send = (s, j) => { res.writeHead(s, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(j)); };
    const [pathname] = req.url.split('?');
    if (req.method === 'POST' && pathname === '/users/login') return send(200, { access_token: 'token-ana', user: users['token-ana'] });
    if (!users[(req.headers.authorization || '').replace('Bearer ', '')]) return send(401, {});
    if (pathname === '/users/me/budget') return send(200, { used_usd: 1, max_usd: 10, status: 'ok' });
    if (pathname === '/workspaces/ws-ea-1') return send(200, { id: 'ws-ea-1', engine_slug: 'x', display_name: 'Ventas', role: 'owner', status: 'active', kind: 'exact_analysis' });
    if (pathname.startsWith('/workspaces/')) return send(403, { detail: 'sin acceso' });
    return send(404, {});
  };
}

function fakeTabular() {
  const calls = []; let mode = 'ok';
  const handler = (req, res, body) => {
    calls.push({ method: req.method, url: req.url, body });
    const send = (s, j) => { res.writeHead(s, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(j)); };
    if (req.headers.authorization !== `Bearer ${TOKEN}`) return send(401, { detail: { code: 'unauthorized' } });
    if (req.method === 'POST' && req.url === '/v1/spaces') return send(409, { detail: { code: 'space_exists' } });
    if (req.method === 'POST' && req.url === '/v1/spaces/ws-ea-1/query') {
      if (mode === 'fail') return send(422, { detail: { code: 'unsafe_sql' } });
      return send(200, { sql: 'SELECT zona, SUM(monto) AS total FROM t1 GROUP BY zona LIMIT 500', columns: ['zona', 'total'], rows: [{ zona: 'Norte', total: 425 }, { zona: 'Sur', total: 50 }], answer: 'Norte 425, Sur 50.', model_used: 'm' });
    }
    return send(404, { detail: { code: 'space_not_found' } });
  };
  return { handler, calls, setMode: (m) => { mode = m; } };
}

function fakePresenton() {
  const calls = [];
  const handler = (req, res, body) => {
    calls.push({ method: req.method, url: req.url, body });
    if (req.method === 'POST' && req.url === '/api/v1/ppt/presentation/generate') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ presentation_id: 'p', path: '/app_data/exports/p.pptx', edit_path: '/p' }));
    }
    if (req.url === '/app_data/exports/p.pptx') { res.writeHead(200); return res.end(PPTX); }
    res.writeHead(404); res.end();
  };
  return { handler, calls };
}

async function boot(t, { withTabular = true, withPresenton = true } = {}) {
  const tabular = fakeTabular(); const presenton = fakePresenton();
  const g = await startMockServer(fakeGuardian());
  const tb = await startMockServer((q, r, b) => tabular.handler(q, r, b));
  const p = await startMockServer((q, r, b) => presenton.handler(q, r, b));
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hub-handoff-'));
  process.env.ELEA_BACKEND_URL = g.url; process.env.ANYTHINGLLM_URL = 'http://127.0.0.1:1'; process.env.ANYTHINGLLM_API_KEY = 'k';
  process.env.ARTIFACTS_DIR = dir; process.env.PRESENTON_TIMEOUT_MS = '2000';
  if (withTabular) { process.env.TABULAR_URL = tb.url; process.env.TABULAR_INTERNAL_TOKEN = TOKEN; } else { delete process.env.TABULAR_URL; delete process.env.TABULAR_INTERNAL_TOKEN; }
  if (withPresenton) process.env.PRESENTON_URL = p.url; else delete process.env.PRESENTON_URL;
  delete process.env.DOCGEN_URL;
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  t.after(async () => { await g.close(); await tb.close(); await p.close(); fs.rmSync(dir, { recursive: true, force: true }); });
  const ana = request.agent(app);
  await ana.post('/api/auth/login').send({ username: 'ana', password: 'x' }).expect(200);
  return { ana, tabular, presenton };
}

test('handoff: respuesta del chat + pregunta a la planilla → una presentación con ambas cosas', async (t) => {
  const { ana, tabular, presenton } = await boot(t);
  const r = await ana.post('/api/handoff').send({
    target: 'presentation', content: 'Investigación: el mercado creció 12%.',
    tabular: { workspace_id: 'ws-ea-1', question: 'ventas por zona' },
    options: { title: 'Informe', n_slides: 6, export_as: 'pptx' }
  });
  assert.strictEqual(r.status, 200, JSON.stringify(r.body));
  assert.strictEqual(r.body.tabular_used, true);
  assert.strictEqual(r.body.artifact.title, 'Informe');
  assert.strictEqual(r.body.artifact.source, 'handoff+tabular');
  const q = tabular.calls.find((c) => c.url.endsWith('/query'));
  assert.strictEqual(q.body.question, 'ventas por zona');
  const gen = presenton.calls.find((c) => c.method === 'POST');
  assert.ok(gen.body.content.includes('el mercado creció 12%'));
  assert.ok(gen.body.content.includes('Norte 425, Sur 50.'));
  assert.ok(gen.body.content.includes('zona | total') && gen.body.content.includes('Norte | 425'));
  assert.strictEqual(gen.body.n_slides, 6);
});

test('handoff: sin planilla es igual a generar directo', async (t) => {
  const { ana, tabular } = await boot(t);
  const r = await ana.post('/api/handoff').send({ target: 'presentation', content: 'Solo texto.', options: { title: 'T' } });
  assert.strictEqual(r.status, 200); assert.strictEqual(r.body.tabular_used, false);
  assert.strictEqual(tabular.calls.length, 0);
});

test('handoff: si la consulta a la planilla falla, no se genera nada y se avisa', async (t) => {
  const { ana, tabular, presenton } = await boot(t);
  tabular.setMode('fail');
  const r = await ana.post('/api/handoff').send({ target: 'presentation', content: 'x', tabular: { workspace_id: 'ws-ea-1', question: 'q' } });
  assert.strictEqual(r.status, 502); assert.strictEqual(r.body.code, 'tabular_failed');
  assert.match(r.body.error, /no se generó nada/);
  assert.strictEqual(presenton.calls.length, 0);
});

test('handoff: espacio ajeno → 403 sin tocar motores; pregunta vacía → 400', async (t) => {
  const { ana, tabular, presenton } = await boot(t);
  let r = await ana.post('/api/handoff').send({ target: 'presentation', content: 'x', tabular: { workspace_id: 'ws-ajeno', question: 'q' } });
  assert.strictEqual(r.status, 403);
  r = await ana.post('/api/handoff').send({ target: 'presentation', content: 'x', tabular: { workspace_id: 'ws-ea-1', question: '' } });
  assert.strictEqual(r.status, 400);
  assert.strictEqual(tabular.calls.length, 0); assert.strictEqual(presenton.calls.length, 0);
});

test('handoff: destino documento sin motor → 404 feature_disabled; destino inválido → 400', async (t) => {
  const { ana } = await boot(t);
  let r = await ana.post('/api/handoff').send({ target: 'document', content: 'x' });
  assert.strictEqual(r.status, 404); assert.strictEqual(r.body.code, 'feature_disabled');
  r = await ana.post('/api/handoff').send({ target: 'excel', content: 'x' });
  assert.strictEqual(r.status, 400);
});

test('flags: Hub solo con Guardian — features todo en falso, rutas de motores 404, sesión y chat directo siguen', async (t) => {
  const { ana } = await boot(t, { withTabular: false, withPresenton: false });
  const f = await ana.get('/api/features');
  assert.deepStrictEqual({ tabular: f.body.tabular, presentations: f.body.presentations, docgen: f.body.docgen }, { tabular: false, presentations: false, docgen: false });
  assert.strictEqual((await ana.get('/api/tabular/workspaces')).status, 404);
  assert.strictEqual((await ana.post('/api/presentations/generate').send({ content: 'x' })).status, 404);
  assert.strictEqual((await ana.post('/api/handoff').send({ target: 'presentation', content: 'x' })).status, 404);
  assert.strictEqual((await ana.get('/api/user/current')).status, 200);
  assert.strictEqual((await ana.get('/api/artifacts')).status, 200);
});
