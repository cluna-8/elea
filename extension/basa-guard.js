/* ============================================================================
 * Basa Guard — content script MAIN (hookea window.fetch).
 * ----------------------------------------------------------------------------
 * - FAIL-CLOSED: sin API key válida (validada contra /gw/whoami) bloquea el
 *   envío a ChatGPT/Claude y muestra un overlay (Constitución SC-3).
 * - MASKING VÍA GATEWAY: el texto del usuario se manda a /gw/inspect (por el
 *   service worker), que enmascara, atribuye identidad (user/team) y empuja la
 *   decisión al monitor "Firewall en vivo". La respuesta trae los replacements;
 *   des-enmascaramos en el DOM para que el usuario siga leyendo sus datos.
 * - No hay detección local: la hace el gateway, de forma centralizada.
 * El service worker tiene la key; este script (MAIN) nunca la ve.
 *
 * REGLA DEL MAPA REVERSIBLE (S.tok2val): mapea token → valor original, o sea
 * exactamente lo que EVITAMOS que saliera. Vive en el closure y no se expone en
 * ningún lado observable por la página: ni en `window`, ni en el DOM, ni en
 * document.title. Todo lo demás del panel ya salió hacia el proveedor, así que
 * mostrarlo no agrega exposición; el mapa sí. No romper esa asimetría.
 * ==========================================================================*/
(() => {
  if (window.__BASA_GUARD__) return;
  window.__BASA_GUARD__ = true;

  // Sin handle global: `window.__BASA = S` dejaba el mapa token→PII al alcance de
  // cualquier script de la página con una línea (issue #44).
  const S = { tok2val: new Map(), lastEvent: null };
  let state = { enabled: true, connected: false, user: null, team: null };

  // ---- adapters: dónde vive el texto del usuario, cómo leerlo/escribirlo ----
  const ADAPTERS = [
    { id: "chatgpt", vendor: "OpenAI", web: "ChatGPT (web)",
      match: (u) => u.includes("/backend-api/f/conversation"),
      slots: (obj) => {
        const out = [];
        for (const m of (obj.messages || [])) {
          if (m.author && m.author.role === "user" && m.content && Array.isArray(m.content.parts)) {
            m.content.parts.forEach((p, i) => {
              if (typeof p === "string") out.push({ get: () => m.content.parts[i], set: (v) => { m.content.parts[i] = v; } });
            });
          }
        }
        return out;
      } },
    { id: "claude", vendor: "Anthropic", web: "Claude (web)",
      match: (u) => u.includes("/chat_conversations/") && (u.includes("/completion") || u.includes("/title")),
      slots: (obj) => {
        const out = [];
        for (const f of ["prompt", "message_content"]) {
          if (typeof obj[f] === "string") out.push({ get: () => obj[f], set: (v) => { obj[f] = v; } });
        }
        return out;
      } },
  ];

  // ---- puente con el service worker (vía bridge, mundo ISOLATED) ----
  // F-ext-1: nonce handshake. El bridge (ISOLATED) genera un nonce al arrancar y
  // lo incluye en CADA mensaje (init/state/resp). Fijamos el PRIMER nonce visto de
  // un mensaje del bridge (init/state) y rechazamos todo state/resp cuyo nonce no
  // coincida → frena la forja ingenua de la página. NO es inforjable (la página
  // comparte el mundo MAIN y observa el handshake): ver "Modelo de amenaza" en README.
  let _seq = 0; const _pending = new Map();
  let _bridgeNonce = null;
  window.addEventListener("message", (ev) => {
    const d = ev.data; if (!d) return;
    const n = d.__basa_nonce;
    // fijar el nonce del bridge la primera vez que lo vemos (init o state)
    if (_bridgeNonce === null && (d.__basa === "init" || d.__basa === "state") && typeof n === "string" && n) {
      _bridgeNonce = n;
    }
    if (d.__basa === "resp") {
      if (n !== _bridgeNonce) return;                 // forjado / sin handshake → ignorar
      if (_pending.has(d.id)) { _pending.get(d.id)(d.resp); _pending.delete(d.id); }
    } else if (d.__basa === "state") {
      if (n !== _bridgeNonce) return;                 // forjado → ignorar (no cambia el gate)
      state = d.state || state; renderPanel(); updateOverlay();
    }
  });
  function callBridge(kind, payload) {
    return new Promise((resolve) => {
      const id = ++_seq; _pending.set(id, resolve);
      window.postMessage(Object.assign({ __basa: "req", id, kind }, payload), "*");
      setTimeout(() => { if (_pending.has(id)) { _pending.delete(id); resolve({ ok: false, error: "timeout" }); } }, 6000);
    });
  }
  window.postMessage({ __basa: "getState" }, "*"); // pedir estado al arrancar

  // ---- hook de fetch: gating + masking vía gateway ----
  // ¿el request lleva un body que debemos inspeccionar? El fail-closed NO depende
  // de la forma del body (F4): si el adapter matchea y no podemos garantizar la
  // inspección de un body existente, bloqueamos en vez de mandar crudo.
  function requestCarriesBody(input, init) {
    if (init && init.body != null) return true;         // body vía init (string/Blob/FormData/…)
    if (input && typeof input !== "string") {            // input es un Request
      try {
        const m = (input.method || "GET").toUpperCase();
        if (m !== "GET" && m !== "HEAD") return true;     // método de escritura → asumir body
        if (input.body != null) return true;              // stream de body embebido
      } catch (_) { return true; }                        // ante la duda, tratar como con-body (bloquear)
    }
    return false;
  }

  const orig = window.fetch;
  window.fetch = async function (input, init) {
    let matched = false;                                  // ¿este request matcheó un adapter?
    try {
      const url = (typeof input === "string") ? input : (input && input.url) || "";
      const ad = ADAPTERS.find((a) => a.match(url));
      if (ad) {
        matched = true;
        // FAIL-CLOSED: la decisión depende SÓLO del match del adapter, no del body (F4).
        if (!state.connected) {
          updateOverlay();
          throw new Error("[Basa Guard] Conectate con tu API key para usar la IA.");
        }
        if (state.enabled) {
          if (init && typeof init.body === "string") {
            // path inspeccionable: parsear, enmascarar los slots y reescribir el body
            const obj = JSON.parse(init.body);
            const slots = ad.slots(obj);
            const combined = slots.map((s) => s.get()).filter(Boolean).join("\n");
            if (combined.trim()) {
              const res = await callBridge("inspect", { text: combined, tool: ad.web });
              if (!res || !res.ok) {        // gateway caído estando conectado → bloquear (fail-closed)
                updateOverlay(res && res.error);
                throw new Error("[Basa Guard] gateway no disponible" + (res && res.error ? ": " + res.error : ""));
              }
              const reps = (res.replacements || []).slice().sort((a, b) => b.original.length - a.original.length);
              if (reps.length) {
                for (const s of slots) { let t = s.get(); for (const r of reps) t = t.split(r.original).join(r.token); s.set(t); }
                for (const r of reps) S.tok2val.set(r.token, r.original);
                rebuildUnmaskRe();
              }
              S.lastEvent = { vendor: ad.vendor, sentMasked: slots.map((s) => s.get()).filter(Boolean).join(" | "),
                              entities: res.entities || [], user: res.user, team: res.team };
              renderPanel();
              init = Object.assign({}, init, { body: JSON.stringify(obj) });
            }
          } else if (requestCarriesBody(input, init)) {
            // matcheó + conectado + enabled, pero el body NO es texto inspeccionable
            // (Request/Blob/FormData): no podemos garantizar el masking → bloquear (F4).
            throw new Error("[Basa Guard] no puedo inspeccionar este request (body no-texto) — bloqueado por seguridad");
          }
          // sin body → nada que enmascarar ni filtrar → dejar pasar
        }
      }
    } catch (e) {
      if (String(e).includes("[Basa Guard]")) throw e;    // propagar el bloqueo explícito
      if (matched) {                                        // F6: error inesperado en un request YA identificado → fail-closed
        console.warn("[BasaGuard] fail-closed ante error inesperado", e);
        throw new Error("[Basa Guard] error al inspeccionar el request — bloqueado por seguridad");
      }
      console.warn("[BasaGuard]", e);                       // request no-matcheado → no interferir
    }
    return orig.call(this, input, init);
  };

  // ---- unmask en el DOM (usa los tokens exactos que devolvió el gateway) ----
  let _unmaskRe = null;
  function rebuildUnmaskRe() {
    if (!S.tok2val.size) { _unmaskRe = null; return; }
    const toks = [...S.tok2val.keys()].sort((a, b) => b.length - a.length)
      .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    _unmaskRe = new RegExp(toks.join("|"), "g");
  }
  function inPanel(node) { const el = node.parentElement; return !!(el && el.closest && el.closest("#basa-guard-panel")); }
  function unmask(root) {
    if (!_unmaskRe || !root) return;
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT); const ns = [];
    while (w.nextNode()) ns.push(w.currentNode);
    for (const node of ns) {
      if (inPanel(node)) continue;
      const v = node.nodeValue;
      if (v && v.indexOf("[") >= 0) { _unmaskRe.lastIndex = 0; if (_unmaskRe.test(v)) { _unmaskRe.lastIndex = 0; node.nodeValue = v.replace(_unmaskRe, (m) => S.tok2val.get(m) || m); } }
    }
  }
  // NO desenmascarar document.title: el título de página es campo estándar de
  // telemetría de analytics y además va al historial y al sync del perfil del
  // navegador — o sea, el valor real terminaba fuera de la pestaña por un canal
  // que el usuario no ve. El usuario no gana nada con leer su dato ahí (issue #44).

  // ---- overlay de bloqueo (fail-closed) ----
  let overlay;
  function updateOverlay(errMsg) {
    if (!document.body) return;
    if (!state.connected) {
      if (!overlay) {
        overlay = document.createElement("div"); overlay.id = "basa-guard-overlay";
        overlay.style.cssText = "position:fixed;inset:0;z-index:2147483646;background:rgba(6,9,17,.86);backdrop-filter:blur(3px);display:flex;align-items:center;justify-content:center;font:14px/1.5 ui-sans-serif,system-ui,sans-serif;color:#e5e7eb";
        document.body.appendChild(overlay);
      }
      overlay.innerHTML = '<div style="max-width:420px;text-align:center;padding:28px;border:1px solid #1f2937;border-radius:16px;background:#0b0f19;box-shadow:0 20px 60px rgba(0,0,0,.6)">' +
        '<div style="font-size:34px">🛡️</div>' +
        '<div style="font-size:17px;font-weight:700;color:#fff;margin:8px 0">Basa Guard — acceso restringido</div>' +
        '<div style="color:#9ca3af">Necesitás conectarte con tu <b>API key</b> para usar la IA en esta organización.</div>' +
        '<div style="color:#6b7280;margin-top:10px;font-size:12px">Abrí la extensión (ícono 🛡️ en la barra del navegador) y pegá tu key.</div>' +
        (errMsg ? '<div style="color:#fca5a5;margin-top:10px;font-size:12px">' + String(errMsg).replace(/</g, "&lt;") + '</div>' : '') + '</div>';
    } else if (overlay) { overlay.remove(); overlay = null; }
  }

  // ---- panel (identidad + telemetría) ----
  let panel; const esc = (s) => String(s).replace(/</g, "&lt;");
  function renderPanel() {
    if (!document.body || !state.connected) { if (panel) { panel.remove(); panel = null; } return; }
    if (!panel) {
      panel = document.createElement("div"); panel.id = "basa-guard-panel";
      panel.style.cssText = "position:fixed;bottom:16px;right:16px;z-index:2147483645;width:360px;max-height:64vh;overflow:auto;background:#0b0f19;color:#e5e7eb;border:1px solid #1f2937;border-radius:12px;font:12px/1.45 ui-monospace,Menlo,monospace;box-shadow:0 8px 30px rgba(0,0,0,.5)";
      document.body.appendChild(panel);
    }
    const ev = S.lastEvent;
    const ents = ev && ev.entities ? ev.entities.map((e) => e.type + "×" + e.count).join("  ") : "";
    panel.innerHTML =
      '<div style="padding:10px 12px;border-bottom:1px solid #1f2937;display:flex;align-items:center;gap:8px">' +
        '<span style="font-size:14px">🛡️</span><b style="color:#fff">Basa Guard</b>' +
        '<span style="margin-left:auto;color:#22c55e">● gateway</span></div>' +
      '<div style="padding:8px 12px;border-bottom:1px solid #1f2937;color:#93c5fd">' +
        (state.team || "—") + " · " + (state.user || "—") + '</div>' +
      '<div style="padding:10px 12px">' +
        '<div style="color:#9ca3af;margin-bottom:4px">Entidades detectadas: <span style="color:#fca5a5">' + (ents || "—") + '</span></div>' +
        '<div style="color:#9ca3af;margin:6px 0 4px">Lo que salió a ' + (ev ? esc(ev.vendor) : "la IA") + ' (enmascarado):</div>' +
        '<div style="background:#111827;border:1px solid #374151;border-radius:8px;padding:8px;color:#fca5a5;white-space:pre-wrap;word-break:break-word">' + (ev ? esc(ev.sentMasked) : "—") + '</div>' +
        // El mapa reversible NO se renderiza: es lo único del panel que el proveedor
        // todavía no tiene. Lo de arriba ya salió; esto es justamente lo que no salió.
        '<div style="color:#6b7280;margin-top:8px;font-size:11px">Vos seguís viendo tus datos completos en el chat; el proveedor recibió lo de arriba.</div>' +
      '</div>';
  }

  // ---- arranque del DOM ----
  function startDom() {
    new MutationObserver(() => { unmask(document.body); }).observe(document.body, { childList: true, subtree: true, characterData: true });
    updateOverlay(); renderPanel();
  }
  if (document.body) startDom();
  else document.addEventListener("DOMContentLoaded", startDom, { once: true });

  // Sin número de versión: la única fuente es manifest.json (el mundo MAIN no
  // puede leer chrome.runtime, así que acá no se duplica).
  console.log("%c[Basa Guard] activo — fail-closed + masking vía gateway", "color:#22c55e");
})();
