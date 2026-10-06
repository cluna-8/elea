// Ícono del menú (dos flechas que se cruzan), en SVG propio: las páginas de plugin no
// dependen de paquetes de la consola más allá de React.
import React from "react";

export const RedirectIcon: React.FC<{ className?: string; "aria-hidden"?: boolean | "true" | "false" }> = props => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"
    strokeLinejoin="round" width={24} height={24} {...props}>
    <path d="M16 3h5v5" /><path d="M4 20 21 3" /><path d="M21 16v5h-5" /><path d="m15 15 6 6" /><path d="M4 4l5 5" />
  </svg>
);
