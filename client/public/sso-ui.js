// Pantalla de ingreso corporativo (SSO) — lógica pura, sin DOM y sin dependencias, para poder
// probarla con `node --test` (research D13). `index.html` solo la cablea. TODO texto visible
// nuevo del ingreso corporativo vive acá (la etiqueta del botón incluida), sin marca fija: la
// marca sale de `/api/branding`.
//
// Contrato: specs/056-sso-entra-id-hub/contracts/hub-sso.md §4 y §6.
(function (raiz, fabrica) {
  const api = fabrica();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (raiz) raiz.SsoUi = api;
}(typeof window !== 'undefined' ? window : null, function () {
  const TEXTO_BOTON = 'Ingresar con Microsoft';

  // Sufijo común (FR-006): todo fallo del ingreso corporativo recuerda que el acceso con
  // usuario y contraseña sigue disponible.
  const SUFIJO = ' Podés ingresar con tu usuario y contraseña.';

  // Lista cerrada de códigos (hub-sso.md §4). El valor de `?sso_error=` NUNCA se pinta: solo
  // sirve de clave de esta tabla.
  const TEXTOS = Object.freeze({
    sso_no_disponible: 'El ingreso con Microsoft no está disponible en esta instalación.',
    sso_proveedor_caido: 'No pudimos contactar a Microsoft. Probá de nuevo en unos minutos.',
    sso_reintentar: 'El ingreso venció o se interrumpió. Volvé a intentarlo.',
    sso_cancelado: 'Se canceló el ingreso con Microsoft.',
    sso_identidad_no_verificada: 'No se pudo confirmar el ingreso con Microsoft. Si se repite, avisá al administrador.',
    sso_sin_email: 'Tu cuenta corporativa no tiene un email asociado. Pedile a tu área de sistemas que lo complete.',
    sso_usuario_inactivo: 'Tu usuario está dado de baja. Consultá con el administrador.',
    sso_sin_puestos: 'No quedan puestos disponibles para usuarios nuevos. Consultá con el administrador.',
    sso_error: 'No se pudo completar el ingreso con Microsoft.',
  });

  function mensajeError(codigo) {
    const clave = typeof codigo === 'string' && Object.prototype.hasOwnProperty.call(TEXTOS, codigo)
      ? codigo
      : 'sso_error';
    return TEXTOS[clave] + SUFIJO;
  }

  // Origen bien formado (N5 del QA v2): `new URL(x)` no lanza, protocolo http(s) y
  // `new URL(x).origin === x` (descarta credenciales, ruta, query, fragmento, barra final y `\`).
  // Esa regla sola deja pasar caracteres que el parser de URL acepta en el host (comillas,
  // apóstrofos, `=`, `;`…), así que se suma una lista blanca estricta de lo que puede llevar un
  // origen: host en minúsculas (nombre o IPv6 entre corchetes) y puerto numérico.
  const FORMA_ORIGEN = /^https?:\/\/(\[[0-9a-f:.]+\]|[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)(?::[0-9]{1,5})?$/;

  function origenBienFormado(x) {
    if (typeof x !== 'string' || !FORMA_ORIGEN.test(x)) return false;
    try {
      const u = new URL(x);
      return (u.protocol === 'http:' || u.protocol === 'https:') && u.origin === x;
    } catch (e) {
      return false;
    }
  }

  // Destino del botón, o `null` si no hay que dibujarlo (fail-closed: FR-001, FR-015, F4).
  function destinoBoton(disponible, origenActual) {
    if (!disponible || typeof disponible !== 'object') return null;
    if (disponible.enabled !== true) return null;
    const origen = disponible.return_origin;
    if (!origenBienFormado(origen)) return null;
    return origen === origenActual ? '/sso/login' : `${origen}/sso/login`;
  }

  // FR-008: quien entró por el directorio no gestiona su contraseña en el Hub.
  function ofrecerCambioContrasena(usuario) {
    return !(usuario && usuario.auth_method === 'sso');
  }

  return { TEXTO_BOTON, destinoBoton, mensajeError, ofrecerCambioContrasena };
}));
