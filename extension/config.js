/* Basa Guard — configuración de despliegue.
 * ÚNICO lugar donde vive la URL del gateway: lo leen el service worker
 * (importScripts) y el popup (<script src>).
 *
 * Para apuntar la extensión a otro despliegue hay que tocar DOS cosas, y sólo dos:
 *   1. GATEWAY_URL acá abajo.
 *   2. El host correspondiente en "host_permissions" de manifest.json
 *      (MV3 bloquea el fetch del service worker a cualquier host no declarado).
 * No hay una tercera copia. Si aparece, es un bug.
 */
(function (root) {
  root.BASA_CONFIG = {
    // El gateway vive bajo /api/v1/gw en el backend.
    GATEWAY_URL: "http://localhost:8091/api/v1/gw",
  };
})(typeof self !== "undefined" ? self : window);
