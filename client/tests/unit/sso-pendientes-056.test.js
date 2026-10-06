// Spec 056 (T010): unidades de `client/sso.js` — almacén de flujos pendientes (un solo uso,
// vencimiento, rechazo del nuevo cuando está lleno), límite de ritmo de `/sso/login`,
// comparación en tiempo constante y mapeo status/detail → código de error de lista cerrada.
// Contrato: specs/056-sso-entra-id-hub/contracts/hub-sso.md §2, §3 y §4.
const test = require('node:test');
const assert = require('node:assert');
const sso = require('../../sso');

function reloj(inicio = 1_000_000) {
  const r = { t: inicio, ahora: () => r.t, avanzar: (ms) => { r.t += ms; } };
  return r;
}

const flujo = (extra = {}) => ({ stateCookie: 'jwt-estado', state: 'st-1', atadura: null, ...extra });

test('constantes del contrato: 120/min, 10 min de vida, tope de 5000 pendientes', () => {
  assert.strictEqual(sso.SSO_LOGIN_POR_MIN, 120);
  assert.strictEqual(sso.TTL_PENDIENTE_MS, 10 * 60 * 1000);
  assert.strictEqual(sso.MAX_PENDIENTES, 5000);
});

// ── Almacén de pendientes ────────────────────────────────────────────────────────────
test('guarda un pendiente por sid (con atadura opcional) y `tomar` lo devuelve entero', () => {
  const r = reloj();
  const a = sso.crearAlmacenPendientes({ ahora: r.ahora });
  assert.strictEqual(a.guardar('sid-a', flujo({ atadura: 'ata-1' })), true);
  assert.strictEqual(a.guardar('sid-b', flujo()), true);
  const p = a.tomar('sid-a');
  assert.strictEqual(p.stateCookie, 'jwt-estado');
  assert.strictEqual(p.state, 'st-1');
  assert.strictEqual(p.atadura, 'ata-1');
  assert.strictEqual(a.tomar('sid-b').atadura, null);
});

test('un solo uso: `tomar` borra siempre, el segundo `tomar` no encuentra nada', () => {
  const a = sso.crearAlmacenPendientes({ ahora: reloj().ahora });
  a.guardar('sid-a', flujo());
  assert.ok(a.tomar('sid-a'));
  assert.strictEqual(a.tomar('sid-a'), null);
  assert.strictEqual(a.size(), 0);
});

test('`tomar` de un sid desconocido o vacío devuelve null sin lanzar', () => {
  const a = sso.crearAlmacenPendientes({ ahora: reloj().ahora });
  assert.strictEqual(a.tomar('nunca-guardado'), null);
  assert.strictEqual(a.tomar(undefined), null);
  assert.strictEqual(a.tomar(''), null);
});

test('un nuevo flujo del mismo sid reemplaza al anterior', () => {
  const a = sso.crearAlmacenPendientes({ ahora: reloj().ahora });
  a.guardar('sid-a', flujo({ state: 'viejo' }));
  a.guardar('sid-a', flujo({ state: 'nuevo' }));
  assert.strictEqual(a.size(), 1);
  assert.strictEqual(a.tomar('sid-a').state, 'nuevo');
});

test('vence a los 10 minutos (reloj inyectado): un vencido es como no tener pendiente y se borra', () => {
  const r = reloj();
  const a = sso.crearAlmacenPendientes({ ahora: r.ahora });
  a.guardar('sid-a', flujo());
  a.guardar('sid-b', flujo());
  r.avanzar(sso.TTL_PENDIENTE_MS - 1);
  assert.ok(a.tomar('sid-a'), 'a 1 ms de vencer todavía vale');
  r.avanzar(1);
  assert.strictEqual(a.tomar('sid-b'), null, 'a los 10 min exactos ya venció');
  assert.strictEqual(a.size(), 0, 'el vencido se borró al intentar tomarlo');
});

test('almacén lleno: barre los vencidos y entra el nuevo', () => {
  const r = reloj();
  const a = sso.crearAlmacenPendientes({ ahora: r.ahora, max: 3 });
  ['a', 'b', 'c'].forEach((s) => a.guardar(s, flujo()));
  r.avanzar(sso.TTL_PENDIENTE_MS + 1);
  assert.strictEqual(a.guardar('d', flujo()), true);
  assert.strictEqual(a.size(), 1);
});

test('almacén lleno sin vencidos: rechaza al NUEVO y ningún pendiente en curso se expulsa (F5, FR-016)', () => {
  const r = reloj();
  const a = sso.crearAlmacenPendientes({ ahora: r.ahora, max: 3 });
  ['a', 'b', 'c'].forEach((s) => assert.strictEqual(a.guardar(s, flujo({ state: `st-${s}` })), true));
  assert.strictEqual(a.guardar('d', flujo()), false, 'el que llega se rechaza');
  assert.strictEqual(a.size(), 3);
  ['a', 'b', 'c'].forEach((s) => assert.strictEqual(a.tomar(s).state, `st-${s}`, `${s} sigue consumible`));
  assert.strictEqual(a.tomar('d'), null);
});

test('almacén lleno: reemplazar el flujo de un sid que YA está no cuenta como uno nuevo', () => {
  const a = sso.crearAlmacenPendientes({ ahora: reloj().ahora, max: 2 });
  a.guardar('a', flujo({ state: 'v1' }));
  a.guardar('b', flujo());
  assert.strictEqual(a.guardar('a', flujo({ state: 'v2' })), true);
  assert.strictEqual(a.tomar('a').state, 'v2');
});

// ── Límite de ritmo ──────────────────────────────────────────────────────────────────
test('límite de ritmo: acepta SSO_LOGIN_POR_MIN por ventana y rechaza el siguiente', () => {
  const r = reloj();
  const l = sso.crearLimiteRitmo({ ahora: r.ahora });
  for (let i = 0; i < sso.SSO_LOGIN_POR_MIN; i += 1) assert.strictEqual(l.permitir(), true, `pedido ${i + 1}`);
  assert.strictEqual(l.permitir(), false);
  assert.strictEqual(l.permitir(), false);
});

test('límite de ritmo: la ventana siguiente (60 s) vuelve a aceptar', () => {
  const r = reloj();
  const l = sso.crearLimiteRitmo({ ahora: r.ahora, porMin: 2 });
  assert.strictEqual(l.permitir(), true);
  assert.strictEqual(l.permitir(), true);
  assert.strictEqual(l.permitir(), false);
  r.avanzar(59_999);
  assert.strictEqual(l.permitir(), false, 'dentro de la misma ventana sigue rechazando');
  r.avanzar(1);
  assert.strictEqual(l.permitir(), true, 'a los 60 s abre otra ventana');
  assert.strictEqual(l.permitir(), true);
  assert.strictEqual(l.permitir(), false);
});

test('los pedidos rechazados no extienden la ventana', () => {
  const r = reloj();
  const l = sso.crearLimiteRitmo({ ahora: r.ahora, porMin: 1 });
  assert.strictEqual(l.permitir(), true);
  r.avanzar(30_000);
  assert.strictEqual(l.permitir(), false);
  r.avanzar(30_000);
  assert.strictEqual(l.permitir(), true);
});

// ── Comparación en tiempo constante ──────────────────────────────────────────────────
test('`iguales`: coincide solo con el mismo valor; largos distintos no coinciden y no lanzan', () => {
  assert.strictEqual(sso.iguales('abc123', 'abc123'), true);
  assert.strictEqual(sso.iguales('abc123', 'abc124'), false);
  assert.strictEqual(sso.iguales('abc', 'abc123'), false);
  assert.strictEqual(sso.iguales('abc123', 'abc'), false);
  assert.strictEqual(sso.iguales('', ''), false, 'vacío contra vacío no es una coincidencia válida');
  assert.strictEqual(sso.iguales(undefined, 'abc'), false);
  assert.strictEqual(sso.iguales('abc', null), false);
  assert.strictEqual(sso.iguales(123, 123), false, 'solo strings');
});

test('`iguales` compara bytes, no caracteres: mismo largo en caracteres y distinto en bytes no lanza', () => {
  assert.strictEqual(sso.iguales('ñ', 'n'), false);
  assert.strictEqual(sso.iguales('ñ', 'ñ'), true);
});

// ── Mapeo status/detail → código (hub-sso.md §4) ─────────────────────────────────────
const casos = [
  // sso_no_disponible
  [{ status: 403, detail: 'sso_no_licenciado: el acceso por SSO no está habilitado en esta licencia.' }, 'sso_no_disponible'],
  [{ status: 404, detail: 'sso_no_configurado: …' }, 'sso_no_disponible'],
  [{ status: 500, detail: 'sso_redirect_uri_no_configurado: …' }, 'sso_no_disponible'],
  [{ status: 400, detail: 'sso_proveedor_desconocido: …' }, 'sso_no_disponible'],
  // sso_proveedor_caido
  [{ status: 502, detail: 'sso_idp_inaccesible: no se pudo iniciar el flujo con el proveedor.' }, 'sso_proveedor_caido'],
  [{ red: true }, 'sso_proveedor_caido'],
  // sso_reintentar
  [{ status: 400, detail: 'sso_state_ausente' }, 'sso_reintentar'],
  [{ status: 400, detail: 'sso_state_invalido' }, 'sso_reintentar'],
  // sso_cancelado
  [{ status: 400, detail: 'sso_code_ausente' }, 'sso_cancelado'],
  // sso_identidad_no_verificada
  [{ status: 401, detail: 'sso_identidad_no_verificada' }, 'sso_identidad_no_verificada'],
  // sso_sin_email
  [{ status: 401, detail: 'sso_identidad_sin_email' }, 'sso_sin_email'],
  // sso_usuario_inactivo (403 con prefijo; se distingue del 403 de licencia)
  [{ status: 403, detail: 'sso_usuario_inactivo: tu usuario está dado de baja' }, 'sso_usuario_inactivo'],
  // sso_sin_puestos
  [{ status: 402, detail: 'license_seat_limit_exceeded: 10/10 seats' }, 'sso_sin_puestos'],
  [{ status: 403, detail: 'license_creation_blocked: licencia en estado expired' }, 'sso_sin_puestos'],
  // sso_error (todo lo demás)
  [{ status: 500, detail: 'algo_inesperado' }, 'sso_error'],
  [{ status: 418, detail: '' }, 'sso_error'],
  [{ status: 403, detail: 'otra_cosa' }, 'sso_error'],
  [{ status: 401, detail: 'otro_401' }, 'sso_error'],
  [{ status: 400, detail: 'sso_algo_nuevo' }, 'sso_error'],
  [{ status: 500 }, 'sso_error'],
  [{ status: 400, detail: { x: 1 } }, 'sso_error'],
  [{}, 'sso_error'],
];

for (const [entrada, esperado] of casos) {
  test(`codigoError ${JSON.stringify(entrada)} → ${esperado}`, () => {
    assert.strictEqual(sso.codigoError(entrada), esperado);
  });
}

test('el código de error nunca copia el detail del backend', () => {
  const c = sso.codigoError({ status: 500, detail: 'secreto-que-no-debe-salir' });
  assert.ok(!c.includes('secreto'));
});

test('la lista cerrada de códigos es exactamente la de §4', () => {
  assert.deepStrictEqual([...sso.CODIGOS_ERROR].sort(), [
    'sso_cancelado', 'sso_error', 'sso_identidad_no_verificada', 'sso_no_disponible',
    'sso_proveedor_caido', 'sso_reintentar', 'sso_sin_email', 'sso_sin_puestos', 'sso_usuario_inactivo',
  ]);
});
