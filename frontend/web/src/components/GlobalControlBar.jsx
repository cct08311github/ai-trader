import React from 'react'
import { useControlStatus } from '../lib/controlApi'

function Pill({ tone = 'slate', dotClassName = '', className = '', children, title }) {
  const base = 'flex items-center gap-1.5 rounded-full px-3 py-1 text-xs whitespace-nowrap'
  const toneMap = {
    slate: 'bg-slate-900/40 text-slate-200 border border-slate-800',
    emerald: 'bg-emerald-900/25 text-emerald-200 border border-emerald-900/40',
    rose: 'bg-rose-900/25 text-rose-200 border border-rose-900/40',
    blue: 'bg-blue-900/25 text-blue-200 border border-blue-900/40',
    amber: 'bg-amber-900/20 text-amber-200 border border-amber-900/40'
  }

  return (
    <div className={[base, toneMap[tone] || toneMap.slate, className].join(' ')} title={title}>
      <span className={['h-2 w-2 rounded-full', dotClassName].join(' ')} />
      <span>{children}</span>
    </div>
  )
}

export default function GlobalControlBar() {
  const { status, error, loading, lastAction, act } = useControlStatus({ pollMs: 5000 })

  const isEmergency = Boolean(status?.emergency_stop)
  const isAutoTradingEnabled = Boolean(status?.auto_trading_enabled)
  const isSimulation = status?.simulation_mode !== false // treat null as simulation/safe-ish

  const handleEnable = () => {
    if (status?.simulation_mode === false) {
      const ok = window.confirm(
        '⚠️ 警告：您目前處於實際盤模式。啟用自動交易將使用真實資金進行交易。\n\n確定要啟用自動交易嗎？'
      )
      if (!ok) return
    }
    act('/enable')
  }

  const handleDisable = () => act('/disable')

  const handleSwitchToSimulation = () => act('/simulation')

  const handleSwitchToLive = () => {
    const ok = window.confirm(
      '🚨 極度危險警告 🚨\n\n您即將切換到實際盤模式，所有交易將使用真實資金。\n\n確定要切換到實際盤嗎？'
    )
    if (ok) act('/live')
  }

  const handleEmergencyStop = () => {
    const reason = prompt('請輸入緊急停止原因（可選）:', '手動緊急停止')
    act('/stop', { method: 'POST', body: { reason: reason || 'User initiated manual stop' } })
  }

  const handleResume = () => act('/resume')

  return (
    <div className="flex w-full flex-col gap-2">
      <div className="flex w-full flex-wrap items-center justify-end gap-2">
        {/* Status pills */}
        {status ? (
          <>
            <Pill
              tone={isEmergency ? 'rose' : isAutoTradingEnabled ? 'emerald' : 'slate'}
              dotClassName={isEmergency ? 'bg-rose-400 animate-pulse' : isAutoTradingEnabled ? 'bg-emerald-400' : 'bg-slate-400'}
              title="自動交易狀態"
            >
              {isEmergency ? '緊急停止中' : isAutoTradingEnabled ? '自動交易：啟用' : '自動交易：停用'}
            </Pill>
            <Pill
              tone={isSimulation ? 'blue' : 'rose'}
              dotClassName={isSimulation ? 'bg-blue-400' : 'bg-rose-400 animate-pulse'}
              title="交易模式"
            >
              {isSimulation ? '模式：模擬盤' : '模式：實際盤'}
            </Pill>
          </>
        ) : (
          <Pill tone="amber" dotClassName="bg-amber-400 animate-pulse" title="狀態載入中">
            讀取系統狀態...
          </Pill>
        )}

        {/* Actions */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            title="啟用自動交易"
            onClick={handleEnable}
            disabled={!status || loading.enable || isEmergency || isAutoTradingEnabled}
            className={[
              'rounded-lg px-3 py-1.5 text-xs font-semibold transition-all',
              !status || isEmergency || isAutoTradingEnabled
                ? 'bg-slate-900/40 text-slate-500 border border-slate-800 cursor-not-allowed'
                : 'bg-emerald-600 hover:bg-emerald-500 text-white'
            ].join(' ')}
          >
            {loading.enable ? '啟用中...' : '啟用'}
          </button>

          <button
            title="停用自動交易"
            onClick={handleDisable}
            disabled={!status || loading.disable || isEmergency || !isAutoTradingEnabled}
            className={[
              'rounded-lg px-3 py-1.5 text-xs font-semibold transition-all',
              !status || isEmergency || !isAutoTradingEnabled
                ? 'bg-slate-900/40 text-slate-500 border border-slate-800 cursor-not-allowed'
                : 'bg-slate-800 hover:bg-slate-700 text-slate-100 border border-slate-700'
            ].join(' ')}
          >
            {loading.disable ? '停用中...' : '停用'}
          </button>

          <div className="hidden md:block h-5 w-px bg-slate-800 mx-1" />

          <button
            title="切換到模擬盤（較安全）"
            onClick={handleSwitchToSimulation}
            disabled={!status || loading.simulation || isEmergency || isSimulation}
            className={[
              'rounded-lg px-3 py-1.5 text-xs font-semibold transition-all',
              !status || isEmergency || isSimulation
                ? 'bg-slate-900/40 text-slate-500 border border-slate-800 cursor-not-allowed'
                : 'bg-blue-600 hover:bg-blue-500 text-white'
            ].join(' ')}
          >
            {loading.simulation ? '切換中...' : '模擬'}
          </button>

          <button
            title="切換到實際盤（需二次確認）"
            onClick={handleSwitchToLive}
            disabled={!status || loading.live || isEmergency || !isSimulation}
            className={[
              'rounded-lg px-3 py-1.5 text-xs font-semibold transition-all',
              !status || isEmergency || !isSimulation
                ? 'bg-slate-900/40 text-slate-500 border border-slate-800 cursor-not-allowed'
                : 'bg-rose-700 hover:bg-rose-600 text-white'
            ].join(' ')}
          >
            {loading.live ? '切換中...' : '實際'}
          </button>

          <div className="hidden md:block h-5 w-px bg-slate-800 mx-1" />

          <button
            title="緊急停止（最高優先級）"
            onClick={handleEmergencyStop}
            disabled={!status || loading.stop || isEmergency}
            className={[
              'rounded-lg px-3 py-1.5 text-xs font-semibold transition-all',
              !status || isEmergency
                ? 'bg-rose-950/40 text-rose-300 border border-rose-900/40 cursor-not-allowed'
                : 'bg-rose-600 hover:bg-rose-500 text-white'
            ].join(' ')}
          >
            {loading.stop ? '停止中...' : '緊急停止'}
          </button>

          <button
            title="清除緊急停止"
            onClick={handleResume}
            disabled={!status || loading.resume || !isEmergency}
            className={[
              'rounded-lg px-3 py-1.5 text-xs font-semibold transition-all',
              !status || !isEmergency
                ? 'bg-slate-900/40 text-slate-500 border border-slate-800 cursor-not-allowed'
                : 'bg-amber-600 hover:bg-amber-500 text-white'
            ].join(' ')}
          >
            {loading.resume ? '處理中...' : '解除停止'}
          </button>
        </div>
      </div>

      {/* lightweight feedback area */}
      {(error || lastAction) && (
        <div className="flex justify-end">
          <div
            className={[
              'max-w-[720px] rounded-lg px-3 py-2 text-xs border',
              error
                ? 'bg-rose-900/20 text-rose-200 border-rose-900/50'
                : lastAction?.warning
                  ? 'bg-amber-900/20 text-amber-200 border-amber-900/50'
                  : 'bg-emerald-900/15 text-emerald-200 border-emerald-900/40'
            ].join(' ')}
          >
            {error ? (
              <span>{error}</span>
            ) : (
              <span>
                {lastAction?.warning ? `警告：${lastAction.message}` : `成功：${lastAction?.message}`}
                {lastAction?.warning ? `（${lastAction.warning}）` : ''}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
