#!/usr/bin/env node
// Spec 044 (US5, T047): regresión de marca — recorre las superficies que un usuario o
// "ver código fuente" del navegador puede ver de verdad (nunca los logs de servidor ni
// los comentarios de `client/server.js`, que jamás se sirven) buscando términos
// prohibidos del motor/proveedor interno. Mismo criterio y misma disciplina de
// excepciones EXPLÍCITAS y cortas que `backend/tests/contract/test_branding_neutral_043.py`
// — nada de una allowlist amplia que termine ocultando fugas nuevas.
//
// Uso:
//   node tools/check-branding-neutral.js            # corre los objetivos default (ambos repos)
//   node tools/check-branding-neutral.js <archivo|dir> [...]   # objetivos custom
//
// Sale con código 1 y una lista de hallazgos si encuentra algo; 0 si no.
'use strict';

const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '..');

const TERMINOS_PROHIBIDOS = ['litellm', 'anythingllm', 'presidio', 'sentinel'];

// Excepciones EXPLÍCITAS: identificadores internos que nunca llegan como copy visible a
// una persona usuaria — ni en pantalla, ni en "ver código fuente" del HTML servido, ni en
// un mensaje de error que la UI muestre. Cada entrada documenta POR QUÉ es segura.
const EXCEPCIONES_DE_LINEA = [
  // localStorage keys (frontend/src/services/auth.ts) — nunca renderizadas, solo claves
  // internas del navegador; cambiarlas invalidaría sesiones existentes sin ningún
  // beneficio de marca real.
  /["'`]sentinel_session_token["'`]/,
  /["'`]sentinel_current_user["'`]/,
  // `guardian_type`/valor "presidio" — identificador de ENUM interno consumido por lógica
  // (`isPresidio`, `LOCAL_TYPES`), nunca el texto mostrado (ese es `guardian.name`, que
  // sale del backend ya neutro — ver contrato 6 de la 043).
  /guardian_type/,
  /["'`]presidio["'`]\s*[:,)]/,
  // Alias `litellm_params` deprecated de compatibilidad hacia atrás del contrato 6 — su
  // presencia en el tipo/schema es intencional y temporal, documentada en `api.ts`.
  /litellm_params/,
  // El default de fábrica de `branding.ts` (spec 020, pre-existente a la 043/044) es un
  // debate de branding del PRODUCTO BASE completo, no de esta feature — fuera de alcance
  // de T047-T052 (ver CHANGELOG de la 044 §branding). Excepción con dueño explícito.
  /DEFAULT_BRAND[\s\S]{0,40}name:\s*["'`]Sentinel/,
  /name:\s*["'`]Sentinel Secure AI Gateway["'`]/,
];

// Objetivos default — las superficies que esta feature (043/044) controla directamente.
// `client/server.js` se incluye SOLO para sus mensajes de error (líneas con `error:`),
// nunca sus comentarios (ver docstring arriba). El build de `frontend/` se escanea si
// existe `frontend/dist` (post `npm run build`); si no, se avisa y se saltea (no falla) —
// correrlo sin build previo daría un falso "todo limpio".
function objetivosDefault() {
  const objetivos = [
    path.join(REPO_ROOT, 'client', 'public'),
  ];
  const frontendDist = path.join(REPO_ROOT, 'frontend', 'dist');
  if (fs.existsSync(frontendDist)) objetivos.push(frontendDist);
  return objetivos;
}

const EXTENSIONES_TEXTO = new Set(['.html', '.js', '.css', '.json', '.svg', '.txt', '.md']);

function* archivosDe(objetivo) {
  const stat = fs.statSync(objetivo);
  if (stat.isFile()) { yield objetivo; return; }
  for (const entry of fs.readdirSync(objetivo, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === '.git') continue;
    const full = path.join(objetivo, entry.name);
    if (entry.isDirectory()) { yield* archivosDe(full); continue; }
    if (EXTENSIONES_TEXTO.has(path.extname(entry.name))) yield full;
  }
}

function esExcepcion(linea) {
  return EXCEPCIONES_DE_LINEA.some((re) => re.test(linea));
}

function escanearArchivo(filePath, soloLineasDeError) {
  const hallazgos = [];
  const contenido = fs.readFileSync(filePath, 'utf-8');
  const lineas = contenido.split('\n');
  lineas.forEach((linea, idx) => {
    if (soloLineasDeError && !/error\s*[:=]/i.test(linea)) return;
    const low = linea.toLowerCase();
    for (const termino of TERMINOS_PROHIBIDOS) {
      if (low.includes(termino) && !esExcepcion(linea)) {
        hallazgos.push({ file: filePath, line: idx + 1, termino, texto: linea.trim().slice(0, 160) });
      }
    }
  });
  return hallazgos;
}

function main(argv) {
  const objetivosArg = argv.slice(2);
  const hallazgos = [];

  if (objetivosArg.length > 0) {
    for (const objetivo of objetivosArg) {
      for (const f of archivosDe(path.resolve(objetivo))) {
        hallazgos.push(...escanearArchivo(f, false));
      }
    }
  } else {
    for (const objetivo of objetivosDefault()) {
      for (const f of archivosDe(objetivo)) {
        hallazgos.push(...escanearArchivo(f, false));
      }
    }
    // client/server.js: SOLO sus mensajes de error (nunca sus comentarios — no se sirven).
    const serverJs = path.join(REPO_ROOT, 'client', 'server.js');
    if (fs.existsSync(serverJs)) hallazgos.push(...escanearArchivo(serverJs, true));

    if (!fs.existsSync(path.join(REPO_ROOT, 'frontend', 'dist'))) {
      console.log('ℹ frontend/dist no existe — corré "npm run build" en frontend/ antes para incluirlo (no falla, solo se saltea).');
    }
  }

  if (hallazgos.length > 0) {
    console.error(`✗ ${hallazgos.length} término(s) prohibido(s) encontrado(s):\n`);
    for (const h of hallazgos) {
      console.error(`  ${path.relative(REPO_ROOT, h.file)}:${h.line}  [${h.termino}]  ${h.texto}`);
    }
    process.exit(1);
  }

  console.log('✓ branding neutro: sin términos prohibidos en los objetivos escaneados.');
  process.exit(0);
}

if (require.main === module) main(process.argv);
module.exports = { escanearArchivo, esExcepcion, TERMINOS_PROHIBIDOS };
