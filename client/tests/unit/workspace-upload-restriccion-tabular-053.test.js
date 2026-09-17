// Spec 053 (US3, mail Tomás Mc Nally 16-sep): .csv/.xlsx quedan afuera del RAG general
// ("Documentos del Espacio") — van solo por el motor tabular ("Planillas del Espacio"),
// que ya los valida aparte y no se toca acá. Verificado en vivo (17-sep) contra el stack
// real levantado con docker compose antes de escribir este test: 415 para .csv/.xlsx,
// 200 sin cambios para .txt.
const test = require('node:test');
const assert = require('node:assert');
const request = require('supertest');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { startMockServer } = require('../mock-servers');

async function iniciarApp() {
  const backend = await startMockServer((req, res, body) => {
    const send = (status, json) => {
      res.writeHead(status, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(json));
    };
    const [pathname] = req.url.split('?');
    if (req.method === 'POST' && pathname === '/users/login') {
      return send(200, { access_token: 'token-ana', user: { id: 'ana-id', username: 'ana', role: 'client' } });
    }
    if (req.method === 'GET' && pathname === '/workspaces') {
      return send(200, { workspaces: [{ id: 'w1', engine_slug: 'contabilidad', display_name: 'Contabilidad', role: 'owner', status: 'active', kind: 'rag' }] });
    }
    return send(200, {});
  });
  const engine = await startMockServer((req, res) => {
    // Si esto se llama para un .csv/.xlsx rechazado, el test de "no llega al motor" falla.
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ documents: [{ location: 'x' }] }));
  });

  process.env.ELEA_BACKEND_URL = backend.url;
  process.env.ANYTHINGLLM_URL = engine.url;
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  return { app, backend, engine };
}

function archivoTemporal(nombre, contenido) {
  const p = path.join(os.tmpdir(), `${nombre}-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  fs.writeFileSync(p, contenido, 'utf-8');
  return p;
}

test('rechaza .csv en el RAG general con 415 y no toca el motor de documentos', async (t) => {
  const { app, backend, engine } = await iniciarApp();
  t.after(async () => { await backend.close(); await engine.close(); });

  let llamadasAlMotor = 0;
  engine.server.on('request', () => { llamadasAlMotor++; });

  const agent = request.agent(app);
  await agent.post('/api/auth/login').send({ username: 'ana', password: 'x' });

  const tmp = archivoTemporal('planilla', 'id,monto\n1,100');
  const res = await agent.post('/api/workspaces/upload').field('slug', 'contabilidad')
    .attach('file', tmp, 'planilla-053.csv');
  fs.unlinkSync(tmp);

  assert.strictEqual(res.status, 415);
  assert.match(res.body.error, /Planillas del Espacio/);
  assert.strictEqual(llamadasAlMotor, 0, 'un archivo rechazado no debe llegar a pedirle nada al motor de documentos');
});

test('rechaza .xlsx en el RAG general con 415', async (t) => {
  const { app, backend, engine } = await iniciarApp();
  t.after(async () => { await backend.close(); await engine.close(); });

  const agent = request.agent(app);
  await agent.post('/api/auth/login').send({ username: 'ana', password: 'x' });

  const tmp = archivoTemporal('planilla', 'contenido');
  const res = await agent.post('/api/workspaces/upload').field('slug', 'contabilidad')
    .attach('file', tmp, 'planilla-053.xlsx');
  fs.unlinkSync(tmp);

  assert.strictEqual(res.status, 415);
});

test('no rompe la subida de un .txt normal al RAG general', async (t) => {
  const { app, backend, engine } = await iniciarApp();
  t.after(async () => { await backend.close(); await engine.close(); });

  const agent = request.agent(app);
  await agent.post('/api/auth/login').send({ username: 'ana', password: 'x' });

  const tmp = archivoTemporal('doc', 'contenido de prueba');
  const res = await agent.post('/api/workspaces/upload').field('slug', 'contabilidad')
    .attach('file', tmp, 'doc-053.txt');
  fs.unlinkSync(tmp);

  assert.strictEqual(res.status, 200);
  assert.strictEqual(res.body.success, true);
});
