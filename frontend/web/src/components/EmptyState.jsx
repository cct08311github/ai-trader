/**
 * EmptyState — 統一的空狀態元件。
 *
 * 用法：
 *   <EmptyState icon={Briefcase} title="目前無持倉" description="系統將在下次交易時段自動建倉" />
 *   <EmptyState icon={FileText} title="尚無交易紀錄" action={{ label: '創建第一筆', onClick: handleCreate }} />
 */
import React from 'react'

export default function EmptyState({
  icon: Icon,
  title,
  description,
  action, // { label, onClick }
  className = '',
}) {
  return (
    <div className={`flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.15] p-8 text-center ${className}`}>
      {Icon && (
        <div className="rounded-full bg-[rgb(var(--surface)]/0.5 p-3">
          <Icon className="h-6 w-6 text-[rgb(var(--muted))]" />
        </div>
      )}
      <div>
        <p className="text-sm font-semibold text-[rgb(var(--text))]">{title}</p>
        {description && (
          <p className="mt-1 text-xs text-[rgb(var(--muted))]">{description}</p>
        )}
      </div>
      {action && (
        <button
          onClick={action.onClick}
          className="mt-1 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))]/0.5 px-3 py-1.5 text-xs font-medium text-[rgb(var(--text))] hover:bg-[rgb(var(--surface))]/0.8 transition-colors"
        >
          {action.label}
        </button>
      )}
    </div>
  )
}
