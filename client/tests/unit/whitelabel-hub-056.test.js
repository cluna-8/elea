// Spec 056 (T015, FR-013, FR-014, research D14): marca blanca del Hub, solo con `node:fs` y sin
// dependencias, para que corra en `npm test` y en `make -C deploy check-hub-whitelabel`.
//
//  - Archivos NUEVOS de la 056 (`client/sso.js`, `client/public/sso-ui.js`): ni la lista compartida
//    `deploy/release/checks/prohibited_names.txt`, ni los motores internos de documentos y
//    presentaciones (lista local, abajo), ni `Elea`/`Eleia`.
//  - `client/public/index.html` y `client/server.js` completos: solo la lista compartida (ya
//    contienen `Elea`/`ELEA_*` y comentarios que nombran un motor interno; límite honesto, lo
//    cubre la revisión del PR).
//  - `index.html` no lleva texto visible nuevo de la 056: todo sale de `sso-ui.js` (N6 del QA v2).
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const CLIENT = path.join(__dirname, '../..');
const REPO = path.join(CLIENT, '..');

// Motores internos de documentos y presentaciones (lista local: no se toca la compartida).
const MOTORES_INTERNOS = ['anythingllm', 'anything-llm', 'anything llm', 'presenton', 'docgen'];
const MARCAS = ['elea', 'eleia'];

function nombresProhibidos() {
  const txt = fs.readFileSync(path.join(REPO, 'deploy/release/checks/prohibited_names.txt'), 'utf8');
  return txt.split('\n').map((l) => l.trim()).filter((l) => l && !l.startsWith('#')).map((l) => l.toLowerCase());
}

function leer(rel) {
  const abs = path.join(CLIENT, rel);
  assert.ok(fs.existsSync(abs), `falta ${rel}`);
  return fs.readFileSync(abs, 'utf8').toLowerCase();
}

test('la lista compartida de nombres prohibidos existe y no está vacía', () => {
  assert.ok(nombresProhibidos().length > 0);
});

for (const rel of ['sso.js', 'public/sso-ui.js']) {
  test(`${rel}: sin nombres de la lista compartida, de motores internos ni Elea/Eleia`, () => {
    const src = leer(rel);
    for (const n of [...nombresProhibidos(), ...MOTORES_INTERNOS, ...MARCAS]) {
      assert.ok(!src.includes(n), `${rel} contiene «${n}»`);
    }
  });
}

for (const rel of ['public/index.html', 'server.js']) {
  test(`${rel}: sin nombres de la lista compartida`, () => {
    const src = leer(rel);
    for (const n of nombresProhibidos()) {
      assert.ok(!src.includes(n), `${rel} contiene «${n}»`);
    }
  });
}

test('index.html no lleva el literal del botón ni otro texto visible nuevo de la 056 (N6 del QA v2)', () => {
  const html = fs.readFileSync(path.join(CLIENT, 'public/index.html'), 'utf8');
  assert.ok(!html.includes('Ingresar con Microsoft'));
  assert.ok(!/microsoft/i.test(html), 'index.html no debe nombrar el directorio: los textos salen de sso-ui.js');
});
