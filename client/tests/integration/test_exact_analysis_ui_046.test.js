// Proxy del Hub hacia /exact-analysis (spec 046, backend ya probado en vivo — spec 048).
// Dobles HTTP reales (node:http) del backend Guardian, Hub real (server.js) hablándole por
// `fetch` — nada de mocks de módulo.
//
// Bug real encontrado en vivo (11-sep): `eleaFetch` fuerza siempre `Content-Type:
// application/json`, así que la subida de archivo (FormData/multipart) llegaba con un
// Content-Type mintiendo "json" — el backend nunca podía parsear `doc_file`, 422 crudo. El
// test de subida de este archivo es justo el que lo hubiera atrapado antes de la corrida
// manual por Chrome.
const test = require('node:test');
const assert = require('node:assert');
const request = require('supertest');
const { startMockServer } = require('../mock-servers');

function buildFakeBackend() {
  const state = {
    users: { 'token-ana': { id: 'ana-id', username: 'ana', role: 'client' } },
    workspaces: [{ id: 'ws-ea-1', engine_slug: 'ventas-q3', display_name: 'Ventas Q3', kind: 'exact_analysis' }],
  };
  let recibioMultipart = false;
  const textosEnmascarados = []; // cada texto que el Hub mandó a /gw/inspect, en orden
  const handler = (req, res, body) => {
    const send = (status, json) => {
      res.writeHead(status, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(json));
    };
    const [pathname] = req.url.split('?');
    if (req.method === 'POST' && pathname === '/users/login') {
      return send(200, { access_token: 'token-ana', user: state.users['token-ana'] });
    }
    if (req.method === 'POST' && pathname === '/gw/inspect') {
      // Enmascarado fila por fila (spec 046, decisión 11-sep: el encabezado NUNCA debe
      // llegar acá — si el test ve la fila de encabezado pasar por /gw/inspect, es una
      // regresión de esa decisión). Prefijo "MASKED:" simple y determinista, solo para
      // que el test pueda distinguir "pasó por acá" de "no pasó" en el body subido.
      textosEnmascarados.push(body.text || '');
      return send(200, { ok: true, masked: `MASKED:${body.text || ''}`, entities: [] });
    }
    if (req.method === 'GET' && pathname === '/workspaces') {
      return send(200, {
        workspaces: state.workspaces.map((w) => ({
          id: w.id, engine_slug: w.engine_slug, display_name: w.display_name,
          role: 'owner', status: 'active', kind: w.kind,
        })),
      });
    }
    if (req.method === 'POST' && pathname === '/exact-analysis/workspaces') {
      return send(200, { id: 'ws-ea-2', engine_slug: 'nuevo', display_name: body.display_name, kind: 'exact_analysis', role: 'owner' });
    }
    if (req.method === 'POST' && pathname === '/exact-analysis/workspaces/ws-ea-1/files') {
      // El doble real de `node:http` arma `body` parseando el request como JSON (ver
      // mock-servers.js) — con multipart real, eso da `{}` (no es JSON válido), que es
      // justo la señal de que SÍ llegó como multipart y no como JSON mentido. La prueba
      // real de que el bug está arreglado es que `req.headers['content-type']` empiece
      // con `multipart/form-data`, no `application/json`.
      recibioMultipart = (req.headers['content-type'] || '').startsWith('multipart/form-data');
      return send(200, {
        conv_uid: 'conv-123', file_name: 'ventas.csv',
        select_param: { file_path: 'dbgpt-fs://fake', file_name: 'ventas.csv' },
      });
    }
    if (req.method === 'POST' && pathname === '/exact-analysis/workspaces/ws-ea-1/query') {
      return send(200, { answer: 'La suma es 2100.', sql_executed: 'SELECT SUM(ventas) FROM t', model_used: 'azure-gpt-4o-mini' });
    }
    return send(404, { detail: 'no encontrado en el doble de backend' });
  };
  return { handler, gotMultipart: () => recibioMultipart, textosEnmascarados };
}

test('análisis exacto: crear espacio, subir archivo (multipart real, no JSON mentido), preguntar', async (t) => {
  const fakeBackend = buildFakeBackend();
  const backend = await startMockServer((req, res, body) => fakeBackend.handler(req, res, body));

  process.env.ELEA_BACKEND_URL = backend.url;
  process.env.ANYTHINGLLM_URL = 'http://127.0.0.1:1';
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  process.env.MASKING_VIRTUAL_KEY = 'test-mask-key';
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  t.after(async () => { await backend.close(); });

  const ana = request.agent(app);
  await ana.post('/api/auth/login').send({ username: 'ana', password: 'x' });

  // Listado filtra por kind — solo espacios de análisis exacto.
  const list = await ana.get('/api/exact-analysis/workspaces');
  assert.strictEqual(list.status, 200);
  assert.strictEqual(list.body.workspaces.length, 1);
  assert.strictEqual(list.body.workspaces[0].id, 'ws-ea-1');

  // Crear espacio
  const created = await ana.post('/api/exact-analysis/workspaces').send({ display_name: 'Ventas Q3' });
  assert.strictEqual(created.status, 200, JSON.stringify(created.body));
  assert.strictEqual(created.body.kind, 'exact_analysis');

  // Subir archivo — el bug real: esto SE ROMPÍA con Content-Type mentido.
  const upload = await ana.post('/api/exact-analysis/workspaces/ws-ea-1/files')
    .attach('file', Buffer.from('depto,monto\nVentas,100\n'), { filename: 'ventas.csv', contentType: 'text/csv' });
  assert.strictEqual(upload.status, 200, JSON.stringify(upload.body));
  assert.strictEqual(upload.body.conv_uid, 'conv-123');
  assert.ok(fakeBackend.gotMultipart(), 'el backend debe recibir Content-Type multipart real, no application/json');

  // Bug real encontrado en vivo (11-sep, spec 046): el encabezado NUNCA debe pasar por el
  // enmascarado — "depto" salía marcado como PERSON, y el motor terminaba armando SQL
  // contra una columna que ya no existía con ese nombre (respuesta `null` silenciosa, sin
  // error visible). Filas de datos SÍ deben pasar (ahí puede haber PII real).
  assert.deepStrictEqual(
    fakeBackend.textosEnmascarados,
    ['Ventas,100'],
    'solo la fila de datos debe llegar a /gw/inspect, nunca el encabezado "depto,monto"',
  );

  // Rechaza formatos no tabulares
  const badExt = await ana.post('/api/exact-analysis/workspaces/ws-ea-1/files')
    .attach('file', Buffer.from('%PDF-1.4'), { filename: 'informe.pdf', contentType: 'application/pdf' });
  assert.strictEqual(badExt.status, 422);

  // Preguntar
  const query = await ana.post('/api/exact-analysis/workspaces/ws-ea-1/query').send({
    question: '¿cuánto suma?', conv_uid: 'conv-123', select_param: { file_path: 'x' },
  });
  assert.strictEqual(query.status, 200, JSON.stringify(query.body));
  assert.strictEqual(query.body.sql_executed, 'SELECT SUM(ventas) FROM t');
});

test('análisis exacto: sin sesión, 401 en las 3 rutas', async (t) => {
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  const anon = request(app);
  const r1 = await anon.get('/api/exact-analysis/workspaces');
  const r2 = await anon.post('/api/exact-analysis/workspaces').send({ display_name: 'x' });
  const r3 = await anon.post('/api/exact-analysis/workspaces/x/query').send({ question: 'x', conv_uid: 'x', select_param: {} });
  assert.strictEqual(r1.status, 401);
  assert.strictEqual(r2.status, 401);
  assert.strictEqual(r3.status, 401);
});
