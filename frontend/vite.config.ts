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
  // El SPA llama a /api/v1 y /gw en el MISMO origen (así evita mixed-content en prod, donde
  // el ingress Caddy los enruta al backend). En dev servido por Vite no había proxy, así que
  // esas rutas devolvían el index.html del SPA — cualquier fetch fallaba con "<!doctype … is
  // not valid JSON". El proxy dev las manda al backend del compose (host BACKEND_HOST, 8000
  // dentro de la red). Solo aplica a `vite dev`; el build de prod lo ignora.
  server: {
    host: true,
    proxy: {
      // BACKEND_URL: override de URL completa para apuntar el dev server a un backend fuera
      // de la red del compose (p.ej. BACKEND_URL=http://localhost:8091 para el stack sentinel-*
      // ya corriendo en el host). Sin él, cae al patrón de la red del compose (backend:8000).
      '/api': { target: process.env.BACKEND_URL || `http://${process.env.BACKEND_HOST || 'backend'}:8000`, changeOrigin: true },
      '/gw': { target: process.env.BACKEND_URL || `http://${process.env.BACKEND_HOST || 'backend'}:8000`, changeOrigin: true },
    },
  },
})
