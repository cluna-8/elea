/* ============================================================================
 * content script MAIN (hookea window.fetch).
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
 * document.title. El texto enmascarado ya salió hacia el proveedor; el mapa NO,
 * y es justamente lo que no debe salir. No romper esa asimetría (por eso además
 * ya no hay panel de telemetría visible: se eliminó en 028, ver #46).
 * ==========================================================================*/
(() => {
  if (window.__BASA_GUARD__) return;
  window.__BASA_GUARD__ = true;

  // Sin handle global: `window.__BASA = S` dejaba el mapa token→PII al alcance de
  // cualquier script de la página con una línea (issue #44).
  const S = { tok2val: new Map() };
  // No hay `enabled`: el enmascarado NO es desactivable por el usuario. El toggle
  // del popup dejaba que el empleado apagara el firewall y mandara el body crudo.
  // `name` (marca white-label, US3) llega en el `state` que empuja el bridge; el MAIN
  // no puede leer chrome.runtime. `proteccion` (chip de honestidad, US4) también llega
  // en el payload pero acá ya no se consume: el chip vive SÓLO en el popup (028, se sacó
  // el panel de telemetría). Se deja el campo para no tocar el protocolo del bridge.
  let state = { connected: false, user: null, team: null, proteccion: null, name: "" };

  // Tag interno neutro para logs y para el sentinela de bloqueo explícito (sin marca).
  const TAG = "[guardia]";
  const esc = (s) => String(s).replace(/</g, "&lt;");
  // Marca a mostrar: la del paquete del partner (white-label) o un neutro genérico.
  function appLabel() { return (state && state.name) || "Protección de datos"; }
  // (El alcance de protección US4 —chip de honestidad ámbar— se renderiza en el POPUP,
  // que sí puede leer el bloque `proteccion` del storage. Acá ya no hay panel donde
  // mostrarlo, así que no se duplica esa vista en el MAIN.)

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
      state = d.state || state; updateOverlay();
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
          throw new Error(TAG + " Conectate con tu API key para usar la IA.");
        }
        // El enmascarado NO es opcional: no hay condición de usuario acá.
        if (init && typeof init.body === "string") {
          // path inspeccionable: parsear, enmascarar los slots y reescribir el body
          const obj = JSON.parse(init.body);
          const slots = ad.slots(obj);
          const combined = slots.map((s) => s.get()).filter(Boolean).join("\n");
          if (combined.trim()) {
            const res = await callBridge("inspect", { text: combined, tool: ad.web });
            if (!res || !res.ok) {
              // US5: distinguir un BLOQUEO de política (mostrar el `motivo` del server)
              // de un servicio caído. Ambos frenan el envío (fail-closed conservado).
              if (res && res.blocked === true) {
                // `motivo` es catálogo cerrado del server. NUNCA se renderiza
                // `blocked_by_layer` crudo (FR-020): sólo se usa el motivo en lenguaje llano.
                showBlock(res.motivo || "Tu organización bloqueó este envío por política.");
                throw new Error(TAG + " bloqueado por política");
              }
              // ok:false sin `blocked` (o respuesta de una versión vieja) → servicio no disponible.
              // Si además se perdió la sesión (sin key), el overlay de "acceso restringido"
              // cubre el caso; si seguimos conectados, mostramos el aviso de servicio caído.
              if (!state.connected) updateOverlay(res && res.error); else showServicio();
              throw new Error(TAG + " servicio no disponible" + (res && res.error ? ": " + res.error : ""));
            }
            const reps = (res.replacements || []).slice().sort((a, b) => b.original.length - a.original.length);
            if (reps.length) {
              for (const s of slots) { let t = s.get(); for (const r of reps) t = t.split(r.original).join(r.token); s.set(t); }
              for (const r of reps) S.tok2val.set(r.token, r.original);
              rebuildUnmaskRe();
            }
            // (Sin telemetría visible: el enmascarado se aplica al body y punto; el
            // panel de actividad se eliminó en 028. El unmask del DOM sigue igual.)
            init = Object.assign({}, init, { body: JSON.stringify(obj) });
          }
        } else if (requestCarriesBody(input, init)) {
          // matcheó + conectado, pero el body NO es texto inspeccionable
          // (Request/Blob/FormData): no podemos garantizar el masking → bloquear (F4).
          throw new Error(TAG + " no puedo inspeccionar este request (body no-texto) — bloqueado por seguridad");
        }
        // sin body → nada que enmascarar ni filtrar → dejar pasar
      }
    } catch (e) {
      if (String(e).includes(TAG)) throw e;                 // propagar el bloqueo explícito
      if (matched) {                                        // F6: error inesperado en un request YA identificado → fail-closed
        console.warn(TAG + " fail-closed ante error inesperado", e);
        throw new Error(TAG + " error al inspeccionar el request — bloqueado por seguridad");
      }
      console.warn(TAG, e);                                 // request no-matcheado → no interferir
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
  function unmask(root) {
    if (!_unmaskRe || !root) return;
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT); const ns = [];
    while (w.nextNode()) ns.push(w.currentNode);
    for (const node of ns) {
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
        overlay = document.createElement("div"); overlay.id = "guardia-overlay";
        // Tema claro Foundry. En un elemento inyectado en la PÁGINA no podemos asumir
        // que Inter esté disponible: se declara 'Inter' primero y cae a la fuente del
        // sistema (system-ui). Sin @font-face para no depender de red (0-egress).
        overlay.style.cssText = "position:fixed;inset:0;z-index:2147483646;background:rgba(37,36,36,.45);backdrop-filter:blur(3px);display:flex;align-items:center;justify-content:center;font:14px/1.5 'Inter',system-ui,-apple-system,sans-serif;color:#242424";
        document.body.appendChild(overlay);
      }
      overlay.innerHTML = '<div style="max-width:420px;text-align:center;padding:28px;border:1px solid #e1dfdd;border-radius:8px;background:#ffffff;box-shadow:0 8px 30px rgba(0,0,0,.12)">' +
        '<div style="font-size:34px">🛡️</div>' +
        '<div style="font-size:17px;font-weight:700;color:#242424;margin:8px 0">' + esc(appLabel()) + ' — acceso restringido</div>' +
        '<div style="color:#616161">Necesitás conectarte con tu <b>API key</b> para usar la IA en esta organización.</div>' +
        '<div style="color:#8a8886;margin-top:10px;font-size:12px">Abrí la extensión (ícono 🛡️ en la barra del navegador) y pegá tu key.</div>' +
        (errMsg ? '<div style="color:#a4262c;margin-top:10px;font-size:12px">' + esc(errMsg) + '</div>' : '') + '</div>';
    } else if (overlay) { overlay.remove(); overlay = null; }
  }

  // ---- aviso modal estando CONECTADO (US5) — el overlay de arriba sólo cubre "sin
  // conexión". Dos usos: BLOQUEO de política (muestra el `motivo` en lenguaje llano del
  // server, jamás la capa cruda — FR-020) y servicio caído (FR-019). Ambos frenaron el
  // envío por fail-closed; el modal explica por qué.
  let modalEl;
  function showModal(o) {
    if (!document.body) return;
    if (!modalEl) {
      modalEl = document.createElement("div"); modalEl.id = "guardia-modal";
      // Tema claro Foundry; misma nota de fuente que el overlay (Inter → system-ui, sin red).
      modalEl.style.cssText = "position:fixed;inset:0;z-index:2147483647;background:rgba(37,36,36,.45);backdrop-filter:blur(3px);display:flex;align-items:center;justify-content:center;font:14px/1.5 'Inter',system-ui,-apple-system,sans-serif;color:#242424";
      document.body.appendChild(modalEl);
    }
    modalEl.innerHTML = '<div style="max-width:460px;text-align:center;padding:28px;border:1px solid ' + o.borde + ';border-radius:8px;background:#ffffff;box-shadow:0 8px 30px rgba(0,0,0,.12)">' +
      '<div style="font-size:34px">' + o.icon + '</div>' +
      '<div style="font-size:17px;font-weight:700;color:' + (o.tituloColor || "#242424") + ';margin:8px 0">' + esc(o.titulo) + '</div>' +
      '<div style="color:' + o.color + '">' + esc(o.cuerpo) + '</div>' +
      '<div style="margin-top:16px"><button id="guardia-modal-ok" style="background:' + o.btn + ';color:#fff;border:0;border-radius:6px;padding:8px 16px;font:inherit;font-weight:600;cursor:pointer">Entendido</button></div>' +
      '</div>';
    const ok = modalEl.querySelector("#guardia-modal-ok");
    if (ok) ok.addEventListener("click", () => { if (modalEl) { modalEl.remove(); modalEl = null; } });
  }
  // Bloqueo de política: el `motivo` es catálogo cerrado del server (nunca blocked_by_layer).
  // Semántica DANGER (rojo Foundry): borde/título/botón en danger; cuerpo en texto legible.
  function showBlock(motivo) {
    showModal({ icon: "⛔", titulo: "Envío bloqueado por política", cuerpo: motivo,
                borde: "#a4262c", color: "#242424", btn: "#a4262c", tituloColor: "#a4262c" });
  }
  // Servicio caído: NO es un bloqueo de política — se comunica como tal (FR-019).
  // Neutro (no danger): borde/estilo base, botón en acento azul para el "Entendido".
  function showServicio() {
    showModal({ icon: "⚠️", titulo: "Servicio no disponible", cuerpo: "No se pudo verificar tu envío con el gateway. Se frenó por seguridad; reintentá en un momento.",
                borde: "#e1dfdd", color: "#616161", btn: "#0f6cbd", tituloColor: "#242424" });
  }

  // ---- panel de actividad: ELIMINADO en 028 (#46) ----
  // El viejo `#guardia-panel` (abajo a la derecha) listaba entidades detectadas y "lo que
  // salió enmascarado". Molestaba al usuario final y se sacó por completo. NADA de esa
  // telemetría se renderiza ya en la página. Lo importante que sobrevive:
  //   - el chip de honestidad (US4) sigue visible, pero SÓLO en el popup;
  //   - el enmascarado/desenmascarado en el DOM sigue igual (el usuario ve sus datos
  //     completos, el proveedor recibe lo enmascarado);
  //   - el mapa reversible S.tok2val nunca se muestra (regla del hardening #45).

  // ---- arranque del DOM ----
  function startDom() {
    new MutationObserver(() => { unmask(document.body); }).observe(document.body, { childList: true, subtree: true, characterData: true });
    updateOverlay();
  }
  if (document.body) startDom();
  else document.addEventListener("DOMContentLoaded", startDom, { once: true });

  // Sin número de versión: la única fuente es manifest.json (el mundo MAIN no
  // puede leer chrome.runtime, así que acá no se duplica).
  console.log("%c" + TAG + " activo — fail-closed + masking vía gateway", "color:#22c55e");
})();
