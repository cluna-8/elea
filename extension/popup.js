/* Basa Guard — popup logic */
const $ = (id) => document.getElementById(id);
const DEFAULT_GW = "http://localhost:8091/api/v1/gw";

function render(s) {
  const st = $("status");
  if (s.basa_connected && s.basa_key) {
    st.className = "status on";
    st.innerHTML = "🟢 Conectado como <b>" + (s.basa_user || "—") + "</b> · equipo <b>" + (s.basa_team || "—") + "</b>";
  } else {
    st.className = "status off";
    st.textContent = "Desconectado — pegá tu API key para usar la IA.";
  }
  $("enabled").checked = s.basa_enabled !== false;
  if (s.basa_key) $("key").value = s.basa_key;
  $("gw").value = s.basa_gateway || DEFAULT_GW;
}

async function load() {
  const s = await chrome.storage.local.get(
    ["basa_key", "basa_gateway", "basa_enabled", "basa_connected", "basa_user", "basa_team"]);
  render(s);
}

$("connect").addEventListener("click", async () => {
  const key = $("key").value.trim();
  const gw = $("gw").value.trim() || DEFAULT_GW;
  if (!key) return;
  await chrome.storage.local.set({ basa_key: key, basa_gateway: gw });
  $("status").className = "status off";
  $("status").textContent = "Validando…";
  chrome.runtime.sendMessage({ kind: "whoami", key }, async (resp) => {
    if (resp && resp.ok) {
      await chrome.storage.local.set({ basa_connected: true, basa_user: resp.user, basa_team: resp.team });
    } else {
      await chrome.storage.local.set({ basa_connected: false });
      $("status").className = "status off";
      $("status").textContent = "✗ " + ((resp && resp.error) || "no autorizado");
    }
    load();
  });
});

$("disconnect").addEventListener("click", async () => {
  await chrome.storage.local.set({ basa_connected: false, basa_user: null, basa_team: null });
  await chrome.storage.local.remove("basa_key");
  $("key").value = "";
  load();
});

$("enabled").addEventListener("change", async (e) => {
  await chrome.storage.local.set({ basa_enabled: e.target.checked });
});

load();
