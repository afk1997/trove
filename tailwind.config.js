/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./templates/**/*.html"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        paper: "var(--paper)",
        light: "var(--light)",
        teal: "var(--teal)",
        orange: "var(--orange)",
        forest: "var(--forest)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["Fraunces", "Playfair Display", "Georgia", "serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
      borderRadius: {
        DEFAULT: "4px",
        lg: "8px",
      },
    },
  },
  plugins: [],
};
