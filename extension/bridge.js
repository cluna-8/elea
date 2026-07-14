/* Basa Guard — bridge (content script en mundo ISOLATED).
 * Puente entre el content script MAIN (que hookea fetch pero no puede usar
 * chrome.*) y el service worker. Protocolo por window.postMessage:
 *   MAIN  -> {__basa:"req", id, kind, text, tool}   (pedido inspect/whoami)
 *   BRIDGE-> {__basa:"resp", id, resp}              (respuesta del SW)
 *   BRIDGE-> {__basa:"state", state:{enabled,connected,user,team}}  (estado)
 *   MAIN  -> {__basa:"getState"}                    (pide estado)
 */
(() => {
  // MAIN pide algo -> reenviar al SW -> devolver a MAIN
  window.addEventListener("message", (ev) => {
    const d = ev.data;
    if (!d || d.__basa !== "req") return;
    chrome.runtime.sendMessage(
      { kind: d.kind, text: d.text, tool: d.tool, key: d.key },
      (resp) => {
        const err = chrome.runtime.lastError;
        window.postMessage(
          { __basa: "resp", id: d.id, resp: resp || { ok: false, error: err ? err.message : "sin respuesta" } },
          "*"
        );
      }
    );
  });

  // Empujar el estado (toggle + identidad) a MAIN
  async function pushState() {
    const s = await chrome.storage.local.get(["basa_enabled", "basa_connected", "basa_user", "basa_team", "basa_key"]);
    window.postMessage({
      __basa: "state",
      state: {
        enabled: s.basa_enabled !== false,               // default ON
        connected: !!s.basa_connected && !!s.basa_key,   // hay key validada
        user: s.basa_user || null,
        team: s.basa_team || null,
      },
    }, "*");
  }

  window.addEventListener("message", (ev) => {
    if (ev.data && ev.data.__basa === "getState") pushState();
  });
  chrome.storage.onChanged.addListener(pushState);
  pushState();
})();
