/**
 * MobileNav.tsx — Kyo Nakamura
 * Single-column mobile navigation drawer.
 * Renders below header on screens < lg breakpoint.
 *
 * Routes mirrored from App.jsx:
 *   /portfolio  → 庫存總覽
 *   /trades    → 交易紀錄
 *   /strategy  → 策略管理
 *   /analysis  → 數據分析
 *   /agents    → Agent 狀態
 *   /system    → 系統監控
 *   /settings  → 系統設定
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
  X,
} from 'lucide-react'
import { useVariant } from './VariantSwitcher'

const NAV_ITEMS = [
  { to: '/portfolio',  label: '庫存總覽',  Icon: Briefcase },
  { to: '/trades',     label: '交易紀錄',  Icon: FileText  },
  { to: '/strategy',   label: '策略管理',  Icon: Cpu       },
  { to: '/analysis',   label: '數據分析',  Icon: BarChart2  },
  { to: '/agents',     label: 'Agent 狀態', Icon: Bot      },
  { to: '/system',     label: '系統監控',  Icon: Activity   },
  { to: '/settings',   label: '系統設定',  Icon: Settings   },
]

interface Props {
  onClose?: () => void
}

export default function MobileNav({ onClose }: Props) {
  // Ensure theme is loaded
  useVariant()

  return (
    <nav
      aria-label="主要導航"
      className="flex flex-col gap-1 px-3 py-4 lg:hidden"
    >
      {NAV_ITEMS.map(({ to, label, Icon }) => (
        <NavLink
          key={to}
          to={to}
          onClick={onClose}
          className={({ isActive }) => `
            flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-medium
            transition-all duration-150
            ${isActive
              ? 'bg-[rgb(var(--accent))/0.15] text-[rgb(var(--accent))] border border-[rgb(var(--accent))/40]'
              : 'text-[rgb(var(--muted))] border border-transparent hover:bg-[rgb(var(--surface))/0.5] hover:text-[rgb(var(--text))]'
            }
          `}
        >
          <Icon className="h-4 w-4 flex-shrink-0" />
          {label}
        </NavLink>
      ))}
    </nav>
  )
}
