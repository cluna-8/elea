// T— (encontrado en revisión, 09-sep): "Eleia Hub es un cliente más" — el mismo Hub
// tiene que poder apuntar a cualquier instancia de Guardian y mostrar SU marca, no la de
// Elea a la fuerza. `GET /api/branding` es la config en runtime; sin ninguna variable
// HUB_BRAND_* seteada, el default debe ser NEUTRO (nunca "Elea").
const test = require('node:test');
const assert = require('node:assert');
const request = require('supertest');
const { startMockServer } = require('../mock-servers');

async function setupApp(brandEnv) {
  const backend = await startMockServer((req, res) => { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{}'); });
  const engine = await startMockServer((req, res) => { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{}'); });
  process.env.ELEA_BACKEND_URL = backend.url;
  process.env.ANYTHINGLLM_URL = engine.url;
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  process.env.MASKING_VIRTUAL_KEY = 'test-mask-key';
  for (const k of ['HUB_BRAND_NAME', 'HUB_BRAND_TAGLINE', 'HUB_BRAND_LOGO_URL', 'HUB_BRAND_TENANT_LABEL', 'HUB_BRAND_GOVERNANCE_LABEL']) {
    delete process.env[k];
  }
  Object.assign(process.env, brandEnv || {});
  delete require.cache[require.resolve('../../server.js')];
  const app = require('../../server.js');
  return { app, backend, engine };
}

test('sin variables de marca configuradas, el default es neutro (nunca "Elea")', async (t) => {
  const { app, backend, engine } = await setupApp();
  t.after(async () => { await backend.close(); await engine.close(); });

  const res = await request(app).get('/api/branding');
  assert.strictEqual(res.status, 200);
  assert.ok(!/elea/i.test(res.body.name), `el nombre default no debe mencionar "Elea": ${res.body.name}`);
  assert.ok(!/elea/i.test(res.body.tagline || ''), `el tagline default no debe mencionar "Elea": ${res.body.tagline}`);
});

test('con HUB_BRAND_* configuradas (instalación de Elea), la marca real se refleja', async (t) => {
  const { app, backend, engine } = await setupApp({
    HUB_BRAND_NAME: 'Eleia Hub',
    HUB_BRAND_TENANT_LABEL: 'Laboratorios ELEA',
    HUB_BRAND_GOVERNANCE_LABEL: 'Eleia GuardIAn',
  });
  t.after(async () => { await backend.close(); await engine.close(); });

  const res = await request(app).get('/api/branding');
  assert.strictEqual(res.status, 200);
  assert.strictEqual(res.body.name, 'Eleia Hub');
  assert.strictEqual(res.body.tenantLabel, 'Laboratorios ELEA');
  assert.strictEqual(res.body.governanceLabel, 'Eleia GuardIAn');
});

test('con marca de OTRO cliente (simula una segunda instancia, no Elea), no queda nada de Elea', async (t) => {
  const { app, backend, engine } = await setupApp({
    HUB_BRAND_NAME: 'Sentinel Hub',
    HUB_BRAND_TENANT_LABEL: 'Evidenze',
    HUB_BRAND_GOVERNANCE_LABEL: 'Sentinel',
  });
  t.after(async () => { await backend.close(); await engine.close(); });

  const res = await request(app).get('/api/branding');
  assert.strictEqual(res.status, 200);
  assert.ok(!/elea/i.test(JSON.stringify(res.body)), `no debe quedar ningún rastro de Elea: ${JSON.stringify(res.body)}`);
  assert.strictEqual(res.body.name, 'Sentinel Hub');
});
