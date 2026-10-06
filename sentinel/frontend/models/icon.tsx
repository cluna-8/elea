// Ícono del menú de «Modelos» (cubo), en SVG propio: las páginas de plugin no dependen de paquetes
// de la consola más allá de React.
import React from "react";

export const ModelsIcon: React.FC<{ className?: string; "aria-hidden"?: boolean | "true" | "false" }> = props => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"
    strokeLinejoin="round" width={24} height={24} {...props}>
    <path d="M21 8 12 3 3 8v8l9 5 9-5V8Z" /><path d="m3 8 9 5 9-5" /><path d="M12 13v8" />
  </svg>
);
