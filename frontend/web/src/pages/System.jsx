import React from 'react'
import ControlPanel from '../components/ControlPanel'
import LogTerminal from '../components/LogTerminal'
import { useSystemHealth, useSystemQuota, useSystemRisk, useSystemEvents } from '../lib/systemApi'

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

// ─── main page ────────────────────────────────────────────────────────────────

export default function SystemPage() {
  const { data: health, error: healthErr } = useSystemHealth({ pollMs: 5000 })
  const { data: quota } = useSystemQuota({ pollMs: 30000 })
  const { data: risk } = useSystemRisk({ pollMs: 30000 })
  const { data: events } = useSystemEvents({ pollMs: 15000 })

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

      <ControlPanel />

      {/* Row 1: Service status + Sentinel + Resource */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <ServiceStatusPanel health={health} />
        <SentinelPanel health={health} />
        <ResourcePanel health={health} />
      </div>

      {/* Row 2: Quota + Risk */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <QuotaPanel quota={quota} />
        <RiskPanel risk={risk} />
      </div>

      {/* Row 3: Event timeline */}
      <EventsPanel events={events} />

      <LogTerminal />

      {/* Version info */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel">
        <div className="text-sm font-semibold">系統版本資訊</div>
        <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
          <div className="space-y-1">
            <div className="text-slate-400">前端版本</div>
            <div className="text-slate-300">v4.6.0</div>
          </div>
          <div className="space-y-1">
            <div className="text-slate-400">後端版本</div>
            <div className="text-slate-300">v4.6.0</div>
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
