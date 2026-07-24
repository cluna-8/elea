/// <reference types="vite/client" />

// Declara los tipos de los assets que Vite resuelve como módulos (`import logo from
// "../logo.png"` en services/branding.ts). Sin esto `tsc` no sabe qué es un .png y el build
// oficial falla — parte del arreglo del gate de tipos que el frontend no tenía.
