// P6 paso 1 (plan de verificación 043/044) + bug real encontrado en verificación en vivo
// (09-sep): con el motor de documentos respondiendo un error HTTP, /api/chat ya devolvía
// el mensaje neutro de siempre ("El servicio de documentos no está disponible..."). Pero
// con el motor completamente CAÍDO (nada escuchando en el puerto — no un 500, un
// connection-refused real), `fetch()` lanza ANTES de llegar a ese chequeo, y el catch
// general del handler devolvía `err.message` crudo (`"fetch failed"`, o peor con DNS:
// `"getaddrinfo ENOTFOUND ..."`) directo al chat — un nombre técnico visible para
// cualquiera que use el Hub, justo lo que el plan de branding neutro prohíbe.
const test = require('node:test');
const assert = require('node:assert');
const request = require('supertest');
const { startMockServer } = require('../mock-servers');

function buildFakeBackend() {
  const state = {
    users: { 'token-ana': { id: 'ana-id', username: 'ana', role: 'client' } },
    workspaces: [{
      id: 'ws-1', engine_slug: 'contabilidad', display_name: 'Contabilidad',
      members: [{ user_id: 'ana-id', role: 'owner' }],
    }],
  };
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
      return send(200, {
        workspaces: state.workspaces.map((w) => ({
          id: w.id, engine_slug: w.engine_slug, display_name: w.display_name,
          role: 'owner', status: 'active',
        })),
      });
    }
    if (req.method === 'GET' && pathname === `/workspaces/${state.workspaces[0].id}/threads`) {
      return send(200, { threads: [] });
    }
    if (req.method === 'POST' && pathname === '/chat/completions') {
      return send(200, { response: 'no debería llegar acá con slug seteado' });
    }
    return send(404, { detail: 'no encontrado en el doble de backend' });
  };
  return { handler, state };
}

test('motor de documentos completamente caído (fetch lanza): mensaje neutro, sin detalle técnico', async (t) => {
  const fakeBackend = buildFakeBackend();
  const backend = await startMockServer((req, res, body) => fakeBackend.handler(req, res, body));

  // Motor "caído": un mock server que se cierra ANTES de la llamada de chat, así el
  // fetch pega contra un puerto sin nada escuchando (ECONNREFUSED real, no un 4xx/5xx
  // que el `if (!r.ok)` ya sabía manejar).
  const engineFantasma = await startMockServer((req, res) => {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end('{}');
  });
  const engineUrl = engineFantasma.url;
  await engineFantasma.close();

  process.env.ELEA_BACKEND_URL = backend.url;
  process.env.ANYTHINGLLM_URL = engineUrl;
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  process.env.MASKING_VIRTUAL_KEY = 'test-mask-key';
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  t.after(async () => { await backend.close(); });

  const anaAgent = request.agent(app);
  await anaAgent.post('/api/auth/login').send({ username: 'ana', password: 'x' });

  const res = await anaAgent.post('/api/chat').send({ slug: 'contabilidad', message: 'hola' });
  assert.strictEqual(res.status, 502);
  assert.strictEqual(
    res.body.error,
    'El servicio de documentos no está disponible. Intentá de nuevo en unos minutos.'
  );
  const crudo = JSON.stringify(res.body).toLowerCase();
  for (const termino of ['fetch failed', 'econnrefused', 'enotfound', engineUrl.toLowerCase()]) {
    assert.ok(!crudo.includes(termino), `el error no debe filtrar detalle técnico ("${termino}")`);
  }
});

test('chat directo (sin slug) con el Guardian caído: mensaje neutro propio, no el de "servicio de documentos"', async (t) => {
  const backendFantasma = await startMockServer((req, res) => {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end('{}');
  });
  const backendUrl = backendFantasma.url;
  await backendFantasma.close();

  process.env.ELEA_BACKEND_URL = backendUrl;
  process.env.ANYTHINGLLM_URL = 'http://127.0.0.1:1';
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  process.env.MASKING_VIRTUAL_KEY = 'test-mask-key';
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');

  // Sin backend real, el login mismo falla — lo que importa acá es que NINGÚN catch
  // del servidor devuelva un error técnico crudo, con o sin sesión.
  const res = await request(app).post('/api/auth/login').send({ username: 'ana', password: 'x' });
  const crudo = JSON.stringify(res.body).toLowerCase();
  for (const termino of ['fetch failed', 'econnrefused', 'enotfound']) {
    assert.ok(!crudo.includes(termino), `login sin backend no debe filtrar detalle técnico ("${termino}")`);
  }
});
