/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        th: {
          bg:       'rgb(var(--bg) / <alpha-value>)',
          text:     'rgb(var(--text) / <alpha-value>)',
          surface:  'rgb(var(--surface) / <alpha-value>)',
          border:   'rgb(var(--border) / <alpha-value>)',
          muted:    'rgb(var(--muted) / <alpha-value>)',
          card:     'rgb(var(--card) / <alpha-value>)',
          'card-alt':'rgb(var(--card-alt) / <alpha-value>)',
          accent:   'rgb(var(--accent) / <alpha-value>)',
          danger:   'rgb(var(--danger) / <alpha-value>)',
          warn:     'rgb(var(--warn) / <alpha-value>)',
          info:     'rgb(var(--info) / <alpha-value>)',
          gold:     'rgb(var(--gold) / <alpha-value>)',
          up:       'rgb(var(--up) / <alpha-value>)',
          down:     'rgb(var(--down) / <alpha-value>)',
        }
      },
      boxShadow: {
        panel: '0 0 0 1px rgb(var(--border) / 0.5), 0 10px 30px rgb(var(--shadow) / 0.2)',
        'neon-up':   '0 0 8px rgba(var(--up-glow)), 0 0 20px rgba(var(--up-glow))',
        'neon-down': '0 0 8px rgba(var(--down-glow)), 0 0 20px rgba(var(--down-glow))',
        'lava':      '0 0 8px rgba(var(--danger)), 0 0 20px rgba(var(--danger))',
      },
      fontFamily: {
        ui:   'var(--font-ui)',
        mono: 'var(--font-mono)',
        data: 'var(--font-data)',
      },
    }
  },
  plugins: []
}
