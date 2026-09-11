// Contrato 3 (spec 044 US3, T028): un documento grande (más de un trozo de 4000
// caracteres) manda el MISMO `document_id` en todas las llamadas de chunk — es lo que
// hace que un dato repetido en dos trozos distintos reciba el MISMO placeholder (spec 043
// R2). Doble HTTP real del backend que registra el `document_id` de cada llamada recibida.
const test = require('node:test');
const assert = require('node:assert');
const request = require('supertest');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { startMockServer } = require('../mock-servers');

function buildFakeBackend(seenDocumentIds) {
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
      return send(200, { used_usd: 0, max_usd: null, status: 'ok' });
    }
    if (req.method === 'GET' && pathname === '/workspaces') {
      return send(200, { workspaces: [{ id: 'ws-1', engine_slug: 'contabilidad', display_name: 'Contabilidad', role: 'owner', status: 'active' }] });
    }
    if (req.method === 'POST' && pathname === '/gw/inspect') {
      seenDocumentIds.push(body.document_id);
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
    if (pathname === '/api/v1/workspace/contabilidad') return send(200, { workspace: [{ slug: 'contabilidad', name: 'Contabilidad' }] });
    if (pathname === '/api/v1/document/upload') return send(200, { success: true, documents: [{ location: 'contabilidad/doc.txt' }] });
    if (pathname.endsWith('/update-embeddings')) return send(200, { workspace: { slug: 'contabilidad' } });
    return send(200, {});
  };
  return { handler };
}

test('contrato: el mismo document_id viaja en todos los chunks de una subida grande', async (t) => {
  const seenDocumentIds = [];
  const backend = await startMockServer((req, res, body) => buildFakeBackend(seenDocumentIds).handler(req, res, body));
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

  // 9000+ caracteres → al menos 3 chunks de 4000 (MASK_CHUNK_CHARS en server.js).
  const tmpFile = path.join(os.tmpdir(), `doc-grande-${Date.now()}.txt`);
  const linea = 'Julián López, DNI 30111222, vive en Av. Siempre Viva 742.\n';
  fs.writeFileSync(tmpFile, linea.repeat(200), 'utf-8'); // ~11800 caracteres

  const res = await anaAgent
    .post('/api/workspaces/upload')
    .field('slug', 'contabilidad')
    .attach('file', tmpFile);
  fs.unlinkSync(tmpFile);

  assert.strictEqual(res.status, 200, JSON.stringify(res.body));
  assert.ok(seenDocumentIds.length >= 3, `esperaba al menos 3 chunks, hubo ${seenDocumentIds.length}`);
  const distintos = new Set(seenDocumentIds);
  assert.strictEqual(distintos.size, 1, `todos los chunks deben compartir un único document_id, hubo ${[...distintos]}`);
  assert.strictEqual(res.body.document.documentId, seenDocumentIds[0]);
});
