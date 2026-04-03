/**
 * Strategy.jsx -- BattleTheme Redesign
 *
 * Strategy war room: proposal review table, market rating,
 * committee debates (Bull vs Bear), LLM traces, semantic memory.
 * Brutalist panels, monospace labels, status dots, accent borders.
 */

import React, { useEffect, useMemo, useState, Fragment } from 'react'
import { useStreamApiBase, useStrategyData } from '../lib/strategyApi'
import { CheckCircle2, XCircle, Clock, ChevronDown, ChevronRight, MessageSquare, Target, Save, FileSignature, ShieldAlert, Cpu, Copy, Check, FileText, Lightbulb } from 'lucide-react'
import { authFetch, getApiBase, getToken } from '../lib/auth'
import { useToast } from '../components/ToastProvider'
import { useSymbolNames, formatSymbol } from '../lib/symbolNames'
import EmptyState from '../components/EmptyState'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorState from '../components/ErrorState'

function formatUnixSec(sec) {
  const n = Number(sec)
  if (!Number.isFinite(n) || n <= 0) return ''
  const ms = n > 1e12 ? n : n * 1000
  return new Date(ms).toLocaleString('zh-TW', { hour12: false })
}

function safeJsonParse(s) {
  try { return JSON.parse(s) } catch { return null }
}

/* ── Panel wrapper ──────────────────────────────────────────── */
function Panel({ title, right, children, className = '' }) {
  return (
    <section className={`border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.6)] ${className}`} style={{ borderRadius: '4px' }}>
      <div className="flex items-center justify-between border-b border-[rgba(var(--grid),0.3)] px-4 py-2.5">
        <div className="font-mono text-[10px] font-semibold uppercase tracking-widest text-[rgb(var(--text))]">{title}</div>
        {right && <div className="font-mono text-[10px] text-[rgb(var(--muted))]">{right}</div>}
      </div>
      <div className="p-4">{children}</div>
    </section>
  )
}

/* ── Status Tag with dot ───────────────────────────────────── */
function StatusTag({ status }) {
  const s = String(status || '').toLowerCase() || 'unknown'
  const map = {
    pending:  { dot: 'bg-[rgb(var(--warn))]', text: 'text-[rgb(var(--warn))]', label: 'PENDING' },
    approved: { dot: 'bg-[rgb(var(--up))]', text: 'text-[rgb(var(--up))]', label: 'APPROVED' },
    rejected: { dot: 'bg-[rgb(var(--danger))]', text: 'text-[rgb(var(--danger))]', label: 'REJECTED' },
    executed: { dot: 'bg-[rgb(var(--info))]', text: 'text-[rgb(var(--info))]', label: 'EXECUTED' },
    unknown:  { dot: 'bg-[rgb(var(--muted))]', text: 'text-[rgb(var(--muted))]', label: s.toUpperCase() },
  }
  const t = map[s] || map.unknown
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-2 w-2 rounded-full ${t.dot}`} />
      <span className={`font-mono text-[10px] font-bold uppercase tracking-widest ${t.text}`}>{t.label}</span>
    </span>
  )
}

/* ── Rating Card ──────────────────────────────────────────── */
function RatingCard({ rating, basis }) {
  const r = String(rating || '').toUpperCase()
  const borderColor = {
    A: 'border-l-[rgb(var(--up))]',
    B: 'border-l-[rgb(var(--warn))]',
    C: 'border-l-[rgb(var(--danger))]',
  }[r] || 'border-l-[rgb(var(--muted))]'
  const textColor = {
    A: 'text-[rgb(var(--up))]',
    B: 'text-[rgb(var(--warn))]',
    C: 'text-[rgb(var(--danger))]',
  }[r] || 'text-[rgb(var(--muted))]'

  return (
    <div className={`border border-[rgba(var(--grid),0.3)] border-l-4 ${borderColor} bg-[rgba(var(--surface),0.6)] p-6`} style={{ borderRadius: '4px' }}>
      <div className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))]">MARKET RATING</div>
      <div className="mt-4 flex items-end justify-between gap-4">
        <div className={`font-mono text-6xl font-black tabular-nums tracking-tight ${textColor}`}
          style={{ filter: r === 'A' ? 'drop-shadow(0 0 6px rgb(var(--up)))' : 'none' }}
        >{r || '-'}</div>
        <div className="font-mono text-[10px] text-[rgb(var(--muted))]">SOURCE: PM LLM</div>
      </div>
      <div className="mt-4 whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-[rgb(var(--muted))]">{basis || '(No rating basis)'}</div>
    </div>
  )
}

/* ── PM LLM Trace Panel ──────────────────────────────────── */
function PmTracePanel() {
  const [traces, setTraces] = useState([])
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState({})

  function reload() {
    setLoading(true)
    authFetch(`${getApiBase()}/api/strategy/pm-traces?limit=5`)
      .then(r => r.json())
      .then(d => { setTraces(d?.data || []); setLoading(false) })
      .catch(() => setLoading(false))
  }

  useEffect(() => { reload() }, [])

  function toggle(id, field) {
    setExpanded(prev => ({ ...prev, [id]: prev[id] === field ? null : field }))
  }

  return (
    <Panel title="PM AUDIT TRACES" right={`${traces.length} RECORDS`}>
      <div className="mb-3 flex items-center justify-between">
        <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))]">PROMPT + RAW RESPONSE</span>
        <button onClick={reload} disabled={loading}
          className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-3 py-1.5 font-mono text-[10px] text-[rgb(var(--text))] hover:bg-[rgba(var(--surface),0.5)] disabled:opacity-50"
          style={{ borderRadius: '3px' }}
        >{loading ? '...' : 'REFRESH'}</button>
      </div>

      {loading ? (
        <div className="py-6"><LoadingSpinner label="Loading traces..." /></div>
      ) : traces.length === 0 ? (
        <EmptyState icon={FileText} title="NO TRACES" description="Trigger AI review from Portfolio page" />
      ) : (
        <div className="space-y-2">
          {traces.map(t => (
            <div key={t.trace_id} className="border border-[rgba(var(--grid),0.15)] overflow-hidden" style={{ borderRadius: '2px' }}>
              <div className="flex flex-wrap items-center gap-3 bg-[rgba(var(--surface),0.4)] px-4 py-2 font-mono text-[10px] text-[rgb(var(--muted))]">
                <span className="text-[rgb(var(--text))]">{t.trace_id}</span>
                <span>{formatUnixSec(t.created_at)}</span>
                <span className="text-[rgb(var(--info))]">{t.model}</span>
                {t.latency_ms != null && <span>{t.latency_ms}ms</span>}
              </div>
              {/* Prompt */}
              <div className="border-t border-[rgba(var(--grid),0.1)]">
                <button onClick={() => toggle(t.trace_id, 'prompt')}
                  className="flex w-full items-center gap-2 px-4 py-2 text-left font-mono text-[10px] font-bold uppercase tracking-widest text-[rgb(var(--warn))] hover:bg-[rgba(var(--surface),0.2)]"
                >
                  {expanded[t.trace_id] === 'prompt' ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                  PROMPT
                </button>
                {expanded[t.trace_id] === 'prompt' && (
                  <pre className="max-h-[60vh] overflow-auto px-4 pb-4 font-mono text-[11px] leading-relaxed text-[rgb(var(--text))] whitespace-pre-wrap break-words">{t.prompt || '(empty)'}</pre>
                )}
              </div>
              {/* Response */}
              <div className="border-t border-[rgba(var(--grid),0.1)]">
                <button onClick={() => toggle(t.trace_id, 'response')}
                  className="flex w-full items-center gap-2 px-4 py-2 text-left font-mono text-[10px] font-bold uppercase tracking-widest text-[rgb(var(--up))] hover:bg-[rgba(var(--surface),0.2)]"
                >
                  {expanded[t.trace_id] === 'response' ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                  RAW RESPONSE
                </button>
                {expanded[t.trace_id] === 'response' && (
                  <pre className="max-h-[60vh] overflow-auto px-4 pb-4 font-mono text-[11px] leading-relaxed text-[rgb(var(--up))] whitespace-pre-wrap break-words">{t.response || '(empty)'}</pre>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}

/* ── Bull vs Bear Debate Panel ────────────────────────────── */
function DebatePanel() {
  const [debates, setDebates] = useState([])
  const [date, setDate] = useState('today')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    authFetch(`${getApiBase()}/api/strategy/debates?date=${date}`)
      .then(r => r.json())
      .then(d => { setDebates(d?.data || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [date])

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
          ? `${cj.recommended_action} (conf ${((cj.confidence || 0) * 100).toFixed(0)}%, ${approved ? 'AUTHORIZED' : 'BLOCKED'})`
          : null,
        summary: d.summary || null,
      }
    })
  }, [debates])

  const today = new Date().toISOString().slice(0, 10)

  return (
    <Panel title="BULL vs BEAR DEBATE">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))]">COMMITTEE DEBATE LOG</span>
        <input
          type="date"
          value={date === 'today' ? today : date}
          onChange={e => setDate(e.target.value)}
          className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)] px-3 py-1.5 font-mono text-sm text-[rgb(var(--text))] focus:border-[rgba(var(--accent),0.5)] focus:outline-none"
          style={{ borderRadius: '3px' }}
        />
      </div>

      {loading ? (
        <div className="py-6"><LoadingSpinner label="Loading debates..." /></div>
      ) : parsed.length === 0 ? (
        <EmptyState icon={Lightbulb} title="NO DEBATES" description="Trigger AI review from Portfolio page" />
      ) : (
        <div className="space-y-3">
          {parsed.map((d, i) => (
            <div key={d.id || i} className="border border-[rgba(var(--grid),0.15)] overflow-hidden" style={{ borderRadius: '2px' }}>
              {d.summary && (
                <div className="bg-[rgba(var(--surface),0.4)] px-4 py-2 font-mono text-[10px] text-[rgb(var(--muted))] border-b border-[rgba(var(--grid),0.1)]">
                  {formatUnixSec(d.timestamp)} -- {d.summary}
                </div>
              )}
              <div className="grid grid-cols-1 lg:grid-cols-3">
                {/* Bull */}
                <div className="border-l-2 border-l-[rgb(var(--up))] p-4">
                  <div className="mb-2 flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full bg-[rgb(var(--up))]" />
                    <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-[rgb(var(--up))]">BULL</span>
                  </div>
                  <p className="font-mono text-[11px] leading-relaxed text-[rgb(var(--text))]">
                    {d.bull || <span className="text-[rgb(var(--muted))]">(no data)</span>}
                  </p>
                </div>
                {/* Bear */}
                <div className="border-l-2 border-l-[rgb(var(--danger))] p-4">
                  <div className="mb-2 flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full bg-[rgb(var(--danger))]" />
                    <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-[rgb(var(--danger))]">BEAR</span>
                  </div>
                  <p className="font-mono text-[11px] leading-relaxed text-[rgb(var(--text))]">
                    {d.bear || <span className="text-[rgb(var(--muted))]">(no data)</span>}
                  </p>
                </div>
                {/* PM Decision */}
                <div className="border-l-2 border-l-[rgb(var(--info))] bg-[rgba(var(--surface),0.3)] p-4">
                  <div className="mb-2 flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full bg-[rgb(var(--info))]" />
                    <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-[rgb(var(--info))]">PM VERDICT</span>
                  </div>
                  <p className="font-mono text-[11px] font-bold leading-relaxed text-[rgb(var(--text))]">
                    {d.pm || <span className="text-[rgb(var(--muted))]">(no data)</span>}
                  </p>
                  {d.neutral && (
                    <p className="mt-2 font-mono text-[10px] leading-relaxed text-[rgb(var(--muted))]">{d.neutral}</p>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}

/* ── JSON display box ─────────────────────────────────────── */
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

  if (!text) return <div className="font-mono text-xs text-[rgb(var(--muted))]">(empty)</div>

  return (
    <pre className="max-h-[35vh] sm:max-h-[55vh] overflow-y-auto overflow-x-hidden border border-[rgba(var(--grid),0.15)] bg-[rgba(var(--surface),0.3)] p-3 font-mono text-[11px] text-[rgb(var(--text))] whitespace-pre-wrap break-all" style={{ borderRadius: '2px' }}>
      {text}
    </pre>
  )
}

/* ── Committee Context Card ───────────────────────────────── */
function CommitteeContextCard({ title, tone, content, confidence, icon }) {
  const borderMap = {
    emerald: 'border-l-[rgb(var(--up))]',
    rose: 'border-l-[rgb(var(--danger))]',
    cyan: 'border-l-[rgb(var(--info))]',
    slate: 'border-l-[rgb(var(--muted))]',
  }
  const textMap = {
    emerald: 'text-[rgb(var(--up))]',
    rose: 'text-[rgb(var(--danger))]',
    cyan: 'text-[rgb(var(--info))]',
    slate: 'text-[rgb(var(--muted))]',
  }

  return (
    <div className={`border border-[rgba(var(--grid),0.15)] border-l-2 ${borderMap[tone] || borderMap.slate} bg-[rgba(var(--surface),0.3)] p-3`} style={{ borderRadius: '2px' }}>
      <div className="flex items-center justify-between gap-3">
        <div className={`flex items-center gap-2 font-mono text-[10px] font-bold uppercase tracking-widest ${textMap[tone] || textMap.slate}`}>
          <span>{icon}</span>
          <span>{title}</span>
        </div>
        {confidence != null && confidence !== '' && (
          <span className="font-mono text-[10px] text-[rgb(var(--muted))]">CONF {Math.round(Number(confidence) * 100)}%</span>
        )}
      </div>
      <div className="mt-2 whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-[rgb(var(--text))]">
        {content || '(empty)'}
      </div>
    </div>
  )
}

function CommitteeDecisionBasis({ basis }) {
  if (!basis) return null
  const sections = [
    ['BULL POINTS', basis.bull_points],
    ['BEAR POINTS', basis.bear_points],
    ['KEY TRADEOFFS', basis.key_tradeoffs],
    ['DATA GAPS', basis.data_gaps],
  ]
  return (
    <div className="space-y-2">
      {sections.map(([label, items]) => (
        <div key={label} className="border border-[rgba(var(--grid),0.15)] bg-[rgba(var(--surface),0.2)] p-3" style={{ borderRadius: '2px' }}>
          <div className="font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">{label}</div>
          {Array.isArray(items) && items.length > 0 ? (
            <ul className="mt-2 space-y-1 font-mono text-[11px] text-[rgb(var(--text))]">
              {items.map((item, idx) => <li key={idx} className="break-words">- {item}</li>)}
            </ul>
          ) : (
            <div className="mt-2 font-mono text-[11px] text-[rgb(var(--muted))]">(no data)</div>
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
    <div className="mt-4 space-y-3">
      <div className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))]">COMMITTEE DEBATE CONTEXT</div>
      <div className="grid gap-3 lg:grid-cols-3">
        <CommitteeContextCard title="BULL ANALYST" tone="emerald" icon="^" content={ctx?.bull?.thesis} confidence={ctx?.bull?.confidence} />
        <CommitteeContextCard title="BEAR ANALYST" tone="rose" icon="v" content={ctx?.bear?.thesis} confidence={ctx?.bear?.confidence} />
        <CommitteeContextCard title={`ARBITER${ctx?.arbiter?.stance ? ` [${ctx.arbiter.stance}]` : ''}`} tone="cyan" icon="*" content={ctx?.arbiter?.summary} confidence={payload?.confidence ?? ctx?.arbiter?.raw?.confidence} />
      </div>
      <CommitteeDecisionBasis basis={ctx?.arbiter?.decision_basis} />
      <div className="border border-[rgba(var(--grid),0.15)] bg-[rgba(var(--surface),0.2)] p-3" style={{ borderRadius: '2px' }}>
        <div className="font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">COMMITTEE INPUT DATA</div>
        <pre className="mt-2 max-h-[24vh] overflow-auto whitespace-pre-wrap break-all font-mono text-[10px] leading-relaxed text-[rgb(var(--muted))]">
          {ctx?.market_data || '(no data)'}
        </pre>
      </div>
    </div>
  )
}

/* ── Duplicate Alerts ─────────────────────────────────────── */
function DuplicateAlertsSection({ payload }) {
  const alerts = Array.isArray(payload?.duplicate_alerts) ? payload.duplicate_alerts : []
  if (alerts.length === 0) return null

  return (
    <div className="mt-4 border-l-2 border-l-[rgb(var(--warn))] bg-[rgba(var(--warn),0.05)] p-4" style={{ borderRadius: '2px' }}>
      <div className="font-mono text-[10px] font-bold uppercase tracking-widest text-[rgb(var(--warn))]">DUPLICATE ALERTS</div>
      <div className="mt-3 space-y-2">
        {alerts.map((alert, idx) => (
          <div key={`${alert?.duplicate_of || 'dup'}-${idx}`} className="border border-[rgba(var(--warn),0.2)] bg-[rgba(var(--surface),0.3)] p-3 font-mono text-[11px]" style={{ borderRadius: '2px' }}>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-[rgb(var(--warn))]">
              <span>DUP_OF: {alert?.duplicate_of || '-'}</span>
              <span>SIM: {alert?.similarity ?? '-'}</span>
              <span>LOOKBACK: {alert?.lookback_hours ?? '-'}h</span>
            </div>
            {alert?.proposed_value && <div className="mt-2 break-words text-[rgb(var(--text))]">{alert.proposed_value}</div>}
            {alert?.supporting_evidence && <div className="mt-1 break-words text-[rgb(var(--muted))]">{alert.supporting_evidence}</div>}
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
        return { traceId: log?.trace_id, createdAt: log?.created_at, summary: response?.summary || '', ...alert }
      })
      .filter(Boolean)
      .slice(0, 8)
  }, [logs])

  return (
    <Panel title="DUPLICATE SUPPRESSION FEED" right={`${alerts.length} SUPPRESSED`}>
      {alerts.length === 0 ? (
        <div className="font-mono text-xs text-[rgb(var(--muted))]">No duplicate suppressions recorded.</div>
      ) : (
        <div className="space-y-2">
          {alerts.map(alert => (
            <div key={alert.traceId || `${alert.duplicate_of}-${alert.createdAt}`}
              className="border-l-2 border-l-[rgb(var(--warn))] bg-[rgba(var(--surface),0.3)] p-3" style={{ borderRadius: '2px' }}
            >
              <div className="flex flex-wrap items-center gap-3 font-mono text-[10px] text-[rgb(var(--muted))]">
                <span>{formatUnixSec(alert.createdAt) || '-'}</span>
                <span className="text-[rgb(var(--warn))]">SIM {alert.similarity ?? '-'}</span>
                <span>LOOKBACK {alert.lookback_hours ?? '-'}h</span>
                {alert.traceId && <span className="text-[rgb(var(--muted))]">{alert.traceId}</span>}
              </div>
              <div className="mt-2 break-words font-mono text-[11px] font-bold text-[rgb(var(--text))]">
                {alert.proposed_value || '(no summary)'}
              </div>
              {alert.supporting_evidence && <div className="mt-1 break-words font-mono text-[10px] text-[rgb(var(--muted))]">{alert.supporting_evidence}</div>}
              <div className="mt-2 font-mono text-[10px] text-[rgb(var(--warn))]">DUP_OF: {alert.duplicate_of || '-'}</div>
              {alert.summary && <div className="mt-1 font-mono text-[10px] text-[rgb(var(--muted))]">{alert.summary}</div>}
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}

/* ── Proposal Modal ───────────────────────────────────────── */
function ProposalModal({ open, onClose, proposal, onApprove, onReject, busy }) {
  const payload = safeJsonParse(proposal?.proposal_json || '')
  const status = String(proposal?.status || '').toLowerCase()
  const isPending = status === 'pending'

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" onMouseDown={onClose}>
      <div className="w-full max-w-4xl overflow-y-auto overflow-x-hidden border border-[rgba(var(--grid),0.4)] bg-[rgb(var(--bg))] p-5 shadow-2xl max-h-[90dvh]"
        onMouseDown={e => e.stopPropagation()} style={{ borderRadius: '4px' }}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="font-mono text-sm font-bold text-[rgb(var(--text))]">PROPOSAL DETAIL</div>
            <div className="mt-1 font-mono text-[10px] text-[rgb(var(--muted))]">
              ID: {proposal?.proposal_id || '-'} -- {formatUnixSec(proposal?.created_at) || '-'} -- <StatusTag status={proposal?.status} />
            </div>
          </div>
          <button onClick={onClose}
            className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-3 py-1.5 font-mono text-xs text-[rgb(var(--text))]"
            style={{ borderRadius: '3px' }}
          >CLOSE</button>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div className="space-y-2">
            <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">METADATA</div>
            <div className="border border-[rgba(var(--grid),0.15)] bg-[rgba(var(--surface),0.3)] p-3 font-mono text-[11px]" style={{ borderRadius: '2px' }}>
              <div className="grid grid-cols-3 gap-2">
                {[
                  ['GENERATED_BY', proposal?.generated_by],
                  ['TARGET_RULE', proposal?.target_rule],
                  ['RULE_CAT', proposal?.rule_category],
                  ['CONFIDENCE', proposal?.confidence],
                  ['DECIDED_AT', formatUnixSec(proposal?.decided_at)],
                ].map(([k, v]) => (
                  <Fragment key={k}>
                    <div className="text-[rgb(var(--muted))]">{k}</div>
                    <div className="col-span-2 break-words text-[rgb(var(--text))]">{v || '-'}</div>
                  </Fragment>
                ))}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button disabled={busy || !isPending} onClick={onApprove}
                className="border-2 border-[rgb(var(--up))] bg-[rgba(var(--up),0.1)] px-4 py-2 font-mono text-xs font-bold text-[rgb(var(--up))] disabled:opacity-40 hover:bg-[rgba(var(--up),0.2)]"
                style={{ borderRadius: '3px' }}
              >APPROVE</button>
              <button disabled={busy || !isPending} onClick={onReject}
                className="border-2 border-[rgb(var(--danger))] bg-[rgba(var(--danger),0.1)] px-4 py-2 font-mono text-xs font-bold text-[rgb(var(--danger))] disabled:opacity-40 hover:bg-[rgba(var(--danger),0.2)]"
                style={{ borderRadius: '3px' }}
              >REJECT</button>
              {!isPending && <div className="font-mono text-[10px] text-[rgb(var(--muted))]">ONLY PENDING CAN BE ACTIONED</div>}
            </div>
          </div>
          <div className="space-y-2">
            <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">PROPOSAL_JSON</div>
            <JsonBox value={payload || proposal?.proposal_json} />
          </div>
        </div>

        <CommitteeContextSection payload={payload} />
        <DuplicateAlertsSection payload={payload} />
      </div>
    </div>
  )
}

/* ── Semantic Memory Table ────────────────────────────────── */
function SemanticMemoryTable({ data }) {
  if (!data || data.length === 0) return <div className="font-mono text-xs text-[rgb(var(--muted))] py-4">(No learned rules)</div>
  return (
    <div className="overflow-auto border border-[rgba(var(--grid),0.15)]" style={{ borderRadius: '2px' }}>
      <table className="w-full text-left font-mono text-[11px]" style={{ borderCollapse: 'collapse' }}>
        <thead>
          <tr className="border-b border-[rgba(var(--grid),0.15)]">
            <th className="px-3 py-2 text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">CONF</th>
            <th className="px-3 py-2 text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">RULE KEY</th>
            <th className="px-3 py-2 text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">CONTENT</th>
            <th className="px-3 py-2 text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">UPDATED</th>
          </tr>
        </thead>
        <tbody>
          {data.map((m, idx) => (
            <tr key={m.sm_id || m.rule_key || idx} className="border-b border-[rgba(var(--grid),0.08)] hover:bg-[rgba(var(--surface),0.3)]">
              <td className="px-3 py-2 tabular-nums text-[rgb(var(--text))]">{((m.confidence || 0) * 100).toFixed(0)}%</td>
              <td className="px-3 py-2 text-[rgb(var(--accent))]">{m.rule_key || m.sm_id}</td>
              <td className="px-3 py-2 break-words text-[rgb(var(--muted))]">{m.statement || m.content_summary || ''}</td>
              <td className="px-3 py-2 text-[rgb(var(--muted))]">{formatUnixSec(m.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ── Main Page ─────────────────────────────────────────────── */
export default function StrategyPage() {
  const { proposals, logs, marketRating, semanticMemory, debates, error, loading, act, batchAct, refreshProposals, refreshLogs, refreshSemanticMemory } = useStrategyData({ pollMs: 10000 })
  const STREAM_BASE = useStreamApiBase()
  const symbolNames = useSymbolNames()

  const toast = useToast()
  const [selected, setSelected] = useState(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [pendingAct, setPendingAct] = useState(null)
  const [copiedId, setCopiedId] = useState(null)
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [batchPending, setBatchPending] = useState(null)

  const [memOrder, setMemOrder] = useState('desc')
  const [currentPage, setCurrentPage] = useState(1)
  const PAGE_SIZE = 50

  // SSE
  useEffect(() => {
    const token = getToken()
    const url = `${STREAM_BASE}/logs${token ? `?token=${token}` : ''}`
    const es = new EventSource(url)
    let t = null
    const scheduleRefresh = () => {
      if (t) clearTimeout(t)
      t = setTimeout(() => { refreshProposals(); refreshLogs() }, 500)
    }
    es.addEventListener('log', scheduleRefresh)
    es.addEventListener('error', () => {})
    return () => { if (t) clearTimeout(t); es.close() }
  }, [STREAM_BASE, refreshProposals, refreshLogs])

  useEffect(() => {
    if (refreshSemanticMemory) refreshSemanticMemory({ sort: 'confidence', order: memOrder, limit: 50 })
  }, [memOrder, refreshSemanticMemory])

  const rows = useMemo(() => {
    return (proposals || []).map(p => {
      const payload = safeJsonParse(p?.proposal_json || '') || {}
      const symbol = payload?.symbol || payload?.ticker || payload?.stock || payload?.contract || ''
      const side = payload?.side || payload?.direction || payload?.action || ''
      return { ...p, _symbol: symbol ? formatSymbol(symbol, symbolNames) : '-', _side: side || '-', _ts: formatUnixSec(p?.created_at) || '-' }
    })
  }, [proposals, symbolNames])

  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE))
  const pagedRows = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE
    return rows.slice(start, start + PAGE_SIZE)
  }, [rows, currentPage])

  useEffect(() => {
    setCurrentPage(p => {
      const maxPage = Math.max(1, Math.ceil((proposals || []).length / PAGE_SIZE))
      return p > maxPage ? 1 : p
    })
  }, [proposals])

  const openDetail = p => { setSelected(p); setModalOpen(true) }
  const closeDetail = () => { setModalOpen(false) }
  const doApprove = (p) => { if (p?.proposal_id) setPendingAct({ type: 'approve', proposal: p }) }
  const doReject = (p) => { if (p?.proposal_id) setPendingAct({ type: 'reject', proposal: p }) }

  const confirmAct = async () => {
    if (!pendingAct) return
    const { type, proposal: p } = pendingAct
    setPendingAct(null); setModalOpen(false)
    try {
      await act(type, p.proposal_id, { actor: 'operator', reason: `manual ${type} via UI` })
      toast.success(type === 'approve' ? `Proposal ${p.proposal_id} approved` : `Proposal ${p.proposal_id} rejected`)
    } catch (e) { toast.error(`Action failed: ${e?.message || e}`) }
  }

  const pendingRows = useMemo(() => pagedRows.filter(r => String(r?.status || '').toLowerCase() === 'pending'), [pagedRows])
  const allPendingSelected = pendingRows.length > 0 && pendingRows.every(r => selectedIds.has(r.proposal_id))

  const toggleSelect = (pid) => {
    setSelectedIds(prev => { const next = new Set(prev); next.has(pid) ? next.delete(pid) : next.add(pid); return next })
  }
  const toggleSelectAll = () => {
    if (allPendingSelected) setSelectedIds(new Set())
    else setSelectedIds(new Set(pendingRows.map(r => r.proposal_id)))
  }
  const confirmBatch = async () => {
    if (!batchPending) return
    const ids = [...selectedIds]; const action = batchPending.type
    setBatchPending(null)
    try {
      const result = await batchAct(action, ids, { actor: 'operator', reason: `batch ${action} via UI` })
      if (result) {
        toast.success(`Batch ${action} ${result.succeeded?.length || 0} done`)
        if (result.failed?.length) toast.warning(`${result.failed.length} skipped`)
      }
    } catch (e) { toast.error(`Batch failed: ${e?.message || e}`) }
    setSelectedIds(new Set())
  }

  useEffect(() => {
    setSelectedIds(prev => {
      if (prev.size === 0) return prev
      const validIds = new Set((proposals || []).filter(p => p.status === 'pending').map(p => p.proposal_id))
      const next = new Set([...prev].filter(id => validIds.has(id)))
      return next.size === prev.size ? prev : next
    })
  }, [proposals])

  function copyId(id) {
    navigator.clipboard.writeText(id).then(() => { setCopiedId(id); setTimeout(() => setCopiedId(null), 2000) })
  }

  return (
    <div className="space-y-4 pb-20 lg:pb-4">
      {/* ── Proposal Review Table ──────────────────────────────── */}
      <Panel title="STRATEGY PROPOSALS" right={`${rows.length} TOTAL`}>
        <div className="mb-3 font-mono text-[10px] text-[rgb(var(--muted))]">
          PENDING = actionable / APPROVED = queued / EXECUTED = filled / REJECTED = blocked. SSE auto-refresh.
        </div>

        {error && <div className="mb-3 border-l-2 border-l-[rgb(var(--danger))] bg-[rgba(var(--danger),0.05)] p-3 font-mono text-xs text-[rgb(var(--danger))]">{error}</div>}

        {/* Batch bar */}
        {selectedIds.size > 0 && (
          <div className="mb-3 flex items-center gap-3 border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)] px-4 py-2.5" style={{ borderRadius: '3px' }}>
            <span className="font-mono text-xs text-[rgb(var(--text))]">SELECTED: <span className="font-bold">{selectedIds.size}</span></span>
            <button disabled={loading.act} onClick={() => setBatchPending({ type: 'approve' })}
              className="border border-[rgb(var(--up))] bg-[rgba(var(--up),0.1)] px-3 py-1.5 font-mono text-[10px] font-bold text-[rgb(var(--up))] disabled:opacity-40"
              style={{ borderRadius: '3px' }}
            >BATCH APPROVE</button>
            <button disabled={loading.act} onClick={() => setBatchPending({ type: 'reject' })}
              className="border border-[rgb(var(--danger))] bg-[rgba(var(--danger),0.1)] px-3 py-1.5 font-mono text-[10px] font-bold text-[rgb(var(--danger))] disabled:opacity-40"
              style={{ borderRadius: '3px' }}
            >BATCH REJECT</button>
            <button onClick={() => setSelectedIds(new Set())}
              className="ml-auto font-mono text-[10px] text-[rgb(var(--muted))] hover:text-[rgb(var(--text))]"
            >CANCEL</button>
          </div>
        )}

        <div className="overflow-auto border border-[rgba(var(--grid),0.15)]" style={{ borderRadius: '2px' }}>
          <table className="min-w-full sm:min-w-[980px] w-full text-left font-mono text-xs" style={{ borderCollapse: 'collapse' }}>
            <thead>
              <tr className="border-b border-[rgba(var(--grid),0.15)]">
                <th className="px-3 py-3 w-8">
                  <input type="checkbox" checked={allPendingSelected && pendingRows.length > 0}
                    onChange={toggleSelectAll} disabled={pendingRows.length === 0}
                    className="accent-[rgb(var(--accent))] h-3.5 w-3.5" />
                </th>
                {['TIME', 'PROPOSAL ID', 'TARGET', 'SIDE', 'CONF', 'STATUS', 'ACTION'].map(h => (
                  <th key={h} className="px-4 py-3 text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pagedRows.length === 0 ? (
                <tr><td className="px-4 py-8" colSpan={8}>
                  {loading.proposals ? <LoadingSpinner label="Loading proposals..." /> : <EmptyState icon={Target} title="NO PROPOSALS" description="System will generate proposals on next trading session" />}
                </td></tr>
              ) : (
                pagedRows.map(p => {
                  const canAct = String(p?.status || '').toLowerCase() === 'pending'
                  return (
                    <tr key={p.proposal_id} className="border-b border-[rgba(var(--grid),0.08)] hover:bg-[rgba(var(--surface),0.3)]">
                      <td className="px-3 py-3">{canAct && <input type="checkbox" checked={selectedIds.has(p.proposal_id)} onChange={() => toggleSelect(p.proposal_id)} className="accent-[rgb(var(--accent))] h-3.5 w-3.5" />}</td>
                      <td className="px-4 py-3 tabular-nums text-[rgb(var(--muted))] whitespace-nowrap">{p._ts}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          <button onClick={() => openDetail(p)} className="text-[rgb(var(--text))] underline underline-offset-2 hover:text-[rgb(var(--accent))]">{p.proposal_id}</button>
                          <button onClick={e => { e.stopPropagation(); copyId(p.proposal_id) }} className="text-[rgb(var(--muted))] hover:text-[rgb(var(--text))]">
                            {copiedId === p.proposal_id ? <Check className="h-3 w-3 text-[rgb(var(--up))]" /> : <Copy className="h-3 w-3" />}
                          </button>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-[rgb(var(--text))]">{p._symbol}</td>
                      <td className="px-4 py-3 text-[rgb(var(--text))]">{p._side}</td>
                      <td className="px-4 py-3 tabular-nums text-[rgb(var(--text))]">{p.confidence ?? '-'}</td>
                      <td className="px-4 py-3"><StatusTag status={p.status} /></td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <button disabled={!canAct || loading.act} onClick={() => doApprove(p)}
                            className="border border-[rgb(var(--up))] bg-[rgba(var(--up),0.1)] px-2.5 py-1.5 text-[10px] font-bold text-[rgb(var(--up))] disabled:opacity-40"
                            style={{ borderRadius: '3px' }}
                          >APPROVE</button>
                          <button disabled={!canAct || loading.act} onClick={() => doReject(p)}
                            className="border border-[rgb(var(--danger))] bg-[rgba(var(--danger),0.1)] px-2.5 py-1.5 text-[10px] font-bold text-[rgb(var(--danger))] disabled:opacity-40"
                            style={{ borderRadius: '3px' }}
                          >REJECT</button>
                        </div>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="mt-3 flex items-center justify-between">
          <div className="font-mono text-[10px] text-[rgb(var(--muted))]">
            {rows.length} TOTAL / PAGE {currentPage}/{totalPages}
          </div>
          {totalPages > 1 && (
            <div className="flex items-center gap-1.5">
              <button disabled={currentPage <= 1} onClick={() => setCurrentPage(1)}
                className="border border-[rgba(var(--grid),0.3)] px-2 py-1 font-mono text-[10px] text-[rgb(var(--muted))] hover:bg-[rgba(var(--surface),0.3)] disabled:opacity-30" style={{ borderRadius: '3px' }}
              >{'<<'}</button>
              <button disabled={currentPage <= 1} onClick={() => setCurrentPage(p => p - 1)}
                className="border border-[rgba(var(--grid),0.3)] px-2 py-1 font-mono text-[10px] text-[rgb(var(--muted))] hover:bg-[rgba(var(--surface),0.3)] disabled:opacity-30" style={{ borderRadius: '3px' }}
              >{'<'}</button>
              {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => {
                let page
                if (totalPages <= 5) page = i + 1
                else if (currentPage <= 3) page = i + 1
                else if (currentPage >= totalPages - 2) page = totalPages - 4 + i
                else page = currentPage - 2 + i
                return (
                  <button key={page} onClick={() => setCurrentPage(page)}
                    className={`px-2.5 py-1 font-mono text-[10px] font-bold ${page === currentPage ? 'bg-[rgba(var(--accent),0.2)] text-[rgb(var(--accent))]' : 'border border-[rgba(var(--grid),0.3)] text-[rgb(var(--muted))] hover:bg-[rgba(var(--surface),0.3)]'}`}
                    style={{ borderRadius: '3px' }}
                  >{page}</button>
                )
              })}
              <button disabled={currentPage >= totalPages} onClick={() => setCurrentPage(p => p + 1)}
                className="border border-[rgba(var(--grid),0.3)] px-2 py-1 font-mono text-[10px] text-[rgb(var(--muted))] hover:bg-[rgba(var(--surface),0.3)] disabled:opacity-30" style={{ borderRadius: '3px' }}
              >{'>'}</button>
              <button disabled={currentPage >= totalPages} onClick={() => setCurrentPage(totalPages)}
                className="border border-[rgba(var(--grid),0.3)] px-2 py-1 font-mono text-[10px] text-[rgb(var(--muted))] hover:bg-[rgba(var(--surface),0.3)] disabled:opacity-30" style={{ borderRadius: '3px' }}
              >{'>>'}</button>
            </div>
          )}
        </div>
      </Panel>

      {/* ── Rating + Semantic Memory (asymmetric 4:8) ──────────── */}
      <div className="grid gap-4 lg:grid-cols-12">
        <div className="lg:col-span-4">
          <RatingCard rating={marketRating?.rating} basis={marketRating?.basis} />
        </div>
        <div className="lg:col-span-8">
          <Panel title="SEMANTIC MEMORY" right={
            <button onClick={() => setMemOrder(o => (o === 'desc' ? 'asc' : 'desc'))}
              className="font-mono text-[10px] text-[rgb(var(--accent))] hover:underline"
            >CONF {memOrder === 'desc' ? 'v HIGH' : '^ LOW'}</button>
          }>
            <div className="mb-2 font-mono text-[10px] text-[rgb(var(--muted))]">AI-learned rules, ranked by confidence from source episodes</div>
            <SemanticMemoryTable data={semanticMemory} />
          </Panel>
        </div>
      </div>

      {/* ── Proposal Modal ─────────────────────────────────────── */}
      <ProposalModal open={modalOpen} onClose={closeDetail} proposal={selected} busy={loading.act} onApprove={() => doApprove(selected)} onReject={() => doReject(selected)} />

      {/* ── Debate + Duplicates + Traces ────────────────────────── */}
      <DebatePanel />
      <DuplicateAlertFeed logs={logs} />
      <PmTracePanel />

      {/* ── Batch Confirm Dialog ────────────────────────────────── */}
      {batchPending && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" onMouseDown={() => setBatchPending(null)}>
          <div className="w-full max-w-xs border border-[rgba(var(--grid),0.4)] bg-[rgb(var(--bg))] p-5 shadow-2xl" onMouseDown={e => e.stopPropagation()} style={{ borderRadius: '4px' }}>
            <div className={`font-mono text-sm font-bold mb-2 ${batchPending.type === 'approve' ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--danger))]'}`}>
              BATCH {batchPending.type.toUpperCase()} {selectedIds.size} PROPOSALS
            </div>
            <div className="font-mono text-xs text-[rgb(var(--muted))] mb-4">This action cannot be undone.</div>
            <div className="flex gap-3">
              <button onClick={() => setBatchPending(null)}
                className="flex-1 border border-[rgba(var(--grid),0.3)] py-2.5 font-mono text-xs text-[rgb(var(--muted))] hover:bg-[rgba(var(--surface),0.4)]"
                style={{ borderRadius: '3px' }}
              >CANCEL</button>
              <button autoFocus onClick={confirmBatch}
                className={`flex-1 border-2 py-2.5 font-mono text-xs font-bold ${batchPending.type === 'approve' ? 'border-[rgb(var(--up))] bg-[rgba(var(--up),0.15)] text-[rgb(var(--up))]' : 'border-[rgb(var(--danger))] bg-[rgba(var(--danger),0.15)] text-[rgb(var(--danger))]'}`}
                style={{ borderRadius: '3px' }}
              >CONFIRM ({selectedIds.size})</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Single Confirm Dialog ──────────────────────────────── */}
      {pendingAct && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" onMouseDown={() => setPendingAct(null)}>
          <div className="w-full max-w-xs border border-[rgba(var(--grid),0.4)] bg-[rgb(var(--bg))] p-5 shadow-2xl" onMouseDown={e => e.stopPropagation()} style={{ borderRadius: '4px' }}>
            <div className={`font-mono text-sm font-bold mb-2 ${pendingAct.type === 'approve' ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--danger))]'}`}>
              CONFIRM {pendingAct.type.toUpperCase()}
            </div>
            <div className="font-mono text-[10px] text-[rgb(var(--muted))] mb-1">PROPOSAL ID</div>
            <div className="mb-4 border border-[rgba(var(--grid),0.15)] bg-[rgba(var(--surface),0.3)] px-3 py-2 font-mono text-xs text-[rgb(var(--text))] break-all" style={{ borderRadius: '2px' }}>
              {pendingAct.proposal?.proposal_id}
            </div>
            <div className="flex gap-3">
              <button onClick={() => setPendingAct(null)}
                className="flex-1 border border-[rgba(var(--grid),0.3)] py-2.5 font-mono text-xs text-[rgb(var(--muted))] hover:bg-[rgba(var(--surface),0.4)]"
                style={{ borderRadius: '3px' }}
              >CANCEL</button>
              <button autoFocus onClick={confirmAct}
                className={`flex-1 border-2 py-2.5 font-mono text-xs font-bold ${pendingAct.type === 'approve' ? 'border-[rgb(var(--up))] bg-[rgba(var(--up),0.15)] text-[rgb(var(--up))]' : 'border-[rgb(var(--danger))] bg-[rgba(var(--danger),0.15)] text-[rgb(var(--danger))]'}`}
                style={{ borderRadius: '3px' }}
              >CONFIRM</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
