import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Spec 044 (Setup, T002): Vitest 2.x — pineado a la misma línea mayor que Vite 5, ya
// presente en devDependencies. No se toca vite.config.ts (build de producción); este
// archivo es solo para tests.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.test.{ts,tsx}'],
  },
});
