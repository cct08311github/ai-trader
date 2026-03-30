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
  '--bg':      '255 255 255',
  '--text':    '15 23 42',
  '--surface': '248 250 252',
  '--border':  '226 232 240',
  '--muted':   '148 163 184',
};

const DARK_VARS = {
  '--bg':      '2 6 23',
  '--text':    '226 232 240',
  '--surface': '15 23 42',
  '--border':  '30 41 59',
  '--muted':   '100 116 139',
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
