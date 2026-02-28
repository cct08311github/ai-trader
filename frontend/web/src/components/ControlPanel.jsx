import React from 'react'
import { useControlStatus } from '../lib/controlApi'

export default function ControlPanel() {
  const { status, error, loading, lastAction, act } = useControlStatus({ pollMs: 5000 })

  const handleEnable = () => {
    if (status?.simulation_mode === false) {
      const confirm = window.confirm(
        '⚠️ 警告：您目前處於實際盤模式。啟用自動交易將使用真實資金進行交易。\n\n' +
          '請確認：\n' +
          '1. 您已了解相關風險\n' +
          '2. 您已設定適當的風險控制參數\n' +
          '3. 您已準備好承擔潛在損失\n\n' +
          '確定要啟用自動交易嗎？'
      )
      if (!confirm) return
    }
    act('/enable')
  }

  const handleDisable = () => act('/disable')

  const handleEmergencyStop = () => {
    const reason = prompt('請輸入緊急停止原因（可選）:', '手動緊急停止')
    act('/stop', { method: 'POST', body: { reason: reason || 'User initiated manual stop' } })
  }

  const handleResume = () => act('/resume')
  const handleSwitchToSimulation = () => act('/simulation')
  const handleSwitchToLive = () => {
    const confirm = window.confirm(
      '🚨 極度危險警告 🚨\n\n' +
        '您即將切換到實際盤模式。\n' +
        '此模式下，所有交易將使用真實資金。\n\n' +
        '注意事項：\n' +
        '• 系統將自動禁用自動交易\n' +
        '• 您必須手動啟用自動交易才會開始交易\n' +
        '• 任何交易都可能導致資金損失\n' +
        '• 請確保已設定適當的止損與風險控制\n\n' +
        '確定要切換到實際盤嗎？'
    )
    if (confirm) act('/live')
  }

  if (!status) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 text-sm">
        <div className="flex items-center justify-between">
          <div>載入控制面板...</div>
          <div className="h-2 w-2 animate-pulse rounded-full bg-amber-400"></div>
        </div>
      </div>
    )
  }

  const isEmergency = status.emergency_stop
  const isAutoTradingEnabled = status.auto_trading_enabled
  const isSimulation = status.simulation_mode

  return (
    <div className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900/40 p-5 shadow-panel">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold">系統主控制面板</div>
          <div className="mt-1 text-xs text-slate-400">
            風險控制第一優先 • {isSimulation ? '模擬盤 (安全)' : '實際盤 (資金風險)'}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div
            className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs ${
              isEmergency
                ? 'bg-rose-900/40 text-rose-300'
                : isAutoTradingEnabled
                  ? 'bg-emerald-900/40 text-emerald-300'
                  : 'bg-slate-800 text-slate-300'
            }`}
          >
            <div
              className={`h-2 w-2 rounded-full ${
                isEmergency ? 'bg-rose-400 animate-pulse' : isAutoTradingEnabled ? 'bg-emerald-400' : 'bg-slate-400'
              }`}
            ></div>
            {isEmergency ? '緊急停止中' : isAutoTradingEnabled ? '自動交易已啟用' : '自動交易已停用'}
          </div>
          <div
            className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs ${
              isSimulation ? 'bg-blue-900/40 text-blue-300' : 'bg-rose-900/40 text-rose-300 animate-pulse'
            }`}
          >
            <div className={`h-2 w-2 rounded-full ${isSimulation ? 'bg-blue-400' : 'bg-rose-400 animate-pulse'}`}></div>
            {isSimulation ? '模擬盤' : '實際盤'}
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-lg bg-rose-900/20 p-3 text-sm text-rose-300 border border-rose-800">
          <div className="font-medium">錯誤</div>
          <div className="mt-1 text-xs">{error}</div>
        </div>
      )}

      {lastAction && (
        <div
          className={`rounded-lg p-3 text-sm ${
            lastAction.warning
              ? 'bg-amber-900/20 text-amber-300 border border-amber-800'
              : 'bg-emerald-900/20 text-emerald-300 border border-emerald-800'
          }`}
        >
          <div className="font-medium">{lastAction.warning ? '警告' : '操作成功'}</div>
          <div className="mt-1 text-xs">{lastAction.message}</div>
          {lastAction.warning && <div className="mt-2 text-xs font-semibold">{lastAction.warning}</div>}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2 space-y-3 rounded-xl border border-slate-800 bg-slate-900/30 p-4">
          <div className="text-xs font-semibold text-slate-300">自動交易主開關</div>
          <div className="flex gap-2">
            <button
              onClick={handleEnable}
              disabled={loading.enable || isEmergency || isAutoTradingEnabled}
              className={`flex-1 rounded-lg py-2.5 text-sm font-medium transition-all ${
                isEmergency || isAutoTradingEnabled
                  ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
                  : 'bg-emerald-600 hover:bg-emerald-500 text-white'
              }`}
            >
              {loading.enable ? '處理中...' : '🟢 啟動自動交易'}
            </button>
            <button
              onClick={handleDisable}
              disabled={loading.disable || isEmergency || !isAutoTradingEnabled}
              className={`flex-1 rounded-lg py-2.5 text-sm font-medium transition-all ${
                isEmergency || !isAutoTradingEnabled
                  ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
                  : 'bg-rose-600 hover:bg-rose-500 text-white'
              }`}
            >
              {loading.disable ? '處理中...' : '🔴 停止自動交易'}
            </button>
          </div>
        </div>

        <div className="col-span-2 space-y-3 rounded-xl border border-slate-800 bg-slate-900/30 p-4">
          <div className="text-xs font-semibold text-slate-300">交易模式切換</div>
          <div className="flex gap-2">
            <button
              onClick={handleSwitchToSimulation}
              disabled={loading.simulation || isEmergency || isSimulation}
              className={`flex-1 rounded-lg py-2.5 text-sm font-medium transition-all ${
                isEmergency || isSimulation
                  ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
                  : 'bg-blue-600 hover:bg-blue-500 text-white'
              }`}
            >
              {loading.simulation ? '切換中...' : '🔵 切換至模擬盤'}
            </button>
            <button
              onClick={handleSwitchToLive}
              disabled={loading.live || isEmergency || !isSimulation}
              className={`flex-1 rounded-lg py-2.5 text-sm font-medium transition-all ${
                isEmergency || !isSimulation
                  ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
                  : 'bg-rose-600 hover:bg-rose-500 text-white'
              }`}
            >
              {loading.live ? '切換中...' : '🔴 切換至實際盤'}
            </button>
          </div>
        </div>

        <div className="col-span-2 space-y-3 rounded-xl border border-slate-800 bg-slate-900/30 p-4">
          <div className="text-xs font-semibold text-slate-300">緊急控制</div>
          <div className="flex gap-2">
            <button
              onClick={handleEmergencyStop}
              disabled={loading.stop || isEmergency}
              className={`flex-1 rounded-lg py-2.5 text-sm font-medium transition-all ${
                isEmergency ? 'bg-rose-900 text-rose-300 cursor-not-allowed' : 'bg-rose-700 hover:bg-rose-600 text-white'
              }`}
            >
              {loading.stop ? '處理中...' : '🛑 緊急停止 (立即中斷)'}
            </button>
            <button
              onClick={handleResume}
              disabled={loading.resume || !isEmergency}
              className={`flex-1 rounded-lg py-2.5 text-sm font-medium transition-all ${
                !isEmergency ? 'bg-slate-800 text-slate-500 cursor-not-allowed' : 'bg-amber-600 hover:bg-amber-500 text-white'
              }`}
            >
              {loading.resume ? '處理中...' : '🔄 清除緊急停止'}
            </button>
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/30 p-4">
        <div className="text-xs font-semibold text-slate-300">系統狀態詳情</div>
        <div className="mt-2 grid grid-cols-2 gap-3 text-xs">
          <div className="space-y-1">
            <div className="text-slate-400">自動交易狀態</div>
            <div className={isAutoTradingEnabled ? 'text-emerald-300' : 'text-slate-300'}>
              {isAutoTradingEnabled ? '已啟用' : '已停用'}
            </div>
          </div>
          <div className="space-y-1">
            <div className="text-slate-400">交易模式</div>
            <div className={isSimulation ? 'text-blue-300' : 'text-rose-300'}>
              {isSimulation ? '模擬盤 (安全)' : '實際盤 (資金風險)'}
            </div>
          </div>
          <div className="space-y-1">
            <div className="text-slate-400">緊急停止狀態</div>
            <div className={isEmergency ? 'text-rose-300' : 'text-slate-300'}>
              {isEmergency ? `已啟動: ${status.emergency_reason || '未知原因'}` : '未啟動'}
            </div>
          </div>
          <div className="space-y-1">
            <div className="text-slate-400">最後更新</div>
            <div className="text-slate-300">
              {status.last_modified ? new Date(status.last_modified).toLocaleString('zh-TW') : '未知'}
            </div>
          </div>
        </div>
      </div>

      <div className="text-xs text-slate-500">
        <div className="font-semibold">操作須知：</div>
        <ul className="mt-1 list-inside list-disc space-y-0.5">
          <li>系統預設為「模擬盤 + 自動交易停用」狀態</li>
          <li>切換至實際盤將自動禁用自動交易（雙重保險）</li>
          <li>緊急停止優先級最高，會覆蓋所有其他控制</li>
          <li>風險控制是第一優先</li>
        </ul>
      </div>
    </div>
  )
}
