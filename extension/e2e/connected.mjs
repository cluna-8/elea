// 028 e2e connected-path — drives the extension's positive path (US2 connect, US4 amber chip
// from a real server proteccion block, US6 session) LIVE in Chrome, against an inline stub
// gateway that emits the EXACT whoami/inspect contract (the shapes pytest proves the real
// backend returns). A fixture manifest swaps optional_host_permissions → static host_permissions
// for the stub host, which bypasses the native chrome.permissions prompt (that prompt UX is
// covered by code review + the live rehearsal). The connected LOGIC is identical either way.
//
// Usage: PLAYWRIGHT_BROWSERS_PATH=~/Library/Caches/ms-playwright node connected.mjs <rendered-ext-dir>

import { chromium } from 'playwright';
import http from 'node:http';
import { cpSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const renderedDir = process.argv[2];
if (!renderedDir) { console.error('usage: node connected.mjs <rendered-ext-dir>'); process.exit(2); }

const PORT = 8777;
const PISO = ' El piso no negociable —interceptar, registrar, detectar datos personales y bloquear lo prohibido— se aplica siempre.';
const PROTECCION = {
  deteccion: 'patrones',
  titulo: 'Detección por patrones',
  detalle: 'En esta superficie la detección de datos personales funciona por patrones conocidos —correo, teléfono, documentos de identidad, credenciales—. No usa análisis lingüístico.' + PISO,
  capas_delegadas: ['content_moderation', 'prompt_injection'],
};

// --- inline stub gateway (exact contract) ---
const server = http.createServer((req, res) => {
  let body = '';
  req.on('data', c => body += c);
  req.on('end', () => {
    const key = req.headers['x-basa-key'] || '';
    const send = (code, obj) => { res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(obj)); };
    if (req.url.endsWith('/whoami')) {
      if (!key.startsWith('sk-')) return send(401, { ok: false, error: 'API key requerida o inválida' });
      return send(200, { ok: true, user: 'dev.browser', team: 'Equipo Web', key_label: 'chatgpt-key', proteccion: PROTECCION });
    }
    if (req.url.endsWith('/inspect')) {
      const txt = (() => { try { return JSON.parse(body).text || ''; } catch { return ''; } })();
      if (/sk-[a-z0-9]{6,}|AKIA[0-9A-Z]{6,}/i.test(txt)) {
        return send(200, { ok: false, blocked: true, blocked_by_layer: 'secret_detection', motivo: 'Se detectó material secreto (credenciales) en el contenido; el envío se bloqueó.' });
      }
      return send(200, { ok: true, blocked: false, masked: txt, replacements: [], entities: [], user: 'dev.browser', team: 'Equipo Web' });
    }
    send(404, { ok: false, error: 'not found' });
  });
});
await new Promise(r => server.listen(PORT, r));

// --- build fixture: rendered ext + static host_permissions for the stub ---
const fixture = mkdtempSync(join(tmpdir(), 'ext-fixture-'));
cpSync(renderedDir, fixture, { recursive: true });
const mpath = join(fixture, 'manifest.json');
const m = JSON.parse(readFileSync(mpath, 'utf8'));
delete m.optional_host_permissions;
m.host_permissions = [`http://localhost:${PORT}/*`];
writeFileSync(mpath, JSON.stringify(m, null, 2));

const results = [];
const check = (name, ok, detail = '') => { results.push({ ok: !!ok }); console.log(`${ok ? '✅' : '❌'} ${name}${detail ? ' — ' + detail : ''}`); };

const userDataDir = mkdtempSync(join(tmpdir(), 'ext-conn-'));
const ctx = await chromium.launchPersistentContext(userDataDir, {
  headless: false,
  args: [`--disable-extensions-except=${fixture}`, `--load-extension=${fixture}`, '--no-first-run'],
});
try {
  let sw = ctx.serviceWorkers()[0] || await ctx.waitForEvent('serviceworker', { timeout: 8_000 }).catch(() => null);
  const extId = sw ? new URL(sw.url()).host : null;
  check('fixture extension loads', !!extId, extId);

  const popup = await ctx.newPage();
  await popup.goto(`chrome-extension://${extId}/popup.html`);
  await popup.waitForSelector('#open-config');
  await popup.click('#open-config');
  await popup.fill('#gw', `http://localhost:${PORT}/api/v1/gw`);
  await popup.fill('#key', 'sk-basa-e2e-connected');
  await popup.click('#save');

  await popup.waitForFunction(() => document.querySelector('#status')?.classList.contains('on'), { timeout: 10_000 }).catch(() => {});
  const statusOn = await popup.$eval('#status', el => el.classList.contains('on')).catch(() => false);
  const statusText = (await popup.textContent('#status'))?.trim() || '';
  check('US2/US6: connected after whoami (real gateway contract)', statusOn, statusText.slice(0, 60));

  const chipHidden = await popup.$eval('#proteccion', el => el.classList.contains('hidden')).catch(() => true);
  const chipTitle = (await popup.textContent('#proteccion .chip-title'))?.trim() || '';
  const chipDetail = (await popup.textContent('#proteccion .chip-detail'))?.trim() || '';
  check('US4: honesty chip visible + amber', !chipHidden);
  check('US4: chip shows "Detección por patrones · cobertura parcial"', /detecci[oó]n por patrones · cobertura parcial/i.test(chipTitle), chipTitle);
  check('US4: chip detail is the SERVER copy (ends with piso)', chipDetail.includes('piso no negociable'), chipDetail.slice(-40));
  check('US4: chip never says "protegido"/green', !/protegido/i.test(chipTitle + chipDetail));

  // US6: disconnect clears session.
  await popup.click('#disconnect');
  await popup.waitForFunction(() => document.querySelector('#status')?.classList.contains('off'), { timeout: 5_000 }).catch(() => {});
  const off = await popup.$eval('#status', el => el.classList.contains('off')).catch(() => false);
  const chipHiddenAfter = await popup.$eval('#proteccion', el => el.classList.contains('hidden')).catch(() => true);
  check('US6: disconnect → off + chip hidden', off && chipHiddenAfter);
} catch (e) {
  check('harness ran without throwing', false, String(e).slice(0, 200));
} finally {
  await ctx.close();
  server.close();
}
const failed = results.filter(r => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} checks passed`);
process.exit(failed ? 1 : 0);
