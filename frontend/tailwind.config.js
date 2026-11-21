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
          bg: '#10191d',
          panel: '#162126',
          border: '#33434a',
          surface: '#202d32',
        },
        neon: {
          cyan: '#a8e6d4',
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
