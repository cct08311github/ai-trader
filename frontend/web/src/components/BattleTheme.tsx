/**
 * BattleTheme.tsx -- Kyo Nakamura's "台股 AI 交易戰場" Design System
 *
 * ============================================================
 *   DESIGN MANIFESTO -- 台股 AI 交易戰場
 * ============================================================
 *
 *   Standard Tailwind dashboards fail because they were designed
 *   for SaaS onboarding flows and admin panels. They fail the
 *   trader because they suppress tension. Trading is war: every
 *   pixel must communicate urgency, risk, and the raw heartbeat
 *   of capital flowing through silicon arteries.
 *
 *   This design system draws from Taiwan's own visual DNA:
 *   -- The scorching red/green of TWSE ticker boards
 *   -- Night market neon bleeding into rain-soaked concrete
 *   -- Temple incense smoke curling through gold leaf
 *   -- CRT phosphor burn and VHS tracking errors
 *
 *   Three variants. Zero compromise.
 *
 * ============================================================
 *
 * MOODBOARD WINNER: Direction 2
 *   "Taiwan stock ticker board + cyberpunk glitch art + data streams"
 *
 * 3 never-before-seen visual elements:
 *   1. Glitch-split P&L digits with RGB chromatic aberration on tick
 *   2. ECG flatline-to-spike equity curves with cardiac warnings
 *   3. Radioactive contamination rings on bleeding positions
 *
 * ============================================================
 *
 * COLOR PALETTE:
 *
 *   Variant A "Brutalist Dark" (混凝土戰壕)
 *     #080A0F  Bunker Black     -- bg        (the void before market open)
 *     #E2E8F0  Phosphor White   -- text      (CRT terminal readout)
 *     #0F172A  Slate Bunker     -- surface   (concrete panels)
 *     #334155  Wire Grey        -- border    (rebar exposed)
 *     #64748B  Fog              -- muted     (distant artillery)
 *     #10B981  Neon Green       -- up        (victory / profit)
 *     #E11D48  Blood Red        -- down/stop (loss / danger / emergency)
 *     #FB923C  Lava Orange      -- warning   (approaching limit)
 *     #06B6D4  Electric Cyan    -- info      (system comms)
 *
 *   Variant B "Neon Night Market" (霓虹夜市)
 *     #0A061E  Deep Void Purple -- bg        (Ximending after midnight)
 *     #EDE9FE  Lavender Glow    -- text      (neon reflection on wet street)
 *     #1E1440  Dark Purple      -- surface   (night market stall shadow)
 *     #6C3CB4  Neon Purple      -- border    (LED strip edge)
 *     #8B5CF6  Orchid Haze      -- muted     (distant sign flicker)
 *     #34D399  Mint Neon        -- up        (green night-market light)
 *     #FBBF24  Golden Warning   -- down      (金色 danger lamp)
 *     #A78BFA  Violet Info      -- info      (purple tube glow)
 *
 *   Variant C "Wabi-Sabi Data" (侘寂數據)
 *     #0E0C08  Charcoal Earth   -- bg        (burnt wood / 焦炭)
 *     #C8B89A  Rice Paper       -- text      (和紙 warmth)
 *     #1A1610  Dark Umber       -- surface   (aged lacquer)
 *     #4A3A20  Earth Border     -- border    (dried clay crack)
 *     #8B7355  Weathered Stone  -- muted     (temple stone moss)
 *     #7BA05B  Moss Green       -- up        (growth through decay)
 *     #B91C1C  Cinnabar Red     -- down      (朱紅 temple warning)
 *     #C4A24D  Aged Gold        -- accent    (worn gold leaf)
 *
 * TYPOGRAPHY:
 *   UI:   Noto Sans TC (300-900) -- Chinese legibility paramount
 *   Mono: Share Tech Mono        -- military terminal readout
 *   Data: Fira Code              -- financial numbers with ligatures
 *
 * LAYOUT PRINCIPLES:
 *   -- Asymmetric 5:7 or 4:8 splits (never 6:6)
 *   -- Cards tilt, overlap, bleed past edges
 *   -- K-line chart as full-width SVG hero, not trapped in a card
 *   -- Emergency stop button visible at all times, not hidden in menus
 *   -- Position cards stack vertically like military intelligence briefings
 *
 * ============================================================
 */

import { useEffect } from 'react'

// ── Font URLs ─────────────────────────────────────────────────────────────────
const FONT_URL = [
  'https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@300;400;500;700;900&display=swap',
  'https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap',
  'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&display=swap',
  'https://fonts.googleapis.com/css2?family=Fira+Code:wght@300;400;500;600;700&display=swap',
].join('&family=JetBrains+Mono:wght@300;400;500;600;700&family=Fira+Code:wght@300;400;500;600;700&')

// ── Variant token sets ────────────────────────────────────────────────────────
export const VARIANTS = {
  // ═══════════════════════════════════════════════════
  // A: BRUTALIST DARK -- 混凝土戰壕
  //    Raw concrete + sharp edges + red warnings
  //    Emotional note: siege mentality, every trade is survival
  // ═══════════════════════════════════════════════════
  A: {
    '--bg':            '8 10 15',
    '--text':          '226 232 240',
    '--surface':       '15 23 42',
    '--border':        '51 65 85',
    '--muted':         '100 116 139',
    '--card':          '13 19 30',
    '--card-alt':      '20 28 45',
    '--shadow':        '0 0 0',
    '--accent':        '16 185 129',
    '--accent-glow':   '16 185 129',
    '--danger':        '225 29 72',
    '--danger-glow':   '244 63 94',
    '--warn':          '251 146 60',
    '--info':          '6 182 212',
    '--gold':          '161 138 90',
    '--up':            '16 185 129',
    '--up-glow':       '16 185 129 0.4',
    '--down':          '225 29 72',
    '--down-glow':     '244 63 94 0.4',
    '--blink':         'transparent',
    '--font-ui':       '"Noto Sans TC", system-ui, sans-serif',
    '--font-mono':     '"Share Tech Mono", "JetBrains Mono", monospace',
    '--font-data':     '"Fira Code", "JetBrains Mono", monospace',
    '--ecg-up':        '#10b981',
    '--ecg-down':      '#e11d48',
    '--ecg-ball':      '#34d399',
    '--scanline':      '0',
    '--noise':         '0',
    '--ink-wash':      '0',
    '--brutalist-cut': '1',
  },

  // ═══════════════════════════════════════════════════
  // B: NEON NIGHT MARKET -- 霓虹夜市
  //    Electric colors + CRT scanlines + night market chaos
  //    Emotional note: sensory overload, controlled by data
  // ═══════════════════════════════════════════════════
  B: {
    '--bg':            '10 6 30',
    '--text':          '237 233 254',
    '--surface':       '30 20 60',
    '--border':        '108 60 180',
    '--muted':         '139 92 246',
    '--card':          '25 15 50',
    '--card-alt':      '35 20 65',
    '--shadow':        '0 0 0',
    '--accent':        '52 211 153',
    '--accent-glow':   '52 211 153',
    '--danger':        '251 191 36',
    '--danger-glow':   '251 191 36',
    '--warn':          '244 114 22',
    '--info':          '167 139 250',
    '--gold':          '251 191 36',
    '--up':            '52 211 153',
    '--up-glow':       '52 211 153 0.4',
    '--down':          '251 191 36',
    '--down-glow':     '251 191 36 0.4',
    '--blink':         '#a855f7',
    '--font-ui':       '"Noto Sans TC", system-ui, sans-serif',
    '--font-mono':     '"Share Tech Mono", "JetBrains Mono", monospace',
    '--font-data':     '"Fira Code", "JetBrains Mono", monospace',
    '--ecg-up':        '#34d399',
    '--ecg-down':      '#fbbf24',
    '--ecg-ball':      '#6ee7b7',
    '--scanline':      '1',
    '--noise':         '1',
    '--ink-wash':      '0',
    '--brutalist-cut': '0',
  },

  // ═══════════════════════════════════════════════════
  // C: WABI-SABI DATA -- 侘寂數據
  //    Muted earth tones + ink wash gradients + zen data
  //    Emotional note: impermanence of capital, beauty in decay
  // ═══════════════════════════════════════════════════
  C: {
    '--bg':            '14 12 8',
    '--text':          '200 184 154',
    '--surface':       '26 22 16',
    '--border':        '74 58 32',
    '--muted':         '139 115 85',
    '--card':          '20 17 12',
    '--card-alt':      '30 25 18',
    '--shadow':        '0 0 0',
    '--accent':        '196 162 77',
    '--accent-glow':   '196 162 77',
    '--danger':        '185 28 28',
    '--danger-glow':   '220 38 38',
    '--warn':          '180 120 30',
    '--info':          '123 160 91',
    '--gold':          '196 162 77',
    '--up':            '123 160 91',
    '--up-glow':       '123 160 91 0.35',
    '--down':          '185 28 28',
    '--down-glow':     '220 38 38 0.35',
    '--blink':         'transparent',
    '--font-ui':       '"Noto Sans TC", system-ui, sans-serif',
    '--font-mono':     '"Share Tech Mono", "JetBrains Mono", monospace',
    '--font-data':     '"Fira Code", "JetBrains Mono", monospace',
    '--ecg-up':        '#7ba05b',
    '--ecg-down':      '#b91c1c',
    '--ecg-ball':      '#c4a24d',
    '--scanline':      '0',
    '--noise':         '0',
    '--ink-wash':      '1',
    '--brutalist-cut': '0',
  },
}

// ── Global keyframes + scanline/noise/ink-wash overlays ──────────────────────
const GLOBAL_CSS = `
/* ── Digit pulse (ECG number tick) ── */
@keyframes digit-tick {
  0%   { transform: translateY(0);    opacity: 1; }
  40%  { transform: translateY(-4px); opacity: 0.7; }
  100% { transform: translateY(0);    opacity: 1; }
}
.animate-digit-tick {
  animation: digit-tick 0.35s cubic-bezier(0.34,1.56,0.64,1);
}

/* ── Chromatic aberration glitch on P&L change ── */
@keyframes chromatic-glitch {
  0%   { text-shadow: -2px 0 #ff0040, 2px 0 #00ff88; filter: none; }
  25%  { text-shadow: 2px 0 #ff0040, -2px 0 #00ff88; filter: brightness(1.4); }
  50%  { text-shadow: -1px 1px #ff0040, 1px -1px #00ff88; filter: none; }
  75%  { text-shadow: 1px 0 #ff0040, -1px 0 #00ff88; filter: brightness(1.2); }
  100% { text-shadow: none; filter: none; }
}
.animate-chromatic-glitch {
  animation: chromatic-glitch 0.3s steps(2) forwards;
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
  0%,100% { text-shadow: 0 0 4px rgba(var(--accent)), 0 0 10px rgba(var(--accent)); opacity: 1; }
  50%     { text-shadow: 0 0 8px rgba(var(--accent)), 0 0 20px rgba(var(--accent)), 0 0 40px rgba(var(--accent)); opacity: 0.92; }
}
.animate-neon-breathe {
  animation: neon-breathe 2.4s ease-in-out infinite;
}

/* ── Lava/ember pulse (danger) ── */
@keyframes lava-pulse {
  0%,100% { box-shadow: 0 0 6px rgba(var(--danger)), 0 0 14px rgba(var(--danger)); }
  50%     { box-shadow: 0 0 14px rgba(var(--danger)), 0 0 32px rgba(var(--danger)), 0 0 60px rgba(var(--danger)); }
}
.animate-lava-pulse {
  animation: lava-pulse 1.6s ease-in-out infinite;
}

/* ── Glitch / static jitter ── */
@keyframes glitch-jitter {
  0%   { transform: translate(0,0) skewX(0deg);      clip-path: inset(0 0 95% 0); }
  10%  { transform: translate(-2px,1px) skewX(-0.5deg); clip-path: inset(10% 0 60% 0); }
  20%  { transform: translate(2px,-1px) skewX(0.5deg);  clip-path: inset(50% 0 20% 0); }
  30%  { transform: translate(-1px,2px) skewX(-0.3deg); clip-path: inset(80% 0 5% 0); }
  40%  { transform: translate(1px,-2px) skewX(0.3deg);  clip-path: inset(0 0 0 0); }
  100% { transform: translate(0,0) skewX(0deg);         clip-path: inset(0 0 95% 0); }
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
  49%     { opacity: 1; text-shadow: 0 0 6px rgba(168,85,247,0.8); }
  50%     { opacity: 0.2; text-shadow: 0 0 2px rgba(168,85,247,0.3); }
  51%     { opacity: 1; text-shadow: 0 0 6px rgba(168,85,247,0.8); }
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
  background: linear-gradient(90deg, #c4a24d 0%, #e8d48b 25%, #c4a24d 50%, #e8d48b 75%, #c4a24d 100%);
  background-size: 200% auto;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: gold-shimmer 3s linear infinite;
}

/* ── Ink wash drip (Variant C) ── */
@keyframes ink-drip {
  0%   { opacity: 0; transform: translateY(-10px) scaleY(0.5); }
  60%  { opacity: 0.7; transform: translateY(2px) scaleY(1.05); }
  100% { opacity: 0.5; transform: translateY(0) scaleY(1); }
}
.animate-ink-drip {
  animation: ink-drip 1.2s ease-out forwards;
}

/* ── Card explosion expand ── */
@keyframes card-explode {
  from { transform: scale(0.92) translateY(8px); opacity: 0; }
  to   { transform: scale(1) translateY(0); opacity: 1; }
}
.animate-card-explode {
  animation: card-explode 0.35s cubic-bezier(0.34,1.56,0.64,1) forwards;
}

/* ── Floating P&L text ── */
@keyframes pnl-float {
  0%   { transform: translateY(0px); opacity: 0.6; }
  50%  { transform: translateY(-12px); opacity: 1; }
  100% { transform: translateY(-6px); opacity: 0.85; }
}
.animate-pnl-float {
  animation: pnl-float 3s ease-in-out infinite;
}

/* ── Radioactive contamination rings (bleeding positions) ── */
@keyframes contamination-ring {
  0%   { transform: scale(1); opacity: 0.6; }
  50%  { transform: scale(1.15); opacity: 0.2; }
  100% { transform: scale(1.3); opacity: 0; }
}
.animate-contamination {
  animation: contamination-ring 2s ease-out infinite;
}

/* ── CRT scanline overlay (Variant B) ── */
.scanline-overlay::after {
  content: '';
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 9999;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 2px,
    rgba(0,0,0,0.04) 2px,
    rgba(0,0,0,0.04) 4px
  );
  mix-blend-mode: multiply;
}

/* ── Ink wash gradient overlay (Variant C) ── */
.ink-wash-overlay::before {
  content: '';
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 9998;
  background: radial-gradient(
    ellipse 80% 60% at 30% 20%,
    rgba(196,162,77,0.03) 0%,
    transparent 60%
  ),
  radial-gradient(
    ellipse 60% 40% at 70% 80%,
    rgba(185,28,28,0.02) 0%,
    transparent 50%
  );
}

/* ── Brutalist diagonal cut (Variant A) ── */
.brutalist-cut {
  clip-path: polygon(0 0, 100% 0, 100% calc(100% - 3px), calc(100% - 8px) 100%, 0 100%);
}

/* ── Emergency button hover blood seep ── */
@keyframes blood-seep {
  0%,100% { background-position: 50% 100%; background-size: 200% 0%; }
  50%     { background-position: 50% 100%; background-size: 200% 40%; }
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

export function useBattleTheme(variant: 'A' | 'B' | 'C' = 'A') {
  useEffect(() => {
    // Inject fonts
    if (!document.getElementById('battle-fonts')) {
      const link = document.createElement('link')
      link.id = 'battle-fonts'
      link.rel = 'stylesheet'
      link.href = FONT_URL
      document.head.appendChild(link)
    }

    // Inject global keyframes + overlays (once)
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

    // Variant-specific body classes
    document.body.classList.remove('night-market', 'scanline-overlay', 'ink-wash-overlay')
    if (variant === 'B') {
      document.body.classList.add('night-market', 'scanline-overlay')
    } else if (variant === 'C') {
      document.body.classList.add('ink-wash-overlay')
    }

    return () => {
      // Don't remove on unmount -- theme should persist across navigations
    }
  }, [variant])
}

export default useBattleTheme
