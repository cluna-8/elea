/* Basa Guard — popup logic */
const $ = (id) => document.getElementById(id);
const DEFAULT_GW = window.BASA_CONFIG.GATEWAY_URL;

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
  // La key NO se vuelve a escribir en el input: se pone una vez y no se muestra
  // más. Esto es un login, no un gestor de API keys (issue #44).
  $("key").value = "";
  $("key").placeholder = (s.basa_connected && s.basa_key) ? "•••••••••• (guardada)" : "sk-basa-...";
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
  // El gateway sí se persiste antes: el service worker lo lee de storage para
  // hacer el whoami. La KEY no — sólo viaja en el mensaje, y se guarda si valida.
  await chrome.storage.local.set({ basa_gateway: gw });
  $("status").className = "status off";
  $("status").textContent = "Validando…";
  chrome.runtime.sendMessage({ kind: "whoami", key }, async (resp) => {
    if (!resp || !resp.ok) {
      $("status").className = "status off";
      $("status").textContent = "✗ " + ((resp && resp.error) || "no autorizado");
      return;   // sin key en disco: una key inválida no deja rastro
    }
    // El service worker ya escribió basa_connected/user/team al validar; acá sólo
    // falta persistir la key, que deliberadamente no se guardó antes.
    await chrome.storage.local.set({ basa_key: key });
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

// Versión: fuente única = manifest.json.
$("ver").textContent = "v" + chrome.runtime.getManifest().version;

load();
