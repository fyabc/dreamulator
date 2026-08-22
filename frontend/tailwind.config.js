/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        space: {
          bg: '#0a0a1a',
          panel: '#12122a',
          border: '#2a2a5a',
          surface: '#1a1a3a',
        },
        neon: {
          cyan: '#00d4ff',
          purple: '#7b2fbe',
          blue: '#4466ff',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}
