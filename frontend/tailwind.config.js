/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#0b1329", // Deep slate/navy
        panel: "#1c2541",      // Lighter panel slate
        primary: "#00b4d8",    // Calm Cyan
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
