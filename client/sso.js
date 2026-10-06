// Ingreso corporativo (SSO) del Hub — piezas puras del flujo del lado del servidor: almacén de
// flujos pendientes, límite de ritmo de `/sso/login`, comparación en tiempo constante y mapeo
// de errores de lista cerrada. Sin dependencias, sin estado de módulo (todo se crea con una
// fábrica, así cada instancia del Hub y cada test tienen el suyo) y sin textos de marca.
//
// Contrato: specs/056-sso-entra-id-hub/contracts/hub-sso.md §2, §3 y §4; modelo de datos en
// specs/056-sso-entra-id-hub/data-model.md (Flujo SSO pendiente, Contador de ritmo).
const crypto = require('crypto');

const SSO_LOGIN_POR_MIN = 120; // research D11: tope global por proceso de `/sso/login`
const VENTANA_MS = 60 * 1000;
const TTL_PENDIENTE_MS = 10 * 60 * 1000; // mismo TTL que la cookie de estado del backend
const MAX_PENDIENTES = 5000; // research D11: lleno → se rechaza al que llega

// ── Almacén de flujos pendientes (sid → flujo) ────────────────────────────────────────────
// Un solo uso (`tomar` borra siempre), vencimiento a los 10 min y, lleno, rechaza al NUEVO sin
// expulsar a ningún ingreso en curso (F5, FR-016).
function crearAlmacenPendientes({ ahora = Date.now, max = MAX_PENDIENTES, ttlMs = TTL_PENDIENTE_MS } = {}) {
  const mapa = new Map();

  function barrerVencidos() {
    const t = ahora();
    for (const [sid, p] of mapa) {
      if (p.venceEn <= t) mapa.delete(sid);
    }
  }

  return {
    // `true` si quedó guardado; `false` si el almacén está lleno aun después de barrer.
    guardar(sid, { stateCookie, state, atadura = null }) {
      if (!mapa.has(sid) && mapa.size >= max) {
        barrerVencidos();
        if (mapa.size >= max) return false;
      }
      mapa.set(sid, { stateCookie, state, atadura, venceEn: ahora() + ttlMs });
      return true;
    },
    // Devuelve el flujo y lo borra; `null` si no hay, o si ya venció (también se borra).
    tomar(sid) {
      if (typeof sid !== 'string' || !sid) return null;
      const p = mapa.get(sid);
      if (!p) return null;
      mapa.delete(sid);
      if (p.venceEn <= ahora()) return null;
      return { stateCookie: p.stateCookie, state: p.state, atadura: p.atadura, venceEn: p.venceEn };
    },
    size: () => mapa.size,
  };
}

// ── Límite de ritmo global (ventana fija de 60 s) ─────────────────────────────────────────
// Un pedido rechazado no cuenta ni extiende la ventana.
function crearLimiteRitmo({ ahora = Date.now, porMin = SSO_LOGIN_POR_MIN, ventanaMs = VENTANA_MS } = {}) {
  let inicio = null;
  let pedidos = 0;
  return {
    permitir() {
      const t = ahora();
      if (inicio === null || t - inicio >= ventanaMs) {
        inicio = t;
        pedidos = 0;
      }
      if (pedidos >= porMin) return false;
      pedidos += 1;
      return true;
    },
  };
}

// ── Comparación en tiempo constante ───────────────────────────────────────────────────────
// Distinto largo (en bytes) = no coincide, sin lanzar. Vacío nunca coincide.
function iguales(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || !a || !b) return false;
  const x = Buffer.from(a, 'utf8');
  const y = Buffer.from(b, 'utf8');
  if (x.length !== y.length) return false;
  return crypto.timingSafeEqual(x, y);
}

// ── Mapeo status/detail → código de error (lista cerrada, hub-sso.md §4) ───────────────────
// El código sale SOLO del status y del prefijo del `detail`; el `detail` nunca se copia.
const CODIGOS_ERROR = [
  'sso_no_disponible',
  'sso_proveedor_caido',
  'sso_reintentar',
  'sso_cancelado',
  'sso_identidad_no_verificada',
  'sso_sin_email',
  'sso_usuario_inactivo',
  'sso_sin_puestos',
  'sso_error',
];

function codigoError({ status, detail, red } = {}) {
  if (red) return 'sso_proveedor_caido';
  const d = typeof detail === 'string' ? detail : '';
  const empieza = (p) => d.startsWith(p);
  switch (status) {
    case 400:
      if (empieza('sso_proveedor_desconocido')) return 'sso_no_disponible';
      if (empieza('sso_state_')) return 'sso_reintentar';
      if (empieza('sso_code_ausente')) return 'sso_cancelado';
      return 'sso_error';
    case 401:
      if (empieza('sso_identidad_no_verificada')) return 'sso_identidad_no_verificada';
      if (empieza('sso_identidad_sin_email')) return 'sso_sin_email';
      return 'sso_error';
    case 402:
      return empieza('license_seat_limit_exceeded') ? 'sso_sin_puestos' : 'sso_error';
    case 403:
      if (empieza('sso_no_licenciado')) return 'sso_no_disponible';
      if (empieza('sso_usuario_inactivo')) return 'sso_usuario_inactivo';
      if (empieza('license_creation_blocked')) return 'sso_sin_puestos';
      return 'sso_error';
    case 404:
      return empieza('sso_no_configurado') ? 'sso_no_disponible' : 'sso_error';
    case 500:
      return empieza('sso_redirect_uri_no_configurado') ? 'sso_no_disponible' : 'sso_error';
    case 502:
      return empieza('sso_idp_inaccesible') ? 'sso_proveedor_caido' : 'sso_error';
    default:
      return 'sso_error';
  }
}

module.exports = {
  SSO_LOGIN_POR_MIN,
  VENTANA_MS,
  TTL_PENDIENTE_MS,
  MAX_PENDIENTES,
  CODIGOS_ERROR,
  crearAlmacenPendientes,
  crearLimiteRitmo,
  iguales,
  codigoError,
};
