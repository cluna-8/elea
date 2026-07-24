// Verify Codex P1: is chrome.permissions available with the SHIPPED manifest (optional_host_permissions,
// permissions:["storage","alarms"], NO "permissions" API entry)? Probe the real SW.
import { chromium } from 'playwright';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const extDir = process.argv[2];
const ctx = await chromium.launchPersistentContext(mkdtempSync(join(tmpdir(), 'perm-')), {
  headless: false,
  args: [`--disable-extensions-except=${extDir}`, `--load-extension=${extDir}`, '--no-first-run'],
});
try {
  let sw = ctx.serviceWorkers()[0] || await ctx.waitForEvent('serviceworker', { timeout: 8000 });
  const probe = await sw.evaluate(async () => {
    const out = {
      hasPermissions: typeof chrome !== 'undefined' && typeof chrome.permissions,
      hasRequest: typeof chrome?.permissions?.request,
      hasContains: typeof chrome?.permissions?.contains,
    };
    try {
      // contains() needs no gesture; if the API is unavailable this throws.
      out.containsResult = await chrome.permissions.contains({ origins: ['http://localhost:8787/*'] });
      out.containsThrew = false;
    } catch (e) { out.containsThrew = true; out.containsError = String(e); }
    try {
      out.optionalDeclared = chrome.runtime.getManifest().optional_host_permissions;
      out.permsDeclared = chrome.runtime.getManifest().permissions;
    } catch (e) {}
    return out;
  });
  console.log(JSON.stringify(probe, null, 2));
} finally {
  await ctx.close();
}
