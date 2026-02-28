import React from 'react'
import { Moon, Sun } from 'lucide-react'
import { useTheme } from '../lib/theme'

export default function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const isDark = theme === 'dark'

  return (
    <button
      type="button"
      onClick={toggle}
      className="inline-flex items-center gap-2 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.35] px-3 py-1.5 text-xs font-semibold text-[rgb(var(--text))] shadow-panel transition hover:bg-[rgb(var(--surface))/0.5]"
      aria-label={isDark ? '切換到亮色主題' : '切換到暗黑主題'}
      title={isDark ? 'Theme: Dark (click to switch)' : 'Theme: Light (click to switch)'}
    >
      {isDark ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
      <span className="hidden sm:inline">{isDark ? 'Dark' : 'Light'}</span>
    </button>
  )
}
