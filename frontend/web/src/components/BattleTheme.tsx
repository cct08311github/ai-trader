/**
 * BattleTheme.tsx — Kyo Nakamura's War Terminal Design System
 *
 * Injects Google Fonts + global CSS variables + animations.
 * Import this ONCE in App.jsx before any battle UI renders.
 *
 * Variants:
 *   A → "作戰終端機" (War Terminal) 墨戰黑 + 霓虹綠/血紅  [DEFAULT]
 *   B → "霓虹夜市"    (Neon Night Market) 深紫 + 粉綠/金
 *   C → "廟宇金光"    (Temple Gold) 啞光黑 + 金箔漸層
 */

import { useEffect } from 'react'

// ── Font URLs ─────────────────────────────────────────────────────────────────
const FONT_URL = [
  // Noto Sans TC — Chinese legibility
  'https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@300;400;500;700;900&display=swap',
  // Share Tech Mono — terminal / data readouts
  'https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap',
  // JetBrains Mono — code & numbers
  'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&display=swap',
  // Fira Code — ligatures for special chars
  'https://fonts.googleapis.com/css2?family=Fira+Code:wght@300;400;500;600;700&display=swap',
].join('&family=JetBrains+Mono:wght@300;400;500;600;700&family=Fira+Code:wght@300;400;500;600;700&')

// ── Variant token sets ────────────────────────────────────────────────────────
const VARIANTS = {
  A: {
    // 作戰終端機 War Terminal — 墨戰黑 + 霓虹綠/血紅
    '--bg':            '8 9 13',
    '--text':          '226 232 240',
    '--surface':       '15 23 42',
    '--border':        '51 65 85',
    '--muted':         '100 116 139',
    '--card':          '13 19 30',
    '--card-alt':      '20 28 45',
    '--shadow':        '0 0 0',
    '--accent':        '16 185 129',   // 霓虹綠
    '--accent-glow':   '16 185 129',
    '--danger':        '225 29 72',    // 血紅
    '--danger-glow':   '244 63 94',
    '--warn':          '251 146 60',   // 熔岩橙
    '--info':          '6 182 212',    // 電光青
    '--gold':          '161 138 90',  // 啞光金
    '--up':            '16 185 129',
    '--up-glow':       '16 185 129 0.4',
    '--down':          '225 29 72',
    '--down-glow':     '244 63 94 0.4',
    // Night-market blink for Variant B override only
    '--blink':         'transparent',
    // Fonts
    '--font-ui':       '"Noto Sans TC", system-ui, sans-serif',
    '--font-mono':     '"Share Tech Mono", "JetBrains Mono", monospace',
    '--font-data':     '"Fira Code", "JetBrains Mono", monospace',
    // ECG / pulse colours
    '--ecg-up':        '#10b981',
    '--ecg-down':      '#e11d48',
    '--ecg-ball':      '#34d399',
  },
  B: {
    // 霓虹夜市 Neon Night Market — 深紫 + 粉綠/金 + 夜市閃爍
    '--bg':            '15 10 30',
    '--text':          '237 233 254',
    '--surface':       '30 20 60',
    '--border':        '108 60 180',
    '--muted':         '139 92 246',
    '--card':          '25 15 50',
    '--card-alt':      '35 20 65',
    '--shadow':        '0 0 0',
    '--accent':        '52 211 153',   // 粉綠
    '--accent-glow':   '52 211 153',
    '--danger':        '251 191 36',   // 金
    '--danger-glow':   '251 191 36',
    '--warn':          '244 114 22',
    '--info':          '167 139 250',
    '--gold':          '251 191 36',
    '--up':            '52 211 153',
    '--up-glow':       '52 211 153 0.4',
    '--down':          '251 191 36',
    '--down-glow':     '251 191 36 0.4',
    '--blink':         '#a855f7',      // 夜市閃爍燈
    '--font-ui':       '"Noto Sans TC", system-ui, sans-serif',
    '--font-mono':     '"Share Tech Mono", "JetBrains Mono", monospace',
    '--font-data':     '"Fira Code", "JetBrains Mono", monospace',
    '--ecg-up':        '#34d399',
    '--ecg-down':      '#fbbf24',
    '--ecg-ball':      '#6ee7b7',
  },
  C: {
    // 廟宇金光 Temple Gold — 啞光黑 + 金箔漸層 + 紅色警示
    '--bg':            '10 10 10',
    '--text':          '230 220 200',
    '--surface':       '22 18 14',
    '--border':        '90 70 40',
    '--muted':         '150 125 80',
    '--card':          '18 15 12',
    '--card-alt':      '25 20 16',
    '--shadow':        '0 0 0',
    '--accent':        '212 175 55',   // 金箔
    '--accent-glow':   '212 175 55',
    '--danger':        '185 28 28',    // 深紅警示
    '--danger-glow':   '220 38 38',
    '--warn':          '180 120 30',
    '--info':          '201 168 76',
    '--gold':          '212 175 55',
    '--up':            '180 140 50',
    '--up-glow':       '212 175 55 0.35',
    '--down':          '185 28 28',
    '--down-glow':     '220 38 38 0.35',
    '--blink':         'transparent',
    '--font-ui':       '"Noto Sans TC", system-ui, sans-serif',
    '--font-mono':     '"Share Tech Mono", "JetBrains Mono", monospace',
    '--font-data':     '"Fira Code", "JetBrains Mono", monospace',
    '--ecg-up':        '#d4af37',
    '--ecg-down':      '#b91c1c',
    '--ecg-ball':      '#f59e0b',
  },
}

// ── Global keyframes (injected once) ─────────────────────────────────────────
const GLOBAL_CSS = `
/* ── Digit pulse animation (ECG number tick) ── */
@keyframes digit-tick {
  0%   { transform: translateY(0);    opacity: 1; }
  40%  { transform: translateY(-4px);  opacity: 0.7; }
  100% { transform: translateY(0);     opacity: 1; }
}
.animate-digit-tick {
  animation: digit-tick 0.35s cubic-bezier(0.34,1.56,0.64,1);
}

/* ── ECG pulse ripple ── */
@keyframes ecg-pulse {
  0%   { box-shadow: 0 0 0 0   rgba(var(--ecg-ball), 0.7); }
  70%  { box-shadow: 0 0 0 12px rgba(var(--ecg-ball), 0); }
  100% { box-shadow: 0 0 0 0   rgba(var(--ecg-ball), 0); }
}
.animate-ecg-pulse {
  animation: ecg-pulse 1.8s cubic-bezier(0.22,1,0.36,1) infinite;
}

/* ── Neon glow breathe ── */
@keyframes neon-breathe {
  0%,100% { text-shadow: 0 0 4px  rgba(var(--accent)), 0 0 10px rgba(var(--accent)); opacity: 1; }
  50%      { text-shadow: 0 0 8px  rgba(var(--accent)), 0 0 20px rgba(var(--accent)), 0 0 40px rgba(var(--accent)); opacity: 0.92; }
}
.animate-neon-breathe {
  animation: neon-breathe 2.4s ease-in-out infinite;
}

/* ── Lava/ember pulse (Variant A danger) ── */
@keyframes lava-pulse {
  0%,100% { box-shadow: 0 0 6px  rgba(var(--danger)), 0 0 14px rgba(var(--danger)); }
  50%      { box-shadow: 0 0 14px rgba(var(--danger)), 0 0 32px rgba(var(--danger)), 0 0 60px rgba(var(--danger)); }
}
.animate-lava-pulse {
  animation: lava-pulse 1.6s ease-in-out infinite;
}

/* ── Glitch / static jitter ── */
@keyframes glitch-jitter {
  0%   { transform: translate(0,0) skewX(0deg);    clip-path: inset(0 0 95% 0); }
  10%  { transform: translate(-2px,1px) skewX(-0.5deg); clip-path: inset(10% 0 60% 0); }
  20%  { transform: translate(2px,-1px) skewX(0.5deg);  clip-path: inset(50% 0 20% 0); }
  30%  { transform: translate(-1px,2px) skewX(-0.3deg); clip-path: inset(80% 0 5% 0); }
  40%  { transform: translate(1px,-2px) skewX(0.3deg); clip-path: inset(0 0 0 0); }
  100% { transform: translate(0,0) skewX(0deg);        clip-path: inset(0 0 95% 0); }
}
.animate-glitch {
  animation: glitch-jitter 0.4s steps(1) forwards;
}

/* ── K-line entry flash ── */
@keyframes kline-zap {
  0%   { opacity: 0; transform: scaleY(0.1); filter: brightness(3) drop-shadow(0 0 8px rgba(var(--accent))); }
  60%  { opacity: 1; transform: scaleY(1.08); filter: brightness(1.5) drop-shadow(0 0 4px rgba(var(--accent))); }
  100% { opacity: 1; transform: scaleY(1);    filter: brightness(1)   drop-shadow(0 0 0px rgba(var(--accent))); }
}
.animate-kline-zap {
  animation: kline-zap 0.5s cubic-bezier(0.22,1,0.36,1) forwards;
}

/* ── Nuclear explosion overlay ── */
@keyframes nuclear-flash {
  0%   { opacity: 0; }
  15%  { opacity: 1; }
  100% { opacity: 1; }
}
.animate-nuclear-flash {
  animation: nuclear-flash 0.8s ease-out forwards;
}

/* ── Nuclear screen shake ── */
@keyframes nuclear-shake {
  0%,100% { transform: translate(0,0) rotate(0deg); }
  10%  { transform: translate(-8px, 4px) rotate(-0.5deg); }
  20%  { transform: translate( 8px,-4px) rotate( 0.5deg); }
  30%  { transform: translate(-6px, 6px) rotate(-0.3deg); }
  40%  { transform: translate( 6px,-6px) rotate( 0.3deg); }
  50%  { transform: translate(-4px, 4px) rotate(-0.2deg); }
  60%  { transform: translate( 4px,-4px) rotate( 0.2deg); }
  70%  { transform: translate(-2px, 2px) rotate(-0.1deg); }
  80%  { transform: translate( 2px,-2px) rotate( 0.1deg); }
  90%  { transform: translate(-1px, 1px) rotate(0deg); }
}
.animate-nuclear-shake {
  animation: nuclear-shake 0.8s cubic-bezier(0.36,0.07,0.19,0.97) both;
}

/* ── Night-market blink (Variant B only) ── */
@keyframes night-blink {
  0%,100% { opacity: 1; text-shadow: 0 0 6px rgba(168,85,247,0.8); }
  49%      { opacity: 1; text-shadow: 0 0 6px rgba(168,85,247,0.8); }
  50%      { opacity: 0.2; text-shadow: 0 0 2px rgba(168,85,247,0.3); }
  51%      { opacity: 1; text-shadow: 0 0 6px rgba(168,85,247,0.8); }
}
.animate-night-blink {
  animation: night-blink 1.5s step-end infinite;
}

/* ── Gold shimmer (Variant C) ── */
@keyframes gold-shimmer {
  0%   { background-position: 200% center; }
  100% { background-position: -200% center; }
}
.bg-gold-shimmer {
  background: linear-gradient(90deg, #d4af37 0%, #f5d76e 25%, #d4af37 50%, #f5d76e 75%, #d4af37 100%);
  background-size: 200% auto;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: gold-shimmer 3s linear infinite;
}

/* ── Card explosion expand ── */
@keyframes card-explode {
  from { transform: scale(0.92) translateY(8px); opacity: 0; }
  to   { transform: scale(1)    translateY(0);   opacity: 1; }
}
.animate-card-explode {
  animation: card-explode 0.35s cubic-bezier(0.34,1.56,0.64,1) forwards;
}

/* ── Floating P&L text ── */
@keyframes pnl-float {
  0%   { transform: translateY(0px);  opacity: 0.6; }
  50%  { transform: translateY(-12px); opacity: 1; }
  100% { transform: translateY(-6px);  opacity: 0.85; }
}
.animate-pnl-float {
  animation: pnl-float 3s ease-in-out infinite;
}

/* ── Scrollbar theming ── */
* {
  scrollbar-width: thin;
  scrollbar-color: rgb(var(--border)) transparent;
}
::selection {
  background: rgba(var(--accent), 0.25);
}

/* ── Font smooth ── */
body {
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
`

// ── Component ────────────────────────────────────────────────────────────────
let cssInjected = false

export function useBattleTheme(variant = 'A') {
  useEffect(() => {
    // Inject fonts
    if (!document.getElementById('battle-fonts')) {
      const link = document.createElement('link')
      link.id = 'battle-fonts'
      link.rel = 'stylesheet'
      link.href = FONT_URL
      document.head.appendChild(link)
    }

    // Inject global keyframes + reset CSS (once)
    if (!cssInjected) {
      const style = document.createElement('style')
      style.id = 'battle-global-css'
      style.textContent = GLOBAL_CSS
      document.head.appendChild(style)
      cssInjected = true
    }

    // Apply variant CSS variables to :root
    const tokens = VARIANTS[variant] ?? VARIANTS['A']
    const root = document.documentElement
    Object.entries(tokens).forEach(([k, v]) => root.style.setProperty(k, String(v)))

    // Variant B: activate night-market blink on body
    if (variant === 'B') {
      document.body.classList.add('night-market')
    } else {
      document.body.classList.remove('night-market')
    }

    return () => {
      // Don't remove on unmount — theme should persist across navigations
    }
  }, [variant])
}

export { VARIANTS }
export default useBattleTheme
