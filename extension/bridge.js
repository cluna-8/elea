/* Basa Guard — bridge (content script en mundo ISOLATED).
 * Puente entre el content script MAIN (que hookea fetch pero no puede usar
 * chrome.*) y el service worker. Protocolo por window.postMessage:
 *   MAIN  -> {__basa:"req", id, kind, text, tool}      (pedido inspect/whoami)
 *   BRIDGE-> {__basa:"init",  __basa_nonce}             (anuncio de arranque; fija el nonce en MAIN)
 *   BRIDGE-> {__basa:"resp", id, resp, __basa_nonce}    (respuesta del SW)
 *   BRIDGE-> {__basa:"state", state, __basa_nonce}      (estado enabled/connected/user/team)
 *   MAIN  -> {__basa:"getState"}                        (pide estado)
 *
 * F-ext-1: cada mensaje bridge->MAIN lleva __basa_nonce (generado al arrancar).
 * MAIN fija el primer nonce visto y rechaza state/resp con nonce distinto → frena
 * la forja ingenua de la página. Es defense-in-depth, NO una garantía: la página
 * comparte el mundo MAIN y observa el handshake. Limitación conocida y documentada
 * (ver "Modelo de amenaza" en README.md).
 */
(() => {
  // Nonce por-sesión. crypto.randomUUID requiere secure context (https/localhost);
  // los targets (ChatGPT/Claude.ai/gateway local) lo son. Fallback defensivo por si no.
  const NONCE = (self.crypto && self.crypto.randomUUID)
    ? self.crypto.randomUUID()
    : ("n" + Math.random().toString(36).slice(2) + Date.now().toString(36));

  // Todo mensaje bridge->MAIN sale por acá, con el nonce adjunto.
  function post(msg) {
    window.postMessage(Object.assign({ __basa_nonce: NONCE }, msg), "*");
  }

  // Anunciar presencia a MAIN cuanto antes (síncrono, antes del await de storage)
  // para que MAIN fije este nonce como el legítimo.
  post({ __basa: "init" });

  // MAIN pide algo -> reenviar al SW -> devolver a MAIN
  window.addEventListener("message", (ev) => {
    const d = ev.data;
    if (!d || d.__basa !== "req") return;
    chrome.runtime.sendMessage(
      { kind: d.kind, text: d.text, tool: d.tool, key: d.key },
      (resp) => {
        const err = chrome.runtime.lastError;
        post({ __basa: "resp", id: d.id, resp: resp || { ok: false, error: err ? err.message : "sin respuesta" } });
      }
    );
  });

  // Empujar el estado (toggle + identidad) a MAIN
  async function pushState() {
    const s = await chrome.storage.local.get(["basa_enabled", "basa_connected", "basa_user", "basa_team", "basa_key"]);
    post({
      __basa: "state",
      state: {
        enabled: s.basa_enabled !== false,               // default ON
        connected: !!s.basa_connected && !!s.basa_key,   // hay key validada
        user: s.basa_user || null,
        team: s.basa_team || null,
      },
    });
  }

  window.addEventListener("message", (ev) => {
    if (ev.data && ev.data.__basa === "getState") pushState();
  });
  chrome.storage.onChanged.addListener(pushState);
  pushState();
})();
