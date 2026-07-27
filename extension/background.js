/* Service worker (MV3) — DUEÑO ÚNICO del estado de sesión.
 * Único componente que habla con el gateway (tiene el permiso de host concedido en
 * runtime → sin CORS) y único que ve la virtual key. El content script nunca la ve.
 *
 * Estado de sesión (FR-021..FR-025): tres estados, un solo dueño (este SW).
 *   - "conectado"     : whoami ok. Gate abierto.
 *   - "no_verificado" : fallo de RED (fetch throw / status de servicio) → CONSERVA la
 *                       key y NO cierra el gate de una sesión ya válida; reintenta solo.
 *   - "desconectado"  : 401 (key inválida) o 403 (plaza revocada) → BORRA la key.
 * El popup NO escribe estado: sólo observa (chrome.storage.onChanged). */

// El default de URL y la validación viven en config.js — una sola fuente.
importScripts("config.js");
const DEFAULT_GW = self.BASA_CONFIG.GATEWAY_URL;

async function cfg() {
  const s = await chrome.storage.local.get(["basa_key", "basa_gateway"]);
  return { key: s.basa_key || "", gw: s.basa_gateway || DEFAULT_GW };
}

// ── Transiciones de estado (el SW es el ÚNICO que las escribe) ──────────────────
async function setConectado(j, keyToPersist) {
  const patch = {
    sesion_estado: "conectado",
    sesion_motivo: null,
    basa_connected: true,
    basa_user: j.user || null,
    basa_team: j.team || null,
    // proteccion: bloque del server para el chip de honestidad (US4). null si el
    // backend es viejo → la extensión asume la promesa más chica ("patrones").
    proteccion: j.proteccion || null,
  };
  // La key se persiste SÓLO tras validar (hardening #45: nunca antes). Cuando el
  // whoami usó una key provista por el popup y validó, este es el momento correcto.
  if (keyToPersist) patch.basa_key = keyToPersist;
  await chrome.storage.local.set(patch);
}

async function setNoVerificado() {
  // Corte de red: NO tocar basa_connected (una sesión ya válida sigue usable; los
  // envíos igual fail-closan si el gateway no responde) y NO borrar la key (FR-023).
  await chrome.storage.local.set({ sesion_estado: "no_verificado" });
}

async function setDesconectado(motivo) {
  // 401/403: permiso revocado → borrar la key (FR-021/FR-022).
  await chrome.storage.local.set({
    sesion_estado: "desconectado",
    sesion_motivo: motivo,              // "key_invalida" | "plaza_revocada"
    basa_connected: false,
    basa_user: null,
    basa_team: null,
    proteccion: null,
  });
  await chrome.storage.local.remove("basa_key");
}

// ── Permiso de host en runtime (US2/FR-009/FR-011) ──────────────────────────────
// El gesto de Conectar dispara chrome.permissions.request; el popup también lo pide
// (donde el user-gesture es fiable). Acá enforce-amos con contains y, si falta,
// intentamos request (best-effort) → si no se puede/se deniega, "permiso_denegado".
async function ensureHostPermission(origin) {
  const origins = [origin.replace(/\/+$/, "") + "/*"];
  try {
    if (await chrome.permissions.contains({ origins })) return true;
  } catch (_) { /* contains no debería fallar; ante la duda, pedimos */ }
  try {
    return await chrome.permissions.request({ origins });
  } catch (_) {
    return false;                       // request fuera de gesto → el popup ya lo pidió
  }
}

// ── whoami: valida la key contra el gateway y aplica la transición de estado ─────
// persistKey: si validó, persiste esta key (viene del popup). Para la revalidación
// periódica se pasa null (la key ya está en storage).
async function doWhoami(testKey, persistKey) {
  const { gw } = await cfg();
  if (!testKey) return { ok: false, error: "sin API key" };

  const v = self.BASA_CONFIG.validarGatewayUrl(gw);
  if (!v.ok) return { ok: false, error: "gateway_invalido", detalle: v.error };

  const granted = await ensureHostPermission(v.origin);
  if (!granted) return { ok: false, error: "permiso_denegado" };

  let r;
  try {
    r = await fetch(v.url + "/whoami", { headers: { "X-Basa-Key": testKey } });
  } catch (_netErr) {
    await setNoVerificado();            // corte de red → conserva key, reintenta solo
    return { ok: false, error: "sin conexión con el gateway", session: "no_verificado", key_conservada: true };
  }
  const j = await r.json().catch(() => ({}));
  if (r.ok && j.ok) {
    await setConectado(j, persistKey ? testKey : null);
    return { ok: true, user: j.user, team: j.team, key_label: j.key_label, proteccion: j.proteccion || null };
  }
  if (r.status === 401) {               // key inválida/vencida → borra la key
    await setDesconectado("key_invalida");
    return { ok: false, status: 401, error: "key_invalida", session: "desconectado" };
  }
  if (r.status === 403) {               // plaza revocada → borra la key (mensaje propio)
    // NOTA: el backend HOY sólo responde 401 (ver inspect.py:_fail_closed). Este branch
    // queda listo para cuando el server distinga "plaza revocada" con 403; no se inventa.
    await setDesconectado("plaza_revocada");
    return { ok: false, status: 403, error: "plaza_revocada", session: "desconectado" };
  }
  // Otro status (5xx, etc.): problema de servicio, NO es un rechazo de auth → conserva key.
  await setNoVerificado();
  return { ok: false, status: r.status, error: (j && j.error) || "servicio no disponible", session: "no_verificado" };
}

// ── Revalidación periódica (US6/FR-024): alarma ~30 min + al reabrir el navegador ─
const REVALIDATE_ALARM = "revalidate_session";
function scheduleRevalidation() {
  chrome.alarms.create(REVALIDATE_ALARM, { periodInMinutes: 30 });
}
async function revalidate() {
  const { key } = await cfg();
  if (!key) return;                     // nada que revalidar
  await doWhoami(key, false);           // usa la key ya persistida; no re-persiste
}
chrome.runtime.onInstalled.addListener(scheduleRevalidation);
chrome.runtime.onStartup.addListener(() => { scheduleRevalidation(); revalidate(); });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === REVALIDATE_ALARM) revalidate(); });

// ── Mensajería con el popup y el content script (vía bridge) ────────────────────
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      // Login del popup / revalidación: valida la key. Si viene msg.key (popup), se
      // persiste al validar; si no, usa la guardada.
      if (msg.kind === "whoami") {
        const provided = typeof msg.key === "string" && msg.key ? msg.key : null;
        const { key } = await cfg();
        const res = await doWhoami(provided || key, !!provided);
        return sendResponse(res);
      }

      // Desconexión iniciada por el popup: el SW (dueño único) borra la key y el estado.
      if (msg.kind === "disconnect") {
        await setDesconectado(null);    // sin motivo: fue el usuario, no un rechazo
        return sendResponse({ ok: true });
      }

      // Enmascarar un prompt vía el gateway (masking + audit + monitor).
      if (msg.kind === "inspect") {
        const { key, gw } = await cfg();
        if (!key) return sendResponse({ ok: false, error: "sin API key" });
        const v = self.BASA_CONFIG.validarGatewayUrl(gw);
        if (!v.ok) return sendResponse({ ok: false, error: "gateway_invalido" });

        let r;
        try {
          r = await fetch(v.url + "/inspect", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Basa-Key": key },
            body: JSON.stringify({ text: msg.text, tool: msg.tool }),
          });
        } catch (_netErr) {
          await setNoVerificado();       // corte de red → conserva key; el MAIN fail-closa
          return sendResponse({ ok: false, error: "sin conexión con el gateway" });
        }
        const j = await r.json().catch(() => ({}));
        if (r.ok && j.ok) {
          return sendResponse({ ok: true, masked: j.masked, replacements: j.replacements, entities: j.entities, user: j.user, team: j.team });
        }
        // US5: bloqueo de política (HTTP 200 + ok:false + blocked). Propagar blocked /
        // blocked_by_layer / motivo tal cual: el MAIN muestra `motivo`, NUNCA la capa cruda.
        if (j && j.blocked === true) {
          return sendResponse({ ok: false, blocked: true, blocked_by_layer: j.blocked_by_layer, motivo: j.motivo });
        }
        if (r.status === 401) { await setDesconectado("key_invalida"); return sendResponse({ ok: false, status: 401, error: "key_invalida" }); }
        if (r.status === 403) { await setDesconectado("plaza_revocada"); return sendResponse({ ok: false, status: 403, error: "plaza_revocada" }); }
        // Otro fallo sin `blocked`: servicio no disponible; conserva la key (fail-closed en el MAIN).
        return sendResponse({ ok: false, status: r.status, error: (j && j.error) || "inspect falló" });
      }

      sendResponse({ ok: false, error: "kind desconocido" });
    } catch (e) {
      sendResponse({ ok: false, error: String(e) });
    }
  })();
  return true; // respuesta asíncrona
});
