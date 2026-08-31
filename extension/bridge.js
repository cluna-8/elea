/* bridge — content script en mundo ISOLATED.
 * Puente entre el content script MAIN (que hookea fetch pero no puede usar
 * chrome.*) y el service worker. Protocolo por window.postMessage:
 *   MAIN  -> {__sentinel:"req", id, kind, text, tool}      (pedido inspect/whoami)
 *   BRIDGE-> {__sentinel:"init",  __sentinel_nonce}             (anuncio de arranque; fija el nonce en MAIN)
 *   BRIDGE-> {__sentinel:"resp", id, resp, __sentinel_nonce}    (respuesta del SW)
 *   BRIDGE-> {__sentinel:"state", state, __sentinel_nonce}      (estado enabled/connected/user/team)
 *   MAIN  -> {__sentinel:"getState"}                        (pide estado)
 *
 * F-ext-1: cada mensaje bridge->MAIN lleva __sentinel_nonce (generado al arrancar).
 * MAIN fija el primer nonce visto y rechaza state/resp con nonce distinto → frena
 * la forja ingenua de la página. Es defense-in-depth, NO una garantía: la página
 * comparte el mundo MAIN y observa el handshake. Limitación conocida y documentada
 * (ver "Modelo de amenaza" en README.md).
 */
(() => {
  // Nonce por-sesión. crypto.randomUUID requiere contexto seguro (https o dev local);
  // los targets (ChatGPT/Claude.ai) lo son. Fallback defensivo por si no.
  const NONCE = (self.crypto && self.crypto.randomUUID)
    ? self.crypto.randomUUID()
    : ("n" + Math.random().toString(36).slice(2) + Date.now().toString(36));

  // Todo mensaje bridge->MAIN sale por acá, con el nonce adjunto.
  function post(msg) {
    window.postMessage(Object.assign({ __sentinel_nonce: NONCE }, msg), "*");
  }

  // Anunciar presencia a MAIN cuanto antes (síncrono, antes del await de storage)
  // para que MAIN fije este nonce como el legítimo.
  post({ __sentinel: "init" });

  // MAIN pide algo -> reenviar al SW -> devolver a MAIN
  //
  // F-ext-2: el listener oye el `window` que COMPARTIMOS con la página, así que
  // todo lo que llega es no-confiable. Tres guardas, en este orden:
  //   1. ev.source !== window  → descarta lo que venga de un iframe u otra ventana.
  //   2. allowlist de `kind`   → la página no puede disparar "whoami" y, con él,
  //      reescribir sentinel_connected/sentinel_user/sentinel_team en storage (background.js).
  //   3. NO se reenvía `key`   → el service worker la lee de storage; aceptarla por
  //      postMessage dejaba que la página autenticara con una key ajena.
  // Sigue sin ser inforjable (la página comparte el mundo MAIN y ve el handshake):
  // ver "Modelo de amenaza" en README.md. Cierra el deputy confundido, no el mundo MAIN.
  const KINDS_PERMITIDOS = new Set(["inspect"]);
  window.addEventListener("message", (ev) => {
    if (ev.source !== window) return;
    const d = ev.data;
    if (!d || d.__sentinel !== "req") return;
    if (!KINDS_PERMITIDOS.has(d.kind)) return;
    chrome.runtime.sendMessage(
      { kind: d.kind, text: d.text, tool: d.tool },
      (resp) => {
        const err = chrome.runtime.lastError;
        post({ __sentinel: "resp", id: d.id, resp: resp || { ok: false, error: err ? err.message : "sin respuesta" } });
      }
    );
  });

  // Empujar el estado (identidad + honestidad + marca) a MAIN.
  // NOTA 028: sólo se AMPLÍA el payload de `state` (proteccion + name). El handshake
  // de nonce, la allowlist de `kind` y el relay de `resp` NO se tocan: `proteccion` es
  // copy de alcance (no sensible) y no altera el gate (que sigue = connected).
  async function pushState() {
    const s = await chrome.storage.local.get(["sentinel_connected", "sentinel_user", "sentinel_team", "sentinel_key", "proteccion"]);
    let name = "";
    try { name = (chrome.runtime.getManifest().name) || ""; } catch (_) { name = ""; }
    post({
      __sentinel: "state",
      state: {
        connected: !!s.sentinel_connected && !!s.sentinel_key,   // hay key validada
        user: s.sentinel_user || null,
        team: s.sentinel_team || null,
        // US4: bloque de honestidad del server para el chip ámbar del panel (o null → fallback).
        proteccion: s.proteccion || null,
        // US3/white-label: el nombre lo pisa el render del partner; el MAIN no puede leer
        // chrome.runtime, así que el panel/overlay toman de acá la marca a mostrar.
        name: name,
      },
    });
  }

  window.addEventListener("message", (ev) => {
    if (ev.data && ev.data.__sentinel === "getState") pushState();
  });
  chrome.storage.onChanged.addListener(pushState);
  pushState();
})();
