// Ícono del menú (pila de capas), en SVG propio: las páginas de plugin no dependen de paquetes
// de la consola más allá de React.
import React from "react";

export const CatalogIcon: React.FC<{ className?: string; "aria-hidden"?: boolean | "true" | "false" }> = props => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"
    strokeLinejoin="round" width={24} height={24} {...props}>
    <path d="m12 3 9 5-9 5-9-5 9-5Z" /><path d="m3 13 9 5 9-5" /><path d="m3 17.5 9 5 9-5" />
  </svg>
);
