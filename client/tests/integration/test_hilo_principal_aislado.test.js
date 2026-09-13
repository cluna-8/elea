// Bug real encontrado en verificación en vivo (10-sep, el reclamo original de Tomás: "la
// memoria de chats es compartida"). Antes de este fix, el "hilo principal" (cuando nadie
// creó un hilo explícito — el caso normal) no tenía NINGÚN hilo real detrás en el motor:
// el Hub proxeaba directo al chat/historial A NIVEL DE ESPACIO de AnythingLLM, compartido
// por cualquiera que use ese espacio. Confirmado en vivo (sesión limpia, sin caché, API
// directa): un usuario nuevo agregado a un espacio veía la conversación completa de otro.
//
// Este test simula EXACTAMENTE ese escenario con dobles HTTP reales (node:http), Hub real
// (server.js) hablándoles por `fetch` — nada de mocks de módulo: dos personas, mismo
// espacio, NINGUNA crea un hilo explícito (las dos usan "hilo principal" tal cual entra
// cualquiera sin tocar nada), y verifica que sus historiales y sus respuestas nunca se
// cruzan.
const test = require('node:test');
const assert = require('node:assert');
const request = require('supertest');
const crypto = require('node:crypto');
const { startMockServer } = require('../mock-servers');

function buildFakeBackend() {
  const state = {
    users: {
      'token-ana': { id: 'ana-id', username: 'ana', role: 'client' },
      'token-luis': { id: 'luis-id', username: 'luis', role: 'client' }
    },
    workspaces: [{
      id: 'ws-1', engine_slug: 'rrhh', display_name: 'RRHH',
      members: [{ user_id: 'ana-id', role: 'owner' }, { user_id: 'luis-id', role: 'member' }]
    }],
    threads: [] // { id, workspace_id, owner_user_id, engine_thread_slug, principal_engine_thread_slug }
  };

  const handler = (req, res, body) => {
    const send = (status, json) => {
      res.writeHead(status, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(json));
    };
    const [pathname] = req.url.split('?');
    const auth = req.headers['authorization'] || '';
    const token = auth.replace(/^Bearer\s+/, '');
    const user = state.users[token];

    if (req.method === 'POST' && pathname === '/users/login') {
      const tok = body.username === 'ana' ? 'token-ana' : 'token-luis';
      return send(200, { access_token: tok, user: state.users[tok] });
    }
    if (!user) return send(401, { detail: 'no autenticado' });

    if (req.method === 'GET' && pathname === '/users/me/budget') {
      return send(200, { used_usd: 0, max_usd: null, status: 'ok' });
    }
    if (req.method === 'GET' && pathname === '/workspaces') {
      const mine = state.workspaces
        .filter((w) => w.members.some((m) => m.user_id === user.id))
        .map((w) => ({
          id: w.id, engine_slug: w.engine_slug, display_name: w.display_name,
          role: w.members.find((m) => m.user_id === user.id).role, status: 'active'
        }));
      return send(200, { workspaces: mine });
    }
    const threadsMatch = pathname.match(/^\/workspaces\/([^/]+)\/threads$/);
    if (threadsMatch) {
      const wsId = threadsMatch[1];
      if (req.method === 'GET') {
        return send(200, {
          threads: state.threads.filter((t) => t.workspace_id === wsId && t.owner_user_id === user.id)
        });
      }
      if (req.method === 'POST') {
        const engineThreadSlug = body.engine_thread_slug || null;
        let existing = state.threads.find(
          (t) => t.workspace_id === wsId && t.owner_user_id === user.id
                && t.engine_thread_slug === engineThreadSlug
        );
        if (existing) {
          if (engineThreadSlug === null && body.principal_engine_thread_slug
              && !existing.principal_engine_thread_slug) {
            existing.principal_engine_thread_slug = body.principal_engine_thread_slug;
          }
          return send(200, existing);
        }
        const row = {
          id: crypto.randomUUID(), workspace_id: wsId, owner_user_id: user.id,
          engine_thread_slug: engineThreadSlug,
          principal_engine_thread_slug: engineThreadSlug === null
            ? (body.principal_engine_thread_slug || null) : null,
          created_at: new Date().toISOString()
        };
        state.threads.push(row);
        return send(200, row);
      }
    }
    return send(404, { detail: 'no encontrado en el doble de backend' });
  };
  return { handler, state };
}

function buildFakeAnythingLLM() {
  // slug de hilo -> mensajes [{role, content}]
  const threadMessages = {};
  let counter = 0;
  const handler = (req, res, body) => {
    const send = (status, json) => {
      res.writeHead(status, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(json));
    };
    const [pathname] = req.url.split('?');

    const newThreadMatch = pathname.match(/^\/api\/v1\/workspace\/([^/]+)\/thread\/new$/);
    if (req.method === 'POST' && newThreadMatch) {
      const slug = `thread-${++counter}`;
      threadMessages[slug] = [];
      return send(200, { thread: { slug, name: body.name || 'Nuevo hilo' } });
    }

    const chatMatch = pathname.match(/^\/api\/v1\/workspace\/([^/]+)\/thread\/([^/]+)\/chat$/);
    if (req.method === 'POST' && chatMatch) {
      const threadSlug = chatMatch[2];
      if (!threadMessages[threadSlug]) threadMessages[threadSlug] = [];
      threadMessages[threadSlug].push({ role: 'user', content: body.message });
      const respuesta = `respuesta a "${body.message}" en ${threadSlug}`;
      threadMessages[threadSlug].push({ role: 'assistant', content: respuesta });
      return send(200, { textResponse: respuesta, sources: [], metrics: { model: 'test-model' } });
    }

    const chatsMatch = pathname.match(/^\/api\/v1\/workspace\/([^/]+)\/thread\/([^/]+)\/chats$/);
    if (req.method === 'GET' && chatsMatch) {
      const threadSlug = chatsMatch[2];
      return send(200, { history: threadMessages[threadSlug] || [] });
    }

    // Endpoints A NIVEL DE ESPACIO (sin hilo) — si el Hub los llegara a tocar para el
    // "hilo principal", este test lo detecta: los dejamos devolver un mensaje CENTINELA
    // fácil de distinguir del de cualquier hilo real.
    const wsChatMatch = pathname.match(/^\/api\/v1\/workspace\/([^/]+)\/chat$/);
    if (req.method === 'POST' && wsChatMatch) {
      return send(200, { textResponse: 'CENTINELA: chat de espacio compartido', sources: [] });
    }
    const wsChatsMatch = pathname.match(/^\/api\/v1\/workspace\/([^/]+)\/chats$/);
    if (req.method === 'GET' && wsChatsMatch) {
      return send(200, { history: [{ role: 'assistant', content: 'CENTINELA: historial de espacio compartido' }] });
    }

    return send(200, {});
  };
  return { handler };
}

test('hilo principal: dos personas del mismo espacio, ninguna crea un hilo explícito, nunca se cruzan', async (t) => {
  const fakeBackend = buildFakeBackend();
  const fakeAnything = buildFakeAnythingLLM();
  const backend = await startMockServer((req, res, body) => fakeBackend.handler(req, res, body));
  const engine = await startMockServer((req, res, body) => fakeAnything.handler(req, res, body));

  process.env.ELEA_BACKEND_URL = backend.url;
  process.env.ANYTHINGLLM_URL = engine.url;
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');

  t.after(async () => { await backend.close(); await engine.close(); });

  const anaAgent = request.agent(app);
  const luisAgent = request.agent(app);
  await anaAgent.post('/api/auth/login').send({ username: 'ana', password: 'x' });
  await luisAgent.post('/api/auth/login').send({ username: 'luis', password: 'x' });

  // Ana pregunta en el espacio SIN crear ningún hilo (el caso normal).
  const anaChat = await anaAgent.post('/api/chat').send({ slug: 'rrhh', message: 'pregunta de ana' });
  assert.strictEqual(anaChat.status, 200, JSON.stringify(anaChat.body));
  assert.ok(!anaChat.body.content.includes('CENTINELA'),
    'la respuesta a Ana no debe venir del chat de espacio compartido');

  // Luis (recién agregado, jamás escribió nada) lee SU "hilo principal" en el mismo espacio.
  const luisMessages = await luisAgent.get('/api/workspaces/rrhh/messages');
  assert.strictEqual(luisMessages.status, 200);
  assert.strictEqual(luisMessages.body.messages.length, 0,
    'BUG CRÍTICO 10-sep: Luis no debe ver ningún mensaje de Ana en su hilo principal');
  const luisTexts = luisMessages.body.messages.map((m) => m.content).join(' ');
  assert.ok(!luisTexts.includes('pregunta de ana'), 'ni rastro del mensaje de Ana');
  assert.ok(!luisTexts.includes('CENTINELA'), 'tampoco debe leer el historial de espacio compartido');

  // Luis pregunta algo distinto en SU hilo principal.
  const luisChat = await luisAgent.post('/api/chat').send({ slug: 'rrhh', message: 'pregunta de luis' });
  assert.strictEqual(luisChat.status, 200, JSON.stringify(luisChat.body));
  assert.ok(!luisChat.body.content.includes('CENTINELA'));

  // Ana vuelve a leer SU hilo principal — no debe tener nada de Luis.
  const anaMessages = await anaAgent.get('/api/workspaces/rrhh/messages');
  const anaTexts = anaMessages.body.messages.map((m) => m.content).join(' ');
  assert.ok(anaTexts.includes('pregunta de ana'), 'Ana sigue viendo su propia conversación');
  assert.ok(!anaTexts.includes('pregunta de luis'), 'Ana NO debe ver la pregunta de Luis');

  // El backend registró dos hilos reales DISTINTOS, uno por persona.
  const principales = fakeBackend.state.threads.filter((t) => t.engine_thread_slug === null);
  assert.strictEqual(principales.length, 2, 'un hilo principal registrado por persona');
  const slugsReales = principales.map((t) => t.principal_engine_thread_slug);
  assert.strictEqual(new Set(slugsReales).size, 2, 'cada persona tiene su PROPIO hilo real del motor');

  // Volver a preguntar reutiliza el MISMO hilo real (no crea uno nuevo cada vez).
  await anaAgent.post('/api/chat').send({ slug: 'rrhh', message: 'segunda pregunta de ana' });
  const principalesDespues = fakeBackend.state.threads.filter((t) => t.engine_thread_slug === null);
  assert.strictEqual(principalesDespues.length, 2, 'no se crea un hilo nuevo en cada pregunta');
});
