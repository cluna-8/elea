/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // === Tokens 029 (tema claro Foundry) — FUENTE ÚNICA en index.css ===
        // Tripletas RGB + <alpha-value> para conservar los modificadores de
        // opacidad de tailwind (bg-primary/30, bg-danger/10, ...).
        canvas: "rgb(var(--canvas) / <alpha-value>)",            // fondo de página
        surface: {
          DEFAULT: "rgb(var(--surface) / <alpha-value>)",       // cards/sidebar/inputs
          2: "rgb(var(--surface-2) / <alpha-value>)",           // headers tabla/hovers
        },
        border: {
          DEFAULT: "rgb(var(--border) / <alpha-value>)",        // bordes card/input
          strong: "rgb(var(--border-strong) / <alpha-value>)",  // divisores marcados
        },
        text: {
          primary: "rgb(var(--text) / <alpha-value>)",          // #242424
          secondary: "rgb(var(--text-secondary) / <alpha-value>)", // #616161
          tertiary: "rgb(var(--text-tertiary) / <alpha-value>)",   // #8a8886
        },
        primary: {
          DEFAULT: "rgb(var(--primary) / <alpha-value>)",       // acento (brand)
          hover: "rgb(var(--primary-hover) / <alpha-value>)",
          tint: "rgb(var(--primary-tint) / <alpha-value>)",
        },
        // Semánticos: DEFAULT = texto oscuro legible, bg = fondo tenue de pill.
        ok:     { DEFAULT: "rgb(var(--ok-text) / <alpha-value>)",     bg: "rgb(var(--ok-bg) / <alpha-value>)" },
        warn:   { DEFAULT: "rgb(var(--warn-text) / <alpha-value>)",   bg: "rgb(var(--warn-bg) / <alpha-value>)" },
        danger: { DEFAULT: "rgb(var(--danger-text) / <alpha-value>)", bg: "rgb(var(--danger-bg) / <alpha-value>)" },
        info:   { DEFAULT: "rgb(var(--info-text) / <alpha-value>)",   bg: "rgb(var(--info-bg) / <alpha-value>)" },

        // === Compat: clases legacy de las páginas aún-no-restyle-adas ===
        // Se remapean a valores CLAROS para que no queden ilegibles hasta que
        // el minion de cada página las migre al kit. NO usar en código nuevo.
        background: "rgb(var(--canvas) / <alpha-value>)",   // legacy bg-background → canvas
        panel: "rgb(var(--surface) / <alpha-value>)",       // legacy bg-panel → surface blanca
        success: "rgb(var(--ok-text) / <alpha-value>)",     // legacy text-success
        warning: "rgb(var(--warn-text) / <alpha-value>)",   // legacy text-warning
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      borderRadius: {
        card: "8px",
      },
      boxShadow: {
        // Sombra suave de card (spec 029) + focus con el acento.
        card: "0 1px 2px rgba(0,0,0,.06), 0 0 1px rgba(0,0,0,.08)",
        focus: "0 0 0 3px rgb(var(--primary) / 0.35)",
      },
    },
  },
  plugins: [],
}
