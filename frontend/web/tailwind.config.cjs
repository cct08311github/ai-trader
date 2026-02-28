/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      boxShadow: {
        panel: '0 0 0 1px rgba(30, 41, 59, 0.6), 0 10px 30px rgba(0,0,0,0.35)'
      }
    }
  },
  plugins: []
}
