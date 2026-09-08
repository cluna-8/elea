// T029 (US3, R2 de research.md): un fallo de RED transitorio en un chunk (no un 4xx real)
// se reintenta automáticamente reusando el MISMO document_id — la persona no pierde la
// subida por un timeout momentáneo del backend. Doble HTTP real que simula la falla:
// destruye la conexión en el primer intento de cada chunk, responde bien desde el segundo.
const test = require('node:test');
const assert = require('node:assert');
const request = require('supertest');
const { startMockServer } = require('../mock-servers');

function buildFakeBackend(seenDocumentIds, fallosPorHacer) {
  const state = { users: { 'token-ana': { id: 'ana-id', username: 'ana', role: 'client' } } };
  const intentosPorTexto = new Map();
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
      return send(200, { used_usd: 0, max_usd: null, status: 'ok' });
    }
    if (req.method === 'GET' && pathname === '/workspaces') {
      return send(200, { workspaces: [{ id: 'ws-1', engine_slug: 'contabilidad', display_name: 'Contabilidad', role: 'owner', status: 'active' }] });
    }
    if (req.method === 'POST' && pathname === '/gw/inspect') {
      seenDocumentIds.push(body.document_id);
      const yaFalló = intentosPorTexto.get(body.text) || 0;
      if (fallosPorHacer > 0 && yaFalló === 0) {
        intentosPorTexto.set(body.text, 1);
        res.destroy(); // fallo de RED real (conexión cortada), no una respuesta HTTP
        return;
      }
      return send(200, { ok: true, masked: body.text, entities: [] });
    }
    return send(404, { detail: 'no encontrado en el doble de backend' });
  };
  return { handler };
}

function buildFakeAnythingLLM() {
  const handler = (req, res, body) => {
    const send = (status, json) => {
      res.writeHead(status, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(json));
    };
    const [pathname] = req.url.split('?');
    if (pathname === '/api/v1/document/upload') return send(200, { success: true, documents: [{ location: 'contabilidad/doc.txt' }] });
    if (pathname.endsWith('/update-embeddings')) return send(200, { workspace: { slug: 'contabilidad' } });
    return send(200, {});
  };
  return { handler };
}

test('reintento: un fallo de red transitorio en un chunk se recupera con el mismo document_id', async (t) => {
  const seenDocumentIds = [];
  const fakeBackend = buildFakeBackend(seenDocumentIds, 1);
  const backend = await startMockServer((req, res, body) => fakeBackend.handler(req, res, body));
  const engine = await startMockServer((req, res, body) => buildFakeAnythingLLM().handler(req, res, body));
  process.env.ELEA_BACKEND_URL = backend.url;
  process.env.ANYTHINGLLM_URL = engine.url;
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  process.env.MASKING_VIRTUAL_KEY = 'test-mask-key';
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  t.after(async () => { await backend.close(); await engine.close(); });

  const anaAgent = request.agent(app);
  await anaAgent.post('/api/auth/login').send({ username: 'ana', password: 'x' });

  const fs = require('node:fs');
  const os = require('node:os');
  const path = require('node:path');
  const tmpFile = path.join(os.tmpdir(), `doc-reintento-${Date.now()}.txt`);
  fs.writeFileSync(tmpFile, 'Contenido breve, un solo chunk.', 'utf-8');

  const res = await anaAgent
    .post('/api/workspaces/upload')
    .field('slug', 'contabilidad')
    .attach('file', tmpFile);
  fs.unlinkSync(tmpFile);

  assert.strictEqual(res.status, 200, JSON.stringify(res.body));
  // 2 intentos vistos por el backend (el que falló + el reintento), mismo document_id.
  assert.strictEqual(seenDocumentIds.length, 2);
  assert.strictEqual(seenDocumentIds[0], seenDocumentIds[1]);
  assert.strictEqual(res.body.document.documentId, seenDocumentIds[0]);
});
