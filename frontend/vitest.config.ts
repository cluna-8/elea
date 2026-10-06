import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'node:path';

// Spec 044 (Setup, T002): Vitest 2.x — pineado a la misma línea mayor que Vite 5, ya
// presente en devDependencies. No se toca vite.config.ts (build de producción); este
// archivo es solo para tests.
export default defineConfig({
  plugins: [react()],
  // Costura S3: el registry importa `@plugin-pages`; en los tests de la consola apunta
  // siempre al directorio vacío por defecto (el build sin plugins).
  resolve: { alias: { '@plugin-pages': path.resolve(__dirname, 'src/plugins/pages') } },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    // src/plugins/registry.test.ts viene con la costura S3 (páginas de plugins).
    include: ['tests/**/*.test.{ts,tsx}', 'src/**/*.test.{ts,tsx}'],
  },
});
