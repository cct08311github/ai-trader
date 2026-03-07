import React from 'react'
import ControlPanel from '../components/ControlPanel'
import LogTerminal from '../components/LogTerminal'
import {
  useSystemHealth,
  useSystemQuota,
  useSystemRisk,
  useSystemEvents,
  useQuarantineStatus,
  useQuarantinePlan,
  useOpenIncidentClusters,
  useRemediationHistory,
  useQuarantineActions,
} from '../lib/systemApi'

// ─── helpers ─────────────────────────────────────────────────────────────────

function statusDot(status) {
  const map = {
    online: 'bg-emerald-400',
    simulation: 'bg-amber-400',
    warning: 'bg-amber-400',
    offline: 'bg-rose-500',
    delayed: 'bg-amber-400',
    unknown: 'bg-slate-500',
  }
  return map[status] || 'bg-slate-500'
}

function statusText(status) {
  const map = {
    online: '在線',
    simulation: '模擬模式',
    warning: '警告',
    offline: '離線',
    delayed: '延遲',
    unknown: '未知',
  }
  return map[status] || status || '未知'
}

function statusTextColor(status) {
  const map = {
    online: 'text-emerald-300',
    simulation: 'text-amber-300',
    warning: 'text-amber-300',
    offline: 'text-rose-400',
    delayed: 'text-amber-300',
    unknown: 'text-slate-400',
  }
  return map[status] || 'text-slate-400'
}

function ProgressBar({ pct, warn = 80, danger = 100 }) {
  const color = pct >= danger ? 'bg-rose-500' : pct >= warn ? 'bg-amber-400' : 'bg-emerald-400'
  return (
    <div className="h-2 w-full rounded-full bg-slate-800">
      <div
        className={`h-2 rounded-full transition-all ${color}`}
        style={{ width: `${Math.min(pct, 100)}%` }}
      />
    </div>
  )
}

function severityColor(severity) {
  const map = {
    error: 'text-rose-400',
    warning: 'text-amber-300',
    info: 'text-slate-300',
  }
  return map[severity] || 'text-slate-400'
}

function actionLabel(actionType) {
  const map = {
    quarantine_apply: '隔離套用',
    quarantine_clear: '隔離清除',
    incident_resolve: '事件解除',
  }
  return map[actionType] || actionType || '未知操作'
}

// ─── panels ──────────────────────────────────────────────────────────────────

function ServiceStatusPanel({ health }) {
  const services = health?.services || {}
  const rows = [
    { key: 'fastapi', label: '後端 API' },
    { key: 'sqlite', label: '資料庫' },
    { key: 'shioaji', label: 'Shioaji 連線' },
    { key: 'sentinel', label: 'Sentinel 守衛' },
  ]
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel">
      <div className="text-sm font-semibold">服務狀態</div>
      <div className="mt-4 space-y-3">
        {rows.map(({ key, label }) => {
          const svc = services[key] || {}
          const status = svc.status || 'unknown'
          return (
            <div key={key} className="flex items-center justify-between">
              <span className="text-sm text-slate-300">{label}</span>
              <div className="flex items-center gap-2">
                <span className={`inline-block h-2 w-2 rounded-full ${statusDot(status)}`} />
                <span className={`text-xs ${statusTextColor(status)}`}>{statusText(status)}</span>
                {svc.latency_ms != null && (
                  <span className="text-xs text-slate-500">{svc.latency_ms}ms</span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function SentinelPanel({ health }) {
  const sentinel = health?.services?.sentinel || {}
  const { last_heartbeat, today_circuit_breaks = 0, status = 'unknown' } = sentinel
  const ago = last_heartbeat ? Math.floor((Date.now() - new Date(last_heartbeat).getTime()) / 1000) : null
  const agoText = ago == null ? '—' : ago < 60 ? `${ago}s 前` : `${Math.floor(ago / 60)}m 前`
  const alertColor = ago != null && ago > 60 ? 'text-rose-400' : 'text-emerald-300'
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel">
      <div className="text-sm font-semibold">Sentinel 心跳</div>
      <div className="mt-4 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-sm text-slate-300">最後心跳</span>
          <span className={`text-xs ${alertColor}`}>{agoText}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-sm text-slate-300">今日熔斷</span>
          <span className={`text-xs ${today_circuit_breaks > 0 ? 'text-rose-400' : 'text-emerald-300'}`}>
            {today_circuit_breaks} 次
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-sm text-slate-300">狀態</span>
          <div className="flex items-center gap-2">
            <span className={`inline-block h-2 w-2 rounded-full ${statusDot(status)}`} />
            <span className={`text-xs ${statusTextColor(status)}`}>{statusText(status)}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

function ResourcePanel({ health }) {
  const res = health?.resources || {}
  const { cpu_percent = 0, memory_percent = 0, disk_used_gb = 0, disk_total_gb = 1 } = res
  const diskPct = disk_total_gb > 0 ? Math.round((disk_used_gb / disk_total_gb) * 100) : 0
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel">
      <div className="text-sm font-semibold">系統資源</div>
      <div className="mt-4 space-y-4">
        <div>
          <div className="flex justify-between text-xs mb-1">
            <span className="text-slate-400">CPU</span>
            <span className={cpu_percent > 80 ? 'text-rose-400' : 'text-slate-300'}>{cpu_percent.toFixed(1)}%</span>
          </div>
          <ProgressBar pct={cpu_percent} />
        </div>
        <div>
          <div className="flex justify-between text-xs mb-1">
            <span className="text-slate-400">記憶體</span>
            <span className={memory_percent > 85 ? 'text-rose-400' : 'text-slate-300'}>{memory_percent.toFixed(1)}%</span>
          </div>
          <ProgressBar pct={memory_percent} warn={85} />
        </div>
        <div>
          <div className="flex justify-between text-xs mb-1">
            <span className="text-slate-400">磁碟</span>
            <span className="text-slate-300">{disk_used_gb.toFixed(1)} / {disk_total_gb.toFixed(1)} GB</span>
          </div>
          <ProgressBar pct={diskPct} warn={85} />
        </div>
      </div>
    </div>
  )
}

function QuotaPanel({ quota }) {
  const { month = '—', budget_twd = 650, used_twd = 0, used_percent = 0, status = 'ok', daily_trend = [] } = quota || {}
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold">API 配額 {month}</div>
        <span className={`text-xs px-2 py-0.5 rounded-full ${status === 'exceeded' ? 'bg-rose-900/40 text-rose-300' : status === 'warning' ? 'bg-amber-900/40 text-amber-300' : 'bg-emerald-900/40 text-emerald-300'}`}>
          {status === 'exceeded' ? '超限' : status === 'warning' ? '警告' : '正常'}
        </span>
      </div>
      <div className="mt-4 space-y-3">
        <div className="flex justify-between text-xs mb-1">
          <span className="text-slate-400">已用 / 預算</span>
          <span className={used_percent >= 80 ? 'text-amber-300' : 'text-slate-300'}>
            NT$ {used_twd.toFixed(0)} / {budget_twd.toFixed(0)}（{used_percent}%）
          </span>
        </div>
        <ProgressBar pct={used_percent} />
        {daily_trend.length > 0 && (
          <div className="mt-3 space-y-1 text-xs text-slate-500">
            {daily_trend.slice(0, 3).map(d => (
              <div key={d.date} className="flex justify-between">
                <span>{d.date}</span>
                <span>NT$ {d.cost_twd}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function RiskPanel({ risk }) {
  const {
    today_realized_pnl = 0,
    monthly_drawdown_pct = 0,
    monthly_drawdown_limit_pct = 0.15,
    drawdown_remaining_pct = 0.15,
    losing_streak_days = 0,
    risk_mode = 'normal',
  } = risk || {}
  const drawdownUsedPct = Math.round((monthly_drawdown_pct / monthly_drawdown_limit_pct) * 100)
  const remainingPct = Math.round(drawdown_remaining_pct * 100)
  const modeColor = risk_mode === 'high' ? 'text-rose-400' : risk_mode === 'elevated' ? 'text-amber-300' : 'text-emerald-300'
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold">風控狀態</div>
        <span className={`text-xs font-medium ${modeColor}`}>{risk_mode.toUpperCase()}</span>
      </div>
      <div className="mt-4 space-y-4">
        <div>
          <div className="flex justify-between text-xs mb-1">
            <span className="text-slate-400">月度回撤</span>
            <span className={remainingPct < 20 ? 'text-rose-400' : 'text-slate-300'}>
              {(monthly_drawdown_pct * 100).toFixed(2)}% / {(monthly_drawdown_limit_pct * 100).toFixed(0)}%
            </span>
          </div>
          <ProgressBar pct={drawdownUsedPct} warn={70} danger={90} />
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-slate-400">今日損益</span>
          <span className={today_realized_pnl < 0 ? 'text-rose-400' : 'text-emerald-300'}>
            {today_realized_pnl >= 0 ? '+' : ''}{today_realized_pnl.toLocaleString()} NT$
          </span>
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-slate-400">連續虧損天數</span>
          <span className={losing_streak_days >= 3 ? 'text-rose-400' : 'text-slate-300'}>
            {losing_streak_days} 天
          </span>
        </div>
      </div>
    </div>
  )
}

function EventsPanel({ events }) {
  const list = events?.events || []
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel">
      <div className="text-sm font-semibold">事件時間軸</div>
      <div className="mt-4 space-y-2 max-h-64 overflow-y-auto">
        {list.length === 0 ? (
          <div className="text-xs text-slate-500">暫無事件</div>
        ) : (
          list.slice(0, 20).map((ev, i) => (
            <div key={i} className="flex gap-3 text-xs">
              <span className="shrink-0 text-slate-500">{String(ev.ts || '').slice(11, 19)}</span>
              <span className={`shrink-0 ${severityColor(ev.severity)}`}>[{ev.source}]</span>
              <span className="text-slate-400 truncate">{ev.code}: {ev.detail}</span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

function OperatorSnapshotPanel({ quarantineStatus, quarantinePlan, clusters, remediation }) {
  const activeQuarantine = quarantineStatus?.active_count || 0
  const eligible = quarantinePlan?.eligible_symbols?.length || 0
  const openClusters = clusters?.count || 0
  const recentActions = remediation?.count || 0
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel">
      <div className="text-sm font-semibold">Operator Snapshot</div>
      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-3">
          <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Active Quarantine</div>
          <div className="mt-2 text-2xl font-semibold text-rose-300">{activeQuarantine}</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-3">
          <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Eligible Repair</div>
          <div className="mt-2 text-2xl font-semibold text-amber-300">{eligible}</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-3">
          <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Open Clusters</div>
          <div className="mt-2 text-2xl font-semibold text-blue-300">{openClusters}</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-3">
          <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Recent Actions</div>
          <div className="mt-2 text-2xl font-semibold text-emerald-300">{recentActions}</div>
        </div>
      </div>
    </div>
  )
}

function QuarantinePanel({ status, plan, planError, actionState, onApply, onClear, onClearSymbol }) {
  const items = status?.items || []
  const eligibleSymbols = plan?.eligible_symbols || []
  const canApply = Boolean(plan?.safe_to_apply) && eligibleSymbols.length > 0
  const canClear = (status?.active_count || 0) > 0
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold">Quarantine / Reconciliation</div>
        <div className="flex items-center gap-2">
          <button
            onClick={onApply}
            disabled={!canApply || actionState?.loading?.apply}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium ${
              !canApply || actionState?.loading?.apply
                ? 'bg-slate-800 text-slate-500'
                : 'bg-amber-600 text-white hover:bg-amber-500'
            }`}
          >
            {actionState?.loading?.apply ? '套用中...' : '套用建議隔離'}
          </button>
          <button
            onClick={onClear}
            disabled={!canClear || actionState?.loading?.clear}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium ${
              !canClear || actionState?.loading?.clear
                ? 'bg-slate-800 text-slate-500'
                : 'bg-blue-700 text-white hover:bg-blue-600'
            }`}
          >
            {actionState?.loading?.clear ? '清除中...' : '清除全部隔離'}
          </button>
          <div className="text-xs text-slate-400">Active {status?.active_count || 0}</div>
        </div>
      </div>
      {planError && (
        <div className="mt-3 rounded-lg border border-amber-800 bg-amber-900/20 p-3 text-xs text-amber-300">
          最新 reconciliation plan 不可用：{planError}
        </div>
      )}
      {actionState?.error && (
        <div className="mt-3 rounded-lg border border-rose-800 bg-rose-900/20 p-3 text-xs text-rose-300">
          隔離操作失敗：{actionState.error}
        </div>
      )}
      {actionState?.lastAction?.result && (
        <div className="mt-3 rounded-lg border border-emerald-800 bg-emerald-900/20 p-3 text-xs text-emerald-300">
          {actionState.lastAction.type === 'apply'
            ? `已套用 ${actionState.lastAction.result.applied_count || 0} 檔隔離`
            : `已清除 ${actionState.lastAction.result.cleared_count || 0} 檔隔離`}
        </div>
      )}
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
          <div className="text-xs font-semibold text-slate-300">可套用隔離</div>
          <div className="mt-2 text-xs text-slate-500">
            report: {plan?.report_id || '—'}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {eligibleSymbols.length === 0 ? (
              <span className="text-xs text-slate-500">目前沒有可直接套用的 symbol</span>
            ) : eligibleSymbols.map((symbol) => (
              <span key={symbol} className="rounded-full bg-amber-900/30 px-2.5 py-1 text-xs text-amber-200">
                {symbol}
              </span>
            ))}
          </div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
          <div className="text-xs font-semibold text-slate-300">已隔離持倉</div>
          <div className="mt-3 space-y-2">
            {items.length === 0 ? (
              <div className="text-xs text-slate-500">沒有 active quarantine</div>
            ) : items.slice(0, 6).map((item) => (
              <div key={item.symbol} className="flex items-center justify-between gap-3 text-xs">
                <div>
                  <span className="text-slate-300">{item.symbol}</span>
                  <span className="ml-2 text-slate-500">
                    qty {item.position?.quantity ?? 0} · {item.reason_code}
                  </span>
                </div>
                <button
                  onClick={() => onClearSymbol?.(item.symbol)}
                  disabled={actionState?.loading?.clear}
                  className={`rounded-md px-2 py-1 text-[11px] font-medium ${
                    actionState?.loading?.clear
                      ? 'bg-slate-800 text-slate-500'
                      : 'bg-slate-700 text-slate-100 hover:bg-slate-600'
                  }`}
                >
                  清除此檔
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function IncidentClusterPanel({ clusters, resolvingFingerprint, resolveCluster, onResolved }) {
  const items = clusters?.items || []

  const handleResolve = async (item) => {
    const reason = window.prompt('請輸入解除 incident cluster 的原因:', 'root cause remediated')
    if (!reason) return
    await resolveCluster({
      source: item.source,
      code: item.code,
      fingerprint: item.fingerprint,
      reason,
    })
    onResolved?.()
  }

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold">Open Incident Clusters</div>
        <div className="text-xs text-slate-400">{clusters?.count || 0} clusters</div>
      </div>
      <div className="mt-4 space-y-3">
        {items.length === 0 ? (
          <div className="text-xs text-slate-500">目前沒有 open incident clusters</div>
        ) : items.slice(0, 6).map((item) => {
          const isResolving = resolvingFingerprint === item.fingerprint
          return (
            <div key={item.fingerprint} className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-xs font-semibold text-slate-200">{item.source} / {item.code}</div>
                  <div className="mt-1 text-xs text-slate-500">count {item.count} · latest {item.latest_ts}</div>
                </div>
                <button
                  onClick={() => handleResolve(item)}
                  disabled={isResolving}
                  className={`rounded-lg px-3 py-1.5 text-xs font-medium ${
                    isResolving
                      ? 'bg-slate-800 text-slate-500'
                      : 'bg-emerald-700 text-white hover:bg-emerald-600'
                  }`}
                >
                  {isResolving ? '處理中...' : '標記已處理'}
                </button>
              </div>
              <div className="mt-3 text-xs text-slate-400 break-all">{item.fingerprint}</div>
              {item.sample_detail && (
                <pre className="mt-3 overflow-x-auto rounded-lg border border-slate-800 bg-slate-950/60 p-3 text-[11px] leading-5 text-slate-400">
                  {JSON.stringify(item.sample_detail, null, 2)}
                </pre>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function RemediationHistoryPanel({ remediation }) {
  const items = remediation?.items || []
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold">Remediation History</div>
        <div className="text-xs text-slate-400">{remediation?.count || 0} actions</div>
      </div>
      <div className="mt-4 space-y-3">
        {items.length === 0 ? (
          <div className="text-xs text-slate-500">尚無 remediation actions</div>
        ) : items.slice(0, 8).map((item) => (
          <div key={item.action_id} className="flex items-start justify-between gap-3 border-b border-slate-800/80 pb-3 text-xs last:border-b-0">
            <div>
              <div className="text-slate-200">{actionLabel(item.action_type)} · {item.target_ref || '—'}</div>
              <div className="mt-1 text-slate-500">{item.actor} · {new Date(item.created_at).toLocaleString('zh-TW')}</div>
            </div>
            <div className={`rounded-full px-2 py-0.5 ${
              item.status === 'resolved' || item.status === 'applied' || item.status === 'cleared'
                ? 'bg-emerald-900/30 text-emerald-300'
                : 'bg-slate-800 text-slate-300'
            }`}>
              {item.status}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── main page ────────────────────────────────────────────────────────────────

export default function SystemPage() {
  const { data: health, error: healthErr } = useSystemHealth({ pollMs: 5000 })
  const { data: quota } = useSystemQuota({ pollMs: 30000 })
  const { data: risk } = useSystemRisk({ pollMs: 30000 })
  const { data: events } = useSystemEvents({ pollMs: 15000 })
  const { data: quarantineStatus, refresh: refreshQuarantineStatus } = useQuarantineStatus({ pollMs: 15000 })
  const { data: quarantinePlan, error: quarantinePlanErr, refresh: refreshQuarantinePlan } = useQuarantinePlan({ pollMs: 20000 })
  const {
    data: incidentClusters,
    resolveCluster,
    resolvingFingerprint,
    refresh: refreshClusters,
  } = useOpenIncidentClusters({ pollMs: 15000 })
  const { data: remediation, refresh: refreshRemediation } = useRemediationHistory({ pollMs: 15000, limit: 10 })
  const quarantineActions = useQuarantineActions()

  const handleClusterResolved = async () => {
    await Promise.allSettled([refreshClusters(), refreshRemediation()])
  }

  const handleApplyQuarantine = async () => {
    const result = await quarantineActions.applySuggestedQuarantine()
    if (result) {
      await Promise.allSettled([refreshQuarantinePlan(), refreshQuarantineStatus(), refreshRemediation()])
    }
  }

  const handleClearQuarantine = async () => {
    const confirmed = window.confirm('確定要清除全部 active quarantine 並從 fills 重建持倉嗎？')
    if (!confirmed) return
    const result = await quarantineActions.clearAllQuarantine()
    if (result) {
      await Promise.allSettled([refreshQuarantinePlan(), refreshQuarantineStatus(), refreshRemediation()])
    }
  }

  const handleClearQuarantineSymbol = async (symbol) => {
    const confirmed = window.confirm(`確定要清除 ${symbol} 的 quarantine 並重建持倉嗎？`)
    if (!confirmed) return
    const result = await quarantineActions.clearQuarantineSymbols([symbol])
    if (result) {
      await Promise.allSettled([refreshQuarantinePlan(), refreshQuarantineStatus(), refreshRemediation()])
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <div className="text-sm font-semibold">系統監控與控制</div>
        <div className="mt-1 text-xs text-slate-400">
          主開關、緊急停止、模擬/實際盤切換。風險控制是第一優先。
        </div>
        {healthErr && (
          <div className="mt-2 text-xs text-rose-400">健康狀態 API 離線：{healthErr}</div>
        )}
      </div>

      {/* 主要兩欄佈局：左 = 控制，右 = 狀態監控 */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* 左欄：操作控制 + 事件時間軸 */}
        <div className="space-y-6">
          <ControlPanel />
          <OperatorSnapshotPanel
            quarantineStatus={quarantineStatus}
            quarantinePlan={quarantinePlan}
            clusters={incidentClusters}
            remediation={remediation}
          />
          <QuarantinePanel
            status={quarantineStatus}
            plan={quarantinePlan}
            planError={quarantinePlanErr}
            actionState={quarantineActions}
            onApply={handleApplyQuarantine}
            onClear={handleClearQuarantine}
            onClearSymbol={handleClearQuarantineSymbol}
          />
          <IncidentClusterPanel
            clusters={incidentClusters}
            resolvingFingerprint={resolvingFingerprint}
            resolveCluster={resolveCluster}
            onResolved={handleClusterResolved}
          />
          <RemediationHistoryPanel remediation={remediation} />
          <EventsPanel events={events} />
        </div>

        {/* 右欄：服務狀態、資源、配額、風控 */}
        <div className="space-y-6">
          <ServiceStatusPanel health={health} />
          <SentinelPanel health={health} />
          <ResourcePanel health={health} />
          <QuotaPanel quota={quota} />
          <RiskPanel risk={risk} />
        </div>
      </div>

      <LogTerminal />

      {/* Version info */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel">
        <div className="text-sm font-semibold">系統版本資訊</div>
        <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
          <div className="space-y-1">
            <div className="text-slate-400">前端版本</div>
            <div className="text-slate-300">v{__APP_VERSION__}</div>
          </div>
          <div className="space-y-1">
            <div className="text-slate-400">後端版本</div>
            <div className="text-slate-300">v{__APP_VERSION__}</div>
          </div>
          <div className="space-y-1">
            <div className="text-slate-400">DB WAL</div>
            <div className="text-slate-300">
              {health?.db_health?.wal_size_bytes != null
                ? `${(health.db_health.wal_size_bytes / 1024).toFixed(1)} KB`
                : '—'}
            </div>
          </div>
          <div className="space-y-1">
            <div className="text-slate-400">寫入延遲 P99</div>
            <div className="text-slate-300">
              {health?.db_health?.write_latency_p99_ms != null
                ? `${health.db_health.write_latency_p99_ms} ms`
                : '—'}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
