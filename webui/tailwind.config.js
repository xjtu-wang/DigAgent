/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0f172a",
        mist: "#e2e8f0",
        dune: "#f8fafc",
        ember: "#9a3412",
        pine: "#166534",
        sea: "#0f766e",
      },
      boxShadow: {
        panel: "0 18px 60px rgba(15, 23, 42, 0.12)",
      },
      fontFamily: {
        display: ["Georgia", "serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
};

