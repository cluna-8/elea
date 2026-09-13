// Hub ↔ motor tabular (spec 050 US2, contratos 02 y 03 §3.2). Dobles HTTP reales
// (node:http) de Guardian y del motor tabular; Hub real (server.js) hablándoles por fetch.
//
// Lo que se prueba: (1) el Hub verifica membresía contra Guardian ANTES de tocar el motor
// (FR-011); (2) el archivo viaja como multipart real al motor y NUNCA a Guardian (FR-002);
// (3) `X-Hub-User-Id` + token interno en cada llamada al motor (FR-020/022); (4) los códigos
// del motor se traducen a copy neutro sin nombrar el motor (FR-016); (5) sin motor
// configurado, /api/features lo dice y las rutas responden 404 (FR-010).
const test = require('node:test');
const assert = require('node:assert');
const request = require('supertest');
const { startMockServer } = require('../mock-servers');

const TOKEN = 'tabular-internal-test-token';

function buildFakeGuardian() {
  const workspaces = [
    { id: 'ws-ea-1', engine_slug: 'ventas-q3', display_name: 'Ventas Q3', kind: 'exact_analysis', members: ['ana-id'] },
    { id: 'ws-rag-1', engine_slug: 'docs', display_name: 'Docs', kind: 'rag', members: ['ana-id'] },
    { id: 'ws-ea-ajeno', engine_slug: 'ajeno', display_name: 'De Bruno', kind: 'exact_analysis', members: ['bruno-id'] },
  ];
  const users = { 'token-ana': { id: 'ana-id', username: 'ana', role: 'client' } };
  const calls = [];
  const handler = (req, res, body) => {
    calls.push(`${req.method} ${req.url}`);
    const send = (status, json) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(json)); };
    const [pathname] = req.url.split('?');
    const user = users[(req.headers.authorization || '').replace('Bearer ', '')];
    if (req.method === 'POST' && pathname === '/users/login') return send(200, { access_token: 'token-ana', user: users['token-ana'] });
    if (!user) return send(401, { detail: 'no auth' });
    if (req.method === 'GET' && pathname === '/users/me/budget') return send(200, { used_usd: 1, max_usd: 10, status: 'ok' });
    if (req.method === 'GET' && pathname === '/workspaces') {
      return send(200, { workspaces: workspaces.filter((w) => w.members.includes(user.id)).map((w) => ({ id: w.id, engine_slug: w.engine_slug, display_name: w.display_name, role: 'owner', status: 'active', kind: w.kind })) });
    }
    if (req.method === 'POST' && pathname === '/workspaces') {
      assert.strictEqual(body.kind, 'exact_analysis', 'el Hub debe declarar kind al crear (FR-041)');
      const ws = { id: 'ws-ea-2', engine_slug: 'pendiente-x', display_name: body.display_name, kind: 'exact_analysis', members: [user.id] };
      workspaces.push(ws);
      return send(200, { id: ws.id, engine_slug: ws.engine_slug, display_name: ws.display_name, role: 'owner', status: 'active', kind: ws.kind });
    }
    const m = pathname.match(/^\/workspaces\/([^/]+)$/);
    if (req.method === 'GET' && m) {
      const ws = workspaces.find((w) => w.id === m[1]);
      if (!ws || !ws.members.includes(user.id)) return send(403, { detail: 'sin acceso a este espacio' });
      return send(200, { id: ws.id, engine_slug: ws.engine_slug, display_name: ws.display_name, role: 'owner', status: 'active', kind: ws.kind });
    }
    return send(404, { detail: `Guardian doble: ${req.method} ${pathname}` });
  };
  return { handler, calls };
}

function buildFakeTabular() {
  const calls = [];
  const spaces = new Set();
  let nextQuery = { status: 200, body: { sql: 'SELECT depto, SUM(monto) AS total FROM f1_ventas GROUP BY depto LIMIT 500', columns: ['depto', 'total'], rows: [{ depto: 'Ventas', total: 150 }], answer: 'Ventas suma 150.', model_used: 'azure-gpt-4o-mini' } };
  const handler = (req, res, body, raw) => {
    calls.push({ method: req.method, url: req.url, auth: req.headers.authorization, user: req.headers['x-hub-user-id'], ctype: req.headers['content-type'] || '' });
    const send = (status, json) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(json)); };
    if (req.headers.authorization !== `Bearer ${TOKEN}`) return send(401, { detail: { code: 'unauthorized' } });
    if (!req.headers['x-hub-user-id']) return send(400, { detail: { code: 'missing_user' } });
    const [pathname] = req.url.split('?');
    if (req.method === 'POST' && pathname === '/v1/spaces') {
      if (spaces.has(body.workspace_id)) return send(409, { detail: { code: 'space_exists' } });
      spaces.add(body.workspace_id); return send(201, { workspace_id: body.workspace_id });
    }
    let m = pathname.match(/^\/v1\/spaces\/([^/]+)\/files$/);
    if (m && req.method === 'GET') return send(200, { files: [{ file_id: 'f1', name: 'ventas.csv', tables: [{ name: 'f1_ventas', columns: [{ name: 'depto', type: 'VARCHAR' }], rows: 3 }] }] });
    if (m && req.method === 'POST') return send(201, { file_id: 'f1', name: 'ventas.csv', tables: [{ name: 'f1_ventas', columns: [{ name: 'depto', type: 'VARCHAR' }, { name: 'monto', type: 'BIGINT' }], rows: 3, sample: [] }] });
    m = pathname.match(/^\/v1\/spaces\/([^/]+)\/files\/([^/]+)$/);
    if (m && req.method === 'DELETE') return send(m[2] === 'f1' ? 200 : 404, m[2] === 'f1' ? { status: 'ok' } : { detail: { code: 'file_not_found' } });
    m = pathname.match(/^\/v1\/spaces\/([^/]+)\/query$/);
    if (m && req.method === 'POST') return send(nextQuery.status, nextQuery.body);
    return send(404, { detail: { code: 'space_not_found' } });
  };
  return { handler, calls, setNextQuery: (q) => { nextQuery = q; } };
}

async function boot(t, { withTabular = true } = {}) {
  const guardian = buildFakeGuardian();
  const tabular = buildFakeTabular();
  const g = await startMockServer((req, res, body) => guardian.handler(req, res, body));
  const tb = await startMockServer((req, res, body) => tabular.handler(req, res, body));
  process.env.ELEA_BACKEND_URL = g.url;
  process.env.ANYTHINGLLM_URL = 'http://127.0.0.1:1';
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  if (withTabular) { process.env.TABULAR_URL = tb.url; process.env.TABULAR_INTERNAL_TOKEN = TOKEN; }
  else { delete process.env.TABULAR_URL; delete process.env.TABULAR_INTERNAL_TOKEN; }
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  t.after(async () => { await g.close(); await tb.close(); });
  const ana = request.agent(app);
  await ana.post('/api/auth/login').send({ username: 'ana', password: 'x' }).expect(200);
  return { ana, guardian, tabular, app };
}

test('planillas: crear espacio (kind en Guardian), subir multipart al motor, listar, preguntar, quitar', async (t) => {
  const { ana, guardian, tabular } = await boot(t);

  const feat = await ana.get('/api/features');
  assert.deepStrictEqual(feat.body, { documents: true, tabular: true, presentations: false, docgen: false });

  const created = await ana.post('/api/tabular/workspaces').send({ display_name: 'Nuevo' });
  assert.strictEqual(created.status, 200, JSON.stringify(created.body));
  assert.strictEqual(created.body.kind, 'exact_analysis');
  assert.ok(tabular.calls.some((c) => c.method === 'POST' && c.url === '/v1/spaces'), 'el Hub crea la base en el motor');

  const list = await ana.get('/api/tabular/workspaces');
  assert.deepStrictEqual(list.body.workspaces.map((w) => w.id).sort(), ['ws-ea-1', 'ws-ea-2']);

  const upload = await ana.post('/api/tabular/workspaces/ws-ea-1/files')
    .attach('file', Buffer.from('depto,monto\nVentas,100\n'), { filename: 'ventas.csv', contentType: 'text/csv' });
  assert.strictEqual(upload.status, 200, JSON.stringify(upload.body));
  assert.strictEqual(upload.body.tables[0].name, 'f1_ventas');
  const up = tabular.calls.find((c) => c.method === 'POST' && c.url === '/v1/spaces/ws-ea-1/files');
  assert.ok(up.ctype.startsWith('multipart/form-data'), 'multipart real hacia el motor');
  assert.strictEqual(up.user, 'ana-id');
  assert.strictEqual(up.auth, `Bearer ${TOKEN}`);
  // El archivo NUNCA pasa por Guardian: solo membresía y presupuesto (FR-002/FR-011).
  assert.ok(guardian.calls.includes('GET /workspaces/ws-ea-1'));
  assert.ok(!guardian.calls.some((c) => c.includes('files') || c.includes('inspect')));

  const files = await ana.get('/api/tabular/workspaces/ws-ea-1/files');
  assert.strictEqual(files.body.files[0].name, 'ventas.csv');

  const q = await ana.post('/api/tabular/workspaces/ws-ea-1/query').send({ question: 'total por depto', history: [{ question: 'a', answer: 'b' }] });
  assert.strictEqual(q.status, 200, JSON.stringify(q.body));
  assert.strictEqual(q.body.answer, 'Ventas suma 150.');
  assert.deepStrictEqual(q.body.columns, ['depto', 'total']);
  assert.ok(q.body.sql.startsWith('SELECT'));

  assert.strictEqual((await ana.delete('/api/tabular/workspaces/ws-ea-1/files/f1')).status, 200);
  assert.strictEqual((await ana.delete('/api/tabular/workspaces/ws-ea-1/files/zz')).status, 404);
});

test('planillas: sin membresía → 403 uniforme y el motor nunca es llamado; espacio RAG tampoco vale', async (t) => {
  const { ana, tabular } = await boot(t);
  for (const id of ['ws-ea-ajeno', 'ws-inexistente', 'ws-rag-1']) {
    const r = await ana.post(`/api/tabular/workspaces/${id}/query`).send({ question: 'x' });
    assert.strictEqual(r.status, 403, id);
    assert.strictEqual(r.body.error, 'No tenés acceso a este espacio.');
    const up = await ana.post(`/api/tabular/workspaces/${id}/files`)
      .attach('file', Buffer.from('a,b\n1,2\n'), { filename: 'a.csv', contentType: 'text/csv' });
    assert.strictEqual(up.status, 403, id);
  }
  assert.strictEqual(tabular.calls.length, 0, 'el motor no recibe nada sin membresía');
});

test('planillas: errores del motor → copy neutro con el código HTTP correcto, sin nombrar el motor', async (t) => {
  const { ana, tabular } = await boot(t);
  const casos = [
    [{ status: 422, body: { detail: { code: 'unsafe_sql', detail: 'DROP' } } }, 422, /consulta segura/],
    [{ status: 422, body: { detail: { code: 'not_answerable' } } }, 422, /no se puede responder/],
    [{ status: 502, body: { detail: { code: 'engine_error', status: 402 } } }, 402, /presupuesto/],
    [{ status: 502, body: { detail: { code: 'engine_error', status: 400 } } }, 422, /política de protección/],
    [{ status: 502, body: { detail: { code: 'engine_error', status: 401 } } }, 502, /no está disponible/],
    [{ status: 504, body: { detail: { code: 'timeout' } } }, 504, /tardó demasiado/],
  ];
  for (const [next, esperado, re] of casos) {
    tabular.setNextQuery(next);
    const r = await ana.post('/api/tabular/workspaces/ws-ea-1/query').send({ question: 'x' });
    assert.strictEqual(r.status, esperado, JSON.stringify(r.body));
    assert.match(r.body.error, re);
    assert.doesNotMatch(r.body.error.toLowerCase(), /duckdb|tabular|dbgpt|litellm/);
  }
});

test('planillas: formato no soportado y sin sesión', async (t) => {
  const { ana, app, tabular } = await boot(t);
  const bad = await ana.post('/api/tabular/workspaces/ws-ea-1/files')
    .attach('file', Buffer.from('%PDF-1.4'), { filename: 'informe.pdf', contentType: 'application/pdf' });
  assert.strictEqual(bad.status, 415);
  assert.strictEqual(tabular.calls.length, 0);
  const anon = request(app);
  assert.strictEqual((await anon.get('/api/tabular/workspaces')).status, 401);
  assert.strictEqual((await anon.post('/api/tabular/workspaces/ws-ea-1/query').send({ question: 'x' })).status, 401);
});

test('planillas: sin motor configurado, /api/features lo dice y las rutas devuelven 404 sin romper el resto', async (t) => {
  const { ana } = await boot(t, { withTabular: false });
  const feat = await ana.get('/api/features');
  assert.strictEqual(feat.body.tabular, false);
  const r = await ana.get('/api/tabular/workspaces');
  assert.strictEqual(r.status, 404);
  assert.strictEqual(r.body.code, 'feature_disabled');
  assert.strictEqual((await ana.get('/api/user/current')).status, 200);
});
