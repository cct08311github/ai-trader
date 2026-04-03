import React from 'react'

/**
 * DataCard — BattleTheme-compatible reusable card
 * Supports loading/error/empty states with accent border
 */
export function DataCard({ title, loading, error, empty, children, className = '', accentColor }) {
  const accentStyle = accentColor
    ? { borderLeftColor: accentColor }
    : {}

  return (
    <div
      className={`
        relative bg-th-card border border-th-border border-l-2
        rounded-sm shadow-panel overflow-hidden
        ${className}
      `}
      style={{ borderLeftColor: accentColor || 'rgb(var(--accent))', ...accentStyle }}
    >
      {title && (
        <div className="px-3 py-2 border-b border-th-border flex items-center justify-between">
          <span
            className="text-xs font-medium tracking-widest uppercase text-th-muted"
            style={{ fontFamily: 'var(--font-mono)' }}
          >
            {title}
          </span>
        </div>
      )}

      <div className="p-3">
        {loading && (
          <div className="flex items-center justify-center min-h-[80px]">
            <div
              className="w-5 h-5 border-2 border-th-border border-t-th-accent rounded-full animate-spin"
              style={{ borderTopColor: 'rgb(var(--accent))' }}
            />
            <span className="ml-2 text-xs text-th-muted" style={{ fontFamily: 'var(--font-ui)' }}>
              載入中…
            </span>
          </div>
        )}

        {!loading && error && (
          <div className="flex items-start gap-2 min-h-[80px] py-2">
            <span className="text-th-danger text-xs mt-0.5">!</span>
            <span className="text-xs text-th-danger" style={{ fontFamily: 'var(--font-ui)' }}>
              {typeof error === 'string' ? error : error?.message || '資料載入失敗'}
            </span>
          </div>
        )}

        {!loading && !error && empty && (
          <div className="flex items-center justify-center min-h-[80px]">
            <span className="text-xs text-th-muted" style={{ fontFamily: 'var(--font-ui)' }}>
              {typeof empty === 'string' ? empty : '尚無資料'}
            </span>
          </div>
        )}

        {!loading && !error && !empty && children}
      </div>
    </div>
  )
}

export default DataCard
