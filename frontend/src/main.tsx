import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
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
