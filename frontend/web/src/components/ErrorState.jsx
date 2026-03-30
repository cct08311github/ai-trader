/**
 * ErrorState — 統一的錯誤狀態元件，含「重試」按鈕。
 *
 * 用法：
 *   <ErrorState message="API 請求失敗" onRetry={refetch} />
 *   <ErrorState message={error.message} onRetry={refetch} />
 */
import React from 'react'
import { AlertCircle, RefreshCw } from 'lucide-react'

export default function ErrorState({
  message = '讀取失敗',
  description,
  onRetry,
  className = '',
}) {
  return (
    <div
      className={`flex flex-col items-center justify-center gap-3 rounded-2xl border border-rose-500/30 bg-rose-500/10 p-6 text-center ${className}`}
      role="alert"
    >
      <AlertCircle className="h-8 w-8 text-rose-400" />
      <div>
        <p className="text-sm font-semibold text-rose-300">{message}</p>
        {description && (
          <p className="mt-1 text-xs text-rose-300/70">{description}</p>
        )}
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="flex items-center gap-1.5 rounded-lg border border-rose-500/40 bg-rose-500/20 px-3 py-1.5 text-xs font-medium text-rose-300 hover:bg-rose-500/30 transition-colors"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          重試
        </button>
      )}
    </div>
  )
}
