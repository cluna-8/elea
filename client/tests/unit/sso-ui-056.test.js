// Spec 056 (T014, research D13): la lógica de la pantalla de ingreso vive en un módulo puro
// (`client/public/sso-ui.js`, sin DOM ni dependencias) y se prueba con `node --test`.
// Contrato: specs/056-sso-entra-id-hub/contracts/hub-sso.md §6 y §7 (tests 17 a 20).
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const SsoUi = require('../../public/sso-ui');

const HUB = 'https://hub.ejemplo.local';

// ── destinoBoton ─────────────────────────────────────────────────────────────────────
test('destinoBoton: enabled:false → sin botón (US2 AS3)', () => {
  assert.strictEqual(SsoUi.destinoBoton({ enabled: false, return_origin: HUB }, HUB), null);
  assert.strictEqual(SsoUi.destinoBoton({ enabled: false, return_origin: null }, HUB), null);
});

test('destinoBoton: enabled distinto de true (string, 1, ausente) → sin botón', () => {
  assert.strictEqual(SsoUi.destinoBoton({ enabled: 'true', return_origin: HUB }, HUB), null);
  assert.strictEqual(SsoUi.destinoBoton({ enabled: 1, return_origin: HUB }, HUB), null);
  assert.strictEqual(SsoUi.destinoBoton({ return_origin: HUB }, HUB), null);
});

test('destinoBoton: enabled:true + return_origin null/vacío/ausente → sin botón (FR-001, F4)', () => {
  assert.strictEqual(SsoUi.destinoBoton({ enabled: true, return_origin: null }, HUB), null);
  assert.strictEqual(SsoUi.destinoBoton({ enabled: true, return_origin: '' }, HUB), null);
  assert.strictEqual(SsoUi.destinoBoton({ enabled: true }, HUB), null);
});

test('destinoBoton: entrada ausente o rara → sin botón, sin lanzar', () => {
  assert.strictEqual(SsoUi.destinoBoton(null, HUB), null);
  assert.strictEqual(SsoUi.destinoBoton(undefined, HUB), null);
  assert.strictEqual(SsoUi.destinoBoton('x', HUB), null);
  assert.strictEqual(SsoUi.destinoBoton({ enabled: true, return_origin: 5 }, HUB), null);
});

test('destinoBoton: mismo origen → /sso/login (ruta relativa)', () => {
  assert.strictEqual(SsoUi.destinoBoton({ enabled: true, return_origin: HUB }, HUB), '/sso/login');
  assert.strictEqual(
    SsoUi.destinoBoton({ enabled: true, return_origin: 'http://localhost:8095' }, 'http://localhost:8095'),
    '/sso/login'
  );
});

test('destinoBoton: otro origen → `${return_origin}/sso/login`', () => {
  assert.strictEqual(
    SsoUi.destinoBoton({ enabled: true, return_origin: HUB }, 'http://192.168.1.10:8095'),
    `${HUB}/sso/login`
  );
  assert.strictEqual(
    SsoUi.destinoBoton({ enabled: true, return_origin: 'https://hub.ejemplo.local:8443' }, HUB),
    'https://hub.ejemplo.local:8443/sso/login'
  );
});

test('destinoBoton: origen que no es http(s) → sin botón', () => {
  for (const o of ['javascript:alert(1)', 'data:text/html,x', 'ftp://hub.ejemplo.local', 'file:///etc/passwd', '//hub.ejemplo.local', 'hub.ejemplo.local']) {
    assert.strictEqual(SsoUi.destinoBoton({ enabled: true, return_origin: o }, HUB), null, o);
  }
});

test('destinoBoton: origen MAL FORMADO → sin botón (N5 del QA v2)', () => {
  const malos = [
    'https://a"onmouseover=x',      // comilla
    'https://a b',                  // espacio
    'https://a<b',                  // <
    'https://hub.ejemplo.local\\x', // barra invertida
    'https://u@hub.ejemplo.local',  // credenciales
    'https://u:p@hub.ejemplo.local',
    'https://hub.ejemplo.local/ruta', // ruta
    'https://hub.ejemplo.local/',   // barra final
    'https://hub.ejemplo.local?x=1',
    'https://hub.ejemplo.local#x',
    'HTTPS://HUB.EJEMPLO.LOCAL',    // no normalizado: new URL(x).origin !== x
    ' https://hub.ejemplo.local',
  ];
  for (const o of malos) {
    assert.strictEqual(SsoUi.destinoBoton({ enabled: true, return_origin: o }, HUB), null, JSON.stringify(o));
  }
});

// ── TEXTO_BOTON ──────────────────────────────────────────────────────────────────────
test('TEXTO_BOTON: exportado y no vacío (N6 del QA v2)', () => {
  assert.strictEqual(typeof SsoUi.TEXTO_BOTON, 'string');
  assert.ok(SsoUi.TEXTO_BOTON.trim().length > 0);
});

// ── mensajeError ─────────────────────────────────────────────────────────────────────
const CODIGOS = [
  'sso_no_disponible', 'sso_proveedor_caido', 'sso_reintentar', 'sso_cancelado',
  'sso_identidad_no_verificada', 'sso_sin_email', 'sso_usuario_inactivo', 'sso_sin_puestos', 'sso_error',
];
const FRAGMENTO = {
  sso_no_disponible: 'no está disponible',
  sso_proveedor_caido: 'No pudimos contactar',
  sso_reintentar: 'venció o se interrumpió',
  sso_cancelado: 'Se canceló',
  sso_identidad_no_verificada: 'No se pudo confirmar el ingreso',
  sso_sin_email: 'email',
  sso_usuario_inactivo: 'dado de baja',
  sso_sin_puestos: 'puestos',
  sso_error: 'No se pudo completar el ingreso',
};

test('mensajeError: cada código de §4 → su texto, y todos recuerdan el acceso con contraseña (FR-006)', () => {
  const vistos = new Set();
  for (const c of CODIGOS) {
    const t = SsoUi.mensajeError(c);
    assert.ok(t.includes(FRAGMENTO[c]), `${c}: «${t}» debería contener «${FRAGMENTO[c]}»`);
    assert.match(t, /contraseña/i, `${c} no recuerda el acceso con contraseña`);
    vistos.add(t);
  }
  assert.strictEqual(vistos.size, CODIGOS.length, 'cada código tiene un texto propio');
});

test('mensajeError: identidad_no_verificada es neutro, no culpa a la identidad (D15, F10)', () => {
  const t = SsoUi.mensajeError('sso_identidad_no_verificada');
  assert.ok(!/no confirm[oó] tu identidad/i.test(t));
  assert.match(t, /administrador/i);
});

test('mensajeError: desconocido, vacío o con HTML → el genérico, que no contiene lo recibido', () => {
  const generico = SsoUi.mensajeError('sso_error');
  for (const raro of ['no_existe', '', undefined, null, 42, '<img src=x onerror=alert(1)>', 'sso_error<b>', '__proto__', 'constructor', 'toString', 'hasOwnProperty']) {
    const t = SsoUi.mensajeError(raro);
    assert.strictEqual(t, generico, `valor: ${String(raro)}`);
  }
  assert.ok(!generico.includes('<'));
  assert.ok(!SsoUi.mensajeError('<img src=x onerror=alert(1)>').includes('onerror'));
});

test('mensajeError: ningún texto lleva marca fija ni nombres de componentes internos (FR-013, FR-014)', () => {
  for (const c of CODIGOS) {
    assert.ok(!/elea|eleia|anythingllm|presenton|litellm|presidio/i.test(SsoUi.mensajeError(c)), c);
  }
});

// ── ofrecerCambioContrasena ──────────────────────────────────────────────────────────
test('ofrecerCambioContrasena: auth_method sso → false (FR-008, US1 AS5); password o ausente → true', () => {
  assert.strictEqual(SsoUi.ofrecerCambioContrasena({ auth_method: 'sso' }), false);
  assert.strictEqual(SsoUi.ofrecerCambioContrasena({ auth_method: 'password' }), true);
  assert.strictEqual(SsoUi.ofrecerCambioContrasena({ username: 'ana' }), true);
  assert.strictEqual(SsoUi.ofrecerCambioContrasena(null), true);
  assert.strictEqual(SsoUi.ofrecerCambioContrasena(undefined), true);
});

// ── Cableado estático de index.html (hub-sso.md §7 test 20) ──────────────────────────
const HTML = fs.readFileSync(path.join(__dirname, '../../public/index.html'), 'utf8');

function regionSso() {
  const ini = HTML.indexOf('// sso-056:inicio');
  const fin = HTML.indexOf('// sso-056:fin');
  assert.ok(ini !== -1 && fin > ini, 'index.html debe delimitar el cableado con // sso-056:inicio … // sso-056:fin');
  return HTML.slice(ini, fin);
}

test('index.html carga /sso-ui.js antes del script inline', () => {
  const src = HTML.indexOf('<script src="/sso-ui.js"></script>');
  assert.ok(src !== -1, 'falta <script src="/sso-ui.js">');
  const inline = HTML.indexOf('let currentUser = null;');
  assert.ok(inline !== -1);
  assert.ok(src < inline, '/sso-ui.js debe cargarse antes del script inline');
});

test('index.html usa las tres funciones y TEXTO_BOTON de SsoUi', () => {
  for (const nombre of ['destinoBoton', 'mensajeError', 'ofrecerCambioContrasena', 'TEXTO_BOTON']) {
    assert.ok(HTML.includes(`SsoUi.${nombre}`), `index.html no usa SsoUi.${nombre}`);
  }
});

test('index.html consulta /api/auth/sso/available y limpia ?sso_error= con history.replaceState', () => {
  assert.ok(HTML.includes('/api/auth/sso/available'));
  assert.ok(HTML.includes('sso_error'));
  assert.ok(HTML.includes('history.replaceState'));
});

test('el cableado SSO de index.html no escribe con innerHTML ni equivalentes (N5 del QA v2)', () => {
  const r = regionSso();
  for (const prohibido of ['innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write', 'innerText = `', 'eval(']) {
    assert.ok(!r.includes(prohibido), `la región SSO usa ${prohibido}`);
  }
  assert.ok(r.includes('createElement'), 'el botón se arma con createElement');
  assert.ok(r.includes('textContent'), 'los textos se escriben con textContent');
  assert.ok(r.includes('SsoUi.TEXTO_BOTON'));
  assert.ok(r.includes('SsoUi.mensajeError'));
});

test('ofrecerCambioContrasena gobierna el botón "Contraseña" y la apertura del modal', () => {
  const usos = HTML.split('SsoUi.ofrecerCambioContrasena').length - 1;
  assert.ok(usos >= 2, `se esperaban ≥ 2 usos (botón y modal), hay ${usos}`);
  assert.match(HTML, /id="btn-change-password"/, 'el botón necesita un id para poder ocultarse');
});
