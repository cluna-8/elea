// Spec 056 (T011 y T022): contrato del Hub con el flujo SSO — `GET /api/auth/sso/available`
// fail-closed, `GET /sso/login` (pendiente, cookies, límite de ritmo, almacén lleno, errores) y
// regresión/degradación del camino con contraseña.
// Contrato: specs/056-sso-entra-id-hub/contracts/hub-sso.md §1, §2, §4, §5 y §7 (tests 1 a 5 y 16).
// El backend es un doble HTTP real (client/tests/mock-servers.js), no un mock de `fetch`.
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

// ── Doble del backend + app del Hub (se vuelve a requerir el módulo: lee env al cargar) ─────
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

async function setup(cfgInicial = {}) {
  const h = { calls: [] };
  h.cfg = {
    available: { status: 200, body: { enabled: true, provider_type: 'entra', config: { tenant_id: 'x' }, return_origin: HUB } },
    login: () => ({
      status: 302,
      headers: {
        Location: idp(`${HUB}/sso/callback`),
        'Set-Cookie': `sentinel_sso_state=${STATE_JWT}; HttpOnly; Max-Age=600; Path=/api/v1/auth/sso; SameSite=lax; Secure`,
      },
    }),
    callback: () => ({ status: 200, body: { access_token: TOKEN, token_type: 'bearer', user: USUARIO } }),
    password: () => ({ status: 200, body: { access_token: TOKEN, user: { ...USUARIO, must_change_password: false } } }),
    ...cfgInicial,
  };
  h.backend = await startMockServer((req, res, body) => {
    const u = new URL(req.url, 'http://x');
    h.calls.push({ method: req.method, path: u.pathname, search: u.search, query: u.searchParams, cookie: req.headers.cookie, auth: req.headers.authorization, body });
    if (u.pathname === '/auth/sso/available') return responder(res, h.cfg.available);
    if (u.pathname === '/auth/sso/login') return responder(res, h.cfg.login());
    if (u.pathname === '/auth/sso/callback') return responder(res, h.cfg.callback());
    if (u.pathname === '/users/login') return responder(res, h.cfg.password(body));
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

// ── T011 · 1. available fail-closed ────────────────────────────────────────────────────────
test('available: 200 enabled:true → {enabled:true, return_origin} tal cual, no-store, sin provider_type ni config', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const res = await request(h.app).get('/api/auth/sso/available');
  assert.strictEqual(res.status, 200);
  assert.deepStrictEqual(res.body, { enabled: true, return_origin: HUB });
  assert.strictEqual(res.headers['cache-control'], 'no-store');
  assert.ok(!/provider_type|entra|tenant_id|config/.test(res.text), res.text);
});

test('available: enabled:true con return_origin null pasa tal cual (F4)', async (t) => {
  const h = await setup({ available: { status: 200, body: { enabled: true, provider_type: 'entra', return_origin: null } } });
  t.after(() => h.backend.close());
  const res = await request(h.app).get('/api/auth/sso/available');
  assert.deepStrictEqual(res.body, { enabled: true, return_origin: null });
});

test('available: enabled:true sin el campo return_origin (backend viejo) → return_origin null', async (t) => {
  const h = await setup({ available: { status: 200, body: { enabled: true, provider_type: 'entra' } } });
  t.after(() => h.backend.close());
  const res = await request(h.app).get('/api/auth/sso/available');
  assert.deepStrictEqual(res.body, { enabled: true, return_origin: null });
});

test('available: enabled:false → {enabled:false, return_origin:null} aunque el backend mande un origen', async (t) => {
  const h = await setup({ available: { status: 200, body: { enabled: false, provider_type: null, return_origin: HUB } } });
  t.after(() => h.backend.close());
  const res = await request(h.app).get('/api/auth/sso/available');
  assert.strictEqual(res.status, 200);
  assert.deepStrictEqual(res.body, { enabled: false, return_origin: null });
  assert.strictEqual(res.headers['cache-control'], 'no-store');
});

test('available: enabled que no es el booleano true ("true", 1) → fail-closed', async (t) => {
  for (const enabled of ['true', 1, 'yes']) {
    const h = await setup({ available: { status: 200, body: { enabled, return_origin: HUB } } });
    t.after(() => h.backend.close());
    const res = await request(h.app).get('/api/auth/sso/available');
    assert.deepStrictEqual(res.body, { enabled: false, return_origin: null }, String(enabled));
  }
});

for (const [nombre, available] of [
  ['403 (licencia sin sso)', { status: 403, body: { detail: 'sso_no_licenciado: …' } }],
  ['500', { status: 500, body: { detail: 'boom' } }],
  ['502', { status: 502, body: 'bad gateway' }],
  ['200 con cuerpo no JSON', { status: 200, headers: { 'Content-Type': 'text/html' }, body: '<html>proxy</html>' }],
  ['200 con JSON que no es un objeto', { status: 200, body: 'null' }],
  ['200 con cuerpo vacío', { status: 200, body: '' }],
]) {
  test(`available: ${nombre} → 200 {enabled:false, return_origin:null} (nunca un status de error)`, async (t) => {
    const h = await setup({ available });
    t.after(() => h.backend.close());
    const res = await request(h.app).get('/api/auth/sso/available');
    assert.strictEqual(res.status, 200);
    assert.deepStrictEqual(res.body, { enabled: false, return_origin: null });
    assert.strictEqual(res.headers['cache-control'], 'no-store');
  });
}

test('available: backend caído (conexión rechazada) → enabled:false', async (t) => {
  const h = await setup();
  await h.backend.close();
  const res = await request(h.app).get('/api/auth/sso/available');
  assert.strictEqual(res.status, 200);
  assert.deepStrictEqual(res.body, { enabled: false, return_origin: null });
  t.diagnostic('backend cerrado antes del pedido');
});

test('available: backend que no responde → corta por timeout (3 s) y queda enabled:false', async (t) => {
  const colgado = await startMockServer(() => { /* nunca responde */ });
  process.env.ELEA_BACKEND_URL = colgado.url;
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  t.after(async () => { colgado.server.closeAllConnections?.(); await colgado.close(); });
  const t0 = Date.now();
  const res = await request(app).get('/api/auth/sso/available');
  const ms = Date.now() - t0;
  assert.deepStrictEqual(res.body, { enabled: false, return_origin: null });
  assert.ok(ms >= 2500 && ms < 6000, `esperaba ~3 s de timeout, tardó ${ms} ms`);
});

test('available: es pre-auth (no pide sesión) y llama a /auth/sso/available del backend', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  await request(h.app).get('/api/auth/sso/available');
  assert.strictEqual(h.llamadas('/auth/sso/available').length, 1);
  assert.strictEqual(h.llamadas('/auth/sso/available')[0].auth, undefined);
});

// ── T011 · 2. /sso/login ───────────────────────────────────────────────────────────────────
test('login: guarda el pendiente y responde 302 a la Location del backend, con no-store y no-referrer', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const res = await request(h.app).get('/sso/login');
  assert.strictEqual(res.status, 302);
  assert.strictEqual(res.headers.location, idp(`${HUB}/sso/callback`));
  assert.strictEqual(res.headers['cache-control'], 'no-store');
  assert.strictEqual(res.headers['referrer-policy'], 'no-referrer');
  assert.strictEqual(h.llamadas('/auth/sso/login').length, 1);
  const sid = cookiesDe(res).elea_rag_sid.value;
  const p = h.app.locals.sso.pendientes.tomar(sid);
  assert.ok(p, 'el pendiente quedó guardado bajo el sid');
  assert.strictEqual(p.stateCookie, STATE_JWT);
  assert.strictEqual(p.state, STATE);
});

test('login: el JWT de estado del backend nunca llega al navegador (ni cabeceras ni cuerpo)', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const res = await request(h.app).get('/sso/login');
  assert.ok(!JSON.stringify(res.headers).includes(STATE_JWT));
  assert.ok(!res.text.includes(STATE_JWT));
  assert.ok(!lista(res).some((c) => c.startsWith('sentinel_sso_state')));
});

test('login con retorno https:// emite __Host-sso_flow con Secure; HttpOnly; Path=/; SameSite=Lax (F6, D12)', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const res = await request(h.app).get('/sso/login');
  const c = cookiesDe(res)['__Host-sso_flow'];
  assert.ok(c, 'falta __Host-sso_flow');
  assert.match(c.value, /^[0-9a-f]{48}$/, 'atadura de 24 bytes en hex');
  for (const a of ['Secure', 'HttpOnly', 'Path=/', 'SameSite=Lax', 'Max-Age=600']) {
    assert.ok(c.attrs.includes(a), `falta «${a}» en ${c.raw}`);
  }
  assert.ok(!c.attrs.some((a) => /^domain=/i.test(a)), '__Host- no admite Domain');
  const p = h.app.locals.sso.pendientes.tomar(cookiesDe(res).elea_rag_sid.value);
  assert.strictEqual(p.atadura, c.value, 'el pendiente guarda el valor de la atadura');
});

test('login con retorno http://localhost no emite __Host-sso_flow: queda atado solo al sid (D1)', async (t) => {
  const h = await setup({
    login: () => ({
      status: 302,
      headers: {
        Location: idp('http://localhost:8095/sso/callback'),
        'Set-Cookie': `sentinel_sso_state=${STATE_JWT}; HttpOnly; Path=/api/v1/auth/sso; SameSite=lax`,
      },
    }),
  });
  t.after(() => h.backend.close());
  const res = await request(h.app).get('/sso/login');
  assert.strictEqual(res.status, 302);
  assert.strictEqual(cookiesDe(res)['__Host-sso_flow'], undefined);
  const p = h.app.locals.sso.pendientes.tomar(cookiesDe(res).elea_rag_sid.value);
  assert.strictEqual(p.atadura, null);
});

test('login en primera visita (sin elea_rag_sid) con retorno https://: los DOS Set-Cookie y el pendiente bajo ese sid', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const res = await request(h.app).get('/sso/login');
  const todas = lista(res);
  assert.strictEqual(todas.filter((c) => c.startsWith('elea_rag_sid=')).length, 1, `una sola elea_rag_sid: ${todas}`);
  assert.strictEqual(todas.filter((c) => c.startsWith('__Host-sso_flow=')).length, 1, `una sola atadura: ${todas}`);
  const sid = cookiesDe(res).elea_rag_sid.value;
  assert.ok(h.app.locals.sso.pendientes.tomar(sid), 'el pendiente quedó bajo el sid que el navegador va a recibir');
});

test('login con elea_rag_sid ya presente: no se emite un sid nuevo, el pendiente queda bajo el existente', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const res = await request(h.app).get('/sso/login').set('Cookie', 'elea_rag_sid=sid-existente');
  assert.strictEqual(cookiesDe(res).elea_rag_sid, undefined);
  assert.ok(cookiesDe(res)['__Host-sso_flow']);
  assert.ok(h.app.locals.sso.pendientes.tomar('sid-existente'));
});

test('login: un segundo login del mismo sid reemplaza al pendiente anterior', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  await request(h.app).get('/sso/login').set('Cookie', 'elea_rag_sid=sid-r');
  await request(h.app).get('/sso/login').set('Cookie', 'elea_rag_sid=sid-r');
  assert.ok(h.app.locals.sso.pendientes.tomar('sid-r'));
  assert.strictEqual(h.app.locals.sso.pendientes.tomar('sid-r'), null);
});

test('login: pasado el límite de ritmo → sso_reintentar sin llamar al backend ni guardar pendiente', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  for (let i = 0; i < ssoLib.SSO_LOGIN_POR_MIN; i += 1) {
    const ok = await request(h.app).get('/sso/login').set('Cookie', `elea_rag_sid=sid-${i}`);
    assert.strictEqual(ok.status, 302);
    assert.ok(ok.headers.location.startsWith('https://login.microsoftonline.com/'), `pedido ${i + 1}`);
  }
  const antes = h.llamadas('/auth/sso/login').length;
  assert.strictEqual(antes, ssoLib.SSO_LOGIN_POR_MIN);
  const res = await request(h.app).get('/sso/login').set('Cookie', 'elea_rag_sid=sid-limite');
  assert.strictEqual(res.status, 302);
  assert.strictEqual(res.headers.location, '/?sso_error=sso_reintentar');
  assert.strictEqual(res.headers['cache-control'], 'no-store');
  assert.strictEqual(h.llamadas('/auth/sso/login').length, antes, 'no llamó al backend');
  assert.strictEqual(h.app.locals.sso.pendientes.tomar('sid-limite'), null, 'no guardó pendiente');
});

test('login: con el límite agotado, la ventana siguiente (reloj inyectado) vuelve a aceptar', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const base = Date.now();
  h.app.locals.sso.reloj.ahora = () => base;
  for (let i = 0; i < ssoLib.SSO_LOGIN_POR_MIN; i += 1) await request(h.app).get('/sso/login').set('Cookie', `elea_rag_sid=s${i}`);
  const bloqueado = await request(h.app).get('/sso/login').set('Cookie', 'elea_rag_sid=sx');
  assert.strictEqual(bloqueado.headers.location, '/?sso_error=sso_reintentar');
  h.app.locals.sso.reloj.ahora = () => base + 60_001;
  const otra = await request(h.app).get('/sso/login').set('Cookie', 'elea_rag_sid=sy');
  assert.ok(otra.headers.location.startsWith('https://login.microsoftonline.com/'));
});

test('login con el almacén lleno → sso_reintentar, y un pendiente en curso sigue consumible (F5, FR-016)', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const primero = await request(h.app).get('/sso/login');
  const sidEnCurso = cookiesDe(primero).elea_rag_sid.value;
  const { pendientes } = h.app.locals.sso;
  for (let i = 0; pendientes.size() < ssoLib.MAX_PENDIENTES; i += 1) {
    pendientes.guardar(`relleno-${i}`, { stateCookie: 'x', state: 'y', atadura: null });
  }
  const nuevo = await request(h.app).get('/sso/login');
  assert.strictEqual(nuevo.status, 302);
  assert.strictEqual(nuevo.headers.location, '/?sso_error=sso_reintentar');
  assert.strictEqual(pendientes.size(), ssoLib.MAX_PENDIENTES, 'no expulsó a nadie');
  const p = pendientes.tomar(sidEnCurso);
  assert.ok(p && p.state === STATE, 'el ingreso en curso sigue consumible');
});

test('login: backend 302 sin Set-Cookie sentinel_sso_state → /?sso_error=sso_error y sin pendiente', async (t) => {
  const h = await setup({ login: () => ({ status: 302, headers: { Location: idp(`${HUB}/sso/callback`) } }) });
  t.after(() => h.backend.close());
  const res = await request(h.app).get('/sso/login').set('Cookie', 'elea_rag_sid=sid-sc');
  assert.strictEqual(res.status, 302);
  assert.strictEqual(res.headers.location, '/?sso_error=sso_error');
  assert.strictEqual(h.app.locals.sso.pendientes.tomar('sid-sc'), null);
});

test('login: Location sin state o sin redirect_uri, o relativa → sso_error y sin pendiente', async (t) => {
  const casos = [
    'https://login.microsoftonline.com/x?client_id=c&redirect_uri=' + encodeURIComponent(`${HUB}/sso/callback`),
    'https://login.microsoftonline.com/x?client_id=c&state=' + STATE,
    '/relativa?state=a&redirect_uri=b',
  ];
  for (const loc of casos) {
    const h = await setup({ login: () => ({ status: 302, headers: { Location: loc, 'Set-Cookie': `sentinel_sso_state=${STATE_JWT}; HttpOnly` } }) });
    t.after(() => h.backend.close());
    const res = await request(h.app).get('/sso/login').set('Cookie', 'elea_rag_sid=sid-l');
    assert.strictEqual(res.headers.location, '/?sso_error=sso_error', loc);
    assert.strictEqual(h.app.locals.sso.pendientes.tomar('sid-l'), null);
  }
});

for (const [nombre, login, esperado] of [
  ['403 sso_no_licenciado', { status: 403, body: { detail: 'sso_no_licenciado: …' } }, 'sso_no_disponible'],
  ['404 sso_no_configurado', { status: 404, body: { detail: 'sso_no_configurado: …' } }, 'sso_no_disponible'],
  ['500 sso_redirect_uri_no_configurado', { status: 500, body: { detail: 'sso_redirect_uri_no_configurado: …' } }, 'sso_no_disponible'],
  ['400 sso_proveedor_desconocido', { status: 400, body: { detail: 'sso_proveedor_desconocido: …' } }, 'sso_no_disponible'],
  ['502 sso_idp_inaccesible', { status: 502, body: { detail: 'sso_idp_inaccesible: …' } }, 'sso_proveedor_caido'],
  ['500 inesperado', { status: 500, body: { detail: 'otra cosa' } }, 'sso_error'],
  ['200 con cuerpo raro', { status: 200, body: 'ok' }, 'sso_error'],
]) {
  test(`login: backend ${nombre} → 302 /?sso_error=${esperado}, sin copiar el detail`, async (t) => {
    const h = await setup({ login: () => login });
    t.after(() => h.backend.close());
    const res = await request(h.app).get('/sso/login').set('Cookie', 'elea_rag_sid=sid-e');
    assert.strictEqual(res.status, 302);
    assert.strictEqual(res.headers.location, `/?sso_error=${esperado}`);
    assert.strictEqual(h.app.locals.sso.pendientes.tomar('sid-e'), null);
  });
}

// ── T022 · regresión y degradación ─────────────────────────────────────────────────────────
test('regresión: POST /api/auth/login conserva status, cuerpo, must_change_password y cookie sin Secure', async (t) => {
  const usuario = { ...USUARIO, must_change_password: true };
  const h = await setup({ password: () => ({ status: 200, body: { access_token: TOKEN, user: usuario } }) });
  t.after(() => h.backend.close());
  const res = await request(h.app).post('/api/auth/login').send({ username: 'ana', password: 'pw' });
  assert.strictEqual(res.status, 200);
  assert.deepStrictEqual(res.body, { success: true, user: usuario });
  assert.ok(!res.text.includes(TOKEN), 'el token no sale al navegador');
  const sid = cookiesDe(res).elea_rag_sid;
  assert.ok(sid, 'cookie de sesión');
  assert.ok(!sid.attrs.includes('Secure'), 'el camino con contraseña no lleva Secure');
  assert.ok(sid.attrs.includes('HttpOnly') && sid.attrs.includes('Path=/') && sid.attrs.includes('SameSite=Lax'));
  const actual = await request(h.app).get('/api/user/current').set('Cookie', `elea_rag_sid=${sid.value}`);
  assert.strictEqual(actual.body.isAuthenticated, true);
  assert.strictEqual(actual.body.user.must_change_password, true, 'must_change_password pasa al user');
  assert.strictEqual(actual.body.user.auth_method, 'password');
});

test('regresión: login fallido → mismo status y mensaje del backend, sin sesión', async (t) => {
  const h = await setup({ password: () => ({ status: 401, body: { detail: 'Credenciales inválidas' } }) });
  t.after(() => h.backend.close());
  const res = await request(h.app).post('/api/auth/login').send({ username: 'ana', password: 'mal' });
  assert.strictEqual(res.status, 401);
  assert.deepStrictEqual(res.body, { error: 'Credenciales inválidas' });
});

test('regresión: login sin usuario o contraseña → 400 como hoy', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const res = await request(h.app).post('/api/auth/login').send({ username: 'ana' });
  assert.strictEqual(res.status, 400);
  assert.deepStrictEqual(res.body, { error: 'Usuario y contraseña son obligatorios.' });
});

test('regresión: change-password con sesión de contraseña se proxya al backend como hoy', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  const login = await request(h.app).post('/api/auth/login').send({ username: 'ana', password: 'pw' });
  const sid = cookiesDe(login).elea_rag_sid.value;
  const res = await request(h.app).post('/api/auth/change-password').set('Cookie', `elea_rag_sid=${sid}`)
    .send({ current_password: CLAVE_ACTUAL, new_password: CLAVE_NUEVA });
  assert.strictEqual(res.status, 200);
  assert.deepStrictEqual(res.body, { success: true });
  const c = h.llamadas('/users/me/password');
  assert.strictEqual(c.length, 1);
  assert.strictEqual(c[0].auth, `Bearer ${TOKEN}`);
  assert.deepStrictEqual(c[0].body, { current_password: CLAVE_ACTUAL, new_password: CLAVE_NUEVA });
});

test('degradación: licencia sin sso (backend 403) → available enabled:false y el login con contraseña sigue operativo', async (t) => {
  const h = await setup({ available: { status: 403, body: { detail: 'sso_no_licenciado: …' } } });
  t.after(() => h.backend.close());
  const av = await request(h.app).get('/api/auth/sso/available');
  assert.deepStrictEqual(av.body, { enabled: false, return_origin: null });
  const login = await request(h.app).post('/api/auth/login').send({ username: 'ana', password: 'pw' });
  assert.strictEqual(login.status, 200);
  assert.strictEqual(login.body.success, true);
});

test('degradación: backend caído → available enabled:false y /sso/login → sso_proveedor_caido, sin afectar otras rutas', async (t) => {
  const h = await setup();
  await h.backend.close();
  const av = await request(h.app).get('/api/auth/sso/available');
  assert.deepStrictEqual(av.body, { enabled: false, return_origin: null });
  const sso = await request(h.app).get('/sso/login').set('Cookie', 'elea_rag_sid=sid-caido');
  assert.strictEqual(sso.status, 302);
  assert.strictEqual(sso.headers.location, '/?sso_error=sso_proveedor_caido');
  const otras = await request(h.app).get('/api/branding');
  assert.strictEqual(otras.status, 200);
  const cur = await request(h.app).get('/api/user/current');
  assert.strictEqual(cur.status, 200);
  assert.strictEqual(cur.body.isAuthenticated, false);
  t.diagnostic('el cierre del doble ya ocurrió antes de los pedidos');
});

test('degradación: con el límite de ritmo agotado, POST /api/auth/login sigue operativo', async (t) => {
  const h = await setup();
  t.after(() => h.backend.close());
  for (let i = 0; i < ssoLib.SSO_LOGIN_POR_MIN; i += 1) await request(h.app).get('/sso/login').set('Cookie', `elea_rag_sid=r${i}`);
  const bloqueado = await request(h.app).get('/sso/login').set('Cookie', 'elea_rag_sid=rx');
  assert.strictEqual(bloqueado.headers.location, '/?sso_error=sso_reintentar');
  const login = await request(h.app).post('/api/auth/login').send({ username: 'ana', password: 'pw' });
  assert.strictEqual(login.status, 200);
  assert.strictEqual(login.body.success, true);
});
