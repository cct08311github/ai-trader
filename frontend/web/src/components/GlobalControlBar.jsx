import React, { useState } from 'react'
import { useControlStatus } from '../lib/controlApi'
import { useToast } from './ToastProvider'

function Pill({ tone = 'slate', dotClassName = '', className = '', children, title }) {
  const base = 'flex items-center gap-1.5 rounded-full px-3 py-1 text-xs whitespace-nowrap'
  const toneMap = {
    slate: 'bg-slate-900/40 text-slate-200 border border-slate-800',
    emerald: 'bg-emerald-900/25 text-emerald-200 border border-emerald-900/40',
    rose: 'bg-rose-900/25 text-rose-200 border border-rose-900/40',
    blue: 'bg-blue-900/25 text-blue-200 border border-blue-900/40',
    amber: 'bg-amber-900/20 text-amber-200 border border-amber-900/40',
  }
  return (
    <div className={[base, toneMap[tone] || toneMap.slate, className].join(' ')} title={title}>
      <span className={['h-2 w-2 rounded-full', dotClassName].join(' ')} />
      <span>{children}</span>
    </div>
  )
}

/** Styled confirmation dialog — replaces window.confirm / window.prompt */
function ConfirmDialog({ open, title, message, dangerous, inputLabel, inputDefault, onConfirm, onCancel }) {
  const [val, setVal] = useState(inputDefault || '')
  const dialogRef = React.useRef(null)

  // Escape key = cancel
  React.useEffect(() => {
    if (!open) return
    function onKey(e) { if (e.key === 'Escape') onCancel() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onCancel])

  // Focus trap + focus input (if present) or confirm button when opens
  React.useEffect(() => {
    if (!open || !dialogRef.current) return
    const focusable = dialogRef.current.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    )
    if (!focusable.length) return
    // If there's an input, focus it; otherwise focus the last button (primary action)
    const target = inputLabel
      ? focusable[0] // input is first
      : focusable[focusable.length - 1] // confirm is last
    target.focus()
  }, [open, inputLabel])

  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onCancel}
      role="presentation"
    >
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="dlg-title"
        aria-describedby="dlg-msg"
        className="w-full max-w-sm rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        <div id="dlg-title" className={`mb-2 text-base font-semibold ${dangerous ? 'text-rose-300' : 'text-slate-100'}`}>
          {title}
        </div>
        <p id="dlg-msg" className="text-sm text-slate-400 leading-relaxed mb-5 whitespace-pre-wrap">{message}</p>

        {inputLabel && (
          <div className="mb-5">
            <label className="block text-xs text-slate-400 mb-1.5">{inputLabel}</label>
            <input
              autoFocus
              value={val}
              onChange={e => setVal(e.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-sm text-slate-200 focus:border-slate-500 focus:outline-none"
            />
          </div>
        )}

        <div className="flex gap-3">
          <button
            onClick={onCancel}
            className="flex-1 rounded-xl border border-slate-700 py-2.5 text-sm font-medium text-slate-300 hover:bg-slate-800 transition-colors"
          >
            取消
          </button>
          <button
            autoFocus={!inputLabel}
            onClick={() => onConfirm(val)}
            className={`flex-1 rounded-xl py-2.5 text-sm font-semibold text-white transition-colors ${
              dangerous ? 'bg-rose-600 hover:bg-rose-500' : 'bg-emerald-600 hover:bg-emerald-500'
            }`}
          >
            確認
          </button>
        </div>
      </div>
    </div>
  )
}

const ACT_LABELS = {
  '/enable': '✅ 自動交易已啟用',
  '/disable': '⏸️ 自動交易已停用',
  '/stop': '🚨 緊急停止已執行',
  '/resume': '▶️ 緊急停止已解除',
  '/simulation': '🔵 已切換至模擬盤',
  '/live': '🔴 已切換至實際盤',
}

export default function GlobalControlBar() {
  const { status, error, loading, act } = useControlStatus({ pollMs: 5000 })
  const toast = useToast()
  const [dlg, setDlg] = useState(null)

  const isEmergency = Boolean(status?.emergency_stop)
  const isAutoTradingEnabled = Boolean(status?.auto_trading_enabled)
  const isSimulation = status?.simulation_mode !== false

  async function runAct(endpoint, opts) {
    try {
      await act(endpoint, opts)
      toast.success(ACT_LABELS[endpoint] || '指令已執行')
    } catch (e) {
      toast.error(`指令失敗：${e?.message || e}`)
    }
  }

  /** Open a styled confirm/input dialog; resolves { ok, val } */
  function ask(cfg) {
    return new Promise(resolve => {
      setDlg({
        ...cfg,
        _key: Date.now(),
        onConfirm: val => { setDlg(null); resolve({ ok: true, val }) },
        onCancel:  ()  => { setDlg(null); resolve({ ok: false }) },
      })
    })
  }

  const handleEnable = async () => {
    if (status?.simulation_mode === false) {
      const { ok } = await ask({
        title: '⚠️ 啟用自動交易',
        message: '您目前處於實際盤模式。啟用自動交易將使用真實資金進行交易。\n\n確定要啟用嗎？',
        dangerous: true,
      })
      if (!ok) return
    }
    runAct('/enable')
  }

  const handleDisable = () => runAct('/disable')
  const handleSwitchToSimulation = () => runAct('/simulation')

  const handleSwitchToLive = async () => {
    const { ok } = await ask({
      title: '🚨 切換至實際盤',
      message: '您即將切換到實際盤模式，所有交易將使用真實資金。\n\n此操作無法自動撤銷，請謹慎確認。',
      dangerous: true,
    })
    if (ok) runAct('/live')
  }

  const handleEmergencyStop = async () => {
    const { ok, val } = await ask({
      title: '🚨 緊急停止',
      message: '即將觸發緊急停止，所有自動交易將立即暫停。',
      dangerous: true,
      inputLabel: '停止原因（可選）',
      inputDefault: '手動緊急停止',
    })
    if (!ok) return
    runAct('/stop', { method: 'POST', body: { reason: val || 'User initiated manual stop' } })
  }

  const handleResume = () => runAct('/resume')

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

      {/* Lightweight feedback area — shows API error if toast isn't available yet */}
      {error && (
        <div className="flex justify-end">
          <div className="max-w-[720px] rounded-lg px-3 py-2 text-xs border bg-rose-900/20 text-rose-200 border-rose-900/50">
            {error}
          </div>
        </div>
      )}

      {/* Styled confirm / input dialog */}
      {dlg && (
        <ConfirmDialog
          key={dlg._key}
          open
          title={dlg.title}
          message={dlg.message}
          dangerous={dlg.dangerous}
          inputLabel={dlg.inputLabel}
          inputDefault={dlg.inputDefault}
          onConfirm={dlg.onConfirm}
          onCancel={dlg.onCancel}
        />
      )}
    </div>
  )
}
