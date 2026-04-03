/**
 * MobileNav.tsx -- Kyo Nakamura
 * Bottom-anchored mobile navigation with variant-aware styling.
 *
 * On mobile (< lg): renders as a compact bottom bar with icons
 * On desktop: hidden entirely (sidebar handles navigation)
 *
 * The nav uses the same brutalist/neon/wabi-sabi treatment
 * as the rest of the battle UI via CSS custom properties.
 */

import { NavLink } from 'react-router-dom'
import {
  Briefcase,
  FileText,
  Cpu,
  BarChart2,
  Bot,
  Settings,
  Activity,
} from 'lucide-react'

const NAV_ITEMS = [
  { to: '/portfolio',  label: '庫存',     Icon: Briefcase },
  { to: '/trades',     label: '交易',     Icon: FileText  },
  { to: '/strategy',   label: '策略',     Icon: Cpu       },
  { to: '/analysis',   label: '分析',     Icon: BarChart2 },
  { to: '/agents',     label: 'Agent',    Icon: Bot       },
  { to: '/system',     label: '系統',     Icon: Activity  },
  { to: '/settings',   label: '設定',     Icon: Settings  },
]

interface Props {
  onClose?: () => void
}

export default function MobileNav({ onClose }: Props) {
  return (
    <>
      {/* ── Bottom bar (mobile only) ─────────────────────────── */}
      <nav
        aria-label="主要導航"
        className="fixed bottom-0 left-0 right-0 z-50 lg:hidden
                   border-t border-[rgb(var(--border))]
                   bg-[rgb(var(--bg))]/95 backdrop-blur-md
                   safe-area-bottom"
        style={{
          paddingBottom: 'env(safe-area-inset-bottom, 0px)',
        }}
      >
        <div className="flex items-stretch justify-around px-1 py-1">
          {NAV_ITEMS.map(({ to, label, Icon }) => (
            <NavLink
              key={to}
              to={to}
              onClick={onClose}
              className={({ isActive }) => `
                flex flex-col items-center justify-center gap-0.5
                px-1 py-2 min-w-0 flex-1 min-h-[44px]
                text-[9px] font-medium tracking-wide
                transition-all duration-150
                ${isActive
                  ? 'text-[rgb(var(--accent))]'
                  : 'text-[rgb(var(--muted))] active:text-[rgb(var(--text))]'
                }
              `}
            >
              {({ isActive }) => (
                <>
                  <div className="relative">
                    <Icon className="h-4 w-4 flex-shrink-0" />
                    {/* Active indicator dot */}
                    {isActive && (
                      <div
                        className="absolute -top-1 -right-1 h-1.5 w-1.5 rounded-full bg-[rgb(var(--accent))]"
                        style={{
                          boxShadow: '0 0 4px rgb(var(--accent))',
                        }}
                      />
                    )}
                  </div>
                  <span className="truncate">{label}</span>
                </>
              )}
            </NavLink>
          ))}
        </div>
      </nav>

      {/* ── Spacer to prevent content from being hidden behind bottom nav ── */}
      <div className="h-16 lg:hidden" aria-hidden="true" />
    </>
  )
}
