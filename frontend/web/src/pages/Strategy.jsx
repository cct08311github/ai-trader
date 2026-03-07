import React, { useEffect, useMemo, useState, Fragment } from 'react'
import { useStreamApiBase, useStrategyData } from '../lib/strategyApi'
import { CheckCircle2, XCircle, Clock, ChevronDown, ChevronRight, MessageSquare, Target, Save, FileSignature, ShieldAlert, Cpu, Copy, Check } from 'lucide-react'
import { authFetch, getApiBase, getToken } from '../lib/auth'
import { useToast } from '../components/ToastProvider'
import { useSymbolNames, formatSymbol } from '../lib/symbolNames'

function formatUnixSec(sec) {
  const n = Number(sec)
  if (!Number.isFinite(n) || n <= 0) return ''
  // If n > 1e12 it's already milliseconds; otherwise treat as seconds
  const ms = n > 1e12 ? n : n * 1000
  return new Date(ms).toLocaleString('zh-TW', { hour12: false })
}

function safeJsonParse(s) {
  try {
    return JSON.parse(s)
  } catch {
    return null
  }
}

function StatusTag({ status }) {
  const s = String(status || '').toLowerCase() || 'unknown'
  const map = {
    pending:  'bg-slate-800 text-slate-200 border-slate-700',
    approved: 'bg-emerald-900/30 text-emerald-200 border-emerald-800',
    rejected: 'bg-rose-900/30 text-rose-200 border-rose-800',
    executed: 'bg-indigo-900/30 text-indigo-200 border-indigo-800',
    unknown:  'bg-slate-900/30 text-slate-300 border-slate-800',
  }
  const label = {
    pending:  'pending 待審',
    approved: 'approved 已批准',
    rejected: 'rejected 已拒絕',
    executed: 'executed 已執行',
  }
  const cls = map[s] || map.unknown
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${cls}`}>
      {label[s] || s}
    </span>
  )
}

function RatingCard({ rating, basis }) {
  const r = String(rating || '').toUpperCase()
  const theme = {
    A: { bg: 'bg-emerald-900/20', border: 'border-emerald-700', text: 'text-emerald-200', sub: 'text-emerald-200/80' },
    B: { bg: 'bg-amber-900/15',  border: 'border-amber-700',   text: 'text-amber-200',   sub: 'text-amber-200/80'  },
    C: { bg: 'bg-rose-900/15',   border: 'border-rose-700',    text: 'text-rose-200',    sub: 'text-rose-200/80'   },
  }[r] || { bg: 'bg-slate-950/20', border: 'border-slate-800', text: 'text-slate-200', sub: 'text-slate-400' }

  return (
    <div className={`rounded-2xl border ${theme.border} ${theme.bg} p-6 shadow-panel`}>
      <div className="text-sm font-semibold text-slate-300">今日市場評級</div>
      <div className="mt-4 flex items-end justify-between gap-4">
        <div className={`text-6xl font-black tracking-tight ${theme.text}`}>{r || '-'}</div>
        <div className="text-right text-[11px] text-slate-500">來源：llm_traces PM</div>
      </div>
      <div className={`mt-4 whitespace-pre-wrap break-words text-xs leading-relaxed ${theme.sub}`}>{basis || '(暫無評級依據)'}</div>
    </div>
  )
}

/** PM LLM Trace Panel — shows full prompt + raw Gemini response */
function PmTracePanel() {
  const [traces, setTraces] = useState([])
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState({}) // trace_id -> 'prompt' | 'response' | null

  function reload() {
    setLoading(true)
    const base = getApiBase()
    authFetch(`${base}/api/strategy/pm-traces?limit=5`)
      .then(r => r.json())
      .then(d => { setTraces(d?.data || []); setLoading(false) })
      .catch(() => setLoading(false))
  }

  useEffect(() => { reload() }, [])

  function toggle(id, field) {
    setExpanded(prev => ({ ...prev, [id]: prev[id] === field ? null : field }))
  }

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-5 shadow-panel">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-200">PM 審核提示詞 &amp; 原始回覆</div>
          <div className="text-xs text-slate-500 mt-0.5">點擊展開，可查看送給 Gemini 的完整提示詞及原始 JSON 回覆</div>
        </div>
        <button
          onClick={reload}
          disabled={loading}
          className="rounded-lg bg-slate-800 px-3 py-2 text-xs font-medium text-slate-200 hover:bg-slate-700 disabled:opacity-50"
        >
          {loading ? '載入中…' : '重新整理'}
        </button>
      </div>

      {loading ? (
        <div className="text-xs text-slate-500 py-6 text-center">載入中…</div>
      ) : traces.length === 0 ? (
        <div className="text-xs text-slate-500 py-8 text-center">無記錄（點擊 Portfolio 頁面的「AI 審核」按鈕後才會出現）</div>
      ) : (
        <div className="space-y-3">
          {traces.map(t => (
            <div key={t.trace_id} className="rounded-xl border border-slate-800 overflow-hidden">
              {/* Header row */}
              <div className="flex flex-wrap items-center gap-3 px-4 py-2.5 bg-slate-950/50 text-[11px] text-slate-400">
                <span className="font-mono text-slate-300">{t.trace_id}</span>
                <span>{formatUnixSec(t.created_at)}</span>
                <span className="text-indigo-300">{t.model}</span>
                {t.latency_ms != null && <span>{t.latency_ms} ms</span>}
              </div>

              {/* Prompt section */}
              <div className="border-t border-slate-800">
                <button
                  onClick={() => toggle(t.trace_id, 'prompt')}
                  className="flex items-center gap-2 px-4 py-2 w-full text-left text-xs font-medium text-amber-300 hover:bg-slate-950/30"
                >
                  {expanded[t.trace_id] === 'prompt'
                    ? <ChevronDown className="h-3.5 w-3.5 flex-shrink-0" />
                    : <ChevronRight className="h-3.5 w-3.5 flex-shrink-0" />}
                  提示詞 (Prompt)
                </button>
                {expanded[t.trace_id] === 'prompt' && (
                  <pre className="max-h-[60vh] overflow-auto px-4 pb-4 text-[11px] text-slate-300 whitespace-pre-wrap break-words leading-relaxed">
                    {t.prompt || '(無內容)'}
                  </pre>
                )}
              </div>

              {/* Raw response section */}
              <div className="border-t border-slate-800">
                <button
                  onClick={() => toggle(t.trace_id, 'response')}
                  className="flex items-center gap-2 px-4 py-2 w-full text-left text-xs font-medium text-emerald-300 hover:bg-slate-950/30"
                >
                  {expanded[t.trace_id] === 'response'
                    ? <ChevronDown className="h-3.5 w-3.5 flex-shrink-0" />
                    : <ChevronRight className="h-3.5 w-3.5 flex-shrink-0" />}
                  原始回覆 (Raw Response)
                </button>
                {expanded[t.trace_id] === 'response' && (
                  <pre className="max-h-[60vh] overflow-auto px-4 pb-4 text-[11px] text-emerald-200 whitespace-pre-wrap break-words leading-relaxed">
                    {t.response || '(無內容)'}
                  </pre>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Bull vs Bear Debate Panel — design doc §4.3 */
function DebatePanel() {
  const [debates, setDebates] = useState([])
  const [date, setDate] = useState('today')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    const base = getApiBase()
    authFetch(`${base}/api/strategy/debates?date=${date}`)
      .then(r => r.json())
      .then(d => { setDebates(d?.data || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [date])

  // Parse debate content from episodic_memory (content_json field)
  const parsed = useMemo(() => {
    return debates.map(d => {
      const cj = safeJsonParse(d.content_json || '{}') || {}
      const approved = cj.approved
      return {
        id: d.episode_id || d.id,
        timestamp: d.created_at,
        bull: cj.bull_case || null,
        bear: cj.bear_case || null,
        neutral: cj.neutral_case || null,
        pm: cj.recommended_action
          ? `${cj.recommended_action}（信心 ${((cj.confidence || 0) * 100).toFixed(0)}%，${approved ? '✅ 授權' : '🚫 封鎖'}）`
          : null,
        summary: d.summary || null,
      }
    })
  }, [debates])

  const today = new Date().toISOString().slice(0, 10)

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-5 shadow-panel">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-200">多空辯論記錄</div>
          <div className="text-xs text-slate-500 mt-0.5">每日 PM 審核辯論記錄（來源：Gemini AI）</div>
        </div>
        <input
          type="date"
          value={date === 'today' ? today : date}
          onChange={e => setDate(e.target.value)}
          className="rounded-xl border border-slate-700 bg-slate-950/60 px-3 py-1.5 text-sm text-slate-200 focus:border-emerald-500/50 focus:outline-none"
        />
      </div>

      {loading ? (
        <div className="text-xs text-slate-500 py-6 text-center">載入中…</div>
      ) : parsed.length === 0 ? (
        <div className="text-xs text-slate-500 py-8 text-center">當日無辯論記錄（按 Portfolio 頁面的「AI 審核」觸發）</div>
      ) : (
        <div className="space-y-4">
          {parsed.map((d, i) => (
            <div key={d.id || i} className="rounded-xl border border-slate-800 overflow-hidden">
              {d.summary && (
                <div className="px-4 py-2 bg-slate-950/50 text-[11px] text-slate-400 border-b border-slate-800">
                  {formatUnixSec(d.timestamp)}
                  {' — '}{d.summary}
                </div>
              )}
              <div className="grid grid-cols-1 divide-y divide-slate-800 lg:grid-cols-3 lg:divide-x lg:divide-y-0">
                {/* Bull case */}
                <div className="p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="inline-block h-2 w-2 rounded-full bg-emerald-400" />
                    <span className="text-xs font-semibold text-emerald-300">多方觀點</span>
                  </div>
                  <p className="text-xs text-slate-300 leading-relaxed">
                    {d.bull || <span className="text-slate-600">（無資料）</span>}
                  </p>
                </div>
                {/* Bear case */}
                <div className="p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="inline-block h-2 w-2 rounded-full bg-rose-400" />
                    <span className="text-xs font-semibold text-rose-300">空方觀點</span>
                  </div>
                  <p className="text-xs text-slate-300 leading-relaxed">
                    {d.bear || <span className="text-slate-600">（無資料）</span>}
                  </p>
                </div>
                {/* PM decision */}
                <div className="p-4 bg-slate-900/40">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="inline-block h-2 w-2 rounded-full bg-cyan-400" />
                    <span className="text-xs font-semibold text-cyan-300">PM 最終判斷</span>
                  </div>
                  <p className="text-xs text-slate-200 leading-relaxed font-medium">
                    {d.pm || <span className="text-slate-600">（無資料）</span>}
                  </p>
                  {d.neutral && (
                    <p className="mt-2 text-[11px] text-slate-500 leading-relaxed">{d.neutral}</p>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function JsonBox({ value }) {
  const text = useMemo(() => {
    if (value == null) return ''
    if (typeof value === 'string') {
      const j = safeJsonParse(value)
      if (j) return JSON.stringify(j, null, 2)
      return value
    }
    return JSON.stringify(value, null, 2)
  }, [value])

  if (!text) return <div className="text-xs text-slate-500">（無內容）</div>

  return (
    <pre className="max-h-[35vh] sm:max-h-[55vh] overflow-y-auto overflow-x-hidden rounded-xl border border-slate-800 bg-slate-950/40 p-3 text-xs text-slate-200 whitespace-pre-wrap break-all">
      {text}
    </pre>
  )
}

function CommitteeContextCard({ title, tone, content, confidence, icon }) {
  const toneClasses = {
    emerald: 'border-emerald-800 bg-emerald-950/20 text-emerald-100',
    rose: 'border-rose-800 bg-rose-950/20 text-rose-100',
    cyan: 'border-cyan-800 bg-cyan-950/20 text-cyan-100',
    slate: 'border-slate-800 bg-slate-950/20 text-slate-100',
  }
  const theme = toneClasses[tone] || toneClasses.slate
  return (
    <div className={`rounded-xl border p-3 ${theme}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs font-semibold">
          <span>{icon}</span>
          <span>{title}</span>
        </div>
        {confidence != null && confidence !== '' && (
          <span className="text-[11px] opacity-80">信心 {Math.round(Number(confidence) * 100)}%</span>
        )}
      </div>
      <div className="mt-2 whitespace-pre-wrap break-words text-xs leading-relaxed">
        {content || '（無內容）'}
      </div>
    </div>
  )
}

function CommitteeDecisionBasis({ basis }) {
  if (!basis) return null
  const sections = [
    ['多方重點', basis.bull_points],
    ['空方重點', basis.bear_points],
    ['主要權衡', basis.key_tradeoffs],
    ['資料缺口', basis.data_gaps],
  ]
  return (
    <div className="space-y-3">
      {sections.map(([label, items]) => (
        <div key={label} className="rounded-xl border border-slate-800 bg-slate-950/20 p-3">
          <div className="text-[11px] font-semibold text-slate-300">{label}</div>
          {Array.isArray(items) && items.length > 0 ? (
            <ul className="mt-2 space-y-1 text-xs text-slate-300">
              {items.map((item, idx) => (
                <li key={idx} className="break-words">- {item}</li>
              ))}
            </ul>
          ) : (
            <div className="mt-2 text-xs text-slate-500">（無資料）</div>
          )}
        </div>
      ))}
    </div>
  )
}

function CommitteeContextSection({ payload }) {
  const ctx = payload?.committee_context
  if (!ctx) return null

  return (
    <div className="mt-4 space-y-4">
      <div>
        <div className="text-xs font-semibold text-slate-200">委員會辯論脈絡</div>
        <div className="mt-1 text-[11px] text-slate-500">
          這裡顯示 Bull / Bear / Arbiter 的實際輸出，不只是一句最終建議。
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <CommitteeContextCard
          title="Bull Analyst"
          tone="emerald"
          icon="▲"
          content={ctx?.bull?.thesis}
          confidence={ctx?.bull?.confidence}
        />
        <CommitteeContextCard
          title="Bear Analyst"
          tone="rose"
          icon="▼"
          content={ctx?.bear?.thesis}
          confidence={ctx?.bear?.confidence}
        />
        <CommitteeContextCard
          title={`Risk Arbiter${ctx?.arbiter?.stance ? ` · ${ctx.arbiter.stance}` : ''}`}
          tone="cyan"
          icon="◆"
          content={ctx?.arbiter?.summary}
          confidence={payload?.confidence ?? ctx?.arbiter?.raw?.confidence}
        />
      </div>

      <CommitteeDecisionBasis basis={ctx?.arbiter?.decision_basis} />

      <div className="rounded-xl border border-slate-800 bg-slate-950/20 p-3">
        <div className="text-[11px] font-semibold text-slate-300">委員會輸入資料摘要</div>
        <pre className="mt-2 max-h-[24vh] overflow-auto whitespace-pre-wrap break-all text-[11px] leading-relaxed text-slate-400">
          {ctx?.market_data || '（無資料）'}
        </pre>
      </div>
    </div>
  )
}

function DuplicateAlertsSection({ payload }) {
  const alerts = Array.isArray(payload?.duplicate_alerts) ? payload.duplicate_alerts : []
  if (alerts.length === 0) return null

  return (
    <div className="mt-4 rounded-xl border border-amber-800/70 bg-amber-950/20 p-4">
      <div className="text-xs font-semibold text-amber-200">重複提案告警</div>
      <div className="mt-1 text-[11px] text-amber-300/80">
        這筆提案與近期策略方向高度相似，系統可能已做去重或需人工確認是否只是換句話說。
      </div>
      <div className="mt-3 space-y-3">
        {alerts.map((alert, idx) => (
          <div key={`${alert?.duplicate_of || 'dup'}-${idx}`} className="rounded-lg border border-amber-800/60 bg-slate-950/30 p-3 text-xs text-slate-200">
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-amber-200/90">
              <span>duplicate_of: <code>{alert?.duplicate_of || '-'}</code></span>
              <span>similarity: {alert?.similarity ?? '-'}</span>
              <span>lookback: {alert?.lookback_hours ?? '-'}h</span>
            </div>
            {alert?.proposed_value && (
              <div className="mt-2 break-words text-slate-200">{alert.proposed_value}</div>
            )}
            {alert?.supporting_evidence && (
              <div className="mt-1 break-words text-slate-400">{alert.supporting_evidence}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function DuplicateAlertFeed({ logs }) {
  const alerts = useMemo(() => {
    return (logs || [])
      .map(log => {
        const response = safeJsonParse(log?.response || '{}') || {}
        const alert = response?.duplicate_alert
        if (!alert || alert?.action !== 'suppressed') return null
        return {
          traceId: log?.trace_id,
          createdAt: log?.created_at,
          summary: response?.summary || '',
          ...alert,
        }
      })
      .filter(Boolean)
      .slice(0, 8)
  }, [logs])

  return (
    <div className="rounded-2xl border border-amber-800/60 bg-amber-950/10 p-5 shadow-panel">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-amber-200">重複提案告警</div>
          <div className="mt-1 text-xs text-amber-300/70">
            這裡列出 Strategy Committee 近期被 suppress 的重複方向，方便確認系統不是一直重送同一類建議。
          </div>
        </div>
        <div className="rounded-full border border-amber-800/60 px-2 py-0.5 text-[11px] text-amber-200">
          {alerts.length} 筆
        </div>
      </div>

      {alerts.length === 0 ? (
        <div className="mt-4 text-xs text-slate-500">目前沒有重複提案 suppression 記錄。</div>
      ) : (
        <div className="mt-4 space-y-3">
          {alerts.map(alert => (
            <div key={alert.traceId || `${alert.duplicate_of}-${alert.createdAt}`} className="rounded-xl border border-amber-800/50 bg-slate-950/30 p-4">
              <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-400">
                <span>{formatUnixSec(alert.createdAt) || '-'}</span>
                <span className="text-amber-200">similarity {alert.similarity ?? '-'}</span>
                <span>lookback {alert.lookback_hours ?? '-'}h</span>
                {alert.traceId && <span className="font-mono text-slate-500">{alert.traceId}</span>}
              </div>
              <div className="mt-2 text-xs font-medium text-slate-200 break-words">
                {alert.proposed_value || '（無提案摘要）'}
              </div>
              {alert.supporting_evidence && (
                <div className="mt-1 text-xs text-slate-400 break-words">{alert.supporting_evidence}</div>
              )}
              <div className="mt-2 text-[11px] text-amber-300/80">
                duplicate_of: <code>{alert.duplicate_of || '-'}</code>
              </div>
              {alert.summary && (
                <div className="mt-2 text-[11px] text-slate-500">{alert.summary}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ProposalModal({ open, onClose, proposal, onApprove, onReject, busy }) {
  const payload = safeJsonParse(proposal?.proposal_json || '')
  const status = String(proposal?.status || '').toLowerCase()
  const isPending = status === 'pending'

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onMouseDown={onClose}>
      <div className="w-full max-w-4xl rounded-2xl border border-slate-800 bg-slate-900 p-5 shadow-panel overflow-y-auto overflow-x-hidden max-h-[90dvh]" onMouseDown={e => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-slate-200">提案詳情</div>
            <div className="mt-1 text-xs text-slate-400">
              ID: <code className="text-slate-200">{proposal?.proposal_id || '-'}</code>
              <span className="mx-2">·</span>
              {formatUnixSec(proposal?.created_at) || '-'}
              <span className="mx-2">·</span>
              <StatusTag status={proposal?.status} />
            </div>
          </div>
          <button onClick={onClose} className="rounded-lg bg-slate-800 px-3 py-2 text-xs font-medium text-slate-200 hover:bg-slate-700">
            關閉
          </button>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {/* Left: metadata + actions */}
          <div className="space-y-2">
            <div className="text-xs font-semibold text-slate-200">基本資訊</div>
            <div className="rounded-xl border border-slate-800 bg-slate-950/20 p-3 text-xs text-slate-300">
              <div className="grid grid-cols-3 gap-2">
                <div className="text-slate-500">generated_by</div>
                <div className="col-span-2 break-words">{proposal?.generated_by || '-'}</div>
                <div className="text-slate-500">target_rule</div>
                <div className="col-span-2 break-words">{proposal?.target_rule || '-'}</div>
                <div className="text-slate-500">rule_category</div>
                <div className="col-span-2 break-words">{proposal?.rule_category || '-'}</div>
                <div className="text-slate-500">confidence</div>
                <div className="col-span-2 break-words">{proposal?.confidence ?? '-'}</div>
                <div className="text-slate-500">decided_at</div>
                <div className="col-span-2 break-words">{formatUnixSec(proposal?.decided_at) || '-'}</div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                disabled={busy || !isPending}
                onClick={onApprove}
                className="rounded-lg bg-emerald-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40 hover:bg-emerald-500"
              >
                ✓ Approve（批准）
              </button>
              <button
                disabled={busy || !isPending}
                onClick={onReject}
                className="rounded-lg bg-rose-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40 hover:bg-rose-500"
              >
                ✕ Reject（拒絕）
              </button>
              {!isPending && (
                <div className="text-[11px] text-slate-500">僅 pending 狀態可操作</div>
              )}
            </div>
          </div>

          {/* Right: proposal_json */}
          <div className="space-y-2">
            <div className="text-xs font-semibold text-slate-200">proposal_json 原始資料</div>
            <JsonBox value={payload || proposal?.proposal_json} />
          </div>
        </div>

        <CommitteeContextSection payload={payload} />
        <DuplicateAlertsSection payload={payload} />
      </div>
    </div>
  )
}

function SemanticMemoryTable({ data }) {
  if (!data || data.length === 0) return <div className="text-xs text-slate-500 py-4">（尚無學習規則）</div>
  return (
    <div className="overflow-auto rounded-xl border border-slate-800">
      <table className="w-full text-left text-[11px]">
        <thead className="bg-slate-950/40 text-slate-400">
          <tr>
            <th className="px-3 py-2">信心度</th>
            <th className="px-3 py-2">Rule Key</th>
            <th className="px-3 py-2">規則內容</th>
            <th className="px-3 py-2">更新時間</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {data.map((m, idx) => (
            <tr key={m.sm_id || m.rule_key || idx} className="hover:bg-slate-950/30">
              <td className="px-3 py-2 text-slate-300">{((m.confidence || 0) * 100).toFixed(0)}%</td>
              <td className="px-3 py-2 text-slate-200 font-mono">{m.rule_key || m.sm_id}</td>
              <td className="px-3 py-2 text-slate-400 break-words">{m.statement || m.content_summary || ''}</td>
              <td className="px-3 py-2 text-slate-500">{formatUnixSec(m.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function StrategyPage() {
  const { proposals, logs, marketRating, semanticMemory, debates, error, loading, act, refreshProposals, refreshLogs, refreshSemanticMemory } = useStrategyData({ pollMs: 10000 })
  const STREAM_BASE = useStreamApiBase()
  const symbolNames = useSymbolNames()

  const toast = useToast()
  const [selected, setSelected] = useState(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [pendingAct, setPendingAct] = useState(null)  // { type: 'approve'|'reject', proposal }
  const [copiedId, setCopiedId] = useState(null)

  const [memOrder, setMemOrder] = useState('desc')

  // SSE 整合：監聽 llm_traces 新事件 → 自動刷新提案列表（debounce 500ms）
  useEffect(() => {
    const token = getToken()
    const url = `${STREAM_BASE}/logs${token ? `?token=${token}` : ''}`
    const es = new EventSource(url)

    let t = null
    const scheduleRefresh = () => {
      if (t) clearTimeout(t)
      t = setTimeout(() => {
        refreshProposals()
        refreshLogs()
      }, 500)
    }

    es.addEventListener('log', scheduleRefresh)
    es.addEventListener('error', () => {
      // ignore; browser will reconnect
    })

    return () => {
      if (t) clearTimeout(t)
      es.close()
    }
  }, [STREAM_BASE, refreshProposals, refreshLogs])

  useEffect(() => {
    if (refreshSemanticMemory) {
      refreshSemanticMemory({ sort: 'confidence', order: memOrder, limit: 50 })
    }
  }, [memOrder, refreshSemanticMemory])

  const rows = useMemo(() => {
    return (proposals || []).map(p => {
      const payload = safeJsonParse(p?.proposal_json || '') || {}
      const symbol = payload?.symbol || payload?.ticker || payload?.stock || payload?.contract || ''
      const side = payload?.side || payload?.direction || payload?.action || ''
      return {
        ...p,
        _symbol: symbol ? formatSymbol(symbol, symbolNames) : '-',
        _side: side || '-',
        _ts: formatUnixSec(p?.created_at) || '-'
      }
    })
  }, [proposals, symbolNames])

  const openDetail = p => {
    setSelected(p)
    setModalOpen(true)
  }

  const closeDetail = () => {
    setModalOpen(false)
  }

  const doApprove = (p) => {
    if (!p?.proposal_id) return
    setPendingAct({ type: 'approve', proposal: p })
  }

  const doReject = (p) => {
    if (!p?.proposal_id) return
    setPendingAct({ type: 'reject', proposal: p })
  }

  const confirmAct = async () => {
    if (!pendingAct) return
    const { type, proposal: p } = pendingAct
    setPendingAct(null)
    setModalOpen(false)
    try {
      await act(type, p.proposal_id, { actor: 'operator', reason: `manual ${type} via UI` })
      toast.success(type === 'approve' ? `提案 ${p.proposal_id} 已批准` : `提案 ${p.proposal_id} 已拒絕`)
    } catch (e) {
      toast.error(`操作失敗：${e?.message || e}`)
    }
  }

  function copyId(id) {
    navigator.clipboard.writeText(id).then(() => {
      setCopiedId(id)
      setTimeout(() => setCopiedId(null), 2000)
    })
  }

  return (
    <div className="space-y-5">
      {/* ── 提案審核列表 ─────────────────────────────────────────────── */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel">
        <div>
          <div className="text-sm font-semibold text-slate-200">策略提案審核</div>
          <div className="mt-1 text-xs text-slate-400">
            pending 可手動 Approve / Reject；approved → 排隊執行；executed → 已成交；rejected → 已封鎖。
            點擊 ID 開啟 proposal_json 詳情。提案列表由 SSE llm_traces 事件自動刷新。
          </div>
        </div>

        {error && <div className="mt-4 rounded-lg border border-rose-800 bg-rose-900/20 p-3 text-xs text-rose-300">{error}</div>}

        <div className="mt-5 overflow-auto rounded-xl border border-slate-800">
          <table className="min-w-full sm:min-w-[980px] w-full text-left text-xs">
            <thead className="bg-slate-950/40 text-slate-400">
              <tr>
                <th className="px-4 py-3">時間</th>
                <th className="px-4 py-3">Proposal ID</th>
                <th className="px-4 py-3">標的</th>
                <th className="px-4 py-3">方向</th>
                <th className="px-4 py-3">信心度</th>
                <th className="px-4 py-3">狀態</th>
                <th className="px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {rows.length === 0 ? (
                <tr>
                  <td className="px-4 py-5 text-slate-500" colSpan={7}>
                    {loading.proposals ? '讀取中...' : '目前無提案記錄'}
                  </td>
                </tr>
              ) : (
                rows.map(p => {
                  const status = String(p?.status || '').toLowerCase()
                  const canAct = status === 'pending'
                  return (
                    <tr key={p.proposal_id} className="hover:bg-slate-950/30">
                      <td className="px-4 py-3 text-slate-300 whitespace-nowrap">{p._ts}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          <button onClick={() => openDetail(p)} className="text-slate-200 hover:text-white underline underline-offset-2">
                            {p.proposal_id}
                          </button>
                          <button
                            onClick={e => { e.stopPropagation(); copyId(p.proposal_id) }}
                            title="複製 Proposal ID"
                            className="text-slate-600 hover:text-slate-300 transition-colors"
                          >
                            {copiedId === p.proposal_id
                              ? <Check className="h-3 w-3 text-emerald-400" />
                              : <Copy className="h-3 w-3" />}
                          </button>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-slate-300">{p._symbol}</td>
                      <td className="px-4 py-3 text-slate-300">{p._side}</td>
                      <td className="px-4 py-3 text-slate-300">{p.confidence ?? '-'}</td>
                      <td className="px-4 py-3">
                        <StatusTag status={p.status} />
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <button
                            disabled={!canAct || loading.act}
                            onClick={() => doApprove(p)}
                            className="rounded-lg bg-emerald-700 px-2.5 py-1.5 text-[11px] font-semibold text-white disabled:opacity-40 hover:bg-emerald-600"
                          >
                            Approve
                          </button>
                          <button
                            disabled={!canAct || loading.act}
                            onClick={() => doReject(p)}
                            className="rounded-lg bg-rose-700 px-2.5 py-1.5 text-[11px] font-semibold text-white disabled:opacity-40 hover:bg-rose-600"
                          >
                            Reject
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>

        <div className="mt-3 text-[11px] text-slate-500">
          點擊 Proposal ID 開啟詳情 · approve/reject 需要 OPS TOKEN · 由 SSE llm_traces 事件自動刷新（每 10s 輪詢兜底）
        </div>
      </div>

      {/* ── 市場評級 + Semantic Memory ────────────────────────────────── */}
      <div className="grid gap-5 lg:grid-cols-3">
        <RatingCard rating={marketRating?.rating} basis={marketRating?.basis} />

        <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel lg:col-span-2">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-slate-200">語義記憶（Semantic Memory）</div>
              <div className="mt-1 text-xs text-slate-400">
                AI 學習沉澱的交易規則，由 source episodes 累積 confidence 決定優先級
              </div>
            </div>
            <button
              onClick={() => setMemOrder(o => (o === 'desc' ? 'asc' : 'desc'))}
              className="rounded-lg bg-slate-800 px-3 py-2 text-xs hover:bg-slate-700 transition-colors text-slate-200"
            >
              信心度 {memOrder === 'desc' ? '↓ 高→低' : '↑ 低→高'}
            </button>
          </div>
          <div className="mt-4">
            <SemanticMemoryTable data={semanticMemory} />
          </div>
        </div>
      </div>

      {/* ── 提案詳情 Modal ────────────────────────────────────────────── */}
      <ProposalModal
        open={modalOpen}
        onClose={closeDetail}
        proposal={selected}
        busy={loading.act}
        onApprove={() => doApprove(selected)}
        onReject={() => doReject(selected)}
      />

      {/* ── 多空辯論記錄 ─────────────────────────────────────────────── */}
      <DebatePanel />

      <DuplicateAlertFeed logs={logs} />

      {/* ── PM LLM Trace ─────────────────────────────────────────────── */}
      <PmTracePanel />

      {/* ── Approve / Reject 確認 Dialog ──────────────────────────────── */}
      {pendingAct && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4"
          onMouseDown={() => setPendingAct(null)}
        >
          <div
            className="w-full max-w-xs rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl"
            onMouseDown={e => e.stopPropagation()}
          >
            <div className={`text-sm font-semibold mb-2 ${pendingAct.type === 'approve' ? 'text-emerald-300' : 'text-rose-300'}`}>
              確認{pendingAct.type === 'approve' ? '批准' : '拒絕'}提案
            </div>
            <div className="text-xs text-slate-500 mb-1">Proposal ID</div>
            <div className="text-xs text-slate-200 font-mono bg-slate-950/60 rounded-lg px-3 py-2 mb-4 break-all">
              {pendingAct.proposal?.proposal_id}
            </div>
            <div className="flex gap-3">
              <button
                onClick={() => setPendingAct(null)}
                className="flex-1 rounded-xl border border-slate-700 py-2 text-sm font-medium text-slate-300 hover:bg-slate-800 transition-colors"
              >
                取消
              </button>
              <button
                autoFocus
                onClick={confirmAct}
                className={`flex-1 rounded-xl py-2 text-sm font-semibold text-white transition-colors ${
                  pendingAct.type === 'approve' ? 'bg-emerald-600 hover:bg-emerald-500' : 'bg-rose-600 hover:bg-rose-500'
                }`}
              >
                確認
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
