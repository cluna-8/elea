// Spec 051: historial en Planillas (hilos registrados en Guardian + turnos en el motor),
// presentación desde un turno guardado, reintento del encadenado, espacio personal del chat.
// Dobles HTTP reales de Guardian, motor tabular, Presenton y motor de documentos; Hub real.
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
  const users = { 'token-ana': { id: 'ana-id', username: 'ana', role: 'client' }, 'token-bruno': { id: 'bruno-id', username: 'bruno', role: 'client' } };
  const threads = []; // registro compartido: {id, workspace_id, user_id, engine_thread_slug}
  const workspaces = [{ id: 'ws-ea-1', engine_slug: 'x', display_name: 'Ventas', kind: 'exact_analysis', members: ['ana-id', 'bruno-id'] }];
  const calls = [];
  const handler = (req, res, body) => {
    calls.push(`${req.method} ${req.url}`);
    const send = (s, j) => { res.writeHead(s, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(j)); };
    const [pathname] = req.url.split('?');
    if (req.method === 'POST' && pathname === '/users/login') { const tok = body.username === 'bruno' ? 'token-bruno' : 'token-ana'; return send(200, { access_token: tok, user: users[tok] }); }
    const user = users[(req.headers.authorization || '').replace('Bearer ', '')];
    if (!user) return send(401, {});
    if (pathname === '/users/me/budget') return send(200, { used_usd: 1, max_usd: 10, status: 'ok' });
    if (req.method === 'GET' && pathname === '/workspaces') return send(200, { workspaces: workspaces.filter((w) => w.members.includes(user.id)).map((w) => ({ ...w, role: 'owner', status: 'active' })) });
    if (req.method === 'POST' && pathname === '/workspaces') { const ws = { id: `ws-${workspaces.length + 1}`, engine_slug: body.engine_slug, display_name: body.display_name, kind: body.kind || 'rag', members: [user.id] }; workspaces.push(ws); return send(200, { ...ws, role: 'owner', status: 'active' }); }
    let m = pathname.match(/^\/workspaces\/([^/]+)$/);
    if (m) { const ws = workspaces.find((w) => w.id === m[1]); if (!ws || !ws.members.includes(user.id)) return send(403, { detail: 'sin acceso' }); return send(200, { ...ws, role: 'owner', status: 'active' }); }
    m = pathname.match(/^\/workspaces\/([^/]+)\/threads$/);
    if (m && req.method === 'GET') return send(200, { threads: threads.filter((t) => t.workspace_id === m[1] && t.user_id === user.id) });
    if (m && req.method === 'POST') { const row = { id: `th-${threads.length + 1}`, workspace_id: m[1], user_id: user.id, engine_thread_slug: body.engine_thread_slug || null, principal_engine_thread_slug: body.principal_engine_thread_slug || null }; threads.push(row); return send(200, row); }
    m = pathname.match(/^\/workspaces\/([^/]+)\/threads\/([^/]+)$/);
    if (m && req.method === 'DELETE') { const i = threads.findIndex((t) => t.id === m[2] && t.user_id === user.id); if (i < 0) return send(404, { detail: 'hilo no encontrado' }); threads.splice(i, 1); return send(200, { status: 'ok' }); }
    return send(404, { detail: `Guardian doble: ${req.method} ${pathname}` });
  };
  return { handler, calls, threads };
}

function fakeTabular() {
  const calls = []; const threads = {}; const turns = {}; let failQueryOnce = false;
  const handler = (req, res, body) => {
    calls.push({ method: req.method, url: req.url, body, user: req.headers['x-hub-user-id'] });
    const send = (s, j) => { res.writeHead(s, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(j)); };
    if (req.headers.authorization !== `Bearer ${TOKEN}`) return send(401, { detail: { code: 'unauthorized' } });
    const user = req.headers['x-hub-user-id'];
    const [pathname] = req.url.split('?');
    if (req.method === 'POST' && pathname === '/v1/spaces') return send(409, { detail: { code: 'space_exists' } });
    let m = pathname.match(/^\/v1\/spaces\/([^/]+)\/threads$/);
    if (m && req.method === 'GET') return send(200, { threads: Object.values(threads).filter((t) => t.user === user).map((t) => ({ key: t.key, title: t.title, turns: (turns[t.key] || []).length })) });
    if (m && req.method === 'POST') { if (threads[body.key] && threads[body.key].user !== user) return send(403, { detail: { code: 'thread_forbidden' } }); threads[body.key] = threads[body.key] || { key: body.key, title: body.title, user }; return send(201, { key: body.key, title: body.title, turns: 0 }); }
    m = pathname.match(/^\/v1\/spaces\/([^/]+)\/threads\/([^/]+)\/turns\/(\d+)$/);
    if (m && req.method === 'GET') { const t = (turns[m[2]] || []).find((x) => x.id === Number(m[3])); return t ? send(200, t) : send(404, { detail: { code: 'turn_not_found' } }); }
    m = pathname.match(/^\/v1\/spaces\/([^/]+)\/threads\/([^/]+)\/turns$/);
    if (m && req.method === 'GET') { if (!threads[m[2]] || threads[m[2]].user !== user) return send(403, { detail: { code: 'thread_forbidden' } }); return send(200, { turns: turns[m[2]] || [] }); }
    m = pathname.match(/^\/v1\/spaces\/([^/]+)\/threads\/([^/]+)$/);
    if (m && req.method === 'DELETE') { delete threads[m[2]]; delete turns[m[2]]; return send(200, { status: 'ok' }); }
    if (m && req.method === 'PATCH') { threads[m[2]].title = body.title; return send(200, { key: m[2], title: body.title, turns: 0 }); }
    m = pathname.match(/^\/v1\/spaces\/([^/]+)\/query$/);
    if (m && req.method === 'POST') {
      if (failQueryOnce) { failQueryOnce = false; return send(502, { detail: { code: 'engine_error' } }); }
      const out = { sql: 'SELECT zona, SUM(monto) AS total FROM t1 GROUP BY zona LIMIT 500', columns: ['zona', 'total'], rows: [{ zona: 'Norte', total: 425 }], answer: 'Norte 425.', model_used: 'm', turn_id: null };
      if (body.thread_key) { if (!threads[body.thread_key] || threads[body.thread_key].user !== user) return send(403, { detail: { code: 'thread_forbidden' } }); turns[body.thread_key] = turns[body.thread_key] || []; out.turn_id = turns[body.thread_key].length + 1; turns[body.thread_key].push({ id: out.turn_id, question: body.question, answer: out.answer, sql: out.sql, columns: out.columns, rows: out.rows, stale: false }); }
      return send(200, out);
    }
    return send(404, { detail: { code: 'space_not_found' } });
  };
  return { handler, calls, failOnce: () => { failQueryOnce = true; } };
}

function fakePresenton() {
  const calls = [];
  const handler = (req, res, body) => {
    calls.push({ method: req.method, url: req.url, body });
    if (req.method === 'POST' && req.url === '/api/v1/ppt/presentation/generate') { res.writeHead(200, { 'Content-Type': 'application/json' }); return res.end(JSON.stringify({ presentation_id: 'p', path: '/app_data/exports/p.pptx', edit_path: '/p' })); }
    if (req.url === '/app_data/exports/p.pptx') { res.writeHead(200); return res.end(PPTX); }
    res.writeHead(404); res.end();
  };
  return { handler, calls };
}

function fakeDocs() {
  const calls = []; let n = 0;
  const handler = (req, res, body) => {
    calls.push({ method: req.method, url: req.url, body });
    const send = (s, j) => { res.writeHead(s, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(j)); };
    if (req.method === 'POST' && req.url === '/api/v1/workspace/new') { n += 1; return send(200, { workspace: { id: n, name: body.name, slug: `mi-chat-ana-${n}` } }); }
    if (req.url.endsWith('/update')) return send(200, { workspace: {} });
    return send(404, {});
  };
  return { handler, calls };
}

async function boot(t) {
  const guardian = fakeGuardian(); const tabular = fakeTabular(); const presenton = fakePresenton(); const docs = fakeDocs();
  const g = await startMockServer((q, r, b) => guardian.handler(q, r, b));
  const tb = await startMockServer((q, r, b) => tabular.handler(q, r, b));
  const p = await startMockServer((q, r, b) => presenton.handler(q, r, b));
  const d = await startMockServer((q, r, b) => docs.handler(q, r, b));
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hub-051-'));
  process.env.ELEA_BACKEND_URL = g.url; process.env.ANYTHINGLLM_URL = d.url; process.env.ANYTHINGLLM_API_KEY = 'k';
  process.env.ARTIFACTS_DIR = dir; process.env.PRESENTON_TIMEOUT_MS = '2000';
  process.env.TABULAR_URL = tb.url; process.env.TABULAR_INTERNAL_TOKEN = TOKEN; process.env.PRESENTON_URL = p.url;
  delete process.env.DOCGEN_URL;
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  t.after(async () => { await g.close(); await tb.close(); await p.close(); await d.close(); fs.rmSync(dir, { recursive: true, force: true }); });
  const ana = request.agent(app); await ana.post('/api/auth/login').send({ username: 'ana', password: 'x' }).expect(200);
  const bruno = request.agent(app); await bruno.post('/api/auth/login').send({ username: 'bruno', password: 'x' }).expect(200);
  return { ana, bruno, guardian, tabular, presenton, docs };
}

test('planillas: crear hilo lo registra en Guardian y en el motor; listar, preguntar con hilo, turnos, aislamiento, borrar', async (t) => {
  const { ana, bruno, guardian, tabular } = await boot(t);
  const c = await ana.post('/api/tabular/workspaces/ws-ea-1/threads').send({ title: 'Marzo' }).expect(200);
  assert.match(c.body.key, /^h-[0-9a-f]{12}$/);
  assert.ok(guardian.threads.some((th) => th.engine_thread_slug === c.body.key && th.user_id === 'ana-id'), 'registrado en Guardian a nombre de ana');
  assert.ok(tabular.calls.some((x) => x.method === 'POST' && x.url === '/v1/spaces/ws-ea-1/threads' && x.user === 'ana-id'), 'creado en el motor con X-Hub-User-Id');

  const l = await ana.get('/api/tabular/workspaces/ws-ea-1/threads').expect(200);
  assert.deepStrictEqual(l.body.threads.map((x) => x.key), [c.body.key]);
  // bruno comparte el espacio pero no ve el hilo de ana, ni puede preguntar en él, ni leerlo
  assert.deepStrictEqual((await bruno.get('/api/tabular/workspaces/ws-ea-1/threads').expect(200)).body.threads, []);
  await bruno.post('/api/tabular/workspaces/ws-ea-1/query').send({ question: 'x', thread_key: c.body.key }).expect(403);
  await bruno.get(`/api/tabular/workspaces/ws-ea-1/threads/${c.body.key}/turns`).expect(403);
  await bruno.delete(`/api/tabular/workspaces/ws-ea-1/threads/${c.body.key}`).expect(403);
  const motorCallsAntes = tabular.calls.length;
  // (las tres de bruno cortaron en Guardian: el motor no recibió ninguna consulta suya con ese hilo)
  assert.ok(!tabular.calls.slice(0, motorCallsAntes).some((x) => x.user === 'bruno-id' && /query|turns/.test(x.url)));

  const q = await ana.post('/api/tabular/workspaces/ws-ea-1/query').send({ question: '¿Total por zona?', thread_key: c.body.key }).expect(200);
  assert.strictEqual(q.body.turn_id, 1);
  const motorQuery = tabular.calls.find((x) => x.url === '/v1/spaces/ws-ea-1/query');
  assert.strictEqual(motorQuery.body.thread_key, c.body.key);
  assert.deepStrictEqual(motorQuery.body.history, [], 'con hilo, el contexto lo arma el motor');
  const turns = await ana.get(`/api/tabular/workspaces/ws-ea-1/threads/${c.body.key}/turns`).expect(200);
  assert.strictEqual(turns.body.turns.length, 1);
  assert.strictEqual(turns.body.turns[0].question, '¿Total por zona?');

  assert.strictEqual((await ana.patch(`/api/tabular/workspaces/ws-ea-1/threads/${c.body.key}`).send({ title: 'Marzo 2025' }).expect(200)).body.title, 'Marzo 2025');
  await ana.delete(`/api/tabular/workspaces/ws-ea-1/threads/${c.body.key}`).expect(200);
  assert.ok(!guardian.threads.some((th) => th.engine_thread_slug === c.body.key), 'borrado del registro de Guardian');
  assert.deepStrictEqual((await ana.get('/api/tabular/workspaces/ws-ea-1/threads').expect(200)).body.threads, []);
  // hilo inventado (no registrado) → 403 aunque el motor lo aceptara
  await ana.post('/api/tabular/workspaces/ws-ea-1/query').send({ question: 'x', thread_key: 'h-inventado00' }).expect(403);
});

test('handoff: presentación desde un turno guardado, sin volver a consultar; y un reintento si la consulta falla una vez', async (t) => {
  const { ana, tabular, presenton } = await boot(t);
  const th = (await ana.post('/api/tabular/workspaces/ws-ea-1/threads').send({ title: 'Marzo' }).expect(200)).body;
  await ana.post('/api/tabular/workspaces/ws-ea-1/query').send({ question: '¿Total por zona?', thread_key: th.key }).expect(200);
  const queriesAntes = tabular.calls.filter((x) => x.url.endsWith('/query')).length;
  const r = await ana.post('/api/handoff').send({ target: 'presentation', content: 'Resumen para dirección', tabular: { workspace_id: 'ws-ea-1', thread_key: th.key, turn_id: 1 }, options: { title: 'Desde turno', n_slides: 3, export_as: 'pptx' } }).expect(200);
  assert.strictEqual(r.body.tabular_used, true);
  assert.strictEqual(tabular.calls.filter((x) => x.url.endsWith('/query')).length, queriesAntes, 'no hubo consulta nueva');
  assert.match(presenton.calls[0].body.content, /Norte 425|Norte \| 425/);
  // turno de otro hilo no propio → 403
  await ana.post('/api/handoff').send({ target: 'presentation', content: 'x', tabular: { workspace_id: 'ws-ea-1', thread_key: 'h-otro', turn_id: 1 }, options: {} }).expect(403);
  // consulta que falla una vez con 5xx: el Hub reintenta y sale bien
  tabular.failOnce();
  const r2 = await ana.post('/api/handoff').send({ target: 'presentation', content: 'x', tabular: { workspace_id: 'ws-ea-1', question: 'total por zona' }, options: { title: 'Reintento', n_slides: 3, export_as: 'pptx' } }).expect(200);
  assert.strictEqual(r2.body.tabular_used, true);
});

test('chat directo: espacio personal se crea una vez, se registra en Guardian y se reutiliza', async (t) => {
  const { ana, guardian, docs } = await boot(t);
  const a = await ana.post('/api/workspaces/personal').expect(200);
  assert.strictEqual(a.body.created, true);
  assert.strictEqual(a.body.display_name, 'Mi chat · ana');
  assert.ok(docs.calls.some((c) => c.url === '/api/v1/workspace/new'), 'creado en el motor de documentos');
  assert.ok(docs.calls.some((c) => c.url.endsWith('/update') && /rioplatense/.test(JSON.stringify(c.body))), 'prompt de asistente en español');
  assert.ok(guardian.calls.some((c) => c === 'POST /workspaces'), 'registrado en Guardian');
  const b = await ana.post('/api/workspaces/personal').expect(200);
  assert.strictEqual(b.body.created, false);
  assert.strictEqual(b.body.slug, a.body.slug);
  assert.strictEqual(docs.calls.filter((c) => c.url === '/api/v1/workspace/new').length, 1, 'no se crea dos veces');
});
