/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Colores de MARCA como CSS vars (spec 020 US2): el branding pack los
        // overridea en runtime; los defaults (idénticos a los de siempre) viven
        // en index.css. Tripletas RGB + <alpha-value> para que los
        // modificadores de opacidad (bg-primary/30) sigan funcionando.
        background: "rgb(var(--brand-background) / <alpha-value>)", // Deep slate/navy
        panel: "rgb(var(--brand-panel) / <alpha-value>)",           // Lighter panel slate
        primary: "rgb(var(--brand-primary) / <alpha-value>)",       // Calm Cyan
        success: "#06d6a0",    // Health Green
        warning: "#ffd166",    // Warm Yellow
        danger: "#ef476f",     // Warning Red
        text: {
          primary: "#f8f9fa",  // Off-white for readability (WCAG AAA)
          secondary: "#94a3b8",// Muted slate
        }
      },
      fontFamily: {
        sans: ["Fira Sans", "sans-serif"],
        mono: ["Fira Code", "monospace"],
      },
      boxShadow: {
        focus: "0 0 0 3px rgba(0, 180, 216, 0.5)",
      }
    },
  },
  plugins: [],
}
