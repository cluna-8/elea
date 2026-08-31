// 028 e2e US5 block overlay — the crown-jewel path: a real page issues a ChatGPT-shaped fetch
// carrying a credential; guardia-main.js (MAIN) hooks it → bridge → SW → stub gateway returns
// {blocked:true, motivo}; the in-page modal must show the SERVER motivo (never blocked_by_layer).
// Fixture adds a localhost content_scripts match so the guard injects on our test page.
//
// Usage: PLAYWRIGHT_BROWSERS_PATH=~/Library/Caches/ms-playwright node block.mjs <rendered-ext-dir>

import { chromium } from 'playwright';
import http from 'node:http';
import { cpSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const renderedDir = process.argv[2];
if (!renderedDir) { console.error('usage: node block.mjs <rendered-ext-dir>'); process.exit(2); }

const GW = 8787, PAGE = 8788;
const MOTIVO = 'Se detectó material secreto (credenciales) en el contenido; el envío se bloqueó.';

// stub gateway
const gw = http.createServer((req, res) => {
  let b = ''; req.on('data', c => b += c); req.on('end', () => {
    const key = req.headers['x-sentinel-key'] || '';
    const send = (c, o) => { res.writeHead(c, { 'content-type': 'application/json' }); res.end(JSON.stringify(o)); };
    if (req.url.endsWith('/whoami')) return key.startsWith('sk-')
      ? send(200, { ok: true, user: 'dev.browser', team: 'Equipo Web', key_label: 'k', proteccion: { deteccion: 'patrones', titulo: 'Detección por patrones', detalle: 'patrones. El piso no negociable se aplica siempre.', capas_delegadas: [] } })
      : send(401, { ok: false, error: 'inválida' });
    if (req.url.endsWith('/inspect')) {
      const txt = (() => { try { return JSON.parse(b).text || ''; } catch { return ''; } })();
      if (/sk-[a-z0-9]{6,}/i.test(txt)) return send(200, { ok: false, blocked: true, blocked_by_layer: 'secret_detection', motivo: MOTIVO });
      return send(200, { ok: true, blocked: false, masked: txt, replacements: [], entities: [] });
    }
    send(404, {});
  });
});
await new Promise(r => gw.listen(GW, r));

// page server: serves the test page; the guarded fetch path never actually reaches it (blocked first)
const page = http.createServer((_req, res) => {
  res.writeHead(200, { 'content-type': 'text/html' });
  res.end('<!doctype html><html><body><h1>fake chat</h1></body></html>');
});
await new Promise(r => page.listen(PAGE, r));

// fixture: rendered ext + static host perm for the gateway + content_scripts match for our page
const fixture = mkdtempSync(join(tmpdir(), 'ext-block-'));
cpSync(renderedDir, fixture, { recursive: true });
const mpath = join(fixture, 'manifest.json');
const m = JSON.parse(readFileSync(mpath, 'utf8'));
delete m.optional_host_permissions;
m.host_permissions = [`http://localhost:${GW}/*`];
for (const cs of m.content_scripts) cs.matches.push(`http://localhost:${PAGE}/*`);
writeFileSync(mpath, JSON.stringify(m, null, 2));

const results = [];
const check = (n, ok, d = '') => { results.push({ ok: !!ok }); console.log(`${ok ? '✅' : '❌'} ${n}${d ? ' — ' + d : ''}`); };

const userDataDir = mkdtempSync(join(tmpdir(), 'ext-blk-'));
const ctx = await chromium.launchPersistentContext(userDataDir, {
  headless: false,
  args: [`--disable-extensions-except=${fixture}`, `--load-extension=${fixture}`, '--no-first-run'],
});
try {
  let sw = ctx.serviceWorkers()[0] || await ctx.waitForEvent('serviceworker', { timeout: 8_000 }).catch(() => null);
  const extId = sw ? new URL(sw.url()).host : null;
  check('fixture loads', !!extId, extId);

  // connect via popup first (state.connected needed, else guard fail-closes on "not connected")
  const popup = await ctx.newPage();
  await popup.goto(`chrome-extension://${extId}/popup.html`);
  await popup.waitForSelector('#open-config');
  await popup.click('#open-config');
  await popup.fill('#gw', `http://localhost:${GW}/api/v1/gw`);
  await popup.fill('#key', 'sk-sentinel-e2e-block');
  await popup.click('#save');
  await popup.waitForFunction(() => document.querySelector('#status')?.classList.contains('on'), { timeout: 10_000 }).catch(() => {});
  const connected = await popup.$eval('#status', el => el.classList.contains('on')).catch(() => false);
  check('connected (precondition)', connected);
  await popup.close();

  // open the guarded test page
  const tab = await ctx.newPage();
  await tab.goto(`http://localhost:${PAGE}/`);
  await tab.waitForTimeout(800); // let content scripts + nonce handshake settle

  // fire a ChatGPT-shaped fetch carrying a credential → guard hooks it → SW → gateway BLOCK
  const fetchRejected = await tab.evaluate(async (port) => {
    try {
      await fetch(`http://localhost:${port}/backend-api/f/conversation`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ messages: [{ author: { role: 'user' }, content: { parts: ['mi clave es sk-secret1234567'] } }] }),
      });
      return false; // not blocked (bad)
    } catch (e) { return String(e).includes('[') || true; } // guard threw → blocked (good)
  }, PAGE);
  check('guarded fetch was blocked (fail-closed on policy block)', fetchRejected);

  // the in-page modal must show the SERVER motivo, and never the raw layer id
  await tab.waitForSelector('#guardia-modal', { timeout: 4_000 }).catch(() => {});
  const modalText = await tab.$eval('#guardia-modal', el => el.textContent || '').catch(() => '');
  check('US5: modal shows the SERVER motivo', modalText.includes('material secreto'), modalText.replace(/\s+/g, ' ').slice(0, 70));
  check('US5: modal never leaks raw blocked_by_layer', !/secret_detection|blocked_by_layer/i.test(modalText));
} catch (e) {
  check('harness ran without throwing', false, String(e).slice(0, 200));
} finally {
  await ctx.close(); gw.close(); page.close();
}
const failed = results.filter(r => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} checks passed`);
process.exit(failed ? 1 : 0);
