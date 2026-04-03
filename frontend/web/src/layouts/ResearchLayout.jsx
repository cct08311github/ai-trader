import React from 'react'
import { NavLink, Outlet } from 'react-router-dom'

const NAV_ITEMS = [
  { path: '/research', label: '總覽', icon: '◈', end: true },
  { path: '/research/stock', label: '個股分析', icon: '◉' },
  { path: '/research/screener', label: '選股器', icon: '▦' },
]

function ResearchNavLink({ path, label, icon, end }) {
  return (
    <NavLink
      to={path}
      end={end}
      className={({ isActive }) => `
        flex items-center gap-2 px-3 py-2 rounded-sm text-xs transition-colors
        ${isActive
          ? 'text-th-accent bg-th-card border-l-2'
          : 'text-th-muted hover:text-th-text hover:bg-th-card/50 border-l-2 border-transparent'
        }
      `}
      style={({ isActive }) => ({
        fontFamily: 'var(--font-ui)',
        borderLeftColor: isActive ? 'rgb(var(--accent))' : 'transparent',
      })}
    >
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px' }}>{icon}</span>
      {label}
    </NavLink>
  )
}

/**
 * ResearchLayout — nested layout for /research/* routes
 * Left sidebar with sub-navigation + main content area
 */
export default function ResearchLayout() {
  return (
    <div className="flex min-h-full w-full">
      {/* Left sidebar */}
      <aside className="w-40 flex-shrink-0 border-r border-th-border bg-th-surface/50 py-4 px-2 hidden sm:flex flex-col gap-1">
        <div
          className="px-3 py-1 mb-2 text-xs tracking-widest uppercase text-th-muted"
          style={{ fontFamily: 'var(--font-mono)', fontSize: '9px' }}
        >
          研究中心
        </div>
        {NAV_ITEMS.map((item) => (
          <ResearchNavLink key={item.path} {...item} />
        ))}
      </aside>

      {/* Mobile top nav */}
      <div className="sm:hidden w-full absolute top-0 left-0 z-10 bg-th-surface border-b border-th-border px-2 py-1 flex gap-1 overflow-x-auto">
        {NAV_ITEMS.map((item) => (
          <ResearchNavLink key={item.path} {...item} />
        ))}
      </div>

      {/* Main content */}
      <main className="flex-1 min-w-0 p-4 sm:p-6 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
