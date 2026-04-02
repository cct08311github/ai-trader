/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        th: {
          bg:      'rgb(var(--bg) / <alpha-value>)',
          text:    'rgb(var(--text) / <alpha-value>)',
          surface: 'rgb(var(--surface) / <alpha-value>)',
          border:  'rgb(var(--border) / <alpha-value>)',
          muted:   'rgb(var(--muted) / <alpha-value>)',
          card:    'rgb(var(--card) / <alpha-value>)',
          'card-alt': 'rgb(var(--card-alt) / <alpha-value>)',
          accent:  'rgb(var(--accent) / <alpha-value>)',
        }
      },
      boxShadow: {
        panel: '0 0 0 1px rgb(var(--border) / 0.5), 0 10px 30px rgb(var(--shadow) / 0.2)'
      }
    }
  },
  plugins: []
}
