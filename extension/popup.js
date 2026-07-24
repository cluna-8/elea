/* Basa Guard — popup.
 *
 * Dos vistas: principal (conectar / desconectar / configurar) y configuración
 * (API key + gateway). La key y el gateway son un setup de UNA vez: se guardan
 * y no se vuelven a mostrar. Esto es un login, no un gestor de API keys.
 *
 * No hay toggle de protección: el enmascarado no es desactivable por el usuario.
 */
const $ = (id) => document.getElementById(id);
const DEFAULT_GW = window.BASA_CONFIG.GATEWAY_URL;

let cfg = {};   // último snapshot de storage

function render(s) {
  cfg = s;
  const conectado = !!(s.basa_connected && s.basa_key);
  const st = $("status");
  if (conectado) {
    st.className = "status on";
    st.innerHTML = "🟢 Conectado como <b>" + (s.basa_user || "—") + "</b> · equipo <b>" + (s.basa_team || "—") + "</b>";
  } else {
    st.className = "status off";
    st.textContent = s.basa_key
      ? "Desconectado — verificá tu conexión con el gateway."
      : "Desconectado — configurá tu API key para usar la IA.";
  }
  $("disconnect").disabled = !s.basa_key;
  $("connect").disabled = conectado;
}

function mostrarConfig(mostrar, aviso) {
  $("view-config").classList.toggle("hidden", !mostrar);
  $("view-main").classList.toggle("hidden", mostrar);
  if (mostrar) {
    // La key NUNCA se re-inyecta en el input: si ya hay una guardada, el
    // placeholder lo dice y escribir una nueva es lo único que la reemplaza.
    $("key").value = "";
    $("key").placeholder = cfg.basa_key ? "•••••••••• (guardada — escribí una nueva para cambiarla)" : "sk-basa-...";
    $("gw").value = cfg.basa_gateway || DEFAULT_GW;
    if (aviso) { $("status").className = "status off"; $("status").textContent = aviso; }
  }
}

async function load() {
  const s = await chrome.storage.local.get(
    ["basa_key", "basa_gateway", "basa_connected", "basa_user", "basa_team"]);
  render(s);
}

/** Valida contra el gateway. `key` opcional: sin ella el service worker usa la guardada. */
function validar(key, alOk, alError) {
  $("status").className = "status off";
  $("status").textContent = "Validando…";
  const msg = key ? { kind: "whoami", key } : { kind: "whoami" };
  chrome.runtime.sendMessage(msg, (resp) => {
    if (resp && resp.ok) return alOk(resp);
    $("status").className = "status off";
    $("status").textContent = "✗ " + ((resp && resp.error) || "no autorizado");
    if (alError) alError(resp);
  });
}

// Conectar = revalidar con la key ya guardada. Sin key configurada, manda a config.
$("connect").addEventListener("click", () => {
  if (!cfg.basa_key) return mostrarConfig(true, "Configurá tu API key para conectarte.");
  validar(null, () => load());
});

$("disconnect").addEventListener("click", async () => {
  await chrome.storage.local.set({ basa_connected: false, basa_user: null, basa_team: null });
  await chrome.storage.local.remove("basa_key");
  mostrarConfig(false);
  load();
});

$("open-config").addEventListener("click", () => mostrarConfig(true));
$("cancel").addEventListener("click", () => { mostrarConfig(false); load(); });

$("save").addEventListener("click", async () => {
  const escrita = $("key").value.trim();
  const key = escrita || cfg.basa_key;           // sin escribir nada, se reusa la guardada
  const gw = $("gw").value.trim() || DEFAULT_GW;
  if (!key) return;
  // El gateway sí se persiste antes: el service worker lo lee de storage para
  // hacer el whoami. La KEY no — sólo viaja en el mensaje, y se guarda si valida.
  await chrome.storage.local.set({ basa_gateway: gw });
  validar(key, async () => {
    // El service worker ya escribió basa_connected/user/team al validar; acá sólo
    // falta persistir la key, que deliberadamente no se guardó antes.
    await chrome.storage.local.set({ basa_key: key });
    mostrarConfig(false);
    load();
  });
  // si falla, la vista de config sigue abierta y no queda key inválida en disco
});

// Versión: fuente única = manifest.json.
$("ver").textContent = "v" + chrome.runtime.getManifest().version;

load();
