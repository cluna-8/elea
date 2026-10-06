// Tests de las páginas de consola de la capa 2 (spec 068). Corren con las dependencias de la
// consola: `node_modules` de este directorio es un enlace a `frontend/node_modules`
// (lo crea el build de la imagen, sentinel/docker/frontend.Dockerfile; en local:
// `ln -s ../../frontend/node_modules sentinel/frontend/node_modules`). Desde este directorio:
//   npx vitest run          (tests)
//   npx tsc -p .            (tipos, con las mismas reglas que la consola)
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@plugin-pages': path.resolve(__dirname, 'pages') },
    dedupe: ['react', 'react-dom'],
  },
  // Las páginas importan componentes de la consola (frontend/src), fuera de este directorio.
  server: { fs: { allow: [path.resolve(__dirname, '../..')] } },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./test-setup.ts'],
    include: ['redirect/**/*.test.{ts,tsx}', 'catalog/**/*.test.{ts,tsx}', 'models/**/*.test.{ts,tsx}', 'routing/**/*.test.{ts,tsx}'],
  },
});
