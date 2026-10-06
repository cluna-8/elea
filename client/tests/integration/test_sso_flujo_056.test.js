// Spec 056 (T012 y T013): camino feliz del ingreso por el Hub y atadura al navegador
// (FR-016; research D1 y D12, CSRF de login). El Hub es el intermediario del lado del servidor:
// guarda la cookie de estado del backend, la reenvía en el callback y emite la sesión.
// Contrato: specs/056-sso-entra-id-hub/contracts/hub-sso.md §2, §3, §4 y §5 (tests 6 a 15).
const test = require('node:test');
const assert = require('node:assert');
const request = require('supertest');
const { startMockServer } = require('../mock-servers');
const ssoLib = require('../../sso');

const HUB = 'https://hub.ejemplo.local';
const STATE_JWT = 'estado-firmado-056.valor-opaco-de-prueba'; // el Hub no lo decodifica (FR-003)
const STATE = 'st-abc123';
// Valores de prueba (no son credenciales reales).
const CLAVE_ACTUAL = 'clave-actual-de-prueba';
const CLAVE_NUEVA = 'clave-nueva-de-prueba';
const TOKEN = 'tok-secreto-056-no-debe-salir';
const USUARIO = { id: 'u-1', username: 'ana', role: 'user', display_label: 'Ana', email: 'ana@ejemplo.local' };

const idp = (redirectUri, state = STATE) =>
  'https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id=cid&response_type=code'
  + `&redirect_uri=${encodeURIComponent(redirectUri)}&state=${encodeURIComponent(state)}&nonce=n`;

function responder(res, r) {
  const headers = { ...(r.headers || {}) };
  let cuerpo = r.body;
  if (cuerpo !== undefined && typeof cuerpo !== 'string') {
    headers['Content-Type'] = 'application/json';
    cuerpo = JSON.stringify(cuerpo);
  }
  res.writeHead(r.status, headers);
  res.end(cuerpo === undefined ? '' : cuerpo);
}

async function setup({ retorno = `${HUB}/sso/callback`, state = STATE, ...cfgExtra } = {}) {
  const h = { calls: [] };
  h.cfg = {
    login: () => ({
      status: 302,
      headers: {
        Location: idp(retorno, state),
        'Set-Cookie': `sentinel_sso_state=${STATE_JWT}; HttpOnly; Max-Age=600; Path=/api/v1/auth/sso; SameSite=lax; Secure`,
      },
    }),
    callback: () => ({ status: 200, body: { access_token: TOKEN, token_type: 'bearer', user: USUARIO } }),
    ...cfgExtra,
  };
  h.backend = await startMockServer((req, res, body) => {
    const u = new URL(req.url, 'http://x');
    h.calls.push({ method: req.method, path: u.pathname, search: u.search, query: u.searchParams, cookie: req.headers.cookie, auth: req.headers.authorization, body });
    if (u.pathname === '/auth/sso/login') return responder(res, h.cfg.login());
    if (u.pathname === '/auth/sso/callback') return responder(res, h.cfg.callback());
    if (u.pathname === '/users/me/password') return responder(res, { status: 200, body: { success: true } });
    return responder(res, { status: 404, body: { detail: 'no' } });
  });
  process.env.ELEA_BACKEND_URL = h.backend.url;
  process.env.ANYTHINGLLM_URL = h.backend.url;
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  delete require.cache[require.resolve('../../server.js')];
  h.app = require('../../server.js');
  h.llamadas = (p) => h.calls.filter((c) => c.path === p);
  return h;
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
const sinCookie = (llamada) => llamada.cookie === undefined;

// Inicia el flujo como un navegador nuevo y devuelve lo que el navegador guardaría.
async function iniciar(h, { sid } = {}) {
  const req = request(h.app).get('/sso/login');
  if (sid) req.set('Cookie', `elea_rag_sid=${sid}`);
  const res = await req;
  assert.strictEqual(res.status, 302, 'el login debe redirigir al directorio');
  const c = cookiesDe(res);
  return {
    res,
    sid: sid || c.elea_rag_sid.value,
    atadura: c['__Host-sso_flow'] ? c['__Host-sso_flow'].value : null,
  };
}

function cookieHeader(f, { sid = f.sid, atadura = f.atadura } = {}) {
  const partes = [];
  if (sid !== null) partes.push(`elea_rag_sid=${sid}`);
  if (atadura !== null) partes.push(`__Host-sso_flow=${atadura}`);
  return partes.join('; ');
}

const callback = (h, query, cookie) => {
  const r = request(h.app).get(`/sso/callback${query}`);
  if (cookie) r.set('Cookie', cookie);
  return r;
};
const q = (obj) => `?${new URLSearchParams(obj).toString()}`;

// ── T012 · camino feliz ────────────────────────────────────────────────────────────────────
test('login → callback con el mismo sid, state y atadura: canje con la cookie de estado, sesión SSO y 302 /', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const f = await iniciar(h);
  const res = await callback(h, q({ code: 'cod-1', state: STATE }), cookieHeader(f));

  assert.strictEqual(res.status, 302);
  assert.strictEqual(res.headers.location, '/');
  assert.strictEqual(res.headers['cache-control'], 'no-store');
  assert.strictEqual(res.headers['referrer-policy'], 'no-referrer');

  const llamadas = h.llamadas('/auth/sso/callback');
  assert.strictEqual(llamadas.length, 1);
  assert.strictEqual(llamadas[0].cookie, `sentinel_sso_state=${STATE_JWT}`, 'el backend recibe la cookie de estado guardada');
  assert.strictEqual(llamadas[0].query.get('state'), STATE);
  assert.strictEqual(llamadas[0].query.get('code'), 'cod-1');
});

test('sesión con auth_method:"sso" bajo el sid ROTADO; el sid viejo queda sin sesión (D1, requisito 4)', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const f = await iniciar(h);
  const res = await callback(h, q({ code: 'c', state: STATE }), cookieHeader(f));
  const nuevo = cookiesDe(res).elea_rag_sid;
  assert.ok(nuevo, 'Set-Cookie con el sid nuevo');
  assert.notStrictEqual(nuevo.value, f.sid);
  assert.match(nuevo.value, /^[0-9a-f]{48}$/);
  for (const a of ['Secure', 'HttpOnly', 'Path=/', 'SameSite=Lax']) assert.ok(nuevo.attrs.includes(a), `falta ${a}: ${nuevo.raw}`);

  const conNuevo = await request(h.app).get('/api/user/current').set('Cookie', `elea_rag_sid=${nuevo.value}`);
  assert.strictEqual(conNuevo.body.isAuthenticated, true);
  assert.strictEqual(conNuevo.body.user.username, 'ana');
  assert.strictEqual(conNuevo.body.user.auth_method, 'sso');

  const conViejo = await request(h.app).get('/api/user/current').set('Cookie', `elea_rag_sid=${f.sid}`);
  assert.strictEqual(conViejo.body.isAuthenticated, false, 'el sid viejo no hereda la sesión');
});

test('sin atadura (retorno http://localhost): la cookie rotada va SIN Secure', async (t) => {
  const h = await setup({
    retorno: 'http://localhost:8095/sso/callback',
    login: () => ({
      status: 302,
      headers: {
        Location: idp('http://localhost:8095/sso/callback'),
        'Set-Cookie': `sentinel_sso_state=${STATE_JWT}; HttpOnly; Path=/api/v1/auth/sso; SameSite=lax`,
      },
    }),
  });
  t.after(() => h.backend.close());
  const f = await iniciar(h);
  assert.strictEqual(f.atadura, null);
  const res = await callback(h, q({ code: 'c', state: STATE }), cookieHeader(f));
  assert.strictEqual(res.headers.location, '/');
  const nuevo = cookiesDe(res).elea_rag_sid;
  assert.ok(nuevo && !nuevo.attrs.includes('Secure'), nuevo && nuevo.raw);
  assert.strictEqual(cookiesDe(res)['__Host-sso_flow'], undefined, 'no hay atadura que borrar');
});

test('cookies sin pisarse (N8): el callback https trae EXACTAMENTE el sid rotado y el borrado de __Host-sso_flow', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const f = await iniciar(h);
  const res = await callback(h, q({ code: 'c', state: STATE }), cookieHeader(f));
  const todas = lista(res);
  assert.strictEqual(todas.length, 2, `exactamente dos Set-Cookie: ${todas}`);
  const sid = todas.filter((c) => c.startsWith('elea_rag_sid='));
  const ata = todas.filter((c) => c.startsWith('__Host-sso_flow='));
  assert.strictEqual(sid.length, 1);
  assert.strictEqual(ata.length, 1);
  assert.match(ata[0], /^__Host-sso_flow=;/);
  assert.match(ata[0], /Max-Age=0/);
  for (const a of ['Secure', 'HttpOnly', 'Path=/', 'SameSite=Lax']) assert.ok(ata[0].includes(a), `el borrado debe llevar ${a}: ${ata[0]}`);
  assert.ok(!todas.some((c) => c.includes(f.sid)), 'el sid viejo no aparece en ningún Set-Cookie');
  assert.ok(!todas.some((c) => c.includes(f.atadura)), 'la atadura vieja tampoco');
});

test('callback fallido en una primera visita (el middleware ya puso su sid): una sola elea_rag_sid y ninguna rotación', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const res = await callback(h, q({ code: 'c', state: STATE }));
  assert.strictEqual(res.headers.location, '/?sso_error=sso_reintentar');
  const todas = lista(res);
  assert.strictEqual(todas.filter((c) => c.startsWith('elea_rag_sid=')).length, 1, String(todas));
});

test('code y state con &, = y # llegan al backend como UN valor cada uno (B3)', async (t) => {
  const h = await setup({ state: 'a&b=c#d' });
  t.after(() => h.backend.close());
  const f = await iniciar(h);
  const code = 'x&y=z#w&state=otro&code=otro';
  const res = await callback(h, q({ code, state: 'a&b=c#d' }), cookieHeader(f));
  assert.strictEqual(res.headers.location, '/');
  const c = h.llamadas('/auth/sso/callback')[0];
  assert.strictEqual(c.query.get('state'), 'a&b=c#d');
  assert.strictEqual(c.query.get('code'), code);
  assert.deepStrictEqual([...c.query.keys()].sort(), ['code', 'state'], `parámetros inyectados: ${c.search}`);
  assert.ok(!c.search.includes('#'), 'el # va codificado, no como fragmento');
});

test('ninguna respuesta del Hub (cabeceras ni cuerpo) contiene el access_token', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const f = await iniciar(h);
  const res = await callback(h, q({ code: 'c', state: STATE }), cookieHeader(f));
  const nuevo = cookiesDe(res).elea_rag_sid.value;
  const cur = await request(h.app).get('/api/user/current').set('Cookie', `elea_rag_sid=${nuevo}`);
  for (const r of [f.res, res, cur]) {
    assert.ok(!JSON.stringify(r.headers).includes(TOKEN), 'token en cabeceras');
    assert.ok(!r.text.includes(TOKEN), 'token en el cuerpo');
    assert.ok(!(r.headers.location || '').includes('access_token'));
  }
});

test('GET /api/user/current trae user.auth_method', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const f = await iniciar(h);
  const res = await callback(h, q({ code: 'c', state: STATE }), cookieHeader(f));
  const cur = await request(h.app).get('/api/user/current').set('Cookie', `elea_rag_sid=${cookiesDe(res).elea_rag_sid.value}`);
  assert.strictEqual(cur.body.user.auth_method, 'sso');
  assert.strictEqual(cur.body.user.email, 'ana@ejemplo.local');
});

test('POST /api/auth/change-password con sesión SSO → 409 sin llamar al backend (FR-008)', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const f = await iniciar(h);
  const res = await callback(h, q({ code: 'c', state: STATE }), cookieHeader(f));
  const sid = cookiesDe(res).elea_rag_sid.value;
  const r = await request(h.app).post('/api/auth/change-password').set('Cookie', `elea_rag_sid=${sid}`)
    .send({ current_password: CLAVE_ACTUAL, new_password: CLAVE_NUEVA });
  assert.strictEqual(r.status, 409);
  assert.deepStrictEqual(r.body, { error: 'Ingresaste con tu cuenta corporativa: la contraseña se gestiona en Microsoft.' });
  assert.strictEqual(h.llamadas('/users/me/password').length, 0);
});

test('logout de una sesión SSO la borra (sin cambio de /api/auth/logout)', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const f = await iniciar(h);
  const res = await callback(h, q({ code: 'c', state: STATE }), cookieHeader(f));
  const ck = `elea_rag_sid=${cookiesDe(res).elea_rag_sid.value}`;
  await request(h.app).post('/api/auth/logout').set('Cookie', ck);
  const cur = await request(h.app).get('/api/user/current').set('Cookie', ck);
  assert.strictEqual(cur.body.isAuthenticated, false);
});

// ── T012 · errores del callback → código de la lista cerrada (§4, test 14) ─────────────────
for (const [nombre, respuesta, esperado] of [
  ['401 sso_identidad_no_verificada', { status: 401, body: { detail: 'sso_identidad_no_verificada: …' } }, 'sso_identidad_no_verificada'],
  ['401 sso_identidad_sin_email', { status: 401, body: { detail: 'sso_identidad_sin_email: …' } }, 'sso_sin_email'],
  ['403 sso_usuario_inactivo', { status: 403, body: { detail: 'sso_usuario_inactivo: …' } }, 'sso_usuario_inactivo'],
  ['402 license_seat_limit_exceeded', { status: 402, body: { detail: 'license_seat_limit_exceeded: 10/10' } }, 'sso_sin_puestos'],
  ['403 license_creation_blocked', { status: 403, body: { detail: 'license_creation_blocked: …' } }, 'sso_sin_puestos'],
  ['403 sso_no_licenciado', { status: 403, body: { detail: 'sso_no_licenciado: …' } }, 'sso_no_disponible'],
  ['404 sso_no_configurado (apagado a mitad del ingreso)', { status: 404, body: { detail: 'sso_no_configurado: …' } }, 'sso_no_disponible'],
  ['400 sso_state_invalido', { status: 400, body: { detail: 'sso_state_invalido' } }, 'sso_reintentar'],
  ['400 sso_code_ausente', { status: 400, body: { detail: 'sso_code_ausente' } }, 'sso_cancelado'],
  ['500 inesperado', { status: 500, body: { detail: 'trace con datos internos' } }, 'sso_error'],
  ['200 sin access_token', { status: 200, body: { user: USUARIO } }, 'sso_error'],
  ['200 con cuerpo no JSON', { status: 200, body: 'ok' }, 'sso_error'],
]) {
  test(`callback: backend ${nombre} → /?sso_error=${esperado} y sin sesión`, async (t) => {
    const h = await setup({ callback: () => respuesta });
    t.after(() => h.backend.close());
    const f = await iniciar(h);
    const res = await callback(h, q({ code: 'c', state: STATE }), cookieHeader(f));
    assert.strictEqual(res.status, 302);
    assert.strictEqual(res.headers.location, `/?sso_error=${esperado}`);
    assert.ok(!res.headers.location.includes('detalle') && !res.headers.location.includes('trace'));
    const conViejo = await request(h.app).get('/api/user/current').set('Cookie', `elea_rag_sid=${f.sid}`);
    assert.strictEqual(conViejo.body.isAuthenticated, false);
    assert.strictEqual(cookiesDe(res).elea_rag_sid, undefined, 'sin éxito no se rota el sid');
  });
}

test('callback: backend caído durante el canje → sso_proveedor_caido', async (t) => {
  const h = await setup();
  const f = await iniciar(h);
  await h.backend.close();
  const res = await callback(h, q({ code: 'c', state: STATE }), cookieHeader(f));
  assert.strictEqual(res.headers.location, '/?sso_error=sso_proveedor_caido');
  t.diagnostic('backend cerrado entre login y callback');
});

test('callback: el cuerpo del backend (con el token) no se loguea', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const capturado = [];
  const originales = {};
  for (const m of ['log', 'info', 'warn', 'error', 'debug']) {
    originales[m] = console[m];
    console[m] = (...a) => capturado.push(a.map(String).join(' '));
  }
  try {
    const f = await iniciar(h);
    await callback(h, q({ code: 'c', state: STATE }), cookieHeader(f));
  } finally {
    Object.assign(console, originales);
  }
  const todo = capturado.join('\n');
  for (const secreto of [TOKEN, STATE_JWT, 'cod-secreto']) assert.ok(!todo.includes(secreto), `el log contiene un secreto: ${secreto}`);
});

// ── T013 · atadura al navegador ────────────────────────────────────────────────────────────
test('callback desde OTRO sid → sso_reintentar y el backend recibe la llamada SIN cabecera Cookie (para auditar)', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const f = await iniciar(h);
  const res = await callback(h, q({ code: 'c', state: STATE }), cookieHeader(f, { sid: 'sid-de-otro-navegador' }));
  assert.strictEqual(res.headers.location, '/?sso_error=sso_reintentar');
  const llamadas = h.llamadas('/auth/sso/callback');
  assert.strictEqual(llamadas.length, 1, 'el backend igual registra el rechazo');
  assert.ok(sinCookie(llamadas[0]), `no debe viajar la cookie de estado: ${llamadas[0].cookie}`);
  assert.strictEqual(cookiesDe(res).elea_rag_sid && cookiesDe(res).elea_rag_sid.value, undefined, 'no abre sesión');
  const original = await request(h.app).get('/api/user/current').set('Cookie', cookieHeader(f));
  assert.strictEqual(original.body.isAuthenticated, false);
});

test('callback con el sid correcto pero SIN __Host-sso_flow → sso_reintentar, sin canje con cookie', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const f = await iniciar(h);
  const res = await callback(h, q({ code: 'c', state: STATE }), cookieHeader(f, { atadura: null }));
  assert.strictEqual(res.headers.location, '/?sso_error=sso_reintentar');
  const llamadas = h.llamadas('/auth/sso/callback');
  assert.strictEqual(llamadas.length, 1);
  assert.ok(sinCookie(llamadas[0]));
});

test('callback con OTRA __Host-sso_flow (cookie sid inyectada, F6) → sso_reintentar, sin canje con cookie', async (t) => {
  for (const otra of ['0'.repeat(48), 'corta', `${'a'.repeat(47)}`, 'a'.repeat(200)]) {
    const h = await setup();
    t.after(() => h.backend.close());
    const f = await iniciar(h);
    const res = await callback(h, q({ code: 'c', state: STATE }), cookieHeader(f, { atadura: otra }));
    assert.strictEqual(res.status, 302, `atadura ${otra.slice(0, 8)}…`);
    assert.strictEqual(res.headers.location, '/?sso_error=sso_reintentar');
    assert.ok(h.llamadas('/auth/sso/callback').every(sinCookie));
  }
});

test('atadura correcta pero en otro sid (atacante fija su sid y la víctima aporta su atadura) → sso_reintentar', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const atacante = await iniciar(h);
  const victima = await iniciar(h);
  const res = await callback(h, q({ code: 'c', state: STATE }), cookieHeader(atacante, { atadura: victima.atadura }));
  assert.strictEqual(res.headers.location, '/?sso_error=sso_reintentar');
  assert.ok(h.llamadas('/auth/sso/callback').every(sinCookie));
});

test('el pendiente se consume aunque falle la atadura: reintentar con las cookies correctas ya no sirve', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const f = await iniciar(h);
  await callback(h, q({ code: 'c', state: STATE }), cookieHeader(f, { atadura: null }));
  const segundo = await callback(h, q({ code: 'c', state: STATE }), cookieHeader(f));
  assert.strictEqual(segundo.headers.location, '/?sso_error=sso_reintentar');
  assert.ok(h.llamadas('/auth/sso/callback').every(sinCookie));
});

test('state distinto → no hay canje con cookie', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const f = await iniciar(h);
  const res = await callback(h, q({ code: 'c', state: 'st-de-otro' }), cookieHeader(f));
  assert.strictEqual(res.headers.location, '/?sso_error=sso_reintentar');
  const llamadas = h.llamadas('/auth/sso/callback');
  assert.strictEqual(llamadas.length, 1);
  assert.ok(sinCookie(llamadas[0]));
});

test('state ausente, vacío o repetido (array) → sso_reintentar sin canje con cookie', async (t) => {
  for (const query of ['?code=c', '?code=c&state=', `?code=c&state=${STATE}&state=${STATE}`]) {
    const h = await setup();
    t.after(() => h.backend.close());
    const f = await iniciar(h);
    const res = await callback(h, query, cookieHeader(f));
    assert.strictEqual(res.headers.location, '/?sso_error=sso_reintentar', query);
    assert.ok(h.llamadas('/auth/sso/callback').every(sinCookie), query);
  }
});

test('callback repetido (mismo sid, mismo state) → el segundo falla', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const f = await iniciar(h);
  const primero = await callback(h, q({ code: 'c', state: STATE }), cookieHeader(f));
  assert.strictEqual(primero.headers.location, '/');
  const segundo = await callback(h, q({ code: 'c', state: STATE }), cookieHeader(f));
  assert.strictEqual(segundo.headers.location, '/?sso_error=sso_reintentar');
  const llamadas = h.llamadas('/auth/sso/callback');
  assert.strictEqual(llamadas.length, 2);
  assert.strictEqual(llamadas[0].cookie, `sentinel_sso_state=${STATE_JWT}`);
  assert.ok(sinCookie(llamadas[1]), 'el segundo no reusa la cookie de estado');
});

test('pendiente vencido (10 min) → sso_reintentar sin canje con cookie', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const base = Date.now();
  h.app.locals.sso.reloj.ahora = () => base;
  const f = await iniciar(h);
  h.app.locals.sso.reloj.ahora = () => base + ssoLib.TTL_PENDIENTE_MS + 1;
  const res = await callback(h, q({ code: 'c', state: STATE }), cookieHeader(f));
  assert.strictEqual(res.headers.location, '/?sso_error=sso_reintentar');
  assert.ok(h.llamadas('/auth/sso/callback').every(sinCookie));
});

test('Map vacío, como tras un reinicio del Hub → sso_reintentar', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const f = await iniciar(h);
  // Reinicio: se vuelve a cargar el módulo (almacén nuevo y vacío) contra el mismo backend.
  delete require.cache[require.resolve('../../server.js')];
  const reiniciado = require('../../server.js');
  const res = await request(reiniciado).get(`/sso/callback${q({ code: 'c', state: STATE })}`).set('Cookie', cookieHeader(f));
  assert.strictEqual(res.headers.location, '/?sso_error=sso_reintentar');
  assert.ok(h.llamadas('/auth/sso/callback').every(sinCookie));
});

test('error=access_denied del directorio → sso_cancelado; el backend recibe la cookie válida y ningún code', async (t) => {
  const h = await setup({ callback: () => ({ status: 400, body: { detail: 'sso_code_ausente' } }) });
  t.after(() => h.backend.close());
  const f = await iniciar(h);
  const res = await callback(h, q({ error: 'access_denied', error_description: 'AADSTS65004: el usuario canceló', state: STATE }), cookieHeader(f));
  assert.strictEqual(res.status, 302);
  assert.strictEqual(res.headers.location, '/?sso_error=sso_cancelado');
  assert.ok(!res.headers.location.includes('AADSTS'), 'el texto del directorio no se copia a la URL');
  const llamadas = h.llamadas('/auth/sso/callback');
  assert.strictEqual(llamadas.length, 1);
  assert.strictEqual(llamadas[0].cookie, `sentinel_sso_state=${STATE_JWT}`);
  assert.strictEqual(llamadas[0].query.get('code'), null);
  assert.strictEqual(llamadas[0].query.get('state'), STATE);
  const otra = await callback(h, q({ code: 'c', state: STATE }), cookieHeader(f));
  assert.strictEqual(otra.headers.location, '/?sso_error=sso_reintentar', 'también consumió el pendiente');
});
