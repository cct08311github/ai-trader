/**
 * LoadingSpinner — 統一的載入動畫元件。
 *
 * 用法：
 *   <LoadingSpinner />
 *   <LoadingSpinner size="lg" />
 *   <LoadingSpinner label="讀取持倉資料中..." />
 */
import React from 'react'

const SIZE_CLASSES = {
  sm: 'h-4 w-4',
  md: 'h-6 w-6',
  lg: 'h-10 w-10',
}

export default function LoadingSpinner({ size = 'md', label, className = '' }) {
  const s = SIZE_CLASSES[size] || SIZE_CLASSES.md
  return (
    <div className={`flex flex-col items-center justify-center gap-3 ${className}`} role="status" aria-live="polite">
      <svg
        className={`animate-spin ${s} text-indigo-400`}
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
      >
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path
          className="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
        />
      </svg>
      {label && (
        <span className="text-xs text-[rgb(var(--muted))]">{label}</span>
      )}
    </div>
  )
}
