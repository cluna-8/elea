/* Popup — login (conectar / desconectar / configurar).
 *
 * La key y el gateway son un setup de UNA vez: se guardan y no se vuelven a mostrar.
 * Esto es un login, no un gestor de API keys. No hay toggle de protección: el
 * enmascarado no es desactivable por el usuario.
 *
 * DUEÑO ÚNICO del estado = el service worker (US6/FR-025). Este popup NO escribe
 * `basa_connected` ni la key: sólo OBSERVA storage (chrome.storage.onChanged) y le
 * pide al SW conectar/desconectar. El único write propio es `basa_gateway` (config,
 * no estado de sesión), y lo hace en el gesto de guardar.
 */
const $ = (id) => document.getElementById(id);
const DEFAULT_GW = window.BASA_CONFIG.GATEWAY_URL;
const esc = (s) => String(s).replace(/</g, "&lt;");

let cfg = {};   // último snapshot de storage

function setStatus(cls, text) { const st = $("status"); st.className = "status " + cls; st.textContent = text; }

function render(s) {
  cfg = s;
  const estado = s.sesion_estado || (s.basa_connected && s.basa_key ? "conectado" : "desconectado");
  const conectado = estado === "conectado" && !!s.basa_key;
  const st = $("status");
  if (conectado) {
    st.className = "status on";
    st.innerHTML = "Conectado como <b>" + esc(s.basa_user || "—") + "</b> · equipo <b>" + esc(s.basa_team || "—") + "</b>";
  } else {
    if (estado === "no_verificado") {
      setStatus("warn", "Sin conexión con el gateway — se reintenta solo. Tu key se conserva.");
    } else { // desconectado
      if (s.sesion_motivo === "plaza_revocada") setStatus("off", "Tu plaza ya no está activa. Consulta con tu administrador.");
      else if (s.sesion_motivo === "key_invalida") setStatus("off", "Tu API key no es válida. Configura una nueva.");
      else setStatus("off", s.basa_key ? "Desconectado — verifica tu conexión con el gateway." : "Desconectado — configura tu API key para usar la IA.");
    }
  }
  $("disconnect").disabled = !s.basa_key;
  $("connect").disabled = conectado;
}

// Chip de honestidad: removido del popup (feedback JF — al usuario final no le aporta).
// La honestidad por-capa sigue viva en el panel admin (firewall/gobernanza).

function mostrarConfig(mostrar, aviso) {
  $("view-config").classList.toggle("hidden", !mostrar);
  $("view-main").classList.toggle("hidden", mostrar);
  if (mostrar) {
    // La key NUNCA se re-inyecta en el input: si ya hay una guardada, el placeholder lo
    // dice y escribir una nueva es lo único que la reemplaza (hardening #45).
    $("key").value = "";
    $("key").placeholder = cfg.basa_key ? "•••••••••• (guardada — escribe una nueva para cambiarla)" : "Pega tu API key";
    $("gw").value = cfg.basa_gateway || DEFAULT_GW;
    if (aviso) setStatus("off", aviso);
  }
}

async function load() {
  const s = await chrome.storage.local.get(
    ["basa_key", "basa_gateway", "basa_connected", "basa_user", "basa_team",
     "sesion_estado", "sesion_motivo", "proteccion"]);
  render(s);
}

// Traduce los códigos de error del SW a texto para el usuario.
function friendly(resp) {
  const e = resp && resp.error;
  if (e === "plaza_revocada") return "Tu plaza ya no está activa. Consulta con tu administrador.";
  if (e === "key_invalida") return "Tu API key no es válida.";
  if (e === "permiso_denegado") return "Necesitas conceder el permiso al host del gateway para conectar.";
  if (e === "gateway_invalido") return (resp && resp.detalle) || "La dirección del gateway no es válida.";
  return e || "no autorizado";
}

/** Valida contra el gateway vía el SW. `key` opcional: sin ella el SW usa la guardada. */
function validar(key, alOk) {
  setStatus("off", "Validando…");
  const msg = key ? { kind: "whoami", key } : { kind: "whoami" };
  chrome.runtime.sendMessage(msg, (resp) => {
    if (resp && resp.ok) return alOk(resp);
    setStatus("off", "✗ " + friendly(resp));
  });
}

// Pide el permiso de host del gateway en el GESTO del usuario (fiable). Ya concedido →
// resuelve true sin re-promptar. Cambiar de host pide permiso del host nuevo (FR-009).
// Debe ser el PRIMER await del handler para no perder el user-gesture.
async function pedirPermiso(v) {
  try { return await chrome.permissions.request({ origins: [v.origin + "/*"] }); }
  catch (_) { return false; }
}

// Conectar = revalidar con la key ya guardada. Sin key configurada, manda a config.
$("connect").addEventListener("click", async () => {
  if (!cfg.basa_key) return mostrarConfig(true, "Configura tu API key para conectarte.");
  const v = window.BASA_CONFIG.validarGatewayUrl(cfg.basa_gateway || DEFAULT_GW);
  if (!v.ok) return mostrarConfig(true, "✗ " + v.error);
  const granted = await pedirPermiso(v);
  if (!granted) return setStatus("off", "Necesitas conceder el permiso al host del gateway para conectar.");
  validar(null, () => load());
});

// Desconectar: el SW (dueño único) borra la key y el estado; el popup sólo lo pide.
$("disconnect").addEventListener("click", () => {
  chrome.runtime.sendMessage({ kind: "disconnect" }, () => { mostrarConfig(false); load(); });
});

$("open-config").addEventListener("click", () => mostrarConfig(true));
$("cancel").addEventListener("click", () => { mostrarConfig(false); load(); });

$("save").addEventListener("click", async () => {
  const escrita = $("key").value.trim();
  const key = escrita || cfg.basa_key;           // sin escribir nada, se reusa la guardada
  const gwRaw = $("gw").value.trim() || DEFAULT_GW;
  if (!key) return setStatus("off", "Ingresa tu API key.");
  // Validación https/local (FR-010) ANTES de tocar permisos o red.
  const v = window.BASA_CONFIG.validarGatewayUrl(gwRaw);
  if (!v.ok) return setStatus("off", "✗ " + v.error);
  // Permiso de host en el gesto (primer await). Denegado → mensaje claro (FR-011).
  const granted = await pedirPermiso(v);
  if (!granted) return setStatus("off", "Necesitas conceder el permiso al host del gateway para conectar.");
  // El gateway sí se persiste (config, no estado de sesión); el SW lo lee para el whoami.
  // La KEY NO se persiste acá: viaja en el mensaje y la persiste el SW SÓLO si valida.
  await chrome.storage.local.set({ basa_gateway: v.url });
  validar(key, () => { mostrarConfig(false); load(); });
  // si falla, la vista de config sigue abierta y no queda key inválida en disco
});

// El SW es el dueño del estado: reflejar cualquier cambio que escriba (revalidación por
// alarma, revocación, etc.) sin que el popup lo dispare.
chrome.storage.onChanged.addListener((_changes, area) => { if (area === "local") load(); });

// Marca white-label + versión: fuente única = manifest.json (lo pisa el render del partner).
$("app-name").textContent = chrome.runtime.getManifest().name;
$("ver").textContent = "v" + chrome.runtime.getManifest().version;

load();
