import React from 'react'
import { NavLink } from 'react-router-dom'
import { Briefcase, ArrowLeftRight, LineChart, Settings, Package, SlidersHorizontal } from 'lucide-react'

const nav = [
  { to: '/portfolio', label: 'Portfolio', icon: Briefcase },
  { to: '/trades', label: 'Trades', icon: ArrowLeftRight },
  { to: '/strategy', label: 'Strategy', icon: LineChart },
  { to: '/system', label: 'System', icon: Settings },
  { to: '/inventory', label: 'Inventory', icon: Package },
  { to: '/settings', label: '資金設定', icon: SlidersHorizontal },
]

export default function Sidebar() {
  return (
    <aside className="w-64 border-r border-slate-900 bg-slate-950/60 p-4">
      <div className="mb-6 rounded-2xl border border-slate-800 bg-slate-900/30 p-4 shadow-panel">
        <div className="text-sm font-semibold">指揮中心</div>
        <div className="mt-1 text-xs text-slate-400">暗黑戰情室風格 · MVP</div>
      </div>

      <nav className="space-y-1">
        {nav.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
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

    </aside>
  )
}
