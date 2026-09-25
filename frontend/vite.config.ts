import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// El repo no traía vite.config: dev funcionaba con los defaults de Vite. Para el build
// de prod fijamos el plugin de React (JSX runtime automático) y outDir=dist. base='/'
// porque el SPA se sirve en la raíz del dominio y la API va por /api/v1 (mismo origen).
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: '/',
  // Páginas de plugins (src/plugins/registry.ts): `@plugin-pages` apunta al directorio que
  // diga VITE_PLUGIN_PAGES_DIR (relativo a este archivo o absoluto) o, por defecto, a
  // `src/plugins/pages/`, vacío → build sin plugins. `dedupe` hace que un plugin que vive
  // fuera de este árbol use el MISMO React de la consola y no uno propio.
  resolve: {
    alias: {
      '@plugin-pages': path.resolve(__dirname,
        loadEnv(mode, process.cwd(), 'VITE_').VITE_PLUGIN_PAGES_DIR || 'src/plugins/pages'),
    },
    dedupe: ['react', 'react-dom'],
  },
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
    // Instalador (14-sep): el panel se sirve con `vite dev` detrás de un hostname del cliente
    // (eleavdmia); Vite 6 bloquea cualquier host que no sea localhost salvo que se permita acá.
    allowedHosts: true,
    proxy: {
      // BACKEND_URL: override de URL completa para apuntar el dev server a un backend fuera
      // de la red del compose (p.ej. BACKEND_URL=http://localhost:8091 para el stack sentinel-*
      // ya corriendo en el host). Sin él, cae al patrón de la red del compose (backend:8000).
      '/api': { target: process.env.BACKEND_URL || `http://${process.env.BACKEND_HOST || 'backend'}:8000`, changeOrigin: true },
      '/gw': { target: process.env.BACKEND_URL || `http://${process.env.BACKEND_HOST || 'backend'}:8000`, changeOrigin: true },
    },
  },
}))
