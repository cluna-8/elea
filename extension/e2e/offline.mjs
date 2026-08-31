// 028 e2e gateway INALCANZABLE (FR-019 servicio caído + FR-023 corte de red) — el camino real
// del piloto de la Cámara de Comercio (30-jul-2026): el usuario se llevó la laptop a casa y el
// gateway, que vive en una IP de la LAN de la sede, dejó de ser alcanzable. Lo que debe pasar:
//   · la sesión NO se cierra: la key se conserva y `sentinel_connected` sigue true (estado
//     "no_verificado"), así que el popup muestra el banner ámbar y no manda a reconfigurar;
//   · la página del proveedor carga normal (nada de overlay de "acceso restringido");
//   · el bloqueo ocurre AL ENVIAR: el fetch interceptado aborta con el tag [guardia] y sale el
//     modal "Servicio no disponible" — el prompt NUNCA sale del navegador (fail-closed).
// Ese último punto es el que importa de verdad: sin gateway que inspeccione, el texto del
// usuario no se manda crudo al proveedor. Acá se prueba con un contador de hits en el servidor
// de página: si el endpoint conversacional recibe UN solo request, hubo fuga.
//
// El stub gateway se arranca, se APAGA en mitad del test (simula la LAN inalcanzable) y al final
// se reenciende para verificar la recuperación sin reconectar a mano.
//
// Uso: PLAYWRIGHT_BROWSERS_PATH=~/Library/Caches/ms-playwright node offline.mjs <rendered-ext-dir>

import { chromium } from 'playwright';
import http from 'node:http';
import net from 'node:net';
import { cpSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const renderedDir = process.argv[2];
if (!renderedDir) { console.error('uso: node offline.mjs <rendered-ext-dir>'); process.exit(2); }

const GW = 8797, PAGE = 8798;   // puertos propios: no chocan con connected.mjs (8777) ni block.mjs (8787/8788)
const KEY = 'sk-sentinel-e2e-offline';
const PROTECCION = {
  deteccion: 'patrones', titulo: 'Detección por patrones',
  detalle: 'Detección por patrones conocidos. El piso no negociable se aplica siempre.',
  capas_delegadas: [],
};

// Contador de hits del servidor de PÁGINA: la prueba dura de que el envío nunca salió.
const hits = { html: 0, conversacion: 0 };

// --- stub gateway (mismo contrato exacto que connected.mjs/block.mjs) -------------------------
// Es una fábrica porque acá el gateway se apaga y se vuelve a encender. Se rastrean los sockets
// vivos: server.close() deja de ACEPTAR conexiones nuevas pero no corta los keep-alive que el
// navegador ya tiene abiertos — sin destruirlos, el "corte de red" no sería tal.
function crearGateway() {
  const sockets = new Set();
  const srv = http.createServer((req, res) => {
    let b = ''; req.on('data', c => b += c); req.on('end', () => {
      const key = req.headers['x-sentinel-key'] || '';
      const send = (c, o) => { res.writeHead(c, { 'content-type': 'application/json' }); res.end(JSON.stringify(o)); };
      if (req.url.endsWith('/whoami')) return key.startsWith('sk-')
        ? send(200, { ok: true, user: 'dev.browser', team: 'Equipo Web', key_label: 'k', proteccion: PROTECCION })
        : send(401, { ok: false, error: 'inválida' });
      if (req.url.endsWith('/inspect')) {
        const txt = (() => { try { return JSON.parse(b).text || ''; } catch { return ''; } })();
        return send(200, { ok: true, blocked: false, masked: txt, replacements: [], entities: [] });
      }
      send(404, {});
    });
  });
  srv.on('connection', (s) => { sockets.add(s); s.on('close', () => sockets.delete(s)); });
  return { srv, sockets };
}

// --- sondas de puerto: no seguimos hasta CONFIRMAR el estado del puerto (anti-flaky) ----------
function sondear(port, host) {
  return new Promise((resolve) => {
    const s = net.connect({ port, host });
    let listo = false;
    const fin = (v) => { if (listo) return; listo = true; s.destroy(); resolve(v); };
    s.once('connect', () => fin(true));
    s.once('error', () => fin(false));
    setTimeout(() => fin(false), 1_000);
  });
}
// Chrome resuelve "localhost" por IPv4 o IPv6 según el sistema. Detectamos con el stub VIVO qué
// familias de loopback atiende de verdad y después exigimos el estado deseado en todas ellas:
// si sólo mirásemos 127.0.0.1, un listener fantasma en ::1 dejaría el test corriendo contra un
// gateway que en realidad sigue vivo.
let FAMILIAS = null;
async function detectarFamilias(port) {
  const vivas = [];
  for (const h of ['127.0.0.1', '::1']) if (await sondear(port, h)) vivas.push(h);
  return vivas.length ? vivas : ['127.0.0.1'];
}
async function esperarPuerto(port, abierto, ms = 6_000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    const estados = [];
    for (const h of FAMILIAS) estados.push(await sondear(port, h));
    if (estados.every(v => v === abierto)) return true;
    await new Promise(r => setTimeout(r, 100));
  }
  return false;
}

async function encenderGateway() {
  const g = crearGateway();
  await new Promise(r => g.srv.listen(GW, r));
  if (!FAMILIAS) FAMILIAS = await detectarFamilias(GW);
  else await esperarPuerto(GW, true);
  return g;
}
// Apagón real: primero cortar los sockets vivos (esperar el callback de close() con un keep-alive
// abierto cuelga para siempre) y recién después confirmar que el puerto RECHAZA conexiones.
async function apagarGateway(g) {
  g.srv.close();
  for (const s of g.sockets) s.destroy();
  g.sockets.clear();
  return esperarPuerto(GW, false);
}

// Lee chrome.storage.local. El dueño del estado es el service worker; si MV3 lo durmió, caemos a
// una página de la extensión (popup.html sólo LEE storage al cargar — no dispara whoami —, así
// que observarlo no altera el estado que estamos midiendo).
async function leerStorage(ctx, extId) {
  const sw = ctx.serviceWorkers()[0];
  if (sw) { try { return await sw.evaluate(() => chrome.storage.local.get(null)); } catch (_) { /* SW dormido */ } }
  const p = await ctx.newPage();
  await p.goto(`chrome-extension://${extId}/popup.html`);
  const s = await p.evaluate(() => chrome.storage.local.get(null));
  await p.close();
  return s;
}

// Envío con forma de ChatGPT (mismo shape que block.mjs) desde la página guardada.
function enviarPrompt(tab, texto) {
  return tab.evaluate(async ([port, txt]) => {
    try {
      const r = await fetch(`http://localhost:${port}/backend-api/f/conversation`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ messages: [{ author: { role: 'user' }, content: { parts: [txt] } }] }),
      });
      return { rechazado: false, status: r.status, error: '' };
    } catch (e) {
      return { rechazado: true, status: 0, error: String((e && e.message) || e) };
    }
  }, [PAGE, texto]);
}

let gw = await encenderGateway();

// Servidor de PÁGINA: sirve el chat falso y cuenta los hits. El endpoint conversacional es el
// canario: con el gateway caído tiene que quedarse en cero.
const pageSrv = http.createServer((req, res) => {
  if (req.url.includes('/backend-api/f/conversation')) {
    hits.conversacion++;                       // ← si esto sube con el gateway caído, hubo fuga
    res.writeHead(200, { 'content-type': 'application/json' });
    return res.end(JSON.stringify({ ok: true }));
  }
  if (req.url === '/' || req.url.startsWith('/?')) hits.html++;
  res.writeHead(200, { 'content-type': 'text/html' });
  res.end('<!doctype html><html><body><h1>fake chat</h1></body></html>');
});
await new Promise(r => pageSrv.listen(PAGE, r));

// Fixture: extensión renderizada + host_permissions estático para el stub + content_scripts que
// matcheen nuestra página de prueba (idéntico a block.mjs).
const fixture = mkdtempSync(join(tmpdir(), 'ext-offline-'));
cpSync(renderedDir, fixture, { recursive: true });
const mpath = join(fixture, 'manifest.json');
const m = JSON.parse(readFileSync(mpath, 'utf8'));
delete m.optional_host_permissions;
m.host_permissions = [`http://localhost:${GW}/*`];
for (const cs of m.content_scripts) cs.matches.push(`http://localhost:${PAGE}/*`);
writeFileSync(mpath, JSON.stringify(m, null, 2));

const results = [];
const check = (n, ok, d = '') => { results.push({ ok: !!ok }); console.log(`${ok ? '✅' : '❌'} ${n}${d ? ' — ' + d : ''}`); };

const userDataDir = mkdtempSync(join(tmpdir(), 'ext-off-'));
const ctx = await chromium.launchPersistentContext(userDataDir, {
  headless: false,
  args: [`--disable-extensions-except=${fixture}`, `--load-extension=${fixture}`, '--no-first-run'],
});
try {
  const sw = ctx.serviceWorkers()[0] || await ctx.waitForEvent('serviceworker', { timeout: 8_000 }).catch(() => null);
  const extId = sw ? new URL(sw.url()).host : null;
  check('el fixture carga', !!extId, extId);
  if (!extId) throw new Error('sin extension id — no se puede continuar');

  // 1) Conectar con el gateway VIVO (la sede: todo normal).
  const popup = await ctx.newPage();
  await popup.goto(`chrome-extension://${extId}/popup.html`);
  await popup.waitForSelector('#open-config');
  await popup.click('#open-config');
  await popup.fill('#gw', `http://localhost:${GW}/api/v1/gw`);
  await popup.fill('#key', KEY);
  await popup.click('#save');
  await popup.waitForFunction(() => document.querySelector('#status')?.classList.contains('on'), { timeout: 10_000 }).catch(() => {});
  const conectado = await popup.$eval('#status', el => el.classList.contains('on')).catch(() => false);
  await popup.close();
  const st0 = await leerStorage(ctx, extId);
  check('precondición: sesión conectada (sentinel_connected = true)',
    conectado && st0.sentinel_connected === true, `sesion_estado=${st0.sesion_estado}`);

  // 2) La laptop sale de la LAN: el gateway se vuelve INALCANZABLE.
  const cerrado = await apagarGateway(gw);
  check('el stub del gateway quedó inalcanzable (puerto rechaza)', cerrado);

  // 3) La página del proveedor carga normal aunque el gateway no esté.
  const tab = await ctx.newPage();
  await tab.goto(`http://localhost:${PAGE}/`);
  // Handshake bridge→MAIN: el MAIN pinta un overlay transitorio hasta recibir el `state`. Esperar
  // a que desaparezca es la señal determinista de que state.connected=true ya llegó (mejor que
  // dormir un rato fijo) y de paso es la aserción de "la página carga normal".
  await tab.waitForFunction(() => !document.querySelector('#guardia-overlay'), { timeout: 6_000 }).catch(() => {});
  check('la página carga normal: sin overlay de acceso restringido', (await tab.$('#guardia-overlay')) === null);

  // 4) El usuario manda un prompt → el hook fail-closa porque /inspect no responde.
  const r = await enviarPrompt(tab, 'hola, ¿me ayudás a redactar el acta de la reunión de socios?');
  check('(a) el fetch interceptado RECHAZA con el tag [guardia]',
    r.rechazado === true && r.error.includes('[guardia]'), r.rechazado ? r.error.slice(0, 90) : `NO rechazó (status=${r.status})`);

  // (b) Modal de servicio caído — no el overlay de sesión cerrada ni un bloqueo de política.
  await tab.waitForSelector('#guardia-modal', { timeout: 4_000 }).catch(() => {});
  const modal = await tab.$eval('#guardia-modal', el => el.textContent || '').catch(() => '');
  check('(b) modal #guardia-modal "Servicio no disponible"',
    modal.includes('Servicio no disponible'), modal.replace(/\s+/g, ' ').slice(0, 80));
  check('(b) sin overlay #guardia-overlay: la sesión NO se cerró', (await tab.$('#guardia-overlay')) === null);
  check('(b) FR-019: el corte NO se comunica como bloqueo de política', !/bloqueado por política/i.test(modal));

  // (c) FR-023: corte de red conserva sesión y key; sólo marca "no_verificado".
  const st1 = await leerStorage(ctx, extId);
  check('(c) sentinel_connected sigue true', st1.sentinel_connected === true, String(st1.sentinel_connected));
  check('(c) la key se CONSERVA (no se borró por un fallo de red)',
    typeof st1.sentinel_key === 'string' && st1.sentinel_key.length > 0, st1.sentinel_key ? 'presente' : 'BORRADA');
  check('(c) sesion_estado = "no_verificado"', st1.sesion_estado === 'no_verificado', String(st1.sesion_estado));

  // (d) El prompt nunca salió del navegador.
  check('(d) el envío NUNCA llegó al proveedor (0 hits al endpoint conversacional)',
    hits.conversacion === 0, `conversacion=${hits.conversacion}`);
  check('(d) el contador no está muerto: la carga del HTML sí se registró', hits.html >= 1, `html=${hits.html}`);

  // Síntoma que ve el usuario en el popup: banner ámbar, la key se conserva.
  const popup2 = await ctx.newPage();
  await popup2.goto(`chrome-extension://${extId}/popup.html`);
  await popup2.waitForSelector('#status');
  const ambar = await popup2.$eval('#status', el => el.classList.contains('warn')).catch(() => false);
  const textoAmbar = (await popup2.textContent('#status'))?.trim() || '';
  check('popup: banner ámbar "se reintenta solo / tu key se conserva"',
    ambar && /reintenta/i.test(textoAmbar) && /conserva/i.test(textoAmbar), textoAmbar.slice(0, 70));
  await popup2.close();

  // 5) Vuelve la LAN: el envío siguiente pasa SIN que el usuario reconecte a mano.
  gw = await encenderGateway();
  const r2 = await enviarPrompt(tab, 'segundo intento, ya de vuelta en la oficina');
  check('recuperación: el envío posterior pasa sin reconectar',
    r2.rechazado === false && r2.status === 200, r2.rechazado ? r2.error.slice(0, 80) : `status=${r2.status}`);
  check('recuperación: ese envío SÍ salió al proveedor (1 hit)', hits.conversacion === 1, `conversacion=${hits.conversacion}`);
} catch (e) {
  check('el harness corrió sin lanzar', false, String(e).slice(0, 200));
} finally {
  await ctx.close();
  try { gw.srv.close(); for (const s of gw.sockets) s.destroy(); } catch (_) { /* ya cerrado */ }
  pageSrv.close();
}
const failed = results.filter(r => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} checks passed`);
process.exit(failed ? 1 : 0);
