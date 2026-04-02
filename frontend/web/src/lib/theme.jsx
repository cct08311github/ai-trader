import React, { createContext, useContext, useState, useEffect } from 'react';

const ThemeContext = createContext(null);

function getLocalStorage(key, fallback) {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}

const LIGHT_VARS = {
  '--bg':       '249 250 251',   // gray-50
  '--text':     '15 23 42',      // slate-900
  '--surface':  '255 255 255',   // white
  '--border':   '209 213 219',   // gray-300
  '--muted':    '107 114 128',   // gray-500
  '--card':     '255 255 255',   // white
  '--card-alt': '243 244 246',   // gray-100
  '--accent':   '16 185 129',    // emerald-500
  '--shadow':   '0 0 0',
  '--sidebar-bg':      '15 23 42',   // keep sidebar dark in both modes
  '--sidebar-text':    '203 213 225',
  '--sidebar-border':  '30 41 59',
  '--sidebar-surface': '30 41 59',
};

const DARK_VARS = {
  '--bg':       '2 6 23',        // slate-950
  '--text':     '226 232 240',   // slate-200
  '--surface':  '15 23 42',      // slate-900
  '--border':   '30 41 59',      // slate-800
  '--muted':    '100 116 139',   // slate-500
  '--card':     '15 23 42',      // slate-900
  '--card-alt': '8 15 40',       // ~slate-950
  '--accent':   '16 185 129',    // emerald-500
  '--shadow':   '0 0 0',
  '--sidebar-bg':      '2 6 23',
  '--sidebar-text':    '203 213 225',
  '--sidebar-border':  '15 23 42',
  '--sidebar-surface': '15 23 42',
};

function applyTheme(theme) {
  if (typeof document === 'undefined') return;
  const vars = theme === 'light' ? LIGHT_VARS : DARK_VARS;
  const root = document.documentElement;
  Object.entries(vars).forEach(([k, v]) => root.style.setProperty(k, v));
  root.classList.remove('dark', 'light');
  root.classList.add(theme);
  root.setAttribute('data-theme', theme);
}

export function ThemeProvider({ children, defaultTheme = 'dark' }) {
  const [theme, setTheme] = useState(() => {
    // 1. localStorage 優先
    const saved = getLocalStorage('theme', null);
    if (saved === 'light' || saved === 'dark') return saved;
    // 2. 系統偏好
    try {
      if (window.matchMedia?.('(prefers-color-scheme: light)').matches) return 'light';
    } catch {}
    // 3. 預設 dark
    return defaultTheme;
  });

  // 初始化時應用主題
  useEffect(() => {
    applyTheme(theme);
  }, []);

  // 主題變更時寫入 localStorage
  useEffect(() => {
    try { localStorage.setItem('theme', theme); } catch {}
    applyTheme(theme);
  }, [theme]);

  const value = {
    theme,
    setTheme,
    toggleTheme: () => setTheme(prev => prev === 'dark' ? 'light' : 'dark'),
  };

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}
