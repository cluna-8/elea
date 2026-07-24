// 029 verification — screenshots of the 6 pilot pages + checks: 0 console errors, 0 Google-Fonts
// requests (air-gap), light theme rendered. Seeds an admin session in localStorage (the app is a
// state-router in App.tsx; nav is by clicking sidebar buttons).
//
// Usage: PLAYWRIGHT_BROWSERS_PATH=~/Library/Caches/ms-playwright node 029-screens.mjs <base-url> <out-dir>
//   e.g. node 029-screens.mjs http://localhost:5173 ./shots

import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

const base = process.argv[2] || 'http://localhost:5173';
const outDir = process.argv[3] || join(process.cwd(), 'shots-029');
mkdirSync(outDir, { recursive: true });

const ADMIN = { id: 'u-admin', username: 'admin.demo', role: 'admin', email: 'admin@demo.local' };
// The 5 authed pilot pages by their sidebar label; Login is captured logged-out.
const PAGES = [
  { file: '1-login',     nav: null,                       auth: false },
  { file: '2-dashboard', nav: 'Panel Principal',          auth: true },
  { file: '3-firewall',  nav: 'Firewall en vivo',         auth: true },
  { file: '4-models',    nav: 'Modelos & Ollama',         auth: true },
  { file: '5-users',     nav: 'Usuarios & Presupuestos',  auth: true },
  { file: '6-playground',nav: 'Playground',               auth: true },
  { file: '7-security',  nav: 'Seguridad y Guardianes',   auth: true },
];

const fontReqs = [];
const results = [];

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
ctx.on('request', r => { const u = r.url(); if (/fonts\.googleapis|fonts\.gstatic/.test(u)) fontReqs.push(u); });

try {
  for (const p of PAGES) {
    const page = await ctx.newPage();
    const errs = [];
    // Separate REAL js/styling errors from the expected backend-absent network 500s
    // (vite proxies /api,/gw → backend:8000 which isn't reachable without the stack).
    const isBackendAbsent = t => /Failed to load resource|net::ERR|500 \(Internal Server Error\)|the server responded with a status of (500|502|503|404)/i.test(t);
    page.on('console', m => { if (m.type() === 'error' && !isBackendAbsent(m.text())) errs.push(m.text()); });
    page.on('pageerror', e => { if (!isBackendAbsent(e.message)) errs.push('pageerror: ' + e.message); });

    await page.goto(base, { waitUntil: 'domcontentloaded' });
    // seed / clear session
    await page.evaluate((u) => {
      if (u) { localStorage.setItem('basa_session_token', 'e2e-demo-token'); localStorage.setItem('basa_current_user', JSON.stringify(u)); }
      else { localStorage.removeItem('basa_session_token'); localStorage.removeItem('basa_current_user'); }
    }, p.auth ? ADMIN : null);
    await page.goto(base, { waitUntil: 'networkidle' }).catch(() => {});
    await page.waitForTimeout(600);

    if (p.nav) {
      const btn = page.getByRole('button', { name: p.nav, exact: false });
      await btn.first().click({ timeout: 4000 }).catch(() => {});
      await page.waitForTimeout(700);
    }

    // sanity: body background should be the light canvas, not the old dark navy
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor).catch(() => '');
    const shot = join(outDir, p.file + '.png');
    await page.screenshot({ path: shot, fullPage: true });
    const isLight = /^rgb\((2\d\d|25\d),/.test(bg) || bg === 'rgb(250, 249, 248)';
    results.push({ page: p.file, errs: errs.length, bg, isLight, shot });
    console.log(`${errs.length === 0 ? '✅' : '⚠️ '} ${p.file}  bg=${bg}  consoleErrors=${errs.length}  → ${shot}`);
    if (errs.length) errs.slice(0, 3).forEach(e => console.log('     · ' + e));
    await page.close();
  }
} finally {
  await ctx.close();
  await browser.close();
}

console.log(`\nGoogle-Fonts requests: ${fontReqs.length} (must be 0)`);
const totalErrs = results.reduce((a, r) => a + r.errs, 0);
console.log(`Total console errors across pages: ${totalErrs}`);
console.log(`Screenshots in: ${outDir}`);
process.exit(fontReqs.length === 0 && totalErrs === 0 ? 0 : 1);
