/* Basa Guard — service worker (MV3).
 * Único que habla con el gateway de Basa (tiene host_permissions → sin CORS).
 * Guarda la virtual key en chrome.storage.local; el content script nunca la ve. */

// La URL del gateway vive en config.js — un solo lugar para todo el paquete.
importScripts("config.js");
const DEFAULT_GW = self.BASA_CONFIG.GATEWAY_URL;

async function cfg() {
  const s = await chrome.storage.local.get(["basa_key", "basa_gateway"]);
  return { key: s.basa_key || "", gw: s.basa_gateway || DEFAULT_GW };
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      const { key, gw } = await cfg();

      // Validar la key contra el gateway (login del popup / bootstrap del content script)
      if (msg.kind === "whoami") {
        const testKey = msg.key || key;
        if (!testKey) return sendResponse({ ok: false, error: "sin API key" });
        const r = await fetch(gw + "/whoami", { headers: { "X-Basa-Key": testKey } });
        const j = await r.json().catch(() => ({}));
        if (r.ok && j.ok) {
          await chrome.storage.local.set({ basa_connected: true, basa_user: j.user, basa_team: j.team });
          return sendResponse({ ok: true, user: j.user, team: j.team, key_label: j.key_label });
        }
        await chrome.storage.local.set({ basa_connected: false });
        return sendResponse({ ok: false, status: r.status, error: (j && j.error) || "no autorizado" });
      }

      // Enmascarar un prompt vía el gateway (masking + audit + monitor)
      if (msg.kind === "inspect") {
        if (!key) return sendResponse({ ok: false, error: "sin API key" });
        const r = await fetch(gw + "/inspect", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Basa-Key": key },
          body: JSON.stringify({ text: msg.text, tool: msg.tool }),
        });
        const j = await r.json().catch(() => ({}));
        if (r.ok && j.ok) {
          return sendResponse({ ok: true, masked: j.masked, replacements: j.replacements, entities: j.entities, user: j.user, team: j.team });
        }
        if (r.status === 401) await chrome.storage.local.set({ basa_connected: false });
        return sendResponse({ ok: false, status: r.status, error: (j && j.error) || "inspect falló" });
      }

      sendResponse({ ok: false, error: "kind desconocido" });
    } catch (e) {
      sendResponse({ ok: false, error: String(e) });
    }
  })();
  return true; // respuesta asíncrona
});
