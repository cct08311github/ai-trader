import React from 'react'
import { NavLink } from 'react-router-dom'
import {
  Briefcase, ArrowLeftRight, LineChart,
  Settings, Package, SlidersHorizontal, LogOut, User, Bot, BarChart2
} from 'lucide-react'
import { logout, getToken } from '../lib/auth'

const nav = [
  { to: '/portfolio', label: 'Portfolio', icon: Briefcase },
  { to: '/trades', label: 'Trades', icon: ArrowLeftRight },
  { to: '/strategy', label: 'Strategy', icon: LineChart },
  { to: '/analysis', label: '盤後分析', icon: BarChart2 },
  { to: '/agents', label: 'Agents', icon: Bot },
  { to: '/system', label: 'System', icon: Settings },
  { to: '/settings', label: '資金設定', icon: SlidersHorizontal },
]

export default function Sidebar({ onNavigate } = {}) {
  const token = getToken()
  // Show last 8 chars of token as identifier
  const tokenHint = token ? `…${token.slice(-8)}` : '(未登入)'

  function handleLogout() {
    logout()
    if (onNavigate) onNavigate()
  }

  return (
    <aside className="flex flex-col h-screen w-64 border-r border-slate-900 bg-slate-950/60 sticky top-0">
      {/* Branding */}
      <div className="p-4">
        <div className="rounded-2xl border border-slate-800 bg-slate-900/30 p-4 shadow-panel">
          <div className="text-sm font-semibold">指揮中心</div>
          <div className="mt-1 text-xs text-slate-400">暗黑戰情室風格 · MVP</div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-4 space-y-1 overflow-y-auto">
        {nav.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            onClick={onNavigate}
            className={({ isActive }) =>
              [
                'group flex items-center gap-3 rounded-xl px-3 py-2 text-sm',
                'transition-colors',
                isActive
                  ? 'bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/20'
                  : 'text-slate-300 hover:bg-slate-900/40 hover:text-slate-100'
              ].join(' ')
            }
          >
            <item.icon className="h-4 w-4 opacity-90" />
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      {/* Footer: user info + logout */}
      <div className="p-4 border-t border-slate-800 space-y-2">
        {/* Token hint */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-900/40">
          <User className="h-3.5 w-3.5 text-slate-500 shrink-0" />
          <span className="text-xs text-slate-500 truncate font-mono" title={token || ''}>
            token {tokenHint}
          </span>
        </div>

        {/* Logout button — always visible */}
        <button
          type="button"
          id="sidebar-logout-btn"
          onClick={handleLogout}
          className="group flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm
                     text-rose-400 border border-rose-500/20 bg-rose-500/5
                     transition-all hover:bg-rose-500/15 hover:border-rose-500/40
                     hover:text-rose-300 active:scale-[0.98]"
        >
          <LogOut className="h-4 w-4" />
          <span className="font-medium">登出系統</span>
        </button>
      </div>
    </aside>
  )
}
