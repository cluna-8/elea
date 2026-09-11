// Enmascarado real de .xlsx (spec 046, cierra el gap confirmado en vivo el 11-sep: un
// archivo real de un cliente con CUIT/email/teléfono/domicilio volvió del motor sin
// ninguna protección). Doble HTTP real (node:http) de /gw/inspect — `maskXlsxBuffer` le
// habla por `fetch` de verdad. Se llama directo a `maskXlsxBuffer` (exportada en
// server.js solo para este test) porque el doble HTTP compartido (mock-servers.js)
// concatena el body como texto y corrompería un .xlsx binario antes de poder inspeccionarlo.
const test = require('node:test');
const assert = require('node:assert');
const ExcelJS = require('exceljs');
const { startMockServer } = require('../mock-servers');

async function construirXlsxDePrueba() {
  const wb = new ExcelJS.Workbook();
  const ws = wb.addWorksheet('Ventas');
  ws.addRow(['depto', 'contacto', 'monto']); // encabezado — NUNCA debe llegar a /gw/inspect
  ws.addRow(['Ventas', 'Julian Perez', 1200]);
  ws.addRow(['Marketing', 'Maria Gomez', 300]);
  return Buffer.from(await wb.xlsx.writeBuffer());
}

test('maskXlsxBuffer: enmascara celda por celda, nunca el encabezado, nunca los números', async (t) => {
  const textosRecibidos = [];
  const backend = await startMockServer((req, res, body) => {
    const send = (status, json) => {
      res.writeHead(status, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(json));
    };
    const [pathname] = req.url.split('?');
    if (req.method === 'POST' && pathname === '/gw/inspect') {
      textosRecibidos.push(body.text);
      // Enmascarado determinista y simple: cualquier texto con "Julian" o "Maria" se
      // reemplaza por un placeholder reconocible — alcanza para probar que el reemplazo
      // llega a la celda correcta sin tocar las demás.
      const masked = /Julian|Maria/.test(body.text || '') ? '[PERSON_TEST]' : body.text;
      return send(200, { ok: true, masked, entities: [] });
    }
    return send(404, { detail: 'no usado en este test' });
  });
  process.env.ELEA_BACKEND_URL = backend.url;
  process.env.ANYTHINGLLM_URL = 'http://127.0.0.1:1';
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  process.env.MASKING_VIRTUAL_KEY = 'test-mask-key';
  delete require.cache[require.resolve('../../server.js')];
  const { maskXlsxBuffer } = require('../../server.js');
  t.after(async () => { await backend.close(); });

  const xlsxOriginal = await construirXlsxDePrueba();
  const { buffer, blocked, entities, documentId } =
    await maskXlsxBuffer(xlsxOriginal, { actingUserId: 'ana-id' });

  assert.strictEqual(blocked, false);
  assert.ok(documentId);

  // El encabezado y las celdas numéricas NUNCA se mandan al analizador — 4 llamadas, una
  // por cada celda de TEXTO de datos (depto y contacto de las 2 filas; "monto", numérico,
  // ninguna). "depto" también es texto de datos, no encabezado — se manda igual que
  // "contacto" (mismo gap ya documentado para valores categóricos, ver tasks.md); acá el
  // mock solo enmascara lo que matchea nombres, así que "Ventas"/"Marketing" vuelven tal
  // cual y "Julian Perez"/"Maria Gomez" vuelven reemplazados.
  assert.deepStrictEqual(textosRecibidos, ['Ventas', 'Julian Perez', 'Marketing', 'Maria Gomez']);

  // El .xlsx resultante es un archivo real, parseable — no un blob corrupto.
  const wbResultado = new ExcelJS.Workbook();
  await wbResultado.xlsx.load(buffer);
  const ws = wbResultado.getWorksheet('Ventas');

  // Encabezado intacto, textual — NUNCA pasó por el analizador (no está en textosRecibidos).
  assert.deepStrictEqual(ws.getRow(1).values.slice(1), ['depto', 'contacto', 'monto']);
  // Fila de datos: monto (numérico) intacto; depto y contacto pasaron por el analizador —
  // solo contacto matchea el mock de PII y sale reemplazado.
  assert.deepStrictEqual(ws.getRow(2).values.slice(1), ['Ventas', '[PERSON_TEST]', 1200]);
  assert.deepStrictEqual(ws.getRow(3).values.slice(1), ['Marketing', '[PERSON_TEST]', 300]);

  assert.ok(entities.length === 0 || Array.isArray(entities)); // shape correcta, mock no devuelve entities reales
});

test('maskXlsxBuffer: una hoja bloqueada por gobernanza bloquea todo el documento', async (t) => {
  const backend = await startMockServer((req, res, body) => {
    const send = (status, json) => {
      res.writeHead(status, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(json));
    };
    if (req.method === 'POST' && req.url.split('?')[0] === '/gw/inspect') {
      return send(200, { ok: true, blocked: true, motivo: 'contenido sensible detectado', entities: [] });
    }
    return send(404, {});
  });
  process.env.ELEA_BACKEND_URL = backend.url;
  process.env.ANYTHINGLLM_URL = 'http://127.0.0.1:1';
  process.env.ANYTHINGLLM_API_KEY = 'test-key';
  process.env.MASKING_VIRTUAL_KEY = 'test-mask-key';
  delete require.cache[require.resolve('../../server.js')];
  const { maskXlsxBuffer } = require('../../server.js');
  t.after(async () => { await backend.close(); });

  const xlsxOriginal = await construirXlsxDePrueba();
  const result = await maskXlsxBuffer(xlsxOriginal, { actingUserId: 'ana-id' });
  assert.strictEqual(result.blocked, true);
  assert.strictEqual(result.motivo, 'contenido sensible detectado');
});
