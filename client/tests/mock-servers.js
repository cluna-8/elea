// Dobles HTTP reales (node:http, sin mocking de módulos) del backend Guardian y del
// motor de documentos — Eleia Hub habla con ellos por HTTP de verdad (fetch), así que el
// doble más honesto es OTRO servidor HTTP, no un mock de `fetch`. Ambos escuchan en un
// puerto libre (0) y devuelven respuestas programables por test.
const http = require('node:http');

function startMockServer(handler) {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      let body = '';
      req.on('data', (chunk) => { body += chunk; });
      req.on('end', () => {
        let parsed = {};
        try { parsed = body ? JSON.parse(body) : {}; } catch { parsed = {}; }
        handler(req, res, parsed);
      });
    });
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      resolve({ server, url: `http://127.0.0.1:${port}`, close: () => new Promise((r) => server.close(r)) });
    });
  });
}

module.exports = { startMockServer };
