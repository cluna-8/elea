// Spec 056 (T049, N7 del QA v2, preexistente; decisión del owner del 2026-10-06): fijación de
// sesión y cookie mal formada en el Hub.
//  - `POST /api/auth/login` exitoso rota el `sid` (un `sid` plantado antes no hereda la sesión).
//  - `parseCookies` ignora una cookie con `%` mal formado en vez de dar 500.
// Lo visible del login no cambia (FR-005): status y cuerpo idénticos, cookie sin `Secure`.
// Contrato: specs/056-sso-entra-id-hub/contracts/hub-sso.md §5 y §7 (tests 24 y 25).
const test = require('node:test');
const assert = require('node:assert');
const request = require('supertest');
const { startMockServer } = require('../mock-servers');

const TOKEN = 'tok-secreto-049';
const USUARIO = { id: 'u-1', username: 'ana', role: 'user', display_label: 'Ana', email: 'ana@ejemplo.local', must_change_password: false };

async function setup(login = () => ({ status: 200, body: { access_token: TOKEN, user: USUARIO } })) {
  const backend = await startMockServer((req, res, body) => {
    const u = new URL(req.url, 'http://x');
    const r = u.pathname === '/users/login' ? login(body) : { status: 404, body: { detail: 'no' } };
    res.writeHead(r.status, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(r.body));
  });
  process.env.ELEA_BACKEND_URL = backend.url;
  process.env.ANYTHINGLLM_URL = backend.url;
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  delete require.cache[require.resolve('../../server.js')];
  return { app: require('../../server.js'), backend };
}

function cookiesDe(res) {
  const out = {};
  for (const raw of [].concat(res.headers['set-cookie'] || [])) {
    const [par, ...attrs] = raw.split(';');
    const i = par.indexOf('=');
    out[par.slice(0, i).trim()] = { value: par.slice(i + 1).trim(), attrs: attrs.map((a) => a.trim()), raw };
  }
  return out;
}
const lista = (res) => [].concat(res.headers['set-cookie'] || []);
const entrar = (app, cookie) => {
  const r = request(app).post('/api/auth/login').send({ username: 'ana', password: 'pw' });
  if (cookie) r.set('Cookie', cookie);
  return r;
};

test('login exitoso con un elea_rag_sid plantado → sid DISTINTO; la sesión vive bajo el nuevo y el plantado no tiene sesión', async (t) => {
  const { app, backend } = await setup();
  t.after(() => backend.close());
  const res = await entrar(app, 'elea_rag_sid=sid-plantado-por-el-atacante');
  const nuevo = cookiesDe(res).elea_rag_sid;
  assert.ok(nuevo, 'el login debe emitir un sid nuevo');
  assert.notStrictEqual(nuevo.value, 'sid-plantado-por-el-atacante');
  assert.match(nuevo.value, /^[0-9a-f]{48}$/);

  const conNuevo = await request(app).get('/api/user/current').set('Cookie', `elea_rag_sid=${nuevo.value}`);
  assert.strictEqual(conNuevo.body.isAuthenticated, true);
  const conPlantado = await request(app).get('/api/user/current').set('Cookie', 'elea_rag_sid=sid-plantado-por-el-atacante');
  assert.strictEqual(conPlantado.body.isAuthenticated, false, 'el sid plantado no hereda la sesión');
});

test('el sid con sesión previa (otro login) tampoco sobrevive: la sesión vieja se borra al rotar', async (t) => {
  const { app, backend } = await setup();
  t.after(() => backend.close());
  const uno = await entrar(app);
  const sidUno = cookiesDe(uno).elea_rag_sid.value;
  const dos = await entrar(app, `elea_rag_sid=${sidUno}`);
  const sidDos = cookiesDe(dos).elea_rag_sid.value;
  assert.notStrictEqual(sidDos, sidUno);
  const viejo = await request(app).get('/api/user/current').set('Cookie', `elea_rag_sid=${sidUno}`);
  assert.strictEqual(viejo.body.isAuthenticated, false);
  const nuevo = await request(app).get('/api/user/current').set('Cookie', `elea_rag_sid=${sidDos}`);
  assert.strictEqual(nuevo.body.isAuthenticated, true);
});

test('login: status y cuerpo idénticos a hoy y la cookie sigue sin Secure', async (t) => {
  const { app, backend } = await setup();
  t.after(() => backend.close());
  const res = await entrar(app, 'elea_rag_sid=plantado');
  assert.strictEqual(res.status, 200);
  assert.deepStrictEqual(res.body, { success: true, user: USUARIO });
  const nuevo = cookiesDe(res).elea_rag_sid;
  assert.ok(!nuevo.attrs.includes('Secure'), nuevo.raw);
  for (const a of ['HttpOnly', 'Path=/', 'SameSite=Lax']) assert.ok(nuevo.attrs.includes(a), `falta ${a}: ${nuevo.raw}`);
  assert.ok(!res.text.includes(TOKEN));
});

test('primera visita sin cookie: exactamente UN elea_rag_sid en la lista de Set-Cookie (el rotado, no el del middleware)', async (t) => {
  const { app, backend } = await setup();
  t.after(() => backend.close());
  const res = await entrar(app);
  const todas = lista(res);
  assert.strictEqual(todas.filter((c) => c.startsWith('elea_rag_sid=')).length, 1, String(todas));
  const sid = cookiesDe(res).elea_rag_sid.value;
  const cur = await request(app).get('/api/user/current').set('Cookie', `elea_rag_sid=${sid}`);
  assert.strictEqual(cur.body.isAuthenticated, true, 'la sesión vive bajo el sid que el navegador recibe');
});

test('login fallido (401 del backend) → sin rotación ni sesión', async (t) => {
  const { app, backend } = await setup(() => ({ status: 401, body: { detail: 'Credenciales inválidas' } }));
  t.after(() => backend.close());
  const res = await entrar(app, 'elea_rag_sid=sid-previo');
  assert.strictEqual(res.status, 401);
  assert.deepStrictEqual(res.body, { error: 'Credenciales inválidas' });
  assert.strictEqual(cookiesDe(res).elea_rag_sid, undefined, 'sin éxito no se emite un sid nuevo');
  const cur = await request(app).get('/api/user/current').set('Cookie', 'elea_rag_sid=sid-previo');
  assert.strictEqual(cur.body.isAuthenticated, false);
});

test('login con el backend caído (502) → sin rotación ni sesión', async (t) => {
  const { app, backend } = await setup();
  await backend.close();
  const res = await entrar(app, 'elea_rag_sid=sid-previo');
  assert.strictEqual(res.status, 502);
  assert.strictEqual(cookiesDe(res).elea_rag_sid, undefined);
  t.diagnostic('backend cerrado antes del pedido');
});

for (const ruta of ['/api/user/current', '/api/branding', '/sso/callback?code=c&state=s']) {
  test(`cookie mal formada (x=%E0%A4%A) contra ${ruta.split('?')[0]} → nunca 500; la mala se ignora y el sid válido se respeta`, async (t) => {
    const { app, backend } = await setup();
    t.after(() => backend.close());
    const login = await entrar(app);
    const sid = cookiesDe(login).elea_rag_sid.value;
    const res = await request(app).get(ruta).set('Cookie', `x=%E0%A4%A; elea_rag_sid=${sid}`);
    assert.ok(res.status < 500, `${ruta} respondió ${res.status}`);
    if (ruta === '/api/user/current') {
      assert.strictEqual(res.body.isAuthenticated, true, 'el sid válido que va después de la cookie mala se respeta');
    }
    assert.strictEqual(cookiesDe(res).elea_rag_sid, undefined, 'no se emite un sid nuevo si el válido se leyó');
  });
}

test('cookie mal formada en el propio elea_rag_sid → se ignora como si no estuviera (sid nuevo, no 500)', async (t) => {
  const { app, backend } = await setup();
  t.after(() => backend.close());
  const res = await request(app).get('/api/user/current').set('Cookie', 'elea_rag_sid=%E0%A4%A');
  assert.strictEqual(res.status, 200);
  assert.strictEqual(res.body.isAuthenticated, false);
  assert.ok(cookiesDe(res).elea_rag_sid, 'el middleware asigna un sid nuevo');
});

test('cookie mal formada antes del login: el login igual funciona y no 500', async (t) => {
  const { app, backend } = await setup();
  t.after(() => backend.close());
  const res = await entrar(app, 'x=%E0%A4%A');
  assert.strictEqual(res.status, 200);
  assert.strictEqual(lista(res).filter((c) => c.startsWith('elea_rag_sid=')).length, 1);
});
