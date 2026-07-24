// 028 e2e load-smoke — loads the RENDERED cc-guardian extension in real Chrome and verifies
// the packaging + white-label + FR-010 URL validation. Everything here runs WITHOUT triggering
// the native chrome.permissions.request prompt (validation happens before it), so it's reliable
// headless. Connected-path (chip from server, session) is code-reviewed + covered in the
// live rehearsal with a real key.
//
// Usage: PLAYWRIGHT_BROWSERS_PATH=~/Library/Caches/ms-playwright node load-smoke.mjs <ext-dir>

import { chromium } from 'playwright';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const extDir = process.argv[2];
if (!extDir) { console.error('usage: node load-smoke.mjs <ext-dir>'); process.exit(2); }

const results = [];
const check = (name, ok, detail = '') => { results.push({ name, ok: !!ok, detail }); console.log(`${ok ? '✅' : '❌'} ${name}${detail ? ' — ' + detail : ''}`); };

const userDataDir = mkdtempSync(join(tmpdir(), 'ext-smoke-'));
const consoleErrors = [];

const ctx = await chromium.launchPersistentContext(userDataDir, {
  headless: false, // MV3 SW registration is unreliable under headless; headed is the supported path
  args: [`--disable-extensions-except=${extDir}`, `--load-extension=${extDir}`, '--no-first-run'],
});

// Resolve the extension id: prefer the SW registration; fall back to chrome://extensions.
async function resolveExtId() {
  let sw = ctx.serviceWorkers()[0] || await ctx.waitForEvent('serviceworker', { timeout: 8_000 }).catch(() => null);
  if (sw) return { id: new URL(sw.url()).host, via: 'service-worker' };
  const ext = await ctx.newPage();
  await ext.goto('chrome://extensions');
  // Read the id from the extensions manager (shadow DOM traversal).
  const id = await ext.evaluate(async () => {
    const mgr = document.querySelector('extensions-manager');
    const items = mgr?.shadowRoot?.querySelector('extensions-item-list')?.shadowRoot?.querySelectorAll('extensions-item') || [];
    return items.length ? items[0].getAttribute('id') : null;
  }).catch(() => null);
  await ext.close();
  return { id, via: 'chrome://extensions' };
}

try {
  const { id: extId, via } = await resolveExtId();
  check('extension loads + id resolved (manifest valid, no fatal error)', !!extId, extId ? `${extId} (via ${via})` : 'no id');
  if (!extId) throw new Error('no extension id — cannot continue');

  const popup = await ctx.newPage();
  popup.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  popup.on('pageerror', e => consoleErrors.push('pageerror: ' + e.message));
  await popup.goto(`chrome-extension://${extId}/popup.html`);
  await popup.waitForSelector('#app-name', { timeout: 5_000 });

  const appName = (await popup.textContent('#app-name'))?.trim();
  check('white-label header = cc-guardian (US3 live)', appName === 'cc-guardian', appName);
  check('header carries NO fabricant brand', appName && !/basa/i.test(appName), appName);

  // FR-010 (US2): remote non-https URL must be rejected at validation (before any prompt).
  await popup.click('#open-config');
  await popup.waitForSelector('#gw:visible', { timeout: 3_000 }).catch(() => {});
  await popup.fill('#gw', 'http://gateway.remoto.example.org/api/v1/gw');
  await popup.fill('#key', 'sk-basa-dummy-not-a-real-key');
  await popup.click('#save');
  await popup.waitForTimeout(500);
  const statusText1 = (await popup.textContent('#status'))?.trim() || '';
  const stillOff1 = await popup.$eval('#status', el => el.classList.contains('off')).catch(() => true);
  check('FR-010: remote http rejected + stays disconnected', stillOff1 && /https|claro|remota/i.test(statusText1), statusText1.slice(0, 80));

  // Empty URL → clear validation message.
  await popup.fill('#gw', '');
  await popup.click('#save');
  await popup.waitForTimeout(300);
  const statusText2 = (await popup.textContent('#status'))?.trim() || '';
  check('empty URL → validation message (no silent fail)', /ingres|direcci/i.test(statusText2), statusText2.slice(0, 80));

  // The honesty chip must NOT be shown while disconnected (it only appears connected).
  const chipHidden = await popup.$eval('#proteccion', el => el.classList.contains('hidden')).catch(() => true);
  check('chip hidden while disconnected (no false "protegido")', chipHidden);

  check('no console errors during load + popup', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | '));
} catch (e) {
  check('harness ran without throwing', false, String(e).slice(0, 200));
} finally {
  await ctx.close();
}

const failed = results.filter(r => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
if (consoleErrors.length) { console.log('console errors:'); consoleErrors.forEach(e => console.log('  · ' + e)); }
process.exit(failed.length ? 1 : 0);
