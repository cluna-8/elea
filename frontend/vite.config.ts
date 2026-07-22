import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// El repo no traía vite.config: dev funcionaba con los defaults de Vite. Para el build
// de prod fijamos el plugin de React (JSX runtime automático) y outDir=dist. base='/'
// porque el SPA se sirve en la raíz del dominio y la API va por /api/v1 (mismo origen).
export default defineConfig({
  plugins: [react()],
  base: '/',
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1500,
  },
})
