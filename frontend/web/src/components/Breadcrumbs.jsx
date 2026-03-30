import React, { useMemo } from 'react'
import { Link, useLocation } from 'react-router-dom'

const LABELS = {
  portfolio: 'Portfolio',
  trades: 'Trades',
  strategy: 'Strategy',
  system: 'System',
  analysis: '盤後分析',
  agents: 'AI Agents',
  settings: '資金設定',
}

export default function Breadcrumbs() {
  const location = useLocation()

  const crumbs = useMemo(() => {
    const parts = (location.pathname || '/').split('/').filter(Boolean)
    const items = [{ label: 'Home', to: '/' }]
    let acc = ''
    for (const p of parts) {
      acc += `/${p}`
      items.push({ label: LABELS[p] || p, to: acc })
    }
    return items
  }, [location.pathname])

  return (
    <nav aria-label="Breadcrumb" className="text-xs text-[rgb(var(--muted))]">
      <ol className="flex flex-wrap items-center gap-2">
        {crumbs.map((c, idx) => (
          <li key={c.to} className="flex items-center gap-2">
            {idx === crumbs.length - 1 ? (
              <span className="text-[rgb(var(--text))] font-medium">{c.label}</span>
            ) : (
              <Link className="hover:underline" to={c.to}>
                {c.label}
              </Link>
            )}
            {idx === crumbs.length - 1 ? null : <span className="opacity-60">/</span>}
          </li>
        ))}
      </ol>
    </nav>
  )
}
