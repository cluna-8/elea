// 017 US2 · T018 — E2E del login SSO contra el IdP REAL del cliente, con captura por paso.
//
// Qué mide (SC-003, spec 017): que el login por Entra termina en una sesión IDÉNTICA a la
// del login local —mismo juego de claims, tenant claim presente— y que con la licencia SIN
// el flag `sso` la superficie no es alcanzable y el login local sigue intacto.
//
// Por qué por FASES y no un solo `main()`: cada fase exige un ESTADO DE BACKEND distinto
// (licencia sin flag / licencia con flag / config sembrada), y un script de navegador no
// puede —ni debe— reiniciar el backend. El runbook manda el estado; esta pieza mide lo que
// tiene que valer en ese estado y deja la captura. Ver
// `specs/017-auth-rbac-sso/RUNBOOK-e2e-sso.md`.
//
//   sin-licencia          licencia SIN `sso`      → 403 en las 3 rutas + botón ausente + login local OK
//   licenciado-sin-config licencia CON `sso`      → available:false + botón ausente
//   sembrado              + fila del tenant       → botón presente + 302 al IdP real, verificado
//   degradacion           idem                    → el IdP rechaza el canje y SÓLO cae el SSO (FR-009)
//   login-real            + credenciales piloto   → el humano teclea; se mide la sesión que sale
//
// Las 3 primeras son automáticas. `login-real` NO lo es a propósito: el segundo factor del
// cliente lo resuelve una persona, y automatizar un MFA sería falsificar justo lo que este
// E2E existe para probar. El script abre el navegador con cabeza, espera, y mide el final.
//
// Uso:
//   PLAYWRIGHT_BROWSERS_PATH="$HOME/Library/Caches/ms-playwright" \
//     node e2e/017-sso-e2e.mjs http://localhost:8090 ./shots-017-sso --fase=sembrado \
//     --usuario=admin --clave='...' --tenant-id=<uuid> --client-id=<uuid> \
//     --redirect-uri=http://localhost:8090/sso/callback
//
// Exit 0 sólo si TODOS los pasos de la fase pasaron. Escribe `reporte.json` en el out-dir.

import { chromium } from 'playwright';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const FASES = ['sin-licencia', 'licenciado-sin-config', 'sembrado', 'degradacion', 'login-real'];

const base = (process.argv[2] || 'http://localhost:8090').replace(/\/$/, '');
const outDir = process.argv[3] || join(process.cwd(), 'shots-017-sso');
const flags = Object.fromEntries(
  process.argv.slice(4).filter(a => a.startsWith('--'))
    .map(a => { const i = a.indexOf('='); return i === -1 ? [a.slice(2), true] : [a.slice(2, i), a.slice(i + 1)]; })
);

const fase = flags.fase || 'sin-licencia';
if (!FASES.includes(fase)) {
  console.error(`fase desconocida: ${fase}. Opciones: ${FASES.join(' · ')}`);
  process.exit(2);
}

const USUARIO = flags.usuario || process.env.BASA_E2E_USUARIO || 'admin';
const CLAVE = flags.clave || process.env.BASA_E2E_CLAVE || '';
const TENANT_IDP = flags['tenant-id'] || process.env.BASA_E2E_IDP_TENANT_ID || '';
const CLIENT_ID = flags['client-id'] || process.env.BASA_E2E_IDP_CLIENT_ID || '';
const REDIRECT_URI = flags['redirect-uri'] || process.env.BASA_SSO_REDIRECT_URI || `${base}/sso/callback`;
// Cuánto se le da al humano para resolver credenciales + segundo factor.
const ESPERA_HUMANA_MS = Number(flags['espera-humana'] || 300) * 1000;

const BOTON_SSO = /Entrar con Microsoft/i;
const API = `${base}/api/v1`;

mkdirSync(outDir, { recursive: true });

const pasos = [];
let n = 0;

function registrar(nombre, ok, detalle, captura) {
  pasos.push({ paso: ++n, nombre, ok, detalle, captura: captura || null });
  console.log(`${ok ? '✅' : '❌'} ${String(n).padStart(2, '0')} · ${nombre}${detalle ? ` — ${detalle}` : ''}`);
}

/** Captura numerada y estable: el nombre lleva el paso, así el orden del runbook es el
 *  orden del directorio y una captura suelta se ubica sola en el informe. */
async function capturar(page, slug) {
  const archivo = `${fase}-${String(n + 1).padStart(2, '0')}-${slug}.png`;
  const ruta = join(outDir, archivo);
  await page.screenshot({ path: ruta, fullPage: true });
  return archivo;
}

/** Decodifica el payload de un JWT SIN verificar la firma: acá sólo se compara la FORMA
 *  (qué claims trae), que es lo que pide SC-003. Verificar la firma es del backend y ya
 *  tiene sus tests; hacerlo acá exigiría el secreto del deployment en el harness. */
function claimsDe(jwt) {
  const partes = String(jwt || '').split('.');
  if (partes.length !== 3) return null;
  try {
    return JSON.parse(Buffer.from(partes[1].replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8'));
  } catch { return null; }
}

async function json(respuesta) {
  try { return await respuesta.json(); } catch { return null; }
}

// ── plumbing de sesión ────────────────────────────────────────────────────────────────

/** Login local por API. Devuelve el token o null. Es el BRAZO DE CONTROL de SC-003: la
 *  sesión contra la que se compara la que emite el SSO. */
async function tokenLocalPorApi(ctx) {
  const r = await ctx.request.post(`${API}/users/login`, {
    data: { username: USUARIO, password: CLAVE }, failOnStatusCode: false,
  });
  if (r.status() !== 200) return { token: null, status: r.status(), cuerpo: await json(r) };
  const cuerpo = await json(r);
  return { token: cuerpo?.access_token || null, status: 200, cuerpo };
}

async function loginLocalPorPantalla(page) {
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.getByLabel(/usuario/i).first().fill(USUARIO).catch(async () => {
    await page.locator('input[type="text"]').first().fill(USUARIO);
  });
  await page.locator('input[type="password"]').first().fill(CLAVE);
  await page.getByRole('button', { name: /Ingresar al Panel/i }).click();
  // El panel se pinta cuando App.tsx pasa a currentPage="dashboard".
  await page.waitForFunction(() => !!localStorage.getItem('basa_session_token'), null, { timeout: 15000 });
  await page.waitForTimeout(800);
}

async function tokenEnNavegador(page) {
  return page.evaluate(() => localStorage.getItem('basa_session_token'));
}

// ── aserciones compartidas ────────────────────────────────────────────────────────────

/** El botón es PRESENTACIÓN, no la barrera. Se mide igual —porque su ausencia es lo que ve
 *  el usuario— pero SIEMPRE junto al estado de las rutas: ocultar un botón nunca fue un
 *  gate, y un harness que sólo mirara la pantalla certificaría una superficie abierta. */
async function medirBoton(page, esperadoPresente) {
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200); // getSsoAvailable() resuelve y re-renderiza
  // TESTIGO, y no es decorativo: «el botón no está» vale 0 si la pantalla tampoco está.
  // Sin esta línea, un 404, un bundle roto o un puerto equivocado darían el mismo cero y
  // la fase pasaría en verde midiendo la nada. Se afirma primero que HAY pantalla de acceso.
  const hayPantalla = await page.getByRole('button', { name: /Ingresar al Panel/i }).count();
  const cuantos = await page.getByRole('button', { name: BOTON_SSO }).count();
  const captura = await capturar(page, esperadoPresente ? 'login-con-boton-sso' : 'login-sin-boton-sso');
  registrar('la pantalla de acceso se dibujó (testigo del cero de abajo)', hayPantalla === 1,
    `botón de login local encontrado=${hayPantalla}`, captura);
  registrar(
    `botón «Entrar con Microsoft» ${esperadoPresente ? 'PRESENTE' : 'AUSENTE del DOM'}`,
    esperadoPresente ? cuantos === 1 : cuantos === 0,
    `encontrados=${cuantos}`,
  );
}

async function medirRuta(ctx, ruta, statusEsperado, fragmentoDetalle) {
  const r = await ctx.request.get(`${API}${ruta}`, { failOnStatusCode: false, maxRedirects: 0 });
  const cuerpo = await json(r);
  const detalle = cuerpo?.detail ?? '';
  const ok = r.status() === statusEsperado &&
    (!fragmentoDetalle || String(detalle).includes(fragmentoDetalle));
  registrar(`GET ${ruta} → ${statusEsperado}`, ok,
    `status=${r.status()}${detalle ? ` detail="${String(detalle).slice(0, 80)}"` : ''}`);
  return { status: r.status(), cuerpo };
}

/** SC-003, el corazón: la sesión que emite el SSO tiene que ser la MISMA que la local.
 *  Se compara el juego de claims, no los valores —el usuario es otro— y se exige `tenant`. */
function compararSesiones(tokenSso, tokenLocal) {
  const a = claimsDe(tokenSso), b = claimsDe(tokenLocal);
  if (!a || !b) {
    registrar('sesión SSO ≡ sesión local (forma del token)', false,
      `no se pudo decodificar (sso=${!!a} local=${!!b})`);
    return;
  }
  const clavesSso = Object.keys(a).sort(), clavesLocal = Object.keys(b).sort();
  const iguales = JSON.stringify(clavesSso) === JSON.stringify(clavesLocal);
  registrar('sesión SSO ≡ sesión local (mismo juego de claims)', iguales,
    `sso=[${clavesSso}] local=[${clavesLocal}]`);
  registrar('tenant claim presente en la sesión SSO', !!a.tenant, `tenant=${a.tenant ?? '—'}`);
  registrar('el tenant del SSO es el del deployment', a.tenant === b.tenant,
    `sso=${a.tenant} local=${b.tenant}`);
}

// ── fases ─────────────────────────────────────────────────────────────────────────────

async function faseSinLicencia(ctx, page) {
  // «no alcanzable» se prueba en las RUTAS. Las tres, no una: el flujo, el discovery que
  // dibuja el botón, y la superficie de administración que carga la config.
  await medirRuta(ctx, '/auth/sso/login', 403, 'sso_no_licenciado');
  await medirRuta(ctx, '/auth/sso/available', 403, 'sso_no_licenciado');
  await medirRuta(ctx, '/auth/sso/config', 403, 'sso_no_licenciado');
  await medirBoton(page, false);

  // Y el fallback permanente (FR-009): el login local no se entera de nada de lo anterior.
  await loginLocalPorPantalla(page);
  const token = await tokenEnNavegador(page);
  const captura = await capturar(page, 'panel-por-login-local');
  const claims = claimsDe(token);
  registrar('login local intacto con el SSO no licenciado', !!claims,
    `claims=[${claims ? Object.keys(claims).sort() : '—'}]`, captura);
  registrar('la sesión local trae tenant claim', !!claims?.tenant, `tenant=${claims?.tenant ?? '—'}`);
}

async function faseLicenciadoSinConfig(ctx, page) {
  const r = await medirRuta(ctx, '/auth/sso/available', 200);
  registrar('available dice enabled:false (licenciado, sin proveedor)',
    r.cuerpo?.enabled === false && r.cuerpo?.provider_type === null,
    JSON.stringify(r.cuerpo));
  // El flujo corta con el error del TENANT, no con el de licencia: son dos capas y el
  // runbook las separa porque se arreglan en lugares distintos.
  await medirRuta(ctx, '/auth/sso/login', 404, 'sso_no_configurado');
  await medirBoton(page, false);
}

async function faseSembrado(ctx, page) {
  const r = await medirRuta(ctx, '/auth/sso/available', 200);
  registrar('available dice enabled:true / entra',
    r.cuerpo?.enabled === true && r.cuerpo?.provider_type === 'entra',
    JSON.stringify(r.cuerpo));

  // El 302 es la prueba dura de la siembra: dice a QUÉ directorio se va, con qué app, y con
  // qué URI de retorno. Los tres valores que el cliente registró en SU portal, medidos
  // contra lo que la instalación manda de verdad — no contra lo que dice la config.
  const redir = await ctx.request.get(`${API}/auth/sso/login`, { failOnStatusCode: false, maxRedirects: 0 });
  const destino = redir.headers()['location'] || '';
  let u = null; try { u = new URL(destino); } catch { /* queda null */ }
  const q = u?.searchParams;
  registrar('GET /auth/sso/login → 302 al IdP', redir.status() === 302 && !!u,
    `status=${redir.status()} host=${u?.host ?? '—'}`);
  registrar('el 302 apunta al directorio del cliente', u?.host === 'login.microsoftonline.com',
    `host=${u?.host ?? '—'}`);
  if (TENANT_IDP) {
    registrar('la authority lleva el Directory (tenant) ID esperado',
      (u?.pathname || '').includes(TENANT_IDP), `path=${u?.pathname ?? '—'}`);
  }
  if (CLIENT_ID) {
    registrar('client_id = el de la app registrada', q?.get('client_id') === CLIENT_ID,
      `client_id=${q?.get('client_id') ?? '—'}`);
  }
  // El que más falla en instalación: tiene que ser byte a byte el registrado en el portal.
  registrar('redirect_uri = la registrada en el IdP', q?.get('redirect_uri') === REDIRECT_URI,
    `enviada="${q?.get('redirect_uri') ?? '—'}" esperada="${REDIRECT_URI}"`);
  registrar('el pedido lleva state y nonce', !!q?.get('state') && !!q?.get('nonce'),
    `state=${q?.get('state') ? 'sí' : 'no'} nonce=${q?.get('nonce') ? 'sí' : 'no'}`);
  const cookies = String(redir.headers()['set-cookie'] || '');
  registrar('el 302 siembra la cookie de flujo (HttpOnly)',
    cookies.includes('basa_sso_state') && /httponly/i.test(cookies),
    cookies.split(';').slice(0, 2).join(';'));

  await medirBoton(page, true);

  // Y el mismo camino, esta vez con un navegador de verdad: el clic tiene que ATERRIZAR en
  // la pantalla del directorio. Es la única forma de ver lo que va a ver el usuario.
  await page.getByRole('button', { name: BOTON_SSO }).click();
  const llego = await page.waitForURL(/login\.microsoftonline\.com/, { timeout: 30000 })
    .then(() => true).catch(() => false);
  await page.waitForTimeout(2500);
  const captura = await capturar(page, 'pantalla-del-directorio');
  const cuerpo = await page.content();
  const aadsts = [...new Set(cuerpo.match(/AADSTS\d+/g) || [])];
  registrar('el clic aterriza en la pantalla del directorio', llego,
    `url=${page.url().slice(0, 90)}`, captura);
  // AADSTS50058 = «no hay sesión silenciosa», que es exactamente lo normal en un login
  // limpio. Cualquier OTRO código en esta pantalla es un defecto de registro de la app.
  const rotos = aadsts.filter(c => c !== 'AADSTS50058');
  registrar('la pantalla del directorio no muestra error de registro', rotos.length === 0,
    `AADSTS=${aadsts.join(',') || '—'}`);
}

/** FR-009 medido contra el IdP DE VERDAD, no contra un doble: se arranca un flujo real
 *  —cookie de estado incluida— y se vuelve con un código que el directorio va a rechazar.
 *  Lo que se prueba es que el rechazo del IdP degrada SÓLO el camino SSO, con veredicto y
 *  sin filtrar el motivo técnico, y que el login local no se entera. Es la única parte del
 *  brazo encendido que se puede medir sin el secreto del cliente: el canje falla igual, y
 *  el camino de error es exactamente el mismo que el de un secreto vencido en la sede. */
async function faseDegradacion(ctx, page) {
  const redir = await ctx.request.get(`${API}/auth/sso/login`, { failOnStatusCode: false, maxRedirects: 0 });
  let estado = null;
  try { estado = new URL(redir.headers()['location'] || '').searchParams.get('state'); } catch { /* null */ }
  registrar('se abre un flujo real (302 + state + cookie)', redir.status() === 302 && !!estado,
    `status=${redir.status()} state=${estado ? 'sí' : 'no'}`);

  // El state es EL que emitimos, así que el flujo pasa la defensa CSRF y llega hasta el
  // canje: es ahí, contra Microsoft, donde tiene que romper. Con un state inventado
  // cortaría antes y estaríamos midiendo otra cosa.
  const r = await ctx.request.get(
    `${API}/auth/sso/callback?state=${encodeURIComponent(estado || '')}&code=codigo-invalido-a-proposito`,
    { failOnStatusCode: false, maxRedirects: 0 });
  const cuerpo = await json(r);
  const detalle = String(cuerpo?.detail ?? '');
  registrar('el canje rechazado por el directorio degrada con 401', r.status() === 401,
    `status=${r.status()} detail="${detalle.slice(0, 90)}"`);
  registrar('el 401 nombra el veredicto y ofrece el fallback',
    detalle.includes('sso_identidad_no_verificada') && /usuario y contrase/i.test(detalle), detalle.slice(0, 120));
  // El motivo técnico puede citar config del IdP: va a los logs del servidor, no al navegador.
  registrar('el 401 NO filtra el motivo técnico al cliente',
    !/client_secret|invalid_client|AADSTS|token_endpoint/i.test(detalle), `detail="${detalle.slice(0, 90)}"`);

  // Y el fallback permanente, medido donde se usa: la pantalla.
  await loginLocalPorPantalla(page);
  const captura = await capturar(page, 'panel-por-login-local-tras-fallo-sso');
  const claims = claimsDe(await tokenEnNavegador(page));
  registrar('el login local sigue entero después del fallo del SSO', !!claims?.tenant,
    `tenant=${claims?.tenant ?? '—'}`, captura);
}

async function faseLoginReal(ctx, page) {
  await faseSembrado(ctx, page);

  console.log(`\n⏸  Completá el login en la ventana del navegador (credenciales + segundo factor).`);
  console.log(`   Esperando hasta ${ESPERA_HUMANA_MS / 1000}s a que el directorio devuelva a ${base}/sso/callback …\n`);

  // La pantalla de canje es corta; se la caza escuchando la respuesta del callback en vez
  // de intentar acertarle con un timer.
  const canje = page.waitForResponse(
    r => r.url().includes('/api/v1/auth/sso/callback'), { timeout: ESPERA_HUMANA_MS },
  ).catch(() => null);
  const volvio = await page.waitForURL(u => u.pathname === '/sso/callback', { timeout: ESPERA_HUMANA_MS })
    .then(() => true).catch(() => false);
  const capturaCanje = volvio ? await capturar(page, 'canje-en-la-consola') : null;
  registrar('el directorio devuelve el navegador a la consola (no a la API)', volvio,
    `url=${page.url().slice(0, 90)}`, capturaCanje);

  const respuesta = await canje;
  registrar('el canje del código responde 200', respuesta?.status() === 200,
    `status=${respuesta?.status() ?? '—'}`);

  const entro = await page.waitForFunction(
    () => !!localStorage.getItem('basa_session_token'), null, { timeout: 30000 },
  ).then(() => true).catch(() => false);
  await page.waitForTimeout(1200);
  const capturaPanel = await capturar(page, 'panel-por-sso');
  registrar('la sesión SSO queda establecida y entra al panel', entro,
    `url=${page.url()}`, capturaPanel);

  const tokenSso = await tokenEnNavegador(page);
  const local = await tokenLocalPorApi(ctx);
  registrar('brazo de control: login local por API', !!local.token, `status=${local.status}`);
  compararSesiones(tokenSso, local.token);
}

// ── main ──────────────────────────────────────────────────────────────────────────────

const conCabeza = fase === 'login-real' || !!flags.headed;
const browser = await chromium.launch({ headless: !conCabeza });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: true });
const page = await ctx.newPage();

let explosion = null;
try {
  console.log(`\n▶ fase «${fase}» contra ${base}  ·  capturas → ${outDir}\n`);
  if (fase === 'sin-licencia') await faseSinLicencia(ctx, page);
  else if (fase === 'licenciado-sin-config') await faseLicenciadoSinConfig(ctx, page);
  else if (fase === 'sembrado') await faseSembrado(ctx, page);
  else if (fase === 'degradacion') await faseDegradacion(ctx, page);
  else await faseLoginReal(ctx, page);
} catch (e) {
  explosion = String(e?.stack || e);
  registrar('la fase terminó sin explotar', false, String(e?.message || e));
} finally {
  await ctx.close().catch(() => {});
  await browser.close().catch(() => {});
}

const fallados = pasos.filter(p => !p.ok);
const reporte = { fase, base, outDir, cuando: new Date().toISOString(), pasos, fallados: fallados.length, explosion };
writeFileSync(join(outDir, `reporte-${fase}.json`), JSON.stringify(reporte, null, 2));

console.log(`\n${fallados.length === 0 ? '✅' : '❌'} fase «${fase}»: ${pasos.length - fallados.length}/${pasos.length} pasos OK`);
if (fallados.length) fallados.forEach(p => console.log(`   · ${p.nombre} — ${p.detalle}`));
console.log(`Capturas y reporte en: ${outDir}`);
process.exit(fallados.length === 0 ? 0 : 1);
