import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
// Fuentes AUTO-HOSPEDADAS (FR-006, air-gap): Vite las bundlea localmente, 0 CDN
// en runtime. Reemplaza el viejo @import al CDN de Google Fonts de index.css.
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/inter/700.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import '@fontsource/jetbrains-mono/600.css'
import './index.css'
import { loadBranding } from './services/branding'

// La marca es config en runtime (spec 020 US2): se resuelve ANTES del primer
// render para no flashear la marca default sobre una instancia rebrandeada.
loadBranding().finally(() => {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
})
