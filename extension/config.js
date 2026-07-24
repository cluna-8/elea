/* Configuración de despliegue.
 * ÚNICO lugar donde vive el default de la URL del gateway y la validación de URL:
 * lo leen el service worker (importScripts) y el popup (<script src>).
 *
 * La dirección del gateway la ingresa el USUARIO (editable, agnóstica al despliegue).
 * El default es vacío a propósito: el paquete white-label no hornea ninguna URL.
 * El acceso al host se concede en tiempo de ejecución vía chrome.permissions.request
 * (el service worker, que tiene el permiso, hace el fetch → sin CORS). Ya NO hay que
 * declarar el host en el manifest: por eso no existe la vieja "segunda copia" de la URL.
 */
(function (root) {
  // Validación de la URL del gateway (FR-010): una dirección remota debe ser https
  // (la key por usuario viajaría en claro sobre http); http se permite sólo en local.
  // Devuelve { ok, origin, url } o { ok:false, error }. Pura → testeable con node.
  function validarGatewayUrl(raw) {
    const s = (raw || "").trim();
    if (!s) return { ok: false, error: "Ingresá la dirección del gateway." };
    let u;
    try { u = new URL(s); } catch (_) { return { ok: false, error: "La dirección no es una URL válida." }; }
    const proto = u.protocol;
    if (proto !== "https:" && proto !== "http:") {
      return { ok: false, error: "La dirección debe empezar con https:// (http:// sólo en local)." };
    }
    const host = u.hostname;
    const esLocal = host === "localhost" || host === "127.0.0.1" || host === "[::1]" || host === "::1";
    if (proto === "http:" && !esLocal) {
      return { ok: false, error: "Una dirección remota debe usar https:// — sobre http tu key viajaría en claro." };
    }
    return { ok: true, origin: u.origin, url: u.href.replace(/\/+$/, "") };
  }

  root.BASA_CONFIG = {
    // Sin URL horneada: el usuario la ingresa en el popup. Un partner puede pre-cargar
    // aquí un default editable, pero NUNCA una dirección de desarrollo fija.
    GATEWAY_URL: "",
    validarGatewayUrl: validarGatewayUrl,
  };
})(typeof self !== "undefined" ? self : window);
