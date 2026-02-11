/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./*.{js,ts,jsx,tsx}",        // Matches App.jsx in the same folder
    "./src/**/*.{js,ts,jsx,tsx}", // Matches if you ever move files into a src folder
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}